const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { data: null, plan: null, workspace: 'overview', query: '', project: 'all', status: 'all' };
const text = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({ '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;' }[c]));
const status = (project) => {
  const value = `${project.git_status || ''} ${project.status || ''} ${project.production_maintenance_status || ''}`.toLowerCase();
  return value.includes('pending') || value.includes('à confirmer') ? 'pending' : value.includes('active') || value.includes('opérationnel') || value.includes('verified') ? 'active' : 'other';
};
const description = (project) => project.status || project.git_status || project.production_maintenance_status || 'État détaillé dans la mémoire du projet.';
const color = (index) => ['#ffd400','#3478c9','#168b79','#7453a6','#b43f49','#17765a','#8997ae'][index % 7];
const projects = () => (state.data?.portfolio.projects || []).filter((item) => (state.project === 'all' || item.id === state.project) && (state.status === 'all' || status(item) === state.status) && `${item.name} ${item.id} ${description(item)} ${item.primary_memory || ''}`.toLowerCase().includes(state.query.toLowerCase()));

function showWorkspace(name) {
  state.workspace = name;
  $$('.workspace').forEach((node) => node.classList.toggle('active', node.id === name));
  $$('[data-workspace]').forEach((node) => node.classList.toggle('active', node.dataset.workspace === name));
  const labels = {overview:['Vue exécutive','État consolidé des projets, continuité et mémoire durable.'],projects:['Projets','Exploration des environnements, références et état de travail.'],memory:['Mémoire & Dropbox','Plan de synchronisation contrôlé et traces de continuité.'],activity:['Activité','Sources et observations de portefeuille.']};
  $('#page-title').textContent = labels[name][0]; $('#subtitle').textContent = labels[name][1];
}

function openProject(id) {
  const project = state.data.portfolio.projects.find((item) => item.id === id); if (!project) return;
  $('#drawer-title').textContent = project.name; $('#drawer-status').textContent = description(project);
  const rows = [['ID',project.id],['Environnement local',project.local_url || project.canonical_path],['Production',project.production_url || project.remote_environment || 'Non renseigné'],['Mémoire',project.primary_memory || 'Registre portefeuille'],['Git live',project.git_live?.available ? `${project.git_live.branch} · ${project.git_live.changes} changement(s)` : 'Non inspecté']];
  $('#drawer-details').innerHTML = rows.map(([key,value]) => `<dt>${text(key)}</dt><dd>${text(value)}</dd>`).join('');
  const memory = project.primary_memory || 'docs/PROJECT_PORTFOLIO_MEMORY_2026-10-15.md'; $('#drawer-memory').href = `../${memory}`; $('#project-drawer').showModal();
}

function renderProjects() {
  const list = projects(); $('#project-results').textContent = `${list.length} résultat(s)`;
  $('#overview-projects').innerHTML = list.slice(0,6).map((item,index) => `<button class="line-card" style="--accent:${color(index)}" data-project="${text(item.id)}"><header><span>${text(item.id)}</span><small>${text(item.git_live?.branch || item.branch || 'managed')}</small></header><strong>${text(item.name)}</strong><footer>${text(description(item)).slice(0,92)}${description(item).length > 92 ? '…':''}</footer></button>`).join('') || '<p>Aucun projet ne correspond aux filtres.</p>';
  $('#project-table').innerHTML = `<table class="project-table"><thead><tr><th>Projet</th><th>État</th><th>Local</th><th>Production</th><th>Mémoire</th><th>Git</th></tr></thead><tbody>${list.map((item) => `<tr data-project="${text(item.id)}"><td><b>${text(item.name)}</b><br><small>${text(item.id)}</small></td><td><span class="badge ${status(item)}">${status(item)}</span><br><small>${text(description(item)).slice(0,62)}…</small></td><td>${text(item.local_url || item.canonical_path || '—')}</td><td>${text(item.production_url || item.remote_environment || '—')}</td><td>${text(item.primary_memory || '—')}</td><td>${item.git_live?.available ? `${text(item.git_live.branch)}<br><small>${item.git_live.changes} change(s)</small>` : '—'}</td></tr>`).join('')}</tbody></table>`;
  $$('[data-project]').forEach((node) => node.addEventListener('click', () => openProject(node.dataset.project)));
}

