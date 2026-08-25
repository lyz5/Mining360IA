(() => {
    "use strict";
    const root = document.querySelector("[data-report-config-workspace]");
    if (!root) return;

    const $ = (selector, scope = root) => scope.querySelector(selector);
    const $$ = (selector, scope = root) => [...scope.querySelectorAll(selector)];
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const esc = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
    const api = (template, id) => template.replace("__REPORT_ID__", encodeURIComponent(id));
    const AREA_SECTIONS = {
        essentials: [["general", "General"]],
        appearance: [["visual", "Card Identity"], ["catalog", "Reporting Hub Display"]],
        open_navigate: [["launch", "Launch"], ["viewer", "Viewer"], ["navigation", "Power BI Pages"], ["parameters", "Context Parameters"]],
        help_ai: [["troubleshooting", "Troubleshooting"]],
        test_history: [["tests", "Tests"], ["audit", "History"]],
    };
    const SECTION_AREA = Object.fromEntries(Object.entries(AREA_SECTIONS).flatMap(([area, sections]) => sections.map(([section]) => [section, area])));
    const initialParams = new URLSearchParams(location.search);
    const initialSection = initialParams.get("section") || initialParams.get("tab") || "general";
    const normalizedSection = SECTION_AREA[initialSection] ? initialSection : "general";
    const state = {
        reports: [], selectedId: "", config: null, options: {}, baseline: "", dirty: false,
        tags: [], parameters: [], activeTab: normalizedSection, activeArea: SECTION_AREA[normalizedSection],
        filters: { q: "", visibility: "all", status: "all", category: "all", launch_mode: "all", authentication_mode: "all", special_integration: "all", visual_status: "all" },
        listController: null, listTimer: null, detailController: null, pendingSelection: "", toastTimer: null,
        uploadedThumbnailUrl: "", previewMode: "desktop",
        navigatorCollapsed: localStorage.getItem("mining360.reportingConfig.navigatorCollapsed") === "1",
    };
    if (AREA_SECTIONS[initialParams.get("area")] && !initialParams.get("section") && !initialParams.get("tab")) {
        state.activeArea = initialParams.get("area");
        state.activeTab = AREA_SECTIONS[state.activeArea][0][0];
    }

    function toast(message, error = false) {
        const node = $("[data-toast]");
        clearTimeout(state.toastTimer);
        node.textContent = message;
        node.classList.toggle("is-error", error);
        node.classList.add("is-visible");
        state.toastTimer = setTimeout(() => node.classList.remove("is-visible"), 3500);
    }

    async function request(url, options = {}) {
        const isFormData = options.body instanceof FormData;
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: { Accept: "application/json", ...(options.body && !isFormData ? {"Content-Type":"application/json"} : {}), ...(options.method && options.method !== "GET" ? {"X-CSRFToken":csrf} : {}), ...(options.headers || {}) },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) {
            const error = new Error(payload.error || "The request could not be completed.");
            error.code = payload.error_code || "";
            error.fieldErrors = payload.field_errors || {};
            throw error;
        }
        return payload;
    }

    function label(code) { return String(code || "").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase()); }
    function statusLabel(code) { return ({complete:"Complete",needs_review:"Needs Review",incomplete:"Incomplete",invalid:"Invalid"})[code] || label(code); }
    function reportInitials(name) { return String(name || "PBI").split(/\s+/).slice(0, 2).map(x => x[0]).join("").toUpperCase(); }

    function updateUrl() {
        const params = new URLSearchParams();
        if (state.selectedId) params.set("report", state.selectedId);
        if (state.activeArea !== "essentials") params.set("area", state.activeArea);
        if (state.activeTab !== AREA_SECTIONS[state.activeArea][0][0]) params.set("section", state.activeTab);
        if (state.filters.q) params.set("q", state.filters.q);
        Object.entries(state.filters).forEach(([key, value]) => { if (key !== "q" && value !== "all") params.set(key, value); });
        history.replaceState(null, "", `${location.pathname}${params.toString() ? `?${params}` : ""}`);
    }

    function updateSummary(summary) {
        $("[data-summary-total]").textContent = summary.total;
        $("[data-summary-visible]").textContent = summary.visible;
        $("[data-summary-hidden]").textContent = summary.hidden;
        $("[data-summary-review]").textContent = summary.needs_review;
        $("[data-summary-errors]").textContent = summary.errors;
        $("[data-summary-visual-complete]").textContent = summary.visual_complete;
        $("[data-summary-visual-review]").textContent = summary.visual_review;
        $("[data-summary-broken-assets]").textContent = summary.broken_assets;
        $("[data-summary-issues]").textContent = Number(summary.errors || 0) + Number(summary.broken_assets || 0);
    }

    function renderFilterChips() {
        const host = $("[data-filter-chips]");
        const active = Object.entries(state.filters).filter(([key, value]) => key !== "q" && value !== "all");
        host.hidden = !active.length;
        host.innerHTML = active.map(([key, value]) => {
            const select = $(`[data-filter="${key}"]`);
            const text = select?.selectedOptions[0]?.textContent || label(value);
            return `<button type="button" data-filter-remove="${esc(key)}">${esc(text)} <span aria-hidden="true">×</span></button>`;
        }).join("") + (active.length > 1 ? '<button type="button" class="clear-all" data-clear-list-filters>Clear all</button>' : "");
        $("[data-filter-count]").textContent = active.length ? `${active.length} active` : "";
    }

    function renderReportList() {
        const list = $("[data-report-list]");
        if (!state.reports.length) {
            list.innerHTML = '<div class="report-config-list-empty"><strong>No reports found</strong><span>No report matches the current filters.</span></div>';
            return;
        }
        list.innerHTML = state.reports.map(report => `
            <button type="button" class="report-config-list-item ${report.id === state.selectedId ? "is-selected" : ""}" data-report-id="${esc(report.id)}" aria-selected="${report.id === state.selectedId}">
                <span class="report-config-list-item__icon">${esc(reportInitials(report.display_name))}</span>
                <span class="report-config-list-item__body"><strong title="${esc(report.display_name)}">${esc(report.display_name)}</strong><small title="${esc(report.report_name)}">Power BI: ${esc(report.report_name)}</small><span><em>${esc(report.category_label)}</em><b>${report.visible ? "Visible" : "Hidden"}</b></span><span><small>${report.completeness_score}% configured</small><i class="status-${esc(report.configuration_status)}">${esc(statusLabel(report.configuration_status))}</i></span></span>
            </button>`).join("");
    }

    async function loadList({ keepSelection = true } = {}) {
        state.listController?.abort();
        state.listController = new AbortController();
        const params = new URLSearchParams({ ...state.filters, page_size: "50" });
        const list = $("[data-report-list]");
        const previousScroll = list.scrollTop;
        $("[data-list-count]").textContent = "Loading...";
        try {
            const payload = await request(`${root.dataset.listApi}?${params}`, { signal: state.listController.signal });
            state.reports = payload.results || [];
            updateSummary(payload.summary || {});
            $("[data-list-count]").textContent = `${payload.count} report${payload.count === 1 ? "" : "s"}`;
            renderReportList();
            list.scrollTop = previousScroll;
            renderFilterChips();
            if (!keepSelection && state.reports[0]) await selectReport(state.reports[0].id, true);
        } catch (error) {
            if (error.name === "AbortError") return;
            $("[data-list-count]").textContent = "Unavailable";
            $("[data-report-list]").innerHTML = `<div class="report-config-list-empty"><strong>Reports could not be loaded</strong><button type="button" data-list-retry>Retry</button></div>`;
        }
    }

    function scheduleList() {
        clearTimeout(state.listTimer);
        updateUrl();
        state.listTimer = setTimeout(() => loadList(), 300);
    }

    function setOptions(select, options, selected = "", blank = null) {
        select.innerHTML = `${blank !== null ? `<option value="">${esc(blank)}</option>` : ""}${(options || []).map(item => `<option value="${esc(item.value)}" ${String(item.value) === String(selected) ? "selected" : ""}>${esc(item.label)}</option>`).join("")}`;
    }

    function formField(name) { return $(`[name="${name}"]`, $("[data-config-form]")); }
    function setField(name, value) {
        const field = formField(name); if (!field) return;
        if (field.type === "checkbox") field.checked = Boolean(value); else field.value = value ?? "";
    }
    function fieldValue(name) { const field = formField(name); return field?.type === "checkbox" ? field.checked : field?.value ?? ""; }

    function installContextualHelp() {
        $$(".report-config-form-grid > label").forEach(field => {
            const labelNode = field.querySelector(":scope > span");
            const help = field.querySelector(":scope > small");
            if (!labelNode || !help) return;
            const existing = labelNode.querySelector(".contextual-help-icon");
            if (existing) {
                existing.title = help.textContent.trim();
                existing.setAttribute("aria-label", help.textContent.trim());
                return;
            }
            const icon = document.createElement("abbr");
            icon.className = "contextual-help-icon";
            icon.textContent = "i";
            icon.title = help.textContent.trim();
            icon.setAttribute("aria-label", help.textContent.trim());
            icon.tabIndex = 0;
            labelNode.append(" ", icon);
        });
    }

    function renderTags() {
        $("[data-tag-list]").innerHTML = state.tags.map((tag, index) => `<button type="button" data-tag-remove="${index}" title="Remove ${esc(tag)}">${esc(tag)} <span>×</span></button>`).join("") || "<small>No tags</small>";
        updatePreview(); markDirty();
    }

    function renderParameters() {
        const rows = $("[data-parameter-rows]");
        rows.innerHTML = state.parameters.map((item, index) => `<tr>
            <td><strong>${esc(item.display_name)}</strong><small>${esc(item.code)}</small></td><td>${esc(label(item.source))}</td><td>${esc(label(item.data_type))}</td><td>${item.required ? "Yes" : "No"}</td><td>${item.powerbi_table && item.powerbi_column ? `${esc(item.powerbi_table)}[${esc(item.powerbi_column)}]` : "Not mapped"}</td><td><button type="button" data-parameter-edit="${index}" aria-label="Edit ${esc(item.display_name)}">Edit</button><button type="button" data-parameter-remove="${index}" aria-label="Remove ${esc(item.display_name)}">Remove</button></td>
        </tr>`).join("");
        $("[data-parameter-empty]").hidden = state.parameters.length > 0;
    }

    function renderTests() {
        const validation = state.config.status || {};
        $("[data-readiness-score]").textContent = `${validation.completeness_score || 0}%`;
        $("[data-readiness-bar]").style.width = `${validation.completeness_score || 0}%`;
        const latest = new Map((state.config.tests || []).map(item => [item.test_code, item]));
        const tests = [
            ["configuration_validation", "Configuration Validation", true], ["card_preview", "Reporting Hub Card Preview", true],
            ["powerbi_metadata", "Power BI Metadata", true], ["powerbi_authentication", "Power BI Authentication", true],
            ["powerbi_embed", "Power BI Embed", true], ["default_page", "Default Page", true],
            ["troubleshooting_prompt", "Troubleshooting Prompt", state.config.troubleshooting?.enabled],
            ["chatbot_navigation", "Chatbot Navigation", state.config.launch?.supports_chatbot_navigation],
        ];
        const html = tests.filter(item => item[2]).map(([code, name]) => {
            const item = latest.get(code); const status = item?.status || "pending";
            return `<article><span class="test-status test-status--${esc(status)}">${esc(label(status))}</span><div><strong>${esc(name)}</strong><small>${item ? `Last run ${esc(item.created_at)}` : "Not run yet"}</small></div><button type="button" data-single-test="${esc(code)}">Run</button></article>`;
        }).join("");
        $("[data-test-center]").innerHTML = html;
        $("[data-test-drawer-list]").innerHTML = html;
    }

    function renderChecklist() {
        const c = state.config;
        const identity = c.visual_identity || {};
        const required = [
            [Boolean(c.general.display_name), "Display name", "general"],
            [Boolean(c.general.category), "Business category", "visual"],
            [Boolean(c.source.report_id), "Power BI report identity", "general"],
            [Boolean(c.launch?.launch_mode), "Launch mode", "launch"],
            [Boolean(c.launch?.authentication_mode), "Authentication", "launch"],
        ];
        const recommended = [
            [!["needs_review", "invalid", "default"].includes(identity.status), "Visual identity approved", "visual"],
            [Boolean(identity.short_description || c.general.description), "Business description", "visual"],
            [!c.troubleshooting?.enabled || Boolean(c.troubleshooting?.prompt), "Troubleshooting prompt", "troubleshooting"],
            [Boolean((c.tests || []).length), "Configuration tests run", "tests"],
        ];
        const group = (title, items) => `<section><h3>${title}</h3>${items.map(([ok, text, section]) => `<button type="button" data-checklist-section="${section}" class="${ok ? "is-complete" : "needs-action"}"><span>${ok ? "✓" : "!"}</span><strong>${esc(text)}</strong><small>${ok ? "Complete" : "Review"}</small></button>`).join("")}</section>`;
        $("[data-checklist-score]").textContent = `${c.status.completeness_score || 0}%`;
        $("[data-checklist-content]").innerHTML = group("Required", required) + group("Recommended", recommended);
    }

    function renderAudit() {
        $("[data-audit-list]").innerHTML = (state.config.audit || []).map(item => `<li><strong>${esc(label(item.action))}</strong><span>${esc(item.actor)}</span><time>${esc(item.created_at)}</time></li>`).join("") || "<li>No configuration changes recorded.</li>";
        $("[data-version-list]").innerHTML = (state.config.versions || []).map(item => `<li><strong>Version ${item.version}${item.published ? " · Published" : ""}</strong><span>${esc(item.change_summary)}</span><time>${esc(item.created_at)}</time></li>`).join("") || "<li>No saved versions yet.</li>";
    }

    function renderPromptVariables() {
        $("[data-prompt-variables]").innerHTML = (state.options.prompt_variables || []).map(item => `<button type="button" data-prompt-variable="${esc(item)}">{{${esc(item)}}}</button>`).join("");
    }

    function renderEditor() {
        const c = state.config;
        $("[data-selected-name]").textContent = c.general.display_name;
        $("[data-selected-source]").textContent = c.source.report_name;
        $("[data-selected-visibility]").textContent = c.general.visible ? "Visible" : "Hidden";
        $("[data-selected-category]").textContent = label(c.general.category);
        $("[data-selected-launch]").textContent = label(c.launch?.launch_mode || "generic_powerbi");
        $("[data-selected-status]").textContent = statusLabel(c.status.configuration_status);
        $("[data-selected-completeness]").textContent = `${c.status.completeness_score}% configured`;
        $("[data-view-live]").href = `/reports/${encodeURIComponent(c.id)}/`;
        const powerBIServiceLink = $("[data-open-powerbi-service]");
        powerBIServiceLink.hidden = !c.source.web_url;
        if (c.source.web_url) powerBIServiceLink.href = c.source.web_url;
        setField("display_name", c.general.display_name); setField("business_owner", c.general.business_owner);
        setField("visible", c.general.visible); setField("active", c.general.active);
        setOptions(formField("category"), state.options.categories, c.general.category);
        setField("display_order", c.general.display_order); setField("description", c.general.description);
        setField("freshness_threshold_hours", c.general.freshness_threshold_hours);
        const identity = c.visual_identity || {};
        setField("short_description", identity.short_description || c.general.description);
        setField("long_description", identity.long_description); setField("business_purpose", identity.business_purpose);
        setField("technical_owner", identity.technical_owner); setField("featured", identity.featured ?? c.general.featured);
        setOptions(formField("accent_code"), state.options.accents, identity.accent_code || "yellow");
        setOptions(formField("illustration_code"), state.options.illustrations, identity.illustration_code, "Automatic category visual");
        setOptions(formField("icon_code"), state.options.icons, identity.icon_code, "Automatic category icon");
        setOptions(formField("card_style"), state.options.card_styles, identity.card_style || "standard");
        setOptions(formField("thumbnail_source"), state.options.thumbnail_sources, identity.thumbnail_source || "automatic");
        setOptions(formField("selected_visual_asset_id"), state.options.visual_assets, identity.selected_visual_asset_id, "No library asset");
        setField("thumbnail_url", identity.thumbnail_url || c.display?.thumbnail_url); setField("powerbi_screenshot_url", identity.powerbi_screenshot_url);
        setField("thumbnail_status", identity.thumbnail_status || c.display?.thumbnail_status || "fallback");
        setField("thumbnail_focal_x", identity.thumbnail_focal_x ?? 50); setField("thumbnail_focal_y", identity.thumbnail_focal_y ?? 50);
        setField("card_badge", identity.card_badge); state.uploadedThumbnailUrl = identity.effective?.source === "manual_thumbnail" ? identity.effective.thumbnail_url : "";
        $("[data-visual-status]").textContent = statusLabel(identity.status || "default");
        $("[data-visual-status]").className = "visual-identity-status status-" + (identity.status || "default");
        setOptions(formField("launch_mode"), state.options.launch_modes, c.launch?.launch_mode);
        setOptions(formField("authentication_mode"), state.options.authentication_modes, c.launch?.authentication_mode);
        setOptions(formField("open_behavior"), state.options.open_behaviors, c.launch?.open_behavior);
        ["required_entra_tenant_id","contains_powerapps_visual","requires_user_identity","supports_chatbot_navigation","supports_embedded_filtering"].forEach(name => setField(name, c.launch?.[name]));
        setField("opening_profile_name", c.navigation?.opening_profile_name);
        setOptions(formField("default_page_internal_name"), (c.pages || []).map(item => ({value:item.internal_name,label:`${item.display_name} · ${item.internal_name}`})), c.navigation?.default_page_internal_name, "Power BI default");
        setOptions(formField("display_option"), state.options.display_options, c.navigation?.display_option);
        setOptions(formField("background_type"), state.options.background_types, c.navigation?.background_type);
        ["default_rls_role","filter_pane_visible","page_navigation_visible","bookmarks_pane_visible"].forEach(name => setField(name, c.navigation?.[name]));
        const viewer = c.viewer || {};
        setField("viewer_show_filter_bar", viewer.show_filter_bar);
        setField("viewer_auto_apply_presets", viewer.auto_apply_presets);
        setOptions(formField("viewer_default_period"), state.options.viewer_periods || [], viewer.default_period || "ytd");
        setOptions(formField("viewer_reset_behavior"), state.options.viewer_reset_behaviors || [], viewer.reset_behavior || "defaults");
        ["viewer_custom_range_enabled","viewer_external_page_navigation","viewer_focus_mode_enabled","viewer_fullscreen_enabled","viewer_allow_open_powerbi"].forEach(name => setField(name, viewer[name.replace("viewer_", "")]));
        ["viewer_date_table","viewer_date_column","viewer_help_text"].forEach(name => setField(name, viewer[name.replace("viewer_", "")]));
        renderViewerPeriods(viewer.available_periods || []);
        setField("troubleshooting_enabled", c.troubleshooting?.enabled); setField("troubleshooting_prompt", c.troubleshooting?.prompt); setField("troubleshooting_instructions", c.troubleshooting?.instructions);
        $("[data-tech-report-name]").textContent = c.source.report_name; $("[data-tech-report-id]").textContent = c.source.report_id;
        $("[data-tech-workspace]").textContent = c.source.workspace_id; $("[data-tech-dataset]").textContent = c.source.semantic_model_id; $("[data-tech-synced]").textContent = c.source.last_synchronized_at || "Not synchronized";
        state.tags = [...(c.general.tags || [])]; state.parameters = structuredClone(c.parameters || []);
        setOptions($("[data-tag-input]"), (state.options.governed_tags || []).map(item => ({value:item,label:item})), "", "Select a tag");
        renderTags(); renderParameters(); renderTests(); renderChecklist(); renderAudit(); renderPromptVariables(); updatePreview(); updateLaunchHelp(); installContextualHelp(); switchTab(state.activeTab, false);
        state.baseline = JSON.stringify(buildPayload()); setDirty(false);
    }

    function renderViewerPeriods(selected) {
        const host = $("[data-viewer-periods]");
        if (!host) return;
        const values = new Set(selected || []);
        host.innerHTML = (state.options.viewer_periods || []).map(item => `<label><input type="checkbox" value="${esc(item.value)}" ${values.has(item.value) ? "checked" : ""}> <span>${esc(item.label)}</span></label>`).join("");
    }

    function updatePreview() {
        $("[data-preview-name]").textContent = fieldValue("display_name") || "Report name";
        $("[data-preview-description]").textContent = fieldValue("short_description") || fieldValue("description") || "Add a concise business description for this report.";
        const category = formField("category"); $("[data-preview-category]").textContent = category?.selectedOptions[0]?.textContent || "Other";
        $("[data-preview-tags]").innerHTML = state.tags.slice(0, 3).map(item => `<span>${esc(item)}</span>`).join("");
        const source = fieldValue("thumbnail_source");
        const selectedAsset = (state.options.visual_assets || []).find(item => String(item.value) === String(fieldValue("selected_visual_asset_id")));
        let thumbnail = "";
        if (selectedAsset?.thumbnail_url) thumbnail = selectedAsset.thumbnail_url;
        else if (source === "powerbi_screenshot") thumbnail = fieldValue("powerbi_screenshot_url");
        else if (["automatic", "manual_thumbnail"].includes(source)) thumbnail = state.uploadedThumbnailUrl || fieldValue("thumbnail_url");
        const visual = $("[data-preview-thumbnail]");
        visual.style.backgroundImage = thumbnail ? "url(\"" + String(thumbnail).replace(/["\\]/g, "\\$&") + "\")" : "";
        visual.classList.toggle("has-image", Boolean(thumbnail));
        const illustration = fieldValue("illustration_code") || "category";
        $("[data-preview-art]").textContent = illustration.split("_").map(item => item[0]).join("").slice(0, 3).toUpperCase();
        const badge = fieldValue("card_badge"); const badgeNode = $("[data-preview-badge]"); badgeNode.hidden = !badge; badgeNode.textContent = badge;
        const palettes = {yellow:["#fff3c7","#8a6700"],emerald:["#dff2eb","#176b57"],blue:["#dfedf8","#245f91"],purple:["#ece6f5","#66508d"],cyan:["#dff3f5","#25727b"],amber:["#f7edcf","#8a6200"],rose:["#f7e6e9","#954b59"],slate:["#e8edf1","#4c5c6d"]};
        const palette = palettes[fieldValue("accent_code")] || palettes.slate;
        visual.style.setProperty("--preview-soft", palette[0]); visual.style.setProperty("--preview-strong", palette[1]);
        visual.style.backgroundPosition = (fieldValue("thumbnail_focal_x") || 50) + "% " + (fieldValue("thumbnail_focal_y") || 50) + "%";
        $("[data-focal-x]").textContent = (fieldValue("thumbnail_focal_x") || 50) + "%";
        $("[data-focal-y]").textContent = (fieldValue("thumbnail_focal_y") || 50) + "%";
    }

    function updateLaunchHelp() {
        const auth = fieldValue("authentication_mode");
        $("[data-auth-help]").textContent = auth === "user_owns_data" ? "The report uses the connected user's delegated Microsoft Entra identity." : "The report uses the Mining 360 service principal and a Power BI embed token.";
        $("[data-launch-help]").textContent = "The generic viewer is the supported launch mode in this release.";
        const invalid = fieldValue("contains_powerapps_visual") && auth === "app_owns_data";
        const box = $("[data-launch-validation]"); box.hidden = !invalid;
        box.textContent = invalid ? "A Power Apps visual cannot use App Owns Data inside the same embedded report. Use User Owns Data or remove the visual from this embed path." : "";
    }

    function buildPayload() {
        return {
            version: state.config?.version || 0,
            general: {
                display_name: fieldValue("display_name").trim(), business_owner: fieldValue("business_owner").trim(),
                visible: fieldValue("visible"), active: fieldValue("active"), category: fieldValue("category"),
                display_order: Number(fieldValue("display_order") || 0), description: fieldValue("description").trim(),
                tags: [...state.tags], featured: fieldValue("featured"),
                freshness_threshold_hours: fieldValue("freshness_threshold_hours") ? Number(fieldValue("freshness_threshold_hours")) : null,
            },
            display: { thumbnail_url: fieldValue("thumbnail_url").trim(), thumbnail_status: fieldValue("thumbnail_status") || "fallback" },
            visual_identity: {
                short_description: fieldValue("short_description").trim(), long_description: fieldValue("long_description").trim(),
                business_purpose: fieldValue("business_purpose").trim(), technical_owner: fieldValue("technical_owner").trim(),
                secondary_categories: [], thumbnail_source: fieldValue("thumbnail_source"), thumbnail_url: fieldValue("thumbnail_url").trim(),
                selected_visual_asset_id: fieldValue("selected_visual_asset_id") || null,
                powerbi_screenshot_url: fieldValue("powerbi_screenshot_url").trim(), thumbnail_status: fieldValue("thumbnail_status"),
                thumbnail_focal_x: Number(fieldValue("thumbnail_focal_x") || 50), thumbnail_focal_y: Number(fieldValue("thumbnail_focal_y") || 50),
                illustration_code: fieldValue("illustration_code"), icon_code: fieldValue("icon_code"), accent_code: fieldValue("accent_code"),
                card_badge: fieldValue("card_badge"), card_style: fieldValue("card_style"), featured: fieldValue("featured"),
            },
            launch: Object.fromEntries(["launch_mode","authentication_mode","open_behavior","required_entra_tenant_id","contains_powerapps_visual","requires_user_identity","supports_chatbot_navigation","supports_embedded_filtering"].map(name => [name, fieldValue(name)])),
            navigation: Object.fromEntries(["opening_profile_name","default_page_internal_name","display_option","background_type","default_rls_role","filter_pane_visible","page_navigation_visible","bookmarks_pane_visible"].map(name => [name, fieldValue(name)])),
            viewer: {
                show_filter_bar: fieldValue("viewer_show_filter_bar"),
                default_period: fieldValue("viewer_default_period"),
                available_periods: $$("[data-viewer-periods] input:checked").map(input => input.value),
                auto_apply_presets: fieldValue("viewer_auto_apply_presets"),
                custom_range_enabled: fieldValue("viewer_custom_range_enabled"),
                external_page_navigation: fieldValue("viewer_external_page_navigation"),
                focus_mode_enabled: fieldValue("viewer_focus_mode_enabled"),
                fullscreen_enabled: fieldValue("viewer_fullscreen_enabled"),
                allow_open_powerbi: fieldValue("viewer_allow_open_powerbi"),
                reset_behavior: fieldValue("viewer_reset_behavior"),
                date_table: fieldValue("viewer_date_table").trim(),
                date_column: fieldValue("viewer_date_column").trim(),
                help_text: fieldValue("viewer_help_text").trim(),
            },
            troubleshooting: { enabled: fieldValue("troubleshooting_enabled"), prompt: fieldValue("troubleshooting_prompt"), instructions: fieldValue("troubleshooting_instructions") },
            parameters: state.parameters.map((item, index) => ({...item, display_order:index})),
        };
    }

    function markDirty() { if (!state.config) return; setDirty(JSON.stringify(buildPayload()) !== state.baseline); }
    function setDirty(value) {
        state.dirty = value;
        $("[data-save-state]").textContent = value ? "Unsaved changes" : "Saved";
        const saveButton = $("[data-save-changes]");
        const publishButton = $("[data-publish]");
        $("[data-cancel-changes]").disabled = !value;
        saveButton.disabled = !value;
        publishButton.disabled = !value && state.config?.validation_status === "Validated";
        saveButton.classList.toggle("is-primary", value);
        publishButton.classList.toggle("is-primary", !value && !publishButton.disabled);
        $("[data-preview-draft]").textContent = value ? "Preview — Unsaved Changes" : "Preview — Saved";
    }

    function renderSecondaryNavigation() {
        const sections = AREA_SECTIONS[state.activeArea] || AREA_SECTIONS.essentials;
        const host = $("[data-secondary-nav]");
        host.hidden = sections.length < 2;
        host.innerHTML = sections.map(([section, text]) => `<button type="button" data-section="${section}" aria-current="${section === state.activeTab ? "page" : "false"}">${esc(text)}</button>`).join("");
        $$('[data-area]').forEach(button => {
            const active = button.dataset.area === state.activeArea;
            button.setAttribute("aria-selected", String(active));
            button.classList.toggle("is-active", active);
        });
    }

    function switchArea(area) {
        if (!AREA_SECTIONS[area]) area = "essentials";
        state.activeArea = area;
        const available = AREA_SECTIONS[area].map(([section]) => section);
        if (!available.includes(state.activeTab)) state.activeTab = available[0];
        switchTab(state.activeTab);
    }

    function switchTab(tab, update = true) {
        state.activeTab = SECTION_AREA[tab] ? tab : "general";
        state.activeArea = SECTION_AREA[state.activeTab];
        $$('[data-panel]').forEach(panel => panel.hidden = panel.dataset.panel !== state.activeTab);
        renderSecondaryNavigation();
        if (update) updateUrl();
    }

    async function selectReport(id, force = false) {
        if (!force && state.dirty && id !== state.selectedId) { state.pendingSelection = id; return $("[data-unsaved-dialog]").showModal(); }
        state.detailController?.abort(); state.detailController = new AbortController(); state.selectedId = id; updateUrl(); renderReportList();
        root.querySelector(".report-config-workspace")?.classList.add("has-selection");
        $("[data-editor-empty]").hidden = true; $("[data-editor-content]").hidden = true; $("[data-editor-loading]").hidden = false;
        try {
            const payload = await request(api(root.dataset.detailApiTemplate, id), { signal: state.detailController.signal });
            state.config = payload.configuration; state.options = payload.options || {};
            $("[data-editor-loading]").hidden = true; $("[data-editor-content]").hidden = false; renderEditor();
            $("[data-report-sidebar]").classList.remove("is-mobile-open");
        } catch (error) {
            if (error.name === "AbortError") return;
            $("[data-editor-loading]").hidden = true; $("[data-editor-empty]").hidden = false; $("[data-editor-empty] h2").textContent = "Configuration unavailable"; $("[data-editor-empty] p").textContent = error.message;
        }
    }

    async function save(publish = false) {
        if (!state.config) return false;
        const button = publish ? $("[data-publish]") : $("[data-save-changes]"); button.disabled = true; $("[data-save-state]").textContent = publish ? "Publishing..." : "Saving...";
        try {
            const url = api(publish ? root.dataset.publishApiTemplate : root.dataset.detailApiTemplate, state.selectedId);
            const payload = await request(url, { method: publish ? "POST" : "PATCH", body: JSON.stringify(buildPayload()) });
            state.config = payload.configuration; renderEditor(); await loadList(); toast(publish ? "Configuration published." : "Configuration saved."); return true;
        } catch (error) {
            $("[data-save-state]").textContent = "Save failed"; toast(error.message, true);
            if (error.code === "VERSION_CONFLICT") toast("Reload the latest version before saving.", true);
            return false;
        } finally { button.disabled = false; }
    }

    async function validateThumbnailDimensions(file) {
        const url = URL.createObjectURL(file);
        try {
            const image = new Image();
            await new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = () => reject(new Error("The selected image could not be read."));
                image.src = url;
            });
            if (image.naturalWidth < 600 || image.naturalHeight < 225) {
                throw new Error("Use an image of at least 600 × 225 pixels. 1200 × 450 is recommended.");
            }
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    async function uploadThumbnail() {
        const input = $("[data-thumbnail-file]");
        const file = input.files?.[0];
        if (!file || !state.selectedId) return toast("Select a PNG, JPEG or WebP image.", true);
        try {
            await validateThumbnailDimensions(file);
            const body = new FormData(); body.append("thumbnail", file);
            const payload = await request(api(root.dataset.thumbnailApiTemplate, state.selectedId), { method: "POST", body });
            state.uploadedThumbnailUrl = payload.thumbnail_url + "?v=" + Date.now();
            setField("thumbnail_source", "manual_thumbnail"); setField("thumbnail_status", payload.thumbnail_status);
            updatePreview(); markDirty(); toast("Thumbnail uploaded. Save the visual identity to keep all settings.");
        } catch (error) {
            toast(error.message, true);
        }
    }

    async function removeThumbnail() {
        if (!state.selectedId) return;
        try {
            await request(api(root.dataset.thumbnailApiTemplate, state.selectedId), { method: "DELETE" });
            state.uploadedThumbnailUrl = ""; setField("thumbnail_source", "automatic"); setField("thumbnail_status", "fallback");
            $("[data-thumbnail-file]").value = ""; updatePreview(); markDirty(); toast("Thumbnail removed. The resolver will use the next fallback.");
        } catch (error) {
            toast(error.message, true);
        }
    }

    function setPreviewMode(mode) {
        state.previewMode = mode;
        const preview = $("[data-card-preview]");
        preview.className = "report-card-preview preview-" + mode;
        $$("[data-preview-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.previewMode === mode)));
    }

    function openParameter(index = null) {
        const item = index === null ? {id:"",code:"",display_name:"",source:"chatbot",data_type:"text",required:false,default_value:"",powerbi_table:"",powerbi_column:"",operator:"In",supports_multiple_values:false,active:true} : state.parameters[index];
        const drawer = $("[data-parameter-drawer]"); drawer.dataset.index = index === null ? "" : index; $("[data-parameter-title]").textContent = index === null ? "Add parameter" : `Edit ${item.display_name}`;
        $$('[data-param-field]', drawer).forEach(field => { const value = item[field.dataset.paramField]; if (field.type === "checkbox") field.checked = Boolean(value); else field.value = value ?? ""; });
        setOptions($('[data-param-field="source"]', drawer), state.options.parameter_sources, item.source); setOptions($('[data-param-field="data_type"]', drawer), state.options.parameter_types, item.data_type); setOptions($('[data-param-field="operator"]', drawer), state.options.parameter_operators, item.operator);
        drawer.classList.add("is-open"); drawer.setAttribute("aria-hidden", "false"); $("[data-parameter-backdrop]").hidden = false;
    }
    function closeParameter() { const drawer=$("[data-parameter-drawer]"); drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden","true"); $("[data-parameter-backdrop]").hidden=true; }
    function saveParameter() {
        const drawer=$("[data-parameter-drawer]"); const item={}; $$('[data-param-field]',drawer).forEach(field => item[field.dataset.paramField]=field.type==="checkbox"?field.checked:field.value.trim());
        item.active = true; if (!item.code) return toast("Parameter code is required.", true);
        const index=drawer.dataset.index; if (index === "") state.parameters.push(item); else state.parameters[Number(index)] = item;
        renderParameters(); closeParameter(); markDirty();
    }

    async function runTests() {
        if (!state.config) return;
        setDrawer("test", true);
        $("[data-test-center]").innerHTML='<div class="test-running">Running non-destructive configuration tests...</div>';
        $("[data-test-drawer-list]").innerHTML='<div class="test-running">Running non-destructive configuration tests...</div>';
        try { const payload=await request(api(root.dataset.testApiTemplate,state.selectedId),{method:"POST",body:"{}"});
            state.config.status=payload.result.validation; state.config.tests=[{test_code:"configuration_validation",status:payload.result.overall,created_at:new Date().toISOString(),result:payload.result},...(state.config.tests||[])]; renderTests(); toast("Configuration tests completed.");
        } catch(error){ toast(error.message,true); renderTests(); }
    }

    async function promptPreview() {
        const output=$("[data-prompt-validation]"); output.textContent="Validating...";
        try { const payload=await request(api(root.dataset.promptPreviewApiTemplate,state.selectedId),{method:"POST",body:JSON.stringify({prompt:fieldValue("troubleshooting_prompt"),error_message:"Failed to open the MSOLAP connection."})}); output.textContent=`Valid · ${payload.provider} · ${payload.use_case}`; alert(payload.rendered_prompt); }
        catch(error){ output.textContent=error.message; }
    }

    function renderDiagnostic(result) {
        const out=$("[data-diagnostic-output]"); out.hidden=false;
        out.innerHTML=`<header><strong>${esc(result.status)}</strong></header><ul>${(result.checks||[]).map(item=>`<li class="status-${esc(item.status.toLowerCase())}"><strong>${esc(item.name)}</strong><span>${esc(item.status)}</span><p>${esc(item.detail)}</p></li>`).join("")}</ul>${(result.recommendations||[]).map(item=>`<article><strong>${esc(item.title)}</strong><p>${esc(item.detail)}</p></article>`).join("")}`;
    }
    async function diagnose(repair=false) { const out=$("[data-diagnostic-output]"); out.hidden=false; out.textContent="Running Power BI diagnostics...";
        try{const payload=await request(api(root.dataset.diagnosticsApiTemplate,state.selectedId),{method:"POST",body:JSON.stringify({error_text:$("[data-diagnostic-error]").value,repair})}); renderDiagnostic(payload.result);}catch(error){out.textContent=error.message;}}
    async function refreshModel(){try{const payload=await request(api(root.dataset.refreshApiTemplate,state.selectedId),{method:"POST"});toast(`Semantic-model status: ${payload.status}.`);}catch(error){toast(error.message,true);}}

    function openCopyDialog(){const dialog=$("[data-copy-dialog]"); const select=$("[data-copy-source]",dialog); setOptions(select,(state.options.copy_sources||[]).map(x=>({value:x.report_id,label:x.display_name})),"","Select a report");dialog.showModal();}
    async function copySettings(){const dialog=$("[data-copy-dialog]");const source=$("[data-copy-source]",dialog).value;const sections=$$('input[type="checkbox"]:checked',dialog).map(x=>x.value);if(!source||!sections.length)return toast("Select a report and at least one section.",true);try{const payload=await request(api(root.dataset.copyApiTemplate,state.selectedId),{method:"POST",body:JSON.stringify({source_report_id:source,sections})});state.config=payload.configuration;renderEditor();dialog.close();toast("Selected settings copied.");}catch(error){toast(error.message,true);}}

    async function synchronize(apply=false){const dialog=$("[data-sync-dialog]");const results=$("[data-sync-results]",dialog);results.textContent=apply?"Applying synchronization...":"Comparing Power BI reports...";try{const payload=await request(root.dataset.syncApi,{method:"POST",body:JSON.stringify({apply})});results.innerHTML=`<strong>${payload.report_count} reports detected</strong><ul>${(payload.changes||[]).map(item=>`<li><span>${esc(item.name)}</span><b>${esc(label(item.change))}</b></li>`).join("")||"<li>No changes detected.</li>"}</ul>`;$('[value="apply"]',dialog).disabled=apply||!payload.changes.length;if(apply){await loadList();toast("Reports synchronized.");}}catch(error){results.textContent=error.message;}}

    function setNavigatorCollapsed(collapsed) {
        state.navigatorCollapsed = collapsed;
        root.classList.toggle("navigator-collapsed", collapsed);
        localStorage.setItem("mining360.reportingConfig.navigatorCollapsed", collapsed ? "1" : "0");
    }

    function setDrawer(name, open) {
        const drawer = $(`[data-${name}-drawer]`);
        const backdrop = $(`[data-${name}-backdrop]`);
        drawer.classList.toggle("is-open", open);
        drawer.setAttribute("aria-hidden", String(!open));
        backdrop.hidden = !open;
        if (open) drawer.querySelector("button")?.focus();
    }

    function toggleHealth(open) {
        const popover = $("[data-health-popover]");
        popover.hidden = !open;
        $("[data-health-toggle]").setAttribute("aria-expanded", String(open));
    }

    root.addEventListener("click", event => {
        const report=event.target.closest("[data-report-id]"); if(report)return selectReport(report.dataset.reportId);
        if(event.target.closest("[data-list-retry]"))return loadList();
        const area=event.target.closest("[data-area]"); if(area)return switchArea(area.dataset.area);
        const section=event.target.closest("[data-section]"); if(section)return switchTab(section.dataset.section);
        if(event.target.closest("[data-health-toggle]"))return toggleHealth($("[data-health-popover]").hidden);
        if(event.target.closest("[data-health-close]"))return toggleHealth(false);
        if(event.target.closest("[data-filter-toggle]")){const filters=$("[data-filters]");filters.hidden=!filters.hidden;event.target.closest("[data-filter-toggle]").setAttribute("aria-expanded",String(!filters.hidden));return;}
        const removeFilter=event.target.closest("[data-filter-remove]");if(removeFilter){const key=removeFilter.dataset.filterRemove;state.filters[key]="all";$(`[data-filter="${key}"]`).value="all";return scheduleList();}
        if(event.target.closest("[data-clear-list-filters]")){Object.keys(state.filters).forEach(key=>state.filters[key]=key==="q"?"":"all");$("[data-report-search]").value="";$$('[data-filter]').forEach(x=>x.value="all");renderFilterChips();return scheduleList();}
        const summary=event.target.closest("[data-summary-filter]");if(summary){const value=summary.dataset.summaryFilter;if(value==="visible"||value==="hidden"){state.filters.visibility=value;$("[data-filter=visibility]").value=value;}else if(value==="needs_review"||value==="invalid"){state.filters.status=value;$("[data-filter=status]").value=value;}else{state.filters.visibility="all";state.filters.status="all";}return scheduleList();}
        const visualSummary=event.target.closest("[data-visual-summary-filter]");if(visualSummary){state.filters.visual_status=visualSummary.dataset.visualSummaryFilter;$("[data-filter=visual_status]").value=state.filters.visual_status;return scheduleList();}
        if(event.target.closest("[data-tag-add]")){const input=$("[data-tag-input]");const value=input.value.trim();if(value&&!state.tags.includes(value)&&state.tags.length<10){state.tags.push(value);input.value="";renderTags();}return;}
        const tag=event.target.closest("[data-tag-remove]");if(tag){state.tags.splice(Number(tag.dataset.tagRemove),1);return renderTags();}
        if(event.target.closest("[data-parameter-add]"))return openParameter(); const edit=event.target.closest("[data-parameter-edit]");if(edit)return openParameter(Number(edit.dataset.parameterEdit)); const remove=event.target.closest("[data-parameter-remove]");if(remove){state.parameters.splice(Number(remove.dataset.parameterRemove),1);renderParameters();return markDirty();}
        if(event.target.closest("[data-parameter-save]"))return saveParameter();if(event.target.closest("[data-parameter-close]")||event.target.matches("[data-parameter-backdrop]"))return closeParameter();
        if(event.target.closest("[data-save-changes]"))return save(false);if(event.target.closest("[data-publish]"))return save(true);if(event.target.closest("[data-cancel-changes]")){renderEditor();return;}
        if(event.target.closest("[data-test-open]")){renderTests();return setDrawer("test",true);}
        if(event.target.closest("[data-test-close]")||event.target.matches("[data-test-backdrop]"))return setDrawer("test",false);
        if(event.target.closest("[data-run-tests]")||event.target.closest("[data-run-all-tests]")||event.target.closest("[data-test-run-all]")||event.target.closest("[data-test-run-failed]")||event.target.closest("[data-single-test]"))return runTests();
        if(event.target.closest("[data-checklist-open]")){renderChecklist();return setDrawer("checklist",true);}
        if(event.target.closest("[data-checklist-close]")||event.target.matches("[data-checklist-backdrop]"))return setDrawer("checklist",false);
        const checklistSection=event.target.closest("[data-checklist-section]");if(checklistSection){setDrawer("checklist",false);return switchTab(checklistSection.dataset.checklistSection);}
        if(event.target.closest("[data-prompt-preview]"))return promptPreview();const variable=event.target.closest("[data-prompt-variable]");if(variable){const field=formField("troubleshooting_prompt");const token=`{{${variable.dataset.promptVariable}}}`;field.setRangeText(token,field.selectionStart,field.selectionEnd,"end");field.focus();return markDirty();}
        if(event.target.closest("[data-prompt-reset]")){setField("troubleshooting_prompt","Explain {{error_message}} for {{report_name}}. Use {{report_status}} and {{last_refresh}} to provide safe, concise corrective actions. Never expose credentials or tokens.");return markDirty();}
        if(event.target.closest("[data-diagnostic-run]"))return diagnose(false);if(event.target.closest("[data-diagnostic-repair]"))return diagnose(true);if(event.target.closest("[data-model-refresh]"))return refreshModel();
        if(event.target.closest("[data-report-more-toggle]")){const menu=$("[data-report-more]");menu.hidden=!menu.hidden;event.target.closest("[data-report-more-toggle]").setAttribute("aria-expanded",String(!menu.hidden));return;}
        if(event.target.closest("[data-copy-open]"))return openCopyDialog();if(event.target.closest("[data-preview-card]")){switchTab("visual");$("[data-report-more]").hidden=true;return;}
        if(event.target.closest("[data-open-visual-tab]"))return switchTab("visual");
        if(event.target.closest("[data-thumbnail-upload]"))return uploadThumbnail();
        if(event.target.closest("[data-thumbnail-remove]"))return removeThumbnail();
        const previewMode=event.target.closest("[data-preview-mode]");if(previewMode)return setPreviewMode(previewMode.dataset.previewMode);
        if(event.target.closest("[data-navigator-collapse]"))return setNavigatorCollapsed(true);
        if(event.target.closest("[data-navigator-expand]"))return setNavigatorCollapsed(false);
        if(event.target.closest("[data-mobile-list]"))return root.querySelector(".report-config-workspace")?.classList.remove("has-selection");
        if(event.target.closest("[data-sync-open]")){const dialog=$("[data-sync-dialog]");dialog.showModal();return synchronize(false);}
    });

    $("[data-config-form]").addEventListener("input",()=>{updatePreview();updateLaunchHelp();markDirty();});
    $("[data-config-form]").addEventListener("change",()=>{updatePreview();updateLaunchHelp();markDirty();});
    $("[data-report-search]").addEventListener("input",event=>{state.filters.q=event.target.value.trim();scheduleList();});
    $$('[data-filter]').forEach(select=>select.addEventListener("change",()=>{state.filters[select.dataset.filter]=select.value;scheduleList();}));
    window.addEventListener("beforeunload",event=>{if(state.dirty){event.preventDefault();event.returnValue="";}});
    document.addEventListener("keydown", event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            if (state.dirty) save(false);
        }
        if (event.key === "Escape") {
            setDrawer("test", false); setDrawer("checklist", false); toggleHealth(false);
            const menu = $("[data-report-more]"); if (menu) menu.hidden = true;
        }
    });
    $("[data-report-list]").addEventListener("keydown", event => {
        if (!["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) return;
        const items = $$("[data-report-id]", $("[data-report-list]"));
        const current = items.indexOf(document.activeElement);
        if (event.key === "Enter" && current >= 0) return selectReport(items[current].dataset.reportId);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const next = current < 0 ? 0 : Math.max(0, Math.min(items.length - 1, current + (event.key === "ArrowDown" ? 1 : -1)));
            items[next]?.focus();
        }
    });

    const unsavedDialog=$("[data-unsaved-dialog]");
    const copyDialog=$("[data-copy-dialog]");
    const syncDialog=$("[data-sync-dialog]");
    unsavedDialog?.addEventListener("click",async event=>{const value=event.target.value;if(!value)return;if(value==="keep")return event.currentTarget.close();if(value==="save"&&!await save(false))return;event.currentTarget.close();const id=state.pendingSelection;state.pendingSelection="";if(id)selectReport(id,true);});
    copyDialog?.addEventListener("click",event=>{if(event.target.value==="cancel")event.currentTarget.close();if(event.target.value==="copy")copySettings();});
    syncDialog?.addEventListener("click",event=>{if(event.target.value==="cancel")event.currentTarget.close();if(event.target.value==="preview")synchronize(false);if(event.target.value==="apply")synchronize(true);});

    installContextualHelp();
    setNavigatorCollapsed(state.navigatorCollapsed);
    const params=new URLSearchParams(location.search);state.selectedId=params.get("report")||"";state.filters.q=params.get("q")||"";$("[data-report-search]").value=state.filters.q;
    Object.keys(state.filters).forEach(key=>{if(key!=="q"&&params.get(key)){state.filters[key]=params.get(key);const field=$(`[data-filter="${key}"]`);if(field)field.value=state.filters[key];}});
    renderFilterChips();
    loadList().then(()=>{if(state.selectedId)selectReport(state.selectedId,true);else if(state.reports[0])selectReport(state.reports[0].id,true);});
})();
