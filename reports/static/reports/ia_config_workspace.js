(function () {
    const root = document.querySelector("[data-ai-workspace]");
    const controller = window.Mining360AIConfig;
    if (!root || !controller) return;

    const areaResources = {
        "language-training": ["question-examples", "synonyms", "business-vocabulary", "few-shot-examples"],
        "semantic-model": ["metrics", "filters", "visual-mapping", "semantic-tables", "semantic-columns", "semantic-measures", "semantic-relationships", "powerbi-pages"],
        "query-response": ["dax-templates", "response-templates", "intent-template-mappings", "prompt-templates"],
        "business-governance": ["business-rules", "kpi-targets", "recommended-actions"],
        "test-diagnostics": ["debug-runs"],
    };
    const labels = {
        "language-training": "Language & Training",
        "semantic-model": "Semantic Model",
        "query-response": "Query & Response",
        "business-governance": "Business Governance",
        "test-diagnostics": "Test & Diagnostics",
    };
    let sections = [];
    let activeArea = "language-training";
    let lastFocus = null;

    function byResource(resource) { return document.querySelector(`.ia-tab[data-resource-type="${resource}"]`); }
    function areaForResource(resource) {
        return Object.keys(areaResources).find((area) => areaResources[area].includes(resource)) || "language-training";
    }
    function urlState(replace) {
        const url = new URL(window.location.href);
        url.searchParams.set("section", controller.state.sectionCode);
        url.searchParams.set("area", activeArea);
        url.searchParams.set("entity", controller.state.resourceType);
        window.history[replace ? "replaceState" : "pushState"]({}, "", url);
    }
    function setArea(area, preferredResource, push) {
        activeArea = areaResources[area] ? area : "language-training";
        document.querySelectorAll("[data-ai-area]").forEach((button) => {
            const active = button.dataset.aiArea === activeArea;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", String(active));
        });
        document.querySelectorAll("[data-entity-group]").forEach((group) => {
            group.hidden = group.dataset.entityGroup !== activeArea;
        });
        document.querySelector("[data-area-label]").textContent = labels[activeArea];
        document.querySelectorAll("[data-ai-import-open]").forEach((button) => {
            button.hidden = activeArea !== "semantic-model";
        });
        const target = preferredResource && areaResources[activeArea].includes(preferredResource)
            ? preferredResource : areaResources[activeArea][0];
        const tab = byResource(target);
        if (tab && target !== controller.state.resourceType) tab.click();
        if (push !== false) urlState(false);
    }
    function openDrawer(selector, trigger) {
        const drawer = document.querySelector(selector);
        if (!drawer) return;
        lastFocus = trigger || document.activeElement;
        drawer.hidden = false;
        drawer.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        drawer.querySelector("button, input, select, textarea")?.focus();
    }
    function closeDrawer(drawer) {
        drawer.hidden = true;
        drawer.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
        lastFocus?.focus?.();
    }
    function escape(value) {
        const div = document.createElement("div"); div.textContent = value == null ? "" : String(value); return div.innerHTML;
    }
    function renderResolution(payload) {
        const intent = payload.intent || {};
        const validation = payload.validation || {};
        const filters = intent.filters || intent.filter_values || {};
        const values = [
            ["Resolved Section", intent.section || intent.section_code || controller.state.sectionCode],
            ["Intent", intent.intent || intent.intent_type || intent.type || "Not resolved"],
            ["KPI", intent.kpi || intent.metric || intent.metric_code || "Not resolved"],
            ["Filters", Object.keys(filters).length ? JSON.stringify(filters) : "None"],
            ["Status", validation.valid ? "Valid" : "Review required"],
        ];
        document.querySelector("[data-resolution-summary]").innerHTML = `<div class="aiw-resolution-grid">${values.map(([key, value]) => `<div><small>${escape(key)}</small><strong>${escape(value)}</strong></div>`).join("")}</div>`;
    }
    function renderSections(payload) {
        sections = payload.sections || [];
        const summary = payload.summary || {};
        document.querySelector("[data-health-total]").textContent = summary.total ?? sections.length;
        document.querySelector("[data-health-ready]").textContent = summary.ready ?? 0;
        document.querySelector("[data-health-review]").textContent = summary.needs_review ?? 0;
        document.querySelector("[data-health-critical]").textContent = summary.critical ?? 0;
        sections.forEach((section) => {
            const item = document.querySelector(`[data-section-code="${section.code}"]`);
            if (!item) return;
            item.querySelector("[data-section-score]").textContent = section.status === "external_workspace" ? "Open" : `${section.readiness_score}%`;
            item.querySelector("[data-section-status]").textContent = section.status === "external_workspace" ? "External workspace" : `${section.issue_count} items to review`;
        });
        updateSelectedSection();
    }
    function updateSelectedSection() {
        const section = sections.find((item) => item.code === controller.state.sectionCode);
        if (!section) return;
        const score = `${section.readiness_score ?? 0}%`;
        document.querySelector("[data-selected-readiness]").textContent = score;
        document.querySelector("[data-selected-section-meta]").textContent = `${score} ready · ${section.issue_count || 0} items need review`;
        const entries = Object.entries(section.entity_counts || {});
        document.querySelector("[data-readiness-content]").innerHTML = `<h3>${escape(section.name)} — ${escape(score)} Ready</h3>${entries.map(([key, count]) => `<p><strong>${count ? "✓" : "!"} ${escape(controller.resourceConfig[key]?.title || key)}</strong> <span>${count} records</span></p>`).join("")}`;
    }
    async function fetchSections() {
        try {
            const response = await fetch(root.dataset.sectionsApi, {headers: {Accept: "application/json"}});
            const payload = await response.json();
            if (response.ok && payload.ok) renderSections(payload);
        } catch (error) { document.querySelector("[data-selected-section-meta]").textContent = "Readiness temporarily unavailable"; }
    }

    document.querySelectorAll("[data-ai-area]").forEach((button) => button.addEventListener("click", () => setArea(button.dataset.aiArea)));
    document.querySelectorAll(".ia-tab[data-resource-type]").forEach((tab) => tab.addEventListener("click", () => {
        activeArea = areaForResource(tab.dataset.resourceType);
        document.querySelector("[data-entity-title]").textContent = controller.resourceConfig[tab.dataset.resourceType]?.title || tab.textContent.trim();
        urlState(false);
    }));
    document.querySelectorAll(".js-ia-section-card").forEach((button) => button.addEventListener("click", () => { updateSelectedSection(); urlState(false); }));
    document.querySelectorAll("[data-entity-add]").forEach((button) => button.addEventListener("click", () => document.getElementById("ia-add-item")?.click()));

    const drawerBindings = [
        ["[data-ai-test-open]", "[data-ai-test-drawer]", "[data-ai-drawer-close]"],
        ["[data-ai-import-open]", "[data-ai-import-drawer]", "[data-import-close]"],
        ["[data-readiness-open]", "[data-ai-readiness-drawer]", "[data-readiness-close]"],
        ["[data-ai-help-open]", "[data-ai-help-drawer]", "[data-help-close]"],
    ];
    drawerBindings.forEach(([openSelector, drawerSelector, closeSelector]) => {
        document.querySelectorAll(openSelector).forEach((trigger) => trigger.addEventListener("click", () => openDrawer(drawerSelector, trigger)));
        document.querySelectorAll(`${drawerSelector} ${closeSelector}`).forEach((trigger) => trigger.addEventListener("click", () => closeDrawer(trigger.closest(".aiw-drawer"))));
    });
    document.querySelectorAll("[data-result-tab]").forEach((button) => button.addEventListener("click", () => {
        document.querySelectorAll("[data-result-tab]").forEach((item) => item.classList.toggle("active", item === button));
        document.querySelectorAll("[data-result-panel]").forEach((panel) => { panel.hidden = panel.dataset.resultPanel !== button.dataset.resultTab; });
    }));
    document.addEventListener("ai-config:test-completed", (event) => {
        renderResolution(event.detail);
        const output = event.detail.powerbi_result || event.detail.powerbi_response;
        document.querySelector("[data-powerbi-result]").textContent = output
            ? JSON.stringify(output, null, 2)
            : "No Power BI execution result returned by this test.";
    });
    document.addEventListener("ai-config:import-completed", (event) => {
        const imported = event.detail.imported || {};
        document.querySelector("[data-import-summary]").textContent = `Import complete: ${imported.tables || 0} tables, ${imported.columns || 0} columns, ${imported.measures || 0} measures and ${imported.relationships || 0} relationships.`;
    });
    document.addEventListener("ai-config:items-rendered", (event) => {
        const readonly = Boolean(controller.resourceConfig[event.detail.resourceType]?.readonly);
        document.querySelectorAll("[data-entity-add]").forEach((button) => {
            button.hidden = readonly;
        });
        const pagination = event.detail.pagination;
        document.querySelector("[data-entity-count]").textContent = `${pagination?.count ?? event.detail.items.length} records`;
        const footer = document.querySelector("[data-pagination]");
        footer.hidden = !pagination || pagination.pages <= 1;
        if (pagination) {
            footer.querySelector("[data-page-summary]").textContent = `Page ${pagination.page} of ${pagination.pages} · ${pagination.count} records`;
            footer.querySelector("[data-page-previous]").disabled = !pagination.has_previous;
            footer.querySelector("[data-page-next]").disabled = !pagination.has_next;
        }
    });
    document.querySelector("[data-page-previous]")?.addEventListener("click", () => { controller.state.page -= 1; controller.loadItems(); });
    document.querySelector("[data-page-next]")?.addEventListener("click", () => { controller.state.page += 1; controller.loadItems(); });

    const shell = document.querySelector(".aiw-shell");
    const navigator = document.querySelector("[data-section-navigator]");
    const appNavPreference = "mining360.aiConfig.appNavMode";
    const appNavMode = localStorage.getItem(appNavPreference) || "compact";
    const applyWorkspaceNavMode = () => document.body.classList.toggle(
        "nav-collapsed", appNavMode !== "expanded"
    );
    applyWorkspaceNavMode();
    window.addEventListener("DOMContentLoaded", applyWorkspaceNavMode, {once: true});
    document.querySelector(".js-toggle-nav")?.addEventListener("click", () => window.setTimeout(() => {
        localStorage.setItem(
            appNavPreference,
            document.body.classList.contains("nav-collapsed") ? "compact" : "expanded"
        );
    }));
    const stored = localStorage.getItem("mining360.aiConfig.navigatorCollapsed");
    if (stored === "1") shell.classList.add("navigator-collapsed");
    document.querySelector("[data-section-navigator-toggle]")?.addEventListener("click", () => {
        shell.classList.toggle("navigator-collapsed");
        localStorage.setItem("mining360.aiConfig.navigatorCollapsed", shell.classList.contains("navigator-collapsed") ? "1" : "0");
    });
    document.querySelector("[data-section-navigator-open]")?.addEventListener("click", () => navigator.classList.add("open"));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") document.querySelectorAll(".aiw-drawer:not([hidden])").forEach(closeDrawer);
    });

    const params = new URLSearchParams(window.location.search);
    const section = params.get("section");
    const entity = params.get("entity");
    const area = params.get("area") || areaForResource(entity);
    if (section) document.querySelector(`[data-section-code="${section}"]`)?.click();
    setArea(area, entity, false);
    urlState(true);
    fetchSections();
}());
