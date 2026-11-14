/* Native presentation layer. Never fetches business data or embeds a report. */
(() => {
  'use strict';
  if (!document.documentElement.classList.contains('m360-responsive')) return;
  const nav = document.querySelector('.app-nav');
  const main = document.querySelector('main.app-shell');
  if (!nav || !main) return;
  const compact = matchMedia('(max-width: 1199px)');
  const phone = matchMedia('(max-width: 767px)');
  const body = document.body;
  const originalNavLabel = nav.getAttribute('aria-label');
  const originalMainId = main.id;
  if (!main.id) main.id = 'm360-main-content';
  if (!main.hasAttribute('tabindex')) main.tabIndex = -1;
  const header = document.createElement('header');
  header.className = 'm360-compact-header';
  const brand = nav.querySelector('.brand').cloneNode(true);
  brand.className = 'm360-compact-brand';
  const title = document.createElement('span');
  title.className = 'm360-compact-title';
  title.textContent = document.title.split('|')[0].trim();
  const menu = document.createElement('button');
  menu.type = 'button'; menu.className = 'm360-menu-button';
  menu.textContent = 'Menu'; menu.setAttribute('aria-expanded', 'false');
  nav.id ||= 'm360-navigation';
  menu.setAttribute('aria-controls', nav.id);
  header.append(brand, title, menu);
  const bottom = document.createElement('nav');
  bottom.className = 'm360-bottom-nav'; bottom.setAttribute('aria-label', 'Application destinations');
  // Server-authorized links are the single destination/permission definition.
  nav.querySelectorAll('[data-mobile-destination]').forEach(source => {
    const link = source.cloneNode(true);
    link.querySelector('span').textContent = source.dataset.mobileDestination;
    link.removeAttribute('data-mobile-destination');
    link.title = source.textContent.trim();
    link.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
    bottom.append(link);
  });
  const more = document.createElement('button');
  more.type = 'button'; more.textContent = 'More'; more.className = 'm360-more-button';
  more.setAttribute('aria-controls', nav.id); more.setAttribute('aria-expanded', 'false');
  const dots = document.createElement('span'); dots.textContent = '•••'; dots.setAttribute('aria-hidden','true');
  more.prepend(dots); bottom.append(more);
  bottom.style.setProperty('--destinations', bottom.children.length);
  const close = document.createElement('button');
  close.type = 'button'; close.textContent = 'Close menu'; close.className = 'm360-menu-close';
  nav.prepend(close);
  const backdrop = document.createElement('button');
  backdrop.type = 'button'; backdrop.className = 'm360-menu-backdrop'; backdrop.hidden = true;
  backdrop.setAttribute('aria-label', 'Close navigation menu');
  const skip = document.createElement('a');
  skip.className = 'm360-skip'; skip.href = `#${main.id}`; skip.textContent = 'Skip to content';
  body.prepend(skip, header, backdrop); body.append(bottom);
  let opener = null;
  let menuOpen = false;
  let previousMainInert = false;
  function setMenu(open, trigger) {
    if (open && !compact.matches) return;
    if (menuOpen === open) return;
    if (open) {
      document.querySelector('[data-filter-sheet].open [data-filter-close]')?.click();
      if (main.classList.contains('history-open')) main.querySelector('#codex-history-toggle')?.click();
    }
    menuOpen = open;
    if (open) { opener = trigger || document.activeElement; previousMainInert = main.inert; }
    body.classList.toggle('m360-menu-open', open);
    menu.setAttribute('aria-expanded', String(open)); more.setAttribute('aria-expanded', String(open));
    backdrop.hidden = !open; main.inert = open || previousMainInert;
    nav.inert = compact.matches && !open;
    if (open) {
      nav.setAttribute('role', 'dialog'); nav.setAttribute('aria-modal', 'true');
      nav.setAttribute('aria-label', 'More destinations'); close.focus();
    } else {
      nav.removeAttribute('role'); nav.removeAttribute('aria-modal');
      nav.setAttribute('aria-label', originalNavLabel);
      if (opener?.isConnected && compact.matches) opener.focus();
      opener = null;
    }
  }
  menu.addEventListener('click', () => setMenu(!menuOpen, menu));
  more.addEventListener('click', () => setMenu(!menuOpen, more));
  close.addEventListener('click', () => setMenu(false));
  backdrop.addEventListener('click', () => setMenu(false));
  document.addEventListener('keydown', event => {
    if (!menuOpen) return;
    if (event.key === 'Escape') { event.preventDefault(); setMenu(false); }
    if (event.key === 'Tab') {
      const stops = [...nav.querySelectorAll('a[href],button:not(:disabled),input,select,[tabindex="0"]')]
        .filter(node => node.getClientRects().length);
      const first = stops[0], last = stops.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  function adapt() {
    if (!compact.matches) setMenu(false);
    nav.inert = compact.matches && !menuOpen;
    header.hidden = !compact.matches; bottom.hidden = !phone.matches;
    skip.tabIndex = compact.matches ? 0 : -1;
    // The existing page owns nav-collapsed and its desktop preference (including
    // the viewer's separate navMode). Compact navigation never changes either.
  }
  compact.addEventListener('change', adapt); phone.addEventListener('change', adapt); adapt();

  // Local scrolling retains every column and the original table/handlers.
  const wrapped = new Set();
  const enhanceTables = () => {
    wrapped.forEach(wrapper => { if (!wrapper.isConnected) wrapped.delete(wrapper); });
    if (!compact.matches) {
      wrapped.forEach(wrapper => { if (wrapper.isConnected) wrapper.replaceWith(...wrapper.childNodes); });
      wrapped.clear(); return;
    }
    main.querySelectorAll('table').forEach(table => {
      if (table.closest('.m360-table-scroll,.pf-table-scroll,.pf-chart-scroll,.bcc-table-wrap,.table-scroll,.table-wrap,.codex-result__table')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'm360-table-scroll'; wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', `${table.caption?.textContent || 'Data table'} — scroll for all columns`);
      table.before(wrapper); wrapper.append(table); wrapped.add(wrapper);
    });
  };
  let tableFrame = 0;
  new MutationObserver(() => {
    if (!compact.matches || tableFrame) return;
    tableFrame = requestAnimationFrame(() => { tableFrame = 0; enhanceTables(); });
  }).observe(main, {childList:true,subtree:true});
  compact.addEventListener('change', enhanceTables); enhanceTables();

  // Reuse each real secondary navigator in one collapsible compact panel.
  // Moving (never cloning) preserves selections, unsaved forms and listeners.
  const panels = new Map();
  const panelDefinitions = [
    ['.aiw-section-navigator', 'AI sections'],
    ['.report-config-sidebar', 'Reports'],
    ['.ia-config-sidebar', 'Knowledge navigation'],
    ['.data-browser-list-panel', 'Data browsers'],
    ['.source-catalog-pane', 'Source objects'],
    ['[data-context-controls]', 'Fleet filters'],
  ];
  function adaptPanels() {
    if (!compact.matches) {
      panels.forEach(({details, onSelect}, node) => {
        node.removeEventListener('click', onSelect);
        if (details.isConnected) details.replaceWith(node);
      });
      panels.clear(); return;
    }
    panelDefinitions.forEach(([selector, label]) => {
      const node = main.querySelector(selector);
      if (!node || panels.has(node)) return;
      const details = document.createElement('details'); details.className = 'm360-compact-panel';
      const summary = document.createElement('summary'); summary.textContent = label;
      details.append(summary); node.before(details); details.append(node);
      const onSelect = event => {
        if (event.target.closest('[data-section-code],[data-report-id],[data-browser-id]') && compact.matches) details.open = false;
      };
      node.addEventListener('click', onSelect); panels.set(node, {details,onSelect});
    });
  }
  compact.addEventListener('change', adaptPanels); adaptPanels();

  const charts = [...main.querySelectorAll('.bcc-trend-visual,.availability-home .trend-chart')].map(frame =>
    [frame, ['tabindex','role','aria-label'].map(name => [name,frame.getAttribute(name)])]);
  const adaptCharts = () => charts.forEach(([frame, original]) => {
    if (compact.matches) {
      frame.tabIndex = 0; frame.setAttribute('role','region');
      frame.setAttribute('aria-label',`${frame.classList.contains('bcc-trend-visual') ? 'Revenue' : 'Fleet'} trend. Scroll horizontally to view all periods.`);
    } else original.forEach(([name,value]) => value === null ? frame.removeAttribute(name) : frame.setAttribute(name,value));
  });
  compact.addEventListener('change', adaptCharts); adaptCharts();

  if (main.id === 'availability-command-center') {
    const controls = main.querySelector('.analysis-controls');
    new ResizeObserver(() => {
      const notice = main.querySelector('[data-display-context]');
      if (notice && !notice.hidden) notice.style.top = `${controls.offsetTop + controls.offsetHeight + 10}px`;
    }).observe(controls);
  }

  const chat = main.matches('.codex-chat');
  if (chat) {
    const input = main.querySelector('textarea');
    const historyPane = main.querySelector('.codex-chat__history');
    const conversation = main.querySelector('.codex-chat__main');
    const historyToggle = main.querySelector('#codex-history-toggle');
    const historyClose = document.createElement('button');
    historyClose.type = 'button'; historyClose.className = 'm360-history-close'; historyClose.textContent = 'Close conversations';
    historyPane.prepend(historyClose);
    const syncHistory = () => {
      const open = compact.matches && main.classList.contains('history-open');
      conversation.inert = open;
      if (open) {
        historyPane.setAttribute('role','dialog'); historyPane.setAttribute('aria-modal','true'); historyClose.focus();
      } else {
        historyPane.removeAttribute('role'); historyPane.removeAttribute('aria-modal');
      }
    };
    // The existing conversations script owns the class toggle; read it after
    // all click listeners, independent of deferred script execution order.
    historyToggle.addEventListener('click', () => requestAnimationFrame(() => {
      syncHistory();
      if (!main.classList.contains('history-open')) historyToggle.focus();
    }));
    historyClose.addEventListener('click', () => { historyToggle.click(); historyToggle.focus(); });
    compact.addEventListener('change', () => {
      if (!compact.matches) main.classList.remove('history-open');
      syncHistory();
    });
    historyPane.addEventListener('keydown', event => {
      if (!compact.matches) return;
      if (event.key === 'Escape') { historyClose.click(); event.stopPropagation(); }
      if (event.key === 'Tab') {
        const stops = [...historyPane.querySelectorAll('button:not(:disabled),a[href],input,summary')].filter(node => node.getClientRects().length);
        if (event.shiftKey && document.activeElement === stops[0]) { event.preventDefault(); stops.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === stops.at(-1)) { event.preventDefault(); stops[0]?.focus(); }
      }
    });
    const updateViewport = () => {
      const typing = phone.matches && (document.activeElement === input);
      body.classList.toggle('m360-composing', typing);
      main.style.setProperty('--m360-visible-height', `${window.visualViewport?.height || innerHeight}px`);
    };
    input?.addEventListener('focus', updateViewport); input?.addEventListener('blur', updateViewport);
    window.visualViewport?.addEventListener('resize', updateViewport);
    phone.addEventListener('change', updateViewport); updateViewport();
  }
})();
