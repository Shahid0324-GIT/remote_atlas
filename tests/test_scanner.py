import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import job_matching as matching
import job_sources as sources
import job_scanner

class MatchingTests(unittest.TestCase):
    def test_skill_boundaries_and_transparent_scores(self):
        self.assertNotIn('Java',matching.skills('JavaScript, React, GitHub and HTML'))
        self.assertNotIn('Git',matching.skills('GitHub'))
        self.assertIn('C++',matching.skills('C++ developer'))
        job={'title':'Backend Software Engineer','description':'Python SQL Docker. 5+ years of experience.','location':'Remote, USA'}
        prefs={**job_scanner.DEFAULTS,'resume_text':'Python SQL developer with two years experience','experience_years':2}
        result=matching.match(job,prefs)
        self.assertEqual(result['score'],67)
        self.assertEqual(result['matched_skills'],['Python','SQL'])
        self.assertEqual(result['missing_skills'],['Docker'])
        self.assertEqual(result['location_signal'],'Check eligibility')
        self.assertTrue(result['experience_warning'])
        self.assertIsNone(matching.match({'title':'Software Engineer'},prefs)['score'])
        self.assertEqual(matching.match({**job,'description':'3-5 years in software development. Python'},prefs)['minimum_years'],3)

class SourceTests(unittest.TestCase):
    def test_providers_and_embed_boards(self):
        self.assertEqual(sources.board('https://boards.greenhouse.io/embed/job_board?for=example'),('Greenhouse','example',''))
        self.assertEqual(sources.board('https://jobs.eu.lever.co/example'),('Lever','example','eu'))
        self.assertEqual(sources.board('https://jobs.ashbyhq.com/example'),('Ashby','example',''))
        self.assertIsNone(sources.board('https://jobs.lever.co.evil.example/company'))

    def test_all_feed_adapters(self):
        fixtures=[(('Greenhouse','example',''),{'jobs':[{'title':'Software Engineer','absolute_url':'https://example.com/1','content':'Python &amp; SQL','location':{'name':'Remote - India'}}]}),
                  (('Lever','example',''),[{'text':'Backend Developer','hostedUrl':'https://example.com/2','descriptionPlain':'Python','categories':{'location':'Remote'},'workplaceType':'remote','lists':[{'content':'<p>SQL</p>'}]}]),
                  (('Ashby','example',''),{'jobs':[{'title':'Frontend Developer','jobUrl':'https://example.com/3','descriptionPlain':'React','location':'India','isRemote':True,'isListed':True}]})]
        for info,payload in fixtures:
            with self.subTest(provider=info[0]),patch.object(sources,'request',return_value=(json.dumps(payload),'https://api.example.com')):
                jobs,_=sources.feed_jobs(info)
                self.assertEqual(len(jobs),1)
                self.assertTrue(jobs[0]['remote'])
                self.assertNotIn('<p>',jobs[0]['description'])

    def test_discovery_uses_observed_provider_url(self):
        content='<a href="https://jobs.lever.co/actual-tenant">Careers</a>'
        with patch.object(sources,'public_url',side_effect=lambda url:url),patch.object(sources,'allowed'),patch.object(sources,'request',return_value=(content,'https://example.com')),patch.object(sources,'feed_jobs',return_value=([],'endpoint')) as feed:
            result=sources.scan_company({'url':'https://example.com','name':'Unrelated Brand'})
        self.assertEqual(result['status'],'checked')
        self.assertEqual(result['jobs'],[])
        feed.assert_called_once_with(('Lever','actual-tenant',''))

    def test_empty_page_is_not_reported_as_no_openings(self):
        with patch.object(sources,'public_url',side_effect=lambda url:url),patch.object(sources,'allowed'),patch.object(sources,'request',return_value=('<p>No structured listings here</p>','https://example.com')):
            result=sources.scan_company({'url':'https://example.com'})
        self.assertEqual(result['status'],'failed')

    def test_html_job_pages_require_a_matching_heading(self):
        listing=sources.Page('<a href="/careers/backend-engineer">Backend Engineer</a><a href="/blog/software-engineer">Software Engineer</a>')
        self.assertEqual(sources.html_job_links(listing,'https://example.com'),[('https://example.com/careers/backend-engineer','Backend Engineer')])
        detail=sources.Page('<h1>Backend Engineer</h1><p>Python SQL. Apply below.</p>')
        self.assertIsNotNone(sources.html_job(detail,'https://example.com/careers/backend-engineer','Backend Engineer'))
        self.assertIsNone(sources.html_job(detail,'https://example.com/careers/backend-engineer','Other title'))
        closed=sources.Page('<h1>Backend Engineer</h1><p>This position has been filled.</p>')
        self.assertIsNone(sources.html_job(closed,'https://example.com/careers/backend-engineer','Backend Engineer'))

    def test_malformed_feed_is_not_reported_as_zero_jobs(self):
        with patch.object(sources,'request',return_value=(json.dumps({'jobs':[{'unexpected':'format'}]}),'endpoint')):
            with self.assertRaises(sources.ScanError):sources.feed_jobs(('Greenhouse','example',''))

    def test_structured_jobs_and_expired_jobs(self):
        objects=[{'@type':'JobPosting','title':'Backend Developer','description':'<p>Python</p>','url':'/job/1','jobLocationType':'TELECOMMUTE','applicantLocationRequirements':{'name':'India'}},
                 {'@type':'JobPosting','title':'Expired','validThrough':'2000-01-01','url':'/job/old'}]
        parsed=sources.Page('<script type="application/ld+json">'+json.dumps({'@graph':objects})+'</script>')
        jobs=sources.structured(parsed,'https://example.com/careers')
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['url'],'https://example.com/job/1')
        self.assertEqual(jobs[0]['location'],'India')

    def test_private_addresses_and_redirects_are_blocked(self):
        with patch.object(sources.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(sources.ScanError):sources.public_url('https://example.com')
        for url in ('file:///secret','http://user:pass@example.com','https://example.com:8000'):
            with self.assertRaises(sources.ScanError):sources.public_url(url)

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data')
        self.previous_db=app.DB;app.DB=Path(self.temp.name)/'scanner.sqlite3';app.initialize()
        self.scanner=job_scanner.Scanner(app.connect)
        self.scanner.save_settings({'resume_text':'A software engineer experienced with Python and SQL.'})
        self.job={'title':'Software Engineer','url':'https://example.com/job/1','description':'Python SQL Docker','location':'India','remote':True,'source':'Greenhouse'}

    def tearDown(self):
        self.scanner.stop.set()
        if self.scanner.worker:self.scanner.worker.join(3)
        app.DB=self.previous_db;self.temp.cleanup()

    def scan(self,result,force=False):
        with patch.object(sources,'scan_company',return_value=result) as fetch:
            self.scanner.start({'scope':'all','company_id':1,'limit':1,'force':force})
            self.scanner.worker.join(4)
            self.assertFalse(self.scanner.worker.is_alive())
            return fetch

    def test_cache_failed_refresh_and_resume_rematching(self):
        success={'status':'checked','jobs':[self.job],'source_url':'https://example.com/careers','method':'Greenhouse','message':'1 published job'}
        fetch=self.scan(success)
        self.assertNotIn('resume_text',fetch.call_args.args[0])
        self.assertEqual(self.scanner.results()['jobs'][0]['score'],67)
        cached=self.scan(success)
        cached.assert_not_called()
        self.scanner.save_settings({'resume_text':'Software engineer with Python SQL and Docker experience'})
        self.assertEqual(self.scanner.results()['jobs'][0]['score'],100)
        self.scan({**success,'status':'failed','jobs':[],'message':'Blocked'},True)
        self.assertTrue(self.scanner.results()['jobs'][0]['stale'])
        self.assertEqual(self.scanner.state()['status'],'complete')
        self.scan({**success,'jobs':[],'message':'No openings'},True)
        self.assertEqual(self.scanner.results()['jobs'],[])

    def test_demo_and_validation(self):
        with self.assertRaises(ValueError):self.scanner.save_settings({'experience_years':-1})
        with self.assertRaises(ValueError):self.scanner.start({'scope':'saved','limit':1})
        with self.assertRaises(ValueError):job_scanner.Scanner(app.connect,lambda:True).start({})
        self.scanner.save_settings({'resume_text':''})
        with self.assertRaises(ValueError):self.scanner.start({'scope':'all','limit':1})

    def test_cancel_and_changed_sources(self):
        success={'status':'checked','jobs':[self.job],'source_url':'https://example.com','method':'Greenhouse','message':'OK'}
        self.scan(success)
        with patch.object(sources,'public_url',side_effect=lambda url:url):self.scanner.save_source({'company_id':1,'url':'https://example.com/new'})
        self.assertTrue(self.scanner.results()['jobs'][0]['stale'])
        self.scan(success).assert_called_once()
        def cancel(company,*args):
            self.scanner.cancel()
            return success
        with patch.object(sources,'scan_company',side_effect=cancel):
            self.scanner.start({'scope':'all','limit':1,'force':True})
            self.scanner.worker.join(3)
        self.assertEqual(self.scanner.state()['status'],'cancelled')

if __name__=='__main__':unittest.main()
