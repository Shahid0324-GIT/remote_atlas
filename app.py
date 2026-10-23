"""Remote Atlas: a local, dependency-free SQLite job-search workspace."""
import argparse
import csv
import io
import json
import os
import sqlite3
import threading
import ai_profiles
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('REMOTE_ATLAS_DB', str(ROOT / 'data' / 'tracker.sqlite3')))
STATUSES = ['Not started', 'Researching', 'Applied', 'Interviewing', 'Offer', 'Closed']
RESEARCH_SLOTS = threading.BoundedSemaphore(2)
RESEARCH_LOCK = threading.Lock()
RESEARCHING = set()
SETTINGS_LOCK = threading.Lock()

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
          CREATE TABLE IF NOT EXISTS company_profiles (
            company_id INTEGER PRIMARY KEY REFERENCES companies(id), data TEXT NOT NULL);
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
        if path == '/api/ai/settings': return self.send(ai_profiles.public_configuration())
        parts = path.strip('/').split('/')
        if len(parts) == 4 and parts[:2] == ['api','companies'] and parts[3] == 'profile':
            try: company_id = int(parts[2])
            except ValueError: return self.send({'error':'Invalid company'},400)
            with connect() as db:
                if not db.execute('SELECT id FROM companies WHERE id=?',(company_id,)).fetchone():
                    return self.send({'error':'Company not found'},404)
                row = db.execute('SELECT data FROM company_profiles WHERE company_id=?',(company_id,)).fetchone()
            return self.send({'profile': json.loads(row['data']) if row else None})
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
                data = {'version':1, 'companies':[dict(r) for r in db.execute('SELECT * FROM companies')], 'clicks':[dict(r) for r in db.execute('SELECT * FROM clicks')],
                        'profiles':[{'company_id':r['company_id'],'profile':json.loads(r['data'])} for r in db.execute('SELECT * FROM company_profiles')]}
            return self.send(json.dumps(data, indent=2).encode(), kind='application/octet-stream', headers={'Content-Disposition':'attachment; filename="remote-atlas-backup.json"'})
        assets = {'/':'index.html', '/app.js':'app.js', '/profile.js':'profile.js', '/style.css':'style.css'}
        if path in assets:
            kinds = {'/':'text/html', '/app.js':'text/javascript', '/profile.js':'text/javascript', '/style.css':'text/css'}
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
            if size < 0 or size > 32000: raise ValueError('Request too large')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data,dict): raise ValueError('Object required')
            if urlparse(self.path).path == '/api/ai/settings':
                with SETTINGS_LOCK:
                    result = ai_profiles.save_configuration(data)
                return self.send(result)
            parts = urlparse(self.path).path.strip('/').split('/')
            if len(parts) != 4 or parts[:2] != ['api','companies']: return self.send({'error':'Not found'},404)
            company_id = int(parts[2])
            if parts[3] == 'research': return self.research_company(company_id, data)
            with connect() as db:
                row = db.execute('SELECT * FROM companies WHERE id=?',(company_id,)).fetchone()
                if not row: return self.send({'error':'Company not found'},404)
                if parts[3] == 'visit':
                    destination = row['url']
                    if data.get('kind') == 'careers':
                        saved = db.execute('SELECT data FROM company_profiles WHERE company_id=?',(company_id,)).fetchone()
                        destination = ai_profiles.safe_url(json.loads(saved['data']).get('careers_url')) if saved else ''
                        if not destination: return self.send({'error':'No researched careers page is available yet.'},400)
                    db.execute('INSERT INTO clicks(company_id,clicked_at) VALUES(?,?)',(company_id,datetime.now(timezone.utc).isoformat()))
                    db.commit()
                    return self.send({'url':destination})
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
        except ai_profiles.ResearchError as error:
            self.send({'error':str(error)},error.status)
        except OSError:
            self.send({'error':'Could not save local settings. Check folder permissions.'},500)

    def research_company(self, company_id, data):
        if type(data.get('refresh',False)) is not bool: raise ValueError('Invalid refresh')
        with connect() as db:
            company = db.execute('SELECT name,url FROM companies WHERE id=?',(company_id,)).fetchone()
            if not company: return self.send({'error':'Company not found'},404)
            cached = db.execute('SELECT data FROM company_profiles WHERE company_id=?',(company_id,)).fetchone()
        if cached and not data.get('refresh'):
            return self.send({'profile':json.loads(cached['data']), 'cached':True})
        with RESEARCH_LOCK:
            if company_id in RESEARCHING:
                return self.send({'error':'This company is already being researched. Reopen its profile shortly.'},409)
            if not RESEARCH_SLOTS.acquire(blocking=False):
                return self.send({'error':'Two company profiles are being researched. Try again once one finishes.'},429)
            RESEARCHING.add(company_id)
        try:
            profile = ai_profiles.research(dict(company))
            with connect() as db:
                db.execute('INSERT INTO company_profiles(company_id,data) VALUES(?,?) ON CONFLICT(company_id) DO UPDATE SET data=excluded.data',
                           (company_id,json.dumps(profile)))
            return self.send({'profile':profile, 'cached':False})
        finally:
            with RESEARCH_LOCK: RESEARCHING.discard(company_id)
            RESEARCH_SLOTS.release()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--open-browser', action='store_true', help='Open the app in your default browser')
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(('127.0.0.1',args.port), Handler)
    except OSError:
        print(f'Port {args.port} is already in use. If Remote Atlas is running, open http://127.0.0.1:{args.port}. Otherwise use --port 8001.', flush=True)
        raise SystemExit(1)
    initialize()
    print(f'Remote Atlas ready at http://127.0.0.1:{args.port}', flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nRemote Atlas stopped. Your progress is saved.')
    finally:
        server.server_close()
