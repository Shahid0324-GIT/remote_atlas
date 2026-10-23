"""SQLite-backed scan queue and daily scheduling. Resume matching never uses external AI."""
import base64
import importlib.util
import io
import json
import threading
from datetime import datetime, timezone, timedelta
import job_sources
from job_matching import match, skills

DEFAULTS = {'resume_text':'','roles':'software engineer,software developer,frontend,backend,full stack,fullstack,devops,site reliability',
            'location':'India','experience_years':None,'use_browser':True,'auto_daily':False,'daily_scope':'saved'}

def now():return datetime.now(timezone.utc).isoformat()

def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS scanner_config (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS job_sources (company_id INTEGER PRIMARY KEY REFERENCES companies(id), url TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS scanner_checks (company_id INTEGER PRIMARY KEY REFERENCES companies(id), checked_at TEXT NOT NULL, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS scanner_jobs (company_id INTEGER NOT NULL REFERENCES companies(id), url TEXT NOT NULL, data TEXT NOT NULL, fetched_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(company_id,url));
      CREATE TABLE IF NOT EXISTS scan_runs (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    ''')

class Scanner:
    def __init__(self, connect, is_demo=lambda:False):
        self.connect=connect;self.is_demo=is_demo
        self.lock=threading.Lock();self.stop=threading.Event();self.worker=None
        self.shutdown=threading.Event()

    def settings(self):
        with self.connect() as db:row=db.execute('SELECT data FROM scanner_config WHERE id=1').fetchone()
        settings={**DEFAULTS,**(json.loads(row['data']) if row else {})}
        return {**settings,'detected_skills':sorted(skills(settings['resume_text'])),
                'playwright_installed':importlib.util.find_spec('playwright') is not None}

    def save_settings(self, data):
        if set(data)-set(DEFAULTS):raise ValueError('Unknown scanner setting.')
        settings={key:self.settings()[key] for key in DEFAULTS};settings.update(data)
        for key,limit in [('resume_text',60000),('roles',500),('location',100)]:
            if not isinstance(settings[key],str) or len(settings[key])>limit:raise ValueError(f'Invalid {key}.')
        if not any(v.strip() for v in settings['roles'].split(',')):raise ValueError('Enter at least one role keyword.')
        if settings['experience_years'] is not None and (type(settings['experience_years']) is not int or not 0<=settings['experience_years']<=60):raise ValueError('Experience must be between 0 and 60 years.')
        for key in ('use_browser','auto_daily'):
            if type(settings[key]) is not bool:raise ValueError('Checkbox settings must be true or false.')
        if settings['daily_scope'] not in ('saved','all'):raise ValueError('Invalid daily scan scope.')
        if settings['auto_daily'] and len(settings['resume_text'].strip())<20:raise ValueError('Save your resume before enabling daily scans.')
        with self.connect() as db:db.execute('INSERT INTO scanner_config(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(json.dumps(settings),))
        return self.settings()

    def save_source(self, data):
        company_id=data.get('company_id');url=data.get('url','')
        if type(company_id) is not int or not isinstance(url,str) or len(url)>2048:raise ValueError('Select a company and a valid careers URL.')
        url=url.strip()
        if url:job_sources.public_url(url)
        with self.connect() as db:
            if not db.execute('SELECT id FROM companies WHERE id=?',(company_id,)).fetchone():raise ValueError('Unknown company.')
            if url:db.execute('INSERT INTO job_sources(company_id,url) VALUES(?,?) ON CONFLICT(company_id) DO UPDATE SET url=excluded.url',(company_id,url))
            else:db.execute('DELETE FROM job_sources WHERE company_id=?',(company_id,))
            row=db.execute('SELECT data FROM scanner_checks WHERE company_id=?',(company_id,)).fetchone()
            if row:
                report=json.loads(row['data']);report.update(source_changed=True,status='unchecked',message='Careers source changed. Scan this company again.')
                db.execute('UPDATE scanner_checks SET data=? WHERE company_id=?',(json.dumps(report),company_id))
        return {'ok':True}

    def state(self):
        with self.connect() as db:row=db.execute('SELECT data FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()
        return json.loads(row['data']) if row else {'status':'idle','done':0,'total':0}

    def write_state(self, run_id, state):
        with self.connect() as db:db.execute('UPDATE scan_runs SET data=? WHERE id=?',(json.dumps(state),run_id))

    def start(self, data):
        if self.is_demo():raise ValueError('Job scanning and resumes are unavailable in the public demo.')
        settings=self.settings()
        if len(settings['resume_text'].strip())<20:raise ValueError('Paste or import your resume and save your preferences first.')
        scope=data.get('scope','saved');limit=data.get('limit',25);force=data.get('force',False)
        company_id=data.get('company_id')
        if company_id is not None and (type(company_id) is not int or company_id<1):raise ValueError('Select a valid company.')
        if scope not in ('saved','all') or type(limit) is not int or not 1<=limit<=735 or type(force) is not bool:raise ValueError('Invalid scan options.')
        with self.lock:
            if self.worker and self.worker.is_alive():raise ValueError('A scan is already running. Stop it before starting another.')
            with self.connect() as db:
                rows=db.execute('''SELECT c.id,c.name,c.url,c.favorite,s.url AS override_url,p.data AS profile,k.checked_at,k.data AS previous
                    FROM companies c LEFT JOIN job_sources s ON s.company_id=c.id
                    LEFT JOIN company_profiles p ON p.company_id=c.id
                    LEFT JOIN scanner_checks k ON k.company_id=c.id
                    WHERE (?='all' OR c.favorite=1) AND (? IS NULL OR c.id=?) ORDER BY COALESCE(k.checked_at,''),c.name COLLATE NOCASE LIMIT ?''',(scope,company_id,company_id,limit)).fetchall()
                companies=[]
                for row in rows:
                    company=dict(row)
                    profile=json.loads(company.pop('profile')) if company.get('profile') else {}
                    company['careers_url']=company.get('override_url') or profile.get('careers_url') or ''
                    companies.append(company)
                if not companies:raise ValueError('No bookmarked companies yet. Bookmark some companies, or choose All companies.')
                state={'status':'running','done':0,'total':len(companies),'current':'Starting…','started_at':now(),
                       'checked':0,'failed':0,'cached':0,'scope':scope}
                cursor=db.execute('INSERT INTO scan_runs(data) VALUES(?)',(json.dumps(state),));run_id=cursor.lastrowid
            self.stop.clear()
            self.worker=threading.Thread(target=self.run,args=(run_id,state,companies,settings,force),daemon=True)
            self.worker.start()
        return state

    def run(self,run_id,state,companies,settings,force):
        try:
            for company in companies:
                if self.stop.is_set():break
                state['current']=company['name'];self.write_state(run_id,state)
                cached=False
                if company.get('checked_at') and not force:
                    previous=json.loads(company['previous'])
                    ttl=24 if previous['status'] in ('checked','partial') else 4
                    cached=not previous.get('source_changed') and datetime.fromisoformat(company['checked_at'])>datetime.now(timezone.utc)-timedelta(hours=ttl)
                if cached:state['cached']+=1
                else:
                    try:result=job_sources.scan_company(company,settings['use_browser'],self.stop.is_set)
                    except Exception as error:
                        result={'status':'failed','jobs':[],'source_url':company['careers_url'] or company['url'],
                                'method':'Discovery','message':str(error) if isinstance(error,job_sources.ScanError) else 'Unexpected page format. Try a direct careers or ATS board URL.'}
                    if self.stop.is_set():break
                    timestamp=now()
                    with self.connect() as db:
                        if result['status']=='checked':db.execute('UPDATE scanner_jobs SET active=0 WHERE company_id=?',(company['id'],))
                        for job in result['jobs']:
                            db.execute('''INSERT INTO scanner_jobs(company_id,url,data,fetched_at,active) VALUES(?,?,?,?,1)
                                ON CONFLICT(company_id,url) DO UPDATE SET data=excluded.data,fetched_at=excluded.fetched_at,active=1''',
                                (company['id'],job['url'],json.dumps(job),timestamp))
                        report={key:value for key,value in result.items() if key!='jobs'}
                        report['job_count']=len(result['jobs'])
                        db.execute('INSERT INTO scanner_checks(company_id,checked_at,data) VALUES(?,?,?) ON CONFLICT(company_id) DO UPDATE SET checked_at=excluded.checked_at,data=excluded.data',
                                   (company['id'],timestamp,json.dumps(report)))
                    state['failed' if result['status']=='failed' else 'checked']+=1
                state['done']+=1;self.write_state(run_id,state)
            state.update(status='cancelled' if self.stop.is_set() else 'complete',finished_at=now(),current='')
        except Exception:
            state.update(status='failed',current='',message='The scan stopped after a local storage error. Results already saved are kept.')
        finally:self.write_state(run_id,state)

    def cancel(self):
        self.stop.set()
        return {'ok':True,'message':'Stopping after the current network request. Previously saved results are kept.'}

    def results(self):
        settings=self.settings();jobs=[];reports=[]
        with self.connect() as db:
            total=db.execute('SELECT COUNT(*) FROM scanner_jobs WHERE active=1').fetchone()[0]
            checks={row['company_id']:{**json.loads(row['data']),'checked_at':row['checked_at']} for row in db.execute('SELECT * FROM scanner_checks')}
            companies={row['id']:dict(row) for row in db.execute('SELECT c.id,c.name,c.url,s.url AS careers_url FROM companies c LEFT JOIN job_sources s ON s.company_id=c.id')}
            for row in db.execute('SELECT * FROM scanner_jobs WHERE active=1 ORDER BY fetched_at DESC LIMIT 10000'):
                job=json.loads(row['data']);matching=match(job,settings)
                if not matching['role_match']:continue
                company=companies[row['company_id']];check=checks.get(company['id'],{})
                stale=bool(check.get('source_changed')) or check.get('status')=='failed' or row['fetched_at']<check.get('checked_at','') or datetime.fromisoformat(row['fetched_at'])<datetime.now(timezone.utc)-timedelta(hours=24)
                jobs.append({**job,**matching,'description':job['description'][:1200], 'company_id':company['id'],'company_name':company['name'],
                             'fetched_at':row['fetched_at'],'stale':stale})
            for company in companies.values():
                reports.append({**company,**checks.get(company['id'],{'status':'unchecked','message':'Not scanned yet.','job_count':0})})
        jobs.sort(key=lambda job:job['score'] if job['score'] is not None else -1,reverse=True)
        return {'jobs':jobs[:3000],'companies':reports,'state':self.state(),'limited':total>10000 or len(jobs)>3000}

    def start_scheduler(self):
        # Recover an interrupted process without silently restarting its crawl.
        state=self.state()
        if state['status']=='running':
            with self.connect() as db:
                row=db.execute('SELECT id FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()
            state.update(status='interrupted',current='',message='The app stopped during the last scan. Start a new scan to continue.')
            self.write_state(row['id'],state)
        def schedule():
            while not self.shutdown.wait(60):
                if self.is_demo():continue
                try:
                    settings=self.settings();state=self.state()
                    last=datetime.fromisoformat(state['started_at']) if state.get('started_at') else None
                    if settings['auto_daily'] and (last is None or last<datetime.now(timezone.utc)-timedelta(hours=24)):
                        self.start({'scope':settings['daily_scope'],'limit':735})
                except Exception:
                    # An empty shortlist or busy scan is retried on the next scheduler tick.
                    pass
        threading.Thread(target=schedule,daemon=True).start()

def extract_resume(data):
    try:
        raw=base64.b64decode(data.get('pdf',''),validate=True)
        if len(raw)>4_000_000:raise ValueError('Resume PDF must be under 4 MB.')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:raise ValueError('This PDF is encrypted. Paste your resume text instead.')
        if len(reader.pages)>10:raise ValueError('Resume PDFs must have at most 10 pages.')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)[:60000]
        if len(text.strip())<20:raise ValueError('No readable text found. Paste resume text or use a text-based PDF.')
        return {'text':text}
    except ImportError:raise ValueError('PDF import needs pypdf. Run the scanner setup, or paste your resume text.') from None
    except ValueError:raise
    except Exception:raise ValueError('Could not read this PDF. Paste your resume text instead.') from None
