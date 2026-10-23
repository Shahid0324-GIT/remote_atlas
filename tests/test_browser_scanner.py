"""Real headless-browser test, using only a local fixture and no external sites."""
import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import job_sources

@unittest.skipUnless(importlib.util.find_spec('playwright'),'Optional Playwright dependency is not installed')
class BrowserFallbackTests(unittest.TestCase):
    def test_javascript_jobs_and_bounded_load_more(self):
        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self):
                body=b'''<!doctype html><body><h1>Careers</h1><button onclick="job(2);this.remove()">Load more jobs</button><script>
                function job(id){let s=document.createElement('script');s.type='application/ld+json';s.textContent=JSON.stringify({'@type':'JobPosting',title:'Software Engineer '+id,url:'/job/'+id,description:'Python SQL Docker',jobLocationType:'TELECOMMUTE'});document.body.appendChild(s)}setTimeout(()=>job(1),100);
                </script></body>'''
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            # Local fixtures are allowed only inside this test; production still rejects private hosts.
            with patch.object(job_sources,'public_url',side_effect=lambda url:url),patch.object(job_sources,'allowed'):
                content,url=job_sources.browser_page(f'http://127.0.0.1:{server.server_port}/careers')
            jobs=job_sources.structured(job_sources.Page(content),url)
            self.assertEqual({j['title'] for j in jobs},{'Software Engineer 1','Software Engineer 2'})
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
