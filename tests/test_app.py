import concurrent.futures
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
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
        cls.original_env_file = app.ai_profiles.ENV_FILE
        app.ai_profiles.ENV_FILE = Path(cls.temp.name) / '.env'
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
        app.ai_profiles.ENV_FILE = cls.original_env_file
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
        self.assertEqual(len([c for c in history if c['company_id']==1]),12)

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

    def test_ai_settings_never_return_the_key(self):
        secret='gsk_'+'testsecret'*4
        result=json.load(self.request('/api/ai/settings',{'key':secret,'model':'openai/gpt-oss-20b'}))
        self.assertTrue(result['configured'])
        self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn(secret,self.request('/api/ai/settings').read().decode())
        self.assertNotIn(secret,self.request('/api/backup').read().decode())
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/ai/settings',{'key':'bad-key','model':'openai/gpt-oss-20b'})
        self.assertEqual(caught.exception.code,400)
        caught.exception.close()

    def test_ai_research_toggle_blocks_fetching_but_keeps_cached_profiles(self):
        saved={'summary':'Saved before research was disabled'}
        with app.connect() as db:
            db.execute('INSERT INTO company_profiles(company_id,data) VALUES(?,?)',(15,json.dumps(saved)))
        try:
            result=json.load(self.request('/api/ai/preferences',{'enabled':False}))
            self.assertFalse(result['enabled'])
            app.initialize()
            self.assertFalse(json.load(self.request('/api/ai/settings'))['enabled'])
            self.assertEqual(json.load(self.request('/api/companies/15/profile'))['profile'],saved)
            with patch.object(app.ai_profiles,'research') as research:
                cached=json.load(self.request('/api/companies/15/research',{}))
                self.assertTrue(cached['cached'])
                for company_id,request_data in ((15,{'refresh':True}),(16,{})):
                    with self.assertRaises(HTTPError) as caught:
                        self.request(f'/api/companies/{company_id}/research',request_data)
                    self.assertEqual(caught.exception.code,403)
                    caught.exception.close()
                research.assert_not_called()
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/ai/preferences',{'enabled':'false'})
            self.assertEqual(caught.exception.code,400)
            caught.exception.close()
        finally:
            json.load(self.request('/api/ai/preferences',{'enabled':True}))

    def test_shared_demo_disables_ai_and_allows_https_tracking(self):
        with patch.object(app,'DEMO_MODE',True), patch.object(app.ai_profiles,'research') as research:
            settings=json.load(self.request('/api/ai/settings'))
            self.assertTrue(settings['demo'])
            self.assertFalse(settings['configured'])
            self.assertFalse(settings['enabled'])
            for path, data in (('/api/ai/settings',{'key':'no'}),('/api/ai/preferences',{'enabled':True}),('/api/companies/30/research',{})):
                with self.assertRaises(HTTPError) as caught:self.request(path,data)
                self.assertEqual(caught.exception.code,403)
                caught.exception.close()
            research.assert_not_called()
            self.assertIn('Shared demo',self.request('/').read().decode())
            response=json.load(self.request('/api/companies/31/update',{'favorite':True},Host='demo.example',Origin='https://demo.example'))
            self.assertTrue(response['ok'])
            with self.assertRaises(HTTPError) as caught:self.request('/api/scanner/settings')
            self.assertEqual(caught.exception.code,403)
            caught.exception.close()
            with self.assertRaises(HTTPError) as caught:self.request('/api/scanner/start',{})
            self.assertEqual(caught.exception.code,403)
            caught.exception.close()

    def test_scanner_http_settings_resume_privacy_and_job_visits(self):
        resume='A software developer with Python SQL and Docker project experience.'
        settings=json.load(self.request('/api/scanner/settings',{'resume_text':resume,'roles':'engineer,developer','use_browser':False}))
        self.assertEqual(settings['detected_skills'],['Docker','Python','SQL'])
        self.assertNotIn(resume,self.request('/api/companies').read().decode())
        job={'title':'Software Engineer','url':'https://example.com/position','description':'Python SQL','location':'Remote India','remote':True,'source':'Test feed'}
        with app.connect() as db:
            db.execute('INSERT INTO scanner_jobs(company_id,url,data,fetched_at) VALUES(?,?,?,?)',(17,job['url'],json.dumps(job),app.job_scanner.now()))
        response=json.load(self.request('/api/scanner/results'))
        self.assertEqual(next(j for j in response['jobs'] if j['company_id']==17)['score'],100)
        visit=json.load(self.request('/api/companies/17/visit',{'kind':'job','url':job['url']}))
        self.assertEqual(visit['url'],job['url'])
        with self.assertRaises(HTTPError) as caught:self.request('/api/companies/17/visit',{'kind':'job','url':'https://other.example'})
        self.assertEqual(caught.exception.code,400)
        caught.exception.close()

    def test_company_research_cache_refresh_and_failure(self):
        self.assertIsNone(json.load(self.request('/api/companies/10/profile'))['profile'])
        profile={'summary':'A researched company','careers_url':'https://example.com/careers','sources':[{'title':'Official','url':'https://example.com'}]}
        with patch.object(app.ai_profiles,'research',return_value=profile) as research:
            first=json.load(self.request('/api/companies/10/research',{}))
            self.assertFalse(first['cached'])
            cached=json.load(self.request('/api/companies/10/research',{}))
            self.assertTrue(cached['cached'])
            self.assertEqual(research.call_count,1)
            identity=research.call_args.args[0]
            self.assertEqual(set(identity),{'name','url'})
        app.initialize()
        self.assertEqual(json.load(self.request('/api/companies/10/profile'))['profile'],profile)
        visit=json.load(self.request('/api/companies/10/visit',{'kind':'careers'}))
        self.assertEqual(visit['url'],'https://example.com/careers')
        with self.assertRaises(HTTPError) as missing:self.request('/api/companies/11/visit',{'kind':'careers'})
        self.assertEqual(missing.exception.code,400)
        missing.exception.close()
        with patch.object(app.ai_profiles,'research',side_effect=app.ai_profiles.ResearchError('Rate limit',429)):
            with self.assertRaises(HTTPError) as caught:self.request('/api/companies/10/research',{'refresh':True})
            self.assertEqual(caught.exception.code,429)
            caught.exception.close()
        self.assertEqual(json.load(self.request('/api/companies/10/profile'))['profile'],profile)
        self.assertNotIn(10,app.RESEARCHING)

    def test_research_deduplicates_simultaneous_requests(self):
        started=threading.Event()
        release=threading.Event()
        def research(company):
            started.set()
            release.wait(5)
            return {'summary':'Complete'}
        with patch.object(app.ai_profiles,'research',side_effect=research):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(lambda:json.load(self.request('/api/companies/12/research',{})))
                self.assertTrue(started.wait(3))
                try:
                    with self.assertRaises(HTTPError) as caught:self.request('/api/companies/12/research',{})
                    self.assertEqual(caught.exception.code,409)
                    caught.exception.close()
                finally:release.set()
                self.assertEqual(pending.result()['profile']['summary'],'Complete')

if __name__=='__main__': unittest.main()
