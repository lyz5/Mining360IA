(() => {
  'use strict';
  if (window.m360AjaxSpinner) return;
  const loader = document.querySelector('[data-ajax-spinner]');
  if (!loader) return;
  let pending = 0;
  let hideTimer;
  let showTimer;
  let shownAt = 0;
  let initialLoad = true;
  let actionUntil = 0;
  const markAction = () => { actionUntil = performance.now() + 700; };
  for (const event of ['click', 'change', 'submit', 'input']) {
    document.addEventListener(event, markAction, true);
  }
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => { initialLoad = false; }, 1500);
  }, {once: true});
  const isForeground = () => initialLoad || performance.now() < actionUntil;
  function begin(enabled = true) {
    if (!enabled) return () => {};
    pending += 1;
    clearTimeout(hideTimer);
    if (loader.hidden && !showTimer) {
      showTimer = setTimeout(() => {
        showTimer = null;
        if (pending) { loader.hidden = false; shownAt = performance.now(); }
      }, 180);
    }
    let finished = false;
    return () => {
      if (finished) return;
      finished = true;
      pending -= 1;
      if (!pending) {
        clearTimeout(showTimer); showTimer = null;
        hideTimer = setTimeout(() => {
          if (!pending) { loader.hidden = true; initialLoad = false; }
        }, Math.max(200, 350 - (performance.now() - shownAt)));
      }
    };
  }
  window.m360AjaxSpinner = { begin, get pending() { return pending; } };
  document.documentElement.classList.add('ajax-spinner-ready');
  const wrappedResponses = new WeakSet();
  function wrapResponse(response, foreground) {
    if (wrappedResponses.has(response)) return response;
    wrappedResponses.add(response);
    // Track body consumption without reading or cloning streams ourselves.
    for (const name of ['json', 'text', 'blob', 'arrayBuffer', 'formData', 'bytes']) {
      const original = response[name];
      if (typeof original !== 'function') continue;
      response[name] = function (...args) {
        const end = begin(foreground);
        try { return Promise.resolve(original.apply(this, args)).finally(end); }
        catch (error) { end(); throw error; }
      };
    }
    return response;
  }
  if (window.fetch) {
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
      const foreground = isForeground();
      const end = begin(foreground);
      try { return originalFetch.apply(this, args).then(response => wrapResponse(response, foreground)).finally(end); }
      catch (error) { end(); throw error; }
    };
  }
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    const end = begin(isForeground());
    const complete = () => { this.removeEventListener('loadend', complete); end(); };
    this.addEventListener('loadend', complete);
    try { return originalSend.apply(this, args); }
    catch (error) { complete(); throw error; }
  };
})();
