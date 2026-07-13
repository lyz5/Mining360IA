(function () {
    const root = document.querySelector("[data-browser-app]");
    if (!root) return;

    const state = {
        browsers: [],
        activeBrowser: null,
        previewData: null,
        previewFilters: [],
        previewFilterPanelOpen: false,
        previewSort: {
            columnIndex: null,
            direction: "asc",
        },
        editingRecordId: null,
        importFile: null,
        importPreview: null,
        previewLimit: "1000",
        browserSearch: "",
        browserStatusFilter: "all",
    };

    const initialBrowsersScript = document.getElementById("browser-state-data");
    if (initialBrowsersScript) {
        try {
            state.browsers = JSON.parse(initialBrowsersScript.textContent || "[]") || [];
        } catch (error) {
            state.browsers = [];
        }
    }

    const els = {
        list: root.querySelector("[data-browser-list]"),
        browserPane: root.querySelector("[data-browser-pane]"),
        browserPaneToggle: root.querySelector("[data-browser-pane-toggle]"),
        browserSearch: root.querySelector("[data-browser-search]"),
        browserStatusFilter: root.querySelector("[data-browser-status-filter]"),
        browserOrderSave: root.querySelector("[data-browser-order-save]"),
        form: document.querySelector("[data-browser-form]"),
        formTitle: document.querySelector("[data-browser-form-title]"),
        browserId: document.querySelector("[data-browser-id]"),
        newButton: root.querySelector("[data-browser-new]"),
        previewButtons: document.querySelectorAll("[data-browser-preview]"),
        deleteButtons: document.querySelectorAll("[data-browser-delete]"),
        status: document.querySelector("[data-browser-status]"),
        columnForm: document.querySelector("[data-column-form]"),
        columnId: document.querySelector("[data-column-id]"),
        columnSubmit: document.querySelector("[data-column-submit]"),
        lookupToggle: document.querySelector("[data-lookup-toggle]"),
        lookupFields: document.querySelectorAll("[data-lookup-field]"),
        lookupSource: document.querySelector("[data-lookup-source]"),
        lookupValueColumn: document.querySelector("[data-lookup-value-column]"),
        lookupLabelColumn: document.querySelector("[data-lookup-label-column]"),
        lookupFilterColumn: document.querySelector("[data-lookup-filter-column]"),
        columnOrderSave: document.querySelector("[data-column-order-save]"),
        previewSection: root.querySelector("[data-preview-section]"),
        previewHead: root.querySelector("[data-preview-head]"),
        previewBody: root.querySelector("[data-preview-body]"),
        previewRowCount: root.querySelector("[data-browser-row-count]"),
        previewLimit: root.querySelector("[data-browser-preview-limit]"),
        previewFilterToggle: root.querySelector("[data-preview-filter-toggle]"),
        previewFilterModal: document.querySelector("[data-preview-filter-modal]"),
        previewFilterPanel: document.querySelector("[data-preview-filter-panel]"),
        previewFilterStack: document.querySelector("[data-preview-filter-stack]"),
        previewFilterAdd: document.querySelector("[data-preview-filter-add]"),
        previewFilterApply: document.querySelector("[data-preview-filter-apply]"),
        previewFilterReset: document.querySelector("[data-preview-filter-reset]"),
        exportButton: root.querySelector("[data-browser-export]"),
        previewFullscreen: root.querySelector("[data-browser-fullscreen]"),
        runtimeTitle: root.querySelector("[data-runtime-title]"),
        recordNew: root.querySelector("[data-record-new]"),
        recordEdit: root.querySelector("[data-record-edit]"),
        recordDelete: root.querySelector("[data-record-delete]"),
        recordOpen: root.querySelector("[data-record-open]"),
        recordForm: document.querySelector("[data-record-form]"),
        importTrigger: root.querySelector("[data-import-trigger]"),
        importFile: root.querySelector("[data-import-file]"),
        columnTable: document.querySelector("[data-column-table]"),
        definitionModal: document.querySelector("[data-definition-modal]"),
        recordModal: document.querySelector("[data-record-modal]"),
        centerMessage: document.querySelector("[data-browser-center-message]"),
        centerMessageText: document.querySelector("[data-browser-center-message-text]"),
        centerMessageActions: document.querySelector("[data-browser-center-message-actions]"),
        centerMessageOk: document.querySelector("[data-browser-center-message-ok]"),
        importModal: document.querySelector("[data-import-modal]"),
        importSummary: document.querySelector("[data-import-summary]"),
        importBrowserName: document.querySelector("[data-import-browser-name]"),
        importFileName: document.querySelector("[data-import-file-name]"),
        importRowCount: document.querySelector("[data-import-row-count]"),
        importDuplicateMode: document.querySelector("[data-import-duplicate-mode]"),
        importCommitRows: document.querySelector("[data-import-commit-rows]"),
        importProgressBar: document.querySelector("[data-import-progress-bar]"),
        importProgressText: document.querySelector("[data-import-progress-text]"),
        importFileHead: document.querySelector("[data-import-file-head]"),
        importFileBody: document.querySelector("[data-import-file-body]"),
        importMapBody: document.querySelector("[data-import-map-body]"),
        importCommitButton: document.querySelector("[data-import-commit]"),
    };

    let centerMessageTimer = null;
    let openModalCount = 0;
    let centerMessageSticky = false;
    let importStatusTimer = null;
    let draggedColumnRow = null;
    let draggedBrowserRow = null;

    function csrfToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken(),
                "X-Requested-With": "XMLHttpRequest",
                ...(options.headers || {}),
            },
            ...options,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok !== true) {
            throw new Error(payload.error || `Request failed with status ${response.status}`);
        }
        return payload;
    }

    function showCenterMessage(message, isError = false, sticky = false) {
        if (!els.centerMessage || !els.centerMessageText) return;
        clearTimeout(centerMessageTimer);
        centerMessageSticky = Boolean(sticky && message);
        if (!message) {
            els.centerMessage.hidden = true;
            els.centerMessage.classList.remove("visible", "error", "loading");
            els.centerMessageText.textContent = "";
            if (els.centerMessageActions) els.centerMessageActions.hidden = true;
            return;
        }
        els.centerMessageText.textContent = message;
        els.centerMessage.hidden = false;
        els.centerMessage.classList.toggle("error", Boolean(isError));
        els.centerMessage.classList.toggle("loading", /(?:\.{3}|loading|saving|syncing|deleting|importing)/i.test(message));
        els.centerMessage.classList.add("visible");
        if (els.centerMessageActions) els.centerMessageActions.hidden = !(isError || sticky);
        const duration = (isError || sticky) ? 0 : (/\.\.\.$/.test(message) ? 0 : 2400);
        if (duration > 0) {
            centerMessageTimer = setTimeout(() => {
                els.centerMessage.hidden = true;
                els.centerMessage.classList.remove("visible", "error", "loading");
                els.centerMessageText.textContent = "";
                if (els.centerMessageActions) els.centerMessageActions.hidden = true;
            }, duration);
        }
    }

    function hideCenterMessage() {
        centerMessageSticky = false;
        clearTimeout(centerMessageTimer);
        if (els.centerMessage) {
            els.centerMessage.hidden = true;
            els.centerMessage.classList.remove("visible", "error", "loading");
        }
        if (els.centerMessageText) els.centerMessageText.textContent = "";
        if (els.centerMessageActions) els.centerMessageActions.hidden = true;
    }

    function setStatus(message, isError = false, sticky = false) {
        els.status.textContent = message || "";
        els.status.classList.toggle("error", Boolean(isError));
        showCenterMessage(message, isError, sticky);
    }

    function setButtonsDisabled(buttons, disabled) {
        buttons.forEach((button) => {
            button.disabled = disabled;
        });
    }

    function setHtml(element, html) {
        if (element) {
            element.innerHTML = html;
        }
    }

    function inferPreviewCellType(value) {
        if (value === null || value === undefined || value === "") {
            return "text";
        }
        const text = String(value).trim();
        if (!text) {
            return "text";
        }
        if (/^-?\d+(?:\.\d+)?$/.test(text)) {
            return "number";
        }
        if (/^\d{4}-\d{2}-\d{2}(?:[ T].*)?$/.test(text)) {
            return "date";
        }
        return "text";
    }

    function comparePreviewValues(left, right) {
        const leftType = inferPreviewCellType(left);
        const rightType = inferPreviewCellType(right);
        const leftText = String(left ?? "").trim();
        const rightText = String(right ?? "").trim();
        if (leftType === "number" && rightType === "number") {
            return Number(leftText) - Number(rightText);
        }
        if (leftType === "date" && rightType === "date") {
            return new Date(leftText).getTime() - new Date(rightText).getTime();
        }
        return leftText.localeCompare(rightText, undefined, { numeric: true, sensitivity: "base" });
    }

    function inferPreviewColumnTypes(preview) {
        const explicitTypes = Array.isArray(preview?.column_types) ? preview.column_types : [];
        if (explicitTypes.length) {
            return explicitTypes.map((type) => {
                const normalized = String(type || "").trim().toLowerCase();
                if (normalized === "date" || normalized === "datetime" || normalized === "datetime2") {
                    return "date";
                }
                if (normalized === "integer" || normalized === "decimal" || normalized === "number") {
                    return "number";
                }
                return "text";
            });
        }
        const rows = Array.isArray(preview?.row_values) ? preview.row_values : [];
        return (preview?.columns || []).map((_, columnIndex) => {
            for (const row of rows) {
                const sample = row && row.length > columnIndex ? row[columnIndex] : "";
                const text = String(sample ?? "").trim();
                if (!text) continue;
                if (/^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/.test(text)) return "date";
                if (/^-?\d+(?:\.\d+)?$/.test(text)) return "number";
                return "text";
            }
            return "text";
        });
    }

    function createPreviewFilter(columnIndex = 0) {
        return {
            id: `filter-${Date.now()}-${Math.random().toString(16).slice(2)}`,
            columnIndex,
            operator: "equal",
            value: "",
            joiner: "AND",
        };
    }

    function clampPreviewIndex(value, preview) {
        const maxIndex = Math.max((preview?.columns || []).length - 1, 0);
        const index = Number(value);
        if (Number.isNaN(index)) {
            return 0;
        }
        return Math.min(Math.max(index, 0), maxIndex);
    }

    function getFilterColumnType(preview, filter) {
        const types = inferPreviewColumnTypes(preview);
        return types[clampPreviewIndex(filter.columnIndex, preview)] || "text";
    }

    function setPreviewFilterPanelOpen(isOpen) {
        state.previewFilterPanelOpen = Boolean(isOpen);
        document.body.classList.toggle("preview-filter-modal-open", state.previewFilterPanelOpen);
        if (els.previewFilterModal) {
            els.previewFilterModal.hidden = !state.previewFilterPanelOpen;
            els.previewFilterModal.setAttribute("aria-hidden", state.previewFilterPanelOpen ? "false" : "true");
        }
        if (els.previewFilterPanel) {
            els.previewFilterPanel.classList.toggle("is-open", state.previewFilterPanelOpen);
        }
        if (els.previewFilterToggle) {
            els.previewFilterToggle.setAttribute("aria-expanded", state.previewFilterPanelOpen ? "true" : "false");
            els.previewFilterToggle.textContent = state.previewFilterPanelOpen ? "Close filters" : "Filters";
        }
    }

    function normalizeComparableValue(value, type) {
        const text = String(value ?? "").trim();
        if (!text) {
            return null;
        }
        if (type === "number") {
            const numeric = Number(text.replaceAll(",", "."));
            return Number.isNaN(numeric) ? null : numeric;
        }
        if (type === "date") {
            const parsed = Date.parse(text);
            return Number.isNaN(parsed) ? null : parsed;
        }
        return text.toLowerCase();
    }

    function comparePreviewValuesWithType(left, right, type) {
        const leftValue = normalizeComparableValue(left, type);
        const rightValue = normalizeComparableValue(right, type);
        if (leftValue === null && rightValue === null) return 0;
        if (leftValue === null) return 1;
        if (rightValue === null) return -1;
        if (type === "text") {
            return String(leftValue).localeCompare(String(rightValue), undefined, { sensitivity: "base" });
        }
        if (leftValue < rightValue) return -1;
        if (leftValue > rightValue) return 1;
        return 0;
    }

    function getPreviewColumnLabel(preview, index) {
        const columns = preview?.columns || [];
        return columns[index] || columns[0] || "";
    }

    function buildPreviewFilterClause(preview, filter) {
        const value = String(filter.value ?? "").trim();
        if (!value) return "1 = 1";
        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        const columnName = getPreviewColumnLabel(preview, columnIndex);
        if (!columnName) return "1 = 1";
        const columnSql = `[${String(columnName).replaceAll("]", "]]")}]`;
        const type = getFilterColumnType(preview, filter);
        const operator = String(filter.operator || "equal").toLowerCase();
        if (type === "date") {
            return `CONVERT(date, ${columnSql}) = '${value.slice(0, 10).replaceAll("'", "''")}'`;
        }
        if (operator === "like") {
            return `${columnSql} LIKE N'%${value.replaceAll("'", "''")}%'`;
        }
        if (type === "number") {
            return `${columnSql} = ${value}`;
        }
        return `${columnSql} = N'${value.replaceAll("'", "''")}'`;
    }

    function buildPreviewSql(preview) {
        if (!preview || !preview.columns || !preview.columns.length) {
            return preview?.sql || "";
        }
        const activeFilters = (state.previewFilters || []).filter((filter) => String(filter.value ?? "").trim());
        if (!activeFilters.length) {
            return preview.sql || "";
        }
        const whereClause = activeFilters.map((filter, index) => {
            const clause = buildPreviewFilterClause(preview, filter);
            if (index === 0) return clause;
            return `${String(filter.joiner || "AND").toUpperCase()} ${clause}`;
        }).join(" ");
        return `${preview.sql || ""}\n-- Filters applied\nWHERE ${whereClause}`;
    }

    function rowMatchesFilter(row, preview, filter) {
        const value = String(filter.value ?? "").trim();
        if (!value) return true;
        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        const cell = row && row.length > columnIndex ? row[columnIndex] : "";
        const cellText = String(cell ?? "").trim();
        if (!cellText) return false;
        const type = getFilterColumnType(preview, filter);
        const operator = String(filter.operator || "equal").toLowerCase();
        if (type === "date") {
            return cellText.slice(0, 10) === value.slice(0, 10);
        }
        if (operator === "like") {
            return cellText.toLowerCase().includes(value.toLowerCase());
        }
        if (type === "number") {
            return cellText === value;
        }
        return cellText.toLowerCase() === value.toLowerCase();
    }

    function evaluatePreviewRow(row, preview) {
        const activeFilters = (state.previewFilters || []).filter((filter) => String(filter.value ?? "").trim());
        if (!activeFilters.length) {
            return true;
        }
        let result = rowMatchesFilter(row, preview, activeFilters[0]);
        for (let index = 1; index < activeFilters.length; index += 1) {
            const filter = activeFilters[index];
            const nextMatch = rowMatchesFilter(row, preview, filter);
            result = String(filter.joiner || "AND").toUpperCase() === "OR" ? (result || nextMatch) : (result && nextMatch);
        }
        return result;
    }

    function getFilteredPreviewRows(preview) {
        const rows = Array.isArray(preview?.row_values) ? preview.row_values : [];
        return rows.filter((row) => evaluatePreviewRow(row, preview));
    }

    function getSortedPreviewRows(preview, rows) {
        const sort = state.previewSort || {};
        const columnIndex = Number(sort.columnIndex);
        if (sort.columnIndex === null || Number.isNaN(columnIndex)) {
            return rows.slice();
        }
        const direction = String(sort.direction || "asc").toLowerCase() === "desc" ? -1 : 1;
        const types = inferPreviewColumnTypes(preview);
        const type = types[columnIndex] || "text";
        return rows.slice().sort((leftRow, rightRow) => {
            const leftValue = leftRow && leftRow.length > columnIndex ? leftRow[columnIndex] : "";
            const rightValue = rightRow && rightRow.length > columnIndex ? rightRow[columnIndex] : "";
            return comparePreviewValuesWithType(leftValue, rightValue, type) * direction;
        });
    }

    function getSortedAndFilteredPreviewRows(preview) {
        return getSortedPreviewRows(preview, getFilteredPreviewRows(preview));
    }

    function renderFilterOperatorOptions(type, currentOperator) {
        const operators = type === "date"
            ? [{ value: "equal", label: "=" }]
            : [{ value: "equal", label: "=" }, { value: "like", label: "LIKE" }];
        return operators.map((operator) => {
            const selected = String(currentOperator || "equal") === operator.value ? " selected" : "";
            return `<option value="${operator.value}"${selected}>${operator.label}</option>`;
        }).join("");
    }

    function renderFilterRowHtml(preview, filter, index, columnTypes) {
        const columns = preview?.columns || [];
        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        const type = columnTypes[columnIndex] || "text";
        const joinerHtml = index > 0
            ? `
                <label class="preview-filter-joiner">
                    <span>Link</span>
                    <select data-preview-filter-joiner="${index}">
                        <option value="AND"${String(filter.joiner || "AND").toUpperCase() === "AND" ? " selected" : ""}>AND</option>
                        <option value="OR"${String(filter.joiner || "AND").toUpperCase() === "OR" ? " selected" : ""}>OR</option>
                    </select>
                </label>
            `
            : "";
        const columnOptions = columns.map((column, idx) => {
            const selected = idx === columnIndex ? " selected" : "";
            return `<option value="${idx}"${selected}>${escapeHtml(column)}</option>`;
        }).join("");
        const valueType = type === "date" ? "date" : "text";
        const valueInput = valueType === "date"
            ? `<input type="date" class="preview-filter-input" data-preview-filter-value="${index}" value="${escapeHtml(String(filter.value || "").slice(0, 10))}" aria-label="Filter value">`
            : `<input type="text" class="preview-filter-input" data-preview-filter-value="${index}" value="${escapeHtml(filter.value || "")}" placeholder="Value" aria-label="Filter value">`;
        return `
            <div class="preview-filter-row${index === 0 ? " preview-filter-row-first" : ""}" data-preview-filter-row="${index}">
                ${joinerHtml}
                <label class="preview-filter-control">
                    <span>Column</span>
                    <select data-preview-filter-column="${index}">
                        ${columnOptions}
                    </select>
                </label>
                <label class="preview-filter-control preview-filter-operator">
                    <span>Operator</span>
                    <select data-preview-filter-operator="${index}">
                        ${renderFilterOperatorOptions(type, filter.operator)}
                    </select>
                </label>
                <label class="preview-filter-control preview-filter-value">
                    <span>Value</span>
                    <div class="preview-filter-field">
                        ${valueInput}
                    </div>
                </label>
                <button type="button" class="icon-button preview-filter-remove" data-preview-filter-remove="${index}" aria-label="Remove filter" title="Remove filter"></button>
            </div>
        `;
    }

    function syncPreviewFilterRow(container, preview, index) {
        const row = container.querySelector(`[data-preview-filter-row="${index}"]`);
        if (!row) return;
        const filter = state.previewFilters[index];
        if (!filter) return;
        const columnTypes = inferPreviewColumnTypes(preview);
        const type = columnTypes[clampPreviewIndex(filter.columnIndex, preview)] || "text";
        const operatorSelect = row.querySelector("[data-preview-filter-operator]");
        const valueField = row.querySelector(".preview-filter-field");
        const value = String(filter.value || "");
        if (operatorSelect) {
            const currentOperator = type === "date" ? "equal" : (filter.operator || "equal");
            filter.operator = currentOperator;
            operatorSelect.innerHTML = renderFilterOperatorOptions(type, currentOperator);
            operatorSelect.value = currentOperator;
        }
        if (valueField) {
            const valueType = type === "date" ? "date" : "text";
            valueField.innerHTML = valueType === "date"
                ? `<input type="date" class="preview-filter-input" data-preview-filter-value="${index}" value="${escapeHtml(value.slice(0, 10))}" aria-label="Filter value">`
                : `<input type="text" class="preview-filter-input" data-preview-filter-value="${index}" value="${escapeHtml(value)}" placeholder="Value" aria-label="Filter value">`;
            const input = valueField.querySelector("[data-preview-filter-value]");
            if (input) {
                input.addEventListener("input", () => {
                    const idx = Number(input.dataset.previewFilterValue);
                    if (state.previewFilters[idx]) {
                        state.previewFilters[idx].value = input.value || "";
                    }
                });
            }
        }
    }

    function renderPreviewFilterPanel(preview) {
        if (!els.previewFilterStack || !els.previewFilterModal) return;
        const columnTypes = inferPreviewColumnTypes(preview);
        if (!state.previewFilters.length && (preview?.columns || []).length) {
            state.previewFilters = [createPreviewFilter(0)];
        }
        els.previewFilterStack.innerHTML = state.previewFilters.length
            ? state.previewFilters.map((filter, index) => renderFilterRowHtml(preview, filter, index, columnTypes)).join("")
            : '<div class="empty compact">No columns available.</div>';
        if (els.previewFilterAdd) {
            els.previewFilterAdd.disabled = !(preview?.columns || []).length;
        }
    }

    function bindPreviewFilters(preview) {
        document.querySelectorAll("[data-preview-filter-column]").forEach((element) => {
            element.addEventListener("change", () => {
                const index = Number(element.dataset.previewFilterColumn);
                if (!state.previewFilters[index]) return;
                state.previewFilters[index].columnIndex = Number(element.value) || 0;
                state.previewFilters[index].operator = "equal";
                syncPreviewFilterRow(els.previewFilterStack || document, preview, index);
            });
        });
        document.querySelectorAll("[data-preview-filter-operator]").forEach((element) => {
            element.addEventListener("change", () => {
                const index = Number(element.dataset.previewFilterOperator);
                if (!state.previewFilters[index]) return;
                state.previewFilters[index].operator = element.value || "equal";
            });
        });
        document.querySelectorAll("[data-preview-filter-value]").forEach((element) => {
            element.addEventListener("input", () => {
                const index = Number(element.dataset.previewFilterValue);
                if (!state.previewFilters[index]) return;
                state.previewFilters[index].value = element.value || "";
            });
        });
        document.querySelectorAll("[data-preview-filter-joiner]").forEach((element) => {
            element.addEventListener("change", () => {
                const index = Number(element.dataset.previewFilterJoiner);
                if (!state.previewFilters[index]) return;
                state.previewFilters[index].joiner = element.value || "AND";
            });
        });
        document.querySelectorAll("[data-preview-filter-remove]").forEach((element) => {
            element.addEventListener("click", () => {
                const index = Number(element.dataset.previewFilterRemove);
                state.previewFilters.splice(index, 1);
                if (!state.previewFilters.length && (preview?.columns || []).length) {
                    state.previewFilters = [createPreviewFilter(0)];
                }
                renderPreviewFilterPanel(preview);
                bindPreviewFilters(preview);
                setPreviewFilterPanelOpen(true);
            });
        });
    }

    function getSortedPreviewRows(data) {
        const rows = Array.isArray(data?.row_values) ? data.row_values.slice() : [];
        const sort = state.previewSort || {};
        const columnIndex = Number(sort.columnIndex);
        if (sort.columnIndex === null || Number.isNaN(columnIndex)) {
            return rows;
        }
        const direction = String(sort.direction || "asc").toLowerCase() === "desc" ? -1 : 1;
        return rows.sort((leftRow, rightRow) => direction * comparePreviewValues(leftRow[columnIndex], rightRow[columnIndex]));
    }

    function renderPreviewHeader(columns, visibleColumnIndexes) {
        const activeColumnIndex = state.previewSort.columnIndex === null ? null : Number(state.previewSort.columnIndex);
        const headers = visibleColumnIndexes.map(({ column, index }) => {
            const isActive = activeColumnIndex === index;
            const direction = isActive && String(state.previewSort.direction || "asc").toLowerCase() === "desc" ? "desc" : "asc";
            const arrow = !isActive ? "" : (direction === "asc" ? " ▲" : " ▼");
            return `
                <th scope="col" class="preview-sort-header${isActive ? " active" : ""}" aria-sort="${isActive ? (direction === "asc" ? "ascending" : "descending") : "none"}">
                    <button type="button" class="preview-sort-button" data-preview-sort-column="${index}" aria-label="Sort by ${escapeHtml(column)}">
                        <span>${escapeHtml(column)}</span>
                        <span class="preview-sort-indicator" aria-hidden="true">${arrow}</span>
                    </button>
                </th>
            `;
        }).join("");
        return `<tr><th><input type="checkbox" data-record-select-all aria-label="Select all rows"></th>${headers}</tr>`;
    }

    function bindPreviewHeaderSorting() {
        document.querySelectorAll("[data-preview-sort-column]").forEach((element) => {
            element.addEventListener("click", () => {
                const index = Number(element.dataset.previewSortColumn);
                if (Number.isNaN(index) || !state.previewData) {
                    return;
                }
                if (state.previewSort.columnIndex === index) {
                    state.previewSort.direction = String(state.previewSort.direction || "asc").toLowerCase() === "asc" ? "desc" : "asc";
                } else {
                    state.previewSort.columnIndex = index;
                    state.previewSort.direction = "asc";
                }
                renderPreview(state.previewData, true);
            });
        });
    }

    function normalizeDropdownSearch(value) {
        return String(value || "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, " ")
            .trim();
    }

    function syncSearchableSelect(select) {
        if (!select) return;
        const wrapper = select.closest(".searchable-select");
        if (!wrapper) return;
        const button = wrapper.querySelector(".searchable-select__button");
        const selectedOption = select.options[select.selectedIndex] || select.options[0] || null;
        const label = selectedOption ? String(selectedOption.textContent || "").trim() : "";
        button.textContent = label || select.dataset.searchablePlaceholder || "Search";
        button.title = label || select.dataset.searchablePlaceholder || "Search";
    }

    function refreshSearchableSelect(select) {
        if (!select) return;
        const wrapper = select.closest(".searchable-select");
        if (!wrapper) return;
        const render = wrapper._renderSearchableOptions;
        if (typeof render === "function") {
            render();
        }
        syncSearchableSelect(select);
    }

    function initSearchableSelect(select) {
        if (!select || select.dataset.searchableInitialized === "1") return;
        select.dataset.searchableInitialized = "1";

        const wrapper = document.createElement("div");
        wrapper.className = "searchable-select";
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(select);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "searchable-select__button";
        button.setAttribute("aria-haspopup", "listbox");
        button.setAttribute("aria-expanded", "false");

        const panel = document.createElement("div");
        panel.className = "searchable-select__panel";
        panel.hidden = true;

        const search = document.createElement("input");
        search.type = "search";
        search.className = "searchable-select__search";
        search.placeholder = select.dataset.searchablePlaceholder || "Search...";
        search.autocomplete = "off";

        const list = document.createElement("div");
        list.className = "searchable-select__list";

        panel.appendChild(search);
        panel.appendChild(list);
        wrapper.appendChild(button);
        wrapper.appendChild(panel);

        const renderOptions = () => {
            const queryTerms = normalizeDropdownSearch(search.value).split(/\s+/).filter(Boolean);
            const options = Array.from(select.options || []);
            const items = options.filter((option) => {
                if (!queryTerms.length) return true;
                const searchableValue = normalizeDropdownSearch(
                    `${option.textContent || ""} ${option.value || ""}`
                );
                return queryTerms.every((term) => searchableValue.includes(term));
            });
            list.innerHTML = items.length
                ? items.map((option) => {
                    const selected = option.value === select.value ? " selected" : "";
                    const disabled = option.disabled ? " disabled" : "";
                    return `<button type="button" class="searchable-select__option${selected}${disabled}" data-select-value="${escapeHtml(option.value)}"${option.disabled ? " disabled" : ""}>${escapeHtml(option.textContent || option.value || "")}</button>`;
                }).join("")
                : '<div class="searchable-select__empty">No match</div>';
        };
        wrapper._renderSearchableOptions = renderOptions;
        wrapper._openSearchableSelect = () => {
            wrapper.classList.add("is-open");
            panel.hidden = false;
            button.setAttribute("aria-expanded", "true");
            syncSearchableSelect(select);
            renderOptions();
            window.requestAnimationFrame(() => search.focus());
        };
        wrapper._closeSearchableSelect = () => {
            wrapper.classList.remove("is-open");
            panel.hidden = true;
            button.setAttribute("aria-expanded", "false");
        };

        button.addEventListener("click", () => {
            if (panel.hidden) {
                wrapper._openSearchableSelect();
                return;
            }
            wrapper._closeSearchableSelect();
        });

        search.addEventListener("input", renderOptions);
        list.addEventListener("click", (event) => {
            const item = event.target.closest("[data-select-value]");
            if (!item) return;
            select.value = item.dataset.selectValue || "";
            select.dispatchEvent(new Event("change", { bubbles: true }));
            syncSearchableSelect(select);
            wrapper._closeSearchableSelect();
        });

        select.addEventListener("change", () => syncSearchableSelect(select));

        syncSearchableSelect(select);
        wrapper._closeSearchableSelect();
    }

    function initSearchableSelects(rootNode = document) {
        rootNode.querySelectorAll("[data-searchable-select]").forEach((select) => initSearchableSelect(select));
    }

    function openModal(modal) {
        if (!modal) return;
        modal.hidden = false;
        modal.classList.add("visible");
        openModalCount += 1;
        document.body.classList.add("modal-open");
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove("visible");
        modal.hidden = true;
        openModalCount = Math.max(0, openModalCount - 1);
        if (openModalCount === 0) {
            document.body.classList.remove("modal-open");
        }
    }

    function openDefinitionModal(newBrowser = false) {
        closeModal(els.recordModal);
        if (newBrowser || !state.activeBrowser) {
            resetBrowserForm();
        }
        openModal(els.definitionModal);
    }

    function openRecordModal() {
        closeModal(els.definitionModal);
        openModal(els.recordModal);
    }

    function closeAllModals() {
        closeModal(els.definitionModal);
        closeModal(els.recordModal);
    }

    function formData(form) {
        const data = {};
        const fields = new FormData(form);
        for (const [key, value] of fields.entries()) {
            data[key] = value;
        }
        form.querySelectorAll("input[type='checkbox']").forEach((input) => {
            data[input.name] = input.matches("[data-record-boolean]")
                ? (input.checked ? -1 : 0)
                : input.checked;
        });
        return data;
    }

    function resetBrowserForm() {
        state.activeBrowser = null;
        els.form.reset();
        els.browserId.value = "";
        els.form.querySelector("[name='is_active']").checked = true;
        els.form.querySelector("[name='show_browser_record_id']").checked = true;
        els.form.querySelector("[name='show_eventchain_id']").checked = true;
        els.formTitle.textContent = "New Browser";
        setButtonsDisabled(els.previewButtons, true);
        setButtonsDisabled(els.deleteButtons, true);
        els.columnSubmit.disabled = true;
        resetColumnForm();
        renderColumns([]);
        renderPreview(null);
        setStatus("");
        if (els.previewRowCount) els.previewRowCount.textContent = "0 rows loaded";
        if (els.recordForm) {
            els.recordForm.hidden = true;
            setHtml(els.recordForm, "");
        }
    }

    function fillBrowserForm(browser) {
        state.activeBrowser = browser;
        els.browserId.value = browser.id;
        els.formTitle.textContent = browser.name;
        els.form.elements.name.value = browser.name || "";
        els.form.elements.description.value = browser.description || "";
        els.form.elements.table_name.value = browser.table_name || "";
        els.form.elements.source_view_name.value = browser.source_view_name || "";
        els.form.elements.is_active.checked = Boolean(browser.is_active);
        els.form.elements.show_browser_record_id.checked = browser.show_browser_record_id !== false;
        els.form.elements.show_eventchain_id.checked = browser.show_eventchain_id !== false;
        setButtonsDisabled(els.previewButtons, false);
        setButtonsDisabled(els.deleteButtons, false);
        els.columnSubmit.disabled = false;
        resetColumnForm();
        renderColumns(browser.columns || []);
        renderLookupSources();
        els.previewSection.hidden = false;
        if (els.runtimeTitle) els.runtimeTitle.textContent = browser.name;
        if (els.previewRowCount) els.previewRowCount.textContent = "0 rows loaded";
        renderPreview(null);
        setStatus(browser.last_sync_message || "");
    }

    function renderBrowsers() {
        if (!state.browsers.length) {
            setHtml(els.list, '<div class="empty compact">No Browser configured yet.</div>');
            if (els.browserOrderSave) els.browserOrderSave.disabled = true;
            return;
        }
        const terms = normalizeDropdownSearch(state.browserSearch).split(/\s+/).filter(Boolean);
        const visibleBrowsers = state.browsers.filter((browser) => {
            const statusMatches = state.browserStatusFilter === "all"
                || (state.browserStatusFilter === "active" && browser.is_active)
                || (state.browserStatusFilter === "inactive" && !browser.is_active);
            const searchable = normalizeDropdownSearch(`${browser.name || ""} ${browser.table_name || ""}`);
            return statusMatches && terms.every((term) => searchable.includes(term));
        });
        setHtml(els.list, visibleBrowsers.length ? visibleBrowsers.map((browser) => `
            <div class="browser-list-row" draggable="false" data-browser-row="${browser.id}">
                <button type="button" class="browser-list-drag" aria-label="Move ${escapeHtml(browser.name)}" title="Drag to reorder">
                    <span aria-hidden="true"></span>
                </button>
                <button type="button" class="browser-list-item ${state.activeBrowser && state.activeBrowser.id === browser.id ? "active" : ""}" data-browser-select="${browser.id}">
                    <strong>${escapeHtml(browser.name)}</strong>
                    <span>${escapeHtml(browser.table_name || "-")}</span>
                    <em>${browser.is_active ? "Active" : "Inactive"}</em>
                </button>
            </div>
        `).join("") : '<div class="empty compact">No Browser matches these filters.</div>');
        if (els.browserOrderSave) els.browserOrderSave.disabled = true;
    }

    function markBrowserOrderChanged() {
        if (els.browserOrderSave) els.browserOrderSave.disabled = false;
    }

    async function saveBrowserOrder() {
        const visibleIds = Array.from(els.list.querySelectorAll("[data-browser-row]"))
            .map((row) => Number(row.dataset.browserRow));
        if (!visibleIds.length) return;
        const visibleSet = new Set(visibleIds);
        const browserById = new Map(state.browsers.map((browser) => [Number(browser.id), browser]));
        let visibleIndex = 0;
        const reordered = state.browsers.map((browser) => (
            visibleSet.has(Number(browser.id))
                ? browserById.get(visibleIds[visibleIndex++])
                : browser
        ));

        els.browserOrderSave.disabled = true;
        try {
            const payload = await api("/data-browsers/reorder", {
                method: "POST",
                body: JSON.stringify({ browser_ids: reordered.map((browser) => browser.id) }),
            });
            state.browsers = payload.browsers || reordered;
            renderBrowsers();
            renderLookupSources();
            showCenterMessage("Browser order saved.");
        } catch (error) {
            els.browserOrderSave.disabled = false;
            showCenterMessage(error.message, true, true);
        }
    }

    function setBrowserPaneCollapsed(collapsed) {
        if (!els.browserPane) return;
        els.browserPane.classList.toggle("collapsed", Boolean(collapsed));
        root.classList.toggle("browser-pane-collapsed", Boolean(collapsed));
        if (els.browserPaneToggle) {
            els.browserPaneToggle.setAttribute("aria-label", collapsed ? "Expand Browser panel" : "Collapse Browser panel");
            els.browserPaneToggle.setAttribute("title", collapsed ? "Expand panel" : "Collapse panel");
        }
        localStorage.setItem("mining360BrowserPaneCollapsed", collapsed ? "1" : "0");
    }

    function markBrowserSelection(id) {
        document.querySelectorAll("[data-browser-select]").forEach((button) => {
            button.classList.toggle("active", String(button.dataset.browserSelect) === String(id));
        });
    }

    function renderLookupSources(selectedValue = "") {
        if (!els.lookupSource) return;
        const currentBrowserId = state.activeBrowser ? state.activeBrowser.id : null;
        const options = state.browsers
            .filter((browser) => browser.id !== currentBrowserId)
            .map((browser) => `<option value="${escapeHtml(browser.table_name)}">${escapeHtml(browser.name)}</option>`)
            .join("");
        setHtml(els.lookupSource, '<option value="">Select Browser</option>' + options);
        els.lookupSource.value = selectedValue || "";
        refreshSearchableSelect(els.lookupSource);
        renderLookupColumns(selectedValue || els.lookupSource.value, {});
    }

    async function renderLookupColumns(sourceTable, selected = {}) {
        const selects = [els.lookupValueColumn, els.lookupLabelColumn, els.lookupFilterColumn].filter(Boolean);
        selects.forEach((select) => {
            const emptyLabel = select === els.lookupFilterColumn ? "No filter" : "Select column";
            setHtml(select, `<option value="">${emptyLabel}</option>`);
        });
        if (!sourceTable) return;
        const browser = state.browsers.find((item) => item.table_name === sourceTable);
        if (!browser) return;
        try {
            const payload = await api(`/data-browsers/${browser.id}`);
            const columns = payload.browser.columns || [];
            const options = columns.map((column) => `<option value="${escapeHtml(column.sql_name)}">${escapeHtml(column.display_name)} (${escapeHtml(column.sql_name)})</option>`).join("");
            if (els.lookupValueColumn) {
                setHtml(els.lookupValueColumn, '<option value="">Select column</option>' + options);
                els.lookupValueColumn.value = selected.value || "";
                refreshSearchableSelect(els.lookupValueColumn);
            }
            if (els.lookupLabelColumn) {
                setHtml(els.lookupLabelColumn, '<option value="">Select column</option>' + options);
                els.lookupLabelColumn.value = selected.label || selected.value || "";
                refreshSearchableSelect(els.lookupLabelColumn);
            }
            if (els.lookupFilterColumn) {
                setHtml(els.lookupFilterColumn, '<option value="">No filter</option>' + options);
                els.lookupFilterColumn.value = selected.filter || "";
                refreshSearchableSelect(els.lookupFilterColumn);
            }
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    function renderColumns(columns) {
        if (!columns.length) {
            setHtml(els.columnTable, '<tr><td colspan="10">No configured column.</td></tr>');
            if (els.columnOrderSave) els.columnOrderSave.disabled = true;
            return;
        }
        setHtml(els.columnTable, columns.map((column) => `
            <tr draggable="false" data-column-row="${column.id}">
                <td class="drag-column">
                    <button type="button" class="column-drag-handle" aria-label="Move ${escapeHtml(column.display_name)}" title="Drag to reorder">
                        <span aria-hidden="true"></span>
                    </button>
                </td>
                <td>${escapeHtml(column.display_name)}</td>
                <td>${escapeHtml(column.sql_name)}</td>
                <td>${escapeHtml(column.data_type)}${column.length ? ` (${column.length})` : ""}</td>
                <td>${column.is_required ? "No" : "Yes"}</td>
                <td>${column.is_unique ? "Yes" : "No"}</td>
                <td>${column.is_visible ? "Yes" : "No"}</td>
                <td>${column.is_lookup ? `Yes<br><span class="muted-mini">${escapeHtml(column.lookup_source_name)}</span>` : "No"}</td>
                <td>${column.display_order}</td>
                <td class="row-actions">
                    <button type="button" class="button secondary small" data-column-edit="${column.id}">Edit</button>
                    <button type="button" class="button secondary small danger-soft" data-column-delete="${column.id}">Delete</button>
                </td>
            </tr>
        `).join(""));
        if (els.columnOrderSave) els.columnOrderSave.disabled = true;
    }

    function markColumnOrderChanged() {
        if (els.columnOrderSave) els.columnOrderSave.disabled = false;
        els.columnTable.querySelectorAll("[data-column-row]").forEach((row, index) => {
            const orderCell = row.children[8];
            if (orderCell) orderCell.textContent = String(index + 1);
        });
    }

    async function saveColumnOrder() {
        if (!state.activeBrowser || !els.columnOrderSave) return;
        const columnIds = Array.from(els.columnTable.querySelectorAll("[data-column-row]"))
            .map((row) => Number(row.dataset.columnRow));
        if (!columnIds.length) return;

        els.columnOrderSave.disabled = true;
        els.columnOrderSave.classList.add("is-loading");
        try {
            const payload = await api(`/data-browsers/${state.activeBrowser.id}/columns/reorder`, {
                method: "POST",
                body: JSON.stringify({ column_ids: columnIds }),
            });
            state.activeBrowser.columns = payload.columns || [];
            renderColumns(state.activeBrowser.columns);
            showCenterMessage("Column order saved.");
            await previewData();
        } catch (error) {
            els.columnOrderSave.disabled = false;
            showCenterMessage(error.message, true, true);
        } finally {
            els.columnOrderSave.classList.remove("is-loading");
        }
    }

    function resetColumnForm() {
        els.columnForm.reset();
        els.columnId.value = "";
        if (els.columnForm.elements.allow_null) {
            els.columnForm.elements.allow_null.checked = true;
        }
        els.columnForm.elements.is_visible.checked = true;
        els.columnForm.elements.display_order.value = "0";
        els.columnSubmit.textContent = "Add Column";
        renderLookupSources();
        toggleLookupFields();
    }

    async function fillColumnForm(column) {
        els.columnId.value = column.id;
        els.columnForm.elements.display_name.value = column.display_name || "";
        els.columnForm.elements.sql_name.value = column.sql_name || "";
        els.columnForm.elements.data_type.value = column.data_type || "Text";
        els.columnForm.elements.length.value = column.length || "";
        els.columnForm.elements.default_value.value = column.default_value || "";
        els.columnForm.elements.display_order.value = column.display_order || 0;
        if (els.columnForm.elements.allow_null) {
            els.columnForm.elements.allow_null.checked = !Boolean(column.is_required);
        }
        els.columnForm.elements.is_unique.checked = Boolean(column.is_unique);
        els.columnForm.elements.is_visible.checked = Boolean(column.is_visible);
        els.columnForm.elements.is_lookup.checked = Boolean(column.is_lookup);
        renderLookupSources(column.lookup_source_name || "");
        await renderLookupColumns(column.lookup_source_name || "", {
            value: column.lookup_value_column || "",
            label: column.lookup_label_column || "",
            filter: column.lookup_filter || "",
        });
        els.columnSubmit.textContent = "Save Column";
        toggleLookupFields();
    }

    function toggleLookupFields() {
        const enabled = Boolean(els.lookupToggle && els.lookupToggle.checked);
        els.lookupFields.forEach((field) => {
            field.hidden = !enabled;
            field.querySelectorAll("input, select").forEach((input) => {
                input.disabled = !enabled;
                if (!enabled) input.value = "";
            });
        });
    }

    function renderPreview(data, preserveState = false) {
        state.previewData = data;
        state.editingRecordId = null;
        updateRecordActionState();
        if (!data) {
            els.previewSection.hidden = true;
            if (els.previewRowCount) els.previewRowCount.textContent = "0 rows loaded";
            setHtml(els.previewHead, "");
            setHtml(els.previewBody, "");
            if (els.previewFilterToggle) {
                els.previewFilterToggle.disabled = true;
            }
            if (!preserveState) {
                state.previewFilters = [];
                state.previewSort = {
                    columnIndex: null,
                    direction: "asc",
                };
                setPreviewFilterPanelOpen(false);
            }
            return;
        }
        els.previewSection.hidden = false;
        if (els.previewRowCount) {
            const total = Number(data.row_count || 0);
            els.previewRowCount.textContent = `${total} row${total === 1 ? "" : "s"} loaded`;
        }
        if (!preserveState) {
            state.previewFilters = (data.columns || []).length ? [createPreviewFilter(0)] : [];
            state.previewSort = {
                columnIndex: null,
                direction: "asc",
            };
        }
        if (els.previewFilterToggle) {
            els.previewFilterToggle.disabled = !(data.columns || []).length;
        }
        renderPreviewFilterPanel(data);
        const recordIdIndex = data.columns.indexOf("BrowserRecordId");
        const visibleColumnIndexes = data.columns
            .map((column, index) => ({ column, index }))
            .filter(({ column }) => {
                if (column === "BrowserRecordId") return !state.activeBrowser || state.activeBrowser.show_browser_record_id !== false;
                if (column === "EventChainID") return !state.activeBrowser || state.activeBrowser.show_eventchain_id !== false;
                return true;
            });
        if (state.previewSort.columnIndex !== null && !visibleColumnIndexes.some(({ index }) => index === Number(state.previewSort.columnIndex))) {
            state.previewSort.columnIndex = null;
            state.previewSort.direction = "asc";
        }
        setHtml(els.previewHead, renderPreviewHeader(data.columns || [], visibleColumnIndexes));
        if (recordIdIndex < 0) {
            setHtml(els.previewBody, `<tr><td colspan="${Math.max(visibleColumnIndexes.length + 1, 1)}">BrowserRecordId is missing from the preview, so edit/delete actions are unavailable.</td></tr>`);
            setStatus("BrowserRecordId is missing from the preview.", true);
            return;
        }
        const sortedRows = getSortedAndFilteredPreviewRows(data);
        if (!sortedRows.length) {
            setHtml(els.previewBody, `<tr><td colspan="${Math.max(visibleColumnIndexes.length + 1, 1)}">No data returned.</td></tr>`);
            return;
        }
        setHtml(els.previewBody, sortedRows.map((row) => `
            <tr data-record-row="${escapeHtml(row[recordIdIndex])}">
                <td><input type="checkbox" data-record-select value="${escapeHtml(row[recordIdIndex])}"></td>
                ${visibleColumnIndexes.map(({ index }) => {
                    const value = row[index];
                    return `<td>${escapeHtml(value === null || value === undefined ? "" : String(value))}</td>`;
                }).join("")}
            </tr>
        `).join(""));
        bindPreviewHeaderSorting();
        bindPreviewFilters(data);
    }

    async function renderRecordForm(record = null) {
        if (!state.activeBrowser || !els.recordForm) return;
        const columns = state.activeBrowser.columns || [];
        if (!columns.length) {
            els.recordForm.hidden = true;
            setHtml(els.recordForm, "");
            return;
        }
        openRecordModal();
        els.recordForm.hidden = false;
        state.editingRecordId = record ? record.BrowserRecordId : null;
        const title = document.getElementById("record-modal-title");
        if (title) {
            title.textContent = record ? "Edit record" : "Add record";
        }
        setHtml(els.recordForm, `
            <div class="browser-record-grid">
                ${columns.map((column) => recordFieldHtml(column)).join("")}
            </div>
            <div class="browser-action-row">
                <button class="button" type="submit">${record ? "Update Record" : "Save Record"}</button>
                <button class="button secondary" type="button" data-record-cancel>Cancel</button>
            </div>
        `);
        initSearchableSelects(els.recordForm);
        for (const column of columns.filter((item) => item.is_lookup)) {
            await hydrateLookup(column);
        }
        if (record) {
            columns.forEach((column) => {
                const input = els.recordForm.elements[column.sql_name];
                if (!input) return;
                const value = record[column.display_name] ?? record[column.sql_name] ?? "";
                if (column.data_type === "Boolean") {
                    input.checked = ["-1", "1", "true", "yes", "on"].includes(String(value).toLowerCase());
                    const stateLabel = input.closest(".browser-boolean-control")?.querySelector("[data-boolean-state]");
                    if (stateLabel) stateLabel.textContent = input.checked ? "Active" : "Inactive";
                } else {
                    input.value = value;
                }
            });
        }
    }

    function recordFieldHtml(column) {
        const required = column.is_required ? "required" : "";
        if (column.is_lookup) {
            return `
                <label>
                    <span>${escapeHtml(column.display_name)}</span>
                    <select name="${escapeHtml(column.sql_name)}" ${required} data-lookup-select="${column.id}" data-searchable-select data-searchable-placeholder="Search values...">
                        <option value="">Loading...</option>
                    </select>
                </label>
            `;
        }
        if (column.data_type === "Boolean") {
            return `
                <label class="browser-boolean-field">
                    <span>${escapeHtml(column.display_name)}</span>
                    <span class="browser-boolean-control">
                        <input type="checkbox" name="${escapeHtml(column.sql_name)}" value="-1" data-record-boolean>
                        <span data-boolean-state>Inactive</span>
                    </span>
                </label>
            `;
        }
        const type = column.data_type === "Date" ? "date"
            : column.data_type === "DateTime" ? "datetime-local"
            : column.data_type === "Integer" || column.data_type === "Decimal" ? "number"
            : "text";
        const step = column.data_type === "Decimal" ? ' step="0.01"' : "";
        return `
            <label>
                <span>${escapeHtml(column.display_name)}</span>
                <input type="${type}" name="${escapeHtml(column.sql_name)}" ${required}${step}>
            </label>
        `;
    }

    async function hydrateLookup(column) {
        const select = els.recordForm.querySelector(`[data-lookup-select="${column.id}"]`);
        if (!select || !state.activeBrowser) return;
        try {
            const payload = await api(`/data-browsers/${state.activeBrowser.id}/columns/${column.id}/lookup-options?limit=all`);
            const options = payload.lookup.options || [];
            setHtml(select, '<option value=""></option>' + options.map((option) => (
                `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`
            )).join(""));
            refreshSearchableSelect(select);
        } catch (error) {
            setHtml(select, `<option value="">${escapeHtml(error.message)}</option>`);
            refreshSearchableSelect(select);
        }
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    async function loadBrowsers(selectId = null) {
        const payload = await api("/data-browsers");
        state.browsers = Array.isArray(payload.browsers) ? payload.browsers : [];
        renderBrowsers();
        renderLookupSources();
        if (selectId) {
            await selectBrowser(selectId);
        }
    }

    async function selectBrowser(id) {
        try {
            markBrowserSelection(id);
            setStatus("Loading browser...");
            const browser = state.browsers.find((item) => String(item.id) === String(id));
            if (!browser) {
                throw new Error("Browser not found in current page state.");
            }
            fillBrowserForm(browser);
            if (els.previewSection) {
                els.previewSection.hidden = false;
            }
            if (els.form && els.form.closest(".browser-modal")) {
                closeModal(els.definitionModal);
            }
            renderBrowsers();
            await previewData();
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function saveBrowser(event) {
        event.preventDefault();
        const id = els.browserId.value;
        const data = formData(els.form);
        try {
            setStatus("Saving Browser...");
            const payload = await api(id ? `/data-browsers/${id}` : "/data-browsers", {
                method: id ? "PUT" : "POST",
                body: JSON.stringify(data),
            });
            await loadBrowsers(payload.browser.id);
            setStatus("Browser saved.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function deleteBrowser() {
        if (!state.activeBrowser) return;
        if (!confirm(`Delete ${state.activeBrowser.name}? SQL Server table will not be deleted.`)) return;
        try {
            setStatus("Deleting Browser...");
            await api(`/data-browsers/${state.activeBrowser.id}`, { method: "DELETE" });
            resetBrowserForm();
            await loadBrowsers();
            setStatus("Browser deleted.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    async function saveColumn(event) {
        event.preventDefault();
        if (!state.activeBrowser) return;
        const id = els.columnId.value;
        const data = formData(els.columnForm);
        data.is_required = !Boolean(data.allow_null);
        delete data.allow_null;
        try {
            setStatus("Saving column...");
            await api(id ? `/data-browsers/${state.activeBrowser.id}/columns/${id}` : `/data-browsers/${state.activeBrowser.id}/columns`, {
                method: id ? "PUT" : "POST",
                body: JSON.stringify(data),
            });
            await selectBrowser(state.activeBrowser.id);
            setStatus("Column saved.");
        } catch (error) {
            setStatus(`Column save or SQL synchronization failed: ${error.message}`, true, true);
        }
    }

    async function deleteColumn(id) {
        if (!state.activeBrowser) return;
        if (!confirm("Delete this configured column? SQL Server column will not be deleted automatically.")) return;
        try {
            setStatus("Deleting column...");
            await api(`/data-browsers/${state.activeBrowser.id}/columns/${id}`, { method: "DELETE" });
            await selectBrowser(state.activeBrowser.id);
            setStatus("Column deleted.");
        } catch (error) {
            setStatus(`Column delete failed: ${error.message}`, true, true);
        }
    }

    async function previewData() {
        if (!state.activeBrowser) return;
        try {
            setStatus("Loading preview...");
            const limit = String(state.previewLimit || "1000");
            const filters = encodeURIComponent(JSON.stringify(state.previewFilters || []));
            const payload = await api(`/data-browsers/${state.activeBrowser.id}/data?limit=${encodeURIComponent(limit)}&filters=${filters}`);
            renderPreview(payload.data, true);
            if (payload.data && payload.data.needs_sync) {
                await syncBrowser(true);
                return;
            }
            setStatus(payload.data.message || `${payload.data.row_count} row(s) loaded.`, Boolean(payload.data.needs_sync));
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    function exportBrowserData() {
        if (!state.activeBrowser) {
            setStatus("Select a browser before exporting.", true);
            return;
        }
        const limit = els.previewLimit ? els.previewLimit.value : state.previewLimit;
        const filters = encodeURIComponent(JSON.stringify(state.previewFilters || []));
        window.location.href = `/data-browsers/${state.activeBrowser.id}/export?limit=${encodeURIComponent(limit || "1000")}&filters=${filters}`;
    }

    function setPreviewFullscreen(isFullscreen) {
        if (!els.previewSection) return;
        els.previewSection.classList.toggle("fullscreen-mode", Boolean(isFullscreen));
        document.body.classList.toggle("data-browser-fullscreen", Boolean(isFullscreen));
        if (els.previewFullscreen) {
            els.previewFullscreen.setAttribute("aria-label", isFullscreen ? "Exit fullscreen preview" : "Fullscreen preview");
            els.previewFullscreen.setAttribute("title", isFullscreen ? "Exit fullscreen preview" : "Fullscreen preview");
        }
    }

    async function togglePreviewFullscreen() {
        const section = els.previewSection;
        if (!section) return;
        try {
            if (document.fullscreenElement === section) {
                await document.exitFullscreen();
                return;
            }
            if (section.requestFullscreen) {
                await section.requestFullscreen();
                return;
            }
        } catch (error) {
            // fallback below
        }
        const nextState = !section.classList.contains("fullscreen-mode");
        setPreviewFullscreen(nextState);
    }

    function openImportModal() {
        if (!els.importModal) return;
        els.importModal.hidden = false;
        els.importModal.classList.add("visible");
        document.body.classList.add("modal-open");
    }

    function closeImportModal() {
        if (!els.importModal) return;
        stopImportPolling();
        els.importModal.classList.remove("visible");
        els.importModal.hidden = true;
        document.body.classList.remove("modal-open");
        state.importFile = null;
        state.importPreview = null;
        if (els.importFile) {
            els.importFile.value = "";
        }
    }

    function normalizeImportHeaders(headers) {
        return (headers || []).map((header) => String(header || "").trim()).filter(Boolean);
    }

    function renderImportFilePreview(importPreview) {
        const headers = normalizeImportHeaders(importPreview.headers || []);
        const sampleRows = Array.isArray(importPreview.sample_rows) ? importPreview.sample_rows : [];
        if (els.importCommitButton) {
            els.importCommitButton.disabled = false;
        }
        if (els.importRowCount) {
            els.importRowCount.textContent = String(importPreview.total_rows || 0);
        }
        if (els.importFileName) {
            els.importFileName.textContent = importPreview.file_name || "-";
        }
        if (els.importFileHead) {
            els.importFileHead.innerHTML = `<tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>`;
        }
        if (els.importFileBody) {
            if (!sampleRows.length) {
                els.importFileBody.innerHTML = `<tr><td colspan="${Math.max(headers.length, 1)}">No sample rows available.</td></tr>`;
            } else {
                els.importFileBody.innerHTML = sampleRows.map((row) => {
                    const values = headers.map((header) => escapeHtml(row[header] ?? ""));
                    return `<tr>${values.map((value) => `<td>${value}</td>`).join("")}</tr>`;
                }).join("");
            }
        }
    }

    function browserColumnMappingRow(column, headers, index) {
        const headerOptions = ['<option value="">-- select file column --</option>']
            .concat(headers.map((header) => {
                const match = String(header || "").trim().toLowerCase() === String(column.display_name || column.sql_name || "").trim().toLowerCase();
                const selected = match ? " selected" : "";
                return `<option value="${escapeHtml(header)}"${selected}>${escapeHtml(header)}</option>`;
            }))
            .join("");
        const defaultValue = column.default_value || "";
        return `
            <tr data-import-map-row="${index}">
                <td>
                    <strong>${escapeHtml(column.display_name)}</strong>
                    <div class="table-subtext">${escapeHtml(column.sql_name)}${column.is_required ? " · required" : ""}</div>
                </td>
                <td>
                    <select data-import-source-column="${escapeHtml(column.sql_name)}">
                        ${headerOptions}
                    </select>
                </td>
                <td>
                    <input type="text" data-import-default-value="${escapeHtml(column.sql_name)}" value="${escapeHtml(defaultValue)}" placeholder="Optional default">
                </td>
            </tr>
        `;
    }

    function renderImportMapping(browser, importPreview) {
        if (!browser || !importPreview) return;
        state.importPreview = importPreview;
        const headers = normalizeImportHeaders(importPreview.headers || []);
        if (els.importBrowserName) {
            els.importBrowserName.textContent = browser.name || "-";
        }
        if (els.importSummary) {
            els.importSummary.textContent = `Map the browser columns against the columns found in ${importPreview.file_name || "the selected file"}.`;
        }
        if (els.importProgressText) {
            els.importProgressText.textContent = `0 / ${importPreview.total_rows || 0}`;
        }
        if (els.importProgressBar) {
            els.importProgressBar.style.width = "0%";
        }
        if (els.importMapBody) {
            const columns = Array.isArray(browser.columns) ? browser.columns : [];
            els.importMapBody.innerHTML = columns.length
                ? columns.map((column, index) => browserColumnMappingRow(column, headers, index)).join("")
                : '<tr><td colspan="3">No columns configured on this Browser.</td></tr>';
        }
        renderImportFilePreview(importPreview);
        openImportModal();
    }

    async function prepareImport(file) {
        if (!state.activeBrowser || !file) return;
        const data = new FormData();
        data.append("file", file);
        try {
            setStatus("Analyzing import file...");
            const response = await fetch(`/data-browsers/${state.activeBrowser.id}/import/preview`, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrfToken(),
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: data,
            });
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.error || "Import preview failed.");
            state.importFile = file;
            renderImportMapping(payload.browser || state.activeBrowser, payload.import_preview || {});
            setStatus("Import mapping ready.");
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    function buildImportMappingPayload() {
        const mapping = {};
        const browserColumns = (state.activeBrowser && Array.isArray(state.activeBrowser.columns)) ? state.activeBrowser.columns : [];
        browserColumns.forEach((column) => {
            const sourceSelect = document.querySelector(`[data-import-source-column="${CSS.escape(column.sql_name)}"]`);
            const defaultInput = document.querySelector(`[data-import-default-value="${CSS.escape(column.sql_name)}"]`);
            mapping[column.sql_name] = {
                source_column: sourceSelect ? sourceSelect.value || "" : "",
                default_value: defaultInput ? defaultInput.value || "" : "",
            };
        });
        return mapping;
    }

    function updateImportProgress(processed, totalRows, inserted = null, updated = null, skipped = null, errors = null) {
        const total = Math.max(0, Number(totalRows || 0));
        const done = Math.max(0, Math.min(Number(processed || 0), total || Number(processed || 0)));
        const percent = total > 0 ? Math.round((done / total) * 100) : 0;
        if (els.importProgressText) {
            const parts = [`${percent}%`, `${done} / ${total}`];
            if (inserted !== null) parts.push(`${inserted} inserted`);
            if (updated !== null) parts.push(`${updated} updated`);
            if (skipped !== null) parts.push(`${skipped} skipped`);
            if (errors !== null) parts.push(`${errors} error(s)`);
            els.importProgressText.textContent = parts.join(" • ");
        }
        if (els.importProgressBar) {
            els.importProgressBar.style.width = `${percent}%`;
            els.importProgressBar.setAttribute("aria-valuenow", String(percent));
        }
    }

    function formatImportSummary(status) {
        const total = Number(status.total_rows || 0);
        const processed = Number(status.processed || 0);
        const inserted = Number(status.inserted || 0);
        const updated = Number(status.updated || 0);
        const skipped = Number(status.skipped || 0);
        const errorCount = Number(status.error_count || 0);
        const lines = [
            status.failed ? "Import interrupted" : "Import completed",
            `Total rows: ${total}`,
            `Processed: ${processed}`,
            `Inserted: ${inserted}`,
            `Updated: ${updated}`,
            `Skipped duplicates: ${skipped}`,
            `Rows with errors: ${errorCount}`,
        ];
        const errors = Array.isArray(status.errors) ? status.errors.slice(0, 5) : [];
        if (errors.length) {
            lines.push("", "First errors:");
            errors.forEach((item) => {
                lines.push(`Row ${item.row}: ${item.error || "Unknown error"}`);
            });
            if (errorCount > errors.length) {
                lines.push(`...and ${errorCount - errors.length} more error(s).`);
            }
        }
        if (status.fatal_error) {
            lines.push("", `Technical error: ${status.fatal_error}`);
        }
        return lines.join("\n");
    }

    function stopImportPolling() {
        if (importStatusTimer) {
            clearTimeout(importStatusTimer);
            importStatusTimer = null;
        }
    }

    function pollImportStatus(jobToken, onComplete, onError) {
        let consecutivePollingErrors = 0;
        const tick = async () => {
            try {
                const payload = await api(`/data-browsers/import/status/${encodeURIComponent(jobToken)}`);
                consecutivePollingErrors = 0;
                const status = payload.status || {};
                updateImportProgress(
                    status.processed || 0,
                    status.total_rows || 0,
                    status.inserted || 0,
                    status.updated || 0,
                    status.skipped || 0,
                    status.error_count || 0,
                );
                if (status.message) {
                    if (els.status) {
                        els.status.textContent = status.message;
                        els.status.classList.toggle("error", Boolean(status.failed));
                    }
                }
                if (status.failed) {
                    stopImportPolling();
                    if (onError) onError(status);
                    return;
                }
                if (status.done) {
                    stopImportPolling();
                    if (onComplete) onComplete(status);
                    return;
                }
                importStatusTimer = setTimeout(tick, 350);
            } catch (error) {
                consecutivePollingErrors += 1;
                if (consecutivePollingErrors < 5) {
                    importStatusTimer = setTimeout(tick, 700);
                    return;
                }
                stopImportPolling();
                if (onError) onError(error);
            }
        };
        stopImportPolling();
        importStatusTimer = setTimeout(tick, 150);
    }

    async function commitImport() {
        if (!state.activeBrowser || !state.importFile || !state.importPreview) return;
        const token = state.importPreview.token;
        const totalRows = Number(state.importPreview.total_rows || 0);
        if (!token) {
            setStatus("Import session is missing. Please re-open the file preview.", true);
            return;
        }
        if (!Number.isFinite(totalRows) || totalRows < 0) {
            setStatus("Import preview returned an invalid row count.", true);
            return;
        }
        const mappingPayload = {
            column_map: buildImportMappingPayload(),
            duplicate_mode: els.importDuplicateMode ? els.importDuplicateMode.value : "skip",
            commit_individual_rows: Boolean(els.importCommitRows && els.importCommitRows.checked),
        };
        try {
            stopImportPolling();
            setStatus("Starting import...");
            if (els.importCommitButton) {
                els.importCommitButton.disabled = true;
            }
            updateImportProgress(0, totalRows, 0, 0, 0, 0);
            const response = await api(`/data-browsers/${state.activeBrowser.id}/import/start`, {
                method: "POST",
                body: JSON.stringify({
                    token,
                    mapping: mappingPayload,
                }),
            });
            const jobToken = response.import && response.import.job_token;
            if (!jobToken) {
                throw new Error("Import job could not be started.");
            }
            setStatus("Import running...");
            pollImportStatus(
                jobToken,
                async (status) => {
                    updateImportProgress(
                        status.processed || 0,
                        status.total_rows || 0,
                        status.inserted || 0,
                        status.updated || 0,
                        status.skipped || 0,
                        status.error_count || 0,
                    );
                    closeImportModal();
                    await previewData();
                    showCenterMessage(formatImportSummary(status), false, true);
                    if (els.status) els.status.textContent = status.message || "Import completed.";
                    if (els.importCommitButton) {
                        els.importCommitButton.disabled = false;
                    }
                },
                (status) => {
                    if (status instanceof Error) {
                        status = {
                            failed: true,
                            fatal_error: status.message,
                            message: status.message,
                        };
                    }
                    closeImportModal();
                    showCenterMessage(formatImportSummary(status || {}), true, true);
                    if (els.status) els.status.textContent = (status && status.message) || "Import failed.";
                    if (els.importCommitButton) {
                        els.importCommitButton.disabled = false;
                    }
                },
            );
        } catch (error) {
            setStatus(error.message, true);
            if (els.importCommitButton) {
                els.importCommitButton.disabled = false;
            }
        }
    }

    async function syncBrowser(silentRetry = false) {
        if (!state.activeBrowser) return;
        try {
            setStatus(silentRetry ? "Syncing browser..." : "Syncing Browser...");
            const payload = await api(`/data-browsers/${state.activeBrowser.id}/sync-sql`, {
                method: "POST",
            });
            const browser = payload.browser || null;
            if (browser) {
                const index = state.browsers.findIndex((item) => String(item.id) === String(browser.id));
                if (index >= 0) {
                    state.browsers[index] = browser;
                }
                fillBrowserForm(browser);
                renderBrowsers();
            }
            if (!silentRetry) {
                setStatus("Browser synchronized.");
            }
            await previewData();
        } catch (error) {
            setStatus(error.message, true, true);
        }
    }

    async function saveRecord(event) {
        event.preventDefault();
        if (!state.activeBrowser) return;
        try {
            setStatus("Saving record...");
            const url = state.editingRecordId
                ? `/data-browsers/${state.activeBrowser.id}/records/${state.editingRecordId}`
                : `/data-browsers/${state.activeBrowser.id}/records`;
            await api(url, {
                method: state.editingRecordId ? "PUT" : "POST",
                body: JSON.stringify(formData(els.recordForm)),
            });
            els.recordForm.reset();
            state.editingRecordId = null;
            closeModal(els.recordModal);
            await previewData();
            setStatus("Record saved.");
        } catch (error) {
            setStatus(error.message, true, true);
        }
    }

    function selectedRecordIds() {
        return Array.from(root.querySelectorAll("[data-record-select]:checked"))
            .map((input) => input.value)
            .filter(Boolean);
    }

    function updateRecordActionState() {
        const count = selectedRecordIds().length;
        if (els.recordEdit) els.recordEdit.disabled = count !== 1;
        if (els.recordDelete) els.recordDelete.disabled = count < 1;
    }

    function selectedRecord() {
        const ids = selectedRecordIds();
        if (ids.length !== 1 || !state.previewData) return null;
        const recordIdIndex = state.previewData.columns.indexOf("BrowserRecordId");
        const row = (state.previewData.row_values || []).find((item) => String(item[recordIdIndex]) === String(ids[0]));
        if (!row) return null;
        return Object.fromEntries(state.previewData.columns.map((column, index) => [column, row[index]]));
    }

    async function editSelectedRecord() {
        const record = selectedRecord();
        if (!record) return;
        await renderRecordForm(record);
    }

    async function deleteSelectedRecords() {
        if (!state.activeBrowser) return;
        const ids = selectedRecordIds();
        if (!ids.length) return;
        if (!confirm(`Delete ${ids.length} selected record(s)?`)) return;
        try {
            setStatus("Deleting selected records...");
            const payload = await api(`/data-browsers/${state.activeBrowser.id}/records/bulk-delete`, {
                method: "POST",
                body: JSON.stringify({ record_ids: ids }),
            });
            await previewData();
            closeModal(els.recordModal);
            const deleted = payload?.result?.deleted ?? ids.length;
            setStatus(`${deleted} record(s) deleted.`);
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    els.newButton.addEventListener("click", () => openDefinitionModal(true));
    document.querySelectorAll("[data-browser-definition-open]").forEach((button) => {
        button.addEventListener("click", () => openDefinitionModal(false));
    });
    els.form.addEventListener("submit", saveBrowser);
    els.deleteButtons.forEach((button) => button.addEventListener("click", deleteBrowser));
    els.previewButtons.forEach((button) => button.addEventListener("click", previewData));
    document.querySelectorAll("[data-browser-sync]").forEach((button) => button.addEventListener("click", () => syncBrowser(false)));
    els.columnForm.addEventListener("submit", saveColumn);
    if (els.recordOpen) els.recordOpen.addEventListener("click", () => renderRecordForm());
    if (els.recordEdit) els.recordEdit.addEventListener("click", editSelectedRecord);
    if (els.recordDelete) els.recordDelete.addEventListener("click", deleteSelectedRecords);
    if (els.recordForm) {
        els.recordForm.addEventListener("submit", saveRecord);
        els.recordForm.addEventListener("change", (event) => {
            if (!event.target.matches("[data-record-boolean]")) return;
            const stateLabel = event.target.closest(".browser-boolean-control")?.querySelector("[data-boolean-state]");
            if (stateLabel) stateLabel.textContent = event.target.checked ? "Active" : "Inactive";
        });
        els.recordForm.addEventListener("click", (event) => {
            if (event.target.closest("[data-record-cancel]")) {
                closeModal(els.recordModal);
                els.recordForm.hidden = true;
                state.editingRecordId = null;
            }
        });
    }
    if (els.importTrigger && els.importFile) {
        els.importTrigger.addEventListener("click", () => els.importFile.click());
        els.importFile.addEventListener("change", () => prepareImport(els.importFile.files[0]));
    }
    if (els.importCommitButton) {
        els.importCommitButton.addEventListener("click", () => commitImport());
    }
    if (els.previewLimit) {
        state.previewLimit = els.previewLimit.value || "1000";
        els.previewLimit.addEventListener("change", () => {
            state.previewLimit = els.previewLimit.value || "1000";
            if (state.activeBrowser) {
                previewData().catch((error) => setStatus(error.message, true));
            }
        });
    }
    if (els.previewFilterToggle) {
        els.previewFilterToggle.addEventListener("click", () => {
            if (!state.previewData || !(state.previewData.columns || []).length) {
                return;
            }
            setPreviewFilterPanelOpen(!state.previewFilterPanelOpen);
            if (state.previewFilterPanelOpen) {
                renderPreviewFilterPanel(state.previewData);
                bindPreviewFilters(state.previewData);
            }
        });
    }
    if (els.previewFilterAdd) {
        els.previewFilterAdd.addEventListener("click", () => {
            if (!state.previewData || !(state.previewData.columns || []).length) {
                return;
            }
            state.previewFilters.push(createPreviewFilter(0));
            renderPreviewFilterPanel(state.previewData);
            bindPreviewFilters(state.previewData);
            setPreviewFilterPanelOpen(true);
        });
    }
    if (els.previewFilterReset) {
        els.previewFilterReset.addEventListener("click", () => {
            if (!state.previewData || !(state.previewData.columns || []).length) {
                return;
            }
            state.previewFilters = [createPreviewFilter(0)];
            renderPreviewFilterPanel(state.previewData);
            bindPreviewFilters(state.previewData);
            setPreviewFilterPanelOpen(true);
        });
    }
    if (els.previewFilterApply) {
        els.previewFilterApply.addEventListener("click", () => {
            setPreviewFilterPanelOpen(false);
            if (state.activeBrowser) {
                previewData().catch((error) => setStatus(error.message, true));
            }
        });
    }
    document.querySelectorAll("[data-preview-filter-close]").forEach((button) => {
        button.addEventListener("click", () => setPreviewFilterPanelOpen(false));
    });
    if (els.previewFullscreen) {
        els.previewFullscreen.addEventListener("click", () => togglePreviewFullscreen());
    }
    if (els.exportButton) {
        els.exportButton.addEventListener("click", exportBrowserData);
    }
    document.addEventListener("fullscreenchange", () => {
        if (!els.previewSection) return;
        setPreviewFullscreen(Boolean(document.fullscreenElement === els.previewSection));
    });
    document.querySelectorAll("[data-import-close]").forEach((button) => {
        button.addEventListener("click", () => closeImportModal());
    });
    const importBack = document.querySelector("[data-import-back]");
    if (importBack) {
        importBack.addEventListener("click", () => {
            closeImportModal();
            if (els.importFile) {
                els.importFile.click();
            }
        });
    }
    if (els.lookupToggle) {
        els.lookupToggle.addEventListener("change", toggleLookupFields);
        toggleLookupFields();
    }
    if (els.centerMessageOk) {
        els.centerMessageOk.addEventListener("click", hideCenterMessage);
    }

    initSearchableSelects();

    if (els.browserSearch) {
        els.browserSearch.addEventListener("input", () => {
            state.browserSearch = els.browserSearch.value || "";
            renderBrowsers();
        });
    }
    if (els.browserStatusFilter) {
        els.browserStatusFilter.addEventListener("change", () => {
            state.browserStatusFilter = els.browserStatusFilter.value || "all";
            renderBrowsers();
        });
    }
    if (els.browserOrderSave) {
        els.browserOrderSave.addEventListener("click", saveBrowserOrder);
    }
    if (els.browserPaneToggle) {
        els.browserPaneToggle.addEventListener("click", () => {
            setBrowserPaneCollapsed(!els.browserPane.classList.contains("collapsed"));
        });
    }
    setBrowserPaneCollapsed(localStorage.getItem("mining360BrowserPaneCollapsed") === "1");

    els.list.addEventListener("pointerdown", (event) => {
        const handle = event.target.closest(".browser-list-drag");
        const row = handle && handle.closest("[data-browser-row]");
        if (row) row.draggable = true;
    });

    ["pointerup", "pointercancel"].forEach((eventName) => {
        els.list.addEventListener(eventName, (event) => {
            const row = event.target.closest("[data-browser-row]");
            if (row && row !== draggedBrowserRow) row.draggable = false;
        });
    });

    els.list.addEventListener("dragstart", (event) => {
        const row = event.target.closest("[data-browser-row]");
        if (!row || row.draggable !== true) {
            event.preventDefault();
            return;
        }
        draggedBrowserRow = row;
        row.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.browserRow);
    });

    els.list.addEventListener("dragover", (event) => {
        if (!draggedBrowserRow) return;
        event.preventDefault();
        const targetRow = event.target.closest("[data-browser-row]");
        if (!targetRow || targetRow === draggedBrowserRow) return;
        const bounds = targetRow.getBoundingClientRect();
        const insertAfter = event.clientY > bounds.top + bounds.height / 2;
        els.list.insertBefore(draggedBrowserRow, insertAfter ? targetRow.nextSibling : targetRow);
        markBrowserOrderChanged();
    });

    els.list.addEventListener("drop", (event) => {
        if (draggedBrowserRow) event.preventDefault();
    });

    els.list.addEventListener("dragend", () => {
        if (draggedBrowserRow) {
            draggedBrowserRow.classList.remove("is-dragging");
            draggedBrowserRow.draggable = false;
        }
        draggedBrowserRow = null;
    });

    els.list.addEventListener("click", (event) => {
        const button = event.target.closest("[data-browser-select]");
        if (button) {
            event.preventDefault();
            selectBrowser(button.dataset.browserSelect);
        }
    });

    els.columnTable.addEventListener("click", (event) => {
        const editButton = event.target.closest("[data-column-edit]");
        const deleteButton = event.target.closest("[data-column-delete]");
        if (editButton && state.activeBrowser) {
            const column = (state.activeBrowser.columns || []).find((item) => String(item.id) === String(editButton.dataset.columnEdit));
            if (column) fillColumnForm(column);
        }
        if (deleteButton) deleteColumn(deleteButton.dataset.columnDelete);
    });

    els.columnTable.addEventListener("pointerdown", (event) => {
        const handle = event.target.closest(".column-drag-handle");
        const row = handle && handle.closest("[data-column-row]");
        if (row) row.draggable = true;
    });

    ["pointerup", "pointercancel"].forEach((eventName) => {
        els.columnTable.addEventListener(eventName, (event) => {
            const row = event.target.closest("[data-column-row]");
            if (row && row !== draggedColumnRow) row.draggable = false;
        });
    });

    els.columnTable.addEventListener("dragstart", (event) => {
        const row = event.target.closest("[data-column-row]");
        if (!row || row.draggable !== true) {
            event.preventDefault();
            return;
        }
        draggedColumnRow = row;
        row.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.columnRow);
    });

    els.columnTable.addEventListener("dragover", (event) => {
        if (!draggedColumnRow) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        const targetRow = event.target.closest("[data-column-row]");
        if (!targetRow || targetRow === draggedColumnRow) return;
        const bounds = targetRow.getBoundingClientRect();
        const insertAfter = event.clientY > bounds.top + bounds.height / 2;
        els.columnTable.insertBefore(draggedColumnRow, insertAfter ? targetRow.nextSibling : targetRow);
        markColumnOrderChanged();
    });

    els.columnTable.addEventListener("drop", (event) => {
        if (draggedColumnRow) event.preventDefault();
    });

    els.columnTable.addEventListener("dragend", () => {
        if (draggedColumnRow) {
            draggedColumnRow.classList.remove("is-dragging");
            draggedColumnRow.draggable = false;
        }
        draggedColumnRow = null;
    });

    if (els.columnOrderSave) {
        els.columnOrderSave.addEventListener("click", saveColumnOrder);
    }

    if (els.lookupSource) {
        els.lookupSource.addEventListener("change", () => renderLookupColumns(els.lookupSource.value, {}));
    }

    document.querySelectorAll("[data-modal-close]").forEach((button) => {
        button.addEventListener("click", () => {
            closeAllModals();
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeAllModals();
        }
    });

    root.addEventListener("change", (event) => {
        if (event.target.matches("[data-record-select-all]")) {
            const checked = Boolean(event.target.checked);
            root.querySelectorAll("[data-record-select]").forEach((input) => {
                input.checked = checked;
            });
            updateRecordActionState();
        }
        if (event.target.matches("[data-record-select]")) {
            updateRecordActionState();
        }
    });

    renderBrowsers();
    if (!state.browsers.length) {
        loadBrowsers().catch((error) => {
            if (els.list) {
                setHtml(els.list, `<div class="alert">${escapeHtml(error.message)}</div>`);
            }
        });
    }
})();
