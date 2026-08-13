(function () {
    const root = document.querySelector("[data-ia-config-root]");
    if (!root) {
        return;
    }

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

    function readSections() {
        const script = document.getElementById("ia-config-sections-data");
        if (!script) {
            return [];
        }
        try {
            const value = JSON.parse(script.textContent || "[]");
            return Array.isArray(value) ? value : [];
        } catch (error) {
            return [];
        }
    }

    const state = {
        sections: readSections(),
        sectionCode: "",
        resourceType: "question-examples",
        items: [],
        editingItem: null,
        isAdmin: root.dataset.isAdmin === "1",
    };

    const resourceConfig = {
        "response-templates": {
            title: "Response Templates",
            columns: ["code", "name", "primary_component", "version", "validation_status", "active"],
            fields: [
                ["code", "Code", "text"], ["name", "Name", "text"],
                ["description", "Description", "textarea"], ["domain", "Domain", "text"],
                ["primary_component", "Primary component", "text"],
                ["component_order_json", "Component order", "json"],
                ["required_data_fields_json", "Required data fields", "json"],
                ["fallback_template_code", "Fallback template", "text"],
                ["version", "Version", "text"],
                ["validation_status", "Validation", "select", ["Draft", "To Review", "Validated", "Rejected"]],
                ["active", "Active", "checkbox"],
            ],
        },
        "intent-template-mappings": {
            title: "Intent-to-Template Mapping",
            columns: ["intent_type", "scope_type", "metric_code", "response_template", "priority", "validation_status", "active"],
            fields: [
                ["domain", "Domain", "text"], ["intent_type", "Intent type", "text"],
                ["scope_type", "Scope type", "text"], ["metric_code", "Metric code", "text"],
                ["response_template", "Response template code", "text"], ["priority", "Priority", "number"],
                ["validation_status", "Validation", "select", ["Draft", "To Review", "Validated", "Rejected"]],
                ["active", "Active", "checkbox"],
            ],
        },
        "question-examples": {
            title: "Question Examples",
            columns: ["question_text", "language", "is_active"],
            fields: [
                ["question_text", "Question text", "textarea"],
                ["language", "Language", "text"],
                ["expected_json_intent", "Expected JSON Intent", "json"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "synonyms": {
            title: "Synonyms",
            columns: ["entity_type", "canonical_value", "synonym_value", "language", "is_active"],
            fields: [
                ["entity_type", "Entity type", "select", ["metric", "minesite", "model", "family", "period", "customer", "component", "measure", "field"]],
                ["canonical_value", "Canonical value", "text"],
                ["synonym_value", "Synonym value", "text"],
                ["language", "Language", "text"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        metrics: {
            title: "Metrics Mapping",
            columns: ["metric_code", "metric_label", "powerbi_measure_name", "is_active"],
            fields: [
                ["metric_code", "Metric code", "text"],
                ["metric_label", "Metric label", "text"],
                ["powerbi_measure_name", "Power BI measure name", "text"],
                ["description", "Description", "textarea"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        filters: {
            title: "Filters Mapping",
            columns: ["filter_code", "filter_label", "powerbi_table_name", "powerbi_column_name", "data_type", "is_required", "is_active"],
            fields: [
                ["filter_code", "Filter code", "text"],
                ["filter_label", "Filter label", "text"],
                ["powerbi_table_name", "Power BI table name", "text"],
                ["powerbi_column_name", "Power BI column name", "text"],
                ["data_type", "Data type", "select", ["Text", "Integer", "Decimal", "Date", "DateTime", "Boolean"]],
                ["is_required", "Required", "checkbox"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "dax-templates": {
            title: "DAX Templates",
            columns: ["template_name", "template_code", "is_active"],
            fields: [
                ["template_name", "Template name", "text"],
                ["template_code", "Template code", "text"],
                ["dax_template", "DAX template", "textarea"],
                ["description", "Description", "textarea"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "semantic-tables": {
            title: "Semantic Tables",
            columns: ["table_name", "display_name", "description", "is_active"],
            fields: [
                ["table_name", "Table Name", "text"],
                ["display_name", "Display Name", "text"],
                ["description", "Description", "textarea"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "semantic-columns": {
            title: "Semantic Columns",
            columns: ["table_name", "column_name", "display_name", "data_type", "is_filter", "is_active"],
            fields: [
                ["table_name", "Table", "text"],
                ["column_name", "Column Name", "text"],
                ["display_name", "Display Name", "text"],
                ["data_type", "Data Type", "select", ["Text", "Integer", "Decimal", "Date", "DateTime", "Boolean", "Currency", "Percentage", "Unknown"]],
                ["description", "Description", "textarea"],
                ["is_filter", "Is Filter", "checkbox"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "semantic-measures": {
            title: "Semantic Measures",
            columns: ["measure_name", "display_name", "dax_name", "unit", "category", "is_active"],
            fields: [
                ["measure_name", "Measure Name", "text"],
                ["display_name", "Display Name", "text"],
                ["description", "Description", "textarea"],
                ["dax_name", "DAX Name", "text"],
                ["unit", "Unit", "text"],
                ["category", "Category", "text"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "semantic-relationships": {
            title: "Semantic Relationships",
            columns: ["parent_table", "parent_column", "child_table", "child_column", "relationship_type", "is_active"],
            fields: [
                ["parent_table", "Parent Table", "text"],
                ["parent_column", "Parent Column", "text"],
                ["child_table", "Child Table", "text"],
                ["child_column", "Child Column", "text"],
                ["relationship_type", "Relationship Type", "text"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "business-vocabulary": {
            title: "Business Vocabulary",
            columns: ["business_term", "category", "business_definition", "is_active"],
            fields: [
                ["business_term", "Business Term", "text"],
                ["business_definition", "Business Definition", "textarea"],
                ["category", "Category", "text"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "few-shot-examples": {
            title: "Few Shot Examples",
            columns: ["question", "expected_response", "is_active"],
            fields: [
                ["question", "Question", "textarea"],
                ["expected_json_intent", "Expected JSON Intent", "json"],
                ["expected_dax", "Expected DAX", "textarea"],
                ["expected_response", "Expected Response", "textarea"],
                ["explanation", "Explanation", "textarea"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "prompt-templates": {
            title: "Prompt Templates",
            columns: ["prompt_type", "template_name", "description", "is_active"],
            fields: [
                ["prompt_type", "Prompt Type", "select", ["intent_extraction", "response_generation", "business_explanation", "recommendation", "executive_summary", "comparison", "trend_analysis"]],
                ["template_name", "Template Name", "text"],
                ["prompt_template", "Prompt Template", "textarea"],
                ["description", "Description", "textarea"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "business-rules": {
            title: "Business Rules",
            columns: ["metric_code", "rule_name", "condition", "action", "priority", "is_active"],
            fields: [
                ["metric_code", "Metric", "text"],
                ["rule_name", "Rule Name", "text"],
                ["condition", "Condition", "textarea"],
                ["action", "Action", "textarea"],
                ["default_value", "Default Value", "text"],
                ["priority", "Priority", "number"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "powerbi-pages": {
            title: "Power BI Pages",
            columns: ["page_name", "report_name", "page_display_name", "is_default_page", "is_active"],
            fields: [
                ["page_name", "Page Name", "text"],
                ["report_name", "Report Name", "text"],
                ["report_id", "Report ID", "text"],
                ["page_display_name", "Page Display Name", "text"],
                ["description", "Description", "textarea"],
                ["is_default_page", "Default Page", "checkbox"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "visual-mapping": {
            title: "Visual Mapping",
            columns: ["metric_code", "recommended_visual", "priority", "is_active"],
            fields: [
                ["metric_code", "Metric", "text"],
                ["recommended_visual", "Recommended Visual", "select", ["Gauge", "Line Chart", "Trend", "Stacked Bar", "Table", "Card", "Matrix", "Scatter", "Map"]],
                ["description", "Description", "textarea"],
                ["priority", "Priority", "number"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "kpi-targets": {
            title: "KPI Targets",
            columns: ["metric_code", "target", "warning_threshold", "critical_threshold", "unit", "is_active"],
            fields: [
                ["metric_code", "Metric", "text"],
                ["target", "Target", "number"],
                ["warning_threshold", "Warning Threshold", "number"],
                ["critical_threshold", "Critical Threshold", "number"],
                ["unit", "Unit", "text"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "recommended-actions": {
            title: "Recommended Actions",
            columns: ["metric_code", "condition", "recommendations", "priority", "is_active"],
            fields: [
                ["metric_code", "Metric", "text"],
                ["condition", "Condition", "text"],
                ["recommendations", "Recommendations", "textarea"],
                ["priority", "Priority", "number"],
                ["is_active", "Active", "checkbox"],
            ],
        },
        "debug-runs": {
            title: "Debug Center",
            readonly: true,
            columns: ["created_at", "question_text", "detected_section", "execution_time_ms", "errors"],
            fields: [
                ["question_text", "Original Question", "textarea"],
                ["detected_section", "Detected Section", "text"],
                ["extracted_intent", "Extracted Intent", "json"],
                ["generated_dax", "Generated DAX", "textarea"],
                ["powerbi_response", "Power BI Response", "json"],
                ["formatted_response", "Formatted Response", "textarea"],
                ["execution_time_ms", "Execution Time", "number"],
                ["token_usage", "Token Usage", "json"],
                ["errors", "Errors", "textarea"],
            ],
        },
    };

    const table = document.getElementById("ia-resource-table");
    const sectionTitle = document.getElementById("ia-active-section-title");
    const searchInput = document.getElementById("ia-resource-search");
    const activeSelect = document.getElementById("ia-resource-active");
    const modal = document.getElementById("ia-config-modal");
    const form = document.getElementById("ia-config-form");
    const formFields = document.getElementById("ia-config-form-fields");
    const modalTitle = document.getElementById("ia-modal-title");
    const centerMessage = document.getElementById("ia-center-message");
    const centerText = document.getElementById("ia-center-message-text");
    const addButton = document.getElementById("ia-add-item");
    const importButton = document.getElementById("ia-import-semantic");

    function showMessage(message, isError) {
        if (!centerMessage || !centerText) {
            window.alert(message);
            return;
        }
        centerText.textContent = message;
        centerMessage.hidden = false;
        centerMessage.setAttribute("aria-hidden", "false");
        centerMessage.classList.toggle("error", Boolean(isError));
        centerMessage.classList.add("visible");
    }

    function hideMessage() {
        if (!centerMessage) {
            return;
        }
        centerMessage.classList.remove("visible", "error");
        centerMessage.hidden = true;
        centerMessage.setAttribute("aria-hidden", "true");
    }

    function setModalOpen(isOpen) {
        if (!modal) {
            return;
        }
        modal.hidden = !isOpen;
        modal.setAttribute("aria-hidden", isOpen ? "false" : "true");
        document.body.classList.toggle("modal-open", isOpen);
    }

    function apiUrl(resourceType, itemId) {
        const base = root.dataset.apiBase || "/ia-config/api";
        let url = `${base}/${state.sectionCode}/${resourceType}/`;
        if (itemId) {
            url += `${itemId}/`;
        }
        return url;
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options || {});
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
            throw new Error(payload.error || "Request failed.");
        }
        return payload;
    }

    function formatValue(value) {
        if (typeof value === "boolean") {
            return value ? "Yes" : "No";
        }
        if (value && typeof value === "object") {
            return JSON.stringify(value);
        }
        return value ?? "";
    }

    function renderTable() {
        if (!table) {
            return;
        }
        const config = resourceConfig[state.resourceType];
        const columns = config.columns;
        const head = `
            <thead>
                <tr>
                    ${columns.map((column) => `<th>${escapeHtml(column.replaceAll("_", " "))}</th>`).join("")}
                    <th>Actions</th>
                </tr>
            </thead>
        `;
        const body = state.items.length
            ? state.items.map((item) => `
                <tr>
                    ${columns.map((column) => `<td>${escapeHtml(formatValue(item[column]))}</td>`).join("")}
                    <td class="row-actions">
                        <button type="button" class="icon-action js-ia-edit" data-id="${item.id}" aria-label="${config.readonly ? "View" : "Edit"}" title="${config.readonly ? "View" : "Edit"}"></button>
                        ${config.readonly ? "" : `<button type="button" class="icon-action delete-action js-ia-delete" data-id="${item.id}" aria-label="Delete" title="Delete"></button>`}
                    </td>
                </tr>
            `).join("")
            : `<tr><td colspan="${columns.length + 1}" class="empty compact">No records found.</td></tr>`;
        table.innerHTML = `${head}<tbody>${body}</tbody>`;
        bindRowActions();
        updateToolbarState();
    }

    function renderSections() {
        const testSection = document.getElementById("ia-test-section");
        if (testSection) {
            testSection.innerHTML = `<option value="">Auto</option>` + state.sections.map((section) => (
                `<option value="${escapeHtml(section.code)}">${escapeHtml(section.name)}</option>`
            )).join("");
        }
        if (!state.sectionCode && state.sections.length) {
            state.sectionCode = state.sections[0].code;
        }
        document.querySelectorAll(".js-ia-section-card").forEach((card) => {
            card.classList.toggle("active", card.dataset.sectionCode === state.sectionCode);
        });
        const active = state.sections.find((section) => section.code === state.sectionCode);
        if (sectionTitle && active) {
            sectionTitle.textContent = active.name;
        }
    }

    function updateToolbarState() {
        const config = resourceConfig[state.resourceType] || {};
        const isSemantic = state.resourceType.startsWith("semantic-");
        if (addButton) {
            addButton.hidden = Boolean(config.readonly);
        }
        if (importButton) {
            importButton.hidden = !isSemantic;
        }
    }

    async function loadItems() {
        if (!state.sectionCode) {
            renderTable();
            return;
        }
        const target = new URL(apiUrl(state.resourceType), window.location.origin);
        if (searchInput && searchInput.value.trim()) {
            target.searchParams.set("q", searchInput.value.trim());
        }
        if (activeSelect && activeSelect.value) {
            target.searchParams.set("active", activeSelect.value);
        }
        table.innerHTML = `<tbody><tr><td class="empty compact">Loading...</td></tr></tbody>`;
        try {
            const payload = await fetchJson(target.toString(), {
                headers: {"Accept": "application/json"},
            });
            state.items = payload.items || [];
            renderTable();
        } catch (error) {
            table.innerHTML = `<tbody><tr><td class="empty compact">${escapeHtml(error.message)}</td></tr></tbody>`;
        }
    }

    function fieldHtml(name, label, type, options, value) {
        const id = `ia-field-${name}`;
        if (type === "checkbox") {
            const checked = value === undefined ? true : Boolean(value);
            return `<label class="inline-check stacked"><input id="${id}" name="${name}" type="checkbox" ${checked ? "checked" : ""}> ${escapeHtml(label)}</label>`;
        }
        if (type === "select") {
            return `
                <label>
                    ${escapeHtml(label)}
                    <select id="${id}" name="${name}">
                        ${(options || []).map((option) => `<option value="${escapeHtml(option)}" ${String(value || "") === option ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}
                    </select>
                </label>
            `;
        }
        if (type === "number") {
            return `<label>${escapeHtml(label)}<input id="${id}" name="${name}" type="number" step="any" value="${escapeHtml(value ?? "")}"></label>`;
        }
        if (type === "textarea" || type === "json") {
            const display = type === "json" && value && typeof value === "object"
                ? JSON.stringify(value, null, 2)
                : value || "";
            return `<label class="full-width">${escapeHtml(label)}<textarea id="${id}" name="${name}" rows="${type === "json" ? 10 : 6}">${escapeHtml(display)}</textarea></label>`;
        }
        return `<label>${escapeHtml(label)}<input id="${id}" name="${name}" type="text" value="${escapeHtml(value || "")}"></label>`;
    }

    function openForm(item) {
        state.editingItem = item || null;
        const config = resourceConfig[state.resourceType];
        if (modalTitle) {
            modalTitle.textContent = `${item ? "Edit" : "Create"} ${config.title}`;
        }
        formFields.innerHTML = config.fields.map(([name, label, type, options]) => (
            fieldHtml(name, label, type, options, item ? item[name] : undefined)
        )).join("");
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            field.disabled = Boolean(config.readonly);
        });
        const saveButton = document.getElementById("ia-save-item");
        if (saveButton) {
            saveButton.hidden = Boolean(config.readonly);
        }
        setModalOpen(true);
    }

    function collectFormPayload() {
        const config = resourceConfig[state.resourceType];
        const payload = {};
        config.fields.forEach(([name, label, type]) => {
            const field = form.querySelector(`[name="${name}"]`);
            if (!field) {
                return;
            }
            if (type === "checkbox") {
                payload[name] = field.checked;
            } else if (type === "json") {
                try {
                    payload[name] = field.value.trim() ? JSON.parse(field.value) : {};
                } catch (error) {
                    throw new Error(`${label} must be valid JSON.`);
                }
            } else {
                payload[name] = field.value;
            }
        });
        return payload;
    }

    function bindRowActions() {
        table.querySelectorAll(".js-ia-edit").forEach((button) => {
            button.addEventListener("click", () => {
                const item = state.items.find((candidate) => String(candidate.id) === String(button.dataset.id));
                if (item) {
                    openForm(item);
                }
            });
        });
        table.querySelectorAll(".js-ia-delete").forEach((button) => {
            button.addEventListener("click", async () => {
                if (!window.confirm("Delete this configuration item?")) {
                    return;
                }
                try {
                    await fetchJson(apiUrl(state.resourceType, button.dataset.id), {
                        method: "DELETE",
                        headers: {
                            "X-CSRFToken": csrfToken(),
                            "Accept": "application/json",
                        },
                    });
                    showMessage("Item deleted.", false);
                    await loadItems();
                } catch (error) {
                    showMessage(error.message, true);
                }
            });
        });
    }

    async function importSemanticModel() {
        if (!state.sectionCode) {
            showMessage("Select a section first.", true);
            return;
        }
        const datasetName = window.prompt("Power BI dataset name", "FPR Global DB + RLS");
        if (!datasetName) {
            return;
        }
        importButton.disabled = true;
        importButton.textContent = "Importing...";
        try {
            const payload = await fetchJson(`/ia-config/api/${state.sectionCode}/import-semantic-model/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                    "Accept": "application/json",
                },
                body: JSON.stringify({dataset_name: datasetName}),
            });
            const imported = payload.imported || {};
            const errorCount = Object.keys(payload.errors || {}).length;
            showMessage(
                `Import completed. Tables: ${imported.tables || 0}, Columns: ${imported.columns || 0}, Measures: ${imported.measures || 0}, Relationships: ${imported.relationships || 0}.${errorCount ? ` ${errorCount} Power BI API errors returned.` : ""}`,
                Boolean(errorCount)
            );
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        } finally {
            importButton.disabled = false;
            importButton.textContent = "Import Semantic Model";
        }
    }

    async function runIntentTest() {
        const question = document.getElementById("ia-test-question");
        const section = document.getElementById("ia-test-section");
        const intentOut = document.getElementById("ia-test-intent");
        const daxOut = document.getElementById("ia-test-dax");
        const validationOut = document.getElementById("ia-test-validation");
        const status = document.getElementById("ia-test-status");
        if (!question || !question.value.trim()) {
            showMessage("Question is required.", true);
            return;
        }
        if (status) {
            status.hidden = false;
            status.textContent = "Testing intent...";
        }
        try {
            const payload = await fetchJson("/ia-config/api/test-intent/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                    "Accept": "application/json",
                },
                body: JSON.stringify({
                    question_text: question.value.trim(),
                    section_code: section ? section.value : "",
                }),
            });
            if (intentOut) intentOut.textContent = JSON.stringify(payload.intent || {}, null, 2);
            if (daxOut) daxOut.textContent = payload.dax || "";
            if (validationOut) validationOut.textContent = JSON.stringify(payload.validation || {}, null, 2);
            if (status) {
                status.textContent = payload.validation && payload.validation.valid ? "Validation OK" : "Validation failed";
                status.classList.toggle("error", !(payload.validation && payload.validation.valid));
            }
        } catch (error) {
            if (status) {
                status.hidden = false;
                status.textContent = error.message;
                status.classList.add("error");
            }
        }
    }

    document.querySelectorAll(".js-ia-section-card").forEach((card) => {
        card.addEventListener("click", async () => {
            state.sectionCode = card.dataset.sectionCode || state.sectionCode;
            renderSections();
            await loadItems();
        });
    });

    document.querySelectorAll(".ia-tab").forEach((tab) => {
        tab.addEventListener("click", async () => {
            state.resourceType = tab.dataset.resourceType || state.resourceType;
            document.querySelectorAll(".ia-tab").forEach((item) => item.classList.toggle("active", item === tab));
            updateToolbarState();
            await loadItems();
        });
    });

    addButton?.addEventListener("click", () => openForm(null));
    importButton?.addEventListener("click", importSemanticModel);
    document.getElementById("ia-refresh-items")?.addEventListener("click", loadItems);
    document.getElementById("ia-run-test")?.addEventListener("click", runIntentTest);
    document.getElementById("ia-center-message-ok")?.addEventListener("click", hideMessage);
    searchInput?.addEventListener("input", () => window.clearTimeout(searchInput._timer));
    searchInput?.addEventListener("keyup", () => {
        window.clearTimeout(searchInput._timer);
        searchInput._timer = window.setTimeout(loadItems, 250);
    });
    activeSelect?.addEventListener("change", loadItems);
    document.querySelectorAll("[data-ia-modal-close]").forEach((button) => {
        button.addEventListener("click", () => setModalOpen(false));
    });

    form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const payload = collectFormPayload();
            const editing = state.editingItem;
            await fetchJson(apiUrl(state.resourceType, editing && editing.id), {
                method: editing ? "PUT" : "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                    "Accept": "application/json",
                },
                body: JSON.stringify(payload),
            });
            setModalOpen(false);
            showMessage("Configuration saved.", false);
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    renderSections();
    updateToolbarState();
    loadItems();
}());
