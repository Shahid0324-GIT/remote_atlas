let aiConfig = {configured:false, enabled:true, model:'openai/gpt-oss-20b'};
const profileRequests = new Map();
let profileLoad = 0;
const facts = {industry:'Industry',headquarters:'Headquarters',founded:'Founded',company_size:'Company size',remote_policy:'Remote policy',hiring_regions:'Hiring regions',tech_stack:'Tech stack',hiring_status:'Hiring activity'};

function switchProfileTab(name) {
 const profile = name === 'profile';
 $('profile-panel').hidden = !profile;
 $('tracking-panel').hidden = profile;
 $('save-details').hidden = profile;
 for (const [id, active] of [['profile-tab',profile],['tracking-tab',!profile]]) {
  $(id).setAttribute('aria-selected',String(active));
  $(id).tabIndex = active ? 0 : -1;
 }
}
function paintConnection() {
 $('ai-research-toggle').setAttribute('aria-checked',String(aiConfig.enabled));
 $('ai-research-toggle').disabled=!!aiConfig.demo;
 $('ai-settings').hidden=!!aiConfig.demo;
 $('ai-connect-banner').hidden=!!aiConfig.demo;
 $('ai-research-label').textContent=aiConfig.enabled?'AI research on':'AI research off';
 $('ai-research-hint').textContent=aiConfig.enabled?'Click a company card for an AI-researched profile, sources, and your next steps.':'Fetching is paused. Saved company profiles and your tracking are still available.';
 if(aiConfig.demo)$('ai-research-hint').textContent='Shared demo: explore the directory, bookmark companies, and try tracking. AI research is disabled here.';
 $('refresh-profile').disabled=!aiConfig.enabled || profileRequests.has(selected?.id);
 $('ai-connect-banner').textContent = aiConfig.configured ? '✧ AI connected · Settings' : 'Connect Groq →';
 $('ai-connection-status').textContent = aiConfig.configured ? '● Key saved · Ready to research. The key is checked when you research a company.' : 'No key connected yet. Add your key below to get started.';
 $('groq-key').placeholder = aiConfig.configured ? 'Key saved · Enter a new key to replace it' : 'gsk_…';
 $('groq-model').value = aiConfig.model;
}
$('ai-research-toggle').onclick=async()=>{
 $('ai-research-toggle').disabled=true;
 try {
  aiConfig=await api('/api/ai/preferences',{enabled:!aiConfig.enabled});
  paintConnection();
  toast(aiConfig.enabled?'AI research enabled.':'AI research off. Already-started requests may still finish.');
  if($('details').open&&!$('profile-panel').hidden)loadCompanyProfile(selected.id);
 }catch(error){toast(error.message);$('ai-research-toggle').disabled=false;}
};
async function updateConnection() {
 aiConfig = await api('/api/ai/settings');
 paintConnection();
}
async function openAISettings() {
 $('groq-key').value = '';
 $('ai-settings-error').textContent = '';
 try { await updateConnection(); } catch (error) { $('ai-settings-error').textContent = error.message; }
 if (!$('ai-settings-dialog').open) $('ai-settings-dialog').showModal();
}
$('ai-settings').onclick = openAISettings;
$('ai-connect-banner').onclick = openAISettings;
$('close-ai-settings').onclick = () => { $('groq-key').value=''; $('ai-settings-dialog').close(); };
$('ai-settings-dialog').addEventListener('close',() => { $('groq-key').value=''; });
$('ai-settings-form').onsubmit = async event => {
 event.preventDefault();
 $('save-ai-settings').disabled = true;
 $('ai-settings-error').textContent = '';
 try {
  aiConfig = await api('/api/ai/settings',{key:$('groq-key').value, model:$('groq-model').value});
  $('groq-key').value='';
  paintConnection();
  $('ai-settings-dialog').close();
  toast('AI connection saved. Open a company to start researching.');
  if ($('details').open && !$('profile-panel').hidden) loadCompanyProfile(selected.id);
 } catch(error) { $('ai-settings-error').textContent=error.message; }
 finally { $('save-ai-settings').disabled=false; }
};

