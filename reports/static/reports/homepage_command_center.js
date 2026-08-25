(() => {
    "use strict";

    const root = document.getElementById("availability-command-center");
    if (!root) return;

    // Start the command center with compact navigation on small screens. The
    // existing global toggle remains available when the user needs the menu.
    if (window.matchMedia("(max-width: 900px)").matches) {
        document.body.classList.add("nav-collapsed");
    }

    const $ = (selector, scope = root) => scope.querySelector(selector);
    const $$ = (selector, scope = root) => Array.from(scope.querySelectorAll(selector));
    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const validPeriods = new Set(["ytd", "last_12_months"]);
    const validBreakdowns = new Set(["overall", "minesite", "model", "equipment"]);
    const params = new URLSearchParams(window.location.search);
    const state = {
        period: validPeriods.has(params.get("period")) ? params.get("period") : "ytd",
        breakdown: validBreakdowns.has(params.get("breakdown")) ? params.get("breakdown") : "overall",
        filters: {
            minesite: params.get("minesite") || "",
            model: params.get("model") || "",
            equipment: params.get("equipment") || "",
            serial_number: params.get("serial_number") || "",
            customer: params.get("customer") || "",
        },
        query: params.get("q") || "",
        ordering: params.get("ordering") || "availability_desc",
        page: Math.max(1, Number(params.get("page")) || 1),
        pageSize: 25,
        controller: null,
        payload: null,
        renderedValue: null,
        searchTimer: null,
        initialLoad: true,
    };

    function dismissBrandLoader() {
        if (!state.initialLoad) return;
        state.initialLoad = false;
        root.setAttribute("aria-busy", "false");
        const loader = $("[data-brand-loader]");
        if (!loader) return;
        loader.classList.add("is-leaving");
        window.setTimeout(() => { loader.hidden = true; }, reducedMotion.matches ? 0 : 360);
    }

    function apiParams() {
        const result = new URLSearchParams({
            period: state.period,
            breakdown: state.breakdown,
            ordering: state.ordering,
            page: String(state.page),
            page_size: String(state.pageSize),
        });
        Object.entries(state.filters).forEach(([key, value]) => {
            if (value) result.set(key, value);
        });
        if (state.query) result.set("q", state.query);
        return result;
    }

    function syncUrl(replace = false) {
        const url = new URL(window.location.href);
        ["period", "breakdown", "ordering", "page", "minesite", "model", "equipment", "serial_number", "customer", "q"]
            .forEach((key) => url.searchParams.delete(key));
        const current = apiParams();
        current.delete("page_size");
        current.forEach((value, key) => {
            if ((key === "page" && value === "1") || (key === "ordering" && value === "availability_desc")) return;
            url.searchParams.set(key, value);
        });
        window.history[replace ? "replaceState" : "pushState"]({}, "", url);
    }

    function csrfToken() {
        return document.querySelector('meta[name="csrf-token"]')?.content || "";
    }

    function track(eventType, extra = {}) {
        const context = {
            period: state.period,
            breakdown: state.breakdown,
            ...state.filters,
            ...extra,
        };
        fetch(root.dataset.eventsUrl, {
            method: "POST",
            credentials: "same-origin",
            keepalive: true,
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
            body: JSON.stringify({ event_type: eventType, context }),
        }).catch(() => {});
    }

    function setPressed(selector, attribute, value) {
        $$(selector).forEach((button) => {
            button.setAttribute("aria-pressed", String(button.dataset[attribute] === value));
        });
    }

    function syncControls() {
        setPressed("[data-period]", "period", state.period);
        setPressed("[data-breakdown]", "breakdown", state.breakdown);
        const context = $("[data-context-controls]");
        const siteField = $('[data-filter-field="minesite"]');
        const modelField = $('[data-filter-field="model"]');
        const equipmentField = $('[data-filter-field="equipment"]');
        const showSite = true;
        const showModel = true;
        const showEquipment = true;
        siteField.hidden = !showSite;
        modelField.hidden = !showModel;
        equipmentField.hidden = !showEquipment;
        context.hidden = !(showSite || showModel || showEquipment);
        $('[data-filter="minesite"]').value = state.filters.minesite;
        $('[data-filter="model"]').value = state.filters.model;
        $('[data-filter="equipment"]').value = state.filters.equipment;
        $("[data-ordering]").value = state.ordering;
        $("[data-order-field]").hidden = state.breakdown === "overall";
        $("[data-breakdown-section]").hidden = state.breakdown === "overall" || state.breakdown === "equipment";
        $("[data-period-label]").textContent = state.period === "ytd" ? "Year to Date" : "Last 12 Months";
        const titles = {
            overall: "Overall fleet performance",
            minesite: "Availability by Mine Site",
            model: "Availability by Model",
            equipment: "Equipment analysis",
        };
        $("[data-breakdown-title]").textContent = titles[state.breakdown];
        renderBreadcrumb();
    }

    function renderBreadcrumb() {
        const holder = $("[data-breadcrumb]");
        const parts = [{ label: "All MineSites", clear: ["minesite", "model", "equipment", "serial_number"] }];
        if (state.filters.minesite) parts.push({ label: state.filters.minesite, clear: ["model", "equipment", "serial_number"] });
        if (state.filters.model) parts.push({ label: `Model ${state.filters.model}`, clear: ["equipment", "serial_number"] });
        if (state.filters.equipment || state.filters.serial_number) parts.push({ label: state.filters.equipment || state.filters.serial_number, clear: [] });
        holder.innerHTML = parts.map((part, index) => (
            `<button type="button" data-breadcrumb-index="${index}">${escapeHtml(part.label)}</button>`
        )).join("");
        $$('[data-breadcrumb-index]', holder).forEach((button) => {
            button.addEventListener("click", () => {
                const part = parts[Number(button.dataset.breadcrumbIndex)];
                part.clear.forEach((key) => { state.filters[key] = ""; });
                if (Number(button.dataset.breadcrumbIndex) === 0) state.breakdown = "minesite";
                else if (state.filters.minesite && !state.filters.model) state.breakdown = "model";
                state.page = 1;
                syncControls();
                syncUrl();
                loadData();
            });
        });
    }

    function setUpdating(active) {
        root.classList.toggle("is-updating", active);
        $("[data-updating]").hidden = !active;
        $$("button, select, input", $(".analysis-controls")).forEach((control) => {
            if (control.matches("[data-filter='q']")) return;
            control.disabled = active;
        });
    }

    function showError(message) {
        const error = $("[data-homepage-error]");
        $("[data-error-message]", error).textContent = message || "Please retry in a moment.";
        error.hidden = false;
        const connection = $("[data-connection-status]");
        connection.classList.remove("is-ready");
        connection.classList.add("is-error");
        $("span", connection).textContent = "Power BI unavailable";
    }

    function clearError() {
        $("[data-homepage-error]").hidden = true;
    }

    function animateValue(target) {
        const holder = $("[data-availability-value]");
        if (target == null) {
            holder.textContent = "--";
            state.renderedValue = null;
            return;
        }
        const from = state.renderedValue == null ? 0 : state.renderedValue;
        const duration = reducedMotion.matches ? 0 : (state.renderedValue == null ? 850 : 360);
        const started = performance.now();
        const draw = (now) => {
            const progress = duration ? Math.min(1, (now - started) / duration) : 1;
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = from + (target - from) * eased;
            holder.textContent = `${(current * 100).toFixed(2)}%`;
            if (progress < 1) window.requestAnimationFrame(draw);
            else state.renderedValue = target;
        };
        window.requestAnimationFrame(draw);
    }

    function statusLabel(status) {
        return {
            on_target: "On Target",
            attention: "Attention",
            below_target: "Below Target",
            critical: "Critical",
            data_quality_issue: "Data issue",
        }[status] || "";
    }

    function renderHero(payload) {
        const availability = payload.availability || {};
        const value = availability.raw_value;
        animateValue(value);
        const ring = $("[data-ring]");
        ring.dataset.quality = availability.quality_status || "valid";
        if (availability.quality_status === "out_of_range") {
            $("[data-availability-value]").textContent = "Invalid data";
        }
        const angle = value == null ? 0 : Math.max(0, Math.min(360, value * 360));
        ring.style.setProperty("--ring-progress", `${angle}deg`);
        ring.setAttribute("aria-label", value == null
            ? "Physical Availability unavailable."
            : `Physical Availability: ${(value * 100).toFixed(2)} percent.`);
        const status = $("[data-availability-status]");
        status.hidden = !availability.status;
        status.dataset.status = availability.status || "";
        status.textContent = statusLabel(availability.status);
        const target = $("[data-target-summary]");
        target.hidden = availability.target_raw == null;
        $("[data-target-value]").textContent = availability.target_formatted || "--";
        const comparison = $("[data-comparison-summary]");
        comparison.hidden = !availability.comparison;
        if (availability.comparison) {
            $("[data-comparison-label]").textContent = availability.comparison.label;
            const delta = availability.comparison.delta_points;
            $("[data-comparison-value]").textContent = `${delta > 0 ? "+" : ""}${delta.toFixed(2)} pts`;
        }
        const quality = payload.data_quality || {};
        $("[data-data-through]").textContent = quality.latest_available_date
            ? `Data through ${formatDate(quality.latest_available_date)}${quality.is_stale ? " - Data may be outdated" : ""}`
            : "Latest available date unavailable";
        $("[data-refresh-status]").textContent = quality.last_refresh_at
            ? `Last refresh: ${quality.last_refresh_at}`
            : "Refresh time unavailable";
        const connection = $("[data-connection-status]");
        connection.classList.remove("is-error");
        connection.classList.add("is-ready");
        $("span", connection).textContent = "Power BI connected";
    }

    function formatDate(value) {
        const date = new Date(`${value}T00:00:00`);
        return Number.isNaN(date.getTime())
            ? value
            : new Intl.DateTimeFormat(document.documentElement.lang || "fr", { day: "2-digit", month: "long", year: "numeric" }).format(date);
    }

    function chartPointLabel(value) {
        return String(value || "").replace(/^\d{4}[- ]?/, "").slice(0, 8);
    }

    function renderTrend(payload) {
        const holder = $("[data-trend-chart]");
        const points = payload.trend || [];
        if (points.length < 2) {
            holder.innerHTML = '<div class="command-empty">Not enough monthly data to display a trend.</div>';
            holder.setAttribute("aria-label", "Availability trend unavailable.");
            $("[data-trend-statistics]").innerHTML = "";
            return;
        }
        const width = 760;
        const height = 250;
        const padding = { left: 42, right: 26, top: 25, bottom: 38 };
        const values = points.map((point) => Number(point.value));
        const target = payload.availability?.target_raw;
        const domainValues = target == null ? values : [...values, Number(target)];
        let min = Math.min(...domainValues);
        let max = Math.max(...domainValues);
        const range = Math.max(.04, max - min);
        min = Math.max(0, min - range * .25);
        max = Math.min(1, max + range * .25);
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const x = (index) => padding.left + (plotWidth * index / Math.max(1, points.length - 1));
        const y = (value) => padding.top + plotHeight * (1 - (value - min) / Math.max(.001, max - min));
        const coordinates = points.map((point, index) => [x(index), y(point.value)]);
        const line = coordinates.map(([px, py], index) => `${index ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
        const area = `${line} L${x(points.length - 1).toFixed(1)},${(padding.top + plotHeight).toFixed(1)} L${padding.left},${(padding.top + plotHeight).toFixed(1)} Z`;
        const grid = [0, .5, 1].map((fraction) => {
            const gy = padding.top + plotHeight * fraction;
            const label = ((max - (max - min) * fraction) * 100).toFixed(0);
            return `<line class="trend-grid-line" x1="${padding.left}" y1="${gy}" x2="${width - padding.right}" y2="${gy}"></line><text class="trend-label" x="4" y="${gy + 4}">${label}%</text>`;
        }).join("");
        const targetLine = target == null ? "" : (() => {
            const targetY = y(target);
            const labelY = targetY <= padding.top + 14 ? targetY + 16 : targetY - 7;
            const targetLabel = `Target ${(Number(target) * 100).toFixed(1)}%`;
            return `<line class="trend-target-line" x1="${padding.left}" y1="${targetY}" x2="${width - padding.right}" y2="${targetY}"></line><text class="trend-target-label" text-anchor="end" x="${width - padding.right - 4}" y="${labelY}">${escapeHtml(targetLabel)}</text>`;
        })();
        const pointNodes = points.map((point, index) => {
            const [px, py] = coordinates[index];
            const showLabel = index === 0 || index === points.length - 1 || points.length <= 8 || index % 2 === 0;
            const valueLabelY = py <= padding.top + 16 ? py + 20 : py - 12;
            const valueLabel = escapeHtml(point.formatted_value || `${(Number(point.value) * 100).toFixed(1)}%`);
            return `${showLabel ? `<text class="trend-label" text-anchor="middle" x="${px}" y="${height - 12}">${escapeHtml(chartPointLabel(point.period))}</text>` : ""}<text class="trend-value-label" text-anchor="middle" x="${px}" y="${valueLabelY}">${valueLabel}</text><circle class="trend-point" tabindex="0" data-trend-index="${index}" cx="${px}" cy="${py}" r="5"></circle>`;
        }).join("");
        holder.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}${targetLine}<path class="trend-area" d="${area}"></path><path class="trend-line" d="${line}"></path>${pointNodes}</svg><div class="trend-tooltip" data-trend-tooltip hidden></div>`;
        holder.setAttribute("aria-label", `Physical Availability trend with ${points.length} monthly values.`);
        const path = $(".trend-line", holder);
        if (path && !reducedMotion.matches) {
            const length = path.getTotalLength();
            path.style.strokeDasharray = String(length);
            path.style.strokeDashoffset = String(length);
            window.requestAnimationFrame(() => {
                path.style.transition = "stroke-dashoffset 700ms ease";
                path.style.strokeDashoffset = "0";
            });
        }
        const tooltip = $("[data-trend-tooltip]", holder);
        $$('[data-trend-index]', holder).forEach((node) => {
            const show = () => {
                const point = points[Number(node.dataset.trendIndex)];
                tooltip.textContent = `${point.period}: ${point.formatted_value}`;
                tooltip.style.left = `${Number(node.getAttribute("cx")) / width * 100}%`;
                tooltip.style.top = `${Number(node.getAttribute("cy")) / height * 100}%`;
                tooltip.hidden = false;
            };
            node.addEventListener("mouseenter", show);
            node.addEventListener("focus", show);
            node.addEventListener("mouseleave", () => { tooltip.hidden = true; });
            node.addEventListener("blur", () => { tooltip.hidden = true; });
        });
        const best = points.reduce((current, point) => point.value > current.value ? point : current);
        const lowest = points.reduce((current, point) => point.value < current.value ? point : current);
        const latest = points[points.length - 1];
        $("[data-trend-statistics]").innerHTML = `
            <div><span>Latest</span><strong>${escapeHtml(latest.formatted_value)}</strong></div>
            <div><span>Best period</span><strong>${escapeHtml(best.period)} - ${escapeHtml(best.formatted_value)}</strong></div>
            <div><span>Lowest period</span><strong>${escapeHtml(lowest.period)} - ${escapeHtml(lowest.formatted_value)}</strong></div>`;
    }

    function numberLabel(value, decimals = 1) {
        const number = Number(value);
        return Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: decimals }) : "--";
    }

    function renderSummary(payload) {
        const summary = payload.summary || {};
        $('[data-summary="minesite_count"]').textContent = numberLabel(summary.minesite_count, 0);
        $('[data-summary="equipment_count"]').textContent = numberLabel(summary.equipment_count, 0);
        $('[data-summary="downtime_hours"]').textContent = summary.downtime_hours == null ? "Not mapped" : numberLabel(summary.downtime_hours);
        const scope = [state.filters.minesite, state.filters.model, state.filters.equipment || state.filters.serial_number].filter(Boolean).join(" / ") || "Overall";
        $('[data-summary="scope"]').textContent = scope;
    }

    function renderFilterOptions(payload) {
        ["minesite", "model", "equipment"].forEach((code) => {
            const select = $(`[data-filter="${code}"]`);
            const current = state.filters[code];
            const allLabels = { minesite: "All MineSites", model: "All models", equipment: "All equipment" };
            const options = new Set(payload.filter_options?.[code] || []);
            if (current) options.add(current);
            select.innerHTML = `<option value="">${allLabels[code]}</option>` + Array.from(options)
                .sort((a, b) => a.localeCompare(b))
                .map((value) => `<option value="${escapeHtml(value)}" title="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
            select.value = current;
            select.title = select.selectedOptions[0]?.textContent || allLabels[code];
        });
    }

    function performanceCard(item, index) {
        const meta = [];
        if (item.customer_type && item.target_formatted) meta.push(`${item.customer_type} - target ${item.target_formatted}`);
        if (item.equipment_count) meta.push(`${numberLabel(item.equipment_count, 0)} equipment`);
        if (item.downtime_hours != null) meta.push(`${numberLabel(item.downtime_hours)} h downtime`);
        return `<button type="button" class="breakdown-card command-enter" style="--enter-index:${index}" data-entity="${escapeHtml(item.entity)}">
            <span class="breakdown-card__head"><strong>${escapeHtml(item.entity)}</strong><small>${escapeHtml(statusLabel(item.status))}</small></span>
            <span class="breakdown-card__value">${escapeHtml(item.formatted_value)}</span>
            <span class="mini-progress"><span style="width:${Math.max(0, Math.min(100, item.availability * 100))}%"></span></span>
            <span class="breakdown-card__meta"><span>${escapeHtml(meta.join(" - ") || "Selected period")}</span><span>${item.gap_points == null ? "" : `${item.gap_points > 0 ? "+" : ""}${item.gap_points.toFixed(2)} pts`}</span></span>
        </button>`;
    }

    function bindBreakdownClicks(holder) {
        $$('[data-entity]', holder).forEach((node) => node.addEventListener("click", () => drillDown(node.dataset.entity)));
    }

    function renderBreakdown(payload) {
        const holder = $("[data-breakdown-content]");
        const items = payload.breakdown || [];
        if (state.breakdown === "overall" || state.breakdown === "equipment") {
            holder.innerHTML = "";
            $("[data-equipment-pagination]").hidden = true;
            return;
        }
        if (!items.length) {
            holder.innerHTML = '<div class="command-empty">No Physical Availability data is available for the selected context.</div>';
            $("[data-equipment-pagination]").hidden = true;
            return;
        }
        holder.innerHTML = `<div class="breakdown-grid">${items.map(performanceCard).join("")}</div>`;
        bindBreakdownClicks(holder);
        $("[data-equipment-pagination]").hidden = true;
    }

    function renderPagination(pagination) {
        const holder = $("[data-equipment-pagination]");
        holder.hidden = Number(pagination.pages || 1) <= 1;
        $("[data-page-summary]", holder).textContent = `Page ${pagination.page || 1} of ${pagination.pages || 1} - ${pagination.count || 0} equipment`;
        $('[data-page-direction="previous"]', holder).disabled = Number(pagination.page || 1) <= 1;
        $('[data-page-direction="next"]', holder).disabled = Number(pagination.page || 1) >= Number(pagination.pages || 1);
    }

    function renderHighlights(payload) {
        const row = (item) => `<div class="highlight-row"><span>${escapeHtml(item.entity)}</span><strong>${escapeHtml(item.formatted_value)}</strong></div>`;
        $("[data-top-performers]").innerHTML = (payload.top_performers || []).map(row).join("") || '<span class="muted-value">No ranking available</span>';
        $("[data-bottom-performers]").innerHTML = (payload.bottom_performers || []).map(row).join("") || '<span class="muted-value">No ranking available</span>';
        $("[data-key-takeaway]").textContent = payload.key_takeaway || "No deterministic insight is available for this context.";
    }

    function render(payload) {
        state.payload = payload;
        state.pageSize = Number(payload.breakdown_pagination?.page_size) || state.pageSize;
        renderHero(payload);
        renderTrend(payload);
        renderSummary(payload);
        renderFilterOptions(payload);
        renderBreakdown(payload);
        renderHighlights(payload);
        syncControls();
    }

    async function loadData() {
        state.controller?.abort();
        state.controller = new AbortController();
        clearError();
        setUpdating(true);
        try {
            const response = await fetch(`${root.dataset.apiUrl}?${apiParams()}`, {
                credentials: "same-origin",
                headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
                signal: state.controller.signal,
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Fleet performance data could not be loaded.");
            render(payload);
        } catch (error) {
            if (error.name !== "AbortError") showError(error.message);
        } finally {
            if (!state.controller?.signal.aborted) setUpdating(false);
            if (!state.controller?.signal.aborted) dismissBrandLoader();
        }
    }

    function changeBreakdown(value) {
        if (!validBreakdowns.has(value) || value === state.breakdown) return;
        state.breakdown = value;
        state.page = 1;
        if (value === "overall" || value === "minesite") {
            state.filters.model = "";
            state.filters.equipment = "";
            state.filters.serial_number = "";
            state.query = "";
        } else if (value === "model") {
            state.filters.equipment = "";
            state.filters.serial_number = "";
            state.query = "";
        }
        syncControls();
        syncUrl();
        track("breakdown_change");
        loadData();
    }

    function drillDown(entity) {
        if (state.breakdown === "overall" || state.breakdown === "minesite") {
            state.filters.minesite = entity;
            state.filters.model = "";
            state.filters.equipment = "";
            state.breakdown = "model";
        } else if (state.breakdown === "model") {
            state.filters.model = entity;
            state.breakdown = "equipment";
        } else {
            state.filters.equipment = entity;
            openAI(`Show the Physical Availability details for equipment ${entity}.`);
            return;
        }
        state.page = 1;
        syncControls();
        syncUrl();
        track("drill_down", { action: entity });
        loadData();
    }

    function contextQuestion(kind = "explain") {
        const context = [
            state.filters.minesite ? `at ${state.filters.minesite}` : "",
            state.filters.model ? `for model ${state.filters.model}` : "",
            state.filters.equipment || state.filters.serial_number ? `for equipment ${state.filters.equipment || state.filters.serial_number}` : "",
        ].filter(Boolean).join(" ");
        const period = state.period === "ytd" ? "year to date" : "over the last 12 months";
        if (kind === "downtime") return `Show the top downtime drivers affecting Physical Availability ${context} ${period}.`.replace(/\s+/g, " ");
        return `Explain the Physical Availability performance ${context} ${period}.`.replace(/\s+/g, " ");
    }

    function openAI(question) {
        const url = new URL(root.dataset.aiUrl, window.location.origin);
        url.searchParams.set("draft", question);
        url.searchParams.set("metric", "availability");
        url.searchParams.set("period", state.period);
        url.searchParams.set("breakdown", state.breakdown);
        Object.entries(state.filters).forEach(([key, value]) => { if (value) url.searchParams.set(key, value); });
        window.location.href = url;
    }

    function resetFilters() {
        Object.keys(state.filters).forEach((key) => { state.filters[key] = ""; });
        state.query = "";
        state.page = 1;
        syncControls();
        syncUrl();
        track("filter_change", { action: "reset" });
        loadData();
    }

    $$('[data-period]').forEach((button) => button.addEventListener("click", () => {
        if (button.dataset.period === state.period) return;
        state.period = button.dataset.period;
        state.page = 1;
        syncControls();
        syncUrl();
        track("period_change");
        loadData();
    }));
    $$('[data-breakdown]').forEach((button) => button.addEventListener("click", () => changeBreakdown(button.dataset.breakdown)));
    $$('[data-filter="minesite"], [data-filter="model"], [data-filter="equipment"]').forEach((select) => select.addEventListener("change", () => {
        select.title = select.selectedOptions[0]?.textContent || "";
        state.filters[select.dataset.filter] = select.value;
        if (select.dataset.filter === "minesite") {
            state.filters.model = "";
            state.filters.equipment = "";
            state.filters.serial_number = "";
        } else if (select.dataset.filter === "model") {
            state.filters.equipment = "";
            state.filters.serial_number = "";
        } else if (select.dataset.filter === "equipment") {
            state.filters.serial_number = "";
        }
        state.page = 1;
        syncControls();
        syncUrl();
        track("filter_change");
        loadData();
    }));
    $("[data-ordering]").addEventListener("change", (event) => {
        state.ordering = event.target.value;
        state.page = 1;
        syncUrl();
        loadData();
    });
    $("[data-reset-filters]").addEventListener("click", resetFilters);
    $("[data-retry]").addEventListener("click", loadData);
    $$('[data-page-direction]').forEach((button) => button.addEventListener("click", () => {
        state.page += button.dataset.pageDirection === "next" ? 1 : -1;
        state.page = Math.max(1, state.page);
        syncUrl();
        loadData();
    }));
    $$('[data-action="ask-ai"]').forEach((button) => button.addEventListener("click", () => {
        track("ask_ai");
        openAI(contextQuestion());
    }));
    $('[data-action="view-downtime"]').addEventListener("click", () => {
        track("open_downtime");
        openAI(contextQuestion("downtime"));
    });
    $('[data-action="open-report"]').addEventListener("click", () => {
        track("open_report");
        window.location.href = root.dataset.reportUrl;
    });
    window.addEventListener("popstate", () => window.location.reload());

    syncControls();
    root.setAttribute("aria-busy", "true");
    syncUrl(true);
    track("page_view");
    loadData();
})();
