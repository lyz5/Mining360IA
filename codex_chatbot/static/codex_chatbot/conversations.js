(() => {
  const root = document.querySelector('.codex-chat');
  if (!root) return;
  const list = document.querySelector('#codex-history-list');
  const dialog = document.querySelector('#codex-conversation-dialog');
  const titleInput = document.querySelector('#codex-conversation-title');
  const error = document.querySelector('#codex-dialog-error');
  const csrf = document.querySelector('#codex-composer [name=csrfmiddlewaretoken]').value;
  let pending = null;
  let saving = false;
  document.querySelector('#codex-history-search').addEventListener('input', (event) => {
    const normalize = (text) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const query = normalize(event.target.value);
    list.querySelectorAll('.codex-history-row').forEach(row => { row.hidden = !normalize(row.dataset.title).includes(query); });
  });

  async function apply(action, row, title) {
    const id = row.dataset.conversationId;
    const response = await fetch(`/codex-chatbot/api/conversations/${id}/`, {
      method: action === 'delete' ? 'DELETE' : 'PATCH',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: action === 'delete' ? undefined : JSON.stringify(action === 'rename' ? {title} : {status: action === 'archive' ? 'ARCHIVED' : 'ACTIVE'}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Unable to update the conversation.');
    if (action === 'rename') {
      row.dataset.title = payload.conversation.title;
      row.querySelector('strong').textContent = payload.conversation.title;
      if (document.querySelector('#codex-thread').dataset.conversationId === id) {
        document.querySelector('.codex-chat__header h1').textContent = payload.conversation.title;
      }
      row.querySelector('details').open = false;
    } else if (document.querySelector('#codex-thread').dataset.conversationId === id) {
      window.location.assign('/codex-chatbot/');
    } else {
      row.remove();
    }
  }
  list.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-conversation-action]');
    if (!button || saving) return;
    const row = button.closest('[data-conversation-id]');
    const action = button.dataset.conversationAction;
    error.textContent = '';
    if (['rename', 'delete'].includes(action)) {
      pending = {action, row};
      const deleting = action === 'delete';
      document.querySelector('#codex-dialog-title').textContent = deleting ? 'Delete this conversation?' : 'Rename conversation';
      document.querySelector('#codex-dialog-description').textContent = deleting ? 'Its messages and data will be deleted from the application. This action cannot be undone.' : '';
      document.querySelector('#codex-title-label').hidden = deleting;
      titleInput.hidden = deleting;
      titleInput.value = row.dataset.title;
      document.querySelector('#codex-dialog-confirm').textContent = deleting ? 'Delete' : 'Save';
      dialog.showModal();
      if (!deleting) { titleInput.focus(); titleInput.select(); }
    } else {
      saving = true;
      button.disabled = true;
      try { await apply(action, row); }
      catch (err) { document.querySelector('#codex-progress').textContent = err.message; document.querySelector('#codex-run-progress').hidden = false; }
      finally { saving = false; button.disabled = false; }
    }
  });
  dialog.querySelector('form').addEventListener('submit', async (event) => {
    if (event.submitter?.value !== 'confirm') return;
    event.preventDefault();
    if (!pending || saving) return;
    if (pending.action === 'rename' && !titleInput.value.trim()) { error.textContent = 'Enter a title.'; return; }
    saving = true;
    document.querySelector('#codex-dialog-confirm').disabled = true;
    try { await apply(pending.action, pending.row, titleInput.value.trim()); dialog.close(); }
    catch (err) { error.textContent = err.message; }
    finally { saving = false; document.querySelector('#codex-dialog-confirm').disabled = false; }
  });
  document.addEventListener('codex:conversation-created', (event) => {
    const {id, title} = event.detail;
    if (Array.from(list.children).some(row => row.dataset.conversationId === id)) return;
    list.querySelector('.codex-muted')?.remove();
    const row = document.createElement('div');
    row.className = 'codex-history-row';
    Object.assign(row.dataset, {conversationId: id, title, status: 'ACTIVE'});
    const link = document.createElement('a');
    link.className = 'codex-history-item is-active';
    link.href = `/codex-chatbot/c/${id}/`;
    const heading = document.createElement('strong'); heading.textContent = title;
    link.append(heading); row.append(link);
    const menu = document.createElement('details'); menu.className = 'codex-conversation-menu';
    const summary = document.createElement('summary'); summary.textContent = '⋯'; summary.setAttribute('aria-label', 'Conversation actions'); menu.append(summary);
    const choices = document.createElement('div');
    [['rename', 'Rename'], ['archive', 'Archive'], ['delete', 'Delete']].forEach(([action, label]) => {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.conversationAction = action; button.textContent = label; choices.append(button);
    });
    menu.append(choices); row.append(menu); list.prepend(row);
    document.querySelector('.codex-chat__header h1').textContent = title;
  });
  const toggle = document.querySelector('#codex-history-toggle');
  toggle.addEventListener('click', () => {
    const open = root.classList.toggle('history-open'); toggle.setAttribute('aria-expanded', String(open));
  });
})();
