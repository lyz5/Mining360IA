(() => {
    const root = document.querySelector("[data-reporting-config]");
    if (!root) return;

    const rows = [...root.querySelectorAll("[data-report-config-row]")];
    const search = root.querySelector("[data-report-config-search]");
    const empty = root.querySelector("[data-report-config-empty]");
    const csrf = root.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));

    function updateVisibility(input) {
        const label = input.closest("[data-report-config-row]")?.querySelector("[data-visibility-label]");
        if (label) label.textContent = input.checked ? "Visible" : "Hidden";
    }

    function refreshSearchValue(row, displayName) {
        const sourceName = row.dataset.reportName || "";
        row.dataset.search = `${sourceName} ${displayName}`.toLowerCase();
    }

    async function saveDisplayName(row) {
        const input = row.querySelector("[data-report-display-input]");
        const button = row.querySelector("[data-report-display-save]");
        const status = row.querySelector("[data-report-display-status]");
        const value = input.value.trim().replace(/\s+/g, " ");
        if (!value) {
            status.textContent = "Display name is required.";
            status.className = "is-error";
            input.focus();
            return;
        }
        input.value = value;
        button.disabled = true;
        input.disabled = true;
        status.textContent = "Saving...";
        status.className = "is-saving";
        try {
            const response = await fetch(row.dataset.displayNameUrl, {
                method: "PATCH",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({
                    display_name: value,
                    category: row.querySelector("[data-report-category]")?.value || "other",
                    description: row.querySelector("[data-report-description]")?.value || "",
                    tags: (row.querySelector("[data-report-tags]")?.value || "").split(",").map(item => item.trim()).filter(Boolean),
                    business_owner: row.querySelector("[data-report-owner]")?.value || "",
                    freshness_threshold_hours: row.querySelector("[data-report-freshness]")?.value || null,
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.error || "Display name could not be saved.");
            input.value = payload.report.display_name;
            row.querySelector("[data-report-display-title]").textContent = payload.report.display_name;
            refreshSearchValue(row, payload.report.display_name);
            status.textContent = "Saved";
            status.className = "is-saved";
        } catch (error) {
            status.textContent = error.message;
            status.className = "is-error";
        } finally {
            button.disabled = false;
            input.disabled = false;
        }
    }

    function openingPayload(row) {
        return {
            profile_name: row.querySelector("[data-opening-profile-name]")?.value || "Standard Power BI",
            authentication_mode: row.querySelector("[data-opening-auth]")?.value || "app_owns_data",
            default_page_internal_name: row.querySelector("[data-opening-page]")?.value || "",
            display_option: row.querySelector("[data-opening-display]")?.value || "fit_to_page",
            background_type: row.querySelector("[data-opening-background]")?.value || "default",
            default_rls_role: row.querySelector("[data-opening-rls]")?.value || "Global",
            filter_pane_visible: Boolean(row.querySelector("[data-opening-filters]")?.checked),
            page_navigation_visible: Boolean(row.querySelector("[data-opening-navigation]")?.checked),
            bookmarks_pane_visible: Boolean(row.querySelector("[data-opening-bookmarks]")?.checked),
        };
    }

    function applyOpeningProfile(row, profile) {
        const setValue = (selector, value) => { const field = row.querySelector(selector); if (field) field.value = value ?? ""; };
        const setChecked = (selector, value) => { const field = row.querySelector(selector); if (field) field.checked = Boolean(value); };
        setValue("[data-opening-profile-name]", profile.profile_name || "Standard Power BI");
        setValue("[data-opening-auth]", profile.authentication_mode || "app_owns_data");
        setValue("[data-opening-page]", profile.default_page_internal_name || "");
        setValue("[data-opening-display]", profile.display_option || "fit_to_page");
        setValue("[data-opening-background]", profile.background_type || "default");
        setValue("[data-opening-rls]", profile.default_rls_role || "Global");
        setChecked("[data-opening-filters]", profile.filter_pane_visible);
        setChecked("[data-opening-navigation]", profile.page_navigation_visible);
        setChecked("[data-opening-bookmarks]", profile.bookmarks_pane_visible);
        const fields = row.querySelector("[data-opening-fields]");
        if (fields) fields.hidden = false;
        const summary = row.querySelector("[data-opening-summary]");
        if (summary) summary.textContent = `${profile.profile_name || "Standard Power BI"} · ${profile.authentication_mode || "app_owns_data"}`;
    }

    async function updateOpeningProfile(row, method, body, button) {
        const status = row.querySelector("[data-opening-status]");
        button.disabled = true;
        if (status) { status.textContent = method === "POST" ? "Copying..." : "Saving..."; status.className = "is-saving"; }
        try {
            const response = await fetch(row.dataset.openingProfileUrl, {
                method,
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify(body),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Opening parameters could not be saved.");
            applyOpeningProfile(row, payload.opening_profile);
            if (status) { status.textContent = payload.message || "Saved"; status.className = "is-saved"; }
        } catch (error) {
            if (status) { status.textContent = error.message; status.className = "is-error"; }
        } finally {
            button.disabled = false;
        }
    }

    function renderDiagnostics(row, result) {
        const target = row.querySelector("[data-diagnostics-result]");
        if (!target) return;
        const checks = (result.checks || []).map(item => `
            <li class="diagnostic-check diagnostic-check--${escapeHtml(String(item.status || "").toLowerCase().replaceAll(" ", "-"))}">
                <span>${escapeHtml(item.status)}</span><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.detail)}</p>
            </li>`).join("");
        const recommendations = (result.recommendations || []).map(item => `
            <article><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></article>`).join("");
        const sources = (result.datasources || []).map(item => `
            <li><strong>${escapeHtml(item.type)}</strong><span>${escapeHtml(item.location)}${item.database ? ` · ${escapeHtml(item.database)}` : ""}</span><small>${item.gateway_bound ? "Gateway bound" : "No gateway binding detected"}</small></li>`).join("");
        const actions = (result.actions || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
        const links = result.links || {};
        target.innerHTML = `
            <header><span>Diagnostic result</span><strong>${escapeHtml(result.status || "Completed")}</strong></header>
            <ul class="diagnostic-checks">${checks}</ul>
            ${recommendations ? `<section><h4>Recommended actions</h4>${recommendations}</section>` : ""}
            ${sources ? `<section><h4>Detected data sources</h4><ul class="diagnostic-sources">${sources}</ul></section>` : ""}
            ${actions ? `<section><h4>Actions completed</h4><ul>${actions}</ul></section>` : ""}
            ${(links.report || links.semantic_model) ? `<nav>${links.report ? `<a href="${escapeHtml(links.report)}" target="_blank" rel="noreferrer">Open report settings</a>` : ""}${links.semantic_model ? `<a href="${escapeHtml(links.semantic_model)}" target="_blank" rel="noreferrer">Open semantic model settings</a>` : ""}</nav>` : ""}`;
        target.hidden = false;
    }

    async function runDiagnostics(row, button, repair = false) {
        const target = row.querySelector("[data-diagnostics-result]");
        button.disabled = true;
        if (target) { target.hidden = false; target.textContent = "Running Power BI diagnostics..."; }
        try {
            const response = await fetch(row.dataset.diagnosticsUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({ error_text: row.querySelector("[data-diagnostics-error]")?.value || "", repair }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Diagnostics could not complete.");
            renderDiagnostics(row, payload.result || {});
        } catch (error) {
            if (target) { target.hidden = false; target.innerHTML = `<p class="is-error">${escapeHtml(error.message)}</p>`; }
        } finally {
            button.disabled = false;
        }
    }

    async function refreshSemanticModel(row, button) {
        const target = row.querySelector("[data-diagnostics-result]");
        button.disabled = true;
        try {
            const response = await fetch(row.dataset.refreshUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { Accept: "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.error || "The semantic-model refresh could not start.");
            if (target) { target.hidden = false; target.innerHTML = `<p class="is-saved">Semantic-model refresh started. Power BI status: ${escapeHtml(payload.status || "Refreshing")}.</p>`; }
        } catch (error) {
            if (target) { target.hidden = false; target.innerHTML = `<p class="is-error">${escapeHtml(error.message)}</p>`; }
        } finally {
            button.disabled = false;
        }
    }

    root.addEventListener("change", event => {
        if (event.target.matches("input[name='visible_report_ids']")) updateVisibility(event.target);
    });

    root.addEventListener("click", event => {
        const save = event.target.closest("[data-report-display-save]");
        if (save) return saveDisplayName(save.closest("[data-report-config-row]"));
        const openingSave = event.target.closest("[data-opening-save]");
        if (openingSave) {
            const row = openingSave.closest("[data-report-config-row]");
            return updateOpeningProfile(row, "PATCH", openingPayload(row), openingSave);
        }
        const openingCopy = event.target.closest("[data-opening-copy]");
        if (openingCopy) {
            const row = openingCopy.closest("[data-report-config-row]");
            const source = row.querySelector("[data-opening-source]")?.value || "";
            const status = row.querySelector("[data-opening-status]");
            if (!source) {
                if (status) { status.textContent = "Select a reference report."; status.className = "is-error"; }
                return;
            }
            return updateOpeningProfile(row, "POST", { source_report_id: source }, openingCopy);
        }
        const diagnosticsRun = event.target.closest("[data-diagnostics-run]");
        if (diagnosticsRun) return runDiagnostics(diagnosticsRun.closest("[data-report-config-row]"), diagnosticsRun, false);
        const diagnosticsRepair = event.target.closest("[data-diagnostics-repair]");
        if (diagnosticsRepair) return runDiagnostics(diagnosticsRepair.closest("[data-report-config-row]"), diagnosticsRepair, true);
        const diagnosticsRefresh = event.target.closest("[data-diagnostics-refresh]");
        if (diagnosticsRefresh) return refreshSemanticModel(diagnosticsRefresh.closest("[data-report-config-row]"), diagnosticsRefresh);
        const reset = event.target.closest("[data-report-display-reset]");
        if (reset) {
            const row = reset.closest("[data-report-config-row]");
            const source = row.dataset.reportName || "";
            row.querySelector("[data-report-display-input]").value = source;
            return saveDisplayName(row);
        }
        const select = event.target.closest("[data-report-config-select]");
        if (select) {
            const checked = select.dataset.reportConfigSelect === "all";
            rows.forEach(row => {
                if (row.hidden) return;
                const input = row.querySelector("input[name='visible_report_ids']");
                input.checked = checked;
                updateVisibility(input);
            });
        }
    });

    root.addEventListener("keydown", event => {
        if (event.target.matches("[data-report-display-input]") && event.key === "Enter") {
            event.preventDefault();
            saveDisplayName(event.target.closest("[data-report-config-row]"));
        }
    });

    search?.addEventListener("input", () => {
        const query = search.value.trim().toLowerCase();
        let visibleRows = 0;
        rows.forEach(row => {
            row.hidden = Boolean(query) && !row.dataset.search.includes(query);
            if (!row.hidden) visibleRows += 1;
        });
        if (empty) empty.hidden = visibleRows !== 0;
    });
})();
