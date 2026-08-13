(function () {
    const root = document.getElementById("powerbi-interaction-panel");
    if (!root) return;

    const state = { resource: "reports", items: [], editing: null, navigation: null, embed: null, loaded: false };
    const apiBase = root.dataset.apiBase;
    const table = document.getElementById("pbi-table");
    const modal = document.getElementById("pbi-modal");
    const form = document.getElementById("pbi-form");
    const fields = document.getElementById("pbi-form-fields");
    const sections = (() => { try { return JSON.parse(document.getElementById("kb-sections-data")?.textContent || "[]"); } catch (_) { return []; } })();
    const caches = { reports: [], pages: [], visuals: [] };

    const configs = {
        reports: { columns: ["display_name", "authentication_mode", "contains_powerapps_visual", "validation_status", "is_active"], fields: [["section", "Section", "section"], ["workspace_id", "Workspace ID"], ["report_id", "Report ID"], ["report_name", "Report Name"], ["display_name", "Display Name"], ["semantic_model_id", "Semantic Model ID"], ["embed_url", "Embed URL", "textarea"], ["description", "Description", "textarea"], ["authentication_mode", "Authentication Mode", "authentication_mode"], ["contains_powerapps_visual", "Contains Power Apps Visual", "checkbox"], ["requires_user_identity", "Requires User Entra Identity", "checkbox"], ["allow_service_principal_metadata_access", "Service Principal Allowed for Metadata", "checkbox"], ["required_entra_tenant_id", "Required Tenant ID"], ["powerapps_app_name", "Power Apps App Name"], ["powerapps_environment", "Power Apps Environment"], ["access_instructions", "Access Instructions", "textarea"], ["is_default", "Default", "checkbox"], ["validation_status", "Validation", "status"], ["is_active", "Active", "checkbox"]] },
        pages: { columns: ["page_display_name", "page_internal_name", "report_display_name", "validation_status", "is_active"], fields: [["report", "Report", "report"], ["section", "Section", "section"], ["page_internal_name", "Internal Name"], ["page_display_name", "Display Name"], ["description", "Description", "textarea"], ["page_order", "Order", "number"], ["is_default", "Default", "checkbox"], ["validation_status", "Validation", "status"], ["is_active", "Active", "checkbox"]] },
        visuals: { columns: ["visual_title", "visual_internal_name", "visual_type", "page_display_name", "related_metric_code", "validation_status"], fields: [["page", "Page", "page"], ["section", "Section", "section"], ["visual_internal_name", "Internal Name"], ["visual_title", "Title"], ["visual_type", "Type"], ["description", "Description", "textarea"], ["supported_actions", "Supported Actions JSON", "json"], ["related_metric_code", "Metric Code"], ["is_primary_visual", "Primary", "checkbox"], ["validation_status", "Validation", "status"], ["is_active", "Active", "checkbox"]] },
        slicers: { columns: ["slicer_title", "slicer_internal_name", "filter_code", "powerbi_table_name", "powerbi_column_name", "validation_status"], fields: [["page", "Page", "page"], ["visual", "Visual", "visual", true], ["slicer_internal_name", "Internal Name"], ["slicer_title", "Title"], ["powerbi_table_name", "Table"], ["powerbi_column_name", "Column"], ["filter_code", "Filter Code"], ["value_mapping", "Value Mapping (JSON)", "json"], ["data_type", "Data Type"], ["supports_multiple_values", "Multiple Values", "checkbox"], ["is_required", "Required", "checkbox"], ["validation_status", "Validation", "status"], ["is_active", "Active", "checkbox"]] },
        "kpi-page-mappings": { columns: ["metric_code", "section_code", "report", "page", "priority", "is_default", "is_active"], fields: [["section", "Section", "section"], ["metric_code", "Metric Code"], ["report", "Report", "report"], ["page", "Page", "page"], ["priority", "Priority", "number"], ["is_default", "Default", "checkbox"], ["is_active", "Active", "checkbox"]] },
        "kpi-visual-mappings": { columns: ["metric_code", "section_code", "page", "visual", "interaction_action", "priority", "is_active"], fields: [["section", "Section", "section"], ["metric_code", "Metric Code"], ["page", "Page", "page"], ["visual", "Visual", "visual"], ["interaction_action", "Action", "action"], ["priority", "Priority", "number"], ["is_default", "Default", "checkbox"], ["is_active", "Active", "checkbox"]] },
        "intent-navigation-mappings": { columns: ["intent_type", "metric_code", "section_code", "report", "page", "visual", "priority"], fields: [["section", "Section", "section"], ["intent_type", "Intent Type", "intent"], ["metric_code", "Metric Code"], ["report", "Report", "report"], ["page", "Page", "page", true], ["visual", "Visual", "visual", true], ["priority", "Priority", "number"], ["is_active", "Active", "checkbox"]] },
        "supported-actions": { columns: ["action_code", "display_name", "target_type", "is_active"], fields: [["action_code", "Action Code"], ["display_name", "Display Name"], ["description", "Description", "textarea"], ["target_type", "Target Type"], ["is_active", "Active", "checkbox"]] },
        logs: { columns: ["created_at", "question_text", "status", "report", "page", "visual", "execution_time_ms"], readonly: true },
    };

    function csrf() { return document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || ""; }
    function esc(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;"); }
    async function jsonFetch(url, options) { const response = await fetch(url, options); const payload = await response.json(); if (!response.ok || !payload.ok) throw new Error(payload.error || "Request failed."); return payload; }
    function labelFor(type, id) { const item = (caches[type] || []).find((row) => String(row.id) === String(id)); return item ? (item.display_name || item.page_display_name || item.visual_title || item.report_name || item.visual_internal_name) : (id || ""); }
    function display(column, value) { if (["report", "page", "visual"].includes(column)) return labelFor(`${column}s`, value); if (typeof value === "boolean") return value ? "Yes" : "No"; if (value && typeof value === "object") return JSON.stringify(value); return value ?? ""; }

    async function loadCaches() {
        const [reports, pages, visuals] = await Promise.all(["reports", "pages", "visuals"].map((name) => jsonFetch(`${apiBase}/${name}/`)));
        caches.reports = reports.items; caches.pages = pages.items; caches.visuals = visuals.items;
    }

    async function load() {
        if (state.resource === "navigation-test") return;
        table.innerHTML = `<tbody><tr><td>Loading...</td></tr></tbody>`;
        try {
            await loadCaches();
            const url = new URL(`${apiBase}/${state.resource}/`, location.origin);
            const status = document.getElementById("pbi-status").value;
            if (status) url.searchParams.set("status", status);
            const payload = await jsonFetch(url);
            const query = document.getElementById("pbi-search").value.trim().toLowerCase();
            state.items = query ? payload.items.filter((item) => JSON.stringify(item).toLowerCase().includes(query)) : payload.items;
            render();
        } catch (error) { table.innerHTML = `<tbody><tr><td>${esc(error.message)}</td></tr></tbody>`; }
    }

    function render() {
        const config = configs[state.resource]; const columns = config.columns;
        table.innerHTML = `<thead><tr>${columns.map((column) => `<th>${esc(column.replaceAll("_", " "))}</th>`).join("")}<th>Actions</th></tr></thead><tbody>${state.items.map((item) => `<tr>${columns.map((column) => `<td>${esc(display(column, item[column]))}</td>`).join("")}<td class="row-actions"><button class="icon-action js-pbi-edit" data-id="${item.id}" title="${config.readonly ? "View" : "Edit"}"></button>${config.readonly ? "" : `<button class="icon-action delete-action js-pbi-delete" data-id="${item.id}" title="Deactivate"></button>`}${state.resource === "reports" ? `<button class="button secondary js-pbi-discover" data-report-id="${esc(item.report_id)}">Discover</button><button class="button secondary js-pbi-auth-test" data-report-id="${esc(item.report_id)}">Test auth</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="${columns.length + 1}">No records.</td></tr>`}</tbody>`;
        table.querySelectorAll(".js-pbi-edit").forEach((button) => button.onclick = () => openModal(state.items.find((item) => String(item.id) === button.dataset.id)));
        table.querySelectorAll(".js-pbi-delete").forEach((button) => button.onclick = async () => { if (!confirm("Deactivate this mapping?")) return; await jsonFetch(`${apiBase}/${state.resource}/${button.dataset.id}/`, { method: "DELETE", headers: { "X-CSRFToken": csrf() } }); await load(); });
        table.querySelectorAll(".js-pbi-discover").forEach((button) => button.onclick = () => previewForDiscovery(button.dataset.reportId));
        table.querySelectorAll(".js-pbi-auth-test").forEach((button) => button.onclick = async () => {
            try {
                const payload = await jsonFetch(`/powerbi-interaction/preflight/${encodeURIComponent(button.dataset.reportId)}/`);
                const result = payload.preflight || {};
                if (result.connect_url) {
                    window.location.href = result.connect_url;
                    return;
                }
                window.alert(result.ready_to_embed ? `Authentication ready for ${result.user?.upn || "the connected user"}.` : (result.error || "Authentication is not ready."));
            } catch (error) {
                window.alert(error.message);
            }
        });
    }

    function selectOptions(type, value, optional) {
        let options = [];
        if (type === "section") options = sections.map((item) => [item.id, item.name]);
        else if (type === "status") options = ["Imported", "To Review", "Validated", "Deprecated"].map((item) => [item, item]);
        else if (type === "intent") options = ["single_kpi", "trend", "comparison", "ranking", "navigation", "follow_up_navigation"].map((item) => [item, item]);
        else if (type === "action") options = ["focus", "show", "apply_filter", "read_filters", "export_data"].map((item) => [item, item]);
        else if (type === "authentication_mode") options = [["app_owns_data", "App owns data"], ["user_owns_data", "User owns data"]];
        else options = (caches[`${type}s`] || []).map((item) => [item.id, item.display_name || item.page_display_name || item.visual_title || item.visual_internal_name]);
        return `${optional ? '<option value="">None</option>' : ""}${options.map(([id, label]) => `<option value="${esc(id)}" ${String(id) === String(value ?? "") ? "selected" : ""}>${esc(label)}</option>`).join("")}`;
    }

    function fieldHtml(field, item) {
        const [name, label, type = "text", optional] = field; const value = item?.[name];
        if (["section", "status", "intent", "action", "report", "page", "visual", "authentication_mode"].includes(type)) return `<label>${esc(label)}<select name="${name}">${selectOptions(type, value, optional)}</select></label>`;
        if (type === "checkbox") return `<label class="inline-check stacked"><input type="checkbox" name="${name}" ${value === undefined || value ? "checked" : ""}> ${esc(label)}</label>`;
        if (type === "textarea" || type === "json") return `<label class="full-width">${esc(label)}<textarea name="${name}" rows="6">${esc(type === "json" && value && typeof value === "object" ? JSON.stringify(value, null, 2) : value || "")}</textarea></label>`;
        return `<label>${esc(label)}<input name="${name}" type="${type}" value="${esc(value ?? "")}"></label>`;
    }

    async function openModal(item) { await loadCaches(); state.editing = item || null; const config = configs[state.resource]; fields.innerHTML = (config.fields || []).map((field) => fieldHtml(field, item)).join(""); modal.hidden = false; modal.setAttribute("aria-hidden", "false"); }
    function closeModal() { modal.hidden = true; modal.setAttribute("aria-hidden", "true"); }
    function collect() { const result = {}; for (const [name, , type = "text"] of configs[state.resource].fields || []) { const field = form.elements[name]; if (!field) continue; if (type === "checkbox") result[name] = field.checked; else if (type === "number") result[name] = Number(field.value || 0); else if (type === "json") result[name] = field.value.trim() ? JSON.parse(field.value) : (name === "value_mapping" ? {} : []); else result[name] = field.value; } return result; }

    async function resolveTest() {
        const filters = {}; ["minesite", "period", "model", "customer"].forEach((name) => { const value = document.getElementById(`pbi-test-${name}`).value.trim(); if (value) filters[name] = value; });
        const intent = { section: document.getElementById("pbi-test-section").value, intent_type: "single_kpi", metric: document.getElementById("pbi-test-metric").value.trim(), filters, navigation: { open_report: true, open_page: true, focus_visual: true } };
        const output = document.getElementById("pbi-test-output"); output.textContent = "Resolving...";
        try { const payload = await jsonFetch(`${apiBase}/navigation-test/`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ intent }) }); state.navigation = payload.navigation; output.textContent = JSON.stringify(payload, null, 2); document.getElementById("pbi-test-preview").disabled = false; } catch (error) { output.textContent = error.message; }
    }

    async function previewNavigation() {
        const container = document.getElementById("pbi-test-embed"); container.hidden = false;
        if (!state.embed) state.embed = new window.Mining360PowerBIEmbed(container, { embedConfigUrl: root.dataset.embedConfigUrl });
        await state.embed.navigate(state.navigation);
    }

    async function previewForDiscovery(reportId) {
        state.navigation = { report_id: reportId, page_internal_name: "", filters: [] };
        await previewNavigation();
        const pages = await state.embed.discover();
        const payload = await jsonFetch(`${apiBase}/discover/${encodeURIComponent(reportId)}/`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ pages }) });
        alert(`Discovered ${payload.pages} pages, ${payload.visuals} visuals and ${payload.slicers} slicers. Review them before validation.`);
        await load();
    }

    document.addEventListener("mining360:powerbi-interaction-open", async () => { if (!state.loaded) { state.loaded = true; const select = document.getElementById("pbi-test-section"); select.innerHTML = sections.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join(""); await load(); } });
    document.querySelectorAll("#pbi-interaction-tabs [data-pbi-resource]").forEach((button) => button.onclick = async () => { state.resource = button.dataset.pbiResource; document.querySelectorAll("#pbi-interaction-tabs .ia-tab").forEach((item) => item.classList.toggle("active", item === button)); const testing = state.resource === "navigation-test"; document.getElementById("pbi-table-wrap").hidden = testing; document.getElementById("pbi-navigation-test").hidden = !testing; document.getElementById("pbi-add-item").hidden = testing || configs[state.resource]?.readonly; if (!testing) await load(); });
    document.getElementById("pbi-refresh").onclick = load;
    document.getElementById("pbi-search").oninput = () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(load, 200); };
    document.getElementById("pbi-status").onchange = load;
    document.getElementById("pbi-add-item").onclick = () => openModal(null);
    document.getElementById("pbi-import-reports").onclick = async () => { const payload = await jsonFetch(`${apiBase}/import-reports/`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ section_code: document.getElementById("pbi-test-section").value || "performance" }) }); alert(`${payload.imported} reports imported as To Review.`); await load(); };
    document.getElementById("pbi-test-resolve").onclick = resolveTest;
    document.getElementById("pbi-test-preview").onclick = previewNavigation;
    document.querySelectorAll("[data-pbi-modal-close]").forEach((button) => button.onclick = closeModal);
    form.onsubmit = async (event) => { event.preventDefault(); try { const data = collect(); const url = `${apiBase}/${state.resource}/${state.editing ? `${state.editing.id}/` : ""}`; await jsonFetch(url, { method: state.editing ? "PUT" : "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(data) }); closeModal(); await load(); } catch (error) { alert(error.message); } };
}());
