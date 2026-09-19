(() => {
  const root = document.querySelector('.codex-chat');
  if (!root) return;
  const form = document.querySelector('#codex-composer');
  const input = document.querySelector('#codex-question');
  const thread = document.querySelector('#codex-thread');
  const progressWrap = document.querySelector('#codex-run-progress');
  const progress = document.querySelector('#codex-progress');
  const progressBar = progressWrap.querySelector('span');
  const submitButton = form.querySelector('[type=submit]');
  const cancelButton = document.querySelector('#codex-cancel');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  let activeRunId = root.dataset.activeRunId || '';
  let pollTimer = null;
  const renderMessage = (element, content) => {
    const value = String(content || '');
    element.replaceChildren();
    const pattern = /\[([^\]\n]+)\]\((https?:\/\/[^\s<>"')]+)\)|(https?:\/\/[^\s<>"')]+)/g;
    let offset = 0;
    for (const match of value.matchAll(pattern)) {
      element.append(document.createTextNode(value.slice(offset, match.index)));
      const href = match[2] || match[3];
      try {
        const url = new URL(href);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid link');
        const link = document.createElement('a');
        link.href = url.href;
        link.textContent = match[1] || href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        element.append(link);
      } catch (_) { element.append(document.createTextNode(match[0])); }
      offset = match.index + match[0].length;
    }
    element.append(document.createTextNode(value.slice(offset)));
  };
  thread.querySelectorAll('.codex-message p').forEach(element => renderMessage(element, element.textContent));
  if (!thread.dataset.conversationId) {
    input.value = (new URLSearchParams(window.location.search).get('draft') || '').slice(0, 3000);
  }

  const appendMessage = (role, content, status = '', messageId = '', runId = '') => {
    const provisional = runId ? thread.querySelector(`[data-provisional-run-id="${runId}"]`) : null;
    if (provisional) {
      renderMessage(provisional.querySelector('p'), content);
      const meta = provisional.querySelector('small') || document.createElement('small');
      meta.textContent = status;
      if (!meta.parentElement) provisional.append(meta);
      if (messageId) {
        provisional.dataset.messageId = messageId;
        delete provisional.dataset.provisionalRunId;
      }
      return;
    }
    if (messageId && thread.querySelector(`[data-message-id="${messageId}"]`)) return;
    const article = document.createElement('article');
    article.className = `codex-message codex-message--${role.toLowerCase()}`;
    if (messageId) article.dataset.messageId = messageId;
    if (runId && !messageId) article.dataset.provisionalRunId = runId;
    const label = document.createElement('span');
    label.textContent = role === 'USER' ? 'User' : 'Assistant';
    const text = document.createElement('p');
    renderMessage(text, content);
    article.append(label, text);
    if (status) {
      const meta = document.createElement('small');
      meta.textContent = status;
      article.append(meta);
    }
    thread.querySelector('.codex-empty')?.remove();
    thread.append(article);
    thread.scrollTop = thread.scrollHeight;
  };

  const appendTable = (section, title, rows, columns) => {
    if (!rows?.length) return;
    const heading = document.createElement('h3');
    heading.textContent = title;
    const wrap = document.createElement('div');
    wrap.className = 'codex-result__table';
    const table = document.createElement('table');
    const thead = table.createTHead().insertRow();
    columns.forEach(([key, label]) => {
      const cell = document.createElement('th');
      cell.textContent = label;
      thead.append(cell);
    });
    const tbody = table.createTBody();
    rows.forEach((row) => {
      const tr = tbody.insertRow();
      columns.forEach(([key]) => {
        const value = row[key];
        tr.insertCell().textContent = value === null || value === undefined || value === '' ? 'Not specified' : value;
      });
    });
    wrap.append(table);
    section.append(heading, wrap);
  };

  const appendFleetResult = (run) => {
    const result = run.result;
    if (!result || result.kind === 'machine_not_found') return;
    const section = document.createElement('section');
    section.className = 'codex-result';
    section.dataset.runId = run.id;
    if (result.kind === 'web_sources') {
      const note = document.createElement('p');
      note.textContent = 'Web research completed. Sources are linked in the answer.';
      section.append(note);
      thread.append(section);
      return;
    }
    if (result.kind === 'governed_answer') {
      appendTable(section, 'Verified metrics', result.rows, [
        ['metric', 'Metric'], ['period', 'Period'], ['formatted_value', 'Value'],
      ]);
      (result.knowledge || []).forEach((item) => {
        const source = item.source || {};
        const link = document.createElement('a');
        link.textContent = `${source.title || item.title} · page ${source.page || 'not specified'}`;
        const url = new URL(source.url || '/', window.location.origin);
        if (url.origin === window.location.origin && ['http:', 'https:'].includes(url.protocol)) link.href = url.href;
        const paragraph = document.createElement('p');
        paragraph.append(link);
        section.append(paragraph);
      });
      if (!result.rows?.length) {
        if (section.childNodes.length) thread.append(section);
        return;
      }
    } else if (result.kind === 'availability_summary') {
      const context = result.context || {};
      const availability = result.availability || {};
      const comparison = availability.comparison || {};
      const summary = document.createElement('div');
      summary.className = 'codex-result__summary';
      [
        ['Physical availability', availability.formatted_value || 'Unavailable'],
        ['Change', comparison.delta_points === null || comparison.delta_points === undefined ? 'N/A' : `${comparison.delta_points} points`],
        ['Equipment', result.summary?.equipment_count ?? 'N/A'],
        ['Period', context.period_label || 'N/A'],
      ].forEach(([label, value]) => {
        const item = document.createElement('div');
        const strong = document.createElement('strong');
        strong.textContent = value;
        const span = document.createElement('span');
        span.textContent = label;
        item.append(strong, span);
        summary.append(item);
      });
      section.append(summary);
      if (result.presentation?.show_trend) {
        appendTable(section, 'Availability trend', result.trend, [
          ['period', 'Period'], ['formatted_value', 'Availability'],
        ]);
      }
      if (result.presentation?.show_breakdown) {
        appendTable(section, 'Scope breakdown', result.breakdown, [
          ['entity', 'Entity'], ['formatted_value', 'Availability'],
          ['equipment_count', 'Equipment'], ['downtime_hours', 'Downtime hours'],
        ]);
      }
      const trust = document.createElement('p');
      trust.className = 'codex-result__trust';
      trust.textContent = `${result.source_table} · Measure ${result.source_measure || 'Physical Availability'} · Data through ${result.data_quality?.latest_available_date || 'N/A'}${result.data_quality?.is_stale ? ' · Stale data' : ''}`;
      section.append(trust);
    } else if (result.kind === 'revenue_summary') {
      const context = result.context;
      const summary = document.createElement('div');
      summary.className = 'codex-result__summary';
      [
        ['Revenue EUR', Number(result.hero.revenue).toLocaleString('en-GB', {maximumFractionDigits: 2})],
        ['Change EUR', Number(result.hero.absolute_delta).toLocaleString('en-GB', {maximumFractionDigits: 2})],
        ['Change %', result.hero.relative_delta === null ? 'N/A' : `${result.hero.relative_delta} %`],
        ['Period', context.period_label],
      ].forEach(([label, value]) => {
        const item = document.createElement('div');
        const strong = document.createElement('strong');
        strong.textContent = value;
        const span = document.createElement('span');
        span.textContent = label;
        item.append(strong, span);
        summary.append(item);
      });
      section.append(summary);
      appendTable(section, 'Revenue by business line', result.business_lines, [
        ['rank', 'Rank'], ['label', 'Line'], ['revenue', 'Revenue EUR'],
        ['comparison_revenue', 'Comparison EUR'], ['absolute_delta', 'Change EUR'],
        ['relative_delta', 'Change %'], ['share', 'Share %'],
      ]);
      appendTable(section, 'Top customers', result.top_customers, [
        ['rank', 'Rank'], ['name', 'Client'], ['revenue', 'Revenue EUR'], ['absolute_delta', 'Change EUR'], ['share', 'Share %'],
      ]);
      appendTable(section, 'Top countries', result.top_countries, [
        ['rank', 'Rank'], ['name', 'Country'], ['revenue', 'Revenue EUR'], ['absolute_delta', 'Change EUR'], ['share', 'Share %'],
      ]);
      appendTable(section, 'Top Key Accounts', result.top_key_accounts, [
        ['rank', 'Rank'], ['name', 'Key Account'], ['revenue', 'Revenue EUR'], ['absolute_delta', 'Change EUR'], ['share', 'Share %'],
      ]);
      const trust = document.createElement('p');
      trust.className = 'codex-result__trust';
      trust.textContent = `Data through ${result.freshness.data_through_date} · Published mapping v${context.published_mapping_version ?? 'N/A'} · Reconciliation ${result.reconciliation.status} · Confidence ${result.confidence.status}`;
      section.append(trust);
    } else if (result.machine) {
      appendTable(section, 'Machine details', [result.machine], [
        ['serial_number', 'Serial number'], ['equipment', 'Equipment'], ['model', 'Model'],
        ['equipment_family', 'Family'], ['brand', 'Brand'], ['site', 'MineSite'], ['smu', 'SMU'],
      ]);
    } else {
      const summary = document.createElement('div');
      summary.className = 'codex-result__summary';
      [
        ['Equipment', result.equipment_count], ['Serial numbers', result.serial_count],
        ['Models', result.model_count], ['Families', result.family_count],
      ].forEach(([label, value]) => {
        const item = document.createElement('div');
        const strong = document.createElement('strong');
        strong.textContent = value ?? 'N/A';
        const span = document.createElement('span');
        span.textContent = label;
        item.append(strong, span);
        summary.append(item);
      });
      section.append(summary);
      appendTable(section, 'Model breakdown', result.models, [['model', 'Model'], ['equipment_count', 'Equipment']]);
      appendTable(section, 'Family breakdown', result.families, [['equipment_family', 'Family'], ['equipment_count', 'Equipment']]);
      appendTable(section, `Equipment (${Math.min(result.rows?.length || 0, 150)} shown)`, (result.rows || []).slice(0, 150), [
        ['serial_number', 'Serial number'], ['equipment', 'Equipment'], ['model', 'Model'],
        ['equipment_family', 'Family'], ['brand', 'Brand'], ['site', 'MineSite'],
      ]);
    }
    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'codex-result__export';
    exportButton.textContent = 'Export CSV';
    exportButton.addEventListener('click', async () => {
      exportButton.disabled = true;
      try {
        const response = await fetch(`${root.dataset.runBase}${run.id}/export/`, {
          method: 'POST', headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || 'Export unavailable.');
        window.location.assign(payload.artifact.download_url);
      } catch (error) {
        progressWrap.hidden = false;
        progress.textContent = error.message;
      } finally {
        exportButton.disabled = false;
      }
    });
    section.append(exportButton);
    thread.append(section);
    thread.scrollTop = thread.scrollHeight;
  };

  const setRunState = (run) => {
    progressWrap.hidden = false;
    progressBar.style.width = `${run.progress_percent || 0}%`;
    progress.textContent = run.progress_label || 'Processing...';
    cancelButton.hidden = !run.can_cancel;
    submitButton.disabled = !run.terminal;
    input.disabled = !run.terminal;
  };

  const finishRun = (run) => {
    clearTimeout(pollTimer);
    activeRunId = '';
    root.dataset.activeRunId = '';
    setRunState(run);
    cancelButton.hidden = true;
    submitButton.disabled = false;
    input.disabled = false;
    if (run.message) {
      appendMessage(run.message.role, run.message.content, run.message.answer_status, run.message.id, run.id);
    }
    if (!thread.querySelector(`.codex-result[data-run-id="${run.id}"]`)) appendFleetResult(run);
    input.focus();
  };

  const pollRun = async () => {
    if (!activeRunId) return;
    try {
      const response = await fetch(`${root.dataset.runBase}${activeRunId}/`, {
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Status unavailable.');
      setRunState(payload.run);
      if (payload.run.provisional_message) {
        const draft = payload.run.provisional_message;
        appendMessage(draft.role, draft.content, `${draft.answer_status} · Codex summary in progress`, '', payload.run.id);
      }
      if (payload.run.result && !thread.querySelector(`.codex-result[data-run-id="${payload.run.id}"]`)) {
        appendFleetResult(payload.run);
      }
      if (payload.run.terminal) finishRun(payload.run);
      else pollTimer = setTimeout(pollRun, 800);
    } catch (error) {
      progressWrap.hidden = false;
      progress.textContent = `${error.message} Retrying...`;
      pollTimer = setTimeout(pollRun, 2000);
    }
  };

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      if (!input.disabled && !event.repeat) form.requestSubmit();
    }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 190)}px`;
  });
  let submitting = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submitting || activeRunId) return;
    if (root.dataset.voiceActive === '1') { form.dispatchEvent(new Event('codex:voice-send')); return; }
    const question = input.value.trim();
    if (!question || question.length > 3000) { input.focus(); return; }
    submitting = true;
    const requestId = crypto.randomUUID();
    appendMessage('USER', question, '', `pending-${requestId}`);
    input.value = '';
    submitButton.disabled = true;
    input.disabled = true;
    progressWrap.hidden = false;
    progressBar.style.width = '0%';
    progress.textContent = 'Submitting your request...';
    try {
      const response = await fetch(root.dataset.submitUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
        body: JSON.stringify({
          question,
          request_id: requestId,
          conversation_id: thread.dataset.conversationId || null,
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'The request failed.');
      activeRunId = payload.run.id;
      root.dataset.activeRunId = activeRunId;
      thread.dataset.conversationId = payload.run.conversation_id;
      document.dispatchEvent(new CustomEvent('codex:conversation-created', {detail: {id: payload.run.conversation_id, title: question.slice(0, 180)}}));
      history.replaceState({}, '', `/codex-chatbot/c/${payload.run.conversation_id}/`);
      submitting = false;
      setRunState(payload.run);
      pollRun();
    } catch (error) {
      submitting = false;
      thread.querySelector(`[data-message-id="pending-${requestId}"]`)?.remove();
      input.value = question;
      appendMessage('ASSISTANT', error.message, 'TEMPORARILY_UNAVAILABLE');
      progress.textContent = 'Submission failed.';
      submitButton.disabled = false;
      input.disabled = false;
      input.focus();
    }
  });

  cancelButton.addEventListener('click', async () => {
    if (!activeRunId) return;
    cancelButton.disabled = true;
    try {
      const response = await fetch(`${root.dataset.runBase}${activeRunId}/cancel/`, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Unable to cancel.');
      setRunState(payload.run);
      if (payload.run.terminal) finishRun(payload.run);
    } catch (error) {
      progress.textContent = error.message;
    } finally {
      cancelButton.disabled = false;
    }
  });

  if (activeRunId) {
    submitButton.disabled = true;
    input.disabled = true;
    progressWrap.hidden = false;
    progress.textContent = 'Resuming progress updates...';
    pollRun();
  } else if (root.dataset.conversationUrl) {
    fetch(root.dataset.conversationUrl, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then((response) => response.json())
      .then((payload) => {
        (payload.conversation?.runs || []).reverse().forEach((run) => {
          if (!thread.querySelector(`.codex-result[data-run-id="${run.id}"]`)) appendFleetResult(run);
        });
      })
      .catch(() => {});
  }
})();
