"""Bounded public-feed discovery, HTML/JSON-LD parsing and optional Playwright fallback."""
import html
import ipaddress
import json
import os
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin, parse_qs, quote, urlunparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser
from pathlib import Path

USER_AGENT = 'RemoteAtlasJobScanner/1.0'
MAX_BYTES = 5_000_000
ROBOTS = {}
LAST_HOST = {}

class ScanError(Exception): pass

def public_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        if parsed.port not in (None,80,443): raise ValueError()
        addresses = socket.getaddrinfo(parsed.hostname,parsed.port or 443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            raise ValueError()
        return url
    except (ValueError,OSError):
        raise ScanError('URL is invalid, unreachable, or does not point to a public website.') from None

class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def request(url, robots=False):
    public_url(url)
    host=urlparse(url).netloc
    delay=0.6-(time.monotonic()-LAST_HOST.get(host,0))
    if delay>0:time.sleep(delay)
    LAST_HOST[host]=time.monotonic()
    try:
        with build_opener(PublicRedirect()).open(Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/json,text/html;q=0.9'}),timeout=12) as response:
            data=response.read(MAX_BYTES+1)
            if len(data)>MAX_BYTES:raise ScanError('Page is too large to scan safely.')
            return data.decode('utf-8',errors='replace'),response.geturl()
    except ScanError:raise
    except Exception as error:
        code=getattr(error,'code',None)
        if code in (401,403,429):raise ScanError(f'Website restricted automated access (HTTP {code}). Use the manual careers link.') from None
        raise ScanError(f'Website could not be fetched{f" (HTTP {code})" if code else ""}.') from None

def allowed(url):
    public_url(url)
    p=urlparse(url)
    origin=f'{p.scheme}://{p.netloc}'
    if origin not in ROBOTS:
        parser=RobotFileParser()
        try:
            text,_=request(origin+'/robots.txt',robots=True)
            parser.parse(text.splitlines())
        except ScanError as error:
            if 'HTTP 404' in str(error):parser.parse([])
            else:raise ScanError('Could not verify robots.txt permissions. Use the manual careers link.') from None
        ROBOTS[origin]=parser
    if not ROBOTS[origin].can_fetch(USER_AGENT,url):
        raise ScanError('This page disallows automated scanning in robots.txt.')

class Page(HTMLParser):
    def __init__(self,content):
        super().__init__(convert_charrefs=True)
        self.links=[]; self.scripts=[]; self.text=[]; self.current=None; self.link=None; self.skip=0; self.headings=[]; self.heading=None
        self.feed(content)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':
            self.current=[] if 'ld+json' in attrs.get('type','') else None
            self.skip+=1
        if tag=='style':self.skip+=1
        if tag=='a':self.link=[attrs.get('href',''),'']
        if tag=='h1':self.heading=[]
        if tag in ('iframe',) and attrs.get('src'):self.links.append((attrs['src'],'embedded frame'))
    def handle_endtag(self,tag):
        if tag=='script':
            if self.current is not None:self.scripts.append(''.join(self.current))
            self.current=None;self.skip=max(0,self.skip-1)
        if tag=='style':self.skip=max(0,self.skip-1)
        if tag=='a' and self.link:self.links.append(tuple(self.link));self.link=None
        if tag=='h1' and self.heading is not None:self.headings.append(''.join(self.heading));self.heading=None
    def handle_data(self,data):
        if self.current is not None:self.current.append(data)
        if not self.skip:self.text.append(data)
        if self.link:self.link[1]+=data
        if self.heading is not None:self.heading.append(data)

def plain(value):
    return ' '.join(Page(html.unescape(html.unescape(str(value or '')))).text)[:45000]

def board(url):
    p=urlparse(url); host=(p.hostname or '').lower(); parts=[v for v in p.path.split('/') if v]
    if host in ('boards.greenhouse.io','job-boards.greenhouse.io'):
        token=parse_qs(p.query).get('for',[None])[0] if parts and parts[0]=='embed' else (parts[0] if parts else None)
        if token:return ('Greenhouse',token,'')
    if host in ('jobs.lever.co','jobs.eu.lever.co') and parts:return ('Lever',parts[0],'eu' if '.eu.' in host else '')
    if host=='jobs.ashbyhq.com' and parts:return ('Ashby',parts[0],'')
    return None

def normalized(title,url,location,description,source,remote=None):
    if not title or not url:return None
    try:
        p=urlparse(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:return None
    except ValueError:return None
    return {'title':plain(title)[:300],'url':url[:2048],'location':plain(location)[:500],
            'description':plain(description),'source':source,'remote':remote}

def feed_jobs(info):
    source,token,region=info
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',token):raise ScanError('Invalid job-board identifier.')
    token=quote(token,safe='')
    endpoint={'Greenhouse':f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true',
              'Lever':f'https://api{ ".eu" if region else ""}.lever.co/v0/postings/{token}?mode=json',
              'Ashby':f'https://api.ashbyhq.com/posting-api/job-board/{token}'}[source]
    raw,_=request(endpoint)
    try:data=json.loads(raw)
    except ValueError:raise ScanError('Job feed did not return valid JSON.') from None
    if source in ('Greenhouse','Ashby'):
        if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):raise ScanError('Unrecognized job-feed format.')
        entries=data['jobs']
    else:
        if not isinstance(data,list):raise ScanError('Unrecognized job-feed format.')
        entries=data
    if len(entries)>5000:raise ScanError('Job board exceeds the scan limit; narrow it with a careers page.')
    jobs=[]
    for j in entries:
        if not isinstance(j,dict):continue
        if source=='Greenhouse':
            loc=(j.get('location') or {}).get('name','')
            job=normalized(j.get('title'),j.get('absolute_url'),loc,j.get('content',''),source,
                           True if 'remote' in loc.lower() else None)
        elif source=='Lever':
            loc=(j.get('categories') or {}).get('location','')
            desc=(j.get('descriptionPlain') or j.get('description',''))+' '+ ' '.join(str(v.get('content','')) for v in j.get('lists',[]) if isinstance(v,dict))
            job=normalized(j.get('text'),j.get('hostedUrl'),loc,desc,source,
                           True if j.get('workplaceType')=='remote' or 'remote' in loc.lower() else False if j.get('workplaceType') in ('on-site','hybrid') else None)
        else:
            if j.get('isListed') is False:continue
            loc=j.get('location','')+'; '+ '; '.join(v.get('location','') for v in j.get('secondaryLocations',[]) if isinstance(v,dict))
            job=normalized(j.get('title'),j.get('jobUrl'),loc,j.get('descriptionPlain') or j.get('descriptionHtml',''),source,j.get('isRemote'))
        if job:jobs.append(job)
    only_unlisted=source=='Ashby' and all(isinstance(j,dict) and j.get('isListed') is False for j in entries)
    if entries and not jobs and not only_unlisted:raise ScanError('The feed contained listings but their format could not be parsed. Check the careers page manually.')
    return jobs,endpoint

def structured(page,url):
    jobs=[]
    def walk(value):
        if isinstance(value,list):
            for item in value:walk(item)
        elif isinstance(value,dict):
            if value.get('@type')=='JobPosting' or 'JobPosting' in (value.get('@type') if isinstance(value.get('@type'),list) else []):
                locations=value.get('jobLocation',[])
                if not isinstance(locations,list):locations=[locations]
                loc=[]
                for location in locations:
                    address=location.get('address',{}) if isinstance(location,dict) else {}
                    if isinstance(address,str):loc.append(address)
                    elif isinstance(address,dict):loc.append(', '.join(str(address.get(k,'')) for k in ('addressLocality','addressRegion','addressCountry') if address.get(k)))
                remote=True if value.get('jobLocationType')=='TELECOMMUTE' else None
                restrictions=value.get('applicantLocationRequirements',[])
                if isinstance(restrictions,dict):restrictions=[restrictions]
                loc.extend(str(v.get('name','')) for v in restrictions if isinstance(v,dict))
                valid_until=str(value.get('validThrough',''))
                from datetime import datetime,timezone
                if valid_until:
                    try:
                        expires=datetime.fromisoformat(valid_until.replace('Z','+00:00'))
                        if expires.replace(tzinfo=expires.tzinfo or timezone.utc)<datetime.now(timezone.utc):return
                    except ValueError:pass
                job=normalized(value.get('title'),urljoin(url,value.get('url') or url),'; '.join(loc),value.get('description',''),'Careers page',remote)
                if job:jobs.append(job)
            for child in value.values():
                if isinstance(child,(dict,list)):walk(child)
    for script in page.scripts:
        try:walk(json.loads(script))
        except (ValueError,RecursionError):continue
    return jobs

def html_job_links(page, base):
    return [(urljoin(base,href),plain(text)) for href,text in page.links
            if re.search(r'\b(engineer|developer|analyst|designer|architect|scientist|programmer)\b',text,re.I)
            and re.search(r'/(jobs?|careers?|positions?|openings?)/[^/?#]+',urlparse(urljoin(base,href)).path,re.I)
            and not re.search(r'/apply(?:/|$)',urlparse(href).path,re.I)]

def html_job(page,url,title):
    if not any(plain(h).strip().casefold()==title.strip().casefold() for h in page.headings):return None
    text=' '.join(page.text)
    if re.search(r'position has been filled|no longer accepting applications|this job is no longer available|job is closed',text,re.I):return None
    return normalized(title,url,'',text,'HTML job page',True if re.search(r'\bremote\b',title,re.I) else None)

def browser_page(url):
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(Path(__file__).resolve().parent/'.local-tools'/'pw-browsers'))
    try:from playwright.sync_api import sync_playwright
    except ImportError:raise ScanError('Playwright is not installed. Run the scanner setup command shown in Matching jobs.') from None
    with sync_playwright() as pw:
        try:browser=pw.chromium.launch(headless=True)
        except Exception:raise ScanError('Playwright Chromium is missing. Run python -m playwright install chromium.') from None
        try:
            context=browser.new_context(user_agent=USER_AGENT,accept_downloads=False,service_workers='block')
            def route_request(route):
                try:
                    if route.request.resource_type in ('image','media','font'):return route.abort()
                    public_url(route.request.url)
                    if route.request.resource_type=='document':allowed(route.request.url)
                    route.continue_()
                except Exception:route.abort()
            context.route('**/*',route_request)
            page=context.new_page()
            page.goto(public_url(url),wait_until='domcontentloaded',timeout=20000)
            page.locator('body').wait_for(timeout=5000)
            try:page.wait_for_load_state('networkidle',timeout=6000)
            except Exception:pass
            # Bounded read-only navigation: never click Apply, sign in, or form submissions.
            bodies=[page.content()]
            for _ in range(2):
                button=page.get_by_role('button',name=re.compile(r'^(load more|show more)( jobs| openings| roles)?$',re.I))
                if button.count()!=1 or not button.is_visible():break
                button.click(timeout=3000)
                page.wait_for_timeout(600)
                bodies.append(page.content())
            return '\n'.join(bodies),page.url
        except ScanError:raise
        except Exception:raise ScanError('Browser scan timed out or was blocked. Use the manual careers link.') from None
        finally:browser.close()

def scan_company(company, use_browser=False, cancelled=lambda:False):
    candidates=[company.get('careers_url') or company['url']]
    seen=set(); found=[]; errors=[]; source_url=candidates[0]
    deadline=time.monotonic()+65
    used_browser=False
    detail_seen=set()
    while candidates and len(seen)<5:
        if cancelled():raise ScanError('Scan cancelled.')
        if time.monotonic()>deadline:break
        url=candidates.pop(0)
        parsed_url=urlparse(url)
        url=urlunparse(parsed_url._replace(fragment='',path=parsed_url.path.rstrip('/') or '/'))
        if url in seen:continue
        seen.add(url);source_url=url
        try:
            public_url(url)
            info=board(url)
            if info:
                jobs,endpoint=feed_jobs(info)
                return {'status':'checked','jobs':jobs,'source_url':url,'method':info[0],
                        'message':f'{len(jobs)} published openings returned by the public feed.'}
            allowed(url)
            content,final_url=request(url)
            if board(final_url):
                candidates.insert(0,final_url);continue
            parsed=Page(content)
            found.extend(structured(parsed,final_url))
            links=[(urljoin(final_url,href),text) for href,text in parsed.links]
            # Follow only links observed on the company's public site, never guessed tenant names.
            api_links=[link for link,text in links if board(link)]
            career_links=[link for link,text in links if re.search(r'career|\bjobs?\b|join (?:us|our)|open (?:positions|roles)|work with us',text+' '+urlparse(link).path,re.I)
                          and (urlparse(link).hostname==urlparse(final_url).hostname or re.search(r'careers?|job openings|our openings|open (?:positions|roles)',text,re.I))]
            candidates=list(dict.fromkeys(api_links+career_links+candidates))
            detail_links=html_job_links(parsed,final_url)
            if use_browser and not api_links and not career_links and not found and not used_browser and time.monotonic()<deadline-10 and not cancelled():
                used_browser=True
                rendered,rendered_url=browser_page(final_url)
                parsed=Page(rendered)
                found.extend(structured(parsed,rendered_url))
                detail_links+=html_job_links(parsed,rendered_url)
                candidates=[urljoin(rendered_url,href) for href,text in parsed.links if board(urljoin(rendered_url,href)) or
                            (urlparse(urljoin(rendered_url,href)).hostname==urlparse(rendered_url).hostname and re.search(r'careers?|\bjobs?\b|open positions',text+' '+urlparse(href).path,re.I))]+candidates
            for job_url,title in detail_links:
                if len(detail_seen)>=3 or time.monotonic()>deadline or cancelled():break
                if job_url in detail_seen or job_url in seen or board(job_url):continue
                detail_seen.add(job_url)
                try:
                    allowed(job_url)
                    job_content,job_url=request(job_url)
                    detail=Page(job_content)
                    described=structured(detail,job_url)
                    if described:found.extend(described)
                    else:
                        job=html_job(detail,job_url,title)
                        if job:found.append(job)
                except ScanError as error:errors.append(str(error))
        except ScanError as error:errors.append(str(error))
    unique={j['url']:j for j in found}
    if unique:return {'status':'partial','jobs':list(unique.values()),'source_url':source_url,'method':'Playwright / HTML' if used_browser else 'HTML / JSON-LD',
                      'message':'Job listings found on careers pages. Coverage may be partial; pagination or other roles may be missing.'}
    return {'status':'failed','jobs':[],'source_url':source_url,'method':'Discovery',
            'message':errors[-1] if errors else 'No supported public feed or structured job listings found. Add the exact careers or ATS board URL and try again.'}
