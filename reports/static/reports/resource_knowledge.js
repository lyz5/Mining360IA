(() => {
  'use strict';
  const root = document.querySelector('.kb-review');
  if (!root) return;
  const dialog = document.getElementById('resource-kb-item-dialog');
  const content = dialog.querySelector('[data-kb-detail-content]');
  const detailStatus = dialog.querySelector('[data-kb-detail-status]');
  const footer = dialog.querySelector('footer');
  const notice = root.querySelector('[data-kb-notice]');
  const csrf = root.querySelector('[name=csrfmiddlewaretoken]').value;
  const busy = new Set();
  let detailRequest = 0;
  const endpoint = id => root.dataset.itemUrlTemplate.replace('__ITEM_ID__', encodeURIComponent(id));
  async function request(id, init) {
    const response = await fetch(endpoint(id), init);
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || 'Unable to save or load this knowledge. Please try again.');
    return payload;
  }
  function showNotice(message, error = false) {
    notice.hidden = false;
    notice.textContent = message;
    notice.classList.toggle('is-error', error);
  }
  function section(title, value, tag = 'p') {
    if (!value || (Array.isArray(value) && !value.length)) return;
    const heading = document.createElement('h3'); heading.textContent = title; content.append(heading);
    if (Array.isArray(value)) {
      const list = document.createElement('ul');
      value.forEach(text => { const item = document.createElement('li'); item.textContent = text; list.append(item); });
      content.append(list);
    } else { const node = document.createElement(tag); node.textContent = value; content.append(node); }
  }
  async function details(id) {
    const current = ++detailRequest;
    content.replaceChildren(); footer.hidden = true;
    dialog.querySelectorAll('[data-kb-decision]').forEach(button => { delete button.dataset.kbId; });
    detailStatus.textContent = 'Loading details...';
    if (!dialog.open) dialog.showModal();
    try {
      const {item} = await request(id);
      if (current !== detailRequest || !dialog.open) return;
      detailStatus.textContent = item.validation_status;
      section('Best Practice', item.source.document);
      section('Identified Knowledge', item.title);
      const fields = [['Equipment', 'equipment'], ['Model', 'equipment_model'], ['System', 'system'], ['Component', 'component'], ['Subcomponent', 'subcomponent'], ['Symptom', 'symptom'], ['Failure mode', 'failure_mode'], ['Fault codes', 'fault_codes'], ['Probable causes', 'probable_causes'], ['Conditions', 'occurrence_conditions'], ['Impacts', 'possible_impacts'], ['Inspection', 'inspection_procedure'], ['Troubleshooting', 'troubleshooting_procedure'], ['Best practices', 'best_practices'], ['Recommendations', 'recommendations'], ['Safety instructions', 'safety_instructions'], ['Validation notes', 'validation_notes']];
      fields.forEach(([label, key]) => section(label, item[key]));
      section(item.source.page ? `Source excerpt · Page ${item.source.page}` : 'Source excerpt', item.source.excerpt, 'blockquote');
      const link = document.createElement('a'); link.textContent = item.source.page ? `Open PDF · Page ${item.source.page}` : 'Open source document';
      link.href = item.source.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; content.append(link);
      footer.hidden = false;
      footer.querySelectorAll('[data-kb-decision]').forEach(button => { button.dataset.kbId = id; button.disabled = busy.has(id) || button.dataset.kbDecision === item.validation_status; });
    } catch (error) { if (current === detailRequest) detailStatus.textContent = error.message; }
  }
  async function decide(id, status) {
    if (!id || busy.has(id)) return;
    busy.add(id);
    const buttons = Array.from(document.querySelectorAll('[data-kb-decision]')).filter(button => button.dataset.kbId === id);
    buttons.forEach(button => { button.disabled = true; });
    const row = root.querySelector(`[data-kb-row="${id}"]`);
    const previous = row?.querySelector('[data-kb-status]').textContent;
    let saved = false;
    try {
      const payload = await request(id, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify({validation_status: status})});
      saved = true;
      if (row) row.querySelector('[data-kb-status]').textContent = payload.status;
      if (dialog.open && footer.querySelector('[data-kb-id]')?.dataset.kbId === id) dialog.close();
      showNotice(status === 'Validated' ? 'Knowledge validated.' : 'Knowledge rejected.');
      // Refresh a filtered page so pagination cannot skip records as the queue shrinks.
      if (root.dataset.statusFilter && root.dataset.statusFilter !== status) window.location.reload();
    } catch (error) {
      showNotice(error.message, true);
      if (dialog.open) detailStatus.textContent = error.message;
    } finally {
      busy.delete(id);
      buttons.forEach(button => { button.disabled = button.dataset.kbDecision === (saved ? status : previous); });
    }
  }
  function clicked(event) {
    const detail = event.target.closest('[data-kb-detail]');
    if (detail) details(detail.dataset.kbDetail);
    const decision = event.target.closest('[data-kb-decision]');
    if (decision && !decision.disabled) decide(decision.dataset.kbId, decision.dataset.kbDecision);
  }
  root.addEventListener('click', clicked); dialog.addEventListener('click', clicked);
  dialog.querySelector('[data-kb-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { ++detailRequest; });
})();
