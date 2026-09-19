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
    const validMetrics = new Set(["availability", "mtbs", "mtbf", "mttr", "fuel"]);
    const validPeriods = new Set(["ytd", "last_12_months"]);
    const validBreakdowns = new Set(["overall", "minesite", "model", "equipment"]);
    const params = new URLSearchParams(window.location.search);
    const state = {
        metric: validMetrics.has(params.get("metric")) ? params.get("metric") : "availability",
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
    const fuelSiteAliases = {
        "Essakane": "IAMGOLD Essakane",
        "Fekola": "B2Gold Fekola",
        "Sangaredi/CBG": "CBG Sangaredi",
        "Siguiri": "AngloGold Ashanti Siguiri",
    };
    const fleetSiteAliases = Object.fromEntries(
        Object.entries(fuelSiteAliases).map(([fleet, fuel]) => [fuel, fleet]),
    );

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
            metric: state.metric,
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
        ["metric", "period", "breakdown", "ordering", "page", "minesite", "model", "equipment", "serial_number", "customer", "q"]
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
            metric: state.metric,
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
        $("[data-metric-selector]").value = state.metric;
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
        const trendExportContext = [
            metricConfig().label,
            state.period === "ytd" ? "Year to Date" : "Last 12 Months",
            state.filters.minesite ? `MineSite: ${state.filters.minesite}` : "All MineSites",
            state.filters.model ? `Model: ${state.filters.model}` : "",
            state.filters.equipment ? `Equipment: ${state.filters.equipment}` : "",
        ].filter(Boolean).join(" · ");
        const availabilityExportContext = [
            metricConfig().label,
            state.filters.minesite ? `MineSite: ${state.filters.minesite}` : "All MineSites",
            state.filters.model ? `Model: ${state.filters.model}` : "",
            state.filters.equipment ? `Equipment: ${state.filters.equipment}` : "",
        ].filter(Boolean).join(" · ");
        const trendContext = $("[data-trend-export-context]");
        const availabilityContext = $("[data-availability-export-context]");
        if (trendContext) trendContext.textContent = trendExportContext;
        if (availabilityContext) availabilityContext.textContent = availabilityExportContext;
        const metricName = state.metric === "availability" ? "Availability" : state.metric === "fuel" ? "Fuel" : state.metric.toUpperCase();
        $("[data-ordering]").value = state.ordering;
        const orderSelect = $("[data-ordering]");
        orderSelect.options[0].textContent = state.metric === "availability" ? "Best performing" : `Highest ${metricName}`;
        orderSelect.options[1].textContent = state.metric === "availability" ? "Lowest performing" : `Lowest ${metricName}`;
        $("[data-order-field]").hidden = state.breakdown === "overall";
        $("[data-breakdown-section]").hidden = state.breakdown === "overall" || state.breakdown === "equipment";
        $("[data-period-label]").textContent = state.period === "ytd" ? "Year to Date" : "Last 12 Months";
        const titles = {
            overall: "Overall fleet performance",
            minesite: `${metricName} by Mine Site`,
            model: `${metricName} by Model`,
            equipment: "Equipment analysis",
        };
        $("[data-breakdown-title]").textContent = titles[state.breakdown];
        renderBreadcrumb();
        syncMetricWorkspace();
    }

    function syncMetricWorkspace() {
        const fuelMode = state.metric === "fuel";
        root.classList.toggle("fuel-mode", fuelMode);
        $("[data-fuel-workspace]").hidden = !fuelMode;
        $$('[data-fleet-workspace]').forEach((section) => {
            if (fuelMode) section.hidden = true;
            else if (!section.matches("[data-breakdown-section]")) section.hidden = false;
        });
        const highlights = $(".performance-highlights");
        if (highlights) highlights.hidden = false;
        if (!fuelMode) {
            $("[data-breakdown-section]").hidden = state.breakdown === "overall" || state.breakdown === "equipment";
        }
        const downtimeAction = $('[data-action="view-downtime"]');
        const reportAction = $('[data-action="open-report"]');
        if (downtimeAction) downtimeAction.hidden = fuelMode;
        if (reportAction) reportAction.textContent = fuelMode ? "Open Reporting Hub" : "Open Fleet Performance Report";
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
        [
            ["availability-trend", "[data-copy-availability-trend]"],
            ["physical-availability", "[data-copy-physical-availability]"],
        ].forEach(([visual, buttonSelector]) => {
            const panel = $(`[data-export-visual='${visual}']`);
            const button = $(buttonSelector);
            if (panel && button) button.disabled = active || panel.dataset.exportReady !== "true";
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

    function metricConfig() {
        if (state.metric === "mtbs") {
            return {
                code: "mtbs",
                label: "MTBS",
                centerTitle: "Fleet MTBS Excellence Center",
                subtitle: "Immediate, intelligent insight into time between stoppages.",
                trendTitle: "MTBS Trend",
                format: (value) => `${Number(value).toFixed(2)} h`,
            };
        }
        if (state.metric === "mtbf") {
            return {
                code: "mtbf",
                label: "MTBF",
                centerTitle: "Fleet MTBF Excellence Center",
                subtitle: "Immediate, intelligent insight into time between failures.",
                trendTitle: "MTBF Trend",
                format: (value) => `${Number(value).toFixed(2)} h`,
            };
        }
        if (state.metric === "mttr") {
            return {
                code: "mttr",
                label: "MTTR",
                centerTitle: "Fleet MTTR Excellence Center",
                subtitle: "Immediate, intelligent insight into time to repair.",
                trendTitle: "MTTR Trend",
                format: (value) => `${Number(value).toFixed(2)} h`,
            };
        }
        if (state.metric === "fuel") {
            return {
                code: "fuel",
                label: "Average Fuel Rate",
                centerTitle: "Fleet Fuel Consumption Excellence Center",
                subtitle: "Immediate insight into fleet fuel efficiency and consumption distribution.",
                trendTitle: "Fuel Consumption Distribution",
                format: (value) => `${Number(value).toFixed(1)} L/h`,
            };
        }
        return {
            code: "availability",
            label: "Physical Availability",
            centerTitle: "Fleet Availability Excellence Center",
            subtitle: "Immediate, intelligent insight into fleet availability.",
            trendTitle: "Availability Trend",
            format: (value) => `${(Number(value) * 100).toFixed(2)}%`,
        };
    }

    function animateValue(target, onComplete) {
        const holder = $("[data-availability-value]");
        if (target == null) {
            holder.textContent = "--";
            state.renderedValue = null;
            onComplete?.();
            return;
        }
        const from = state.renderedValue == null ? 0 : state.renderedValue;
        const duration = reducedMotion.matches ? 0 : (state.renderedValue == null ? 850 : 360);
        const started = performance.now();
        const draw = (now) => {
            const progress = duration ? Math.min(1, (now - started) / duration) : 1;
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = from + (target - from) * eased;
            holder.textContent = metricConfig().format(current);
            if (progress < 1) window.requestAnimationFrame(draw);
            else {
                state.renderedValue = target;
                onComplete?.();
            }
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
        const metric = payload.metric || payload.availability || {};
        const config = metricConfig();
        const value = metric.raw_value;
        root.classList.toggle("metric-mode-hours", state.metric !== "availability");
        $("[data-center-title]").textContent = config.centerTitle;
        $("[data-center-subtitle]").textContent = config.subtitle;
        $("[data-hero-title]").textContent = config.label;
        $("[data-hero-metric-label]").textContent = config.label;
        $("[data-trend-title]").textContent = config.trendTitle;
        $("[data-highlights-title]").textContent = `${config.label} Highlights`;
        $("[data-top-title]").textContent = state.metric === "availability"
            ? "Top performers"
            : state.metric === "mttr" ? "Lowest MTTR" : `Highest ${config.label}`;
        $("[data-bottom-title]").textContent = state.metric === "availability"
            ? "Requires attention"
            : state.metric === "mttr" ? "Highest MTTR" : `Lowest ${config.label}`;
        $("[data-copy-physical-availability]").setAttribute("aria-label", `Copy ${config.label} KPI to clipboard`);
        $("[data-copy-availability-trend]").setAttribute("aria-label", `Copy ${config.label} trend to clipboard`);
        const availabilityPanel = $("[data-export-visual='physical-availability']");
        const availabilityCopy = $("[data-copy-physical-availability]");
        availabilityPanel.dataset.exportReady = "false";
        availabilityCopy.disabled = true;
        animateValue(value, () => {
            availabilityPanel.dataset.exportReady = "true";
            availabilityCopy.disabled = false;
        });
        const ring = $("[data-ring]");
        ring.dataset.quality = metric.quality_status || "valid";
        if (metric.quality_status === "out_of_range") {
            $("[data-availability-value]").textContent = "Invalid data";
        }
        const angle = state.metric === "availability" && value != null
            ? Math.max(0, Math.min(360, value * 360))
            : 0;
        ring.style.setProperty("--ring-progress", `${angle}deg`);
        ring.setAttribute("aria-label", value == null
            ? `${config.label} unavailable.`
            : `${config.label}: ${config.format(value)}.`);
        const status = $("[data-availability-status]");
        status.hidden = !metric.status;
        status.dataset.status = metric.status || "";
        status.textContent = statusLabel(metric.status);
        const target = $("[data-target-summary]");
        target.hidden = metric.target_raw == null;
        $("[data-target-value]").textContent = metric.target_formatted || "--";
        const comparison = $("[data-comparison-summary]");
        comparison.hidden = !metric.comparison;
        if (metric.comparison) {
            $("[data-comparison-label]").textContent = metric.comparison.label;
            $("[data-comparison-value]").textContent = metric.comparison.delta_formatted
                || `${metric.comparison.delta_points > 0 ? "+" : ""}${metric.comparison.delta_points.toFixed(2)} pts`;
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
            : new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "long", year: "numeric" }).format(date);
    }

    function chartPointLabel(value) {
        return String(value || "").replace(/^\d{4}[- ]?/, "").slice(0, 8);
    }

    function renderTrend(payload) {
        const holder = $("[data-trend-chart]");
        const points = payload.trend || [];
        const config = metricConfig();
        if (points.length < 2) {
            holder.innerHTML = '<div class="command-empty">Not enough monthly data to display a trend.</div>';
            holder.setAttribute("aria-label", `${config.label} trend unavailable.`);
            $("[data-trend-statistics]").innerHTML = "";
            $("[data-export-visual='availability-trend']").dataset.exportReady = "false";
            return;
        }
        const width = 760;
        const height = 250;
        const padding = { left: 42, right: 26, top: 25, bottom: 38 };
        const values = points.map((point) => Number(point.value));
        const target = payload.metric?.target_raw;
        const domainValues = target == null ? values : [...values, Number(target)];
        let min = Math.min(...domainValues);
        let max = Math.max(...domainValues);
        const minimumRange = state.metric !== "availability" ? Math.max(1, max * .08) : .04;
        const range = Math.max(minimumRange, max - min);
        min = Math.max(0, min - range * .25);
        max = state.metric !== "availability" ? max + range * .25 : Math.min(1, max + range * .25);
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const x = (index) => padding.left + (plotWidth * index / Math.max(1, points.length - 1));
        const y = (value) => padding.top + plotHeight * (1 - (value - min) / Math.max(.001, max - min));
        const coordinates = points.map((point, index) => [x(index), y(point.value)]);
        const line = coordinates.map(([px, py], index) => `${index ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
        const area = `${line} L${x(points.length - 1).toFixed(1)},${(padding.top + plotHeight).toFixed(1)} L${padding.left},${(padding.top + plotHeight).toFixed(1)} Z`;
        const grid = [0, .5, 1].map((fraction) => {
            const gy = padding.top + plotHeight * fraction;
            const gridValue = max - (max - min) * fraction;
            const label = state.metric !== "availability" ? `${gridValue.toFixed(0)}h` : `${(gridValue * 100).toFixed(0)}%`;
            return `<line class="trend-grid-line" x1="${padding.left}" y1="${gy}" x2="${width - padding.right}" y2="${gy}"></line><text class="trend-label" x="4" y="${gy + 4}">${label}</text>`;
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
            const previousY = coordinates[index - 1]?.[1];
            const nextY = coordinates[index + 1]?.[1];
            const closeToNeighbor = [previousY, nextY].some((neighborY) => (
                Number.isFinite(neighborY) && Math.abs(py - neighborY) < 20
            ));
            const closeToTarget = target != null && Math.abs(py - y(target)) < 18;
            const placeBelow = (closeToNeighbor || closeToTarget) && index % 2 === 1;
            const rawLabelY = placeBelow ? py + 22 : py - 12;
            const valueLabelY = Math.max(padding.top + 11, Math.min(padding.top + plotHeight - 8, rawLabelY));
            const valueLabel = escapeHtml(point.formatted_value || `${(Number(point.value) * 100).toFixed(1)}%`);
            return `${showLabel ? `<text class="trend-label" text-anchor="middle" x="${px}" y="${height - 12}">${escapeHtml(chartPointLabel(point.period))}</text>` : ""}<text class="trend-value-label" text-anchor="middle" x="${px}" y="${valueLabelY}">${valueLabel}</text><circle class="trend-point" tabindex="0" data-trend-index="${index}" cx="${px}" cy="${py}" r="5"></circle>`;
        }).join("");
        holder.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}${targetLine}<path class="trend-area" d="${area}"></path><path class="trend-line" d="${line}"></path>${pointNodes}</svg><div class="trend-tooltip" data-trend-tooltip data-export-ignore="true" hidden></div>`;
        holder.setAttribute("aria-label", `${config.label} trend with ${points.length} monthly values.`);
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
        const highest = points.reduce((current, point) => point.value > current.value ? point : current);
        const lowest = points.reduce((current, point) => point.value < current.value ? point : current);
        const best = state.metric === "mttr" ? lowest : highest;
        const worst = state.metric === "mttr" ? highest : lowest;
        const latest = points[points.length - 1];
        $("[data-trend-statistics]").innerHTML = `
            <div><span>Latest</span><strong>${escapeHtml(latest.formatted_value)}</strong></div>
            <div><span>Best period</span><strong>${escapeHtml(best.period)} - ${escapeHtml(best.formatted_value)}</strong></div>
            <div><span>${state.metric === "mttr" ? "Highest period" : "Lowest period"}</span><strong>${escapeHtml(worst.period)} - ${escapeHtml(worst.formatted_value)}</strong></div>`;
        const trendPanel = $("[data-export-visual='availability-trend']");
        trendPanel.dataset.exportReady = "true";
        $("[data-copy-availability-trend]").disabled = false;
    }

    function setupAvailabilityTrendExport() {
        const exporter = window.Mining360VisualExport;
        const target = $("[data-export-visual='availability-trend']");
        const button = $("[data-copy-availability-trend]");
        if (!exporter || !target || !button) return;
        const language = "en";

        button.setAttribute("aria-label", button.dataset.labelEn);
        button.title = "Copy chart";
        exporter.bindCopyAction({
            button,
            target,
            language,
            scale: 2,
            background: "#ffffff",
            fileName: "Mining360_Fleet_Performance_Trend",
            prepareClone: (clone) => {
                const context = clone.querySelector("[data-export-context]");
                if (context) {
                    context.hidden = false;
                    context.style.cssText = "display:block;margin:5px 0 0;color:#667085;font:600 11px Arial,sans-serif;letter-spacing:0;";
                }
                const line = clone.querySelector(".trend-line");
                if (line) {
                    line.style.strokeDasharray = "none";
                    line.style.strokeDashoffset = "0";
                    line.style.transition = "none";
                }
            },
            onSuccess: () => track("chart_copy", { visual: "availability_trend" }),
            onFallback: () => track("chart_download", { visual: "availability_trend" }),
        });
    }

    function setupPhysicalAvailabilityExport() {
        const exporter = window.Mining360VisualExport;
        const target = $("[data-export-visual='physical-availability']");
        const button = $("[data-copy-physical-availability]");
        if (!exporter || !target || !button) return;
        const language = "en";

        button.setAttribute("aria-label", button.dataset.labelEn);
        button.title = "Copy chart";
        exporter.bindCopyAction({
            button,
            target,
            language,
            scale: 2,
            background: "#fffdf6",
            fileName: "Mining360_Fleet_Performance_KPI",
            prepareClone: (clone) => {
                const context = clone.querySelector("[data-availability-export-context]");
                if (context) {
                    context.hidden = false;
                    context.style.cssText = "display:block;margin:5px 0 0;color:#667085;font:600 11px Arial,sans-serif;letter-spacing:0;";
                }
                const ring = clone.querySelector("[data-ring]");
                if (ring) {
                    const center = document.createElement("span");
                    center.setAttribute("aria-hidden", "true");
                    center.style.cssText = "position:absolute;inset:14px;border-radius:50%;background:#fff;box-shadow:inset 0 0 0 1px #edf0f3;";
                    ring.prepend(center);
                }
            },
            onSuccess: () => track("chart_copy", { visual: "physical_availability" }),
            onFallback: () => track("chart_download", { visual: "physical_availability" }),
        });
    }

    function numberLabel(value, decimals = 1) {
        const number = Number(value);
        return Number.isFinite(number) ? number.toLocaleString("en-GB", { maximumFractionDigits: decimals }) : "--";
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

    function performanceCard(item, index, maximumValue) {
        const meta = [];
        if (item.customer_type && item.target_formatted) meta.push(`${item.customer_type} - target ${item.target_formatted}`);
        if (item.equipment_count) meta.push(`${numberLabel(item.equipment_count, 0)} equipment`);
        if (item.downtime_hours != null) meta.push(`${numberLabel(item.downtime_hours)} h downtime`);
        const progress = state.metric !== "availability"
            ? (maximumValue > 0 ? item.metric_value / maximumValue * 100 : 0)
            : item.metric_value * 100;
        return `<button type="button" class="breakdown-card command-enter" style="--enter-index:${index}" data-entity="${escapeHtml(item.entity)}">
            <span class="breakdown-card__head"><strong>${escapeHtml(item.entity)}</strong><small>${escapeHtml(statusLabel(item.status))}</small></span>
            <span class="breakdown-card__value">${escapeHtml(item.formatted_value)}</span>
            <span class="mini-progress"><span style="width:${Math.max(0, Math.min(100, progress))}%"></span></span>
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
            holder.innerHTML = `<div class="command-empty">No ${escapeHtml(metricConfig().label)} data is available for the selected context.</div>`;
            $("[data-equipment-pagination]").hidden = true;
            return;
        }
        const maximumValue = Math.max(...items.map((item) => Number(item.metric_value) || 0));
        holder.innerHTML = `<div class="breakdown-grid">${items.map((item, index) => performanceCard(item, index, maximumValue)).join("")}</div>`;
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

    function fuelValue(value) {
        if (value === null || value === undefined || value === "") return "--";
        const number = Number(value);
        return Number.isFinite(number) ? `${number.toFixed(1)} L/h` : "--";
    }

    function smoothFuelPath(points) {
        if (!points.length) return "";
        let path = `M${points[0][0]},${points[0][1]}`;
        for (let index = 1; index < points.length; index += 1) {
            const previous = points[index - 1];
            const current = points[index];
            const middle = (previous[0] + current[0]) / 2;
            path += ` C${middle},${previous[1]} ${middle},${current[1]} ${current[0]},${current[1]}`;
        }
        return path;
    }

    function fuelDensityCurve(equipment, maximumX) {
        const values = (equipment || [])
            .map((item) => Number(item.lph))
            .filter((value) => Number.isFinite(value) && value >= 0);
        if (values.length < 2) return [];
        const mean = values.reduce((total, value) => total + value, 0) / values.length;
        const variance = values.reduce((total, value) => total + (value - mean) ** 2, 0) / values.length;
        const deviation = Math.sqrt(variance);
        const bandwidth = Math.max(18, Math.min(36, 1.5 * 1.06 * (deviation || 10) * values.length ** -0.2));
        const denominator = values.length * bandwidth * Math.sqrt(2 * Math.PI);
        const step = Math.max(2, maximumX / 90);
        const curve = [];
        for (let lph = 0; lph <= maximumX + step / 2; lph += step) {
            const kernel = values.reduce(
                (total, value) => total + Math.exp(-0.5 * ((lph - value) / bandwidth) ** 2),
                0,
            );
            curve.push({
                lph: Math.min(lph, maximumX),
                percentage: kernel / denominator * 20 * 100,
            });
        }
        return curve;
    }

    function renderFuel(payload) {
        const metric = payload.metric || {};
        const hasValue = metric.raw_value !== null && metric.raw_value !== undefined && metric.raw_value !== "";
        const value = hasValue ? Number(metric.raw_value) : Number.NaN;
        const validValue = Number.isFinite(value);
        $("[data-center-title]").textContent = "Fleet Fuel Consumption Excellence Center";
        $("[data-center-subtitle]").textContent = "Immediate insight into fleet fuel efficiency and consumption distribution.";
        $("[data-fuel-period]").textContent = payload.context?.period_label || "Year to Date";
        $("[data-fuel-value]").textContent = validValue ? value.toFixed(1) : "--";
        const gauge = $("[data-fuel-gauge]");
        const gaugeDegrees = validValue ? Math.max(0, Math.min(360, value / 160 * 360)) : 0;
        gauge.style.setProperty("--fuel-progress", `${gaugeDegrees}deg`);
        gauge.setAttribute("aria-label", validValue ? `Average Fuel Rate: ${value.toFixed(1)} litres per hour.` : "Average Fuel Rate unavailable.");

        const comparison = metric.comparison;
        const deltaHolder = $("[data-fuel-comparison]");
        deltaHolder.classList.remove("is-improving", "is-worsening");
        if (comparison?.delta_value != null) {
            deltaHolder.classList.add(Number(comparison.delta_value) < 0 ? "is-improving" : "is-worsening");
            $("[data-fuel-delta]").textContent = comparison.delta_formatted;
            $("[data-fuel-delta-percent]").textContent = comparison.delta_percent == null
                ? ""
                : `(${comparison.delta_percent > 0 ? "+" : ""}${comparison.delta_percent.toFixed(1)}%)`;
        } else {
            $("[data-fuel-delta]").textContent = "Not available";
            $("[data-fuel-delta-percent]").textContent = "";
        }
        $("[data-fuel-benchmark]").textContent = metric.benchmark_formatted || "Not available";
        $("[data-fuel-scope]").textContent = state.filters.minesite || "All MineSites";

        const points = payload.distribution || [];
        const density = fuelDensityCurve(payload.equipment, Math.max(180, ...points.map(item => Number(item.lph) || 0)));
        const chart = $("[data-fuel-chart]");
        const width = 960, height = 330;
        const padding = {left: 54, right: 20, top: 28, bottom: 46};
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const maximumX = Math.max(160, ...points.map(item => Number(item.lph) || 0));
        const maximumY = Math.max(
            5,
            ...points.map(item => Number(item.percentage) || 0),
            ...density.map(item => Number(item.percentage) || 0),
        ) * 1.18;
        const x = (number) => padding.left + Number(number) / maximumX * plotWidth;
        const y = (number) => padding.top + (1 - Number(number) / maximumY) * plotHeight;
        const coordinates = points.map(item => [x(item.lph), y(item.percentage)]);
        const densityCoordinates = density.map(item => [x(item.lph), y(item.percentage)]);
        const curveCoordinates = densityCoordinates.length ? densityCoordinates : coordinates;
        const line = densityCoordinates.length
            ? densityCoordinates.map((point, index) => `${index ? "L" : "M"}${point[0]},${point[1]}`).join(" ")
            : smoothFuelPath(coordinates);
        const area = curveCoordinates.length
            ? `${line} L${curveCoordinates.at(-1)[0]},${padding.top + plotHeight} L${curveCoordinates[0][0]},${padding.top + plotHeight} Z`
            : "";
        const grid = [0, .25, .5, .75, 1].map(fraction => {
            const gy = padding.top + plotHeight * (1 - fraction);
            return `<line class="fuel-grid" x1="${padding.left}" y1="${gy}" x2="${width - padding.right}" y2="${gy}"></line><text class="fuel-axis-label" x="4" y="${gy + 4}">${(maximumY * fraction).toFixed(0)}%</text>`;
        }).join("");
        const xLabels = points.map(item => `<text class="fuel-axis-label" text-anchor="middle" x="${x(item.lph)}" y="${height - 12}">${item.lph}</text>`).join("");
        const nodes = points.map((item, index) => {
            const nearest = density.reduce((current, candidate) => (
                Math.abs(candidate.lph - item.lph) < Math.abs(current.lph - item.lph) ? candidate : current
            ), density[0] || item);
            const smoothedPercentage = Number(nearest.percentage ?? item.percentage);
            const [px] = coordinates[index];
            const py = y(smoothedPercentage);
            const offset = index % 2 === 0 ? 12 : 26;
            const labelY = Math.max(padding.top + 10, Math.min(padding.top + plotHeight - 8, py - offset));
            return `<text class="fuel-point-label" text-anchor="middle" x="${px}" y="${labelY}">${smoothedPercentage.toFixed(1)}%</text><circle class="fuel-point" cx="${px}" cy="${py}" r="6"><title>Smoothed share: ${smoothedPercentage.toFixed(1)}% · Exact 20 L/h band: ${Number(item.percentage).toFixed(1)}% (${item.count} equipment)</title></circle>`;
        }).join("");
        const averageMarker = validValue
            ? `<line class="fuel-average-line" x1="${x(value)}" y1="${padding.top}" x2="${x(value)}" y2="${padding.top + plotHeight}"></line><text class="fuel-average-label" text-anchor="middle" x="${x(value)}" y="${height - 27}">${value.toFixed(1)} L/h</text>`
            : "";
        chart.innerHTML = points.length
            ? `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}<path class="fuel-area" d="${area}"></path><path class="fuel-line" d="${line}"></path>${nodes}${averageMarker}${xLabels}<text class="fuel-axis-title" text-anchor="middle" x="${padding.left + plotWidth / 2}" y="${height}">Average Fuel Rate (L/h)</text></svg>`
            : '<div class="command-empty">No Fuel consumption data is available for the selected context.</div>';
        chart.setAttribute("aria-label", points.length ? `Fuel distribution across ${payload.summary?.equipment_count || 0} equipment.` : "Fuel distribution unavailable.");

        const statistics = payload.statistics || {};
        [statistics.lowest, statistics.p25, statistics.median, statistics.p75, statistics.highest].forEach((number, index) => {
            $("strong", $$('[data-fuel-statistics] > div')[index]).textContent = fuelValue(number);
        });
        const quality = payload.data_quality || {};
        $("[data-refresh-status]").textContent = quality.last_refresh_at ? `Last refresh: ${quality.last_refresh_at}` : "Refresh time unavailable";
        const connection = $("[data-connection-status]");
        connection.classList.remove("is-error");
        connection.classList.add("is-ready");
        $("span", connection).textContent = "Fuel Monitoring connected";
        $("[data-fuel-workspace]").dataset.exportReady = points.length ? "true" : "false";
        renderFuelDecisionSupport(payload);
    }

    function renderFuelDecisionSupport(payload) {
        const ranked = (payload.equipment || [])
            .filter((item) => Number(item.lph) > 0)
            .sort((left, right) => Number(left.lph) - Number(right.lph));
        const fallbackItem = (item) => ({
            entity: item.equipment || "Unidentified equipment",
            model: item.model || null,
            minesite: item.minesite || null,
            formatted_value: fuelValue(item.lph),
        });
        const veryHighCount = ranked.filter((item) => Number(item.lph) > 120).length;
        const lowCount = ranked.filter((item) => Number(item.lph) < 40).length;
        const fallback = {
            lowest_observed: ranked.slice(0, 5).map(fallbackItem),
            highest_observed: ranked.slice(-5).reverse().map(fallbackItem),
            takeaway: ranked.length
                ? (veryHighCount
                    ? `${veryHighCount} equipment record an average Fuel rate above 120 L/h. Review model, duty cycle and operating conditions before drawing an efficiency conclusion.`
                    : `No equipment records an average Fuel rate above 120 L/h; ${lowCount} are below 40 L/h. Compare equipment within the same model and duty cycle before taking action.`)
                : "No equipment-level Fuel rate is available for decision support in this context.",
        };
        const support = payload.decision_support || fallback;
        const row = (item) => {
            const context = [item.model, item.minesite].filter(Boolean).join(" · ");
            return `<div class="highlight-row fuel-highlight-row"><span><strong>${escapeHtml(item.entity)}</strong>${context ? `<small>${escapeHtml(context)}</small>` : ""}</span><strong>${escapeHtml(item.formatted_value || "--")}</strong></div>`;
        };
        $("[data-highlights-title]").textContent = "Fuel Consumption Highlights";
        $("[data-top-title]").textContent = "Lowest observed fuel rates";
        $("[data-bottom-title]").textContent = "Highest observed fuel rates";
        $("[data-top-performers]").innerHTML = (support.lowest_observed || []).map(row).join("")
            || '<span class="muted-value">No equipment-level Fuel data available</span>';
        $("[data-bottom-performers]").innerHTML = (support.highest_observed || []).map(row).join("")
            || '<span class="muted-value">No equipment-level Fuel data available</span>';
        $("[data-key-takeaway]").textContent = support.takeaway
            || "No deterministic Fuel insight is available for this context.";
    }

    function render(payload) {
        state.payload = payload;
        state.pageSize = Number(payload.breakdown_pagination?.page_size) || state.pageSize;
        if (state.metric === "fuel") {
            const canonicalFilters = payload.context?.filters || {};
            state.filters.minesite = canonicalFilters.minesite || state.filters.minesite;
            state.filters.model = canonicalFilters.model || state.filters.model;
            state.filters.equipment = canonicalFilters.equipment || state.filters.equipment;
            renderFuel(payload);
            renderFilterOptions(payload);
            syncControls();
            return;
        }
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
            openAI(`Show the ${metricConfig().label} details for equipment ${entity}.`);
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
        if (kind === "downtime") return `Show the top downtime drivers affecting ${metricConfig().label} ${context} ${period}.`.replace(/\s+/g, " ");
        return `Explain the ${metricConfig().label} performance ${context} ${period}.`.replace(/\s+/g, " ");
    }

    function openAI(question) {
        const url = new URL(root.dataset.aiUrl, window.location.origin);
        url.searchParams.set("draft", question);
        url.searchParams.set("metric", state.metric);
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

    $("[data-metric-selector]").addEventListener("change", (event) => {
        const metric = event.target.value;
        if (!validMetrics.has(metric) || metric === state.metric) return;
        const previousMetric = state.metric;
        state.metric = metric;
        if (metric === "fuel" && state.filters.minesite) {
            state.filters.minesite = fuelSiteAliases[state.filters.minesite] || state.filters.minesite;
        } else if (previousMetric === "fuel" && state.filters.minesite) {
            state.filters.minesite = fleetSiteAliases[state.filters.minesite] || state.filters.minesite;
        }
        if (metric === "fuel") state.breakdown = "overall";
        state.renderedValue = null;
        state.page = 1;
        syncControls();
        syncUrl();
        track("metric_change");
        loadData();
    });

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
    setupPhysicalAvailabilityExport();
    setupAvailabilityTrendExport();
    root.setAttribute("aria-busy", "true");
    syncUrl(true);
    track("page_view");
    loadData();
})();
