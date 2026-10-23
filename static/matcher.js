let matcherData={jobs:[],companies:[],state:{status:'idle'}}, matchingPage=1, matchingView='jobs', matcherTimer;
const matchingPageSize=12;
let matcherLoaded=false;
function matchingError(error){$('matcher-error').textContent=error?.message||String(error);}
function paintScanState(state){
 const running=state.status==='running';
 $('start-scan').disabled=running;
 $('stop-scan').hidden=!running;
 $('scan-progress').max=state.total||1;
 $('scan-progress').value=state.done||0;
 $('scan-status').textContent=state.status==='idle'?'Ready when you are. Save your resume and choose companies above.':`${({running:'Scanning',complete:'Scan complete',cancelled:'Scan stopped',interrupted:'Scan interrupted',failed:'Scan failed'})[state.status]||state.status} · ${state.done||0} / ${state.total||0} companies · ${state.checked||0} checked · ${state.failed||0} couldn’t check · ${state.cached||0} cached${state.current?' · '+state.current:''}${state.message?' · '+state.message:''}`;
}
async function loadMatcherResults(){matcherData=await api('/api/scanner/results');paintScanState(matcherData.state);renderMatches();}
async function pollMatcher(){
 clearTimeout(matcherTimer);
 try {
  const previous=matcherData.state;
  const state=await api('/api/scanner/state');
  matcherData.state=state;paintScanState(state);
  if(state.status!=='running'||Math.floor((state.done||0)/5)!==Math.floor((previous.done||0)/5))await loadMatcherResults();
  if(state.status==='running')matcherTimer=setTimeout(pollMatcher,2500);
 }catch(error){matchingError(error);matcherTimer=setTimeout(pollMatcher,10000);}
}
function populateMatcher(settings){
 $('resume-text').value=settings.resume_text;
 $('match-roles').value=settings.roles;
 $('match-location').value=settings.location;
 $('match-experience').value=settings.experience_years??'';
 $('match-browser').checked=settings.use_browser;
 $('match-daily').checked=settings.auto_daily;
 $('match-daily-scope').value=settings.daily_scope;
 $('resume-saved-state').textContent=settings.resume_text?'Resume saved locally':'Set up once';
 $('detected-skills').textContent=settings.detected_skills.length?'Detected resume skills: '+settings.detected_skills.join(', '):'No recognized technical skills yet. Add the skills you want to match.';
 $('browser-availability').textContent=settings.playwright_installed?'Playwright package detected. Chromium must also be installed for browser fallback.':'Browser fallback needs one-time setup: double-click Setup Job Scanner.cmd, then launch Start Job Scanner.cmd. Public feeds work without Playwright.';
}
$('open-matcher').onclick=async()=>{
 document.querySelectorAll('nav button').forEach(button=>button.classList.toggle('active',button.id==='open-matcher'));
 $('breadcrumb').textContent='Matching jobs';
 document.querySelector('.directory').hidden=true;document.querySelector('.research-banner').hidden=true;$('matcher').hidden=false;
 $('matcher-error').textContent='';
 try {
  if(!matcherLoaded){
   const settings=await api('/api/scanner/settings');populateMatcher(settings);$('matcher-setup').open=!settings.resume_text;matcherLoaded=true;
  }
  await loadMatcherResults();
  const old=$('source-company').value;
  $('source-company').innerHTML=matcherData.companies.map(c=>`<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
  if(old)$('source-company').value=old;
  paintSource();
  if(matcherData.state.status==='running')pollMatcher();
 }catch(error){matchingError(error);}
};
$('matcher-settings-form').onsubmit=async event=>{
 event.preventDefault();$('save-matcher').disabled=true;$('matcher-error').textContent='';
 try {
  const years=$('match-experience').value;
  const settings=await api('/api/scanner/settings',{resume_text:$('resume-text').value,roles:$('match-roles').value,location:$('match-location').value,
   experience_years:years===''?null:Number(years),use_browser:$('match-browser').checked,auto_daily:$('match-daily').checked,daily_scope:$('match-daily-scope').value});
  populateMatcher(settings);await loadMatcherResults();toast('Resume and preferences saved. Existing jobs have been matched again locally.');
 }catch(error){matchingError(error);toast(error.message);}finally{$('save-matcher').disabled=false;}
};
$('resume-file').onchange=async()=>{
 const file=$('resume-file').files[0];if(!file)return;
 $('resume-import-status').textContent='Importing locally…';$('save-matcher').disabled=true;
 try {
  if(file.size>4000000)throw Error('Choose a PDF or text file under 4 MB.');
  let text;
  if(file.name.toLowerCase().endsWith('.txt'))text=await file.text();
  else if(file.name.toLowerCase().endsWith('.pdf')){
   const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('Could not read the file.'));reader.readAsDataURL(file);});
   text=(await api('/api/scanner/resume',{pdf:data})).text;
  }else throw Error('Choose a PDF or .txt file, or paste the resume text.');
  if(text.length>60000)throw Error('Resume text must be under 60,000 characters.');
  $('resume-text').value=text;$('resume-import-status').textContent='Imported. Review the text and save your preferences.';
 }catch(error){$('resume-import-status').textContent=error.message;}finally{$('save-matcher').disabled=false;$('resume-file').value='';}
};
$('start-scan').onclick=async()=>{
 $('matcher-error').textContent='';$('start-scan').disabled=true;
 try {const state=await api('/api/scanner/start',{scope:$('scan-scope').value,limit:Number($('scan-limit').value),force:$('scan-force').checked});$('stop-scan').disabled=false;matcherData.state=state;paintScanState(state);pollMatcher();}
 catch(error){matchingError(error);$('start-scan').disabled=false;}
};
$('stop-scan').onclick=async()=>{try{await api('/api/scanner/cancel',{});$('stop-scan').disabled=true;$('scan-status').textContent='Stopping after the current network request…';}catch(error){matchingError(error);}};
function paintSource(){const c=matcherData.companies.find(c=>c.id===Number($('source-company').value));$('source-url').value=c?.careers_url||'';}
$('source-company').onchange=paintSource;
$('source-form').onsubmit=async event=>{event.preventDefault();try{await api('/api/scanner/source',{company_id:Number($('source-company').value),url:$('source-url').value});await loadMatcherResults();toast('Careers page saved. Start a fresh scan to check it.');}catch(error){matchingError(error);toast(error.message);}};
function selectedJobs(){
 const q=$('match-search').value.trim().toLowerCase(),minimum=Number($('match-threshold').value);
 return matcherData.jobs.filter(j=>(j.score===null?$('filter-unscored').checked:j.score>=minimum)
  &&(!$('filter-remote').checked||j.remote===true)
  &&(!$('filter-location').checked||['Location matches','Worldwide listed'].includes(j.location_signal))
  &&(!$('filter-experience').checked||!j.experience_warning)
  &&(!q||`${j.company_name} ${j.title} ${j.location} ${j.matched_skills.join(' ')} ${j.missing_skills.join(' ')}`.toLowerCase().includes(q)));
}
function renderMatches(){
 $('match-threshold-label').textContent=$('match-threshold').value+'%';
 const jobs=selectedJobs(), companyCounts=new Map();
 jobs.forEach(j=>companyCounts.set(j.company_id,(companyCounts.get(j.company_id)||0)+1));
 const q=$('match-search').value.toLowerCase().trim(),coverage=$('coverage-status').value;
 let rows=matchingView==='jobs'?jobs:matcherData.companies.filter(c=>(!q||c.name.toLowerCase().includes(q))&&(!coverage||(coverage==='matches'?companyCounts.has(c.id):c.status===coverage)));
 const pages=Math.max(1,Math.ceil(rows.length/matchingPageSize));matchingPage=Math.min(matchingPage,pages);
 $('matching-page').textContent=`Page ${matchingPage} of ${pages}`;$('matching-previous').disabled=matchingPage<=1;$('matching-next').disabled=matchingPage>=pages;
 $('match-count').textContent=`${jobs.length} jobs across ${companyCounts.size} companies match these filters. ${matcherData.companies.filter(c=>c.status!=='unchecked').length} / ${matcherData.companies.length} companies checked.${matcherData.limited?' Results capped for performance; narrow your role preferences.':''}`;
 $('coverage-status').disabled=matchingView==='jobs';
 rows=rows.slice((matchingPage-1)*matchingPageSize,matchingPage*matchingPageSize);
 if(!rows.length){$('matching-results').innerHTML=`<div class="empty"><h2>${matcherData.jobs.length?'No results for these filters.':'Start with your resume and a small scan.'}</h2><p>${matcherData.jobs.length?'Lower the skill threshold or relax your location and remote filters.':'No matching roles collected yet. Company coverage explains what was checked and which pages need a manual link.'}</p></div>`;return;}
 if(matchingView==='companies'){
  $('matching-results').innerHTML=rows.map(c=>`<article class="coverage-row"><div><strong>${escapeHtml(c.name)}</strong><span class="pill">${companyCounts.has(c.id)?`${companyCounts.get(c.id)} matching jobs`:({checked:'No matching jobs for these filters',partial:'Partial coverage',failed:'Couldn’t check',unchecked:'Not scanned'})[c.status]}</span><p>${escapeHtml(c.message)}</p><small>${c.checked_at?'Last check: '+escapeHtml(new Date(c.checked_at).toLocaleString()):'Not checked'}${c.method?' · '+escapeHtml(c.method):''}</small></div><div><button class="secondary" data-careers-company="${c.id}" type="button">Set careers page</button><button class="text-button" data-open-careers="${c.id}" type="button">Open careers ↗</button><button class="text-button" data-notebook-company="${c.id}" type="button">My notes</button></div></article>`).join('');return;
 }
 $('matching-results').innerHTML=rows.map(j=>`<article class="match-job"><div class="match-job-top"><div><span class="eyebrow">${escapeHtml(j.company_name)}</span><h3>${escapeHtml(j.title)}</h3><p>${escapeHtml(j.location||'Location not specified')} · ${j.remote===true?'Remote listed':j.remote===false?'On-site / hybrid listed':'Remote status unknown'}</p></div><div class="match-score">${j.score===null?'—':j.score+'%'}<small>skill overlap</small></div></div><div class="job-flags"><span class="pill">${escapeHtml(j.location_signal)}</span>${j.experience_warning?'<span class="pill stage">More experience requested</span>':''}${j.seniority_warning?'<span class="pill stage">Check seniority</span>':''}${j.stale?'<span class="pill stage">Older result · verify opening</span>':''}</div><p class="skill-list"><strong>Matched:</strong> ${escapeHtml(j.matched_skills.join(', ')||'No recognized matches')}</p><p class="skill-list"><strong>Not in resume:</strong> ${escapeHtml(j.missing_skills.join(', ')||'None of the detected skills')}${j.minimum_years!==null?' · '+j.minimum_years+'+ years mentioned':''}</p><details><summary>Job excerpt & match explanation</summary><p class="job-excerpt">${escapeHtml(j.description||'The source did not include a full description.')}</p><p class="muted">${j.score===null?'Not enough recognized skills to calculate a score.':`${j.matched_skills.length} matched / ${j.matched_skills.length+j.missing_skills.length} detected skills. These are keywords from the posting, not verified mandatory requirements.`}</p></details><div class="match-job-footer"><small>${escapeHtml(j.source)} · Checked ${escapeHtml(new Date(j.fetched_at).toLocaleDateString())}</small><div><button class="text-button" type="button" data-notebook-company="${j.company_id}">My notes</button><button class="primary" type="button" data-open-job="${escapeHtml(j.url)}" data-company="${j.company_id}">View job ↗</button></div></div></article>`).join('');
}
for(const id of ['match-threshold','match-search','coverage-status','filter-remote','filter-location','filter-experience','filter-unscored'])$(id).addEventListener('input',()=>{matchingPage=1;renderMatches();});
for(const [id,kind] of [['show-job-results','jobs'],['show-company-results','companies']])$(id).onclick=()=>{matchingView=kind;matchingPage=1;$('show-job-results').setAttribute('aria-pressed',String(kind==='jobs'));$('show-company-results').setAttribute('aria-pressed',String(kind==='companies'));renderMatches();};
$('matching-previous').onclick=()=>{matchingPage--;renderMatches();};$('matching-next').onclick=()=>{matchingPage++;renderMatches();};
$('matching-results').onclick=async event=>{
 const button=event.target.closest('button');if(!button)return;
 if(button.dataset.careersCompany){$('source-setup').open=true;$('source-company').value=button.dataset.careersCompany;paintSource();$('source-url').focus();return;}
 if(button.dataset.openCareers){visit(Number(button.dataset.openCareers),'scan-careers');return;}
 if(button.dataset.notebookCompany){details(Number(button.dataset.notebookCompany),'tracking');return;}
 if(button.dataset.openJob){
  const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;
  try{const result=await api(`/api/companies/${button.dataset.company}/visit`,{kind:'job',url:button.dataset.openJob});if(popup)popup.location.replace(result.url);else toast('Visit recorded. Allow pop-ups to open job listings.');await refresh();}
  catch(error){if(popup)popup.close();toast(error.message);}
 }
};

$('scan-source-company').onclick=async()=>{
 $('scan-source-company').disabled=true;$('matcher-error').textContent='';
 try {
  const id=Number($('source-company').value);
  await api('/api/scanner/source',{company_id:id,url:$('source-url').value});
  const state=await api('/api/scanner/start',{scope:'all',company_id:id,limit:1,force:true});
  $('stop-scan').disabled=false;matcherData.state=state;paintScanState(state);pollMatcher();
 }catch(error){matchingError(error);toast(error.message);}finally{$('scan-source-company').disabled=false;}
};
