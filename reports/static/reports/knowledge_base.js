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

    const kpiFields = [
        [fields.section[0], fields.section[1], fields.section[2], null, "General Information"],
        ["kpi_code", "KPI Code", "text", null, "General Information"],
        ["kpi_name", "KPI Name", "text", null, "General Information"],
        ["business_category", "Business Category", "select", ["Reliability", "Maintenance", "Operations", "Productivity", "Fuel", "Parts Sales", "Component Rebuild", "Financial", "Other"], "General Information"],
        ["unit", "Unit", "text", null, "General Information"],
        ["owner", "Owner", "text", null, "General Information"],
        ["validation_status", "Validation Status", "select", ["Draft", "To Review", "Validated", "Rejected", "Deprecated"], "General Information"],
        ["is_active", "Active", "checkbox", null, "General Information"],

        ["business_definition", "Business Definition", "textarea", null, "Business Definition"],
        ["business_purpose", "Business Purpose", "textarea", null, "Business Definition"],
        ["business_interpretation", "Business Interpretation", "textarea", null, "Business Definition"],
        ["formula_description", "Formula Description", "textarea", null, "Business Definition"],
        ["higher_is_better", "Higher Is Better", "checkbox", null, "Business Definition"],
        ["lower_is_better", "Lower Is Better", "checkbox", null, "Business Definition"],

        ["numerator_description", "Numerator Description", "textarea", null, "Calculation"],
        ["denominator_description", "Denominator Description", "textarea", null, "Calculation"],
        ["calculation_type", "Calculation Type", "select", ["Ratio", "Percentage", "Sum", "Average", "Weighted Average", "Count", "Duration", "Rate", "Index", "Custom"], "Calculation"],
        ["null_handling_rule", "Null Handling Rule", "select", ["Ignore Nulls", "Treat as Zero", "Return Blank", "Use Previous Value", "Custom"], "Calculation"],
        ["zero_denominator_behavior", "Zero Denominator Behavior", "select", ["Return Blank", "Return Zero", "Return Error", "Custom"], "Calculation"],
        ["decimal_precision", "Decimal Precision", "integer", null, "Calculation"],
        ["display_format", "Display Format", "text", null, "Calculation"],
        ["aggregation_rule", "Aggregation Rule", "textarea", null, "Calculation"],
        ["default_time_grain", "Default Time Grain", "text", null, "Calculation"],

        ["powerbi_workspace_id", "Power BI Workspace ID", "text", null, "Power BI Mapping"],
        ["powerbi_report_id", "Power BI Report ID", "text", null, "Power BI Mapping"],
        ["powerbi_semantic_model_id", "Power BI Semantic Model ID", "text", null, "Power BI Mapping"],
        ["powerbi_measure_table", "Power BI Measure Table", "text", null, "Power BI Mapping"],
        ["powerbi_measure_name", "Power BI Measure Name", "text", null, "Power BI Mapping"],
        ["powerbi_measure_full_reference", "Power BI Measure Full Reference", "readonly", null, "Power BI Mapping"],
        ["source_report_name", "Source Report Name", "text", null, "Power BI Mapping"],
        ["source_page_name", "Source Page Name", "text", null, "Power BI Mapping"],
        ["source_page_internal_name", "Source Page Internal Name", "text", null, "Power BI Mapping"],
        ["primary_visual_name", "Primary Visual Name", "text", null, "Power BI Mapping"],
        ["primary_visual_internal_name", "Primary Visual Internal Name", "text", null, "Power BI Mapping"],

        ["target", "Target", "number", null, "Targets and Thresholds"],
        ["warning_threshold", "Warning Threshold", "number", null, "Targets and Thresholds"],
        ["critical_threshold", "Critical Threshold", "number", null, "Targets and Thresholds"],
        ["threshold_direction", "Threshold Direction", "select", ["Higher Is Better", "Lower Is Better"], "Targets and Thresholds"],
        ["target_source", "Target Source", "select", ["Fixed Value", "Power BI Measure", "Site Target", "Customer Target", "Model Target", "External Benchmark"], "Targets and Thresholds"],
        ["target_measure_name", "Target Measure Name", "text", null, "Targets and Thresholds"],
        ["threshold_evaluation_rule", "Threshold Evaluation Rule", "textarea", null, "Targets and Thresholds"],

        ["default_comparison_type", "Default Comparison Type", "select", ["None", "Previous Period", "Previous Month", "Previous Year", "Target", "Budget", "Benchmark", "Custom"], "Analytical Behavior"],
        ["default_comparison_period", "Default Comparison Period", "text", null, "Analytical Behavior"],
        ["default_ranking_direction", "Default Ranking Direction", "select", ["Highest First", "Lowest First", "Not Applicable"], "Analytical Behavior"],
        ["default_top_n", "Default Top N", "integer", null, "Analytical Behavior"],
        ["trend_supported", "Trend Supported", "checkbox", null, "Analytical Behavior"],
        ["comparison_supported", "Comparison Supported", "checkbox", null, "Analytical Behavior"],
        ["ranking_supported", "Ranking Supported", "checkbox", null, "Analytical Behavior"],
        ["root_cause_supported", "Root Cause Supported", "checkbox", null, "Analytical Behavior"],
        ["forecast_supported", "Forecast Supported", "checkbox", null, "Analytical Behavior"],

        ["supported_dimensions", "Supported Dimensions", "multiselect", "filters", "Filters and Drill-Down"],
        ["default_drill_down_dimension", "Default Drill-Down Dimension", "dynamic-select", "filters", "Filters and Drill-Down"],
        ["required_filters", "Required Filters", "multiselect", "filters", "Filters and Drill-Down"],
        ["optional_filters", "Optional Filters", "multiselect", "filters", "Filters and Drill-Down"],

        ["related_kpis", "Related KPIs", "multiselect", "kpis", "Related KPIs"],
        ["diagnostic_kpis", "Diagnostic KPIs", "multiselect", "kpis", "Related KPIs"],
        ["parent_kpi", "Parent KPI", "dynamic-select", "kpis", "Related KPIs"],
        ["child_kpis", "Child KPIs", "multiselect", "kpis", "Related KPIs"],

        ["default_answer_template", "Default Answer Template", "textarea", null, "AI Response Configuration"],
        ["business_explanation_template", "Business Explanation Template", "textarea", null, "AI Response Configuration"],
        ["clarification_message", "Clarification Message", "textarea", null, "AI Response Configuration"],
        ["ai_usage_instructions", "AI Usage Instructions", "textarea", null, "AI Response Configuration"],

        ["minimum_data_completeness", "Minimum Data Completeness", "number", null, "Data Quality"],
        ["minimum_equipment_count", "Minimum Equipment Count", "integer", null, "Data Quality"],
        ["freshness_requirement", "Freshness Requirement", "text", null, "Data Quality"],
        ["data_quality_warning_message", "Data Quality Warning Message", "textarea", null, "Data Quality"],

        ["business_owner", "Business Owner", "text", null, "Governance"],
        ["technical_owner", "Technical Owner", "text", null, "Governance"],
        ["approved_by", "Approved By", "text", null, "Governance"],
        ["approved_at", "Approved At", "datetime", null, "Governance"],
        ["version", "Version", "text", null, "Governance"],
        ["effective_from", "Effective From", "date", null, "Governance"],
        ["effective_to", "Effective To", "date", null, "Governance"],
        ["review_frequency", "Review Frequency", "select", ["Monthly", "Quarterly", "Semi-Annual", "Annual", "On Change"], "Governance"],
        ["last_reviewed_at", "Last Reviewed At", "datetime", null, "Governance"],
        ["review_notes", "Review Notes", "textarea", null, "Governance"],
    ];

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
            fields: kpiFields,
            groups: ["General Information", "Business Definition", "Calculation", "Power BI Mapping", "Targets and Thresholds", "Analytical Behavior", "Filters and Drill-Down", "Related KPIs", "AI Response Configuration", "Data Quality", "Governance"],
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
            columns: ["canonical_term", "synonym", "normalized_value", "entity_type", "language", "confidence", "match_type", "synonym_source", "usage_count", "is_ambiguous", "validation_status", "is_active", "updated_at"],
            groups: ["General Information", "Matching Configuration", "Governance", "Usage Statistics"],
            fields: [
                ["section", "Section", "section", null, "General Information"],
                ["entity_type", "Entity Type", "select", ["KPI", "Filter", "Mine Site", "Model", "Component", "Customer", "Period", "Business Term"], "General Information"],
                ["canonical_term", "Canonical Term", "text", null, "General Information"],
                ["synonym", "Synonym", "text", null, "General Information"],
                ["normalized_value", "Normalized Value", "text", null, "General Information"],
                ["language", "Language", "text", null, "General Information"],
                ["match_type", "Match Type", "select", ["Exact", "Phrase", "Contains", "Abbreviation", "Fuzzy", "Semantic"], "Matching Configuration"],
                ["confidence", "Confidence", "number", null, "Matching Configuration"],
                ["resolution_priority", "Resolution Priority", "integer", null, "Matching Configuration"],
                ["is_ambiguous", "Is Ambiguous", "checkbox", null, "Matching Configuration"],
                ["ambiguity_notes", "Ambiguity Notes", "textarea", null, "Matching Configuration"],
                ["synonym_source", "Synonym Source", "select", ["Manual", "Business", "Imported", "System Generated", "AI Generated"], "Governance"],
                ["owner", "Owner", "text", null, "Governance"],
                ["validation_status", "Validation Status", "select", ["Draft", "To Review", "Validated", "Rejected", "Deprecated"], "Governance"],
                ["is_active", "Active", "checkbox", null, "Governance"],
                ["usage_count", "Usage Count", "readonly", null, "Usage Statistics"],
                ["last_used_at", "Last Used At", "readonly", null, "Usage Statistics"],
                ["last_used_question", "Last Used Question", "readonly", null, "Usage Statistics"],
                ["created_at", "Created At", "readonly", null, "Usage Statistics"],
                ["created_by", "Created By", "readonly", null, "Usage Statistics"],
                ["updated_at", "Updated At", "readonly", null, "Usage Statistics"],
                ["updated_by", "Updated By", "readonly", null, "Usage Statistics"],
                ["validated_at", "Validated At", "readonly", null, "Usage Statistics"],
                ["validated_by", "Validated By", "readonly", null, "Usage Statistics"],
            ],
        },
        "synonym-analytics": {title: "Synonym Analytics", readonly: true, columns: [], fields: []},
        "synonym-resolution-test": {title: "Test Synonym Resolution", readonly: true, columns: [], fields: []},
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
        formMetadata: {},
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

    function tableCell(column, item) {
        const value = item[column];
        if (["validation_status", "synonym_source"].includes(column)) {
            const css = String(value || "").toLowerCase().replaceAll(" ", "-");
            return `<span class="status-badge ${escapeHtml(css)}">${escapeHtml(value || "Unknown")}</span>`;
        }
        if (column === "is_ambiguous") {
            return `<span class="status-badge ${value ? "warning" : "success"}">${value ? "Ambiguous" : "Unambiguous"}</span>`;
        }
        if (column === "is_active") {
            return `<span class="status-badge ${value ? "success" : "neutral"}">${value ? "Active" : "Inactive"}</span>`;
        }
        return escapeHtml(formatValue(value));
    }

    function updateToolbar() {
        const isOverview = state.resourceType === "overview";
        const isPowerBIInteraction = state.resourceType === "powerbi-interaction";
        const isResolution = state.resourceType === "knowledge-resolution";
        const isSynonymAnalytics = state.resourceType === "synonym-analytics";
        const isSynonymTest = state.resourceType === "synonym-resolution-test";
        const isStandalone = isOverview || isPowerBIInteraction || isResolution || isSynonymAnalytics || isSynonymTest;
        const config = resourceConfig[state.resourceType] || {};
        root.classList.toggle("kb-overview-active", isOverview);
        if (overviewPanel) overviewPanel.hidden = !isOverview;
        if (tableWrap) tableWrap.hidden = isStandalone;
        const interactionPanel = document.getElementById("powerbi-interaction-panel");
        if (interactionPanel) interactionPanel.hidden = !isPowerBIInteraction;
        const resolutionPanel = document.getElementById("kb-resolution-panel");
        if (resolutionPanel) resolutionPanel.hidden = !isResolution;
        const synonymAnalyticsPanel = document.getElementById("kb-synonym-analytics-panel");
        if (synonymAnalyticsPanel) synonymAnalyticsPanel.hidden = !isSynonymAnalytics;
        const synonymTestPanel = document.getElementById("kb-synonym-test-panel");
        if (synonymTestPanel) synonymTestPanel.hidden = !isSynonymTest;
        if (addButton) addButton.hidden = isStandalone || Boolean(config.readonly);
        const synonymActions = document.getElementById("kb-synonym-actions");
        if (synonymActions) synonymActions.hidden = state.resourceType !== "synonym-library";
        [searchInput, sectionFilter, statusFilter, activeFilter].forEach((el) => {
            if (el) el.closest(".ia-filter").hidden = isStandalone;
        });
        document.getElementById("kb-active-title").textContent = isOverview
            ? "Overview"
            : (isPowerBIInteraction ? "Power BI Interaction" : (isResolution ? "Knowledge Resolution" : config.title));
    }

    function renderTable() {
        const config = resourceConfig[state.resourceType];
        const columns = config.columns || [];
        table.dataset.resource = state.resourceType;
        table.innerHTML = `
            <thead><tr>${columns.map((column) => `<th data-column="${escapeHtml(column)}">${escapeHtml(column.replaceAll("_", " "))}</th>`).join("")}<th data-column="actions">Actions</th></tr></thead>
            <tbody>
                ${state.items.length ? state.items.map((item) => `
                    <tr>
                        ${columns.map((column) => `<td data-column="${escapeHtml(column)}">${tableCell(column, item)}</td>`).join("")}
                        <td class="row-actions" data-column="actions">
                            <button type="button" class="icon-action js-kb-edit" data-id="${item.id}" title="${config.readonly ? "View" : "Edit"}"></button>
                            ${config.readonly ? "" : `<button type="button" class="icon-action delete-action js-kb-delete" data-id="${item.id}" title="${["business-glossary", "kpi-dictionary"].includes(state.resourceType) ? "Delete permanently" : "Deactivate"}"></button>`}
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
                const hardDelete = ["business-glossary", "kpi-dictionary"].includes(state.resourceType);
                const confirmation = hardDelete
                    ? `Permanently delete this ${state.resourceType === "kpi-dictionary" ? "KPI" : "Business Glossary item"}?`
                    : "Deactivate this knowledge item?";
                if (!confirm(confirmation)) return;
                try {
                    const suffix = hardDelete ? "?hard=1" : "";
                    await fetchJson(`/knowledge-base/api/${state.resourceType}/${button.dataset.id}/${suffix}`, {
                        method: "DELETE",
                        headers: {"X-CSRFToken": csrfToken(), "Accept": "application/json"},
                    });
                    showMessage(
                        hardDelete
                            ? (state.resourceType === "kpi-dictionary"
                                ? "KPI deleted."
                                : "Business Glossary item deleted.")
                            : "Knowledge item deactivated.",
                        false,
                    );
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
        if (state.resourceType === "knowledge-resolution") return;
        if (state.resourceType === "synonym-analytics") {
            await loadSynonymAnalytics();
            return;
        }
        if (state.resourceType === "synonym-resolution-test") return;
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
        if (state.resourceType === "synonym-library") {
            const synonymFilters = {
                entity_type: "kb-synonym-entity",
                language: "kb-synonym-language",
                source: "kb-synonym-source",
                match_type: "kb-synonym-match",
                quick: "kb-synonym-quick",
                ambiguous: "kb-synonym-ambiguous",
                owner: "kb-synonym-owner",
                min_usage: "kb-synonym-min-usage",
                min_confidence: "kb-synonym-min-confidence",
            };
            Object.entries(synonymFilters).forEach(([parameter, id]) => {
                const value = document.getElementById(id)?.value?.trim();
                if (value) url.searchParams.set(parameter, value);
            });
        }
        const synonymExport = document.getElementById("kb-export-synonyms");
        if (synonymExport && state.resourceType === "synonym-library") {
            const exportUrl = new URL(synonymExport.href, window.location.origin);
            exportUrl.search = url.search;
            synonymExport.href = exportUrl.toString();
        }
        document.querySelectorAll(".kb-synonym-export-format").forEach((link) => {
            const exportUrl = new URL(link.href, window.location.origin);
            exportUrl.search = url.search;
            link.href = exportUrl.toString();
        });
        table.innerHTML = `<tbody><tr><td class="empty compact">Loading...</td></tr></tbody>`;
        try {
            const payload = await fetchJson(url.toString());
            state.items = payload.items || [];
            state.formMetadata = payload.form_metadata || {};
            renderTable();
        } catch (error) {
            table.innerHTML = `<tbody><tr><td class="empty compact">${escapeHtml(error.message)}</td></tr></tbody>`;
        }
    }

    function dynamicOptions(source, item) {
        if (Array.isArray(source)) return source.map((value) => ({value, label: value}));
        const sectionCode = item?.section || form?.querySelector('[name="section"]')?.value || "";
        const values = source === "filters"
            ? (state.formMetadata.filters || [])
            : source === "kpis"
                ? (state.formMetadata.kpis || [])
                : [];
        return values
            .filter((option) => !sectionCode || option.section === sectionCode)
            .filter((option) => source !== "kpis" || option.value !== item?.kpi_code);
    }

    function fieldHtml([name, label, type, options], value, item) {
        if (value === undefined && name === "confidence") value = 100;
        if (value === undefined && name === "resolution_priority") value = 50;
        if (type === "section") {
            return `<label>${escapeHtml(label)}<select name="${name}">${state.sections.map((section) => `<option value="${escapeHtml(section.code)}" ${String(value || "") === section.code ? "selected" : ""}>${escapeHtml(section.name)}</option>`).join("")}</select></label>`;
        }
        if (type === "checkbox") {
            const checked = value === undefined ? name === "is_active" : Boolean(value);
            return `<label class="inline-check stacked"><input name="${name}" type="checkbox" ${checked ? "checked" : ""}> ${escapeHtml(label)}</label>`;
        }
        if (type === "select" || type === "dynamic-select") {
            const resolved = dynamicOptions(options, item);
            const empty = type === "dynamic-select" ? '<option value="">None</option>' : "";
            return `<label>${escapeHtml(label)}<select name="${name}">${empty}${resolved.map((option) => `<option value="${escapeHtml(option.value)}" ${String(value || "") === String(option.value) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
        }
        if (type === "multiselect") {
            const selectedValues = Array.isArray(value) ? value.map(String) : [];
            const resolved = dynamicOptions(options, item);
            return `<label class="full-width">${escapeHtml(label)}<select name="${name}" multiple size="6">${resolved.map((option) => `<option value="${escapeHtml(option.value)}" ${selectedValues.includes(String(option.value)) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
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
        if (type === "integer") {
            return `<label>${escapeHtml(label)}<input name="${name}" type="number" step="1" min="0" value="${escapeHtml(value ?? "")}"></label>`;
        }
        if (type === "date") {
            return `<label>${escapeHtml(label)}<input name="${name}" type="date" value="${escapeHtml(String(value || "").slice(0, 10))}"></label>`;
        }
        if (type === "datetime") {
            return `<label>${escapeHtml(label)}<input name="${name}" type="datetime-local" value="${escapeHtml(String(value || "").slice(0, 16))}"></label>`;
        }
        if (type === "readonly") {
            return `<label>${escapeHtml(label)}<input name="${name}" type="text" value="${escapeHtml(value || "")}" readonly></label>`;
        }
        return `<label>${escapeHtml(label)}<input name="${name}" type="text" value="${escapeHtml(value || "")}"></label>`;
    }

    function setModalOpen(open) {
        modal.hidden = !open;
        modal.setAttribute("aria-hidden", open ? "false" : "true");
        document.body.classList.toggle("modal-open", open);
    }

    function syncDefaultDrillDownOptions() {
        const supported = form.querySelector('[name="supported_dimensions"]');
        const defaultDimension = form.querySelector('[name="default_drill_down_dimension"]');
        if (!supported || !defaultDimension) return;
        const previous = defaultDimension.value;
        const options = Array.from(supported.selectedOptions).map((option) => ({
            value: option.value,
            label: option.textContent,
        }));
        defaultDimension.innerHTML = '<option value="">None</option>' + options
            .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
            .join("");
        defaultDimension.value = options.some((option) => option.value === previous) ? previous : "";
    }

    function openForm(item) {
        state.editingItem = item || null;
        const config = resourceConfig[state.resourceType];
        modalTitle.textContent = `${item ? "Edit" : "Create"} ${config.title}`;
        if (config.groups) {
            formFields.innerHTML = config.groups.map((group, index) => `
                <details class="kb-form-section" ${index === 0 ? "open" : ""}>
                    <summary>${escapeHtml(group)}</summary>
                    <div class="form-grid">
                        ${(config.fields || []).filter((field) => field[4] === group).map((field) => fieldHtml(field, item ? item[field[0]] : undefined, item)).join("")}
                    </div>
                </details>
            `).join("") + '<pre id="kb-kpi-test-output" class="ia-code-block" hidden></pre>';
        } else {
            formFields.innerHTML = (config.fields || []).map((field) => fieldHtml(field, item ? item[field[0]] : undefined, item)).join("");
        }
        const sectionSelect = form.querySelector('[name="section"]');
        if (sectionSelect && !sectionSelect.value) {
            sectionSelect.value = sectionFilter?.value || state.sections[0]?.code || "performance";
        }
        const defaultDimension = form.querySelector('[name="default_drill_down_dimension"]');
        const savedDefaultDimension = defaultDimension?.value || item?.default_drill_down_dimension || "";
        syncDefaultDrillDownOptions();
        if (defaultDimension && Array.from(defaultDimension.options).some((option) => option.value === savedDefaultDimension)) {
            defaultDimension.value = savedDefaultDimension;
        }
        form.querySelector('[name="supported_dimensions"]')?.addEventListener("change", syncDefaultDrillDownOptions);
        const ambiguity = form.querySelector('[name="is_ambiguous"]');
        const ambiguityNotes = form.querySelector('[name="ambiguity_notes"]')?.closest("label");
        const syncAmbiguity = () => {
            if (ambiguityNotes) ambiguityNotes.hidden = !ambiguity?.checked;
        };
        ambiguity?.addEventListener("change", syncAmbiguity);
        syncAmbiguity();
        const synonymInput = form.querySelector('[name="synonym"]');
        const matchType = form.querySelector('[name="match_type"]');
        synonymInput?.addEventListener("blur", () => {
            if (!state.editingItem && matchType && matchType.value === "Exact" && synonymInput.value.trim().split(/\s+/).length > 1) {
                matchType.value = "Phrase";
            }
        });
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            field.disabled = Boolean(config.readonly);
        });
        document.getElementById("kb-save").hidden = Boolean(config.readonly);
        document.querySelectorAll("[data-kpi-action]").forEach((button) => {
            button.hidden = state.resourceType !== "kpi-dictionary" || Boolean(config.readonly);
            if (button.dataset.kpiAction === "duplicate") {
                button.disabled = !item;
            }
            if (["test", "preview"].includes(button.dataset.kpiAction)) {
                button.disabled = !item;
            }
        });
        setModalOpen(true);
    }

    function collectPayload() {
        const config = resourceConfig[state.resourceType];
        const payload = {};
        for (const [name, label, type] of config.fields || []) {
            const field = form.querySelector(`[name="${name}"]`);
            if (!field) continue;
            if (type === "checkbox") payload[name] = field.checked;
            else if (type === "multiselect") {
                payload[name] = Array.from(field.selectedOptions).map((option) => option.value);
            }
            else if (type === "json") {
                try {
                    payload[name] = field.value.trim() ? JSON.parse(field.value) : {};
                } catch (error) {
                    throw new Error(`${label} must be valid JSON.`);
                }
            } else payload[name] = field.value;
        }
        if ((config.fields || []).some(([name]) => name === "section")) {
            const sectionSelect = form.querySelector('[name="section"]');
            const sectionCode = String(sectionSelect?.value || "").trim();
            if (!sectionCode) throw new Error("Section is required.");
            payload.section = sectionCode;
            const section = state.sections.find((item) => item.code === sectionCode);
            if (section?.id) payload.section_id = section.id;
        }
        return payload;
    }

    async function runCoverageTest() {
        const section = document.getElementById("kb-test-section").value || "performance";
        const kpi = document.getElementById("kb-test-kpi").value.trim();
        const question = document.getElementById("kb-test-question").value.trim();
        const mode = document.querySelector('[name="kb-execution-mode"]:checked')?.value || "Production";
        const output = document.getElementById("kb-coverage-result");
        output.innerHTML = '<p class="kb-coverage-empty">Testing...</p>';
        try {
            const payload = await fetchJson("/knowledge-base/api/coverage-test/", {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({section, kpi, question, mode}),
            });
            const warnings = (payload.warnings || []).map((warning) => `
                <div class="kb-coverage-warning">${escapeHtml(warning)}</div>
            `).join("");
            const groupedRepositories = (payload.repositories || []).reduce((groups, item) => {
                (groups[item.repository] ||= []).push(item);
                return groups;
            }, {});
            const repositories = Object.entries(groupedRepositories).map(([repository, items]) => {
                const usedItems = items.filter((item) => item.used);
                const statuses = [...new Set(items.map((item) => item.status))];
                const primaryStatus = usedItems[0]?.status || items[0]?.status || "Not Found";
                const statusClass = String(primaryStatus).toLowerCase().replaceAll(" ", "-");
                return `
                    <article class="kb-coverage-item ${usedItems.length ? "used" : "unused"}">
                        <div class="kb-coverage-item__head">
                            <strong>${escapeHtml(repository)}</strong>
                            <span class="kb-validation-badge ${escapeHtml(statusClass)}">${escapeHtml(primaryStatus)}</span>
                        </div>
                        <span class="kb-coverage-item__name">${usedItems.length} of ${items.length} configured item(s) usable</span>
                        <span class="kb-used-badge ${usedItems.length ? "used" : "unused"}">${usedItems.length ? "Ready" : "Not ready"}</span>
                        <details class="kb-repository-details">
                            <summary>View records</summary>
                            ${items.map((item) => `
                                <div>
                                    <span>${escapeHtml(item.item)}</span>
                                    <small>${escapeHtml(item.status)} · ${item.used ? "Used" : "Not used"}${item.reason ? ` · ${escapeHtml(item.reason)}` : ""}</small>
                                </div>
                            `).join("")}
                        </details>
                    </article>
                `;
            }).join("");
            const detectedFilters = Object.entries(payload.intent?.filters || {})
                .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && !value.length));
            output.innerHTML = `
                <div class="kb-coverage-notice">
                    <strong>Knowledge readiness test</strong>
                    <span>${escapeHtml(payload.message || "")}</span>
                </div>
                <div class="kb-detected-request">
                    <div><span>Section</span><strong>${escapeHtml(payload.intent?.section || "Not detected")}</strong></div>
                    <div><span>Metric</span><strong>${escapeHtml(payload.intent?.metric || "Not detected")}</strong></div>
                    <div class="full-width">
                        <span>Detected filters</span>
                        <div class="kb-filter-chips">
                            ${detectedFilters.length
                                ? detectedFilters.map(([key, value]) => `<span><strong>${escapeHtml(key)}</strong> = ${escapeHtml(value)}</span>`).join("")
                                : '<em>No filter detected</em>'}
                        </div>
                    </div>
                </div>
                <div class="kb-coverage-summary">
                    <div><span>Mode</span><strong>${escapeHtml(payload.mode)}</strong></div>
                    <div><span>Knowledge readiness</span><strong>${escapeHtml(payload.coverage_score)}%</strong></div>
                </div>
                ${warnings}
                <button type="button" class="button secondary kb-run-resolution">Resolve &amp; Execute Power BI</button>
                <div class="kb-coverage-items">${repositories}</div>
                <details class="kb-coverage-debug">
                    <summary>Debug details</summary>
                    <pre class="ia-code-block">${escapeHtml(JSON.stringify({
                        intent: payload.intent,
                        checks: payload.checks,
                        debug: payload.debug,
                    }, null, 2))}</pre>
                </details>
            `;
            output.querySelector(".kb-run-resolution")?.addEventListener("click", () => {
                const resolutionTab = document.querySelector('#kb-tabs [data-resource-type="knowledge-resolution"]');
                const resolutionQuestion = document.getElementById("kb-resolution-question");
                const resolutionMode = document.querySelector(`[name="kb-resolution-mode"][value="${mode}"]`);
                if (resolutionQuestion) resolutionQuestion.value = question;
                if (resolutionMode) resolutionMode.checked = true;
                resolutionTab?.click();
                resolveKnowledgeQuestion();
            });
        } catch (error) {
            output.innerHTML = `<div class="kb-coverage-warning error">${escapeHtml(error.message)}</div>`;
        }
    }

    function resolutionStep(title, key, value) {
        return `
            <article class="kb-resolution-step" data-resolution-key="${escapeHtml(key)}">
                <div class="kb-resolution-step__head">
                    <div><span>Step</span><h3>${escapeHtml(title)}</h3></div>
                    <button type="button" class="icon-button js-resolution-copy" data-resolution-copy="${escapeHtml(key)}" title="Copy">⧉</button>
                </div>
                <pre class="ia-code-block">${escapeHtml(JSON.stringify(value ?? {}, null, 2))}</pre>
            </article>
        `;
    }

    function renderResolution(trace) {
        const tree = document.getElementById("kb-resolution-tree");
        const details = document.getElementById("kb-resolution-details");
        const exports = document.getElementById("kb-resolution-exports");
        const status = document.getElementById("kb-resolution-status");
        const warnings = trace.debug_information?.warnings || [];
        status.innerHTML = `
            <div class="kb-coverage-summary">
                <div><span>Mode</span><strong>${escapeHtml(trace.mode)}</strong></div>
                <div><span>Coverage</span><strong>${escapeHtml(trace.knowledge_coverage?.score ?? 0)}%</strong></div>
                <div><span>Execution</span><strong>${escapeHtml(trace.powerbi_execution?.status || "Unknown")}</strong></div>
                <div><span>Time</span><strong>${escapeHtml(trace.debug_information?.execution_time_ms ?? 0)} ms</strong></div>
            </div>
            ${warnings.map((warning) => `<div class="kb-coverage-warning">${escapeHtml(warning)}</div>`).join("")}
        `;
        tree.innerHTML = (trace.decision_tree || []).map((node, index) => `
            ${index ? '<span class="kb-tree-arrow" aria-hidden="true">↓</span>' : ""}
            <button type="button" class="kb-tree-node" data-node-id="${escapeHtml(node.id)}">
                <strong>${escapeHtml(node.label)}</strong>
                <span>${escapeHtml(typeof node.value === "object" ? JSON.stringify(node.value) : node.value ?? "")}</span>
            </button>
        `).join("");
        const steps = [
            ["1. Question Analysis", "question_analysis"],
            ["2. Entity Extraction", "entities"],
            ["3. Knowledge Lookup", "knowledge_lookup"],
            ["4. Business Rules", "business_rules"],
            ["5. Power BI Resolution", "powerbi_resolution"],
            ["6. JSON Intent", "json_intent"],
            ["7. DAX Generation", "dax_generation"],
            ["8. Power BI Execution", "powerbi_execution"],
            ["9. AI Response", "ai_response"],
            ["10. Knowledge Coverage", "knowledge_coverage"],
            ["11. Decision Tree", "decision_tree"],
            ["12. Debug Information", "debug_information"],
        ];
        details.innerHTML = steps.map(([title, key]) => resolutionStep(title, key, trace[key])).join("");
        details.querySelectorAll(".js-resolution-copy").forEach((button) => {
            button.addEventListener("click", async () => {
                await navigator.clipboard.writeText(JSON.stringify(trace[button.dataset.resolutionCopy] ?? {}, null, 2));
                button.title = "Copied";
            });
        });
        const nodeDetail = document.getElementById("kb-resolution-node-detail");
        tree.querySelectorAll(".kb-tree-node").forEach((button) => {
            button.addEventListener("click", () => {
                const node = (trace.decision_tree || []).find((item) => item.id === button.dataset.nodeId);
                const related = (trace.knowledge_lookup || []).filter((item) => item.record_id && item.record_id === node?.record_id);
                nodeDetail.hidden = false;
                nodeDetail.textContent = JSON.stringify({node, related_records: related}, null, 2);
                tree.querySelectorAll(".kb-tree-node").forEach((item) => item.classList.toggle("active", item === button));
            });
        });
        exports.hidden = false;
        exports.querySelectorAll("[data-resolution-export]").forEach((link) => {
            link.href = `/knowledge-base/api/resolution/${encodeURIComponent(trace.trace_id)}/export/${link.dataset.resolutionExport}/`;
        });
    }

    async function resolveKnowledgeQuestion() {
        const question = document.getElementById("kb-resolution-question").value.trim();
        const mode = document.querySelector('[name="kb-resolution-mode"]:checked')?.value || "Production";
        const status = document.getElementById("kb-resolution-status");
        if (!question) {
            status.innerHTML = '<div class="kb-coverage-warning error">User Question is required.</div>';
            return;
        }
        const button = document.getElementById("kb-resolve-question");
        button.disabled = true;
        button.textContent = "Resolving...";
        status.innerHTML = '<p class="kb-coverage-empty">Resolving intent, knowledge, DAX and Power BI...</p>';
        try {
            const payload = await fetchJson("/knowledge-base/api/resolution/", {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({question, mode}),
            });
            renderResolution(payload.trace);
        } catch (error) {
            status.innerHTML = `<div class="kb-coverage-warning error">${escapeHtml(error.message)}</div>`;
        } finally {
            button.disabled = false;
            button.textContent = "Resolve Question";
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

    async function saveKnowledgeItem(statusOverride) {
        const payload = collectPayload();
        if (statusOverride) payload.validation_status = statusOverride;
        const editing = state.editingItem;
        const response = await fetchJson(`/knowledge-base/api/${state.resourceType}/${editing ? `${editing.id}/` : ""}`, {
            method: editing ? "PUT" : "POST",
            headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
            body: JSON.stringify(payload),
        });
        state.editingItem = response.item || editing;
        setModalOpen(false);
        showMessage(statusOverride === "Validated" ? "KPI validated." : "Knowledge item saved.", false);
        await loadItems();
    }

    async function runKpiTest(executePowerBI) {
        if (!state.editingItem) return;
        const output = document.getElementById("kb-kpi-test-output");
        if (output) {
            output.hidden = false;
            output.textContent = executePowerBI ? "Testing KPI and Power BI mapping..." : "Building AI answer preview...";
        }
        try {
            const payload = await fetchJson(`/knowledge-base/api/kpi-dictionary/${state.editingItem.id}/test/`, {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({execute_powerbi: executePowerBI}),
            });
            if (output) {
                output.textContent = executePowerBI
                    ? JSON.stringify(payload.test, null, 2)
                    : payload.test.example_ai_answer;
            }
        } catch (error) {
            if (output) output.textContent = error.message;
        }
    }

    function analyticsBars(title, rows, key) {
        const maximum = Math.max(1, ...(rows || []).map((row) => row.count || 0));
        return `<article class="placeholder-panel kb-analytics-chart">
            <h3>${escapeHtml(title)}</h3>
            ${(rows || []).map((row) => `<div class="kb-analytics-bar">
                <span>${escapeHtml(row[key] || "Unknown")}</span>
                <i style="--bar-width:${Math.round((row.count || 0) / maximum * 100)}%"></i>
                <strong>${escapeHtml(row.count || 0)}</strong>
            </div>`).join("")}
        </article>`;
    }

    async function loadSynonymAnalytics() {
        updateToolbar();
        const panel = document.getElementById("kb-synonym-analytics-panel");
        panel.innerHTML = '<p class="kb-coverage-empty">Loading synonym analytics...</p>';
        try {
            const payload = await fetchJson("/knowledge-base/api/synonym-analytics/");
            const data = payload.analytics || {};
            const summary = data.summary || {};
            panel.innerHTML = `
                <div class="kb-kpi-grid">
                    ${[
                        ["Total Synonyms", summary.total], ["Active Synonyms", summary.active],
                        ["Validated", summary.validated], ["Draft", summary.draft],
                        ["Ambiguous", summary.ambiguous], ["Unused", summary.unused],
                        ["AI Generated", summary.ai_generated], ["Total Usages", summary.total_usages],
                    ].map(([label, value]) => `<div class="placeholder-panel kb-kpi-card"><span class="summary-label">${escapeHtml(label)}</span><strong>${escapeHtml(value ?? 0)}</strong></div>`).join("")}
                </div>
                <div class="kb-analytics-grid">
                    ${analyticsBars("By Entity Type", data.by_entity_type, "entity_type")}
                    ${analyticsBars("By Language", data.by_language, "language")}
                    ${analyticsBars("By Source", data.by_source, "synonym_source")}
                    ${analyticsBars("By Validation Status", data.by_status, "validation_status")}
                    ${analyticsBars("Usage Trend", data.usage_trend, "day")}
                </div>
                ${["most_used", "never_used", "ambiguous"].map((name) => `
                    <article class="placeholder-panel">
                        <h3>${escapeHtml(name.replaceAll("_", " "))}</h3>
                        <div class="table-scroll"><table class="data-table">
                            <thead><tr><th>Synonym</th><th>Canonical Term</th><th>Entity Type</th><th>Usage</th><th>Status</th><th>Last Used</th></tr></thead>
                            <tbody>${(data[name] || []).map((row) => `<tr><td>${escapeHtml(row.synonym)}</td><td>${escapeHtml(row.canonical_term)}</td><td>${escapeHtml(row.entity_type)}</td><td>${escapeHtml(row.usage_count)}</td><td>${escapeHtml(row.validation_status)}</td><td>${escapeHtml(row.last_used_at || "Never")}</td></tr>`).join("") || '<tr><td colspan="6">No records.</td></tr>'}</tbody>
                        </table></div>
                    </article>
                `).join("")}
            `;
        } catch (error) {
            panel.innerHTML = `<div class="kb-coverage-warning error">${escapeHtml(error.message)}</div>`;
        }
    }

    async function runSynonymResolutionTest() {
        const question = document.getElementById("kb-synonym-test-question").value.trim();
        const output = document.getElementById("kb-synonym-test-result");
        if (!question) {
            output.innerHTML = '<div class="kb-coverage-warning error">Question is required.</div>';
            return;
        }
        output.innerHTML = '<p class="kb-coverage-empty">Resolving synonyms...</p>';
        try {
            const payload = await fetchJson("/knowledge-base/api/synonym-resolution-test/", {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({
                    question,
                    section: document.getElementById("kb-synonym-test-section").value,
                    mode: document.querySelector('[name="kb-synonym-test-mode"]:checked')?.value || "Production",
                    count_usage: document.getElementById("kb-count-test-usage").checked,
                }),
            });
            const result = payload.result || {};
            output.innerHTML = `
                ${result.requires_clarification ? `<div class="kb-coverage-warning">${escapeHtml(result.clarification_question)}</div>` : ""}
                <div class="kb-coverage-summary"><div><span>Language</span><strong>${escapeHtml(result.language)}</strong></div><div><span>Mode</span><strong>${escapeHtml(result.mode)}</strong></div><div><span>Entities</span><strong>${escapeHtml(result.resolved_entities?.length || 0)}</strong></div></div>
                <div class="kb-coverage-items">${(result.resolved_entities || []).map((item) => `
                    <article class="kb-coverage-item used"><strong>${escapeHtml(item.matched_text)}</strong><span>${escapeHtml(item.canonical_term)} → ${escapeHtml(item.normalized_value)}</span><small>${escapeHtml(item.entity_type)} · ${escapeHtml(item.match_type)} · ${escapeHtml(item.synonym_source)} · ${escapeHtml(item.confidence)}%</small></article>
                `).join("")}</div>
                <details class="kb-coverage-debug" open><summary>Complete JSON</summary><pre class="ia-code-block">${escapeHtml(JSON.stringify(result, null, 2))}</pre></details>
            `;
        } catch (error) {
            output.innerHTML = `<div class="kb-coverage-warning error">${escapeHtml(error.message)}</div>`;
        }
    }

    async function loadSynonymThreshold() {
        const section = document.getElementById("kb-synonym-test-section")?.value;
        if (!section) return;
        try {
            const payload = await fetchJson(`/knowledge-base/api/synonym-settings/${encodeURIComponent(section)}/`);
            document.getElementById("kb-synonym-threshold").value = payload.settings?.ambiguity_threshold ?? 90;
        } catch (error) {
            showMessage(error.message, true);
        }
    }

    async function saveSynonymThreshold() {
        const section = document.getElementById("kb-synonym-test-section")?.value;
        const ambiguityThreshold = document.getElementById("kb-synonym-threshold")?.value;
        if (!section) return;
        try {
            await fetchJson(`/knowledge-base/api/synonym-settings/${encodeURIComponent(section)}/`, {
                method: "PUT",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: JSON.stringify({ambiguity_threshold: ambiguityThreshold}),
            });
            showMessage("Ambiguity threshold saved.", false);
        } catch (error) {
            showMessage(error.message, true);
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
    const synonymImportButton = document.getElementById("kb-import-synonyms");
    const synonymImportFile = document.getElementById("kb-import-synonyms-file");
    synonymImportButton?.addEventListener("click", () => synonymImportFile?.click());
    synonymImportFile?.addEventListener("change", async () => {
        const file = synonymImportFile.files?.[0];
        if (!file) return;
        synonymImportButton.disabled = true;
        const formData = new FormData();
        formData.append("file", file);
        try {
            const payload = await fetchJson("/knowledge-base/synonyms/import/", {
                method: "POST",
                headers: {"X-CSRFToken": csrfToken(), "Accept": "application/json"},
                body: formData,
            });
            const result = payload.summary || {};
            const errorPreview = (result.errors || [])
                .slice(0, 5)
                .map((item) => `Row ${item.row}: ${item.message}`)
                .join(" | ");
            showMessage(
                `Import completed. Total: ${result.total_rows || 0}; Created: ${result.created || 0}; ` +
                `Updated: ${result.updated || 0}; Skipped: ${result.skipped || 0}; Errors: ${result.error_count || 0}` +
                (errorPreview ? `. ${errorPreview}` : ""),
                Boolean(result.error_count),
            );
            await loadItems();
        } catch (error) {
            showMessage(error.message, true);
        } finally {
            synonymImportButton.disabled = false;
            synonymImportFile.value = "";
        }
    });
    document.getElementById("kb-run-coverage")?.addEventListener("click", runCoverageTest);
    document.getElementById("kb-run-synonym-test")?.addEventListener("click", runSynonymResolutionTest);
    document.getElementById("kb-save-synonym-threshold")?.addEventListener("click", saveSynonymThreshold);
    document.getElementById("kb-synonym-test-section")?.addEventListener("change", loadSynonymThreshold);
    document.getElementById("kb-resolve-question")?.addEventListener("click", resolveKnowledgeQuestion);
    document.getElementById("kb-generate")?.addEventListener("click", generateKnowledge);
    document.getElementById("kb-center-message-ok")?.addEventListener("click", hideMessage);
    document.querySelectorAll("[data-kb-modal-close]").forEach((button) => button.addEventListener("click", () => setModalOpen(false)));
    document.querySelectorAll("[data-kpi-action]").forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                const action = button.dataset.kpiAction;
                if (action === "draft") {
                    await saveKnowledgeItem("Draft");
                } else if (action === "validate") {
                    await saveKnowledgeItem("Validated");
                } else if (action === "duplicate" && state.editingItem) {
                    await fetchJson(`/knowledge-base/api/kpi-dictionary/${state.editingItem.id}/duplicate/`, {
                        method: "POST",
                        headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json"},
                    });
                    setModalOpen(false);
                    showMessage("KPI duplicated as Draft.", false);
                    await loadItems();
                } else if (action === "test") {
                    await runKpiTest(true);
                } else if (action === "preview") {
                    await runKpiTest(false);
                }
            } catch (error) {
                showMessage(error.message, true);
            }
        });
    });
    [sectionFilter, statusFilter, activeFilter].forEach((filter) => filter?.addEventListener("change", loadItems));
    ["kb-synonym-entity", "kb-synonym-language", "kb-synonym-source", "kb-synonym-match", "kb-synonym-quick", "kb-synonym-ambiguous", "kb-synonym-owner", "kb-synonym-min-usage", "kb-synonym-min-confidence"].forEach((id) => {
        const filter = document.getElementById(id);
        const eventName = filter?.tagName === "INPUT" ? "input" : "change";
        filter?.addEventListener(eventName, () => {
            clearTimeout(filter._timer);
            filter._timer = setTimeout(loadItems, 200);
        });
    });
    searchInput?.addEventListener("keyup", () => {
        clearTimeout(searchInput._timer);
        searchInput._timer = setTimeout(loadItems, 250);
    });
    form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            await saveKnowledgeItem();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    fillSectionSelect(sectionFilter, true, false);
    fillSectionSelect(document.getElementById("kb-test-section"), false, false);
    fillSectionSelect(document.getElementById("kb-generate-section"), true, false);
    fillSectionSelect(document.getElementById("kb-synonym-test-section"), false, false);
    loadSynonymThreshold();
    updateToolbar();
    loadOverview();
}());
