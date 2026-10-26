(() => {
  const root = document.querySelector('[data-downtime-checking]');
  if (!root) return;
  const get = (name) => root.querySelector(`[data-${name}]`);
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const state = { run: '', page: 1, q: '', kind: '', change: 'open', minesite: '', timer: null, controller: null, poll: null };
  const text = (value) => value == null || value === '' ? '—' : String(value);
  const safe = (value) => document.createTextNode(text(value));
  const params = (extra = {}) => new URLSearchParams({...state, ...extra, controller: undefined, timer: undefined, poll: undefined});
  const changeLabel = (value) => ({new:'New',persistent:'Persistent',resolved:'Corrected',unverified:'Not confirmed'})[value] || value;
  const updateUrl = () => { const p = params(); p.delete('controller'); p.delete('timer'); p.delete('poll'); history.replaceState(null, '', `${location.pathname}?${p}`); };
  const setMetric = (key, value) => { const node = root.querySelector(`[data-metric="${key}"]`); if (node) node.textContent = text(value); };
  const renderRun = (run) => {
    const counts = run?.counts || {};
    setMetric('events', counts.events); setMetric('findings', counts.findings);
    setMetric('missing', (counts.by_kind?.missing || 0) + (counts.by_kind?.invalid || 0)); setMetric('corrected', counts.corrected);
    get('metric-sites').textContent = counts.events == null ? '— sites' : `${counts.sites || 0} sites`;
    get('metric-open').textContent = counts.events_open == null ? '— affected events' : `${counts.events_open} affected events`;
    get('last-success').textContent = run?.completed_at ? `Last successful check: ${new Date(run.completed_at).toLocaleString()}` : '';
  };
  const option = (value, label, selected = false) => { const node = document.createElement('option'); node.value = value; node.textContent = label; node.selected = selected; return node; };
  const renderHistory = (data) => {
    const select = get('run-select'); const current = state.run || data.successful?.id || '';
    select.replaceChildren(option('', 'Latest successful check'));
    data.history.filter(r => r.status === 'completed').forEach(r => select.append(option(r.id, `${new Date(r.created_at).toLocaleString()} · ${r.counts?.findings || 0} open`, r.id === current)));
    state.run = select.value;
    renderRun(data.successful);
  };
  const row = (item) => {
    const tr = document.createElement('tr');
    const cells = [document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td')];
    const signal = document.createElement('span'); signal.className = `dtcheck-badge ${item.kind}`; signal.textContent = item.kind_label; cells[0].append(signal, document.createElement('br')); const title = document.createElement('span'); title.className='dtcheck-signal'; title.textContent=item.title; cells[0].append(title);
    cells[1].append(safe(item.minesite)); const sub=document.createElement('span');sub.className='dtcheck-sub';sub.textContent=`Event ${item.event_id} · ${item.serial_number || 'No serial'}`;cells[1].append(sub);
    cells[2].append(safe(item.labour_type)); cells[3].append(safe(item.description_cat)); const change=document.createElement('span');change.className=`dtcheck-badge ${item.change}`;change.textContent=changeLabel(item.change);cells[4].append(change);
    const button=document.createElement('button');button.type='button';button.className='dtcheck-detail-button';button.textContent='View';button.addEventListener('click',()=>showDetail(item,button));cells[5].append(button); cells.forEach(c=>tr.append(c)); return tr;
  };
  const showDetail = (item, trigger) => { const dialog=get('detail-dialog'); get('detail-title').textContent=item.title; get('detail-reason').textContent=item.reason; const fields=get('detail-fields'); fields.replaceChildren(); [['Event ID',item.event_id],['MineSite',item.minesite],['Serial number',item.serial_number],['Labour Type',item.labour_type],['Description CAT',item.description_cat],['State',changeLabel(item.change)],['Recommendation',item.recommendation],['Comment',item.comment]].forEach(([label,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=text(value);fields.append(dt,dd);}); get('detail-evidence').textContent=JSON.stringify({before:item.previous_evidence,after:item.evidence},null,2); dialog.showModal(); dialog.addEventListener('close',()=>trigger.focus(),{once:true}); };
  const renderPagination = (data) => { const nav=get('pagination');nav.replaceChildren();if(data.pages<2)return; const add=(label,page,disabled)=>{const b=document.createElement('button');b.textContent=label;b.disabled=disabled;b.addEventListener('click',()=>{state.page=page;loadResults();});nav.append(b);};add('Previous',data.page-1,data.page<=1); const status=document.createElement('span');status.textContent=`Page ${data.page} of ${data.pages}`;nav.append(status);add('Next',data.page+1,data.page>=data.pages); };
  const populateSites = (sites) => { const select=get('filter="minesite"'); if (!select) return; const selected=state.minesite;select.replaceChildren(option('', 'All sites'));sites.forEach(s=>select.append(option(s,s,s===selected))); };
  async function loadResults() {
    if (state.controller) state.controller.abort(); state.controller=new AbortController(); const query=params(); ['timer','controller','poll'].forEach(k=>query.delete(k));
    try { const response=await fetch(`${root.dataset.resultsUrl}?${query}`,{signal:state.controller.signal,headers:{Accept:'application/json'}}); const data=await response.json();if(!response.ok)throw Error(data.error||'Unable to load results');
      const body=get('results');body.replaceChildren(...data.results.map(row));get('empty').hidden=!!data.run;get('table-wrap').hidden=!data.run;get('results-summary').textContent=data.run ? `${data.count} finding${data.count===1?'':'s'} · saved YTD check` : 'No saved YTD check yet.'; renderPagination(data);populateSites(data.sites||[]);if(data.run)renderRun(data.run);updateUrl();
    } catch(error) { if(error.name!=='AbortError'){get('results-summary').textContent='Saved results could not be loaded.';} } finally {state.controller=null;}
  }
  const setProgress=(run)=>{const active=run&&['queued','running'].includes(run.status);get('progress').hidden=!active;get('recheck').disabled=active;if(active){get('progress-phase').textContent=run.phase||'Checking…';const total=run.total_rows||0,done=run.processed_rows||0;get('progress-count').textContent=total?`${done.toLocaleString()} / ${total.toLocaleString()}`:'Preparing source check…';get('progress-bar').style.width=total?`${Math.max(3,Math.min(100,done/total*100))}%`:'12%';get('run-status').textContent='YTD check in progress';}else get('run-status').textContent=run?.completed_at?'Saved results available':'No active check';};
  async function refreshStatus(){try{const response=await fetch(root.dataset.statusUrl,{headers:{Accept:'application/json'}});const data=await response.json();if(!response.ok)throw Error();renderHistory(data);setProgress(data.current);if(data.successful && !state.run){state.run=data.successful.id;}await loadResults();if(data.current&&['queued','running'].includes(data.current.status)){clearTimeout(state.poll);state.poll=setTimeout(refreshStatus,2500);}}catch{get('run-status').textContent='Status unavailable';}}
  get('recheck').addEventListener('click',async()=>{get('recheck').disabled=true;try{const response=await fetch(root.dataset.recheckUrl,{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/json',Accept:'application/json'},body:'{}'});const data=await response.json();if(!response.ok&&response.status!==409)throw Error(data.error||'Unable to start the YTD check');setProgress(data.run);get('run-status').textContent=data.created?'YTD check started':'A YTD check is already running';refreshStatus();}catch(error){get('run-status').textContent=error.message;get('recheck').disabled=false;}});
  ['q','kind','change','minesite'].forEach(key=>{const control=get(`filter="${key}"`); if(!control)return;control.addEventListener('input',()=>{state[key]=control.value;state.page=1;clearTimeout(state.timer);state.timer=setTimeout(loadResults,key==='q'?350:0);get('clear-search').hidden=!state.q;});control.addEventListener('change',()=>{state[key]=control.value;state.page=1;loadResults();});});
  get('clear-search').addEventListener('click',()=>{const input=get('filter="q"');input.value='';state.q='';get('clear-search').hidden=true;state.page=1;loadResults();input.focus();});
  get('run-select').addEventListener('change',event=>{state.run=event.target.value;state.page=1;loadResults();}); get('export').addEventListener('click',event=>{const query=params();['timer','controller','poll','page'].forEach(k=>query.delete(k));event.currentTarget.href=`${root.dataset.exportUrl}?${query}`;});
  const initial=new URLSearchParams(location.search);['run','q','kind','change','minesite'].forEach(k=>{if(initial.has(k))state[k]=initial.get(k);});state.page=Math.max(1,Number(initial.get('page')||1));['q','kind','change','minesite'].forEach(k=>{const control=get(`filter="${k}"`);if(control)control.value=state[k];});get('clear-search').hidden=!state.q;refreshStatus();
})();
