(function () {
    const root = document.querySelector("[data-kb-root]");
    if (!root) return;

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
        const script = document.getElementById("kb-sections-data");
        try {
            const value = JSON.parse(script?.textContent || "[]");
            return Array.isArray(value) ? value : [];
        } catch (error) {
            return [];
        }
    }

    const fields = {
        section: ["section", "Section", "section"],
        is_active: ["is_active", "Active", "checkbox"],
        validation_status: ["validation_status", "Validation Status", "select", ["Draft", "To Review", "Validated", "Rejected", "Deprecated"]],
        owner: ["owner", "Owner", "text"],
    };

    const resourceConfig = {
        "powerbi-metadata": {
            title: "Power BI Metadata",
            readonly: true,
            columns: ["item_type", "section_name", "display_name", "table_name", "measure_name", "dataset_id", "validation_status", "is_active"],
            fields: [],
        },
        "business-glossary": {
            title: "Business Glossary",
            columns: ["term", "category", "related_kpi", "validation_status", "is_active"],
            fields: [fields.section, ["term", "Term", "text"], ["business_definition", "Business Definition", "textarea"], ["category", "Category", "text"], ["related_kpi", "Related KPI", "text"], ["related_powerbi_measure", "Related Power BI Measure", "text"], ["related_table", "Related Table", "text"], ["related_column", "Related Column", "text"], ["example_usage", "Example Usage", "textarea"], fields.owner, fields.validation_status, fields.is_active],
        },
        "kpi-dictionary": {
            title: "KPI Dictionary",
            columns: ["kpi_code", "kpi_name", "powerbi_measure_name", "unit", "validation_status", "is_active"],
            fields: [fields.section, ["kpi_code", "KPI Code", "text"], ["kpi_name", "KPI Name", "text"], ["business_definition", "Business Definition", "textarea"], ["formula_description", "Formula Description", "textarea"], ["powerbi_measure_name", "Power BI Measure Name", "text"], ["unit", "Unit", "text"], ["target", "Target", "number"], ["warning_threshold", "Warning Threshold", "number"], ["critical_threshold", "Critical Threshold", "number"], ["aggregation_rule", "Aggregation Rule", "text"], ["default_time_grain", "Default Time Grain", "text"], fields.owner, fields.validation_status, fields.is_active],
        },
        "mining-terminology": {
            title: "Mining Terminology",
            columns: ["term", "category", "related_process", "validation_status", "is_active"],
            fields: [fields.section, ["term", "Term", "text"], ["definition", "Definition", "textarea"], ["category", "Category", "select", ["Maintenance", "Operations", "Reliability", "Components", "Sales", "Parts", "Telematics", "Oil Analysis"]], ["related_process", "Related Process", "text"], ["example", "Example", "textarea"], fields.owner, fields.validation_status, fields.is_active],
        },
        "question-library": {
            title: "Question Library",
            columns: ["question_text", "intent_type", "language", "difficulty_level", "validation_status", "is_active"],
            fields: [fields.section, ["question_text", "Question Text", "textarea"], ["intent_type", "Intent Type", "select", ["Single KPI", "Trend", "Comparison", "Ranking", "Root Cause", "Recommendation", "Executive Summary"]], ["expected_json_intent", "Expected JSON Intent", "json"], ["expected_dax", "Expected DAX", "textarea"], ["expected_answer_style", "Expected Answer Style", "textarea"], ["language", "Language", "text"], ["difficulty_level", "Difficulty Level", "text"], fields.owner, fields.validation_status, fields.is_active],
        },
        "synonym-library": {
            title: "Synonym Library",
            columns: ["canonical_term", "synonym", "entity_type", "language", "confidence", "validation_status", "is_active"],
            fields: [fields.section, ["canonical_term", "Canonical Term", "text"], ["synonym", "Synonym", "text"], ["entity_type", "Entity Type", "select", ["KPI", "Filter", "Mine Site", "Model", "Component", "Customer", "Period", "Business Term"]], ["language", "Language", "text"], ["confidence", "Confidence", "number"], fields.owner, fields.validation_status, fields.is_active],
        },
        "business-rules": {
            title: "Business Rules",
            columns: ["rule_name", "kpi", "condition", "validation_status", "is_active"],
            fields: [fields.section, ["rule_name", "Rule Name", "text"], ["kpi", "KPI", "text"], ["condition", "Condition", "textarea"], ["rule_description", "Rule Description", "textarea"], ["default_behavior", "Default Behavior", "textarea"], ["required_filters", "Required Filters", "text"], ["missing_filter_behavior", "Missing Filter Behavior", "textarea"], fields.owner, fields.validation_status, fields.is_active],
        },
        "prompt-library": {
            title: "Prompt Library",
            columns: ["prompt_name", "prompt_type", "version", "validation_status", "is_active"],
            fields: [fields.section, ["prompt_name", "Prompt Name", "text"], ["prompt_type", "Prompt Type", "select", ["Intent Extraction", "DAX Generation Control", "Business Response", "Recommendation", "Executive Summary", "Trend Analysis", "Comparison", "Root Cause Analysis"]], ["prompt_content", "Prompt Content", "textarea"], ["version", "Version", "text"], ["created_by", "Created By", "text"], fields.owner, fields.validation_status, fields.is_active],
        },
        "recommended-actions": {
            title: "Recommended Actions",
            columns: ["kpi", "condition", "priority", "validation_status", "is_active"],
            fields: [fields.section, ["kpi", "KPI", "text"], ["condition", "Condition", "text"], ["business_context", "Business Context", "textarea"], ["recommended_action", "Recommended Action", "textarea"], ["priority", "Priority", "number"], fields.owner, fields.validation_status, fields.is_active],
        },
        "ai-logs": {
            title: "AI Logs",
            readonly: true,
            columns: ["created_at", "user_question", "detected_section", "status", "execution_time_ms", "error_message"],
            fields: [["user_question", "User Question", "textarea"], ["detected_section", "Detected Section", "text"], ["extracted_intent", "Extracted Intent", "json"], ["generated_dax", "Generated DAX", "textarea"], ["powerbi_result", "Power BI Result", "json"], ["final_answer", "Final Answer", "textarea"], ["status", "Status", "text"], ["error_message", "Error Message", "textarea"], ["execution_time_ms", "Execution Time", "number"], ["token_usage", "Token Usage", "json"]],
        },
        "user-feedback": {
            title: "User Feedback",
            columns: ["created_at", "rating", "was_answer_useful", "feedback_comment"],
            fields: [["rating", "Rating", "number"], ["feedback_comment", "Feedback Comment", "textarea"], ["was_answer_useful", "Was Answer Useful", "checkbox"], ["corrected_intent", "Corrected Intent", "json"], ["corrected_answer", "Corrected Answer", "textarea"]],
        },
    };

    const state = {
        sections: readSections(),
        resourceType: "overview",
        items: [],
        editingItem: null,
    };

    const table = document.getElementById("kb-table");
    const tableWrap = document.getElementById("kb-table-wrap");
    const overviewPanel = document.getElementById("kb-overview-panel");
    const modal = document.getElementById("kb-modal");
    const form = document.getElementById("kb-form");
    const formFields = document.getElementById("kb-form-fields");
    const modalTitle = document.getElementById("kb-modal-title");
    const addButton = document.getElementById("kb-add");
    const searchInput = document.getElementById("kb-search");
    const sectionFilter = document.getElementById("kb-section-filter");
    const statusFilter = document.getElementById("kb-status-filter");
    const activeFilter = document.getElementById("kb-active-filter");

    async function fetchJson(url, options) {
        const response = await fetch(url, options || {});
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "Request failed.");
        return payload;
    }

    function showMessage(message, isError) {
        const box = document.getElementById("kb-center-message");
        const text = document.getElementById("kb-center-message-text");
        if (!box || !text) {
            alert(message);
            return;
        }
        text.textContent = message;
        box.hidden = false;
        box.setAttribute("aria-hidden", "false");
        box.classList.toggle("error", Boolean(isError));
        box.classList.add("visible");
    }

    function hideMessage() {
        const box = document.getElementById("kb-center-message");
        if (!box) return;
        box.classList.remove("visible", "error");
        box.hidden = true;
        box.setAttribute("aria-hidden", "true");
    }

    function fillSectionSelect(select, includeAll, includeAuto) {
        if (!select) return;
        const prefix = includeAll ? `<option value="">All</option>` : (includeAuto ? `<option value="">Auto</option>` : "");
        select.innerHTML = prefix + state.sections.map((section) => `<option value="${escapeHtml(section.code)}">${escapeHtml(section.name)}</option>`).join("");
    }

    function formatValue(value) {
        if (typeof value === "boolean") return value ? "Yes" : "No";
        if (value && typeof value === "object") return JSON.stringify(value);
        return value ?? "";
    }

    function updateToolbar() {
        const isOverview = state.resourceType === "overview";
        const isPowerBIInteraction = state.resourceType === "powerbi-interaction";
        const config = resourceConfig[state.resourceType] || {};
        if (overviewPanel) overviewPanel.hidden = !isOverview;
        if (tableWrap) tableWrap.hidden = isOverview || isPowerBIInteraction;
        const interactionPanel = document.getElementById("powerbi-interaction-panel");
        if (interactionPanel) interactionPanel.hidden = !isPowerBIInteraction;
        if (addButton) addButton.hidden = isOverview || isPowerBIInteraction || Boolean(config.readonly);
        [searchInput, sectionFilter, statusFilter, activeFilter].forEach((el) => {
            if (el) el.closest(".ia-filter").hidden = isOverview || isPowerBIInteraction;
        });
        document.getElementById("kb-active-title").textContent = isOverview ? "Overview" : (isPowerBIInteraction ? "Power BI Interaction" : config.title);
    }

    function renderTable() {
        const config = resourceConfig[state.resourceType];
        const columns = config.columns || [];
        table.innerHTML = `
            <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.replaceAll("_", " "))}</th>`).join("")}<th>Actions</th></tr></thead>
            <tbody>
                ${state.items.length ? state.items.map((item) => `
                    <tr>
                        ${columns.map((column) => `<td>${escapeHtml(formatValue(item[column]))}</td>`).join("")}
                        <td class="row-actions">
                            <button type="button" class="icon-action js-kb-edit" data-id="${item.id}" title="${config.readonly ? "View" : "Edit"}"></button>
                            ${config.readonly ? "" : `<button type="button" class="icon-action delete-action js-kb-delete" data-id="${item.id}" title="Deactivate"></button>`}
                        </td>
                    </tr>
                `).join("") : `<tr><td colspan="${columns.length + 1}" class="empty compact">No records found.</td></tr>`}
            </tbody>
        `;
        table.querySelectorAll(".js-kb-edit").forEach((button) => {
            button.addEventListener("click", () => {
                const item = state.items.find((candidate) => String(candidate.id) === String(button.dataset.id));
                if (item) openForm(item);
            });
        });
        table.querySelectorAll(".js-kb-delete").forEach((button) => {
            button.addEventListener("click", async () => {
                if (!confirm("Deactivate this knowledge item?")) return;
                try {
                    await fetchJson(`/knowledge-base/api/${state.resourceType}/${button.dataset.id}/`, {
                        method: "DELETE",
                        headers: {"X-CSRFToken": csrfToken(), "Accept": "application/json"},
                    });
                    showMessage("Knowledge item deactivated.", false);
                    await loadItems();
                } catch (error) {
                    showMessage(error.message, true);
                }
            });
        });
    }

    function renderOverview(overview) {
        document.getElementById("kb-coverage-score").textContent = `${overview.coverage_score || 0}%`;
        const cards = [
            ["Total Knowledge Items", overview.total_items],
            ["Semantic Tables", overview.semantic_tables],
            ["Semantic Measures", overview.semantic_measures],
            ["Synonyms", overview.synonyms],
            ["Question Examples", overview.question_examples],
            ["Business Rules", overview.business_rules],
            ["Prompts", overview.prompts],
            ["Recommended Actions", overview.recommended_actions],
            ["Last Semantic Import", overview.last_imported_at || "None"],
        ];
        overviewPanel.innerHTML = `
            <div class="kb-kpi-grid">
                ${cards.map(([label, value]) => `<div class="placeholder-panel kb-kpi-card"><span class="summary-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}
            </div>
            <div class="placeholder-panel">
                <p class="eyebrow">Coverage by section</p>
                <div class="table-scroll">
                    <table class="data-table">
                        <thead><tr><th>Section</th><th>Metadata</th><th>Synonyms</th><th>Questions</th><th>KPI Targets</th><th>Rules</th><th>Score</th></tr></thead>
                        <tbody>
                            ${(overview.coverage || []).map((row) => `<tr><td>${escapeHtml(row.section)}</td><td>${row.metadata}</td><td>${row.synonyms}</td><td>${row.questions}</td><td>${row.kpis}</td><td>${row.rules}</td><td><span class="status-badge success">${row.score}%</span></td></tr>`).join("")}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    async function loadOverview() {
        updateToolbar();
        const payload = await fetchJson("/knowledge-base/api/overview/");
        renderOverview(payload.overview || {});
    }

    async function loadItems() {
        updateToolbar();
        if (state.resourceType === "powerbi-interaction") {
            document.dispatchEvent(new CustomEvent("mining360:powerbi-interaction-open"));
            return;
        }
        if (state.resourceType === "overview") {
            await loadOverview();
            return;
        }
        const url = new URL(`/knowledge-base/api/${state.resourceType}/`, window.location.origin);
        if (searchInput?.value.trim()) url.searchParams.set("q", searchInput.value.trim());
        if (sectionFilter?.value) url.searchParams.set("section", sectionFilter.value);
        if (statusFilter?.value) url.searchParams.set("status", statusFilter.value);
        if (activeFilter?.value) url.searchParams.set("active", activeFilter.value);
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
        if (type === "section") {
            return `<label>${escapeHtml(label)}<select name="${name}">${state.sections.map((section) => `<option value="${escapeHtml(section.code)}" ${String(value || "") === section.code ? "selected" : ""}>${escapeHtml(section.name)}</option>`).join("")}</select></label>`;
        }
        if (type === "checkbox") {
            const checked = value === undefined ? true : Boolean(value);
            return `<label class="inline-check stacked"><input name="${name}" type="checkbox" ${checked ? "checked" : ""}> ${escapeHtml(label)}</label>`;
        }
        if (type === "select") {
            return `<label>${escapeHtml(label)}<select name="${name}">${(options || []).map((option) => `<option value="${escapeHtml(option)}" ${String(value || "") === option ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select></label>`;
        }
        if (type === "json") {
            const display = value && typeof value === "object" ? JSON.stringify(value, null, 2) : value || "";
            return `<label class="full-width">${escapeHtml(label)}<textarea name="${name}" rows="10">${escapeHtml(display)}</textarea></label>`;
        }
        if (type === "textarea") {
            return `<label class="full-width">${escapeHtml(label)}<textarea name="${name}" rows="6">${escapeHtml(value || "")}</textarea></label>`;
        }
        if (type === "number") {
            return `<label>${escapeHtml(label)}<input name="${name}" type="number" step="any" value="${escapeHtml(value ?? "")}"></label>`;
        }
        return `<label>${escapeHtml(label)}<input name="${name}" type="text" value="${escapeHtml(value || "")}"></label>`;
    }

    function setModalOpen(open) {
        modal.hidden = !open;
        modal.setAttribute("aria-hidden", open ? "false" : "true");
        document.body.classList.toggle("modal-open", open);
    }

    function openForm(item) {
        state.editingItem = item || null;
        const config = resourceConfig[state.resourceType];
        modalTitle.textContent = `${item ? "Edit" : "Create"} ${config.title}`;
        formFields.innerHTML = (config.fields || []).map((field) => fieldHtml(field, item ? item[field[0]] : undefined)).join("");
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            field.disabled = Boolean(config.readonly);
        });
        document.getElementById("kb-save").hidden = Boolean(config.readonly);
        setModalOpen(true);
    }

    function collectPayload() {
        const config = resourceConfig[state.resourceType];
        const payload = {};
        for (const [name, label, type] of config.fields || []) {
            const field = form.querySelector(`[name="${name}"]`);
            if (!field) continue;
            if (type === "checkbox") payload[name] = field.checked;
            else if (type === "json") {
                try {
                    payload[name] = field.value.trim() ? JSON.parse(field.value) : {};
                } catch (error) {
                    throw new Error(`${label} must be valid JSON.`);
                }
            } else payload[name] = field.value;
        }
        return payload;
    }

    async function runCoverageTest() {
        const section = document.getElementById("kb-test-section").value || "performance";
        const kpi = document.getElementById("kb-test-kpi").value.trim();
        const question = document.getElementById("kb-test-question").value.trim();
        const output = document.getElementById("kb-coverage-result");
        output.textContent = "Testing...";
        try {
            const payload = await fetchJson("/knowledge-base/api/coverage-test/", {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({section, kpi, question}),
            });
            output.textContent = JSON.stringify(payload, null, 2);
        } catch (error) {
            output.textContent = error.message;
        }
    }

    async function generateKnowledge() {
        const section = document.getElementById("kb-generate-section").value;
        const button = document.getElementById("kb-generate");
        button.disabled = true;
        button.textContent = "Generating...";
        try {
            const payload = await fetchJson("/knowledge-base/api/generate/", {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({section}),
            });
            showMessage(`Generated draft knowledge: ${JSON.stringify(payload.generated)}`, false);
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        } finally {
            button.disabled = false;
            button.textContent = "Generate Knowledge";
        }
    }

    document.querySelectorAll("#kb-tabs .ia-tab").forEach((tab) => {
        tab.addEventListener("click", async () => {
            state.resourceType = tab.dataset.resourceType;
            document.querySelectorAll("#kb-tabs .ia-tab").forEach((item) => item.classList.toggle("active", item === tab));
            await loadItems();
        });
    });
    document.getElementById("kb-refresh")?.addEventListener("click", loadItems);
    document.getElementById("kb-add")?.addEventListener("click", () => openForm(null));
    document.getElementById("kb-run-coverage")?.addEventListener("click", runCoverageTest);
    document.getElementById("kb-generate")?.addEventListener("click", generateKnowledge);
    document.getElementById("kb-center-message-ok")?.addEventListener("click", hideMessage);
    document.querySelectorAll("[data-kb-modal-close]").forEach((button) => button.addEventListener("click", () => setModalOpen(false)));
    [sectionFilter, statusFilter, activeFilter].forEach((filter) => filter?.addEventListener("change", loadItems));
    searchInput?.addEventListener("keyup", () => {
        clearTimeout(searchInput._timer);
        searchInput._timer = setTimeout(loadItems, 250);
    });
    form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const payload = collectPayload();
            const editing = state.editingItem;
            await fetchJson(`/knowledge-base/api/${state.resourceType}/${editing ? `${editing.id}/` : ""}`, {
                method: editing ? "PUT" : "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify(payload),
            });
            setModalOpen(false);
            showMessage("Knowledge item saved.", false);
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    fillSectionSelect(sectionFilter, true, false);
    fillSectionSelect(document.getElementById("kb-test-section"), false, false);
    fillSectionSelect(document.getElementById("kb-generate-section"), true, false);
    updateToolbar();
    loadOverview();
}());
