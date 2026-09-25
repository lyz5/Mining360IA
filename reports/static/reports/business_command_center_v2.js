(() => {
  const root = document.querySelector('[data-command-center]');
  if (!root) return;
  const $ = (selector, parent = root) => parent.querySelector(selector);
  const $$ = (selector, parent = root) => [...parent.querySelectorAll(selector)];
  const setHidden = (selector, hidden) => {
    const node = $(selector);
    if (node) node.hidden = hidden;
    return node;
  };
  const csrf = $('[name=csrfmiddlewaretoken]')?.value || '';
  const features = JSON.parse(root.dataset.features || '{}');
  const colors = { machine: '#ffd400', parts: '#3478c9', service: '#168b79', rental: '#7453a6', unclassified: '#8993a5' };
  const countryNames = { BF: 'Burkina Faso', BJ: 'Benin', CI: "Côte d’Ivoire", CM: 'Cameroon', FR: 'France', GN: 'Guinea', GW: 'Guinea-Bissau', ML: 'Mali', MR: 'Mauritania', MU: 'Mauritius', NE: 'Niger', SN: 'Senegal', TG: 'Togo' };
  const state = {
    data: null, workspace: 'executive', dimension: 'customers', trendMode: 'ytd',
    operation: 'machine', controller: null, explorerController: null, explorerLoaded: false,
    turnoverController: null, turnoverLoaded: false, leadersController: null,
    machineController: null, machineLoaded: false, machinePage: 1, machinePages: 1,
    partsController: null, partsLoaded: false, partsPage: 1, partsPages: 1,
    selectedLabels: { key_account_ids: '' }, searchTimers: {}, exportBound: false,
  };

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const money = (value, exact = false) => {
    if (value === null || value === undefined) return 'Not available';
    if (exact) return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(value);
    const absolute = Math.abs(Number(value)); const sign = Number(value) < 0 ? '-' : '';
    if (absolute >= 1e9) return `${sign}€${(absolute / 1e9).toFixed(1)}B`;
    if (absolute >= 1e6) return `${sign}€${(absolute / 1e6).toFixed(1)}M`;
    if (absolute >= 1e3) return `${sign}€${(absolute / 1e3).toFixed(0)}K`;
    return `${sign}€${absolute.toFixed(0)}`;
  };
  const growth = item => {
    if (item?.growth_status === 'new') return 'New';
    if (item?.growth_status === 'no_change') return 'No change';
    if (item?.growth_status === 'not_meaningful') return 'Not meaningful';
    if (item?.relative_delta === null || item?.relative_delta === undefined) return 'Not available';
    return `${item.relative_delta > 0 ? '+' : ''}${Number(item.relative_delta).toFixed(1)}%`;
  };
  const dateLabel = value => value ? new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`)) : 'Not available';
  const dateTimeLabel = value => value ? new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : 'Not available';
  const monthLabel = value => value ? new Intl.DateTimeFormat('en-GB', { month: 'short' }).format(new Date(`${value}T00:00:00`)) : '';
  const queryParams = () => {
    const query = new URLSearchParams();
    const customRange = $('[data-filter="period"]').value === 'custom';
    $$('[data-filter]').forEach(control => {
      if (['start_date', 'end_date'].includes(control.dataset.filter) && !customRange) return;
      if (control.value) query.set(control.dataset.filter, control.value);
    });
    query.set('view', state.workspace);
    return query;
  };
  const apiParams = () => { const query = queryParams(); query.delete('view'); return query; };
  const updateUrl = (push = false) => {
    const query = queryParams();
    history[push ? 'pushState' : 'replaceState']({}, '', `${location.pathname}?${query}`);
  };
  const syncFromUrl = () => {
    const query = new URLSearchParams(location.search);
    $$('[data-filter]').forEach(control => { if (query.has(control.dataset.filter)) control.value = query.get(control.dataset.filter); });
    state.workspace = ['executive', 'explore', 'operations', 'actions'].includes(query.get('view')) ? query.get('view') : 'executive';
    $('[data-division-toggle]').checked = $('[data-filter="division_scope"]').value === 'all_divisions';
    toggleCustomDates();
  };
  const toggleCustomDates = () => {
    const customRange = $('[data-filter="period"]').value === 'custom';
    $$('[data-custom-date]').forEach(node => {
      node.hidden = !customRange;
      const input = node.querySelector('input');
      if (input) input.disabled = !customRange;
    });
  };
  const syncCustomDateBounds = data => {
    const maximum = data?.freshness?.data_through_date || '';
    const start = $('[data-filter="start_date"]');
    const end = $('[data-filter="end_date"]');
    if (!maximum || !start || !end) return;
    start.max = maximum;
    end.max = maximum;
    if (start.value > maximum) start.value = maximum;
    if (!end.value || end.value > maximum) end.value = maximum;
  };
  const initializeCustomRange = () => {
    if ($('[data-filter="period"]').value !== 'custom' || !state.data) return;
    const start = $('[data-filter="start_date"]');
    const end = $('[data-filter="end_date"]');
    const maximum = state.data.freshness?.data_through_date || state.data.context.end_date;
    if (!start.value) start.value = state.data.context.start_date;
    if (!end.value || (maximum && end.value > maximum)) end.value = maximum;
    syncCustomDateBounds(state.data);
  };
  const setUpdating = updating => {
    root.classList.toggle('is-updating', updating);
    root.setAttribute('aria-busy', String(updating));
    setHidden('[data-update-loader]', !updating);
    const status = setHidden('[data-status]', Boolean(state.data) || !updating);
    if (status && updating && !state.data) status.textContent = 'Preparing your business view...';
  };

  function renderLineCards(rows, active) {
    $('[data-line-grid]').innerHTML = rows.filter(item => item.code !== 'unclassified').map(item => {
      const movement = item.absolute_delta > 0 ? 'Growth contributor' : item.absolute_delta < 0 ? 'Revenue decline' : 'No material movement';
      return `<button class="bcc-line-card ${active === item.code ? 'active' : ''}" style="--accent:${colors[item.code]}" data-line="${item.code}" type="button"><header><span>${escapeHtml(item.label)}</span><small>#${item.rank}</small></header><strong>${money(item.revenue)}</strong><footer><span>${item.share === null ? 'Share unavailable' : `${item.share.toFixed(1)}% of Revenue`}</span><b class="${item.absolute_delta < 0 ? 'negative' : 'positive'}">${growth(item)}</b></footer><small class="bcc-line-movement">${movement} · ${money(item.absolute_delta)}</small></button>`;
    }).join('');
    $$('[data-line]').forEach(button => button.addEventListener('click', () => {
      const filter = $('[data-filter="business_line"]');
      filter.value = filter.value === button.dataset.line ? 'all_business' : button.dataset.line;
      refresh();
    }));
  }

  const cumulative = rows => { let total = 0; return rows.map(row => ({ ...row, value: total += Number(row.value || 0) })); };
  function pointSet(rows, width, height, padX, padY, minimum, maximum) {
    if (!rows.length) return [];
    const spread = maximum - minimum || 1;
    return rows.map((item, index) => ({
      ...item,
      x: padX + index * ((width - padX * 2) / Math.max(rows.length - 1, 1)),
      y: height - padY - ((Number(item.value || 0) - minimum) / spread) * (height - padY * 2),
    }));
  }
  const points = rows => rows.map(item => `${item.x.toFixed(1)},${item.y.toFixed(1)}`).join(' ');

  function renderTrend(data) {
    const usesDailyGrain = state.trendMode === 'mtd' || state.trendMode === 'daily';
    const currentSource = usesDailyGrain ? (data.daily_trend || []) : data.trend;
    const currentRows = state.trendMode === 'mtd' ? cumulative(currentSource) : currentSource;
    const currentTotal = state.trendMode === 'mtd'
      ? Number(currentRows.at(-1)?.value || 0)
      : currentRows.reduce((sum, row) => sum + Number(row.value || 0), 0);
    $('[data-trend-total-label]').textContent = `${state.trendMode.toUpperCase()} Total`;
    $('[data-trend-total]').textContent = money(currentTotal);
    $('[data-trend-total]').title = money(currentTotal, true);
    const values = currentRows.map(row => Number(row.value || 0));
    const minimum = Math.min(0, ...values); const maximum = Math.max(1, ...values);
    const current = pointSet(currentRows, 760, 260, 48, 34, minimum, maximum);
    const grids = [0, .5, 1].map(fraction => {
      const y = 226 - fraction * 192; const value = minimum + fraction * (maximum - minimum);
      return `<line class="bcc-trend-grid-line" x1="48" y1="${y}" x2="730" y2="${y}"/><text class="bcc-trend-axis-label" x="4" y="${y + 4}">${money(value)}</text>`;
    }).join('');
    const axisLabel = value => usesDailyGrain ? new Date(`${value}T00:00:00`).getDate() : monthLabel(value);
    const labels = current.filter((_, index) => current.length <= 12 || index % 2 === 0 || index === current.length - 1).map(item => `<text class="bcc-trend-axis-label" x="${item.x}" y="250" text-anchor="middle">${axisLabel(item.date)}</text>`).join('');
    const valueLabels = current.filter((_, index) => current.length <= 16 || index % 2 === 0 || index === current.length - 1).map((item, index) => `<text class="bcc-trend-value-label" x="${item.x}" y="${Math.max(13, item.y - (index % 2 ? 14 : 9))}" text-anchor="middle">${money(item.value)}</text>`).join('');
    const linePath = current.map((item, index) => `${index ? 'L' : 'M'}${item.x.toFixed(1)},${item.y.toFixed(1)}`).join(' ');
    const areaPath = current.length ? `${linePath} L${current.at(-1).x.toFixed(1)},226 L${current[0].x.toFixed(1)},226 Z` : '';
    const selected = current.length ? `<path class="bcc-trend-area" d="${areaPath}"/><path class="bcc-trend-line" d="${linePath}"/>${current.map((item, index) => `<circle class="bcc-trend-point" tabindex="0" data-revenue-trend-index="${index}" cx="${item.x}" cy="${item.y}" r="${index === current.length - 1 ? 5 : 4}"><title>${axisLabel(item.date)}: ${money(item.value, true)}</title></circle>`).join('')}${valueLabels}` : '<text x="380" y="130" text-anchor="middle" fill="#77839a">Trend not available</text>';
    $('[data-trend-chart]').innerHTML = `${grids}${labels}${selected}`;
    $('[data-trend-table]').innerHTML = currentRows.map(item => `<tr><td>${escapeHtml(usesDailyGrain ? dateLabel(item.date) : monthLabel(item.date))}</td><td>${money(item.value, true)}</td></tr>`).join('');
    const periodText = item => usesDailyGrain ? dateLabel(item.date) : monthLabel(item.date);
    if (currentRows.length) {
      const latest = currentRows.at(-1);
      const highest = currentRows.reduce((best, item) => Number(item.value) > Number(best.value) ? item : best);
      const lowest = currentRows.reduce((best, item) => Number(item.value) < Number(best.value) ? item : best);
      $('[data-trend-statistics]').innerHTML = `<div><span>Latest</span><strong>${money(latest.value)}</strong><small>${periodText(latest)}</small></div><div><span>Highest period</span><strong>${money(highest.value)}</strong><small>${periodText(highest)}</small></div><div><span>Lowest period</span><strong>${money(lowest.value)}</strong><small>${periodText(lowest)}</small></div>`;
    } else $('[data-trend-statistics]').innerHTML = '';
    const tooltip = $('[data-trend-tooltip]');
    $$('[data-revenue-trend-index]').forEach(node => {
      const show = () => {
        const item = currentRows[Number(node.dataset.revenueTrendIndex)];
        tooltip.textContent = `${periodText(item)}: ${money(item.value, true)}`;
        tooltip.style.left = `${Number(node.getAttribute('cx')) / 760 * 100}%`;
        tooltip.style.top = `${Number(node.getAttribute('cy')) / 260 * 100}%`;
        tooltip.hidden = false;
      };
      node.addEventListener('mouseenter', show); node.addEventListener('focus', show);
      node.addEventListener('mouseleave', () => { tooltip.hidden = true; }); node.addEventListener('blur', () => { tooltip.hidden = true; });
    });
  }

  function renderWaterfall(data) {
    const start = Number(data.hero.comparison_revenue || 0); const end = Number(data.hero.revenue || 0);
    let running = start;
    const steps = [{ label: 'Comparison', start: 0, end: start, total: true }];
    data.bridge.forEach(item => { const before = running; running += Number(item.delta || 0); steps.push({ label: item.label, start: before, end: running, delta: Number(item.delta || 0), code: item.code }); });
    steps.push({ label: 'Current', start: 0, end, total: true });
    const values = steps.flatMap(item => [item.start, item.end]); const min = Math.min(0, ...values); const max = Math.max(1, ...values); const range = max - min || 1;
    const y = value => 205 - ((value - min) / range) * 165; const width = 86; const gap = (700 - width * steps.length) / Math.max(steps.length - 1, 1);
    $('[data-waterfall]').innerHTML = `<line x1="30" y1="205" x2="735" y2="205" stroke="#dfe4eb"/>${steps.map((item, index) => {
      const x = 35 + index * (width + gap); const top = Math.min(y(item.start), y(item.end)); const height = Math.max(2, Math.abs(y(item.start) - y(item.end))); const fill = item.total ? '#10162f' : item.delta < 0 ? '#b43f49' : colors[item.code] || '#17765a';
      return `<rect x="${x}" y="${top}" width="${width}" height="${height}" fill="${fill}" rx="2"><title>${item.label}: ${money(item.total ? item.end : item.delta, true)}</title></rect><text x="${x + width / 2}" y="224" text-anchor="middle" fill="#68748a" font-size="9">${escapeHtml(item.label)}</text><text x="${x + width / 2}" y="${Math.max(13, top - 5)}" text-anchor="middle" fill="#243047" font-size="9" font-weight="700">${money(item.total ? item.end : item.delta)}</text>`;
    }).join('')}`;
  }

  function renderCharts(data) {
    const heroValues = data.trend.map(item => Number(item.value || 0)); const min = Math.min(...heroValues, 0); const max = Math.max(...heroValues, 1);
    const hero = pointSet(data.trend, 500, 150, 10, 12, min, max);
    $('[data-hero-chart]').innerHTML = hero.length ? `<polyline points="${points(hero)}" fill="none" stroke="#ffd400" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>` : '<text x="20" y="75" fill="#aeb9cf">Trend not available</text>';
    renderTrend(data);
    const total = data.mix.reduce((sum, item) => sum + Number(item.revenue || 0), 0);
    const positiveTotal = data.mix.reduce((sum, item) => sum + Math.max(0, Number(item.revenue || 0)), 0);
    let mixOffset = 0;
    const mixSegments = data.mix.filter(item => Number(item.revenue || 0) > 0).map(item => {
      const start = mixOffset; mixOffset += Number(item.revenue) / positiveTotal * 100;
      return `${colors[item.code] || colors.unclassified} ${start.toFixed(2)}% ${mixOffset.toFixed(2)}%`;
    });
    const mixLeader = [...data.mix].sort((a, b) => Number(b.revenue || 0) - Number(a.revenue || 0))[0];
    if ($('[data-mix-donut]')) {
      $('[data-mix-donut]').style.background = mixSegments.length ? `conic-gradient(${mixSegments.join(',')})` : '#e8ecf1';
      $('[data-mix-donut]').setAttribute('aria-label', data.mix.map(item => `${item.label}: ${money(item.revenue)}, ${item.share ?? 0}%`).join('. '));
      $('[data-mix-total]').textContent = money(total);
      $('[data-mix-leader]').textContent = mixLeader ? `${mixLeader.label} leads · ${Number(mixLeader.share || 0).toFixed(1)}%` : 'Top contributor unavailable';
      $('[data-mix-list]').innerHTML = data.mix.map(item => `<button class="bcc-mix-item" type="button" data-mix-line="${escapeHtml(item.code)}"><i style="background:${colors[item.code] || colors.unclassified}"></i><span><b>${escapeHtml(item.label)}</b><small>${item.share === null ? 'Share unavailable' : `${Number(item.share).toFixed(1)}% of Revenue`}</small><em><u style="width:${Math.max(0, Math.min(100, Number(item.share || 0)))}%;background:${colors[item.code] || colors.unclassified}"></u></em></span><strong>${money(item.revenue)}</strong></button>`).join('');
      $$('[data-mix-line]').forEach(button => button.addEventListener('click', () => { $('[data-filter="business_line"]').value = button.dataset.mixLine; refresh(); }));
    }
    if ($('[data-waterfall]')) renderWaterfall(data);
    if (!state.exportBound && window.Mining360VisualExport) {
      window.Mining360VisualExport.bindCopyAction({ button: $('[data-copy="trend"]'), target: $('[data-export-surface="trend"]'), fileName: 'Mining360_Revenue_Trend', background: '#ffffff', scale: 2 });
      state.exportBound = true;
    }
  }

  function changeItem(item, personal = false) {
    const delta = Number(item.absolute_delta || 0); const label = item.entity || item.title || 'Business movement';
    return `<button class="bcc-change-item" type="button" data-change-entity="${escapeHtml(item.entity_id || '')}"><span class="marker ${delta < 0 ? 'negative' : 'positive'}">${delta < 0 ? '&#8595;' : '&#8593;'}</span><span><strong>${escapeHtml(label)}</strong><small>${personal ? 'Latest data day movement' : `${money(item.current_value)} vs ${money(item.comparison_value)}`}</small></span><b class="${delta < 0 ? 'negative' : ''}">${money(delta)}${personal ? '' : ` · ${growth(item)}`}</b></button>`;
  }
  const attentionMarkup = rows => rows.map(item => `<button class="bcc-attention-item ${String(item.severity).toLowerCase()}" type="button"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.entity)} · ${money(item.impact)}</p><small>${escapeHtml(item.severity)} attention · observed change</small></button>`).join('') || '<p class="bcc-empty">No governed attention signal matches this context.</p>';

  function renderLeaders(rows, dimension) {
    const max = Math.max(1, ...rows.map(item => Number(item.revenue || 0)));
    $('[data-leaders-preview]').innerHTML = rows.map(item => `<button class="bcc-leader-row" type="button" data-preview-entity="${escapeHtml(item.id)}"><span class="rank">#${item.rank}</span><strong title="${escapeHtml(item.display_name || item.name || '')}">${escapeHtml(item.display_name || item.name || 'Not available')}</strong><b>${money(item.revenue)}</b><span class="bcc-leader-bar" aria-hidden="true"><i style="width:${Math.max(0, item.revenue / max * 100)}%"></i></span></button>`).join('') || '<p class="bcc-empty">Published Customer rankings are not available.</p>';
    if (!rows.length) $('[data-leaders-preview]').textContent = `Published ${dimension === 'key_accounts' ? 'Key Account' : 'Customer'} rankings are not available.`;
    $$('[data-preview-entity]').forEach(button => button.addEventListener('click', () => openEntity(button.dataset.previewEntity, dimension, rows)));
  }

  async function loadLeaders() {
    state.leadersController?.abort();
    const controller = new AbortController(); state.leadersController = controller;
    const list = $('[data-leaders-preview]'); const status = $('[data-leaders-status]');
    list.replaceChildren(); list.setAttribute('aria-busy', 'true');
    status.textContent = 'Loading Revenue Leaders...';
    const dimension = $('[data-leaders-dimension]').value;
    const query = apiParams(); query.set('dimension', dimension); query.set('ranking', 'revenue');
    query.set('limit', $('[data-leaders-limit]').value);
    try {
      const response = await fetch(`${root.dataset.explorerUrl}?${query}`, {signal: controller.signal, headers: {Accept: 'application/json'}});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Revenue Leaders are temporarily unavailable.');
      if (controller.signal.aborted) return;
      renderLeaders(payload.results, dimension);
      status.textContent = `${payload.results.length} of ${payload.count} ${dimension === 'key_accounts' ? 'key accounts' : 'customers'}`;
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = error.message;
    } finally {
      if (state.leadersController === controller) list.setAttribute('aria-busy', 'false');
    }
  }

  function render(data) {
    if (data.dashboard_snapshot) {
      const snapshot = data.dashboard_snapshot;
      $('[data-revenue-sync-status]').textContent = `BODEFM snapshot · ${dateTimeLabel(snapshot.generated_at)}${snapshot.offline ? ' · Server unavailable; showing the last received snapshot' : snapshot.stale ? ' · Daily update pending' : ''}`;
    }
    setHidden('[data-content]', false); setHidden('[data-status]', true); setHidden('[data-error]', true);
    setHidden('[data-mode-warning]', data.mapping_ready);
    syncCustomDateBounds(data);
    const comparisonControl = $('[data-filter="comparison"]');
    if (comparisonControl.value !== data.context.comparison) { comparisonControl.value = data.context.comparison; updateUrl(); }
    $('[data-ribbon="mapping"]').textContent = data.context.published_mapping_version ? `Published Mapping v${data.context.published_mapping_version}` : 'Mapping not published';
    $('[data-ribbon="data"]').textContent = `Revenue through ${dateLabel(data.freshness.data_through_date)} · Refreshed ${dateTimeLabel(data.freshness.source_snapshot_at)}`;
    $('[data-ribbon="currency"]').textContent = data.context.currency;
    $('[data-ribbon="confidence"]').textContent = data.confidence.status;
    $('[data-confidence-inline-value]').textContent = data.confidence.status;
    const selectedLine = data.business_lines.find(item => item.code === data.context.business_line);
    $('[data-filter="division_scope"]').value = data.context.division_scope;
    $('[data-division-toggle]').checked = data.context.division_scope === 'all_divisions';
    $('[data-sales-scope-warning]').hidden = data.context.division_scope !== 'all_divisions';
    $('[data-hero-label]').textContent = data.context.business_line === 'all_business' ? (data.context.division_scope === 'all_divisions' ? 'Total Revenue · All Divisions' : 'Total Mining Revenue') : `${selectedLine?.label || ''} Revenue`;
    $('[data-hero-value]').textContent = money(data.hero.revenue);
    $('[data-period-label]').textContent = data.context.period_label;
    $('[data-hero-growth]').textContent = `${growth(data.hero)} vs ${data.context.comparison_label}`;
    $('[data-hero-absolute]').textContent = `${money(data.hero.absolute_delta)} absolute change`;
    $('[data-hero-contributor]').textContent = `Top contributor · ${data.hero.top_contributor || 'Not available'}`;
    renderLineCards(data.business_lines, data.context.business_line); renderCharts(data);
    $('[data-changes]').innerHTML = data.changes.map(item => changeItem(item)).join('') || '<p class="bcc-empty">No validated movement is available.</p>';
    const yesterday = data.since_yesterday?.items || [];
    $('[data-since-yesterday]').innerHTML = yesterday.map(item => changeItem(item, true)).join('') || '<p class="bcc-empty">No Revenue movement is recorded on the latest data day.</p>';
    $('[data-yesterday-context]').textContent = data.since_yesterday ? `Revenue recorded on ${dateLabel(data.since_yesterday.through_date)} compared with data through ${dateLabel(data.since_yesterday.from_date)}.` : '';
    $('[data-brief-count="changes"]').textContent = data.changes.length;
    $('[data-brief-count="yesterday"]').textContent = yesterday.length;
    $('[data-brief-count="attention"]').textContent = data.attention_items.length;
    $('[data-attention]').innerHTML = attentionMarkup(data.attention_items);
    $('[data-actions-attention]').innerHTML = attentionMarkup(data.attention_items);
    loadLeaders();
    $('[data-watchlist]').innerHTML = data.watchlist.map(item => `<div class="bcc-watch-item"><span>${escapeHtml(item.display_name)}</span><button class="bcc-text-button" data-remove-watch="${item.id}">Remove</button></div>`).join('') || '<p class="bcc-empty">Add Customers, Countries or Key Accounts from a detail drawer.</p>';
    $$('[data-remove-watch]').forEach(button => button.addEventListener('click', () => removeWatchlist(button.dataset.removeWatch)));
    Object.entries(data.actions_summary).forEach(([key, value]) => { const node = $(`[data-action="${key}"]`); if (node) node.textContent = value; });
    const openActions = Number(data.actions_summary.open || 0); const actionsBadge = setHidden('[data-actions-badge]', !openActions); if (actionsBadge) actionsBadge.textContent = openActions;
    $('[data-actions-state]').textContent = openActions ? `${openActions} open management action${openActions === 1 ? '' : 's'} in this business snapshot.` : 'No open management action matches the current context.';
    populateOptions(data.filter_options); renderChips(); switchWorkspace(state.workspace, false);
  }

  function populateOptions(options) {
    const country = $('[data-filter="country_ids"]'); const selectedCountry = country.value;
    country.innerHTML = `<option value="">All Countries</option>${(options.countries || []).sort((a, b) => String(a.name).localeCompare(String(b.name))).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('')}`; country.value = selectedCountry;
    const keyFilter = $('[data-filter="key_account_ids"]');
    const selectedKey = (options.key_accounts || []).find(item => String(item.id) === String(keyFilter.value));
    if (selectedKey) state.selectedLabels.key_account_ids = selectedKey.name;
    $('[data-combobox="key_accounts"] [data-combobox-label]').textContent = state.selectedLabels.key_account_ids || 'All Key Accounts';
  }

  function renderChips() {
    const period = $('[data-filter="period"]'); const line = $('[data-filter="business_line"]'); const country = $('[data-filter="country_ids"]');
    const chips = [`<span>${escapeHtml(period.selectedOptions[0]?.textContent || 'YTD')}</span>`, `<span>${escapeHtml($('[data-filter="comparison"]').selectedOptions[0]?.textContent || '')}</span>`];
    if ($('[data-filter="division_scope"]').value === 'all_divisions') chips.push('<span>All Divisions</span>');
    if (line.value !== 'all_business') chips.push(`<button data-clear-filter="business_line">${escapeHtml(line.selectedOptions[0].textContent)} &times;</button>`);
    if (country.value) chips.push(`<button data-clear-filter="country_ids">${escapeHtml(country.selectedOptions[0].textContent)} &times;</button>`);
    if ($('[data-filter="key_account_ids"]').value) chips.push(`<button data-clear-filter="key_account_ids">${escapeHtml(state.selectedLabels.key_account_ids || 'Selected')} &times;</button>`);
    $('[data-filter-chips]').innerHTML = chips.join('');
    $$('[data-clear-filter]').forEach(button => button.addEventListener('click', () => { const key = button.dataset.clearFilter; $(`[data-filter="${key}"]`).value = key === 'business_line' ? 'all_business' : ''; if (key in state.selectedLabels) state.selectedLabels[key] = ''; refresh(); }));
    $('[data-filter-count]').textContent = $$('[data-filter]').filter(control => control.value && !['ytd', 'same_period_last_year', 'all_business', 'mining'].includes(control.value)).length;
  }

  async function refresh(forceRefresh = false) {
    state.leadersController?.abort();
    toggleCustomDates(); updateUrl(); state.controller?.abort(); state.controller = new AbortController(); setUpdating(true); setHidden('[data-error]', true);
    try {
      const query = apiParams(); if (forceRefresh === true) query.set("refresh", "1");
      const response = await fetch(`${root.dataset.bootstrapUrl}?${query}`, { signal: state.controller.signal, headers: { Accept: 'application/json' } });
      const data = await response.json(); if (!response.ok) throw new Error(data.message || 'Revenue data is temporarily unavailable.');
      if (state.data && state.data.context.context_id === data.context.context_id) { state.data = data; render(data); setUpdating(false); return; }
      state.data = data; state.explorerLoaded = false; state.turnoverLoaded = false; state.machineLoaded = false; state.partsLoaded = false; render(data); setUpdating(false);
    } catch (error) {
      if (error.name === 'AbortError') return;
      setUpdating(false); if (!state.data) setHidden('[data-content]', true); setHidden('[data-error]', false); const errorMessage = $('[data-error-message]'); if (errorMessage) errorMessage.textContent = error.message;
    }
  }

  function switchWorkspace(name, push = true) {
    state.workspace = name;
    $$('[data-workspace]').forEach(node => node.classList.toggle('active', node.dataset.workspace === name));
    $$('[data-workspace-tab]').forEach(button => button.classList.toggle('active', button.dataset.workspaceTab === name));
    updateUrl(push);
    if (name === 'explore' && !state.explorerLoaded) loadExplorer();
    if (name === 'turnover' && !state.turnoverLoaded) loadTurnover();
    if (name === 'operations') loadOperation(state.operation);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function dimensionRowsMarkup(rows) {
    return rows.map(item => {
      const mix = item.business_line_mix || {}; const total = Object.values(mix).reduce((sum, value) => sum + Number(value || 0), 0);
      const bars = ['machine', 'parts', 'service', 'rental'].map(code => `<i style="width:${total ? Math.max(0, Number(mix[code] || 0) / total * 100) : 0}%;background:${colors[code]}"></i>`).join('');
      return `<tr tabindex="0" data-entity-id="${escapeHtml(item.id)}"><td><span class="bcc-rank">${item.rank}</span></td><td><strong>${escapeHtml(item.display_name || item.name || 'Not available')}</strong></td><td>${money(item.revenue)}</td><td>${item.share === null ? 'Not available' : `${item.share}%`}</td><td>${money(item.previous_revenue)}</td><td class="${item.absolute_delta < 0 ? 'negative' : 'positive'}">${money(item.absolute_delta)}<br><small>${growth(item)}</small></td><td><span class="bcc-mini-mix">${bars}</span></td><td>&#8594;</td></tr>`;
    }).join('') || '<tr><td colspan="8">No published Revenue matches this context.</td></tr>';
  }

  function renderExplorer(rows) {
    const max = Math.max(1, ...rows.map(item => Number(item.revenue || 0)));
    $('[data-ranking-chart]').innerHTML = rows.slice(0, 10).map(item => `<button class="bcc-ranking-row" type="button" data-chart-entity="${escapeHtml(item.id)}"><strong>${escapeHtml(item.display_name || item.name || 'Not available')}</strong><span class="bcc-ranking-track"><i style="width:${Math.max(0, item.revenue / max * 100)}%"></i><em style="left:${Math.max(0, Number(item.previous_revenue || 0) / max * 100)}%"></em></span><b>${money(item.revenue)}</b></button>`).join('');
    $('[data-dimension-table]').innerHTML = dimensionRowsMarkup(rows);
    [...$$('[data-entity-id]'), ...$$('[data-chart-entity]')].forEach(node => { const open = () => openEntity(node.dataset.entityId || node.dataset.chartEntity, state.dimension, rows); node.addEventListener('click', open); node.addEventListener('keydown', event => { if (event.key === 'Enter') open(); }); });
  }

  function turnoverGrowth(current, previous) {
    current = Number(current || 0); previous = Number(previous || 0);
    if (previous === 0) return { label: current > 0 ? 'New' : 'No change', value: null, status: current > 0 ? 'positive' : 'neutral' };
    if (previous < 0 || Math.abs(previous) < 1000) return { label: 'Not meaningful', value: null, status: 'neutral' };
    const value = (current - previous) / Math.abs(previous) * 100;
    return { label: `${value > 0 ? '+' : ''}${value.toFixed(1)}%`, value, status: value < 0 ? 'negative' : value > 0 ? 'positive' : 'neutral' };
  }

  function turnoverCountryName(item) {
    const code = String(item.id || '').toUpperCase();
    const name = String(item.name || '').trim();
    return name && name.toUpperCase() !== code ? name : countryNames[code] || name || item.id || 'Not assigned';
  }

  function renderTurnover(rows) {
    const data = state.data; const lines = data.business_lines.filter(item => ['machine', 'parts', 'service', 'rental'].includes(item.code));
    const countryRows = rows.slice(0, 10);
    $('[data-turnover-period]').textContent = data.context.period_label;
    $('[data-turnover-freshness]').textContent = `Revenue through ${dateLabel(data.freshness.data_through_date)} · Refreshed ${dateTimeLabel(data.freshness.source_snapshot_at)}`;
    $('[data-turnover-subtitle]').textContent = `Actual invoiced Revenue by Country · ${data.context.currency}`;
    const kpis = [...lines, { code: 'total', label: 'Total Sales', revenue: data.hero.revenue, absolute_delta: data.hero.absolute_delta, relative_delta: data.hero.relative_delta, growth_status: data.hero.growth_status }];
    $('[data-turnover-kpis]').innerHTML = kpis.map(item => `<button type="button" class="bcc-turnover-kpi ${item.code}" data-turnover-line="${item.code}"><span>${escapeHtml(item.label)}</span><small>Total Revenue</small><strong>${money(item.revenue)}</strong><footer><em>vs Last Year</em><b class="${Number(item.absolute_delta || 0) < 0 ? 'negative' : 'positive'}">${growth(item)}</b></footer></button>`).join('');
    $$('[data-turnover-line]').forEach(button => button.addEventListener('click', () => { $('[data-filter="business_line"]').value = button.dataset.turnoverLine === 'total' ? 'all_business' : button.dataset.turnoverLine; refresh(); }));
    $('[data-turnover-matrix-head]').innerHTML = `<tr><th>Business Line</th>${countryRows.map(row => `<th>${escapeHtml(turnoverCountryName(row))}</th>`).join('')}</tr>`;
    $('[data-turnover-matrix-body]').innerHTML = lines.map(line => `<tr><th style="--line-color:${colors[line.code]}">${escapeHtml(line.label)}</th>${countryRows.map(row => { const current = row.business_line_mix?.[line.code]; const previous = row.comparison_business_line_mix?.[line.code]; const result = turnoverGrowth(current, previous); return `<td class="${result.status}" title="Current ${money(current, true)} · Last Year ${money(previous, true)}"><strong>${money(current)}</strong><small>${result.label} vs Last Year</small></td>`; }).join('')}</tr>`).join('');

    const growthCountries = countryRows.filter(row => row.growth_status === 'comparable' && Number(row.relative_delta) > 0).sort((a, b) => Number(b.relative_delta) - Number(a.relative_delta)).slice(0, 3);
    const decliningCountries = countryRows.filter(row => Number(row.absolute_delta) < 0).sort((a, b) => Number(a.absolute_delta) - Number(b.absolute_delta)).slice(0, 3);
    const rankingMarkup = (items, mode) => items.map((item, index) => { const magnitude = mode === 'growth' ? Math.abs(Number(item.relative_delta || 0)) : Math.abs(Number(item.absolute_delta || 0)); const max = Math.max(1, ...items.map(row => mode === 'growth' ? Math.abs(Number(row.relative_delta || 0)) : Math.abs(Number(row.absolute_delta || 0)))); return `<div class="bcc-turnover-rank ${mode}"><span>${index + 1}</span><strong>${escapeHtml(turnoverCountryName(item))}</strong><b>${mode === 'growth' ? `+${Number(item.relative_delta).toFixed(1)}%` : money(item.absolute_delta)}</b><em><i style="width:${magnitude / max * 100}%"></i></em></div>`; }).join('');
    $('[data-turnover-growth]').innerHTML = rankingMarkup(growthCountries, 'growth') || '<p class="bcc-empty">No meaningful Country growth is available.</p>';
    $('[data-turnover-country-attention]').innerHTML = rankingMarkup(decliningCountries, 'attention') || '<p class="bcc-empty">No Country Revenue decline requires attention.</p>';

    const strongestLine = [...lines].sort((a, b) => Number(b.absolute_delta || 0) - Number(a.absolute_delta || 0))[0];
    const weakestLine = [...lines].sort((a, b) => Number(a.absolute_delta || 0) - Number(b.absolute_delta || 0))[0];
    const leader = countryRows[0];
    const insightRows = [
      { title: data.hero.absolute_delta >= 0 ? 'Overall Revenue growth' : 'Overall Revenue decline', text: `${money(data.hero.absolute_delta)} · ${growth(data.hero)} vs Last Year.` },
      strongestLine && { title: `${strongestLine.label} leads the movement`, text: `${money(strongestLine.absolute_delta)} change versus the same period last year.` },
      weakestLine && weakestLine.absolute_delta < 0 && { title: `${weakestLine.label} requires attention`, text: `${money(weakestLine.absolute_delta)} observed Revenue movement.` },
      leader && { title: `${turnoverCountryName(leader)} leads`, text: `${money(leader.revenue)} of actual invoiced Revenue in the selected context.` },
      decliningCountries.length && { title: 'Focus on recovery', text: `${decliningCountries.length} leading Countr${decliningCountries.length === 1 ? 'y shows' : 'ies show'} a Revenue decline versus Last Year.` },
    ].filter(Boolean).slice(0, 5);
    $('[data-turnover-insights]').innerHTML = insightRows.map((item, index) => `<li><span>${index + 1}</span><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.text)}</p></div></li>`).join('');
    $('[data-turnover-conclusion]').textContent = decliningCountries.length ? `${strongestLine?.label || 'The leading Business Line'} supports the current performance, while ${weakestLine?.label || 'the weakest line'} and declining Countries require focused management attention.` : `${strongestLine?.label || 'The leading Business Line'} is the strongest current contributor, with no material Country decline in the displayed portfolio.`;
  }

  async function loadTurnover() {
    if (!state.data) return;
    state.turnoverController?.abort(); state.turnoverController = new AbortController();
    const turnoverStatus = setHidden('[data-turnover-status]', false); if (turnoverStatus) turnoverStatus.textContent = 'Loading governed Country performance...';
    const query = apiParams(); query.set('dimension', 'countries'); query.set('ranking', 'revenue'); query.set('limit', '25');
    try {
      const response = await fetch(`${root.dataset.explorerUrl}?${query}`, { signal: state.turnoverController.signal, headers: { Accept: 'application/json' } });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.message || 'Mining Turnover is temporarily unavailable.');
      if (payload.context_id !== state.data.context.context_id) return;
      renderTurnover(payload.results); state.turnoverLoaded = true; setHidden('[data-turnover-status]', true);
    } catch (error) { if (error.name !== 'AbortError') { const status = setHidden('[data-turnover-status]', false); if (status) status.textContent = error.message; } }
  }

  async function loadExplorer() {
    if (!state.data) return;
    if (state.dimension === 'business_lines') { renderExplorer(state.data.business_lines.filter(item => item.code !== 'unclassified').map((item, index) => ({ ...item, id: item.code, name: item.label, previous_revenue: item.comparison_revenue, business_line_mix: { [item.code]: item.revenue }, rank: index + 1 }))); state.explorerLoaded = true; return; }
    state.explorerController?.abort(); state.explorerController = new AbortController(); $('[data-explorer-status]').hidden = false; $('[data-explorer-status]').textContent = 'Loading Revenue Explorer...';
    const query = apiParams(); query.set('dimension', state.dimension); query.set('ranking', $('[data-ranking-mode]').value); query.set('limit', $('[data-explorer-limit]').value);
    try {
      const response = await fetch(`${root.dataset.explorerUrl}?${query}`, { signal: state.explorerController.signal, headers: { Accept: 'application/json' } }); const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Revenue Explorer is temporarily unavailable.');
      if (payload.context_id !== state.data.context.context_id) return;
      renderExplorer(payload.results); state.explorerLoaded = true; $('[data-explorer-status]').hidden = true;
    } catch (error) { if (error.name !== 'AbortError') { $('[data-explorer-status]').hidden = false; $('[data-explorer-status]').textContent = error.message; } }
  }

  function openEntity(id, dimension, rows) {
    state.fleetController?.abort();
    const item = (rows || []).find(row => String(row.id) === String(id)); if (!item) return;
    const type = dimension === 'customers' ? 'Customer' : dimension === 'countries' ? 'Country' : dimension === 'key_accounts' ? 'Key Account' : 'Business Line';
    $('[data-drawer-kicker]').textContent = `${type} 360`; $('[data-drawer-title]').textContent = item.name || type;
    $('[data-drawer-body]').innerHTML = `<div class="bcc-detail-grid"><div class="bcc-detail-metric"><span>Revenue</span><strong>${money(item.revenue, true)}</strong></div><div class="bcc-detail-metric"><span>Share</span><strong>${item.share === null || item.share === undefined ? 'Not available' : `${item.share}%`}</strong></div><div class="bcc-detail-metric"><span>Previous period</span><strong>${money(item.previous_revenue, true)}</strong></div><div class="bcc-detail-metric"><span>Change</span><strong>${money(item.absolute_delta, true)} · ${growth(item)}</strong></div></div><h3>Business Line Mix</h3>${Object.entries(item.business_line_mix || {}).map(([key, value]) => `<div class="bcc-watch-item"><span>${escapeHtml(key)}</span><strong>${money(value)}</strong></div>`).join('')}<p class="bcc-empty">Published Mapping v${state.data.context.published_mapping_version || 'not available'} · context ${state.data.context.context_id}</p>${features.watchlist ? '<button class="bcc-button primary" type="button" data-add-watch>Add to Watchlist</button>' : ''}`;
    $('[data-drawer]').hidden = false; document.body.style.overflow = 'hidden'; $('[data-drawer-close]').focus();
    if (['customers', 'key_accounts', 'countries'].includes(dimension)) {
      $('[data-drawer-body]').insertAdjacentHTML('beforeend', '<section class="bcc-fleet-section"><h3>Fleet</h3><p class="bcc-empty">Current Mining fleet snapshot for linked sites; independent of the Revenue period.</p><div data-entity-fleet role="status">Loading fleet...</div></section>');
      loadEntityFleet(id, dimension);
    }
    $('[data-add-watch]')?.addEventListener('click', () => addWatchlist(type.toLowerCase().replace(' ', '_'), item));
  }
  async function loadEntityFleet(id, dimension) {
    const controller = new AbortController(); state.fleetController = controller;
    const target = $('[data-entity-fleet]');
    const query = apiParams(); query.set('dimension', dimension); query.set('entity_id', id);
    try {
      const response = await fetch(`${root.dataset.fleetUrl}?${query}`, {signal: controller.signal, headers: {Accept: 'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Fleet is temporarily unavailable.');
      if (controller.signal.aborted) return;
      if (!data.linked) { target.textContent = 'No published MineSite link is available for this selection.'; return; }
      if (!data.count) { target.textContent = 'No equipment is available in the current snapshot for the linked sites.'; return; }
      target.innerHTML = `<p class="bcc-empty">Fleet scope: ${escapeHtml(data.scope_label)}</p><p><strong>${data.count} equipment records</strong> · ${data.sites.length} linked sites</p><p class="bcc-empty">${escapeHtml(data.sites.join(', '))}</p><div class="bcc-fleet-models">${data.models.map(row => `<span>${escapeHtml(row.model || 'Unknown model')} <b>${row.count}</b></span>`).join('')}</div><p class="bcc-empty">Showing ${data.equipment.length} of ${data.count} records${data.as_of ? ` · Updated ${escapeHtml(new Date(data.as_of).toLocaleDateString('en-GB'))}` : ''}</p><div class="bcc-fleet-table" tabindex="0" aria-label="Fleet equipment"><table><thead><tr><th>Equipment</th><th>Model</th><th>Serial number</th><th>Site</th><th>Status</th></tr></thead><tbody>${data.equipment.map(row => `<tr>${[row.equipment, row.model, row.serial_number, row.site, row.source_status].map(value => `<td>${escapeHtml(value || 'Not available')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    } catch (error) { if (error.name !== 'AbortError') target.textContent = 'Fleet is temporarily unavailable. Close and reopen this panel to retry.'; }
  }
  function closeDrawer() { state.fleetController?.abort(); $('[data-drawer]').hidden = true; document.body.style.overflow = ''; }

  function renderMachineFamilyGroups(groups) {
    const picker = $('[data-machine-family-picker]');
    const selected = $('[data-machine-filter="family"]').value;
    picker.innerHTML = groups.map(group => {
      const code = String(group.code || '').toUpperCase();
      const imageKey = `image${code.charAt(0)}${code.slice(1).toLowerCase()}`;
      const image = picker.dataset[imageKey] || '';
      const media = image
        ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(group.description || code)}">`
        : `<div class="bcc-machine-family-placeholder" aria-hidden="true">${escapeHtml(code)}</div>`;
      return `<button type="button" data-machine-family-card="${escapeHtml(code)}" aria-pressed="${String(selected === code)}">${media}<span><strong>${escapeHtml(code)}</strong><small>${escapeHtml(group.description || code)}</small><em>${money(group.revenue_eur)} · ${Number(group.equipment_count || 0).toLocaleString('en-GB')} machines</em></span></button>`;
    }).join('');
  }

  async function loadMachineSales(resetPage = false) {
    if (!state.data) return; if (resetPage) state.machinePage = 1;
    state.machineController?.abort(); state.machineController = new AbortController(); const query = apiParams(); query.set('page', state.machinePage); query.set('page_size', '50');
    const search = $('[data-machine-search]').value.trim(); if (search) query.set('search', search); $$('[data-machine-filter]').forEach(control => { if (control.value) query.set(control.dataset.machineFilter, control.value); });
    $('[data-machine-status]').hidden = false; $('[data-machine-status]').textContent = 'Loading Machine Sales detail...';
    try {
      const response = await fetch(`${root.dataset.machineSalesUrl}?${query}`, { signal: state.machineController.signal, headers: { Accept: 'application/json' } }); const data = await response.json(); if (!response.ok) throw new Error(data.message || 'Machine Sales details are temporarily unavailable.');
      if (!data.ready) { $('[data-machine-status]').textContent = 'The governed Machine Sales buffer has not been synchronized yet.'; return; }
      state.machinePages = Math.max(1, data.pagination.pages || 1); state.machineLoaded = true;
      [['family', 'families', 'All Families'], ['brand', 'brands', 'All Brands']].forEach(([filter, key, label]) => { const control = $(`[data-machine-filter="${filter}"]`); const current = control.value; control.innerHTML = `<option value="">${label}</option>${(data.filter_options?.[key] || []).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('')}`; control.value = current; });
      renderMachineFamilyGroups(data.filter_options?.family_groups || []);
      const unclassified = data.filter_options?.unclassified_family || {};
      const unclassifiedNotice = $('[data-machine-unclassified]');
      unclassifiedNotice.hidden = !Number(unclassified.detail_rows || 0);
      unclassifiedNotice.textContent = `Unclassified Machine detail remains visible: ${money(unclassified.revenue_eur)} across ${Number(unclassified.detail_rows || 0).toLocaleString('en-GB')} invoice lines. A governed model or serial mapping is required before assignment to a product group.`;
      const summary = data.summary; const adjustment = Number(summary.reconciliation_adjustment_eur || 0);
      $('[data-machine-source]').textContent = `Machine details through ${dateLabel(data.freshness.data_through_date)} · ${data.freshness.status}${adjustment ? ` · technical reconciliation adjustment ${money(adjustment, true)}` : ' · reconciled to certified Machine Revenue'}`;
      $('[data-machine-summary]').innerHTML = [['Net Invoiced Revenue', money(summary.net_revenue_eur)], ['Machines', Number(summary.equipment_count).toLocaleString('en-GB')], ['Invoices', Number(summary.invoice_count).toLocaleString('en-GB')], ['Machine Sale', money(summary.machine_sale_eur)], ['Other Charges & Adjustments', money(summary.other_charges_eur)], ['Missing Serials', Number(summary.missing_serial_count).toLocaleString('en-GB')]].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join('');
      const rows = data.results;
      $('[data-machine-body]').innerHTML = rows.map((item, index) => { const reconciliation = item.record_type === 'reconciliation_adjustment'; return `<tr class="${reconciliation ? 'bcc-reconciliation-row' : ''}"><td>${dateLabel(item.business_date)}</td><td><strong>${escapeHtml(item.customer_name || (reconciliation ? 'Accounting reconciliation' : 'Not available'))}</strong><small>${escapeHtml(item.customer_code || (reconciliation ? 'Technical adjustment' : ''))}</small></td><td><strong>${escapeHtml(item.model_name || 'Not available')}</strong></td><td>${reconciliation ? 'Accounting' : escapeHtml(item.family_code || 'Not classified')}</td><td>${reconciliation ? '—' : escapeHtml(item.brand || 'Not available')}</td><td>${reconciliation ? '—' : item.serial_number ? escapeHtml(item.serial_number) : '<span class="bcc-data-warning">Missing</span>'}</td><td>${reconciliation ? '—' : escapeHtml(item.equipment_code || 'Not available')}</td><td><button class="bcc-entry-toggle" type="button" data-machine-entry-toggle="${index}" aria-expanded="false">${item.invoice_count} invoices</button></td><td>${reconciliation ? 'Reconciliation' : escapeHtml((item.conditions || []).join(' · ') || 'Not available')}</td><td>${money(item.machine_sale_eur, true)}</td><td>${money(item.other_charges_eur, true)}</td><td>${money(item.net_revenue_eur, true)}</td></tr><tr class="bcc-entry-detail" data-machine-entry="${index}" hidden><td colspan="12"><div><strong>${reconciliation ? 'Reconciliation entries' : 'Invoice entries'}</strong><table><tbody>${(item.entries || []).map(entry => `<tr><td>${dateLabel(entry.business_date)}</td><td>${escapeHtml(entry.invoice_number || 'Not available')}</td><td>${escapeHtml(entry.classification)}</td><td>${money(entry.amount_eur, true)}</td></tr>`).join('')}</tbody></table></div></td></tr>`; }).join('') || '<tr><td colspan="12">No invoiced Machine Sale matches this context.</td></tr>';
      $$('[data-machine-entry-toggle]').forEach(button => button.addEventListener('click', () => { const detail = $(`[data-machine-entry="${button.dataset.machineEntryToggle}"]`); const expanded = button.getAttribute('aria-expanded') === 'true'; button.setAttribute('aria-expanded', String(!expanded)); detail.hidden = expanded; }));
      $('[data-machine-status]').hidden = true; $('[data-machine-table-wrap]').hidden = false; $('[data-machine-pagination]').hidden = !data.pagination.count; $('[data-machine-page]').textContent = `Page ${data.pagination.page} of ${state.machinePages} · ${Number(data.pagination.count).toLocaleString('en-GB')} records`; $('[data-machine-prev]').disabled = state.machinePage <= 1; $('[data-machine-next]').disabled = state.machinePage >= state.machinePages;
    } catch (error) { if (error.name !== 'AbortError') $('[data-machine-status]').textContent = error.message; }
  }

  async function loadPartsSales(resetPage = false) {
    if (!state.data) return; if (resetPage) state.partsPage = 1;
    state.partsController?.abort(); state.partsController = new AbortController(); const query = apiParams(); query.set('page', state.partsPage); query.set('page_size', '50'); query.set('group_by', $('[data-parts-group]').value || 'major');
    const search = $('[data-parts-search]').value.trim(); if (search) query.set('search', search); $$('[data-parts-filter]').forEach(control => { if (control.value) query.set(control.dataset.partsFilter, control.value); });
    $('[data-parts-status]').hidden = false; $('[data-parts-status]').textContent = 'Loading Parts classification detail...';
    try {
      const response = await fetch(`${root.dataset.partsSalesUrl}?${query}`, { signal: state.partsController.signal, headers: { Accept: 'application/json' } }); const data = await response.json(); if (!response.ok) throw new Error(data.message || 'Parts Sales classification is temporarily unavailable.');
      if (!data.ready) { $('[data-parts-status]').textContent = 'The governed Parts Sales buffer has not been synchronized yet.'; return; }
      state.partsPages = Math.max(1, data.pagination.pages || 1); state.partsLoaded = true;
      const config = { major: ['major_classes', 'All Major Classes'], minor: ['minor_classes', 'All Minor Classes'], ppc: ['ppcs', 'All PPC'] }; $$('[data-parts-filter]').forEach(control => { const current = control.value; const [key, label] = config[control.dataset.partsFilter]; control.innerHTML = `<option value="">${label}</option>${(data.filter_options?.[key] || []).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('')}`; control.value = current; });
      const summary = data.summary; const matchedPct = summary.reconciliation_coverage_pct;
      $('[data-parts-source]').textContent = `Parts details through ${dateLabel(data.freshness.data_through_date)} · matched subset analysis only`;
      $('[data-parts-summary]').innerHTML = [['Certified Parts Revenue', money(summary.certified_parts_revenue_eur)], ['Matched Revenue', money(summary.allocated_invoice_revenue_eur)], ['Unmatched Revenue', money(summary.unlinked_revenue_eur)], ['Matched Coverage', matchedPct === null ? 'Not available' : `${matchedPct.toFixed(1)}%`], ['Classified CAT Revenue', money(summary.classified_revenue_eur)], ['Other Brands', money(summary.other_brands_revenue_eur)]].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join('');
      const certified = Number(summary.certified_parts_revenue_eur || 0); const funnel = [['Certified Parts Revenue', summary.certified_parts_revenue_eur], ['Matched to Invoice Lines', summary.allocated_invoice_revenue_eur], ['Classified to Brand', Number(summary.classified_revenue_eur || 0) + Number(summary.other_brands_revenue_eur || 0)], ['CAT Major Class', summary.classified_revenue_eur]]; $('[data-parts-funnel]').innerHTML = funnel.map(([label, value]) => `<div class="bcc-funnel-step"><span>${label}</span><b>${money(value)}</b><small>${certified ? `${(Number(value || 0) / certified * 100).toFixed(1)}% of certified` : 'Not available'}</small></div>`).join('');
      $('[data-parts-body]').innerHTML = data.results.map(item => `<tr><td><span class="bcc-rank">${item.rank}</span></td><td><strong>${escapeHtml(item.brand_group || 'Brand Not Available')}</strong></td><td><strong>${escapeHtml(item.major_class || 'Not classified')}</strong></td><td>${escapeHtml(item.major_description || 'Not classified')}</td><td>${escapeHtml(item.minor_class || 'Not classified')}</td><td>${escapeHtml(item.ppc || 'Not classified')}</td><td>${money(item.revenue_eur, true)}</td><td>${Number(item.line_count).toLocaleString('en-GB')}</td><td>${Number(item.part_count).toLocaleString('en-GB')}</td></tr>`).join('') || '<tr><td colspan="9">No classified Parts sale matches this context.</td></tr>';
      $('[data-parts-status]').hidden = true; $('[data-parts-table-wrap]').hidden = false; $('[data-parts-pagination]').hidden = !data.pagination.count; $('[data-parts-page]').textContent = `Page ${data.pagination.page} of ${state.partsPages} · ${Number(data.pagination.count).toLocaleString('en-GB')} groups`; $('[data-parts-prev]').disabled = state.partsPage <= 1; $('[data-parts-next]').disabled = state.partsPage >= state.partsPages;
    } catch (error) { if (error.name !== 'AbortError') $('[data-parts-status]').textContent = error.message; }
  }

  function loadOperation(name) { state.operation = name; $$('[data-operation-view]').forEach(node => { node.hidden = node.dataset.operationView !== name; }); setHidden('[data-machine-family-picker]', name !== 'machine'); $$('[data-operation-tab]').forEach(button => button.classList.toggle('active', button.dataset.operationTab === name)); if (name === 'machine' && !state.machineLoaded) loadMachineSales(true); if (name === 'parts' && !state.partsLoaded) loadPartsSales(true); }

  async function searchEntities(type, query, target, dropdown = false) {
    if (query.trim().length < 2 && !(dropdown && !query.trim())) { target.innerHTML = '<p class="bcc-empty">Enter at least two characters.</p>'; return []; }
    const url = type === 'customers' ? root.dataset.customerSearchUrl : root.dataset.keyAccountSearchUrl; const params = apiParams(); params.set('q', query.trim());
    const response = await fetch(`${url}?${params}`, { headers: { Accept: 'application/json' } }); const payload = await response.json();
    const allLabel = type === 'customers' ? 'All Customer Groups' : 'All Key Accounts';
    const clear = dropdown ? `<button class="bcc-search-result bcc-search-result-all" type="button" data-search-id="" data-search-name=""><strong>${allLabel}</strong><small>Clear selection</small></button>` : '';
    const rows = payload.results.map(item => `<button class="bcc-search-result" type="button" data-search-id="${escapeHtml(item.id)}" data-search-name="${escapeHtml(item.name)}"><strong>${escapeHtml(item.name || 'Not available')}</strong><small>${escapeHtml(item.country || 'Country not assigned')}${item.revenue === null || item.revenue === undefined ? '' : ` · ${money(item.revenue)}`}</small></button>`).join('');
    target.innerHTML = clear + (rows || '<p class="bcc-empty">No authorized result.</p>');
    return payload.results;
  }

  function bindComboboxResults(input, target) {
    $$('[data-search-id]', target).forEach(button => button.addEventListener('click', () => {
      const key = input.dataset.entitySearch === 'customers' ? 'customer_group_ids' : 'key_account_ids';
      const allLabel = key === 'customer_group_ids' ? 'All Customer Groups' : 'All Key Accounts';
      $(`[data-filter="${key}"]`).value = button.dataset.searchId;
      state.selectedLabels[key] = button.dataset.searchName;
      input.closest('[data-combobox]').querySelector('[data-combobox-label]').textContent = button.dataset.searchName || allLabel;
      input.closest('[data-combobox-menu]').hidden = true;
      input.closest('[data-combobox]').querySelector('[data-combobox-toggle]').setAttribute('aria-expanded', 'false');
      refresh();
    }));
  }

  async function addWatchlist(type, item) { await fetch(root.dataset.watchlistUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ entity_type: type, entity_id: item.id, display_name: item.name }) }); closeDrawer(); refresh(); }
  async function removeWatchlist(id) { await fetch(root.dataset.watchlistUrl, { method: 'DELETE', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ id }) }); refresh(); }

  $$('[data-workspace-tab]').forEach(button => button.addEventListener('click', () => switchWorkspace(button.dataset.workspaceTab)));
  $('[data-leaders-limit]').addEventListener('change', loadLeaders);
  $('[data-leaders-dimension]').addEventListener('change', loadLeaders);
  $('[data-open-actions]').addEventListener('click', () => switchWorkspace('actions'));
  $$('[data-brief-tab]').forEach(button => button.addEventListener('click', () => { $$('[data-brief-tab]').forEach(node => node.classList.toggle('active', node === button)); $$('[data-brief-view]').forEach(node => node.classList.toggle('active', node.dataset.briefView === button.dataset.briefTab)); }));
  $$('[data-analysis-mode]').forEach(button => button.addEventListener('click', () => { $$('[data-analysis-mode]').forEach(node => node.classList.toggle('active', node === button)); $$('[data-analysis-view]').forEach(node => { node.hidden = node.dataset.analysisView !== button.dataset.analysisMode; }); }));
  $$('[data-trend-mode]').forEach(button => button.addEventListener('click', () => { state.trendMode = button.dataset.trendMode; $$('[data-trend-mode]').forEach(node => node.classList.toggle('active', node === button)); renderTrend(state.data); }));
  $('[data-trend-fullscreen]')?.addEventListener('click', () => {
    const panel = $('[data-export-surface="trend"]');
    if (document.fullscreenElement === panel) document.exitFullscreen?.().catch(() => {});
    else panel?.requestFullscreen?.().catch(() => {});
  });
  $$('[data-dimension]').forEach(button => button.addEventListener('click', () => { state.dimension = button.dataset.dimension; state.explorerLoaded = false; $$('[data-dimension]').forEach(node => node.classList.toggle('active', node === button)); loadExplorer(); }));
  $('[data-ranking-mode]').addEventListener('change', () => { state.explorerLoaded = false; loadExplorer(); }); $('[data-explorer-limit]').addEventListener('change', () => { state.explorerLoaded = false; loadExplorer(); });
  $$('[data-operation-tab]').forEach(button => button.addEventListener('click', () => loadOperation(button.dataset.operationTab)));
  $('[data-machine-family-picker]').addEventListener('click', event => {
    const card = event.target.closest('[data-machine-family-card]');
    if (!card) return;
    const family = $('[data-machine-filter="family"]');
    const clearSelection = family.value === card.dataset.machineFamilyCard;
    family.value = clearSelection ? '' : card.dataset.machineFamilyCard;
    $$('[data-machine-family-card]').forEach(item => item.setAttribute('aria-pressed', String(!clearSelection && item === card)));
    loadMachineSales(true);
  });
  $('[data-machine-filter="family"]').addEventListener('change', event => {
    $$('[data-machine-family-card]').forEach(card => card.setAttribute('aria-pressed', String(card.dataset.machineFamilyCard === event.target.value)));
  });
  $$('[data-filter]').filter(control => control.dataset.filter !== 'key_account_ids').forEach(control => control.addEventListener('change', event => {
    toggleCustomDates();
    if (event.currentTarget.dataset.filter === 'period') initializeCustomRange();
    if (['start_date', 'end_date'].includes(event.currentTarget.dataset.filter)) syncCustomDateBounds(state.data);
    if ($('[data-filter="period"]').value !== 'custom' || ($('[data-filter="start_date"]').value && $('[data-filter="end_date"]').value)) refresh();
  }));
  $('[data-division-toggle]').addEventListener('change', event => {
    $('[data-filter="division_scope"]').value = event.currentTarget.checked ? 'all_divisions' : 'mining';
    refresh();
  });
  $$('[data-combobox-toggle]').forEach(button => button.addEventListener('click', async () => {
    const combobox = button.closest('[data-combobox]'); const menu = combobox.querySelector('[data-combobox-menu]'); const opening = menu.hidden;
    $$('[data-combobox-menu]').forEach(other => { other.hidden = true; other.closest('[data-combobox]').querySelector('[data-combobox-toggle]').setAttribute('aria-expanded', 'false'); });
    if (!opening) return;
    menu.hidden = false; button.setAttribute('aria-expanded', 'true');
    const input = menu.querySelector('[data-entity-search]'); const target = menu.querySelector('[data-search-results]');
    input.value = ''; target.innerHTML = '<p class="bcc-empty">Loading authorized values...</p>'; input.focus();
    await searchEntities(input.dataset.entitySearch, '', target, true); bindComboboxResults(input, target);
  }));
  $$('[data-entity-search]').forEach(input => input.addEventListener('input', () => { window.clearTimeout(state.searchTimers[input.dataset.entitySearch]); state.searchTimers[input.dataset.entitySearch] = window.setTimeout(async () => { const target = $(`[data-search-results="${input.dataset.entitySearch}"]`); await searchEntities(input.dataset.entitySearch, input.value, target, true); bindComboboxResults(input, target); }, 250); }));
  $('[data-filter-open]').addEventListener('click', () => $('[data-filter-sheet]').classList.add('open')); $('[data-filter-close]').addEventListener('click', () => $('[data-filter-sheet]').classList.remove('open'));
  $('[data-reset]').addEventListener('click', () => { $$('[data-filter]').forEach(control => { control.value = control.dataset.filter === 'period' ? 'ytd' : control.dataset.filter === 'comparison' ? 'same_period_last_year' : control.dataset.filter === 'business_line' ? 'all_business' : control.dataset.filter === 'division_scope' ? 'mining' : ''; }); $('[data-division-toggle]').checked = false; state.selectedLabels = { key_account_ids: '' }; $('[data-filter-sheet]').classList.remove('open'); refresh(); });
  $('[data-refresh]').addEventListener('click', refreshSource); $('[data-retry]').addEventListener('click', refresh);
  $('[data-drawer-close]').addEventListener('click', closeDrawer);
  $$('[data-confidence-open]').forEach(button => button.addEventListener('click', () => { const confidence = state.data?.confidence; if (!confidence) return; $('[data-drawer-kicker]').textContent = 'Data & Freshness'; $('[data-drawer-title]').textContent = `Data Confidence: ${confidence.status}`; $('[data-drawer-body]').innerHTML = `<div class="bcc-detail-grid"><div class="bcc-detail-metric"><span>Revenue through</span><strong>${dateLabel(state.data.freshness.data_through_date)}</strong></div><div class="bcc-detail-metric"><span>Revenue reconciliation</span><strong>${escapeHtml(state.data.reconciliation.status)}</strong></div><div class="bcc-detail-metric"><span>Customer coverage</span><strong>${confidence.customer_coverage === null ? 'Not available' : confidence.customer_coverage.toFixed(1) + '%'}</strong></div><div class="bcc-detail-metric"><span>Country coverage</span><strong>${confidence.country_coverage === null ? 'Not available' : confidence.country_coverage.toFixed(1) + '%'}</strong></div><div class="bcc-detail-metric"><span>Key Account coverage</span><strong>${confidence.key_account_coverage === null ? 'Not available' : confidence.key_account_coverage.toFixed(1) + '%'}</strong></div><div class="bcc-detail-metric"><span>Unallocated Revenue</span><strong>${money(confidence.unallocated_revenue, true)}</strong></div><div class="bcc-detail-metric"><span>Machine Detail</span><strong>${state.machineLoaded ? $('[data-machine-source]').textContent : 'Load on demand'}</strong></div><div class="bcc-detail-metric"><span>Parts Classification</span><strong>${state.partsLoaded ? $('[data-parts-source]').textContent : 'Load on demand'}</strong></div></div><h3>Known limitations</h3>${confidence.warnings.map(warning => `<p>${escapeHtml(warning)}</p>`).join('') || '<p>No governed headline limitation is currently reported.</p>'}`; $('[data-drawer]').hidden = false; document.body.style.overflow = 'hidden'; $('[data-drawer-close]').focus(); }));
  $('[data-machine-refresh]').addEventListener('click', () => loadMachineSales(true)); $$('[data-machine-filter]').forEach(control => control.addEventListener('change', () => loadMachineSales(true))); let machineTimer; $('[data-machine-search]').addEventListener('input', () => { clearTimeout(machineTimer); machineTimer = setTimeout(() => loadMachineSales(true), 300); }); $('[data-machine-prev]').addEventListener('click', () => { if (state.machinePage > 1) { state.machinePage--; loadMachineSales(); } }); $('[data-machine-next]').addEventListener('click', () => { if (state.machinePage < state.machinePages) { state.machinePage++; loadMachineSales(); } });
  $('[data-machine-export]')?.addEventListener('click', () => { const query = apiParams(); const search = $('[data-machine-search]').value.trim(); if (search) query.set('search', search); $$('[data-machine-filter]').forEach(control => { if (control.value) query.set(control.dataset.machineFilter, control.value); }); location.href = `${root.dataset.machineSalesExportUrl}?${query}`; });
  $('[data-parts-refresh]').addEventListener('click', () => loadPartsSales(true)); $('[data-parts-group]').addEventListener('change', () => loadPartsSales(true)); $$('[data-parts-filter]').forEach(control => control.addEventListener('change', () => loadPartsSales(true))); let partsTimer; $('[data-parts-search]').addEventListener('input', () => { clearTimeout(partsTimer); partsTimer = setTimeout(() => loadPartsSales(true), 300); }); $('[data-parts-prev]').addEventListener('click', () => { if (state.partsPage > 1) { state.partsPage--; loadPartsSales(); } }); $('[data-parts-next]').addEventListener('click', () => { if (state.partsPage < state.partsPages) { state.partsPage++; loadPartsSales(); } });
  $('[data-parts-export]')?.addEventListener('click', () => { const query = apiParams(); query.set('group_by', $('[data-parts-group]').value || 'major'); location.href = `${root.dataset.partsSalesExportUrl}?${query}`; });
  $('[data-presentation]')?.addEventListener('click', () => { document.body.classList.toggle('presentation'); if (document.body.classList.contains('presentation')) document.documentElement.requestFullscreen?.().catch(() => {}); else document.exitFullscreen?.().catch(() => {}); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeDrawer(); $('[data-filter-sheet]').classList.remove('open'); } });
  window.addEventListener('popstate', () => { syncFromUrl(); switchWorkspace(state.workspace, false); refresh(); });
  async function refreshSource() {
    const button = $('[data-refresh]');
    if (button.disabled) return;
    button.disabled = true; button.textContent = 'Refreshing...';
    const status = $('[data-revenue-sync-status]');
    status.textContent = 'Reading the Revenue source...';
    try {
      const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value || document.querySelector('meta[name="csrf-token"]')?.content || decodeURIComponent(document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.slice(10) || '');
      const response = await fetch(root.dataset.syncStatusUrl, {method:'POST', headers:{'X-CSRFToken':token, Accept:'application/json'}});
      const started = await response.json();
      if (!response.ok || !started.accepted) throw new Error(started.message || 'Revenue refresh could not be started.');
      for (let attempt=0; attempt<300; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        const check = await fetch(root.dataset.syncStatusUrl, {headers:{Accept:'application/json'}});
        if (!check.ok) throw new Error('Unable to check the Revenue refresh.');
        const sync = await check.json();
        if (sync.latest_run_id === started.run_id && ['Failed','Cancelled'].includes(sync.latest_run_status)) throw new Error('The source update failed. Previous data is retained.');
        if (sync.source_sync_id === started.run_id) {
          await refresh(true);
          status.textContent = 'Revenue refreshed from the source.';
          return;
        }
      }
      throw new Error('The source update is still running. The page will update when it completes.');
    } catch(error) { status.textContent = error.message; }
    finally { button.disabled = false; button.textContent = 'Refresh'; }
  }
  async function checkRevenueSynchronization() {
    try {
      if (document.hidden) return;
      const response = await fetch(root.dataset.syncStatusUrl, {headers: {Accept: 'application/json'}});
      if (!response.ok) return;
      const sync = await response.json();
      const status = $('[data-revenue-sync-status]');
      if (!sync.enabled) { if (!state.data?.dashboard_snapshot) status.textContent = ''; return; }
      if (sync.running) status.textContent = 'Updating Revenue automatically. The last available data remains visible.';
      else if (sync.last_attempt_failed) status.textContent = 'The automatic update could not reach the source. Existing data is retained; another attempt is scheduled.';
      else if (!sync.source_through_date || sync.source_through_date < sync.target_date) status.textContent = `Latest source transactions: ${sync.source_through_date ? dateLabel(sync.source_through_date) : 'not available'}. Target: ${dateLabel(sync.target_date)}. Source updates are checked automatically.`;
      else status.textContent = 'Revenue is updated automatically.';
      if (!sync.running && sync.source_sync_id && state.data?.source_sync_id !== sync.source_sync_id && !document.hidden && root.getAttribute('aria-busy') !== 'true') {
        await refresh();
      }
    } catch (_error) {
      // Keep the last verified data visible during temporary connection failures.
    } finally { setTimeout(checkRevenueSynchronization, 30000); }
  }
  syncFromUrl(); refresh().finally(checkRevenueSynchronization);
})();
