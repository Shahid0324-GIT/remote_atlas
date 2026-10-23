import concurrent.futures
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class TrackerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'data')
        app.DB = Path(cls.temp.name) / 'test.sqlite3'
        app.initialize()
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, data=None, **headers):
        body = json.dumps(data).encode() if data is not None else None
        return urlopen(Request(self.base+path, data=body, headers={'Content-Type':'application/json', **headers}))

    def test_catalog_import_is_complete(self):
        rows=json.load(self.request('/api/companies'))
        self.assertEqual(len(rows), 735)
        keen=next(c for c in rows if c['name']=='Keen IO')
        self.assertEqual(keen['region'], 'Not specified')
        amazon=next(c for c in rows if c['name']=='Amazon')
        self.assertEqual(amazon['url'], 'https://www.amazon.jobs/en/locations/virtual-locations')

    def test_revisits_and_concurrent_clicks_persist(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            responses=list(executor.map(lambda _: json.load(self.request('/api/companies/1/visit',{})),range(12)))
        self.assertEqual(len(responses),12)
        app.initialize()  # Simulate startup: must not overwrite existing progress.
        row=next(c for c in json.load(self.request('/api/companies')) if c['id']==1)
        self.assertEqual(row['clicks'],12)
        history=json.load(self.request('/api/activity'))
        self.assertEqual(len(history),12)
        self.assertTrue(all(c['company_id']==1 for c in history))

    def test_notes_pipeline_and_exports(self):
        notes='<script>alert(1)</script>\n=2+2'
        json.load(self.request('/api/companies/2/update',{'notes':notes,'favorite':True,'status':'Applied','follow_up':'2026-10-23'}))
        app.initialize()
        row=next(c for c in json.load(self.request('/api/companies')) if c['id']==2)
        self.assertEqual((row['notes'],row['favorite'],row['status'],row['follow_up']),(notes,1,'Applied','2026-10-23'))
        backup=json.load(self.request('/api/backup'))
        self.assertEqual(backup['version'],1)
        self.assertEqual(len(backup['companies']),735)
        json.load(self.request('/api/companies/2/update',{'notes':'=2+2'}))
        exported=self.request('/api/export').read().decode('utf-8-sig')
        self.assertIn("'=2+2",exported)

    def test_invalid_mutations_do_not_write(self):
        for data in ({'status':'Invalid'},{'follow_up':'not-a-date'},{'url':'https://example.com'},{'notes':None}):
            with self.assertRaises(HTTPError) as caught:self.request('/api/companies/3/update',data)
            self.assertEqual(caught.exception.code,400)
        with self.assertRaises(HTTPError) as caught:self.request('/api/companies/3/visit',{},Origin='https://example.com')
        self.assertEqual(caught.exception.code,403)
        with self.assertRaises(HTTPError) as caught:self.request('/api/companies/99999/visit',{})
        self.assertEqual(caught.exception.code,404)

if __name__=='__main__': unittest.main()