function sourceLink(url, title) {
 try { const parsed=new URL(url); if (!['http:','https:'].includes(parsed.protocol)) return ''; }
 catch { return ''; }
 return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)} ↗</a>`;
}
function renderCompanyProfile(profile) {
 if(!profile) { $('profile-content').innerHTML=''; return; }
 $('profile-freshness').textContent = `Researched ${new Date(profile.updated_at).toLocaleString()} · Saved locally`;
 const fieldHTML = Object.entries(facts).map(([key,label]) => {
  const fact=profile[key]||{value:'Not found'};
  return `<div class="profile-fact"><dt>${label}</dt><dd>${escapeHtml(fact.value)}${fact.source_url?`<small>${sourceLink(fact.source_url,'Source')}</small>`:''}</dd></div>`;
 }).join('');
 $('profile-content').innerHTML = `<div class="profile-summary"><span class="eyebrow">THE COMPANY AT A GLANCE</span><p>${escapeHtml(profile.summary)}</p></div>${profile.careers_url?'<button type="button" id="profile-careers" class="primary">Explore their careers page ↗</button>':''}<dl class="profile-facts">${fieldHTML}</dl>${profile.suggested_steps?.length?`<section class="profile-steps"><h3>Your next steps</h3><p class="muted">AI suggestions to guide your research</p><ol>${profile.suggested_steps.map(step=>`<li>${escapeHtml(step)}</li>`).join('')}</ol></section>`:''}<section class="profile-sources"><h3>Research sources</h3><ul>${profile.sources.map(s=>`<li>${sourceLink(s.url,s.title)}</li>`).join('')}</ul></section><p class="muted">AI-researched information can be incomplete or outdated. Check the linked sources before applying. “Not found” means the research could not substantiate that detail.</p>`;
 if($('profile-careers')) $('profile-careers').onclick=()=>visit(selected.id,'careers');
}
function profileNotice(message, kind='info', action='') {
 $('profile-message').innerHTML=`<div class="profile-notice ${kind}">${kind==='loading'?'<span class="spinner" aria-hidden="true"></span>':''}<span>${escapeHtml(message)}</span>${action}</div>`;
}
async function loadCompanyProfile(id, force=false) {
 const revision=++profileLoad;
 const current=()=>selected?.id===id && revision===profileLoad && $('details').open;
 $('profile-message').innerHTML='';
 $('profile-content').innerHTML='';
 $('profile-freshness').textContent='Research from public sources';
 $('refresh-profile').disabled=true;
 try {
  const cached=await api(`/api/companies/${id}/profile`);
  if(!current())return;
  renderCompanyProfile(cached.profile);
  await updateConnection();
  if(!current())return;
  if(!aiConfig.enabled){
   profileNotice(aiConfig.demo?'AI research is disabled in this shared demo. Try the My tracking & notes tab to explore the notebook.':'AI research is off. No new details will be fetched. Saved profiles and your notes remain available. Enable AI research in the directory banner when you want to fetch again.');
   return;
  }
  if(cached.profile&&!force&&!profileRequests.has(id))return;
  if(!aiConfig.configured){
   profileNotice('Connect Groq to research this company. Your personal tracking works without AI.','info','<button type="button" class="secondary" data-profile-action="connect">Connect Groq →</button>');
   return;
  }
  profileNotice(cached.profile?'Updating this profile. Your saved research stays visible until it is ready.':'Researching the web… This usually takes 30–90 seconds. You can close this panel and keep exploring.','loading');
  if(!profileRequests.has(id)) {
   const request=api(`/api/companies/${id}/research`,{refresh:force}).finally(()=>profileRequests.delete(id));
   profileRequests.set(id,request);
  }
  const result=await profileRequests.get(id);
  if(!current())return;
  renderCompanyProfile(result.profile);
  $('profile-message').innerHTML='';
 }catch(error){
  if(current())profileNotice(error.message,'error','<button type="button" class="secondary" data-profile-action="retry">Try again</button><button type="button" class="text-button" data-profile-action="connect">AI settings</button>');
 }finally{if(current())$('refresh-profile').disabled=!aiConfig.enabled;}
}
$('profile-message').onclick = event => {
 const action=event.target.closest('[data-profile-action]')?.dataset.profileAction;
 if(action==='connect')openAISettings();
 if(action==='retry')loadCompanyProfile(selected.id,true);
};
$('refresh-profile').onclick=()=>loadCompanyProfile(selected.id,true);
for (const [id,name] of [['profile-tab','profile'],['tracking-tab','tracking']]) {
 $(id).onclick=()=>{switchProfileTab(name);if(name==='profile')loadCompanyProfile(selected.id);};
 $(id).onkeydown=event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();
  const target=event.key==='Home'?'profile-tab':event.key==='End'?'tracking-tab':id==='profile-tab'?'tracking-tab':'profile-tab';
  $(target).click();$(target).focus();
 };
}
updateConnection().catch(()=>{$('ai-connect-banner').textContent='AI settings';});
