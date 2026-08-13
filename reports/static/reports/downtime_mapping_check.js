(() => {
  const root = document.querySelector('[data-dmc-app]');
  if (!root) return;
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const csrf = () => document.cookie.split('; ').find(value => value.startsWith('csrftoken='))?.split('=')[1] || '';
  const json = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf(), ...(options.headers || {})}, ...options});
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || 'The request failed.');
    return payload;
  };
  const state = {run: null, preview: null, page: 1, count: 0, items: [], poll: null};
  const filters = () => {
    const values = {};
    $$('[data-dmc-filter]').forEach(input => values[input.dataset.dmcFilter] = input.value.trim());
    const {start_date, end_date, mode, ...optional} = values;
    Object.keys(optional).forEach(key => { if (!optional[key] || optional[key] === 'all') delete optional[key]; });
    return {start_date, end_date, mode: mode || 'full', filters: optional};
  };
  const setBusy = (busy) => { $('[data-dmc-check]').disabled = busy; $('[data-dmc-check]').textContent = busy ? 'Checking...' : 'Check data'; };
  const showError = (error) => window.alert(error.message || String(error));
  const setModal = (open) => { const node = $('[data-dmc-confirm]'); node.hidden = !open; node.setAttribute('aria-hidden', String(!open)); };
  const setDrawer = (open) => { const node = $('[data-dmc-drawer]'); node.hidden = !open; node.setAttribute('aria-hidden', String(!open)); };
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const badge = status => `<span class="dmc-status status-${escapeHtml(status.toLowerCase().replaceAll('_', '-'))}">${escapeHtml(status.replaceAll('_', ' '))}</span>`;

  async function preview() {
    setBusy(true);
    try {
      const payload = await json(root.dataset.previewUrl, {method: 'POST', body: JSON.stringify(filters())});
      state.preview = payload.preview;
      const p = payload.preview;
      $('[data-dmc-preview-list]').innerHTML = [
        ['Date range', `${filters().start_date} to ${filters().end_date}`], ['Rows selected', p.total_rows],
        ['Rows already checked and unchanged', p.cached_rows], ['Rows requiring analysis', p.ai_rows],
        ['Rows without comments', p.rows_without_useful_comments], ['Estimated tokens', p.estimated_tokens.toLocaleString()],
        ['Estimated API cost', `$${Number(p.estimated_cost).toFixed(2)}`], ['Mode', p.mode === 'smart' ? 'Smart Audit' : 'Full AI Audit'],
        ...(p.limit_exceeded ? [['Run limit', `Narrow the selection to ${p.maximum_rows.toLocaleString()} rows or fewer`]] : [])
      ].map(([term, value]) => `<div><dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('');
      $('[data-dmc-start]').disabled = Boolean(p.limit_exceeded || !p.total_rows);
      setModal(true);
    } catch (error) { showError(error); } finally { setBusy(false); }
  }
  async function start() {
    setModal(false); setBusy(true);
    try {
      const payload = await json(root.dataset.runsUrl, {method: 'POST', body: JSON.stringify({...filters(), processing_method: 'standard'})});
      state.run = payload.run; state.page = 1; renderRun(); poll(); loadHistory();
    } catch (error) { showError(error); } finally { setBusy(false); }
  }
  function renderRun() {
    const run = state.run; if (!run) return;
    $('[data-dmc-progress]').hidden = !['Queued', 'Running'].includes(run.status);
    $('[data-dmc-summary]').hidden = false; $('[data-dmc-results]').hidden = false;
    const percent = run.total_rows ? Math.round(run.processed_rows / run.total_rows * 100) : 0;
    $('[data-dmc-progress-bar]').style.width = `${Math.min(100, percent)}%`;
    $('[data-dmc-progress-copy]').textContent = `${run.processed_rows.toLocaleString()} / ${run.total_rows.toLocaleString()} rows completed · ${run.status}`;
    const values = {...run, taxonomy: run.unmapped + run.taxonomy_gaps, estimated_cost: `$${Number(run.estimated_cost).toFixed(2)}`};
    $$('[data-dmc-kpi]').forEach(node => node.textContent = values[node.dataset.dmcKpi]?.toLocaleString?.() ?? values[node.dataset.dmcKpi] ?? 0);
    $('[data-dmc-export]').href = `${root.dataset.runsUrl}${run.id}/export/csv/`;
  }
  async function poll() {
    clearTimeout(state.poll); if (!state.run) return;
    try {
      state.run = (await json(`${root.dataset.runsUrl}${state.run.id}/`)).run; renderRun(); await loadItems();
      if (['Queued', 'Running'].includes(state.run.status)) state.poll = setTimeout(poll, 2000);
      else loadHistory();
    } catch (error) { showError(error); }
  }
  async function loadItems() {
    if (!state.run) return;
    const query = new URLSearchParams({page: state.page, page_size: 50, status: $('[data-dmc-status]').value, q: $('[data-dmc-search]').value});
    const payload = await json(`${root.dataset.runsUrl}${state.run.id}/items/?${query}`);
    state.items = payload.results; state.count = payload.count;
    $('[data-dmc-page]').textContent = `Page ${state.page} · ${payload.count.toLocaleString()} rows`;
    $('[data-dmc-previous]').disabled = state.page === 1; $('[data-dmc-next]').disabled = state.page * payload.page_size >= payload.count;
    $('[data-dmc-rows]').innerHTML = state.items.length ? state.items.map(item => `<tr>
      <td data-label="Status">${badge(item.status)}</td><td data-label="Event">${escapeHtml(item.event_id)}</td><td data-label="MineSite">${escapeHtml(item.minesite)}</td>
      <td data-label="Serial">${escapeHtml(item.serial_number)}</td><td data-label="Labour Type">${escapeHtml(item.labour_type)}</td>
      <td data-label="Current CAT">${escapeHtml(item.current_description_cat || 'Unmapped')}</td><td data-label="Recommended CAT">${escapeHtml(item.recommended_description_cat || 'No recommendation')}</td>
      <td data-label="Confidence">${item.confidence}%</td><td data-label="Comment"><span class="dmc-truncate" title="${escapeHtml(item.comment)}">${escapeHtml(item.comment || 'No comment')}</span></td>
      <td><button class="button secondary small" type="button" data-dmc-open="${item.id}">Review</button></td></tr>`).join('') : '<tr><td colspan="10" class="empty compact">No results found.</td></tr>';
  }
  function openItem(id) {
    const item = state.items.find(value => String(value.id) === String(id)); if (!item) return;
    $('[data-dmc-detail-title]').textContent = `Event ${item.event_id}`;
    const evidence = (item.evidence || []).map(value => `<mark>${escapeHtml(value)}</mark>`).join(' ');
    $('[data-dmc-detail]').innerHTML = `<div class="dmc-detail-grid"><div><span>MineSite</span><strong>${escapeHtml(item.minesite || '-')}</strong></div><div><span>Equipment</span><strong>${escapeHtml(item.serial_number || '-')}</strong></div><div><span>Labour Type</span><strong>${escapeHtml(item.labour_type || '-')}</strong></div><div><span>Status</span>${badge(item.status)}</div></div>
      <section><h3>Current mapping</h3><p>${escapeHtml(item.current_description_cat || 'Unmapped')}</p></section>
      <section><h3>Original comment</h3><p class="dmc-comment">${escapeHtml(item.comment || 'No comment')}</p><p>${evidence || 'No evidence phrase was retained.'}</p></section>
      <section><h3>AI independent classification</h3><p><strong>${escapeHtml(item.recommended_description_cat || 'No recommendation')}</strong> · ${item.confidence}%</p><p>${escapeHtml(item.reason)}</p></section>
      <form data-dmc-review-form data-item-id="${item.id}"><label><span>Decision</span><select name="decision"><option>Approve Current</option><option>Approve AI Recommendation</option><option>Select Another Description CAT</option><option>Mark Ambiguous</option><option>Mark Insufficient Evidence</option><option>Reject AI Result</option></select></label><label><span>Approved Description CAT</span><select name="description_cat_id" data-dmc-taxonomy><option value="">Not required</option></select></label><label><span>Review note</span><textarea name="notes" rows="3"></textarea></label><button class="button" type="submit">Save review</button></form>`;
    loadTaxonomy(); setDrawer(true);
  }
  async function loadTaxonomy() {
    const select = $('[data-dmc-taxonomy]'); if (!select) return;
    const payload = await json(root.dataset.taxonomyUrl);
    select.insertAdjacentHTML('beforeend', payload.results.map(item => `<option value="${item.id}">${escapeHtml(item.display_name)}</option>`).join(''));
  }
  async function saveReview(form) {
    const data = Object.fromEntries(new FormData(form));
    try { await json(`/api/data/downtime-mapping-check/items/${form.dataset.itemId}/review/`, {method: 'POST', body: JSON.stringify(data)}); setDrawer(false); loadItems(); }
    catch (error) { showError(error); }
  }
  async function loadHistory() {
    try {
      const payload = await json(root.dataset.runsUrl);
      $('[data-dmc-history]').innerHTML = payload.runs.length ? payload.runs.map(run => `<button type="button" data-dmc-run="${run.id}"><strong>${run.start_date} – ${run.end_date}</strong><span>${run.status} · ${run.processed_rows}/${run.total_rows} · ${run.mismatches} mismatches</span></button>`).join('') : '<p class="empty compact">No audit run yet.</p>';
    } catch (error) { $('[data-dmc-history]').innerHTML = `<p class="empty compact">${escapeHtml(error.message)}</p>`; }
  }
  $('[data-dmc-check]').addEventListener('click', preview); $('[data-dmc-start]').addEventListener('click', start);
  $$('[data-dmc-confirm-close]').forEach(node => node.addEventListener('click', () => setModal(false)));
  $$('[data-dmc-drawer-close]').forEach(node => node.addEventListener('click', () => setDrawer(false)));
  $('[data-dmc-clear]').addEventListener('click', () => $$('[data-dmc-filter]').forEach(input => { if (!['start_date','end_date'].includes(input.dataset.dmcFilter)) input.value = input.tagName === 'SELECT' ? input.options[0].value : ''; }));
  $('[data-dmc-status]').addEventListener('change', () => { state.page = 1; loadItems(); });
  let searchTimer; $('[data-dmc-search]').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.page = 1; loadItems(); }, 300); });
  $('[data-dmc-previous]').addEventListener('click', () => { state.page--; loadItems(); }); $('[data-dmc-next]').addEventListener('click', () => { state.page++; loadItems(); });
  $('[data-dmc-cancel]').addEventListener('click', async () => { if (state.run) { state.run = (await json(`${root.dataset.runsUrl}${state.run.id}/cancel/`, {method:'POST', body:'{}'})).run; renderRun(); } });
  document.addEventListener('click', event => { const open = event.target.closest('[data-dmc-open]'); if (open) openItem(open.dataset.dmcOpen); const run = event.target.closest('[data-dmc-run]'); if (run) { json(`${root.dataset.runsUrl}${run.dataset.dmcRun}/`).then(payload => { state.run = payload.run; state.page = 1; renderRun(); loadItems(); }); } });
  document.addEventListener('submit', event => { if (event.target.matches('[data-dmc-review-form]')) { event.preventDefault(); saveReview(event.target); } });
  const today = new Date(); const start = new Date(today.getFullYear(), today.getMonth(), 1); $('[data-dmc-filter="start_date"]').value = start.toISOString().slice(0,10); $('[data-dmc-filter="end_date"]').value = today.toISOString().slice(0,10);
  loadHistory();
})();
