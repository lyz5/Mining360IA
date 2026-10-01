/* Copy rendered visuals only: no fetching, calculations or changes to filter state. */
(() => {
    "use strict";
    const root = document.querySelector('[data-command-center], #availability-command-center');
    const exporter = window.Mining360VisualExport;
    if (!root || !exporter) return;
    const business = root.matches('[data-command-center]');
    const selectors = business ? [
        '.bcc-hero', '.bcc-line-card', '.bcc-trend-panel', '.bcc-brief-panel',
        '.bcc-leaders-panel', '.bcc-turnover-kpi', '.bcc-turnover-card',
        '.bcc-explorer', '.bcc-operation-summary', '.bcc-machine-sales', '.bcc-parts-sales',
    ] : [
        '.fuel-kpi-panel', '.fuel-distribution-panel', '.connectivity-card',
        '[data-summary-strip]', '[data-breakdown-section]', '.breakdown-card',
        '.performance-highlights', '.highlight-column', '.key-takeaway',
    ];
    const entries = new WeakMap();
    function visible(node) {
        return Boolean(node && !node.closest('[hidden]') && node.getClientRects().length);
    }
    function ready(target) {
        if (!visible(target) || root.classList.contains('is-updating')) return false;
        if (visible(root.querySelector(business ? '[data-error]' : '[data-homepage-error]'))) return false;
        if (business) {
            if (!visible(root.querySelector('[data-content]'))) return false;
            const workspace = target.closest('[data-workspace]');
            if (workspace?.querySelector('[data-turnover-status]:not([hidden]), [data-explorer-status]:not([hidden])')) return false;
            const operation = target.closest('[data-operation-view]');
            if (operation?.querySelector('[data-machine-status]:not([hidden]), [data-parts-status]:not([hidden])')) return false;
            if (target.matches('.bcc-leaders-panel')) {
                const list = root.querySelector('[data-leaders-preview]');
                if (list?.getAttribute('aria-busy') === 'true' || !list?.children.length) return false;
            }
        } else if (!root.querySelector('[data-refresh-status]')?.textContent.trim()) return false;
        return true;
    }
    function title(target) {
        return target.querySelector('h2, h3, header span, [data-hero-label], .breakdown-card__head strong')?.textContent.trim()
            || target.getAttribute('aria-label') || (business ? 'Business Overview' : 'Fleet Performance');
    }
    function install(target) {
        if (entries.has(target)) return;
        // Revenue Trend already uses the shared copy engine: retain its existing button.
        const existing = target.querySelector('[data-copy="trend"]');
        let surface = target;
        if (target.matches('button')) {
            // Keep the original card and drill-down handler; never nest buttons.
            surface = document.createElement('div');
            surface.className = 'm360-copy-card-wrapper';
            target.before(surface);
            surface.append(target);
        }
        let button = existing;
        if (!button) {
            surface.classList.add('m360-copy-surface');
            button = document.createElement('button');
            button.type = 'button';
            button.className = 'm360-visual-copy';
            button.textContent = 'Copy visual';
            button.dataset.exportIgnore = 'true';
            button.title = 'Copy this visual as a PNG image';
            button.setAttribute('aria-label', `Copy ${title(target)} as an image`);
            surface.append(button);
            exporter.bindCopyAction({
                button, target: surface, fileName: `Mining360_${title(target)}`,
                background: '#ffffff', scale: 2,
                canCopy: () => ready(target),
            });
        } else {
            button.dataset.exportIgnore = 'true';
        }
        entries.set(target, { surface, button });
    }
    function update() {
        root.querySelectorAll(selectors.join(',')).forEach(target => {
            install(target);
            const { surface, button } = entries.get(target);
            const enabled = ready(target);
            surface.dataset.exportReady = String(enabled);
            if (!button.hasAttribute('aria-busy') && button.disabled === enabled) button.disabled = !enabled;
        });
    }
    let scheduled = false;
    const schedule = () => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => { scheduled = false; update(); });
    };
    // Coalesce DOM renders, including lazy Sales tables. No polling or network calls.
    new MutationObserver(schedule).observe(root, {
        subtree: true, childList: true, attributes: true, attributeFilter: ['hidden', 'class', 'aria-busy'],
    });
    update();
})();
