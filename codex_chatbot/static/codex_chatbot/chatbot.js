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

  const appendMessage = (role, content, status = '', messageId = '', runId = '') => {
    const provisional = runId ? thread.querySelector(`[data-provisional-run-id="${runId}"]`) : null;
    if (provisional) {
      provisional.querySelector('p').textContent = content;
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
    label.textContent = role === 'USER' ? 'Utilisateur' : 'Assistant';
    const text = document.createElement('p');
    text.textContent = content;
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
        tr.insertCell().textContent = value === null || value === undefined || value === '' ? 'Non renseigné' : value;
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
    if (result.kind === 'availability_summary') {
      const context = result.context || {};
      const availability = result.availability || {};
      const comparison = availability.comparison || {};
      const summary = document.createElement('div');
      summary.className = 'codex-result__summary';
      [
        ['Disponibilité physique', availability.formatted_value || 'Non disponible'],
        ['Écart', comparison.delta_points === null || comparison.delta_points === undefined ? 'N/D' : `${comparison.delta_points} points`],
        ['Équipements', result.summary?.equipment_count ?? 'N/D'],
        ['Période', context.period_label || 'N/D'],
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
        appendTable(section, 'Évolution de la disponibilité', result.trend, [
          ['period', 'Période'], ['formatted_value', 'Disponibilité'],
        ]);
      }
      if (result.presentation?.show_breakdown) {
        appendTable(section, 'Détail du périmètre', result.breakdown, [
          ['entity', 'Entité'], ['formatted_value', 'Disponibilité'],
          ['equipment_count', 'Équipements'], ['downtime_hours', 'Heures d’arrêt'],
        ]);
      }
      const trust = document.createElement('p');
      trust.className = 'codex-result__trust';
      trust.textContent = `${result.source_table} · Mesure ${result.source_measure || 'Physical Availability'} · Données au ${result.data_quality?.latest_available_date || 'N/D'}${result.data_quality?.is_stale ? ' · Données anciennes' : ''}`;
      section.append(trust);
    } else if (result.kind === 'revenue_summary') {
      const context = result.context;
      const summary = document.createElement('div');
      summary.className = 'codex-result__summary';
      [
        ['Revenue EUR', Number(result.hero.revenue).toLocaleString('fr-FR', {maximumFractionDigits: 2})],
        ['Variation EUR', Number(result.hero.absolute_delta).toLocaleString('fr-FR', {maximumFractionDigits: 2})],
        ['Variation %', result.hero.relative_delta === null ? 'N/D' : `${result.hero.relative_delta} %`],
        ['Période', context.period_label],
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
      appendTable(section, 'Revenue par ligne métier', result.business_lines, [
        ['rank', 'Rang'], ['label', 'Ligne'], ['revenue', 'Revenue EUR'],
        ['comparison_revenue', 'Comparaison EUR'], ['absolute_delta', 'Écart EUR'],
        ['relative_delta', 'Écart %'], ['share', 'Part %'],
      ]);
      appendTable(section, 'Principaux clients', result.top_customers, [
        ['rank', 'Rang'], ['name', 'Client'], ['revenue', 'Revenue EUR'], ['absolute_delta', 'Écart EUR'], ['share', 'Part %'],
      ]);
      appendTable(section, 'Principaux pays', result.top_countries, [
        ['rank', 'Rang'], ['name', 'Pays'], ['revenue', 'Revenue EUR'], ['absolute_delta', 'Écart EUR'], ['share', 'Part %'],
      ]);
      appendTable(section, 'Principaux Key Accounts', result.top_key_accounts, [
        ['rank', 'Rang'], ['name', 'Key Account'], ['revenue', 'Revenue EUR'], ['absolute_delta', 'Écart EUR'], ['share', 'Part %'],
      ]);
      const trust = document.createElement('p');
      trust.className = 'codex-result__trust';
      trust.textContent = `Données au ${result.freshness.data_through_date} · Mapping publié v${context.published_mapping_version ?? 'N/D'} · Réconciliation ${result.reconciliation.status} · Confiance ${result.confidence.status}`;
      section.append(trust);
    } else if (result.machine) {
      appendTable(section, 'Fiche machine', [result.machine], [
        ['serial_number', 'Série'], ['equipment', 'Équipement'], ['model', 'Modèle'],
        ['equipment_family', 'Famille'], ['brand', 'Marque'], ['site', 'MineSite'], ['smu', 'SMU'],
      ]);
    } else {
      const summary = document.createElement('div');
      summary.className = 'codex-result__summary';
      [
        ['Équipements', result.equipment_count], ['Séries', result.serial_count],
        ['Modèles', result.model_count], ['Familles', result.family_count],
      ].forEach(([label, value]) => {
        const item = document.createElement('div');
        const strong = document.createElement('strong');
        strong.textContent = value ?? 'N/D';
        const span = document.createElement('span');
        span.textContent = label;
        item.append(strong, span);
        summary.append(item);
      });
      section.append(summary);
      appendTable(section, 'Répartition par modèle', result.models, [['model', 'Modèle'], ['equipment_count', 'Équipements']]);
      appendTable(section, 'Répartition par famille', result.families, [['equipment_family', 'Famille'], ['equipment_count', 'Équipements']]);
      appendTable(section, `Équipements (${Math.min(result.rows?.length || 0, 150)} affichés)`, (result.rows || []).slice(0, 150), [
        ['serial_number', 'Série'], ['equipment', 'Équipement'], ['model', 'Modèle'],
        ['equipment_family', 'Famille'], ['brand', 'Marque'], ['site', 'MineSite'],
      ]);
    }
    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'codex-result__export';
    exportButton.textContent = 'Exporter CSV';
    exportButton.addEventListener('click', async () => {
      exportButton.disabled = true;
      try {
        const response = await fetch(`${root.dataset.runBase}${run.id}/export/`, {
          method: 'POST', headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || 'Export impossible.');
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
    progress.textContent = run.progress_label || 'Traitement en cours...';
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
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Statut indisponible.');
      setRunState(payload.run);
      if (payload.run.provisional_message) {
        const draft = payload.run.provisional_message;
        appendMessage(draft.role, draft.content, `${draft.answer_status} · Synthèse Codex en cours`, '', payload.run.id);
      }
      if (payload.run.result && !thread.querySelector(`.codex-result[data-run-id="${payload.run.id}"]`)) {
        appendFleetResult(payload.run);
      }
      if (payload.run.terminal) finishRun(payload.run);
      else pollTimer = setTimeout(pollRun, 800);
    } catch (error) {
      progressWrap.hidden = false;
      progress.textContent = `${error.message} Nouvelle tentative...`;
      pollTimer = setTimeout(pollRun, 2000);
    }
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || activeRunId) return;
    const requestId = crypto.randomUUID();
    appendMessage('USER', question);
    input.value = '';
    submitButton.disabled = true;
    input.disabled = true;
    progressWrap.hidden = false;
    progressBar.style.width = '0%';
    progress.textContent = 'Enregistrement de la demande...';
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
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'La demande a échoué.');
      activeRunId = payload.run.id;
      root.dataset.activeRunId = activeRunId;
      thread.dataset.conversationId = payload.run.conversation_id;
      history.replaceState({}, '', `/codex-chatbot/c/${payload.run.conversation_id}/`);
      setRunState(payload.run);
      pollRun();
    } catch (error) {
      appendMessage('ASSISTANT', error.message, 'TEMPORARILY_UNAVAILABLE');
      progress.textContent = 'Échec de la soumission.';
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
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Annulation impossible.');
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
    progress.textContent = 'Reprise du suivi du traitement...';
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