function renderOverview() {
  const all = state.data.portfolio.projects; $('#hero-count').textContent = all.length;
  $('#local-count').textContent = all.filter((item) => item.local_url || item.canonical_path).length;
  $('#memory-count').textContent = all.filter((item) => item.memory_available).length;
  const git = all.filter((item) => item.git_live?.available); $('#git-clean').textContent = git.filter((item) => !item.git_live.changes).length;
  $('#dropbox-state').textContent = state.data.dropbox.available ? 'Prêt' : state.data.dropbox.configured ? 'Absent' : 'À configurer';
  const watch = all.filter((item) => status(item) === 'pending').slice(0,5); $('#attention-list').innerHTML = (watch.length ? watch : all.slice(0,3)).map((item) => `<div class="attention-item ${status(item)}"><strong>${text(item.name)}</strong><p>${text(description(item)).slice(0,160)}</p></div>`).join('');
  $('#activity-list').innerHTML = all.map((item) => `<div class="activity"><time>${text(state.data.portfolio.as_of)}</time><span><b>${text(item.name)}</b><br>${text(item.primary_memory || 'Registre portefeuille')}</span><span class="badge ${status(item)}">${status(item)}</span></div>`).join('');
  $('#generated-at').textContent = `Actualisé ${new Date(state.data.generated_at).toLocaleString('fr-FR')}`;
}

async function loadPlan() {
  const response = await fetch('/api/sync/plan'); state.plan = await response.json(); const plan = state.plan;
  $('#sync-plan').innerHTML = plan.files.map((file) => `<div class="sync-row"><span>${text(file.path)}<br><small>${file.exists ? file.sha256.slice(0,16)+'…' : 'Fichier introuvable'}</small></span><b>${file.exists ? '✓' : '!'}</b></div>`).join('');
  const enabled = plan.dropbox.available; $('#sync-button').disabled = !enabled; $('#dropbox-title').textContent = enabled ? 'Dropbox prêt' : plan.dropbox.configured ? 'Dossier Dropbox introuvable' : 'Dropbox non configuré'; $('#dropbox-copy').textContent = enabled ? `Destination : ${plan.dropbox.root}` : 'Copiez le fichier exemple vers dropbox-sync.local.json, indiquez le dossier Dropbox local, puis relancez le centre.';
}

async function load() { const response = await fetch('/api/overview'); state.data = await response.json(); const select = $('#project-filter'); select.innerHTML = '<option value="all">Tous les projets</option>' + state.data.portfolio.projects.map((item) => `<option value="${text(item.id)}">${text(item.name)}</option>`).join(''); renderOverview(); renderProjects(); await loadPlan(); }
async function sync() { if (!confirm('Synchroniser uniquement la documentation autorisée vers Dropbox ? Aucun fichier ne sera supprimé.')) return; const response = await fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:'SYNC_DOCUMENTATION'})}); const result = await response.json(); alert(response.ok ? `${result.files.length} document(s) synchronisé(s) et vérifié(s).` : result.error); if (response.ok) loadPlan(); }
function search(value) { const matches = state.data.portfolio.projects.filter((item) => `${item.name} ${item.id} ${description(item)}`.toLowerCase().includes(value.toLowerCase())); $('#search-results').innerHTML = matches.map((item) => `<button class="search-result" data-project="${text(item.id)}"><b>${text(item.name)}</b><small>${text(description(item)).slice(0,100)}</small></button>`).join('') || '<p>Aucun résultat.</p>'; $$('[data-project]').forEach((node) => node.addEventListener('click', () => { $('#search-dialog').close(); openProject(node.dataset.project); })); }

$$('[data-workspace]').forEach((node) => node.addEventListener('click', () => showWorkspace(node.dataset.workspace))); $('#project-filter').addEventListener('change',(event)=>{state.project=event.target.value;renderProjects()}); $('#status-filter').addEventListener('change',(event)=>{state.status=event.target.value;renderProjects()}); $('#search').addEventListener('input',(event)=>{state.query=event.target.value;renderProjects()}); $('#reset').addEventListener('click',()=>{state.project='all';state.status='all';state.query='';$('#project-filter').value='all';$('#status-filter').value='all';$('#search').value='';renderProjects()}); $('#refresh').addEventListener('click',load); $('#quick-refresh').addEventListener('click',load); $('#reload-plan').addEventListener('click',loadPlan); $('#sync-button').addEventListener('click',sync); $('#search-toggle').addEventListener('click',()=>{$('#search-dialog').showModal();search('');$('#dialog-search').focus()}); $('#dialog-search').addEventListener('input',(event)=>search(event.target.value)); $$('.close').forEach((node)=>node.addEventListener('click',()=>node.closest('dialog').close())); document.addEventListener('keydown',(event)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();$('#search-dialog').showModal();$('#dialog-search').focus()}}); load().catch((error)=>{document.body.innerHTML=`<main class="shell"><h1>360 Command Center</h1><p>${text(error.message)}</p></main>`});
