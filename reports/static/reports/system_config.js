(function () {
    const root = document.querySelector("[data-system-config-root]");
    if (!root) return;

    const state = {
        tab: "overview",
        items: [],
        schemas: [],
        editingItem: null,
        formMode: "integration",
    };

    const databaseColumns = {
        "database-configs": ["name", "engine", "host", "port", "database_name", "username", "driver", "last_status", "is_default", "is_active"],
        "managed-tables": ["database_config_name", "schema_name", "table_name", "category", "model_name", "row_count", "last_synced_at", "is_active"],
    };
    const databaseFields = [
        {key: "name", label: "Name", type: "text", required: true},
        {key: "engine", label: "Engine", type: "select", options: ["SQL Server", "Snowflake", "SQLite", "Other"]},
        {key: "purpose", label: "Purpose", type: "text"},
        {key: "host", label: "Host / Server", type: "text", required: true},
        {key: "port", label: "Port", type: "number"},
        {key: "database_name", label: "Database", type: "text", required: true},
        {key: "schema_name", label: "Default Schema", type: "text"},
        {key: "username", label: "User", type: "text"},
        {key: "password", label: "Password", type: "password", secret: true},
        {key: "driver", label: "Driver", type: "text"},
        {key: "connection_options", label: "Connection Options JSON", type: "json"},
        {key: "is_default", label: "Default", type: "boolean"},
        {key: "is_active", label: "Active", type: "boolean"},
    ];
    const parameterFields = [
        {key: "key", label: "Key", type: "text", required: true},
        {key: "label", label: "Label", type: "text", required: true},
        {key: "category", label: "Category", type: "text", required: true},
        {key: "description", label: "Description", type: "text"},
        {key: "value_type", label: "Value Type", type: "select", options: ["Text", "Integer", "Decimal", "Boolean", "JSON", "URL", "Duration"]},
        {key: "value", label: "Initial Value", type: "text"},
        {key: "default_value", label: "Default Value", type: "text"},
        {key: "options", label: "Options JSON", type: "json"},
        {key: "is_required", label: "Required", type: "boolean"},
        {key: "is_runtime_editable", label: "Runtime Editable", type: "boolean"},
        {key: "is_active", label: "Active", type: "boolean"},
    ];

    const content = document.getElementById("system-content");
    const tableWrap = document.getElementById("system-table-wrap");
    const table = document.getElementById("system-table");
    const search = document.getElementById("system-search");
    const typeFilter = document.getElementById("system-type-filter");
    const typeFilterWrap = document.getElementById("system-type-filter-wrap");
    const addButton = document.getElementById("system-add");
    const refreshTablesButton = document.getElementById("system-refresh-tables");
    const title = document.getElementById("system-config-title");
    const count = document.getElementById("system-config-count");
    const modal = document.getElementById("system-modal");
    const modalTitle = document.getElementById("system-modal-title");
    const form = document.getElementById("system-form");
    const formFields = document.getElementById("system-form-fields");
    const saveButton = document.getElementById("system-save");

    function csrfToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function escapeHtml(value) {
        return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
    }

    function humanize(value) {
        return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options || {});
        let payload;
        try { payload = await response.json(); } catch (error) { payload = {error: "Invalid server response."}; }
        if (!response.ok || !payload.ok) throw new Error(payload.error || payload.message || "Request failed.");
        return payload;
    }

    function showMessage(message, isError) {
        const box = document.getElementById("system-message");
        document.getElementById("system-message-text").textContent = message;
        box.hidden = false;
        box.setAttribute("aria-hidden", "false");
        box.classList.toggle("error", Boolean(isError));
        box.classList.add("visible");
    }

    function hideMessage() {
        const box = document.getElementById("system-message");
        box.classList.remove("visible", "error");
        box.hidden = true;
        box.setAttribute("aria-hidden", "true");
    }

    function setModalOpen(open) {
        modal.hidden = !open;
        modal.setAttribute("aria-hidden", open ? "false" : "true");
        document.body.classList.toggle("modal-open", open);
    }

    function statusClass(status) {
        if (status === "Connected") return "connected";
        if (status === "Failed") return "failed";
        if (status === "Disabled") return "disabled";
        return "configured";
    }

    function renderLoading(label) {
        content.hidden = false;
        tableWrap.hidden = true;
        content.innerHTML = `<div class="system-loading"><span class="system-spinner"></span>${escapeHtml(label)}</div>`;
    }

    async function loadSchemas() {
        if (state.schemas.length) return;
        const payload = await fetchJson("/system-config/api/integration-schemas/");
        state.schemas = payload.items || [];
        typeFilter.innerHTML = `<option value="">All types</option>${state.schemas.map((schema) => `<option value="${escapeHtml(schema.type)}">${escapeHtml(schema.type)}</option>`).join("")}`;
    }

    function updateToolbar() {
        const titles = {overview: "Overview", integrations: "Connections", parameters: "Runtime Parameters", "database-configs": "Database Servers", "managed-tables": "Managed Tables"};
        title.textContent = titles[state.tab] || "System Config";
        addButton.hidden = !["integrations", "parameters", "database-configs"].includes(state.tab);
        addButton.textContent = state.tab === "integrations" ? "Add Connection" : (state.tab === "parameters" ? "Add Parameter" : "Add Server");
        refreshTablesButton.hidden = state.tab !== "managed-tables";
        typeFilterWrap.hidden = state.tab !== "integrations";
        search.closest("label").hidden = state.tab === "overview";
    }

    async function loadOverview() {
        renderLoading("Loading system readiness...");
        const payload = await fetchJson("/system-config/api/overview/");
        const summary = payload.summary || {};
        count.textContent = summary.connections || 0;
        const connections = payload.connections || [];
        content.innerHTML = `
            <div class="system-kpi-grid">
                ${[["Connections", summary.connections], ["Connected", summary.connected], ["Configured", summary.configured], ["Needs attention", summary.failed], ["Parameters", summary.parameters], ["Managed tables", summary.managed_tables]].map(([label, value]) => `
                    <article class="system-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || 0)}</strong></article>
                `).join("")}
            </div>
            <section class="system-readiness">
                <div class="system-panel-heading"><div><h3>Integration readiness</h3><p>Central connection registry used by this installation.</p></div><button class="button secondary js-open-connections" type="button">Manage connections</button></div>
                <div class="system-readiness-list">
                    ${connections.map((item) => `<div class="system-readiness-row"><span class="system-connector-mark">${escapeHtml(item.integration_type.slice(0, 2).toUpperCase())}</span><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.provider || item.integration_type)}</small></span><span class="system-status ${statusClass(item.status)}">${escapeHtml(item.status)}</span></div>`).join("") || '<p class="empty compact">No connection configured.</p>'}
                </div>
            </section>`;
        content.querySelector(".js-open-connections")?.addEventListener("click", () => switchTab("integrations"));
    }

    function renderIntegrations() {
        count.textContent = state.items.length;
        content.innerHTML = `<div class="system-connection-grid">${state.items.map((item) => `
            <article class="system-connection-card ${item.is_active ? "" : "inactive"}">
                <div class="system-connection-head"><span class="system-connector-mark">${escapeHtml(item.integration_type.slice(0, 2).toUpperCase())}</span><span class="system-status ${statusClass(item.status)}">${escapeHtml(item.status)}</span></div>
                <p class="eyebrow">${escapeHtml(item.integration_type)}</p>
                <h3>${escapeHtml(item.name)}</h3>
                <p>${escapeHtml(item.description || item.provider || "No description")}</p>
                <dl><div><dt>Provider</dt><dd>${escapeHtml(item.provider || "Not set")}</dd></div><div><dt>Secrets</dt><dd>${item.configured_secret_keys.length ? `${item.configured_secret_keys.length} configured` : "None"}</dd></div><div><dt>Last test</dt><dd>${escapeHtml(item.last_verified_at ? new Date(item.last_verified_at).toLocaleString() : "Never")}</dd></div></dl>
                ${item.last_message ? `<p class="system-connection-message">${escapeHtml(item.last_message)}</p>` : ""}
                <div class="system-card-actions"><button type="button" class="button secondary js-edit" data-id="${item.id}">Edit</button><button type="button" class="button secondary js-test" data-id="${item.id}">Test</button>${item.integration_type === "Active Directory" ? `<button type="button" class="button js-ad-sync" data-id="${item.id}" ${item.status === "Connected" ? "" : "disabled"}>Sync users</button>` : ""}<button type="button" class="button tertiary js-deactivate" data-id="${item.id}">${item.is_active ? "Deactivate" : "Disabled"}</button></div>
            </article>`).join("") || '<div class="empty">No connections found.</div>'}</div>`;
        content.querySelectorAll(".js-edit").forEach((button) => button.addEventListener("click", () => openIntegrationForm(state.items.find((item) => String(item.id) === button.dataset.id))));
        content.querySelectorAll(".js-test").forEach((button) => button.addEventListener("click", () => verifyIntegration(button)));
        content.querySelectorAll(".js-ad-sync").forEach((button) => button.addEventListener("click", () => synchronizeActiveDirectory(button)));
        content.querySelectorAll(".js-deactivate").forEach((button) => button.addEventListener("click", () => deactivateIntegration(button)));
    }

    async function loadIntegrations() {
        await loadSchemas();
        renderLoading("Loading connections...");
        const url = new URL("/system-config/api/integrations/", window.location.origin);
        if (search.value.trim()) url.searchParams.set("q", search.value.trim());
        if (typeFilter.value) url.searchParams.set("type", typeFilter.value);
        const payload = await fetchJson(url);
        state.items = payload.items || [];
        renderIntegrations();
    }

    function parameterInput(item) {
        const value = item.value ?? "";
        if (item.options?.length) return `<select data-parameter-input>${item.options.map((option) => `<option ${String(option) === String(value) ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select>`;
        if (item.value_type === "Boolean") return `<label class="system-switch"><input type="checkbox" data-parameter-input ${value ? "checked" : ""}><span></span></label>`;
        if (item.value_type === "JSON") return `<textarea rows="3" data-parameter-input>${escapeHtml(JSON.stringify(value, null, 2))}</textarea>`;
        const type = ["Integer", "Decimal", "Duration"].includes(item.value_type) ? "number" : "text";
        return `<input type="${type}" data-parameter-input value="${escapeHtml(value)}">`;
    }

    function renderParameters() {
        count.textContent = state.items.length;
        const groups = Object.groupBy ? Object.groupBy(state.items, (item) => item.category) : state.items.reduce((result, item) => ((result[item.category] ||= []).push(item), result), {});
        content.innerHTML = Object.entries(groups).map(([category, items]) => `<section class="system-parameter-group"><div class="system-panel-heading"><div><h3>${escapeHtml(category)}</h3><p>${items.length} configurable parameters</p></div></div><div class="system-parameter-list">${items.map((item) => `<article class="system-parameter-row" data-parameter-id="${item.id}" data-value-type="${escapeHtml(item.value_type)}"><div><label>${escapeHtml(item.label)}</label><small>${escapeHtml(item.description || item.key)}</small></div><div class="system-parameter-control">${parameterInput(item)}<button type="button" class="button secondary js-save-parameter">Save</button></div></article>`).join("")}</div></section>`).join("") || '<div class="empty">No parameters found.</div>';
        content.querySelectorAll(".js-save-parameter").forEach((button) => button.addEventListener("click", () => saveParameter(button.closest("[data-parameter-id]"), button)));
    }

    async function loadParameters() {
        renderLoading("Loading runtime parameters...");
        const url = new URL("/system-config/api/parameters/", window.location.origin);
        if (search.value.trim()) url.searchParams.set("q", search.value.trim());
        const payload = await fetchJson(url);
        state.items = payload.items || [];
        renderParameters();
    }

    async function saveParameter(row, button) {
        const input = row.querySelector("[data-parameter-input]");
        const type = row.dataset.valueType;
        let value = input.type === "checkbox" ? input.checked : input.value;
        if (type === "JSON") { try { value = JSON.parse(value); } catch (error) { return showMessage("The JSON value is invalid.", true); } }
        button.disabled = true; button.textContent = "Saving...";
        try {
            await fetchJson(`/system-config/api/parameters/${row.dataset.parameterId}/`, {method: "PUT", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()}, body: JSON.stringify({value})});
            showMessage("Parameter saved.", false);
        } catch (error) { showMessage(error.message, true); }
        finally { button.disabled = false; button.textContent = "Save"; }
    }

    function renderDatabaseTable() {
        const activeColumns = databaseColumns[state.tab];
        count.textContent = state.items.length;
        table.innerHTML = `<thead><tr>${activeColumns.map((column) => `<th>${escapeHtml(humanize(column))}</th>`).join("")}<th>Actions</th></tr></thead><tbody>${state.items.length ? state.items.map((item) => `<tr>${activeColumns.map((column) => `<td>${escapeHtml(typeof item[column] === "object" ? JSON.stringify(item[column]) : (typeof item[column] === "boolean" ? (item[column] ? "Yes" : "No") : item[column] ?? ""))}</td>`).join("")}<td class="row-actions">${state.tab === "database-configs" ? `<button type="button" class="button tertiary js-db-edit" data-id="${item.id}">Edit</button><button type="button" class="button tertiary js-db-test" data-id="${item.id}">Test</button>` : ""}</td></tr>`).join("") : `<tr><td colspan="${activeColumns.length + 1}" class="empty compact">No records found.</td></tr>`}</tbody>`;
        table.querySelectorAll(".js-db-edit").forEach((button) => button.addEventListener("click", () => openDatabaseForm(state.items.find((item) => String(item.id) === button.dataset.id))));
        table.querySelectorAll(".js-db-test").forEach((button) => button.addEventListener("click", () => verifyDatabase(button)));
    }

    async function loadDatabaseItems() {
        content.hidden = true; tableWrap.hidden = false;
        table.innerHTML = '<tbody><tr><td class="empty compact">Loading...</td></tr></tbody>';
        const url = new URL(`/system-config/api/${state.tab}/`, window.location.origin);
        if (search.value.trim()) url.searchParams.set("q", search.value.trim());
        const payload = await fetchJson(url);
        state.items = payload.items || [];
        renderDatabaseTable();
    }

    function fieldHtml(field, value) {
        const required = field.required ? "required" : "";
        const badges = `<span class="field-statuses"><span class="field-status ${field.required ? "is-required" : "is-optional"}">${field.required ? "Required" : "Optional"}</span>${Object.prototype.hasOwnProperty.call(field, "default") ? '<span class="field-status is-prefilled">Prefilled</span>' : ""}</span>`;
        const heading = `<span class="field-label-row"><span>${escapeHtml(field.label)}</span>${badges}</span>`;
        const help = field.help ? `<small class="field-help">${escapeHtml(field.help)}</small>` : "";
        if (field.type === "boolean") return `<label class="inline-check stacked system-config-check"><span class="field-label-row"><span><input name="${field.key}" type="checkbox" ${value ?? field.default ? "checked" : ""}> ${escapeHtml(field.label)}</span>${badges}</span>${help}</label>`;
        if (field.type === "select") return `<label>${heading}<select name="${field.key}" ${required}>${(field.options || []).map((option) => `<option value="${escapeHtml(option)}" ${String(value ?? field.default ?? "") === String(option) ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select>${help}</label>`;
        if (field.type === "json") return `<label class="full-width">${heading}<textarea name="${field.key}" rows="5">${escapeHtml(value && typeof value === "object" ? JSON.stringify(value, null, 2) : value || "{}")}</textarea>${help}</label>`;
        const placeholder = field.secret && value === "********" ? "Configured - enter a value only to replace it" : (field.placeholder || "");
        return `<label>${heading}${field.secret && value === "********" ? '<small class="field-secret-note">Secret is configured</small>' : ""}<input name="${field.key}" type="${field.type === "url" ? "url" : field.type}" value="${field.secret ? "" : escapeHtml(value ?? field.default ?? "")}" placeholder="${escapeHtml(placeholder)}" ${required && value !== "********" ? "required" : ""}>${help}</label>`;
    }

    function integrationBaseFields(item) {
        return `<label>Name<input name="name" type="text" value="${escapeHtml(item?.name || "")}" required></label><label>Code<input name="code" type="text" value="${escapeHtml(item?.code || "")}" required ${item ? "readonly" : ""}></label><label>Connection type<select name="integration_type" ${item ? "disabled" : ""}>${state.schemas.map((schema) => `<option value="${escapeHtml(schema.type)}" ${schema.type === (item?.integration_type || "Power BI") ? "selected" : ""}>${escapeHtml(schema.type)}</option>`).join("")}</select></label><label>Provider<input name="provider" type="text" value="${escapeHtml(item?.provider || "")}"></label><label class="full-width">Description<textarea name="description" rows="2">${escapeHtml(item?.description || "")}</textarea></label><label class="inline-check stacked"><input name="is_default" type="checkbox" ${item?.is_default ? "checked" : ""}> Default connection</label><label class="inline-check stacked"><input name="is_active" type="checkbox" ${item ? (item.is_active ? "checked" : "") : "checked"}> Active</label><div class="full-width system-form-divider"><span>Connection settings</span></div>`;
    }

    function renderIntegrationFields(item, type) {
        const schema = state.schemas.find((candidate) => candidate.type === type) || {fields: []};
        const settings = item?.settings || {};
        let previousGroup = "";
        const connectionFields = schema.fields.map((field) => {
            const group = field.group || "";
            const divider = group && group !== previousGroup ? `<div class="full-width system-form-divider system-field-group"><span>${escapeHtml(group)}</span></div>` : "";
            previousGroup = group;
            return divider + fieldHtml(field, settings[field.key]);
        }).join("");
        const legend = `<div class="full-width field-status-legend"><span><strong>Required</strong> must be supplied</span><span><strong>Optional</strong> may be left empty</span><span><strong>Prefilled</strong> has a safe default to verify</span></div>`;
        const adChecklist = type === "Active Directory" ? `<div class="full-width ad-live-checklist"><strong>Live test order</strong><span>1. Save with AD authentication disabled</span><span>2. Test the encrypted connection and authorized group</span><span>3. Sync users</span><span>4. Validate one standard account, then enable AD authentication</span></div>` : "";
        formFields.innerHTML = integrationBaseFields(item) + legend + adChecklist + connectionFields;
        form.querySelector("[name=integration_type]")?.addEventListener("change", (event) => renderIntegrationFields(null, event.target.value));
    }

    function openIntegrationForm(item) {
        state.formMode = "integration"; state.editingItem = item || null;
        modalTitle.textContent = item ? "Edit Connection" : "Add Connection";
        renderIntegrationFields(item, item?.integration_type || typeFilter.value || "Power BI");
        setModalOpen(true);
    }

    function openDatabaseForm(item) {
        state.formMode = "database"; state.editingItem = item || null;
        modalTitle.textContent = item ? "Edit Database Server" : "Add Database Server";
        formFields.innerHTML = databaseFields.map((field) => fieldHtml(field, item?.[field.key])).join("");
        setModalOpen(true);
    }

    function openParameterForm() {
        state.formMode = "parameter"; state.editingItem = null;
        modalTitle.textContent = "Add Runtime Parameter";
        const defaults = {value_type: "Text", options: [], is_runtime_editable: true, is_active: true};
        formFields.innerHTML = parameterFields.map((field) => fieldHtml(field, defaults[field.key])).join("");
        setModalOpen(true);
    }

    function collectFields(fields, container) {
        const result = {};
        fields.forEach((field) => {
            const input = container.querySelector(`[name="${field.key}"]`);
            if (!input) return;
            if (field.type === "boolean") result[field.key] = input.checked;
            else if (field.type === "json") { try { result[field.key] = input.value.trim() ? JSON.parse(input.value) : {}; } catch (error) { throw new Error(`${field.label} must be valid JSON.`); } }
            else result[field.key] = input.value;
        });
        return result;
    }

    function collectIntegrationPayload() {
        const typeInput = form.querySelector("[name=integration_type]");
        const integrationType = typeInput.value;
        const schema = state.schemas.find((candidate) => candidate.type === integrationType) || {fields: []};
        return {name: form.elements.name.value, code: form.elements.code.value, integration_type: integrationType, provider: form.elements.provider.value, description: form.elements.description.value, is_default: form.elements.is_default.checked, is_active: form.elements.is_active.checked, settings: collectFields(schema.fields, form)};
    }

    async function verifyIntegration(button) {
        const original = button.textContent; button.disabled = true; button.textContent = "Testing...";
        try { const payload = await fetchJson(`/system-config/api/integrations/${button.dataset.id}/verify/`, {method: "POST", headers: {"X-CSRFToken": csrfToken()}}); showMessage(payload.message || "Connection successful.", false); }
        catch (error) { showMessage(error.message, true); }
        finally { button.disabled = false; button.textContent = original; await loadIntegrations(); }
    }

    async function synchronizeActiveDirectory(button) {
        if (!confirm("Synchronize authorized Active Directory users and groups now?")) return;
        const original = button.textContent; button.disabled = true; button.textContent = "Synchronizing...";
        try {
            const payload = await fetchJson(`/system-config/api/integrations/${button.dataset.id}/sync-active-directory/`, {method: "POST", headers: {"X-CSRFToken": csrfToken()}});
            showMessage(payload.message || "Active Directory synchronization completed.", false);
        } catch (error) { showMessage(error.message, true); }
        finally { button.disabled = false; button.textContent = original; await loadIntegrations(); }
    }

    async function deactivateIntegration(button) {
        if (button.textContent.trim() === "Disabled" || !confirm("Deactivate this connection?")) return;
        try { await fetchJson(`/system-config/api/integrations/${button.dataset.id}/`, {method: "DELETE", headers: {"X-CSRFToken": csrfToken()}}); await loadIntegrations(); }
        catch (error) { showMessage(error.message, true); }
    }

    async function verifyDatabase(button) {
        button.disabled = true;
        try { const payload = await fetchJson(`/system-config/api/database-configs/${button.dataset.id}/verify/`, {method: "POST", headers: {"X-CSRFToken": csrfToken()}}); showMessage(payload.message || "Connection successful.", false); }
        catch (error) { showMessage(error.message, true); }
        finally { button.disabled = false; await loadDatabaseItems(); }
    }

    async function loadCurrentTab() {
        updateToolbar();
        try {
            if (state.tab === "overview") await loadOverview();
            else if (state.tab === "integrations") await loadIntegrations();
            else if (state.tab === "parameters") await loadParameters();
            else await loadDatabaseItems();
        } catch (error) { content.hidden = false; tableWrap.hidden = true; content.innerHTML = `<div class="system-error">${escapeHtml(error.message)}</div>`; }
    }

    async function switchTab(tabName) {
        state.tab = tabName;
        document.querySelectorAll("#system-tabs .ia-tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === tabName));
        await loadCurrentTab();
    }

    document.querySelectorAll("#system-tabs .ia-tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
    addButton.addEventListener("click", async () => {
        if (state.tab === "integrations") { await loadSchemas(); openIntegrationForm(null); }
        else if (state.tab === "parameters") openParameterForm();
        else openDatabaseForm(null);
    });
    document.getElementById("system-refresh").addEventListener("click", loadCurrentTab);
    refreshTablesButton.addEventListener("click", async () => { try { const payload = await fetchJson("/system-config/api/managed-tables/", {method: "POST", headers: {"X-CSRFToken": csrfToken()}}); showMessage(`Managed tables refreshed: ${payload.refreshed}`, false); await loadCurrentTab(); } catch (error) { showMessage(error.message, true); } });
    search.addEventListener("input", () => { clearTimeout(search._timer); search._timer = setTimeout(loadCurrentTab, 300); });
    typeFilter.addEventListener("change", loadCurrentTab);
    document.querySelectorAll("[data-system-modal-close]").forEach((button) => button.addEventListener("click", () => setModalOpen(false)));
    document.getElementById("system-message-ok").addEventListener("click", hideMessage);
    form.addEventListener("submit", async (event) => {
        event.preventDefault(); saveButton.disabled = true; saveButton.textContent = "Saving...";
        try {
            const item = state.editingItem;
            if (state.formMode === "integration") {
                const payload = collectIntegrationPayload();
                await fetchJson(`/system-config/api/integrations/${item ? `${item.id}/` : ""}`, {method: item ? "PUT" : "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()}, body: JSON.stringify(payload)});
            } else if (state.formMode === "database") {
                const payload = collectFields(databaseFields, form);
                await fetchJson(`/system-config/api/database-configs/${item ? `${item.id}/` : ""}`, {method: item ? "PUT" : "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()}, body: JSON.stringify(payload)});
            } else {
                const payload = collectFields(parameterFields, form);
                await fetchJson("/system-config/api/parameters/", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()}, body: JSON.stringify(payload)});
            }
            setModalOpen(false); showMessage("Configuration saved.", false); await loadCurrentTab();
        } catch (error) { showMessage(error.message, true); }
        finally { saveButton.disabled = false; saveButton.textContent = "Save"; }
    });

    loadCurrentTab();
}());
