(function () {
    const root = document.querySelector("[data-report-viewer]");
    const container = document.getElementById("powerbi-report");
    if (!root || !container || !window.Mining360PowerBIEmbed) return;

    const $ = (selector, scope = root) => scope.querySelector(selector);
    const $$ = (selector, scope = root) => [...scope.querySelectorAll(selector)];
    const reportId = root.dataset.reportId;
    const state = {
        config: null,
        embed: null,
        period: "",
        startDate: "",
        endDate: "",
        applied: null,
        fitMode: "fit_to_page",
        switcherFilter: "all",
        switcherQuery: "",
        switcher: [],
        activeDrawer: null,
        previousFocus: null,
        contextFilters: [],
        contextChips: [],
        eventsBound: false,
        switcherLoaded: false,
        switcherLoading: null,
        timings: { navigationStart: performance.now() },
    };

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function csrfToken() {
        return document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("csrftoken="))?.split("=").slice(1).join("=") || "";
    }

    async function request(url, options = {}) {
        const response = await fetch(url, { credentials: "same-origin", ...options });
        let payload = {};
        try { payload = await response.json(); } catch (_error) { /* normalized below */ }
        if (!response.ok || payload.ok === false) {
            const error = new Error(payload.error || `Request failed (${response.status}).`);
            error.code = payload.error_code || "request_failed";
            throw error;
        }
        return payload;
    }

    function setCanvasState(message, isError = false) {
        const node = $("[data-canvas-state]");
        if (node) node.textContent = message;
        const status = $("[data-filter-status]");
        if (status && isError) {
            status.textContent = message;
            status.classList.add("error");
        }
    }

    function setLoading(message) {
        const loading = $("[data-loading-state]");
        if (loading) loading.hidden = false;
        const label = $("[data-loading-message]");
        if (label) label.textContent = message;
        setCanvasState(message);
    }

    function showError(error) {
        const panel = $("[data-runtime-error]");
        const message = $("[data-runtime-error-message]");
        if (message) message.textContent = error?.message || "Power BI returned an unexpected error.";
        if (panel) panel.hidden = false;
        const connect = $("[data-connect-account]");
        if (connect) {
            connect.hidden = !(error?.authenticationRequired && error?.connectUrl);
            if (!connect.hidden) connect.href = error.connectUrl;
        }
        const loading = $("[data-loading-state]");
        if (loading) loading.hidden = true;
        setCanvasState("Report unavailable", true);
    }

    function dateInput(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    function periodRange(period) {
        const today = new Date();
        if (period === "custom") return { start: state.startDate, end: state.endDate };
        if (period === "ytd") return { start: dateInput(new Date(today.getFullYear(), 0, 1)), end: dateInput(today) };
        if (period === "mtd") return { start: dateInput(new Date(today.getFullYear(), today.getMonth(), 1)), end: dateInput(today) };
        if (period === "last_30_days") {
            const start = new Date(today); start.setDate(start.getDate() - 29);
            return { start: dateInput(start), end: dateInput(today) };
        }
        if (period === "last_month") {
            const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            const end = new Date(today.getFullYear(), today.getMonth(), 0);
            return { start: dateInput(start), end: dateInput(end) };
        }
        if (period === "last_12_months") return { start: dateInput(new Date(today.getFullYear(), today.getMonth() - 11, 1)), end: dateInput(today) };
        return { start: "", end: "" };
    }

    function dateInstruction(period) {
        const mapping = state.config?.viewer?.date_mapping;
        if (!mapping) return null;
        const range = periodRange(period);
        if (!range.start && !range.end) return null;
        const conditions = [];
        if (range.start) conditions.push({ operator: "GreaterThanOrEqual", value: `${range.start}T00:00:00.000Z` });
        if (range.end) conditions.push({ operator: "LessThanOrEqual", value: `${range.end}T23:59:59.999Z` });
        return {
            filter_code: "period",
            display_name: "Period",
            table: mapping.table,
            column: mapping.column,
            filter_type: "advanced",
            conditions,
        };
    }

    function draft() {
        return { period: state.period, startDate: state.startDate, endDate: state.endDate };
    }

    function isDirty() {
        return JSON.stringify(draft()) !== JSON.stringify(state.applied);
    }

    function updateApplyState() {
        const apply = $("[data-apply-filters]");
        if (apply) apply.disabled = !isDirty() || (state.period === "custom" && (!state.startDate || !state.endDate));
        const custom = $("[data-custom-range]");
        if (custom) custom.hidden = state.period !== "custom";
        $$('[data-period]').forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.period === state.period)));
    }

    function updateUrl() {
        const url = new URL(window.location.href);
        url.searchParams.set("period", state.period);
        if (state.period === "custom") {
            if (state.startDate) url.searchParams.set("start_date", state.startDate); else url.searchParams.delete("start_date");
            if (state.endDate) url.searchParams.set("end_date", state.endDate); else url.searchParams.delete("end_date");
        } else {
            url.searchParams.delete("start_date"); url.searchParams.delete("end_date");
        }
        history.replaceState({ reportViewer: true }, "", url);
    }

    function renderChips() {
        const periodLabel = state.config.viewer.available_periods.find((item) => item.code === state.period)?.label || state.period;
        const chips = [{ code: "period", label: "Period", value: periodLabel }, ...state.contextChips];
        if (state.period === "custom" && state.startDate && state.endDate) chips[0].value = `${state.startDate} → ${state.endDate}`;
        $("[data-active-filter-chips]").innerHTML = chips.map((item) => `<span>${escapeHtml(item.label)}: <strong>${escapeHtml(item.value)}</strong></span>`).join("");
        $("[data-active-filter-row]").hidden = chips.length === 0;
        $("[data-filter-count]").textContent = String(chips.length);
    }

    async function applyFilters({ announce = true } = {}) {
        const previous = state.applied;
        const instructions = [...state.contextFilters];
        const date = dateInstruction(state.period);
        if (date) instructions.unshift(date);
        try {
            setCanvasState("Updating report...");
            const page = await state.embed.getActivePage();
            await state.embed.applyFilters(page, instructions);
            state.applied = draft();
            updateApplyState(); updateUrl(); renderChips();
            const status = $("[data-filter-status]");
            if (status) { status.textContent = announce ? "Report filters updated." : ""; status.classList.remove("error"); }
            setCanvasState("Ready");
        } catch (error) {
            state.applied = previous;
            updateApplyState();
            const status = $("[data-filter-status]");
            if (status) { status.textContent = "The selected filters could not be applied. The previous report state remains active."; status.classList.add("error"); }
            setCanvasState("Filter update failed", true);
        }
    }

    async function resetFilters() {
        try {
            setCanvasState("Resetting filters...");
            await state.embed.clearFilters();
            if (state.config.viewer.reset_behavior === "defaults") {
                state.contextFilters = [...(state.config.initial_context.filters || [])];
                state.contextChips = [...(state.config.initial_context.chips || [])];
                state.period = state.config.viewer.default_period;
                const range = periodRange(state.period); state.startDate = range.start; state.endDate = range.end;
                await applyFilters();
            } else {
                state.contextFilters = [];
                state.contextChips = [];
                state.period = state.config.viewer.available_periods[0]?.code || "ytd";
                state.startDate = ""; state.endDate = ""; state.applied = draft();
                updateApplyState(); updateUrl(); renderChips(); setCanvasState("Ready");
            }
        } catch (error) { setCanvasState(error.message || "Filters could not be reset.", true); }
    }

    function renderStatus() {
        const status = state.config.refresh_status || {};
        const wrapper = $("[data-report-status]");
        wrapper.innerHTML = `<span class="report-status-dot status-${escapeHtml(status.code || "neutral")}" aria-hidden="true"></span><span><strong>${escapeHtml(status.label || "Status unavailable")}</strong><small>${escapeHtml(status.detail || "Refresh details unavailable")}</small></span>`;
    }

    async function loadRefreshStatus() {
        try {
            const payload = await request(root.dataset.refreshUrl);
            const normalized = String(payload.status || "").toLowerCase();
            state.config.refresh_status = {
                code: payload.is_refreshing
                    ? "refreshing"
                    : normalized === "completed"
                        ? "healthy"
                        : normalized === "failed"
                            ? "failed"
                            : "no_refresh",
                label: payload.is_refreshing ? "Refreshing" : (payload.status || "No Refresh"),
                detail: payload.last_refresh
                    ? `Refreshed ${payload.last_refresh}`
                    : "Refresh details unavailable",
            };
        } catch (error) {
            state.config.refresh_status = {
                code: "neutral",
                label: "Status unavailable",
                detail: "The report can still be opened",
            };
        }
        renderStatus();
    }

    function renderPeriods() {
        $("[data-period-selector]").innerHTML = state.config.viewer.available_periods.map((item) => `<button type="button" data-period="${escapeHtml(item.code)}" aria-pressed="${item.code === state.period}">${escapeHtml(item.label)}</button>`).join("");
        const showFilterBar = Boolean(state.config.viewer.show_filter_bar);
        $("[data-command-bar]").hidden = !showFilterBar;
        $("[data-command-divider]").hidden = !showFilterBar;
    }

    function renderPages(actualPages) {
        if (!state.config.viewer.show_page_navigation || actualPages.length <= 1) return;
        const nav = $("[data-page-navigation]"); nav.hidden = false;
        $("[data-page-tabs]").innerHTML = actualPages.map((page) => `<button type="button" data-page-name="${escapeHtml(page.name)}" aria-current="${page.isActive ? "page" : "false"}">${escapeHtml(page.displayName)}</button>`).join("");
        $("[data-page-select]").innerHTML = actualPages.map((page) => `<option value="${escapeHtml(page.name)}"${page.isActive ? " selected" : ""}>${escapeHtml(page.displayName)}</option>`).join("");
    }

    async function changePage(name) {
        try {
            setCanvasState("Opening report page...");
            const page = await state.embed.setActivePage(name, "");
            $$('[data-page-name]').forEach((button) => button.setAttribute("aria-current", button.dataset.pageName === page.name ? "page" : "false"));
            $("[data-page-select]").value = page.name;
            const url = new URL(window.location.href); url.searchParams.set("page", page.name); history.replaceState({ reportViewer: true }, "", url);
            setCanvasState("Ready");
        } catch (error) { setCanvasState(error.message, true); }
    }

    async function setFitMode(mode) {
        try {
            await state.embed.setFitMode(mode); state.fitMode = mode;
            $$('[data-fit-mode]').forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.fitMode === mode)));
            localStorage.setItem(`mining360.viewer.fit.${reportId}`, mode); setCanvasState("Ready");
        } catch (error) { setCanvasState(error.message, true); }
    }

    function renderSwitcher() {
        const query = state.switcherQuery.toLowerCase();
        const items = state.switcher.filter((item) => {
            if (state.switcherFilter === "favorites" && !item.favorite) return false;
            if (state.switcherFilter === "recent" && !item.recent) return false;
            return !query || `${item.display_name} ${item.category_label}`.toLowerCase().includes(query);
        });
        $("[data-switcher-results]").innerHTML = items.map((item) => `<button type="button" class="switcher-report" data-switch-report="${escapeHtml(item.url)}"><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.category_label)} · ${escapeHtml(item.status.label)}</small>${item.favorite ? "<em aria-label=\"Favorite\">★</em>" : ""}</button>`).join("") || "<p>No report matches this view.</p>";
    }

    async function loadSwitcher() {
        if (state.switcherLoaded) return;
        if (state.switcherLoading) return state.switcherLoading;
        const results = $("[data-switcher-results]");
        if (results) results.innerHTML = "<p>Loading reports...</p>";
        state.switcherLoading = request(root.dataset.viewerSwitcherUrl)
            .then((payload) => {
                state.switcher = payload.switcher || [];
                state.switcherLoaded = true;
                renderSwitcher();
            })
            .catch((error) => {
                if (results) results.innerHTML = `<p>${escapeHtml(error.message || "Reports could not be loaded.")}</p>`;
            })
            .finally(() => { state.switcherLoading = null; });
        return state.switcherLoading;
    }

    function openDrawer(drawer) {
        closeDrawers(); state.activeDrawer = drawer; state.previousFocus = document.activeElement;
        drawer.setAttribute("aria-hidden", "false"); $("[data-drawer-backdrop]").hidden = false;
        document.body.classList.add("viewer-drawer-open"); drawer.querySelector("input,button")?.focus();
    }

    function closeDrawers() {
        $$(".viewer-drawer").forEach((drawer) => drawer.setAttribute("aria-hidden", "true"));
        $("[data-drawer-backdrop]").hidden = true; document.body.classList.remove("viewer-drawer-open");
        state.activeDrawer = null; state.previousFocus?.focus?.();
    }

    function showInfo(title, html) {
        $("[data-info-title]").textContent = title; $("[data-info-content]").innerHTML = html; openDrawer($("[data-info-drawer]"));
    }

    async function refreshReport() {
        try {
            setCanvasState("Starting refresh...");
            const payload = await request(root.dataset.refreshUrl, { method: "POST", headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/json" }, body: "{}" });
            setCanvasState(payload.message || "Refresh started.");
        } catch (error) { setCanvasState(error.message, true); }
    }

    async function troubleshoot() {
        try {
            const payload = await request(root.dataset.troubleshootUrl, { method: "POST", headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/json" }, body: "{}" });
            const result = payload.result || {};
            showInfo("Troubleshooting", `<p>${escapeHtml(result.message || payload.message || "Troubleshooting completed.")}</p><dl><div><dt>Status</dt><dd>${escapeHtml(result.status || "Completed")}</dd></div></dl>`);
        } catch (error) { showInfo("Troubleshooting", `<p>${escapeHtml(error.message)}</p>`); }
    }

    function bindEvents() {
        root.addEventListener("click", async (event) => {
            const period = event.target.closest("[data-period]");
            if (period) {
                state.period = period.dataset.period;
                const range = periodRange(state.period); state.startDate = range.start; state.endDate = range.end;
                $("[data-start-date]").value = state.startDate; $("[data-end-date]").value = state.endDate;
                updateApplyState();
                if (state.config.viewer.auto_apply_presets && state.period !== "custom") await applyFilters();
                return;
            }
            const fit = event.target.closest("[data-fit-mode]"); if (fit) return setFitMode(fit.dataset.fitMode);
            const page = event.target.closest("[data-page-name]"); if (page) return changePage(page.dataset.pageName);
            if (event.target.closest("[data-apply-filters]")) return applyFilters();
            if (event.target.closest("[data-reset-filters], [data-clear-all]")) return resetFilters();
            if (event.target.closest("[data-switcher-open]")) {
                openDrawer($("[data-switcher-drawer]"));
                loadSwitcher();
                return;
            }
            const report = event.target.closest("[data-switch-report]");
            if (report) { state.embed.reset(); window.location.assign(report.dataset.switchReport); return; }
            if (event.target.closest("[data-drawer-close], [data-drawer-backdrop]")) return closeDrawers();
            if (event.target.closest("[data-more-toggle]")) { const menu = $("[data-more-menu]"); menu.hidden = !menu.hidden; $("[data-more-toggle]").setAttribute("aria-expanded", String(!menu.hidden)); return; }
            if (event.target.closest("[data-focus-toggle]")) {
                const active = document.body.classList.toggle("viewer-focus");
                event.target.closest("button").setAttribute("aria-label", active ? "Exit Focus Mode" : "Enter Focus Mode");
                localStorage.setItem("mining360.viewer.focus", active ? "1" : "0"); return;
            }
            if (event.target.closest("[data-fullscreen-toggle]")) {
                try { if (document.fullscreenElement) await document.exitFullscreen(); else await $("[data-canvas-workspace]").requestFullscreen(); } catch (error) { setCanvasState("Fullscreen is unavailable.", true); } return;
            }
            if (event.target.closest("[data-refresh-report], [data-canvas-refresh]")) return refreshReport();
            if (event.target.closest("[data-troubleshoot]")) return troubleshoot();
            if (event.target.closest("[data-refresh-details]")) {
                const status = state.config.refresh_status;
                return showInfo("Refresh Details", `<dl><div><dt>Status</dt><dd>${escapeHtml(status.label)}</dd></div><div><dt>Details</dt><dd>${escapeHtml(status.detail)}</dd></div></dl>`);
            }
            if (event.target.closest("[data-report-help]")) return showInfo("Report Help", `<p>${escapeHtml(state.config.viewer.help_text || "Use the Mining 360 controls to change period, report page and display fit without reloading the report.")}</p>`);
            if (event.target.closest("[data-technical-details]")) return showInfo("Technical Details", `<dl><div><dt>Report ID</dt><dd>${escapeHtml(state.config.report.id)}</dd></div><div><dt>Launch Mode</dt><dd>${escapeHtml(state.config.report.launch_mode)}</dd></div><div><dt>Category</dt><dd>${escapeHtml(state.config.report.category_label)}</dd></div></dl>`);
            if (event.target.closest("[data-copy-link]")) { await navigator.clipboard.writeText(window.location.href); setCanvasState("Report link copied."); return; }
            if (event.target.closest("[data-filter-drawer-open]")) { $("[data-command-bar]").classList.toggle("is-mobile-open"); return; }
        });
        $("[data-start-date]").addEventListener("input", (event) => { state.startDate = event.target.value; updateApplyState(); });
        $("[data-end-date]").addEventListener("input", (event) => { state.endDate = event.target.value; updateApplyState(); });
        $("[data-page-select]").addEventListener("change", (event) => changePage(event.target.value));
        $("[data-switcher-search]").addEventListener("input", (event) => { state.switcherQuery = event.target.value.trim(); renderSwitcher(); });
        $$("[data-switcher-filter]").forEach((button) => button.addEventListener("click", () => {
            state.switcherFilter = button.dataset.switcherFilter;
            $$("[data-switcher-filter]").forEach((item) => item.setAttribute("aria-pressed", String(item === button))); renderSwitcher();
        }));
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && state.activeDrawer) closeDrawers();
            if (event.key === "Tab" && state.activeDrawer) {
                const focusable = $$("button,a,input,select", state.activeDrawer).filter((node) => !node.disabled && !node.hidden);
                if (!focusable.length) return;
                const first = focusable[0], last = focusable[focusable.length - 1];
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        });
        document.addEventListener("fullscreenchange", () => {
            const active = Boolean(document.fullscreenElement);
            $$('[data-fullscreen-toggle]').forEach((button) => {
                button.setAttribute("aria-label", active ? "Exit fullscreen" : "Open report in fullscreen");
                button.title = active ? "Exit fullscreen" : "Fullscreen";
            });
            setCanvasState(active ? "Fullscreen" : "Ready");
        });
        window.addEventListener("beforeunload", () => state.embed?.reset());
        document.querySelector(".js-toggle-nav")?.addEventListener("click", () => {
            if (window.matchMedia("(max-width: 760px)").matches) {
                document.body.classList.toggle("viewer-mobile-nav-open");
            } else {
                window.setTimeout(() => localStorage.setItem(
                    "mining360.viewer.navMode",
                    document.body.classList.contains("nav-collapsed") ? "compact" : "expanded",
                ));
            }
        });
        $("[data-return-hub]").addEventListener("click", (event) => {
            const stored = sessionStorage.getItem("mining360.reportingHub.returnUrl");
            if (stored) { event.preventDefault(); window.location.assign(stored); }
        });
    }

    async function initialize() {
        const navMode = localStorage.getItem("mining360.viewer.navMode") || "compact";
        document.body.classList.toggle("nav-collapsed", navMode !== "expanded");
        if (!state.eventsBound) { bindEvents(); state.eventsBound = true; }
        setLoading("Preparing report...");
        state.embed = new window.Mining360PowerBIEmbed(container, {
            embedConfigUrl: root.dataset.embedConfigTemplate,
            currentReportId: reportId,
            rlsRole: root.dataset.rlsRole,
            onEvent(event) {
                if (event.type === "rendered") { $("[data-loading-state]").hidden = true; setCanvasState("Ready"); }
                if (event.type === "token_refresh_failed") setCanvasState("Your report session could not be renewed.", true);
            },
        });
        state.embed.bootstrap(reportId, root.dataset.embedUrl);
        try {
            const configUrl = new URL(root.dataset.viewerConfigUrl, window.location.origin);
            new URL(window.location.href).searchParams.forEach((value, key) => configUrl.searchParams.append(key, value));
            let embedError = null;
            const embedPromise = (async () => {
                setLoading("Connecting to Power BI...");
                try {
                    await state.embed.embed(reportId);
                    state.timings.powerBILoaded = performance.now();
                } catch (error) { embedError = error; }
            })();
            const payload = await request(configUrl);
            state.timings.viewerConfigReady = performance.now();
            state.config = payload;
            state.contextFilters = [...(payload.initial_context.filters || [])];
            state.contextChips = [...(payload.initial_context.chips || [])];
            $("[data-report-name]").textContent = payload.report.display_name;
            $("[data-report-breadcrumb-name]").textContent = payload.report.display_name;
            renderStatus();
            loadRefreshStatus();
            state.period = payload.initial_context.period;
            state.startDate = payload.initial_context.start_date;
            state.endDate = payload.initial_context.end_date;
            if (state.period !== "custom") { const range = periodRange(state.period); state.startDate = range.start; state.endDate = range.end; }
            $("[data-start-date]").value = state.startDate; $("[data-end-date]").value = state.endDate;
            renderPeriods(); renderChips();
            const openPowerBI = $("[data-open-powerbi]");
            if (payload.permissions.allow_open_powerbi && payload.permissions.open_powerbi_url) { openPowerBI.hidden = false; openPowerBI.href = payload.permissions.open_powerbi_url; }
            $("[data-focus-toggle]").hidden = !payload.permissions.allow_focus;
            $$('[data-fullscreen-toggle]').forEach((button) => { button.hidden = !payload.permissions.allow_fullscreen; });
            if (payload.permissions.allow_focus && localStorage.getItem("mining360.viewer.focus") === "1") {
                document.body.classList.add("viewer-focus");
                $("[data-focus-toggle]").setAttribute("aria-label", "Exit Focus Mode");
            }
            await embedPromise;
            if (embedError) throw embedError;
            const needsPages = payload.viewer.show_page_navigation || payload.initial_context.page || payload.viewer.default_page;
            const actualPages = needsPages ? await state.embed.getPages() : [];
            if (actualPages.length) renderPages(actualPages);
            const requestedPage = payload.initial_context.page || payload.viewer.default_page;
            if (requestedPage) await changePage(requestedPage);
            const configuredFitMode = payload.viewer.default_fit_mode;
            state.fitMode = localStorage.getItem(`mining360.viewer.fit.${reportId}`) || configuredFitMode;
            if (state.fitMode !== configuredFitMode) await setFitMode(state.fitMode);
            else $$('[data-fit-mode]').forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.fitMode === state.fitMode)));
            state.applied = null; updateApplyState();
            if (payload.viewer.show_filter_bar && (payload.viewer.auto_apply_presets || payload.initial_context.filters.length)) await applyFilters({ announce: false });
            else { state.applied = draft(); updateApplyState(); }
            $("[data-loading-state]").hidden = true; setCanvasState("Ready");
            state.timings.ready = performance.now();
            window.dispatchEvent(new CustomEvent("mining360:report-ready", { detail: {
                viewerConfigMs: Math.round(state.timings.viewerConfigReady - state.timings.navigationStart),
                powerBILoadedMs: Math.round(state.timings.powerBILoaded - state.timings.navigationStart),
                readyMs: Math.round(state.timings.ready - state.timings.navigationStart),
            } }));
        } catch (error) { showError(error); }
    }

    $("[data-retry-embed]")?.addEventListener("click", () => { $("[data-runtime-error]").hidden = true; state.embed.reset(); initialize(); });
    initialize();
}());
