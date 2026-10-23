"""Remote Atlas: a local, dependency-free SQLite job-search workspace."""
import argparse
import csv
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('REMOTE_ATLAS_DB', str(ROOT / 'data' / 'tracker.sqlite3')))
STATUSES = ['Not started', 'Researching', 'Applied', 'Interviewing', 'Offer', 'Closed']

@contextmanager
def connect():
    connection = sqlite3.connect(DB, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
            region TEXT NOT NULL, source_page INTEGER, favorite INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Not started', notes TEXT NOT NULL DEFAULT '',
            follow_up TEXT NOT NULL DEFAULT '');
          CREATE TABLE IF NOT EXISTS clicks (
            id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
            clicked_at TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS click_company ON clicks(company_id);
        ''')
        seed = json.loads((ROOT / 'data' / 'companies.json').read_text(encoding='utf-8'))
        for company in seed:
            db.execute('''INSERT INTO companies(name,url,region,source_page)
                SELECT :name,:url,:region,:source_page WHERE NOT EXISTS
                (SELECT 1 FROM companies WHERE name=:name AND url=:url)''', company)

def catalog():
    with connect() as db:
        return [dict(row) for row in db.execute('''SELECT c.*, COUNT(k.id) AS clicks,
          MAX(k.clicked_at) AS last_visit FROM companies c LEFT JOIN clicks k ON c.id=k.company_id
          GROUP BY c.id ORDER BY c.name COLLATE NOCASE''')]

class Handler(BaseHTTPRequestHandler):
    def send(self, payload, status=200, kind='application/json; charset=utf-8', headers=None):
        body = json.dumps(payload).encode() if kind.startswith('application/json') else payload
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/companies': return self.send(catalog())
        if path == '/api/activity':
            with connect() as db:
                activity = [dict(r) for r in db.execute('SELECT k.*,c.name FROM clicks k JOIN companies c ON c.id=k.company_id ORDER BY k.id DESC LIMIT 200')]
            return self.send(activity)
        if path == '/api/export':
            output = io.StringIO(newline='')
            rows = catalog()
            writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else ['name'])
            writer.writeheader()
            for row in rows:
                # Prevent spreadsheet formula execution when opening exported text.
                writer.writerow({k: ("'" + v if isinstance(v,str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v) for k,v in row.items()})
            return self.send(output.getvalue().encode('utf-8-sig'), kind='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename="remote-atlas.csv"'})
        if path == '/api/backup':
            with connect() as db:
                data = {'version':1, 'companies':[dict(r) for r in db.execute('SELECT * FROM companies')], 'clicks':[dict(r) for r in db.execute('SELECT * FROM clicks')]}
            return self.send(json.dumps(data, indent=2).encode(), kind='application/octet-stream', headers={'Content-Disposition':'attachment; filename="remote-atlas-backup.json"'})
        assets = {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}
        if path in assets:
            kinds = {'/':'text/html', '/app.js':'text/javascript', '/style.css':'text/css'}
            return self.send((ROOT/'static'/assets[path]).read_bytes(), kind=kinds[path]+'; charset=utf-8')
        self.send({'error':'Not found'}, 404)

    def do_POST(self):
        # Mutations only accept same-origin JSON, preventing cross-site form requests.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.send({'error':'Origin rejected'}, 403)
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            return self.send({'error':'JSON required'}, 415)
        try:
            size = int(self.headers.get('Content-Length',0))
            if size > 32000: raise ValueError('Request too large')
            data = json.loads(self.rfile.read(size))
            parts = urlparse(self.path).path.strip('/').split('/')
            if len(parts) != 4 or parts[:2] != ['api','companies']: return self.send({'error':'Not found'},404)
            company_id = int(parts[2])
            with connect() as db:
                row = db.execute('SELECT * FROM companies WHERE id=?',(company_id,)).fetchone()
                if not row: return self.send({'error':'Company not found'},404)
                if parts[3] == 'visit':
                    db.execute('INSERT INTO clicks(company_id,clicked_at) VALUES(?,?)',(company_id,datetime.now(timezone.utc).isoformat()))
                    db.commit()
                    return self.send({'url':row['url']})
                if parts[3] != 'update': return self.send({'error':'Not found'},404)
                allowed = {'favorite','status','notes','follow_up'}
                if not isinstance(data,dict) or not data or set(data)-allowed: raise ValueError('Invalid fields')
                if 'status' in data and data['status'] not in STATUSES: raise ValueError('Invalid status')
                if 'favorite' in data and type(data['favorite']) not in (bool,int): raise ValueError('Invalid bookmark')
                if 'favorite' in data: data['favorite'] = int(bool(data['favorite']))
                for key in ('notes','follow_up'):
                    if key in data and (not isinstance(data[key],str) or len(data[key])>10000): raise ValueError('Invalid text')
                if data.get('follow_up'): date.fromisoformat(data['follow_up'])
                db.execute('UPDATE companies SET '+','.join(k+'=?' for k in data)+' WHERE id=?', [*data.values(),company_id])
            self.send({'ok':True})
        except (ValueError, TypeError, KeyError):
            self.send({'error':'Invalid request. Check fields and date.'},400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    initialize()
    print(f'Remote Atlas ready at http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port), Handler).serve_forever()
