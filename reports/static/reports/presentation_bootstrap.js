/* Same-origin presentation bootstrap; no inline script or CSP relaxation. */
(() => {
  const flags = document.currentScript.dataset;
  if (flags.responsive === 'true') document.documentElement.classList.add('m360-responsive');
  if (flags.businessTheme === 'true') document.documentElement.classList.add('m360-business-theme');
})();
