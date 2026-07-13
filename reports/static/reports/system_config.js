(function () {
    const root = document.querySelector("[data-system-config-root]");
    if (!root) return;

    const state = {
        tab: "database-configs",
        items: [],
        editingItem: null,
    };

    const columns = {
        "database-configs": ["name", "engine", "host", "port", "database_name", "username", "driver", "last_status", "is_default", "is_active"],
        "managed-tables": ["database_config_name", "schema_name", "table_name", "category", "model_name", "row_count", "last_synced_at", "is_active"],
    };

    const fields = [
        ["name", "Name", "text"],
        ["engine", "Engine", "select", ["SQL Server", "Snowflake", "SQLite", "Other"]],
        ["purpose", "Purpose", "text"],
        ["host", "Host / Server", "text"],
        ["port", "Port", "number"],
        ["database_name", "Database", "text"],
        ["schema_name", "Default Schema", "text"],
        ["username", "User", "text"],
        ["password", "Password", "password"],
        ["driver", "Driver", "text"],
        ["connection_options", "Connection Options JSON", "json"],
        ["is_default", "Default", "checkbox"],
        ["is_active", "Active", "checkbox"],
    ];

    const table = document.getElementById("system-table");
    const search = document.getElementById("system-search");
    const addButton = document.getElementById("system-add");
    const refreshTablesButton = document.getElementById("system-refresh-tables");
    const title = document.getElementById("system-config-title");
    const count = document.getElementById("system-config-count");
    const modal = document.getElementById("system-modal");
    const form = document.getElementById("system-form");
    const formFields = document.getElementById("system-form-fields");

    function csrfToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options || {});
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "Request failed.");
        return payload;
    }

    function showMessage(message, isError) {
        const box = document.getElementById("system-message");
        const text = document.getElementById("system-message-text");
        text.textContent = message;
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

    function formatValue(value) {
        if (typeof value === "boolean") return value ? "Yes" : "No";
        if (value && typeof value === "object") return JSON.stringify(value);
        return value ?? "";
    }

    function renderTable() {
        const activeColumns = columns[state.tab];
        count.textContent = state.items.length;
        table.innerHTML = `
            <thead><tr>${activeColumns.map((column) => `<th>${escapeHtml(column.replaceAll("_", " "))}</th>`).join("")}<th>Actions</th></tr></thead>
            <tbody>
                ${state.items.length ? state.items.map((item) => `
                    <tr>
                        ${activeColumns.map((column) => `<td>${escapeHtml(formatValue(item[column]))}</td>`).join("")}
                        <td class="row-actions">
                            ${state.tab === "database-configs" ? `
                                <button type="button" class="icon-action js-edit" data-id="${item.id}" title="Edit"></button>
                                <button type="button" class="icon-action js-verify" data-id="${item.id}" title="Verify connection"></button>
                                <button type="button" class="icon-action delete-action js-delete" data-id="${item.id}" title="Deactivate"></button>
                            ` : ""}
                        </td>
                    </tr>
                `).join("") : `<tr><td colspan="${activeColumns.length + 1}" class="empty compact">No records found.</td></tr>`}
            </tbody>
        `;
        table.querySelectorAll(".js-edit").forEach((button) => {
            button.addEventListener("click", () => {
                const item = state.items.find((candidate) => String(candidate.id) === String(button.dataset.id));
                if (item) openForm(item);
            });
        });
        table.querySelectorAll(".js-delete").forEach((button) => {
            button.addEventListener("click", async () => {
                if (!confirm("Deactivate this server configuration?")) return;
                try {
                    await fetchJson(`/system-config/api/database-configs/${button.dataset.id}/`, {
                        method: "DELETE",
                        headers: {"X-CSRFToken": csrfToken(), "Accept": "application/json"},
                    });
                    showMessage("Server configuration deactivated.", false);
                    await loadItems();
                } catch (error) {
                    showMessage(error.message, true);
                }
            });
        });
        table.querySelectorAll(".js-verify").forEach((button) => {
            button.addEventListener("click", async () => {
                try {
                    const payload = await fetchJson(`/system-config/api/database-configs/${button.dataset.id}/verify/`, {
                        method: "POST",
                        headers: {"X-CSRFToken": csrfToken(), "Accept": "application/json"},
                    });
                    showMessage(payload.message || "Connection successful.", false);
                    await loadItems();
                } catch (error) {
                    showMessage(error.message, true);
                    await loadItems();
                }
            });
        });
    }

    function updateToolbar() {
        const databaseTab = state.tab === "database-configs";
        title.textContent = databaseTab ? "Database Servers" : "Managed Tables";
        addButton.hidden = !databaseTab;
        refreshTablesButton.hidden = databaseTab;
    }

    async function loadItems() {
        updateToolbar();
        const url = new URL(`/system-config/api/${state.tab}/`, window.location.origin);
        if (search.value.trim()) url.searchParams.set("q", search.value.trim());
        table.innerHTML = `<tbody><tr><td class="empty compact">Loading...</td></tr></tbody>`;
        try {
            const payload = await fetchJson(url.toString());
            state.items = payload.items || [];
            renderTable();
        } catch (error) {
            table.innerHTML = `<tbody><tr><td class="empty compact">${escapeHtml(error.message)}</td></tr></tbody>`;
        }
    }

    function fieldHtml([name, label, type, options], value) {
        if (type === "checkbox") {
            const checked = value === undefined ? false : Boolean(value);
            return `<label class="inline-check stacked"><input name="${name}" type="checkbox" ${checked ? "checked" : ""}> ${escapeHtml(label)}</label>`;
        }
        if (type === "select") {
            return `<label>${escapeHtml(label)}<select name="${name}">${options.map((option) => `<option value="${escapeHtml(option)}" ${String(value || "") === option ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select></label>`;
        }
        if (type === "json") {
            const display = value && typeof value === "object" ? JSON.stringify(value, null, 2) : value || "{}";
            return `<label class="full-width">${escapeHtml(label)}<textarea name="${name}" rows="8">${escapeHtml(display)}</textarea></label>`;
        }
        if (type === "number") {
            return `<label>${escapeHtml(label)}<input name="${name}" type="number" value="${escapeHtml(value ?? "")}"></label>`;
        }
        return `<label>${escapeHtml(label)}<input name="${name}" type="${type}" value="${escapeHtml(value || "")}"></label>`;
    }

    function openForm(item) {
        state.editingItem = item || null;
        formFields.innerHTML = fields.map((field) => fieldHtml(field, item ? item[field[0]] : undefined)).join("");
        setModalOpen(true);
    }

    function collectPayload() {
        const payload = {};
        for (const [name, label, type] of fields) {
            const input = form.querySelector(`[name="${name}"]`);
            if (!input) continue;
            if (type === "checkbox") payload[name] = input.checked;
            else if (type === "json") {
                try {
                    payload[name] = input.value.trim() ? JSON.parse(input.value) : {};
                } catch (error) {
                    throw new Error(`${label} must be valid JSON.`);
                }
            } else payload[name] = input.value;
        }
        return payload;
    }

    document.querySelectorAll("#system-tabs .ia-tab").forEach((tab) => {
        tab.addEventListener("click", async () => {
            state.tab = tab.dataset.tab;
            document.querySelectorAll("#system-tabs .ia-tab").forEach((item) => item.classList.toggle("active", item === tab));
            await loadItems();
        });
    });
    addButton.addEventListener("click", () => openForm(null));
    document.getElementById("system-refresh").addEventListener("click", loadItems);
    refreshTablesButton.addEventListener("click", async () => {
        try {
            const payload = await fetchJson("/system-config/api/managed-tables/", {
                method: "POST",
                headers: {"X-CSRFToken": csrfToken(), "Accept": "application/json"},
            });
            showMessage(`Managed tables refreshed: ${payload.refreshed}`, false);
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        }
    });
    search.addEventListener("keyup", () => {
        clearTimeout(search._timer);
        search._timer = setTimeout(loadItems, 250);
    });
    document.querySelectorAll("[data-system-modal-close]").forEach((button) => button.addEventListener("click", () => setModalOpen(false)));
    document.getElementById("system-message-ok").addEventListener("click", hideMessage);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const payload = collectPayload();
            const item = state.editingItem;
            await fetchJson(`/system-config/api/database-configs/${item ? `${item.id}/` : ""}`, {
                method: item ? "PUT" : "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify(payload),
            });
            setModalOpen(false);
            showMessage("Server configuration saved.", false);
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    loadItems();
}());
