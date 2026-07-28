(function () {
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(";").shift();
        return "";
    }

    const flash = document.getElementById("source-flash");

    function showFlash(message, isError = false) {
        if (!flash) return;
        flash.textContent = message;
        flash.hidden = false;
        flash.classList.toggle("error", isError);
        flash.classList.add("visible");
        clearTimeout(flash._hideTimer);
        flash._hideTimer = setTimeout(() => {
            flash.classList.remove("visible");
            flash.hidden = true;
        }, 3500);
    }

    const queuedFlashMessage = sessionStorage.getItem("source-flash-message");
    const queuedFlashIsError = sessionStorage.getItem("source-flash-error") === "1";
    if (queuedFlashMessage) {
        sessionStorage.removeItem("source-flash-message");
        sessionStorage.removeItem("source-flash-error");
        showFlash(queuedFlashMessage, queuedFlashIsError);
    }

    const navStateKey = "mining360ia.navCollapsed";
    const catalogStateKey = "mining360ia.catalogCollapsed";
    const configMenuStateKey = "mining360ia.configMenuOpen";
    function applyNavState(collapsed) {
        document.body.classList.toggle("nav-collapsed", collapsed);
        const button = document.querySelector(".js-toggle-nav");
        if (button) {
            button.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
            button.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
        }
    }

    function applyCatalogState(collapsed) {
        document.body.classList.toggle("catalog-collapsed", collapsed);
        const pane = document.querySelector("[data-catalog-pane]");
        const button = document.querySelector(".js-toggle-catalog");
        if (pane) {
            pane.classList.toggle("collapsed", collapsed);
        }
        if (button) {
            button.setAttribute("aria-label", collapsed ? "Expand catalog" : "Collapse catalog");
            button.setAttribute("title", collapsed ? "Expand catalog" : "Collapse catalog");
        }
    }

    applyNavState(localStorage.getItem(navStateKey) === "1");
    applyCatalogState(localStorage.getItem(catalogStateKey) === "1");

    function applyConfigMenuState(open) {
        document.querySelectorAll("[data-nav-group='config']").forEach((group) => {
            group.classList.toggle("collapsed", !open);
            const button = group.querySelector(".js-toggle-config-menu");
            if (button) {
                button.setAttribute("aria-expanded", open ? "true" : "false");
                button.setAttribute("title", open ? "Close Config menu" : "Open Config menu");
            }
        });
    }

    const activeConfigGroup = document.querySelector("[data-nav-group='config'].active");
    applyConfigMenuState(Boolean(activeConfigGroup) || localStorage.getItem(configMenuStateKey) === "1");

    document.querySelectorAll(".js-toggle-nav").forEach((button) => {
        button.addEventListener("click", () => {
            const collapsed = !document.body.classList.contains("nav-collapsed");
            localStorage.setItem(navStateKey, collapsed ? "1" : "0");
            applyNavState(collapsed);
        });
    });

    document.querySelectorAll(".js-toggle-catalog").forEach((button) => {
        button.addEventListener("click", () => {
            const collapsed = !document.body.classList.contains("catalog-collapsed");
            localStorage.setItem(catalogStateKey, collapsed ? "1" : "0");
            applyCatalogState(collapsed);
        });
    });

    document.querySelectorAll(".js-toggle-config-menu").forEach((button) => {
        button.addEventListener("click", () => {
            const group = button.closest("[data-nav-group='config']");
            const open = group ? group.classList.contains("collapsed") : true;
            localStorage.setItem(configMenuStateKey, open ? "1" : "0");
            applyConfigMenuState(open);
        });
    });

    function updateStatus(container, payload) {
        const status = container.querySelector("[data-source-status]");
        const lastVerified = container.querySelector("[data-source-last-verified]");
        const source = payload.source || {};
        if (status) {
            status.textContent = source.status || "Unknown";
            status.className = `status-badge ${source.status_class || "neutral"}`;
        }
        if (lastVerified) {
            lastVerified.textContent = source.last_verified ? `Last verified: ${source.last_verified}` : "";
        }
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function getSourceShell() {
        return document.querySelector("[data-source-key]");
    }

    function getCatalogBody() {
        return document.querySelector("[data-source-catalog-body]");
    }

    function resetPreviewPane(message = "Click a table, view, or custom view in the left pane to load a preview.") {
        const panel = document.querySelector("[data-table-preview]");
        const count = document.querySelector("[data-table-preview-count]");
        const title = document.querySelector("[data-table-preview-name]");
        const sql = document.querySelector("[data-table-preview-sql]");
        if (panel) {
            panel.innerHTML = `<div class="empty">${escapeHtml(message)}</div>`;
        }
        if (count) {
            count.textContent = "No object selected";
        }
        if (title) {
            title.textContent = "";
        }
        if (sql) {
            sql.textContent = "";
        }
        previewState.preview = null;
        previewState.previewUrl = "";
        previewState.filters = [];
        previewState.sort = { columnIndex: null, direction: "asc" };
    }

    function buildCatalogButtonHtml(item, kind, active) {
        const previewUrl = escapeHtml(item.preview_url || "");
        const qualifiedName = escapeHtml(item.qualified_name || item.key || item.name || "");
        if (kind === "custom") {
            const editUrl = escapeHtml(item.edit_url || "");
            const deleteUrl = escapeHtml(item.delete_url || "");
            return `
                <div class="catalog-item catalog-custom-row">
                    <button
                        type="button"
                        class="catalog-item-button catalog-item-stack js-object-preview${active ? " active" : ""}"
                        data-preview-url="${previewUrl}"
                        data-qualified-name="${qualifiedName}"
                    >
                        <strong>${escapeHtml(item.name || "")}</strong>
                        <span>${escapeHtml(item.description || "Custom SQL view")}</span>
                    </button>
                    <div class="catalog-custom-actions">
                        <button type="button" class="icon-action js-edit-custom-view" data-edit-url="${editUrl}" aria-label="Edit custom view" title="Edit custom view"></button>
                        <button type="button" class="icon-action delete-action js-delete-custom-view" data-delete-url="${deleteUrl}" data-view-name="${escapeHtml(item.name || "")}" aria-label="Delete custom view" title="Delete custom view"></button>
                    </div>
                </div>
            `;
        }
        return `
            <button
                type="button"
                class="catalog-item catalog-item-button js-object-preview${active ? " active" : ""}"
                data-preview-url="${previewUrl}"
                data-qualified-name="${qualifiedName}"
            >
                <span>${escapeHtml(item.schema || "")}.</span>
                <strong>${escapeHtml(item.name || "")}</strong>
            </button>
        `;
    }

    function buildCatalogSectionHtml(title, count, body, sectionKey) {
        return `
            <details class="catalog-section" data-catalog-section="${escapeHtml(sectionKey)}" open>
                <summary class="catalog-section-head">
                    <span>${escapeHtml(title)}</span>
                    <div class="catalog-section-actions">
                        <strong data-catalog-count="${escapeHtml(sectionKey)}">${count}</strong>
                        <span class="catalog-section-chevron" aria-hidden="true"></span>
                    </div>
                </summary>
                <div class="catalog-section-body">
                    <div class="catalog-list">
                        ${body}
                    </div>
                </div>
            </details>
        `;
    }

    function renderCatalogBody(catalog) {
        const body = getCatalogBody();
        if (!body) {
            return;
        }

        const tables = Array.isArray(catalog.tables) ? catalog.tables : [];
        const views = Array.isArray(catalog.views) ? catalog.views : [];
        const customViews = Array.isArray(catalog.custom_views) ? catalog.custom_views : [];

        const tableHtml = tables.length
            ? tables.map((item) => buildCatalogButtonHtml(item, "table", false)).join("")
            : `<div class="empty compact">No tables available.</div>`;
        const viewHtml = views.length
            ? views.map((item) => buildCatalogButtonHtml(item, "view", false)).join("")
            : `<div class="empty compact">No views available.</div>`;
        const customHtml = customViews.length
            ? customViews.map((item) => buildCatalogButtonHtml(item, "custom", false)).join("")
            : `<div class="empty compact">No custom views configured.</div>`;

        body.innerHTML = [
            buildCatalogSectionHtml("Tables", tables.length, tableHtml, "tables"),
            buildCatalogSectionHtml("Views", views.length, viewHtml, "views"),
            buildCatalogSectionHtml("Custom views", customViews.length, customHtml, "custom_views"),
        ].join("");
        bindCatalogPreviewButtons(body);
        bindCustomViewButtons(body);
    }

    function syncSourceMetadata(payload) {
        const source = payload.source || {};
        const inventory = payload.inventory || {};
        const catalog = payload.catalog || {};
        const serverValue = document.querySelector("[data-source-server]");
        const databaseValue = document.querySelector("[data-source-database-value]");
        const databaseLine = document.querySelector("[data-source-database-line]");
        const inventoryLabel = document.querySelector("[data-source-inventory-label]");
        const inventoryCount = document.querySelector("[data-source-inventory-count]");
        const customViewsCount = document.querySelector("[data-source-custom-views]");

        if (serverValue && source.server) {
            serverValue.textContent = source.server;
        }
        if (databaseValue) {
            databaseValue.textContent = source.database || "-";
        }
        if (databaseLine) {
            const prefix = String(source.engine || "").toLowerCase() === "snowflake" ? "Database: " : "Default database: ";
            databaseLine.childNodes.forEach((node) => {
                if (node.nodeType === Node.TEXT_NODE) {
                    node.textContent = prefix;
                }
            });
        }
        if (inventoryLabel) {
            inventoryLabel.textContent = inventory.label || "Inventory";
        }
        if (inventoryCount) {
            inventoryCount.textContent = inventory.count !== null && inventory.count !== undefined ? String(inventory.count) : "N/A";
        }
        if (customViewsCount) {
            customViewsCount.textContent = `Custom views: ${inventory.custom_views !== undefined ? inventory.custom_views : 0}`;
        }
        const countTables = document.querySelector('[data-catalog-count="tables"]');
        const countViews = document.querySelector('[data-catalog-count="views"]');
        const countCustom = document.querySelector('[data-catalog-count="custom_views"]');
        if (countTables) {
            countTables.textContent = (catalog.tables || []).length;
        }
        if (countViews) {
            countViews.textContent = (catalog.views || []).length;
        }
        if (countCustom) {
            countCustom.textContent = (catalog.custom_views || []).length;
        }
    }

    function bindCatalogPreviewButtons(scope = document) {
        scope.querySelectorAll(".js-object-preview, .js-table-preview").forEach((button) => {
            if (button.dataset.previewBound === "1") {
                return;
            }
            button.dataset.previewBound = "1";
            button.addEventListener("click", async () => {
                const url = button.dataset.previewUrl;
                const shell = document.querySelector("[data-source-key]");
                const pane = document.querySelector("[data-table-preview]");
                if (!shell || !pane) {
                    return;
                }

                shell.classList.add("table-loading");
                pane.classList.add("loading");
                setPreviewLoading(true);
                previewState.previewUrl = url;
                previewState.filters = [];
                previewState.sort = {
                    columnIndex: null,
                    direction: "asc",
                };
                document.querySelectorAll(".js-object-preview, .js-table-preview").forEach((item) => item.classList.remove("active"));
                button.classList.add("active");

                try {
                    await loadPreviewForCurrentSelection(document);
                } catch (error) {
                    renderTablePreview(document, { error: "Preview failed." });
                } finally {
                    shell.classList.remove("table-loading");
                    pane.classList.remove("loading");
                    setPreviewLoading(false);
                }
            });
        });
    }

    function setPreviewLoading(isLoading) {
        document.body.classList.toggle("preview-loading", isLoading);
        const overlay = document.querySelector("[data-preview-overlay]");
        if (overlay) {
            overlay.hidden = false;
            overlay.style.display = isLoading ? "flex" : "none";
            overlay.setAttribute("aria-hidden", isLoading ? "false" : "true");
        }
    }

    function setPreviewFullscreen(isFullscreen) {
        const section = document.querySelector(".table-section");
        const button = document.querySelector(".js-toggle-preview-fullscreen");
        if (section) {
            section.classList.toggle("fullscreen-mode", isFullscreen);
        }
        if (button) {
            button.setAttribute("aria-label", isFullscreen ? "Exit fullscreen preview" : "Fullscreen preview");
            button.setAttribute("title", isFullscreen ? "Exit fullscreen preview" : "Fullscreen preview");
        }
    }

    async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 300000) {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
            });
            return await response.json();
        } finally {
            window.clearTimeout(timer);
        }
    }

    setPreviewLoading(false);
    setPreviewFullscreen(Boolean(document.fullscreenElement && document.fullscreenElement.classList && document.fullscreenElement.classList.contains("table-section")));

    const previewState = {
        preview: null,
        filters: [],
        previewUrl: "",
        limit: "1000",
        filterPanelOpen: false,
        sort: {
            columnIndex: null,
            direction: "asc",
        },
        reloadTimer: null,
    };

    function getPreviewUrlWithLimit(url, limit) {
        if (!url) {
            return "";
        }
        const target = new URL(url, window.location.origin);
        target.searchParams.set("limit", limit || "1000");
        return target.toString();
    }

    function buildPreviewFiltersPayload() {
        const preview = previewState.preview || {};
        const columns = preview.columns || [];
        return (previewState.filters || []).map((filter) => {
            const columnIndex = Math.max(0, Math.min(Number(filter.columnIndex) || 0, Math.max(columns.length - 1, 0)));
            return {
                column: columns[columnIndex] || "",
                operator: filter.operator || "equal",
                value: filter.value || "",
                joiner: filter.joiner || "AND",
                type: (preview.column_types || [])[columnIndex] || "",
            };
        }).filter((filter) => filter.column && String(filter.value || "").trim().length > 0);
    }

    async function loadPreviewForCurrentSelection(container) {
        const shell = document.querySelector("[data-source-key]");
        const pane = document.querySelector("[data-table-preview]");
        if (!shell || !pane || !previewState.previewUrl) {
            return;
        }

        const filtersPayload = buildPreviewFiltersPayload();

        const requestUrl = new URL(getPreviewUrlWithLimit(previewState.previewUrl, previewState.limit), window.location.origin);
        requestUrl.searchParams.set("filters", JSON.stringify(filtersPayload));
        shell.classList.add("table-loading");
        pane.classList.add("loading");
        setPreviewLoading(true);
        try {
            const payload = await fetchJsonWithTimeout(requestUrl, {
                method: "GET",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
            });
            if (payload.ok) {
                renderTablePreview(container, payload.preview || {}, true);
            } else {
                renderTablePreview(container, { error: payload.error || "Preview failed." });
            }
        } catch (error) {
            if (error && error.name === "AbortError") {
                showFlash("Preview timed out after 5 minutes without any data arriving.", true);
            } else {
                renderTablePreview(container, { error: "Preview failed." });
            }
        } finally {
            shell.classList.remove("table-loading");
            pane.classList.remove("loading");
            setPreviewLoading(false);
        }
    }

    function rerenderPreviewLocally(container) {
        const preview = previewState.preview;
        if (!preview) {
            return;
        }
        renderTablePreview(container, preview, true);
    }

    const limitSelect = document.querySelector("[data-preview-limit]");
    if (limitSelect) {
        previewState.limit = limitSelect.value || "1000";
        limitSelect.addEventListener("change", async () => {
            previewState.limit = limitSelect.value || "1000";
            if (previewState.previewUrl) {
                await loadPreviewForCurrentSelection(document);
            }
        });
    }

    document.querySelectorAll(".js-toggle-preview-fullscreen").forEach((button) => {
        button.addEventListener("click", async () => {
            const section = document.querySelector(".table-section");
            if (!section) {
                return;
            }

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
                // fall through to CSS fallback
            }

            const nextState = !section.classList.contains("fullscreen-mode");
            section.classList.toggle("fullscreen-mode", nextState);
            setPreviewFullscreen(nextState);
        });
    });

    document.addEventListener("fullscreenchange", () => {
        const section = document.querySelector(".table-section");
        setPreviewFullscreen(Boolean(section && document.fullscreenElement === section));
        if (section) {
            section.classList.toggle("fullscreen-mode", Boolean(document.fullscreenElement === section));
        }
    });

    function normalizePreviewType(value) {
        const type = String(value || "").toLowerCase();
        if (["date", "datetime", "datetime2", "smalldatetime", "timestamp", "time"].includes(type)) {
            return "date";
        }
        if (["number", "numeric", "decimal", "float", "real", "int", "integer", "bigint", "smallint", "tinyint"].includes(type)) {
            return "number";
        }
        return "text";
    }

    function inferPreviewColumnTypes(preview) {
        const explicitTypes = Array.isArray(preview.column_types) ? preview.column_types : [];
        if (explicitTypes.length) {
            return explicitTypes.map(normalizePreviewType);
        }

        const columns = preview.columns || [];
        const rows = preview.row_values || [];
        return columns.map((_, columnIndex) => {
            for (const row of rows) {
                const sample = row && row.length > columnIndex ? row[columnIndex] : "";
                const text = String(sample ?? "").trim();
                if (!text) {
                    continue;
                }
                if (/^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/.test(text)) {
                    return "date";
                }
                if (/^-?\d+(?:\.\d+)?$/.test(text)) {
                    return "number";
                }
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
        const maxIndex = Math.max((preview.columns || []).length - 1, 0);
        const index = Number(value);
        if (Number.isNaN(index)) {
            return 0;
        }
        return Math.min(Math.max(index, 0), maxIndex);
    }

    function getFilterColumnType(preview, filter) {
        const columnTypes = inferPreviewColumnTypes(preview);
        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        return columnTypes[columnIndex] || "text";
    }

    function getPreviewColumnLabel(preview, index) {
        const columns = preview.columns || [];
        return columns[index] || columns[0] || "";
    }

    function setPreviewFilterPanelOpen(container, isOpen) {
        previewState.filterPanelOpen = Boolean(isOpen);
        document.body.classList.toggle("preview-filter-modal-open", previewState.filterPanelOpen);
        const modal = container.querySelector("[data-preview-filter-modal]");
        const panel = container.querySelector("[data-preview-filter-panel]");
        const button = document.querySelector("[data-preview-filter-toggle]");
        if (modal) {
            modal.hidden = !previewState.filterPanelOpen;
            modal.setAttribute("aria-hidden", previewState.filterPanelOpen ? "false" : "true");
        }
        if (panel) {
            panel.classList.toggle("is-open", previewState.filterPanelOpen);
        }
        if (button) {
            button.textContent = previewState.filterPanelOpen ? "Close filters" : "Filters";
            button.setAttribute("aria-expanded", previewState.filterPanelOpen ? "true" : "false");
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

    function comparePreviewValues(left, right, type) {
        const leftValue = normalizeComparableValue(left, type);
        const rightValue = normalizeComparableValue(right, type);

        if (leftValue === null && rightValue === null) {
            return 0;
        }
        if (leftValue === null) {
            return 1;
        }
        if (rightValue === null) {
            return -1;
        }

        if (type === "text") {
            return String(leftValue).localeCompare(String(rightValue), undefined, { sensitivity: "base" });
        }

        if (leftValue < rightValue) {
            return -1;
        }
        if (leftValue > rightValue) {
            return 1;
        }
        return 0;
    }

    function getSortedPreviewRows(preview, rows) {
        const sort = previewState.sort || {};
        const columnIndex = Number(sort.columnIndex);
        if (sort.columnIndex === null || Number.isNaN(columnIndex)) {
            return rows.slice();
        }

        const direction = String(sort.direction || "asc").toLowerCase() === "desc" ? -1 : 1;
        const columnTypes = inferPreviewColumnTypes(preview);
        const type = columnTypes[columnIndex] || "text";

        return rows.slice().sort((leftRow, rightRow) => {
            const leftValue = leftRow && leftRow.length > columnIndex ? leftRow[columnIndex] : "";
            const rightValue = rightRow && rightRow.length > columnIndex ? rightRow[columnIndex] : "";
            return comparePreviewValues(leftValue, rightValue, type) * direction;
        });
    }

    function escapeSqlIdentifier(value) {
        return `[${String(value ?? "").replaceAll("]", "]]")}]`;
    }

    function quotePreviewValue(value, type) {
        const text = String(value ?? "").trim();
        if (!text) {
            return "''";
        }
        if (type === "number") {
            return /^-?\d+(?:\.\d+)?$/.test(text) ? text : `'${text.replaceAll("'", "''")}'`;
        }
        return `N'${text.replaceAll("'", "''")}'`;
    }

    function buildFilterClause(preview, filter) {
        const value = String(filter.value ?? "").trim();
        if (!value) {
            return "1 = 1";
        }

        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        const columnName = getPreviewColumnLabel(preview, columnIndex);
        if (!columnName) {
            return "1 = 1";
        }

        const type = getFilterColumnType(preview, filter);
        const operator = String(filter.operator || "equal").toLowerCase();
        const columnSql = `[${String(columnName).replaceAll("]", "]]")}]`;

        if (type === "date") {
            const quoted = quotePreviewValue(value.slice(0, 10), "text");
            return `CONVERT(date, ${columnSql}) = ${quoted}`;
        }

        if (operator === "like") {
            const quoted = quotePreviewValue(`%${value}%`, "text");
            return `${columnSql} LIKE ${quoted}`;
        }

        return `${columnSql} = ${quotePreviewValue(value, type)}`;
    }

    function buildPreviewSql(preview) {
        const objectName = preview.qualified_name || "";
        const columns = preview.columns || [];
        if (!columns.length || !objectName) {
            return preview.sql || "";
        }

        const filters = (previewState.filters || []).filter((filter) => {
            const value = String(filter.value ?? "").trim();
            return value.length > 0;
        });

        const objectSql = objectName
            .split(".")
            .map((part) => escapeSqlIdentifier(part))
            .join(".");
        let sql = `SELECT TOP (1000) *\nFROM ${objectSql}`;
        if (filters.length) {
            const expression = filters.map((filter, index) => {
                const clause = buildFilterClause(preview, filter);
                if (index === 0) {
                    return clause;
                }
                return `${String(filter.joiner || "AND").toUpperCase()} ${clause}`;
            }).join(" ");
            sql += `\nWHERE ${expression}`;
        }
        return sql;
    }

    function rowMatchesFilter(row, preview, filter) {
        const value = String(filter.value ?? "").trim();
        if (!value) {
            return true;
        }

        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        const cell = row && row.length > columnIndex ? row[columnIndex] : "";
        const cellText = String(cell ?? "").trim();
        if (!cellText) {
            return false;
        }

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
        const activeFilters = (previewState.filters || []).filter((filter) => String(filter.value ?? "").trim().length > 0);
        if (!activeFilters.length) {
            return true;
        }

        let result = rowMatchesFilter(row, preview, activeFilters[0]);
        for (let index = 1; index < activeFilters.length; index += 1) {
            const filter = activeFilters[index];
            const nextMatch = rowMatchesFilter(row, preview, filter);
            const joiner = String(filter.joiner || "AND").toUpperCase();
            result = joiner === "OR" ? (result || nextMatch) : (result && nextMatch);
        }
        return result;
    }

    function getFilteredPreviewRows(preview) {
        const rows = preview.row_values || [];
        return rows.filter((row) => evaluatePreviewRow(row, preview));
    }

    function renderPreviewTableRows(preview, rows) {
        const columns = preview.columns || [];
        const sort = previewState.sort || {};
        const activeColumnIndex = sort.columnIndex === null ? null : Number(sort.columnIndex);
        const headerHtml = columns.map((column, index) => {
            const isActive = activeColumnIndex === index;
            const direction = isActive && String(sort.direction || "asc").toLowerCase() === "desc" ? "desc" : "asc";
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
        const bodyHtml = rows.length
            ? rows.map((row) => `<tr>${row.map((value) => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")
            : `<tr><td colspan="${Math.max(columns.length, 1)}">No rows returned.</td></tr>`;
        return `
            <table>
                <thead>
                    <tr data-table-preview-head>${headerHtml}</tr>
                </thead>
                <tbody data-table-preview-body>${bodyHtml}</tbody>
            </table>
        `;
    }

    function updatePreviewOutput(container, preview) {
        const count = container.querySelector("[data-table-preview-count]");
        const sql = container.querySelector("[data-table-preview-sql]");
        const title = container.querySelector("[data-table-preview-name]");
        const panel = container.querySelector("[data-table-preview]");
        if (!panel) {
            return;
        }

        const filteredRows = getSortedAndFilteredPreviewRows(preview);
        const totalRows = preview.row_count || 0;
        const activeFilters = (previewState.filters || []).filter((filter) => String(filter.value ?? "").trim().length > 0);
        const sqlPreview = buildPreviewSql(preview);

        if (count) {
            count.textContent = activeFilters.length ? `${filteredRows.length} of ${totalRows} rows` : `${totalRows} rows`;
        }
        if (sql) {
            sql.textContent = sqlPreview;
        }
        if (title) {
            title.textContent = preview.qualified_name || "";
        }

        const body = panel.querySelector("[data-table-preview-body]");
        const columns = preview.columns || [];
        if (body) {
            body.innerHTML = filteredRows.length
                ? filteredRows.map((row) => `<tr>${row.map((value) => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")
                : `<tr><td colspan="${Math.max(columns.length, 1)}">No rows returned.</td></tr>`;
        }
    }

    function getSortedAndFilteredPreviewRows(preview) {
        const rows = getFilteredPreviewRows(preview);
        return getSortedPreviewRows(preview, rows);
    }

    function renderFilterOperatorOptions(type, currentOperator) {
        const operators = type === "date"
            ? [{ value: "equal", label: "=" }]
            : [
                { value: "equal", label: "=" },
                { value: "like", label: "LIKE" },
            ];
        return operators.map((operator) => {
            const selected = String(currentOperator || "equal") === operator.value ? " selected" : "";
            return `<option value="${operator.value}"${selected}>${operator.label}</option>`;
        }).join("");
    }

    function bindPreviewFilterValueInput(container, element) {
        element.addEventListener("input", () => {
            const index = Number(element.dataset.previewFilterValue);
            previewState.filters[index].value = element.value || "";
        });
    }

    function syncPreviewFilterRow(container, preview, index) {
        const row = container.querySelector(`[data-preview-filter-row="${index}"]`);
        if (!row) {
            return;
        }

        const filter = previewState.filters[index];
        if (!filter) {
            return;
        }

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
                bindPreviewFilterValueInput(container, input);
            }
        }
    }

    function renderFilterRowHtml(preview, filter, index, columnTypes) {
        const columns = preview.columns || [];
        const columnIndex = clampPreviewIndex(filter.columnIndex, preview);
        const type = columnTypes[columnIndex] || "text";
        const columnOptions = columns.map((column, idx) => {
            const selected = idx === columnIndex ? " selected" : "";
            return `<option value="${idx}"${selected}>${escapeHtml(column)}</option>`;
        }).join("");
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

    function bindPreviewFilters(container, preview) {
        container.querySelectorAll("[data-preview-filter-column]").forEach((element) => {
            element.addEventListener("change", () => {
                const index = Number(element.dataset.previewFilterColumn);
                previewState.filters[index].columnIndex = Number(element.value) || 0;
                previewState.filters[index].operator = "equal";
                syncPreviewFilterRow(container, preview, index);
            });
        });

        container.querySelectorAll("[data-preview-filter-operator]").forEach((element) => {
            element.addEventListener("change", () => {
                const index = Number(element.dataset.previewFilterOperator);
                previewState.filters[index].operator = element.value || "equal";
            });
        });

        container.querySelectorAll("[data-preview-filter-value]").forEach((element) => {
            bindPreviewFilterValueInput(container, element);
        });

        container.querySelectorAll("[data-preview-filter-joiner]").forEach((element) => {
            element.addEventListener("change", () => {
                const index = Number(element.dataset.previewFilterJoiner);
                previewState.filters[index].joiner = element.value || "AND";
            });
        });

        const addButton = container.querySelector("[data-preview-filter-add]");
        if (addButton) {
            addButton.addEventListener("click", () => {
                const columns = preview.columns || [];
                if (!columns.length) {
                    return;
                }
                previewState.filters.push(createPreviewFilter(0));
                previewState.filters[previewState.filters.length - 1].joiner = "AND";
                rerenderPreviewLocally(container);
                setPreviewFilterPanelOpen(container, true);
            });
        }

        const resetButton = container.querySelector("[data-preview-filter-reset]");
        if (resetButton) {
            resetButton.addEventListener("click", () => {
                previewState.filters = (preview.columns || []).length ? [createPreviewFilter(0)] : [];
                rerenderPreviewLocally(container);
                setPreviewFilterPanelOpen(container, true);
            });
        }

        const applyButton = container.querySelector("[data-preview-filter-apply]");
        if (applyButton) {
            applyButton.addEventListener("click", () => {
                setPreviewFilterPanelOpen(container, false);
                loadPreviewForCurrentSelection(container);
            });
        }

        container.querySelectorAll("[data-preview-filter-close]").forEach((element) => {
            element.addEventListener("click", () => {
                setPreviewFilterPanelOpen(container, false);
            });
        });

        container.querySelectorAll("[data-preview-filter-remove]").forEach((element) => {
            element.addEventListener("click", () => {
                const index = Number(element.dataset.previewFilterRemove);
                previewState.filters.splice(index, 1);
                if (!previewState.filters.length && (preview.columns || []).length) {
                    previewState.filters = [createPreviewFilter(0)];
                }
                rerenderPreviewLocally(container);
                setPreviewFilterPanelOpen(container, true);
            });
        });
    }

    function renderTablePreview(container, preview, preserveState = false) {
        const title = container.querySelector("[data-table-preview-name]");
        const count = container.querySelector("[data-table-preview-count]");
        const panel = container.querySelector("[data-table-preview]");
        const columns = preview.columns || [];

        if (!preserveState) {
            previewState.filters = columns.length ? [createPreviewFilter(0)] : [];
            previewState.filterPanelOpen = false;
            previewState.sort = {
                columnIndex: null,
                direction: "asc",
            };
        }

        previewState.preview = preview;
        if (limitSelect) {
            limitSelect.value = previewState.limit || "1000";
        }
        const rowValues = getSortedAndFilteredPreviewRows(preview);
        const activeFilters = (previewState.filters || []).filter((filter) => String(filter.value ?? "").trim().length > 0);
        const sqlPreview = preview.sql || buildPreviewSql(preview);

        if (title) {
            title.textContent = preview.qualified_name || "";
        }
        if (count) {
            count.textContent = activeFilters.length
                ? `${rowValues.length} of ${preview.row_count || 0} rows`
                : `${preview.row_count || 0} rows`;
        }
        if (!panel) {
            return;
        }

        if (preview.error) {
            panel.innerHTML = `<div class="empty">${escapeHtml(preview.error)}</div>`;
            return;
        }

        const columnTypes = inferPreviewColumnTypes(preview);
        const filterRowsHtml = (previewState.filters || []).map((filter, index) => renderFilterRowHtml(preview, filter, index, columnTypes)).join("");
        const tableHtml = renderPreviewTableRows(preview, rowValues);

        panel.innerHTML = `
            <div class="table-preview-meta">
                <div>
                    <span class="eyebrow">Selected object</span>
                    <strong data-table-preview-name>${escapeHtml(preview.qualified_name || "")}</strong>
                </div>
                <div class="table-subtext">SQL preview: <code data-table-preview-sql>${escapeHtml(sqlPreview)}</code></div>
            </div>
            <div class="preview-filter-modal" data-preview-filter-modal hidden aria-hidden="true">
                <div class="preview-filter-modal-backdrop" data-preview-filter-close></div>
                <div class="preview-filter-bar" data-preview-filter-panel role="dialog" aria-modal="true" aria-label="Preview filters">
                    <div class="preview-filter-head">
                        <div>
                            <span class="eyebrow">Filters</span>
                            <h3>Preview filters</h3>
                        </div>
                        <button type="button" class="icon-button preview-filter-close" data-preview-filter-close aria-label="Close filters" title="Close filters"></button>
                    </div>
                    <div class="preview-filter-stack" data-preview-filter-stack>
                        ${filterRowsHtml}
                    </div>
                    <div class="preview-filter-actions">
                        <button type="button" class="button secondary preview-filter-add" data-preview-filter-add>Add filter</button>
                        <button type="button" class="button preview-filter-apply" data-preview-filter-apply>Apply</button>
                        <button type="button" class="button secondary preview-filter-reset" data-preview-filter-reset>Reset</button>
                    </div>
                </div>
            </div>
            <div class="table-wrap live-table-wrap">
                ${tableHtml}
            </div>
        `;

        bindPreviewFilters(container, preview);
        bindPreviewSorting(container);
    }

    function bindPreviewSorting(container) {
        container.querySelectorAll("[data-preview-sort-column]").forEach((element) => {
            element.addEventListener("click", () => {
                const index = Number(element.dataset.previewSortColumn);
                if (Number.isNaN(index)) {
                    return;
                }
                if (previewState.sort.columnIndex === index) {
                    previewState.sort.direction = String(previewState.sort.direction || "asc").toLowerCase() === "asc" ? "desc" : "asc";
                } else {
                    previewState.sort.columnIndex = index;
                    previewState.sort.direction = "asc";
                }
                rerenderPreviewLocally(container);
            });
        });
    }

    document.querySelectorAll(".js-verify-source").forEach(button => {
        button.addEventListener("click", async () => {
            const url = button.dataset.verifyUrl;
            const container = button.closest("[data-source-key]") || document;
            const originalContent = button.innerHTML;
            button.disabled = true;
            button.classList.add("loading");
            button.innerHTML = "";

            try {
                const response = await fetch(url, {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken"),
                        "Accept": "application/json",
                    },
                });
                const payload = await response.json();
                updateStatus(container, payload);
                showFlash(payload.ok ? "Connection successful." : "Connection failed.", !payload.ok);
            } catch (error) {
                showFlash("Connection failed.", true);
            } finally {
                button.disabled = false;
                button.classList.remove("loading");
                button.innerHTML = originalContent;
            }
        });
    });

    async function submitSourceAjaxForm(form, url, options = {}) {
        const submitButton = form.querySelector('button[type="submit"]');
        const originalLabel = submitButton ? submitButton.innerHTML : "";
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.classList.add("loading");
            submitButton.innerHTML = "";
        }

        try {
            const formData = new FormData(form);
            const response = await fetch(url, {
                method: "POST",
                body: formData,
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": getCookie("csrftoken"),
                    "Accept": "application/json",
                },
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Request failed.");
            }
            const message = typeof options.successMessageFactory === "function"
                ? options.successMessageFactory(payload)
                : options.successMessageFactory;
            if (message) {
                showFlash(message, false);
            }
            if (typeof options.onSuccess === "function") {
                options.onSuccess(payload, form);
            }
        } catch (error) {
            showFlash(error && error.message ? error.message : "Request failed.", true);
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.classList.remove("loading");
                submitButton.innerHTML = originalLabel;
            }
        }
    }

    document.querySelectorAll("[data-source-database-form]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const url = form.dataset.sourceDatabaseUrl || form.getAttribute("action") || "";
            if (!url) {
                showFlash("Database update endpoint is unavailable.", true);
                return;
            }
            await submitSourceAjaxForm(form, url, {
                successMessageFactory: (payload) => `Database changed to ${payload.source && payload.source.database ? payload.source.database : "selected database"}.`,
                onSuccess: (payload) => {
                    syncSourceMetadata(payload || {});
                    renderCatalogBody(payload.catalog || {});
                    resetPreviewPane();
                },
            });
        });
    });

    document.querySelectorAll("[data-custom-view-form]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const url = form.dataset.customViewUrl || form.getAttribute("action") || "";
            if (!url) {
                showFlash("Custom view endpoint is unavailable.", true);
                return;
            }
            await submitSourceAjaxForm(form, url, {
                successMessageFactory: (payload) => `Custom view ${payload.view && payload.view.name ? payload.view.name : "created"}.`,
                onSuccess: (payload) => {
                    syncSourceMetadata(payload || {});
                    renderCatalogBody(payload.catalog || {});
                    form.reset();
                },
            });
        });
    });

    function getCustomViewModal() {
        return document.querySelector("[data-custom-view-modal]");
    }

    function setCustomViewModalOpen(isOpen) {
        const modal = getCustomViewModal();
        if (!modal) {
            return;
        }
        modal.hidden = !isOpen;
        modal.setAttribute("aria-hidden", isOpen ? "false" : "true");
        document.body.classList.toggle("modal-open", isOpen);
    }

    function fillCustomViewEditForm(view, editUrl) {
        const form = document.querySelector("[data-custom-view-edit-form]");
        if (!form) {
            return;
        }
        form.dataset.editUrl = editUrl || "";
        const name = form.querySelector('[name="name"]');
        const description = form.querySelector('[name="description"]');
        const sql = form.querySelector('[name="sql"]');
        if (name) name.value = view.name || "";
        if (description) description.value = view.description || "";
        if (sql) sql.value = view.sql || "";
    }

    function bindCustomViewButtons(scope = document) {
        scope.querySelectorAll(".js-edit-custom-view").forEach((button) => {
            if (button.dataset.editBound === "1") {
                return;
            }
            button.dataset.editBound = "1";
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                event.stopPropagation();
                const editUrl = button.dataset.editUrl || "";
                if (!editUrl) {
                    showFlash("Custom view edit endpoint is unavailable.", true);
                    return;
                }
                button.disabled = true;
                button.classList.add("loading");
                try {
                    const response = await fetch(editUrl, {
                        method: "GET",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json",
                        },
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        throw new Error(payload.error || "Unable to load custom view.");
                    }
                    fillCustomViewEditForm(payload.view || {}, editUrl);
                    setCustomViewModalOpen(true);
                } catch (error) {
                    showFlash(error && error.message ? error.message : "Unable to load custom view.", true);
                } finally {
                    button.disabled = false;
                    button.classList.remove("loading");
                }
            });
        });

        scope.querySelectorAll(".js-delete-custom-view").forEach((button) => {
            if (button.dataset.deleteBound === "1") {
                return;
            }
            button.dataset.deleteBound = "1";
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                event.stopPropagation();
                const deleteUrl = button.dataset.deleteUrl || "";
                const viewName = button.dataset.viewName || "this custom view";
                if (!deleteUrl) {
                    showFlash("Custom view delete endpoint is unavailable.", true);
                    return;
                }
                if (!window.confirm(`Delete custom view "${viewName}"?`)) {
                    return;
                }
                button.disabled = true;
                button.classList.add("loading");
                try {
                    const response = await fetch(deleteUrl, {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": getCookie("csrftoken"),
                            "Accept": "application/json",
                        },
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        throw new Error(payload.error || "Unable to delete custom view.");
                    }
                    syncSourceMetadata(payload || {});
                    renderCatalogBody(payload.catalog || {});
                    resetPreviewPane();
                    showFlash("Custom view deleted.", false);
                } catch (error) {
                    showFlash(error && error.message ? error.message : "Unable to delete custom view.", true);
                } finally {
                    button.disabled = false;
                    button.classList.remove("loading");
                }
            });
        });
    }

    bindCustomViewButtons(document);

    document.querySelectorAll("[data-custom-view-modal-close]").forEach((button) => {
        button.addEventListener("click", () => setCustomViewModalOpen(false));
    });

    document.querySelectorAll("[data-custom-view-edit-form]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const editUrl = form.dataset.editUrl || "";
            if (!editUrl) {
                showFlash("Custom view edit endpoint is unavailable.", true);
                return;
            }
            await submitSourceAjaxForm(form, editUrl, {
                successMessageFactory: (payload) => `Custom view ${payload.view && payload.view.name ? payload.view.name : "updated"}.`,
                onSuccess: (payload) => {
                    syncSourceMetadata(payload || {});
                    renderCatalogBody(payload.catalog || {});
                    resetPreviewPane("Custom view updated. Select it again to load the updated preview.");
                    setCustomViewModalOpen(false);
                },
            });
        });
    });

    document.querySelectorAll(".js-export-preview").forEach((button) => {
        if (button.dataset.exportBound === "1") {
            return;
        }
        button.dataset.exportBound = "1";
        button.addEventListener("click", () => {
            if (!previewState.previewUrl) {
                showFlash("Select a table, view, or custom view first.", true);
                return;
            }
            const baseUrl = button.dataset.previewExportUrl || button.getAttribute("data-preview-export-url") || "";
            if (!baseUrl) {
                showFlash("Export endpoint is unavailable.", true);
                return;
            }
            const target = new URL(baseUrl, window.location.origin);
            target.searchParams.set("preview_url", previewState.previewUrl);
            target.searchParams.set("filters", JSON.stringify(buildPreviewFiltersPayload()));
            target.searchParams.set("limit", "all");
            window.location.href = target.toString();
        });
    });

    document.querySelectorAll(".js-toggle-preview-filters").forEach((button) => {
        button.addEventListener("click", () => {
            const container = document.querySelector("[data-source-key]");
            if (!container) {
                return;
            }
            setPreviewFilterPanelOpen(container, !previewState.filterPanelOpen);
            if (previewState.filterPanelOpen) {
                window.setTimeout(() => {
                    const firstField = container.querySelector("[data-preview-filter-panel] input, [data-preview-filter-panel] select");
                    if (firstField && typeof firstField.focus === "function") {
                        firstField.focus();
                    }
                }, 0);
            }
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && previewState.filterPanelOpen) {
            const container = document.querySelector("[data-source-key]");
            if (container) {
                setPreviewFilterPanelOpen(container, false);
            }
        }
    });

    document.querySelectorAll(".js-delete-source").forEach(button => {
        button.addEventListener("click", async () => {
            const url = button.dataset.deleteUrl;
            const redirectUrl = button.dataset.deleteRedirect || "";
            const container = button.closest("[data-source-key]") || document;
            if (!window.confirm("Delete this source?")) {
                return;
            }

            const originalContent = button.innerHTML;
            button.disabled = true;
            button.classList.add("loading");
            button.innerHTML = "";

            try {
                const response = await fetch(url, {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken"),
                        "Accept": "application/json",
                    },
                });
                const payload = await response.json();
                if (payload.ok) {
                    if (redirectUrl) {
                        sessionStorage.setItem("source-flash-message", "Source deleted.");
                        sessionStorage.setItem("source-flash-error", "0");
                        window.location.href = redirectUrl;
                        return;
                    }
                    showFlash("Source deleted.");
                    if (container && container !== document) {
                        container.remove();
                    }
                } else {
                    showFlash("Delete failed.", true);
                }
            } catch (error) {
                showFlash("Delete failed.", true);
            } finally {
                button.disabled = false;
                button.classList.remove("loading");
                button.innerHTML = originalContent;
            }
        });
    });

    bindCatalogPreviewButtons(document);

    const dqState = {
        open: false,
        busy: false,
        currentRunId: null,
        currentRun: null,
        currentPreviewUrl: "",
        currentResults: [],
        runUrl: "",
    };

    function getDataQualityModal() {
        return document.querySelector("[data-dq-modal]");
    }

    function getDataQualityBody() {
        return document.querySelector("[data-dq-body]");
    }

    function getDataQualitySpinner() {
        return document.querySelector("[data-dq-spinner]");
    }

    function getDataQualityContext() {
        return document.querySelector("[data-dq-context]");
    }

    function getDataQualityStatus() {
        return document.querySelector("[data-dq-status]");
    }

    function getDataQualityScore() {
        return document.querySelector("[data-dq-score]");
    }

    function getDataQualityLastRun() {
        return document.querySelector("[data-dq-last-run]");
    }

    function getDataQualityControlCount() {
        return document.querySelector("[data-dq-control-count]");
    }

    function getDataQualityCenterLink() {
        return document.querySelector("[data-dq-center-link]");
    }

    function getDataQualityRecordsPanel() {
        return document.querySelector("[data-dq-records-panel]");
    }

    function getDataQualityRecordsHead() {
        return document.querySelector("[data-dq-records-head]");
    }

    function getDataQualityRecordsBody() {
        return document.querySelector("[data-dq-records-body]");
    }

    function getDataQualityRecordsTitle() {
        return document.querySelector("[data-dq-records-title]");
    }

    function getDataQualityRecordsExport() {
        return document.querySelector("[data-dq-records-export]");
    }

    function getActiveDataQualityPreviewUrl() {
        if (previewState.previewUrl) {
            return previewState.previewUrl;
        }
        const page = document.querySelector("[data-dq-page]");
        if (page && page.dataset.dqPreviewUrl) {
            return page.dataset.dqPreviewUrl;
        }
        return "";
    }

    function getActiveDataQualityPreviewSnapshot() {
        const preview = previewState.preview || {};
        return {
            sql: preview.sql || "",
            columns: Array.isArray(preview.columns) ? preview.columns : [],
            column_types: Array.isArray(preview.column_types) ? preview.column_types : [],
            rows: Array.isArray(preview.rows) ? preview.rows : [],
            row_values: Array.isArray(preview.row_values) ? preview.row_values : [],
            row_count: Number(preview.row_count || 0),
            qualified_name: preview.qualified_name || "",
            filters: (previewState.filters || []).map((filter) => ({
                columnIndex: Number(filter.columnIndex || 0),
                operator: filter.operator || "equal",
                value: filter.value || "",
                joiner: filter.joiner || "AND",
            })),
            limit: previewState.limit || "1000",
        };
    }

    function getActiveDataQualitySourceKey() {
        const shell = document.querySelector("[data-source-key]");
        if (shell && shell.dataset.sourceKey) {
            return shell.dataset.sourceKey;
        }
        const page = document.querySelector("[data-dq-page]");
        if (page && page.dataset.sourceKey) {
            return page.dataset.sourceKey;
        }
        return "";
    }

    function setDataQualityBusy(isBusy) {
        dqState.busy = Boolean(isBusy);
        const spinner = getDataQualitySpinner();
        if (spinner) {
            spinner.hidden = !dqState.busy;
        }
        document.body.classList.toggle("dq-busy", dqState.busy);
    }

    function dqBadgeClass(status) {
        const value = String(status || "").toLowerCase();
        if (value === "ok") {
            return "success";
        }
        if (value === "critical") {
            return "failed";
        }
        return "neutral";
    }

    function dqRenderRow(entry, runId = null) {
        const status = entry.status || "Not run";
        const badge = dqBadgeClass(status);
        const impacted = Number(entry.impacted_records || 0);
        const percentage = Number(entry.error_percentage || 0);
        const execution = Number(entry.execution_ms || 0);
        const resolvedRunId = runId || entry.latest_run_id || "";
        const exportUrl = resolvedRunId && entry.key ? `/data-quality/runs/${encodeURIComponent(String(resolvedRunId))}/export/${encodeURIComponent(entry.key)}/` : "#";
        return `
            <tr data-dq-control-key="${escapeHtml(entry.key || "")}">
                <td>${escapeHtml(entry.name || "")}</td>
                <td>${escapeHtml(entry.category || "")}</td>
                <td><span class="status-badge ${badge}">${escapeHtml(status)}</span></td>
                <td>${impacted}</td>
                <td>${percentage}%</td>
                <td>${escapeHtml(entry.description || "")}</td>
                <td>${execution}</td>
                <td class="dq-actions">
                    <button type="button" class="button secondary" data-dq-run-control data-dq-control-key="${escapeHtml(entry.key || "")}">Run</button>
                    <button type="button" class="button secondary" data-dq-view-records data-dq-run-id="${escapeHtml(String(resolvedRunId || ""))}" data-dq-control-key="${escapeHtml(entry.key || "")}" ${resolvedRunId ? "" : "disabled"}>View Records</button>
                    <a class="button secondary" data-dq-records-export href="${exportUrl}" ${resolvedRunId ? "" : "aria-disabled=\"true\" tabindex=\"-1\""}>Export</a>
                </td>
            </tr>
        `;
    }

    function updateDataQualitySummary(run) {
        const score = getDataQualityScore();
        const status = getDataQualityStatus();
        const lastRun = getDataQualityLastRun();
        const count = getDataQualityControlCount();
        if (score && run) {
            score.textContent = `${Number(run.score || 0).toFixed(0)}%`;
        }
        if (status && run) {
            status.textContent = run.status || "Completed";
        }
        if (lastRun && run) {
            lastRun.textContent = run.created_at ? new Date(run.created_at).toLocaleString() : "-";
        }
        if (count && run) {
            count.textContent = String(run.controls_count || 0);
        }
    }

    function applyDataQualityResults(results, run, replaceMissingRows = false) {
        const body = getDataQualityBody();
        if (!body) {
            return;
        }
        dqState.currentRunId = run ? run.id || null : null;
        dqState.currentRun = run || null;
        dqState.currentResults = Array.isArray(results) ? results : [];
        updateDataQualitySummary(run || {});

        const resultsByKey = new Map();
        dqState.currentResults.forEach((entry) => {
            if (entry && entry.key) {
                resultsByKey.set(entry.key, entry);
            }
        });

        const rows = Array.from(body.querySelectorAll("tr[data-dq-control-key]"));
        rows.forEach((row) => {
            const key = row.dataset.dqControlKey || "";
            const result = resultsByKey.get(key);
            if (!result) {
                return;
            }
            row.outerHTML = dqRenderRow({
                key: result.key,
                name: result.name,
                category: result.category,
                status: result.status,
                impacted_records: result.impacted_records,
                error_percentage: result.error_percentage,
                description: result.description,
                execution_ms: result.execution_ms,
                records: result.records || [],
                latest_run_id: run ? run.id : null,
            }, run ? run.id : null);
        });

        if (replaceMissingRows && !rows.length) {
            body.innerHTML = dqState.currentResults.length
                ? dqState.currentResults.map((result) => dqRenderRow(result, run ? run.id : null)).join("")
                : `<tr><td colspan="8" class="empty compact">No data quality checks available.</td></tr>`;
        }

        applyDataQualitySearch();
        bindDataQualityRowActions(body);
    }

    function setDataQualityRecords(records, columns, control, run) {
        const panel = getDataQualityRecordsPanel();
        const head = getDataQualityRecordsHead();
        const body = getDataQualityRecordsBody();
        const title = getDataQualityRecordsTitle();
        const exportLink = getDataQualityRecordsExport();
        if (!panel || !head || !body || !title || !exportLink) {
            return;
        }
        const safeColumns = Array.isArray(columns) && columns.length ? columns : Object.keys((records && records[0]) || {});
        head.innerHTML = `<tr>${safeColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>`;
        body.innerHTML = records.length
            ? records.map((record) => `<tr>${safeColumns.map((column) => `<td>${escapeHtml(record[column])}</td>`).join("")}</tr>`).join("")
            : `<tr><td colspan="${Math.max(safeColumns.length, 1)}" class="empty compact">No impacted records.</td></tr>`;
        title.textContent = `${control.name || "View Records"}${run && run.object_name ? ` - ${run.object_name}` : ""}`;
        const runId = run && run.id ? run.id : "";
        const exportUrl = runId && control.key ? `/data-quality/runs/${encodeURIComponent(String(runId))}/export/${encodeURIComponent(control.key)}/` : "#";
        exportLink.href = exportUrl;
        exportLink.setAttribute("aria-disabled", runId ? "false" : "true");
        exportLink.tabIndex = runId ? 0 : -1;
        panel.hidden = false;
        if (typeof panel.scrollIntoView === "function") {
            panel.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    function showCachedDataQualityRecords(controlKey) {
        const result = (dqState.currentResults || []).find((entry) => String(entry.key || "") === String(controlKey || ""));
        if (!result) {
            return false;
        }
        setDataQualityRecords(result.records || [], result.affected_columns || [], result, dqState.currentRun || {});
        return true;
    }

    function bindDataQualityRowActions(root = document) {
        root.querySelectorAll("[data-dq-run-control]").forEach((button) => {
            if (button.dataset.dqBound === "1") {
                return;
            }
            button.dataset.dqBound = "1";
            button.onclick = (event) => {
                event.preventDefault();
                event.stopPropagation();
                runDataQualityCheck(button.dataset.dqControlKey || "");
            };
        });

        root.querySelectorAll("[data-dq-view-records]").forEach((button) => {
            if (button.dataset.dqBound === "1") {
                return;
            }
            button.dataset.dqBound = "1";
            button.onclick = (event) => {
                event.preventDefault();
                event.stopPropagation();
                const controlKey = button.dataset.dqControlKey || "";
                if (showCachedDataQualityRecords(controlKey)) {
                    return;
                }
                loadDataQualityRecords(button.dataset.dqRunId || "", controlKey);
            };
        });

        root.querySelectorAll("[data-dq-close]").forEach((button) => {
            if (button.dataset.dqBound === "1") {
                return;
            }
            button.dataset.dqBound = "1";
            button.onclick = (event) => {
                event.preventDefault();
                event.stopPropagation();
                closeDataQualityModal();
            };
        });
    }

    function openDataQualityModal() {
        const modal = getDataQualityModal();
        if (!modal) {
            return;
        }
        dqState.open = true;
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("dq-modal-open");
        const context = getDataQualityContext();
        const preview = previewState.preview || {};
        const openButton = document.querySelector(".js-open-data-quality");
        dqState.runUrl = openButton?.dataset.dqRunUrl
            || document.querySelector("[data-dq-page]")?.dataset.dqRunUrl
            || "";
        if (context) {
            context.textContent = preview.qualified_name
                ? `Running checks for ${preview.qualified_name}.`
                : "Select a table, view, or custom view before running checks.";
        }
        const centerLink = getDataQualityCenterLink();
        if (centerLink) {
            const centerUrl = new URL(centerLink.dataset.dqCenterUrl || centerLink.href, window.location.origin);
            const previewUrl = getActiveDataQualityPreviewUrl();
            const sourceKey = getActiveDataQualitySourceKey();
            if (sourceKey) {
                centerUrl.searchParams.set("source_key", sourceKey);
            }
            if (preview.qualified_name) {
                centerUrl.searchParams.set("object_name", preview.qualified_name);
            }
            if (previewUrl) {
                centerUrl.searchParams.set("preview_url", previewUrl);
            }
            centerLink.href = centerUrl.toString();
        }
        setDataQualityBusy(false);
        bindDataQualityRowActions(modal);
    }

    function closeDataQualityModal() {
        const modal = getDataQualityModal();
        if (!modal) {
            return;
        }
        dqState.open = false;
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("dq-modal-open");
        const recordsPanel = getDataQualityRecordsPanel();
        if (recordsPanel) {
            recordsPanel.hidden = true;
        }
    }

    async function runDataQualityCheck(controlKey = null) {
        const sourceKey = getActiveDataQualitySourceKey();
        const previewUrl = getActiveDataQualityPreviewUrl();
        if (!sourceKey || !previewUrl) {
            showFlash("Select a table, view, or custom view first.", true);
            return;
        }

        const runUrl = dqState.runUrl || document.querySelector("[data-dq-page]")?.dataset.dqRunUrl || document.querySelector(".js-open-data-quality")?.dataset.dqRunUrl || "";
        if (!runUrl) {
            showFlash("Data quality endpoint is unavailable.", true);
            return;
        }

        const status = getDataQualityStatus();
        if (status) {
            status.textContent = "Running";
        }
        showFlash(controlKey ? `Running ${controlKey}...` : "Running all checks...");
        setDataQualityBusy(true);
        try {
            const formData = new FormData();
            formData.append("source_key", sourceKey);
            formData.append("preview_url", previewUrl);
            formData.append("payload", JSON.stringify({
                metadata: {},
                preview: getActiveDataQualityPreviewSnapshot(),
            }));
            if (controlKey) {
                formData.append("control_key", controlKey);
            }

            const payload = await fetchJsonWithTimeout(runUrl, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": getCookie("csrftoken"),
                    "Accept": "application/json",
                },
                body: formData,
            });

            if (!payload.ok) {
                throw new Error(payload.error || "Data Check failed.");
            }

            dqState.currentPreviewUrl = previewUrl;
            applyDataQualityResults(payload.results || [], payload.run || {}, false);
            showFlash(controlKey ? "Data Check completed." : "All Data Checks completed.");
        } catch (error) {
            showFlash(error && error.message ? error.message : "Data Check failed.", true);
        } finally {
            setDataQualityBusy(false);
        }
    }

    async function loadDataQualityRecords(runId, controlKey) {
        if (!runId || !controlKey) {
            return;
        }
        setDataQualityBusy(true);
        try {
            const url = `/data-quality/runs/${encodeURIComponent(runId)}/records/${encodeURIComponent(controlKey)}/`;
            const payload = await fetchJsonWithTimeout(url, {
                method: "GET",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
            });
            if (!payload.ok) {
                throw new Error(payload.error || "Unable to load impacted records.");
            }
            setDataQualityRecords(payload.records || [], payload.columns || [], payload.control || {}, payload.run || {});
        } catch (error) {
            showFlash(error && error.message ? error.message : "Unable to load impacted records.", true);
        } finally {
            setDataQualityBusy(false);
        }
    }

    function applyDataQualitySearch() {
        const body = getDataQualityBody();
        if (!body) {
            return;
        }
        const search = document.querySelector("[data-dq-search]");
        const category = document.querySelector("[data-dq-category]");
        const query = String(search ? search.value : "").trim().toLowerCase();
        const selectedCategory = String(category ? category.value : "").trim().toLowerCase();
        body.querySelectorAll("tr[data-dq-control-key]").forEach((row) => {
            const text = row.textContent.toLowerCase();
            const rowCategory = String(row.children[1]?.textContent || "").trim().toLowerCase();
            const visible = (!query || text.includes(query)) && (!selectedCategory || rowCategory === selectedCategory);
            row.style.display = visible ? "" : "none";
        });
    }

    const dqOpenButton = document.querySelector(".js-open-data-quality");
    if (dqOpenButton) {
        dqOpenButton.onclick = () => {
            if (!getActiveDataQualityPreviewUrl()) {
                showFlash("Select a table, view, or custom view first.", true);
                return;
            }
            dqState.runUrl = dqOpenButton.dataset.dqRunUrl || dqState.runUrl;
            openDataQualityModal();
        };
    }

    bindDataQualityRowActions(document);

    document.querySelectorAll("[data-dq-run-all]").forEach((button) => {
        if (button.dataset.dqBound === "1") {
            return;
        }
        button.dataset.dqBound = "1";
        button.onclick = (event) => {
            event.preventDefault();
            event.stopPropagation();
            runDataQualityCheck(null);
        };
    });

    document.querySelectorAll("[data-dq-search]").forEach((input) => {
        input.oninput = applyDataQualitySearch;
    });

    document.querySelectorAll("[data-dq-category]").forEach((input) => {
        input.onchange = applyDataQualitySearch;
    });

    const dqExportButton = document.querySelector("[data-dq-records-export]");
    if (dqExportButton) {
        dqExportButton.addEventListener("click", (event) => {
            if (dqExportButton.getAttribute("aria-disabled") === "true") {
                event.preventDefault();
            }
        });
    }
})();
