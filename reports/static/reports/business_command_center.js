(() => {
  const root = document.querySelector('[data-command-center]');
  if (!root) return;
  const $ = (selector, parent = root) => parent.querySelector(selector);
  const $$ = (selector, parent = root) => [...parent.querySelectorAll(selector)];
  const csrf = $('[name=csrfmiddlewaretoken]')?.value || '';
  const colors = { machine: '#ffd400', parts: '#3978d4', service: '#178b7b', rental: '#7657ad', unclassified: '#8b94a7' };
  const state = { data: null, dimension: 'customers', salesTab: 'lines', limit: 10, controller: null, exportBound: false };

  const money = (value, exact = false) => {
    if (value === null || value === undefined) return 'Not available';
    if (exact) return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(value);
    const abs = Math.abs(value); const sign = value < 0 ? '-' : '';
    if (abs >= 1e9) return `${sign}EUR ${(abs / 1e9).toFixed(1)}B`;
    if (abs >= 1e6) return `${sign}EUR ${(abs / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `${sign}EUR ${(abs / 1e3).toFixed(0)}K`;
    return `${sign}EUR ${abs.toFixed(0)}`;
  };
  const percent = value => value === null || value === undefined ? 'Not available' : `${value > 0 ? '+' : ''}${Number(value).toFixed(1)}%`;
  const dateLabel = value => value ? new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`)) : 'Not available';
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const params = () => {
    const output = new URLSearchParams(location.search);
    $$('[data-filter]').forEach(control => control.value ? output.set(control.dataset.filter, control.value) : output.delete(control.dataset.filter));
    return output;
  };
  const syncControlsFromUrl = () => {
    const query = new URLSearchParams(location.search);
    $$('[data-filter]').forEach(control => { if (query.has(control.dataset.filter)) control.value = query.get(control.dataset.filter); });
    toggleCustomDates();
  };
  const updateUrl = query => history.replaceState({}, '', `${location.pathname}${query.toString() ? `?${query}` : ''}`);
  const toggleCustomDates = () => $$('[data-custom-date]').forEach(item => { item.hidden = $('[data-filter="period"]').value !== 'custom'; });
  const setLoading = loading => {
    $('[data-status]').hidden = !loading;
    $('[data-content]').hidden = loading || !$('[data-error]').hidden;
    if (loading) $('[data-status]').textContent = state.data ? 'Updating Revenue intelligence...' : 'Preparing your business view...';
  };

  function renderLineCards(rows, active) {
    $('[data-line-grid]').innerHTML = rows.filter(item => item.code !== 'unclassified').map(item => `
      <button class="bcc-line-card ${active === item.code ? 'active' : ''}" style="--accent:${colors[item.code]}" data-line="${item.code}" type="button">
        <header><span>${escapeHtml(item.label)}</span><small>#${item.rank}</small></header>
        <strong>${money(item.revenue)}</strong>
        <footer><span>${item.share === null ? 'Share unavailable' : `${item.share.toFixed(1)}% of Revenue`}</span><b class="${item.absolute_delta < 0 ? 'negative' : 'positive'}">${percent(item.relative_delta)}</b></footer>
      </button>`).join('');
    $$('[data-line]').forEach(button => button.addEventListener('click', () => { $('[data-filter="business_line"]').value = button.dataset.line; refresh(); }));
  }

  function polyline(rows, width, height, pad) {
    if (!rows.length) return '';
    const values = rows.map(item => Number(item.value || 0)); const min = Math.min(...values); const max = Math.max(...values); const spread = max - min || 1;
    return rows.map((item, index) => `${pad + index * ((width - pad * 2) / Math.max(rows.length - 1, 1))},${height - pad - ((Number(item.value || 0) - min) / spread) * (height - pad * 2)}`).join(' ');
  }

  function renderCharts(data) {
    const heroPoints = polyline(data.trend, 560, 150, 12);
    $('[data-hero-chart]').innerHTML = heroPoints ? `<defs><linearGradient id="heroFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd400" stop-opacity=".28"/><stop offset="1" stop-color="#ffd400" stop-opacity="0"/></linearGradient></defs><polyline points="${heroPoints}" fill="none" stroke="#ffd400" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><polyline points="12,138 ${heroPoints} 548,138" fill="url(#heroFill)" stroke="none"/>` : '<text x="20" y="75" fill="#aeb9cf">Trend not available</text>';
    const current = polyline(data.trend, 760, 300, 35); const previous = polyline(data.comparison_trend, 760, 300, 35);
    const grid = [55, 115, 175, 235].map(y => `<line x1="35" y1="${y}" x2="725" y2="${y}" stroke="#e8ebf0"/>`).join('');
    $('[data-trend-chart]').innerHTML = `${grid}${previous ? `<polyline points="${previous}" fill="none" stroke="#aeb8c9" stroke-width="2" stroke-dasharray="7 6"/>` : ''}${current ? `<polyline points="${current}" fill="none" stroke="#d9b400" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>` : '<text x="35" y="150">Trend not available</text>'}`;
    const total = data.mix.reduce((sum, item) => sum + Number(item.revenue || 0), 0);
    $('[data-mix-bar]').innerHTML = data.mix.map(item => `<i class="bcc-mix-segment" style="width:${total ? Math.max(0, item.revenue / total * 100) : 0}%;background:${colors[item.code]}"></i>`).join('');
    $('[data-mix-list]').innerHTML = data.mix.map(item => `<div class="bcc-mix-item"><i style="background:${colors[item.code]}"></i><span>${escapeHtml(item.label)} <small>${item.share === null ? '' : `${item.share}%`}</small></span><strong>${money(item.revenue)}</strong></div>`).join('');
    const maxBridge = Math.max(1, ...data.bridge.map(item => Math.abs(item.delta || 0)));
    $('[data-bridge]').innerHTML = data.bridge.map(item => `<div class="bcc-bridge-row ${item.delta < 0 ? 'negative' : ''}"><span>${escapeHtml(item.label)}</span><div class="bcc-bridge-track"><i style="width:${Math.abs(item.delta || 0) / maxBridge * 100}%"></i></div><b>${money(item.delta)}</b></div>`).join('');
    const exportTarget = $('.bcc-chart-card');
    if (!state.exportBound && window.Mining360VisualExport && exportTarget) {
      exportTarget.dataset.exportReady = 'true';
      window.Mining360VisualExport.bindCopyAction({
        button: $('[data-copy="trend"]'), target: exportTarget,
        fileName: 'Mining360_Revenue_Trend', background: '#ffffff', scale: 2,
      });
      state.exportBound = true;
    }
  }

  function changeItem(item, personal = false) {
    const delta = item.absolute_delta ?? 0;
    return `<button class="bcc-change-item" type="button" data-change-entity="${escapeHtml(item.entity_id || '')}"><span class="marker">${delta < 0 ? '&#8595;' : '&#8593;'}</span><span><strong>${escapeHtml(item.entity || item.title || 'Business movement')}</strong><small>${personal ? 'Since your previous snapshot' : `${money(item.current_value)} vs ${money(item.comparison_value)}`}</small></span><b class="${delta < 0 ? 'negative' : ''}">${money(delta)}</b></button>`;
  }

  function renderDimension() {
    const rows = state.data.dimensions[state.dimension] || [];
    $('[data-dimension-table]').innerHTML = rows.slice(0, state.limit).map(item => {
      const mix = item.business_line_mix || {}; const mixTotal = Object.values(mix).reduce((a, b) => a + Number(b || 0), 0);
      const bars = ['machine','parts','service','rental'].map(code => `<i style="width:${mixTotal ? Math.max(0, Number(mix[code] || 0) / mixTotal * 100) : 0}%;background:${colors[code]}"></i>`).join('');
      return `<tr tabindex="0" data-entity-id="${escapeHtml(item.id)}"><td><span class="bcc-rank">${item.rank}</span></td><td><strong>${escapeHtml(item.name || 'Not available')}</strong></td><td>${money(item.revenue)}</td><td>${item.share === null ? 'Not available' : `${item.share}%`}</td><td>${money(item.previous_revenue)}</td><td class="${item.absolute_delta < 0 ? 'negative' : 'positive'}">${money(item.absolute_delta)}<br><small>${percent(item.relative_delta)}</small></td><td><span class="bcc-mini-mix">${bars}</span></td><td><button class="bcc-icon-btn" type="button" title="Open details">&#8594;</button></td></tr>`;
    }).join('') || '<tr><td colspan="8">Not available until a Mapping version is Published.</td></tr>';
    $$('[data-entity-id]').forEach(row => { row.addEventListener('click', () => openEntity(row.dataset.entityId)); row.addEventListener('keydown', e => { if (e.key === 'Enter') openEntity(row.dataset.entityId); }); });
  }

  function renderSalesReview() {
    const sales = state.data?.sales_review;
    if (!sales) return;
    const summary = sales.summary || {};
    $('[data-sales-summary]').innerHTML = [
      ['Actual Revenue', money(summary.actual_revenue)],
      [state.data.context.comparison_label, money(summary.comparison_revenue)],
      ['Absolute Change', money(summary.absolute_delta)],
      ['Growth', percent(summary.relative_delta)],
    ].map(([label, value], index) => `<div class="bcc-sales-metric ${index > 1 && Number(summary.absolute_delta) < 0 ? 'negative' : ''}"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>`).join('');
    $('[data-sales-budget-status]').innerHTML = `<strong>Budget:</strong> ${escapeHtml(sales.budget?.status === 'NOT_AVAILABLE' ? 'Not available' : sales.budget?.status || 'Not evaluated')}`;
    $('[data-sales-orders-status]').innerHTML = `<strong>Firm Orders:</strong> ${escapeHtml(sales.firm_orders?.status === 'NOT_AVAILABLE' ? 'Not available' : sales.firm_orders?.status || 'Not evaluated')}`;

    if (state.salesTab === 'lines') {
      $('[data-sales-head]').innerHTML = '<tr><th>Rank</th><th>Business Line</th><th>Actual</th><th>Comparison</th><th>Absolute Change</th><th>Growth</th><th>Share</th></tr>';
      $('[data-sales-body]').innerHTML = (sales.by_business_line || []).filter(row => row.code !== 'unclassified').map(row => `<tr><td><span class="bcc-rank">${row.rank}</span></td><td><strong>${escapeHtml(row.label)}</strong></td><td>${money(row.revenue)}</td><td>${money(row.comparison_revenue)}</td><td class="${row.absolute_delta < 0 ? 'negative' : 'positive'}">${money(row.absolute_delta)}</td><td class="${row.relative_delta < 0 ? 'negative' : 'positive'}">${percent(row.relative_delta)}</td><td>${row.share === null ? 'Not available' : `${row.share.toFixed(1)}%`}</td></tr>`).join('');
      return;
    }
    const rows = state.salesTab === 'countries' ? sales.by_country : sales.by_customer;
    $('[data-sales-head]').innerHTML = `<tr><th>Rank</th><th>${state.salesTab === 'countries' ? 'Country' : 'Canonical Customer'}</th><th>Actual</th><th>Comparison</th><th>Absolute Change</th><th>Growth</th><th>Share</th></tr>`;
    $('[data-sales-body]').innerHTML = (rows || []).map(row => `<tr><td><span class="bcc-rank">${row.rank}</span></td><td><strong>${escapeHtml(row.name || 'Not available')}</strong></td><td>${money(row.revenue)}</td><td>${money(row.previous_revenue)}</td><td class="${row.absolute_delta < 0 ? 'negative' : 'positive'}">${money(row.absolute_delta)}</td><td class="${row.relative_delta < 0 ? 'negative' : 'positive'}">${percent(row.relative_delta)}</td><td>${row.share === null ? 'Not available' : `${row.share.toFixed(1)}%`}</td></tr>`).join('') || '<tr><td colspan="7">Published Mapping data is not available for this dimension.</td></tr>';
  }

  function openEntity(id) {
    const item = (state.data.dimensions[state.dimension] || []).find(row => String(row.id) === String(id)); if (!item) return;
    const type = state.dimension === 'customers' ? 'Customer' : state.dimension === 'countries' ? 'Country' : 'Key Account';
    $('[data-drawer-kicker]').textContent = `${type} 360`;
    $('[data-drawer-title]').textContent = item.name || type;
    $('[data-drawer-body]').innerHTML = `<div class="bcc-detail-grid"><div class="bcc-detail-metric"><span>Revenue</span><strong>${money(item.revenue, true)}</strong></div><div class="bcc-detail-metric"><span>Share</span><strong>${item.share ?? 'Not available'}${item.share === null ? '' : '%'}</strong></div><div class="bcc-detail-metric"><span>Previous period</span><strong>${money(item.previous_revenue, true)}</strong></div><div class="bcc-detail-metric"><span>Change</span><strong>${money(item.absolute_delta, true)} · ${percent(item.relative_delta)}</strong></div></div><h3>Business Line Mix</h3>${Object.entries(item.business_line_mix || {}).map(([key,value]) => `<div class="bcc-watch-item"><span>${escapeHtml(key)}</span><strong>${money(value)}</strong></div>`).join('')}<p class="bcc-empty">Published Mapping version ${state.data.context.published_mapping_version || 'not available'}.</p>${root.dataset.features.includes('"watchlist":true') ? `<button class="bcc-button" type="button" data-add-watch>Add to Watchlist</button>` : ''}`;
    $('[data-drawer]').hidden = false; document.body.style.overflow = 'hidden'; $('[data-drawer-close]').focus();
    $('[data-add-watch]')?.addEventListener('click', () => addWatchlist(type.toLowerCase().replace(' ', '_'), item));
  }

  function render(data) {
    $('[data-content]').hidden = false; $('[data-status]').hidden = true; $('[data-error]').hidden = true;
    $('[data-mode-warning]').hidden = data.mapping_ready;
    $('[data-ribbon="mapping"]').textContent = data.context.published_mapping_version ? `Version ${data.context.published_mapping_version}` : 'Not published';
    $('[data-ribbon="data"]').textContent = `Through ${dateLabel(data.freshness.data_through_date)}`;
    $('[data-ribbon="snapshot"]').textContent = dateLabel(data.freshness.data_through_date);
    $('[data-ribbon="currency"]').textContent = data.context.currency;
    $('[data-ribbon="confidence"]').textContent = data.confidence.status;
    $('[data-hero-label]').textContent = data.context.business_line === 'all_business' ? 'Total Mining Revenue' : `${data.business_lines.find(item => item.code === data.context.business_line)?.label || ''} Revenue`;
    $('[data-hero-value]').textContent = money(data.hero.revenue);
    $('[data-period-label]').textContent = data.context.period_label;
    $('[data-hero-growth]').textContent = `${percent(data.hero.relative_delta)} vs ${data.context.comparison_label}`;
    $('[data-hero-absolute]').textContent = `${money(data.hero.absolute_delta)} absolute change`;
    $('[data-hero-contributor]').textContent = `Top contributor: ${data.hero.top_contributor || 'Not available'}`;
    renderLineCards(data.business_lines, data.context.business_line); renderCharts(data); renderSalesReview();
    $('[data-changes]').innerHTML = data.changes.map(item => changeItem(item)).join('') || '<p class="bcc-empty">No validated movement is available for this comparison.</p>';
    const visits = data.since_last_visit?.items || [];
    $('[data-last-visit]').innerHTML = visits.map(item => changeItem(item, true)).join('') || '<p class="bcc-empty">No new governed Revenue snapshot since your previous visit.</p>';
    $('[data-last-visit-section]').hidden = !JSON.parse(root.dataset.features).last_visit;
    renderDimension();
    $('[data-attention]').innerHTML = data.attention_items.map(item => `<button class="bcc-attention-item ${String(item.severity).toLowerCase()}" type="button"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.entity)} · ${money(item.impact)}</p><small>${escapeHtml(item.severity)} attention</small></button>`).join('') || '<p class="bcc-empty">No governed attention signal matches this context.</p>';
    $('[data-watchlist]').innerHTML = data.watchlist.map(item => `<div class="bcc-watch-item"><span>${escapeHtml(item.display_name)}</span><button class="bcc-text-button" data-remove-watch="${item.id}">Remove</button></div>`).join('') || '<p class="bcc-empty">Your watchlist is empty. Add an entity from a detail drawer.</p>';
    $$('[data-remove-watch]').forEach(button => button.addEventListener('click', () => removeWatchlist(button.dataset.removeWatch)));
    Object.entries(data.actions_summary).forEach(([key,value]) => { const node = $(`[data-action="${key}"]`); if (node) node.textContent = value; });
    $('[data-confidence-summary]').textContent = data.confidence.warnings.length ? data.confidence.warnings.join(' ') : 'Published Revenue passed the configured confidence checks.';
    populateOptions(data.filter_options); renderChips();
  }

  function populateOptions(options) {
    const maps = { country_ids: options.countries, customer_ids: options.customers, key_account_ids: options.key_accounts };
    Object.entries(maps).forEach(([key, rows]) => {
      const select = $(`[data-filter="${key}"]`); const current = select.value; const all = key === 'country_ids' ? 'All Countries' : key === 'customer_ids' ? 'All Customers' : 'All Key Accounts';
      select.innerHTML = `<option value="">${all}</option>${rows.sort((a,b) => String(a.name).localeCompare(String(b.name))).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('')}`; select.value = current;
      select.closest('label').hidden = !rows.length;
    });
  }

  function renderChips() {
    const labels = { business_line: 'Line', country_ids: 'Country', customer_ids: 'Customer', key_account_ids: 'Key Account' };
    $('[data-filter-chips]').innerHTML = Object.entries(labels).map(([key,label]) => { const control = $(`[data-filter="${key}"]`); if (!control?.value || (key === 'business_line' && control.value === 'all_business')) return ''; return `<button data-clear-filter="${key}">${label}: ${escapeHtml(control.selectedOptions[0]?.textContent || control.value)} &times;</button>`; }).join('');
    $$('[data-clear-filter]').forEach(button => button.addEventListener('click', () => { $(`[data-filter="${button.dataset.clearFilter}"]`).value = button.dataset.clearFilter === 'business_line' ? 'all_business' : ''; refresh(); }));
  }

  async function refresh() {
    toggleCustomDates(); const query = params(); updateUrl(query); state.controller?.abort(); state.controller = new AbortController(); setLoading(true); $('[data-error]').hidden = true;
    try {
      const response = await fetch(`${root.dataset.bootstrapUrl}?${query}`, { signal: state.controller.signal, headers: { Accept: 'application/json' } });
      const data = await response.json(); if (!response.ok) throw new Error(data.message || 'Revenue data is temporarily unavailable.');
      state.data = data; render(data);
    } catch (error) {
      if (error.name === 'AbortError') return;
      $('[data-status]').hidden = true; $('[data-content]').hidden = true; $('[data-error]').hidden = false; $('[data-error-message]').textContent = error.message;
    }
  }

  async function addWatchlist(type, item) { await fetch(root.dataset.watchlistUrl, { method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify({entity_type:type,entity_id:item.id,display_name:item.name}) }); closeDrawer(); refresh(); }
  async function removeWatchlist(id) { await fetch(root.dataset.watchlistUrl, { method:'DELETE', headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify({id}) }); refresh(); }
  function closeDrawer(){ $('[data-drawer]').hidden = true; document.body.style.overflow = ''; }

  $$('[data-filter]').forEach(control => control.addEventListener('change', () => { if ($('[data-filter="period"]').value !== 'custom' || ( $('[data-filter="start_date"]').value && $('[data-filter="end_date"]').value )) refresh(); else toggleCustomDates(); }));
  $('[data-reset]').addEventListener('click', () => { history.replaceState({},'',location.pathname); $$('[data-filter]').forEach(control => control.value = control.dataset.filter === 'period' ? 'ytd' : control.dataset.filter === 'comparison' ? 'same_period_last_year' : control.dataset.filter === 'business_line' ? 'all_business' : ''); refresh(); });
  $('[data-refresh]').addEventListener('click', refresh); $('[data-retry]').addEventListener('click', refresh);
  $$('[data-dimension]').forEach(button => button.addEventListener('click', () => { state.dimension=button.dataset.dimension; state.limit=10; $$('[data-dimension]').forEach(item=>item.classList.toggle('active',item===button)); renderDimension(); }));
  $$('[data-sales-tab]').forEach(button => button.addEventListener('click', () => { state.salesTab=button.dataset.salesTab; $$('[data-sales-tab]').forEach(item=>item.classList.toggle('active',item===button)); renderSalesReview(); }));
  $('[data-show-all]').addEventListener('click', () => { state.limit = state.limit === 10 ? 25 : 10; $('[data-show-all]').textContent = state.limit === 10 ? 'Show Top 25' : 'Show Top 10'; renderDimension(); });
  $('[data-drawer-close]').addEventListener('click', closeDrawer); document.addEventListener('keydown', event => { if(event.key==='Escape') closeDrawer(); });
  $$('[data-confidence-open]').forEach(button => button.addEventListener('click', () => { const c=state.data?.confidence;if(!c)return;$('[data-drawer-kicker]').textContent='Trust layer';$('[data-drawer-title]').textContent=`Data Confidence: ${c.status}`;$('[data-drawer-body]').innerHTML=`<div class="bcc-detail-grid"><div class="bcc-detail-metric"><span>Customer coverage</span><strong>${c.customer_coverage===null?'Not available':c.customer_coverage.toFixed(1)+'%'}</strong></div><div class="bcc-detail-metric"><span>Country coverage</span><strong>${c.country_coverage===null?'Not available':c.country_coverage.toFixed(1)+'%'}</strong></div><div class="bcc-detail-metric"><span>Key Account coverage</span><strong>${c.key_account_coverage===null?'Not available':c.key_account_coverage.toFixed(1)+'%'}</strong></div><div class="bcc-detail-metric"><span>Unallocated Revenue</span><strong>${money(c.unallocated_revenue,true)}</strong></div></div><h3>Limitations</h3>${c.warnings.map(w=>`<p>${escapeHtml(w)}</p>`).join('')||'<p>No governed limitation is currently reported.</p>'}`;$('[data-drawer]').hidden=false;document.body.style.overflow='hidden'; }));
  $('[data-presentation]')?.addEventListener('click', () => { document.body.classList.toggle('presentation'); if(document.body.classList.contains('presentation')) document.documentElement.requestFullscreen?.().catch(()=>{}); else document.exitFullscreen?.().catch(()=>{}); });
  $('[data-save-view]').addEventListener('click', async () => {
    const name = window.prompt('Saved view name', 'My Business Command Center'); if (!name) return;
    await fetch(root.dataset.savedViewsUrl, { method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify({name,filters:Object.fromEntries(params()),visualization:'business_command_center'}) });
    $('[data-save-view]').textContent = 'View Saved'; window.setTimeout(() => $('[data-save-view]').textContent='Save View', 1800);
  });
  $('[data-export]')?.addEventListener('click', () => { window.location.href = `${root.dataset.exportUrl}?${params()}`; });
  $('[data-mark-reviewed]').addEventListener('click', async () => {
    const hash=state.data?.since_last_visit?.filter_hash;if(hash) await fetch(root.dataset.bootstrapUrl.replace('/bootstrap/','/mark-reviewed/'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({filter_hash:hash})});
    $('[data-last-visit]').innerHTML='<p class="bcc-empty">Current changes marked as reviewed.</p>';
  });
  window.addEventListener('popstate', () => { syncControlsFromUrl(); refresh(); });
  syncControlsFromUrl(); refresh();
})();
