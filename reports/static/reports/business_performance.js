(function () {
    "use strict";
    const root = document.querySelector("[data-bp-root]");
    if (!root) return;
    window.MINING360_BP_READY = true;

    const state = { payload: null, filters: {}, search: "", page: 1, pageSize: 50 };
    const page = root.dataset.page;
    const customer = root.dataset.customer;
    const loading = root.querySelector("[data-bp-state]");
    const error = root.querySelector("[data-bp-error]");
    const content = root.querySelector("[data-bp-content]");
    const overviewSection = root.querySelector("[data-overview-only]");
    const detailSection = root.querySelector("[data-detail-only]");

    function formatValue(value, key) {
        if (value === null || value === undefined || value === "") return "—";
        const number = Number(value);
        if (!Number.isFinite(number)) return String(value);
        const lower = String(key || "").toLowerCase();
        if (lower.includes("%") || lower.includes("share") || lower.includes("contribution")) {
            const pct = Math.abs(number) <= 1 ? number * 100 : number;
            return `${pct.toLocaleString("en-GB", { maximumFractionDigits: 1 })}%`;
        }
        if (lower.includes("revenue") || lower.includes(" ca") || lower.startsWith("ca ")) {
            return new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", notation: "compact", maximumFractionDigits: 1 }).format(number);
        }
        return number.toLocaleString("en-GB", { maximumFractionDigits: 2 });
    }

    function queryString(extra) {
        const params = new URLSearchParams();
        Object.entries(state.filters).forEach(([key, values]) => values.forEach(value => params.append(key, value)));
        Object.entries(extra || {}).forEach(([key, value]) => value !== "" && params.set(key, value));
        return params.toString();
    }

    function endpoint() {
        if (customer) return `customer/?${queryString({ customer })}`;
        return `${page}/?${queryString({ top_n: root.querySelector("[data-top-n]")?.value || "" })}`;
    }

    async function load() {
        loading.hidden = false;
        error.hidden = true;
        content.hidden = true;
        try {
            const response = await fetch(root.dataset.apiBase + endpoint(), { headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" } });
            const data = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
            if (!response.ok || !data.ok) throw Object.assign(new Error(data.error || "Unable to load data."), { code: data.code });
            state.payload = data;
            render(data);
            content.hidden = false;
        } catch (exc) {
            root.querySelector("[data-error-title]").textContent = exc.code === "mapping_missing" ? "Measure or field not configured" : "Semantic Model Unavailable";
            root.querySelector("[data-error-message]").textContent = exc.message;
            error.hidden = false;
        } finally {
            loading.hidden = true;
        }
    }

    function render(data) {
        if (customer) {
            renderOverview(data.summary || {});
            const allRows = [...(data.parts || []), ...(data.prime || [])];
            renderTable("details", allRows);
            overviewSection.hidden = false;
            detailSection.hidden = false;
            return;
        }
        if (page === "overview") {
            renderOverview(data);
            overviewSection.hidden = false;
            detailSection.hidden = true;
        } else if (page === "customers") {
            renderKpis({});
            renderTable("details", data.customers || []);
            overviewSection.hidden = true;
            detailSection.hidden = false;
        } else {
            renderKpis(deriveKpis(data.rows || []));
            renderTable("details", data.rows || []);
            overviewSection.hidden = true;
            detailSection.hidden = false;
        }
    }

    function renderOverview(data) {
        renderKpis(data.kpis || {});
        renderTable("customers", data.customers || []);
        renderTrend(data.trend || []);
        renderPareto(data.pareto || []);
        const insights = root.querySelector("[data-insights]");
        insights.innerHTML = (data.insights || []).map(text => `<li>${escapeHtml(text)}</li>`).join("") || "<li>No insights available for this selection.</li>";
        if (data.last_refresh) root.querySelector("[data-last-refresh]").textContent = new Date(data.last_refresh).toLocaleString("en-GB");
    }

    function renderKpis(values) {
        const holder = root.querySelector("[data-kpis]");
        holder.innerHTML = Object.entries(values).map(([key, value]) => `<article class="bp-kpi"><span>${escapeHtml(key)}</span><strong>${escapeHtml(formatValue(value, key))}</strong><small title="Value returned by the configured Power BI measure">Power BI measure</small></article>`).join("");
        holder.hidden = !Object.keys(values).length;
    }

    function deriveKpis(rows) {
        if (!rows.length) return {};
        const numeric = {};
        rows.forEach(row => Object.entries(row).forEach(([key, value]) => {
            if (Number.isFinite(Number(value))) numeric[key] = (numeric[key] || 0) + Number(value);
        }));
        return Object.fromEntries(Object.entries(numeric).slice(0, 8));
    }

    function filteredRows(rows) {
        const q = state.search.toLowerCase();
        return !q ? rows : rows.filter(row => Object.values(row).some(value => String(value ?? "").toLowerCase().includes(q)));
    }

    function renderTable(name, sourceRows) {
        const table = root.querySelector(`[data-table="${name}"]`);
        if (!table) return;
        const rows = filteredRows(sourceRows);
        const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
        if (!rows.length) {
            table.innerHTML = "<tbody><tr><td class=\"bp-no-data\">No data found for the selected filters.</td></tr></tbody>";
            return;
        }
        const paged = name === "details" ? rows.slice((state.page - 1) * state.pageSize, state.page * state.pageSize) : rows;
        table.innerHTML = `<thead><tr>${columns.map(column => `<th><button data-sort=\"${escapeAttr(column)}\">${escapeHtml(column)}</button></th>`).join("")}</tr></thead><tbody>${paged.map(row => `<tr data-customer=\"${escapeAttr(customerValue(row))}\">${columns.map(column => `<td>${escapeHtml(formatValue(row[column], column))}</td>`).join("")}</tr>`).join("")}</tbody>`;
        table.querySelectorAll("tbody tr[data-customer]").forEach(row => row.addEventListener("click", () => {
            if (row.dataset.customer) location.href = root.dataset.customerBase + encodeURIComponent(row.dataset.customer) + "/";
        }));
        table.querySelectorAll("[data-sort]").forEach(button => button.addEventListener("click", () => {
            const key = button.dataset.sort;
            sourceRows.sort((a, b) => String(a[key] ?? "").localeCompare(String(b[key] ?? ""), undefined, { numeric: true }));
            renderTable(name, sourceRows);
        }));
        if (name === "details") updatePagination(rows.length);
    }

    function customerValue(row) {
        const key = Object.keys(row).find(item => item.toLowerCase() === "customer" || item.toLowerCase().includes("customer name"));
        return key ? row[key] || "" : "";
    }

    function renderTrend(rows) {
        const holder = root.querySelector('[data-chart="trend"]');
        if (!rows.length) { holder.innerHTML = "<p class=\"bp-no-data\">No trend data.</p>"; return; }
        const numericKeys = Object.keys(rows[0]).filter(key => rows.some(row => Number.isFinite(Number(row[key]))));
        const max = Math.max(1, ...rows.flatMap(row => numericKeys.map(key => Number(row[key]) || 0)));
        holder.innerHTML = rows.map(row => `<div class="bp-trend-row"><span>${escapeHtml(Object.values(row)[0])}</span><div>${numericKeys.map((key, index) => `<i class="series-${index}" style="height:${Math.max(4, (Number(row[key]) || 0) / max * 100)}%" title="${escapeAttr(key)}: ${escapeAttr(formatValue(row[key], key))}"></i>`).join("")}</div></div>`).join("");
    }

    function renderPareto(rows) {
        const holder = root.querySelector('[data-chart="pareto"]');
        const max = Math.max(1, ...rows.map(row => Number(row.value) || 0));
        holder.innerHTML = rows.slice(0, 15).map(row => `<div class="bp-pareto-row"><span>${escapeHtml(row.customer)}</span><div><i style="width:${(Number(row.value) || 0) / max * 100}%"></i><b style="left:${Math.min(100, Number(row.cumulative_pct) * 100)}%"></b></div><em>${formatValue(row.cumulative_pct, "%")}</em></div>`).join("") || "<p class=\"bp-no-data\">No concentration data.</p>";
    }

    function renderOpportunity(data) {
        const holder = root.querySelector('[data-chart="opportunity"]');
        const rows = data.rows || [];
        if (!rows.length) { holder.innerHTML = "<p class=\"bp-no-data\">No opportunity data.</p>"; return; }
        const customerKey = Object.keys(rows[0]).find(key => key.toLowerCase().includes("customer"));
        const fleetKey = Object.keys(rows[0]).find(key => key.toLowerCase() === "active fleet");
        const valueKey = Object.keys(rows[0]).find(key => key.toLowerCase().includes("parts revenue per fleet"));
        const totalKey = Object.keys(rows[0]).find(key => key.toLowerCase() === "total revenue");
        const maxX = Math.max(1, ...rows.map(row => Number(row[fleetKey]) || 0));
        const maxY = Math.max(1, ...rows.map(row => Number(row[valueKey]) || 0));
        holder.innerHTML = `<div class="bp-quadrants"><span>High Value Accounts</span><span>Strategic Accounts</span><span>Tactical Accounts</span><span>Growth Opportunities</span></div>${rows.map(row => {
            const x = (Number(row[fleetKey]) || 0) / maxX * 92 + 3;
            const y = 95 - (Number(row[valueKey]) || 0) / maxY * 90;
            const size = Math.max(10, Math.min(30, Math.sqrt(Math.abs(Number(row[totalKey]) || 0)) / 100));
            return `<button class="bp-bubble" style="left:${x}%;top:${y}%;width:${size}px;height:${size}px" title="${escapeAttr(row[customerKey])}: Fleet ${escapeAttr(row[fleetKey])}" data-customer="${escapeAttr(row[customerKey])}"></button>`;
        }).join("")}`;
        holder.querySelectorAll("[data-customer]").forEach(item => item.addEventListener("click", () => location.href = root.dataset.customerBase + encodeURIComponent(item.dataset.customer) + "/"));
    }

    function updatePagination(total) {
        const pages = Math.max(1, Math.ceil(total / state.pageSize));
        state.page = Math.min(state.page, pages);
        root.querySelector("[data-page-status]").textContent = `Page ${state.page} of ${pages} · ${total} rows`;
        root.querySelector("[data-prev-page]").disabled = state.page <= 1;
        root.querySelector("[data-next-page]").disabled = state.page >= pages;
    }

    function readFilters() {
        state.filters = {};
        root.querySelectorAll("[data-filter-panel] [name]").forEach(input => {
            const values = String(input.value || "").split(",").map(value => value.trim()).filter(Boolean);
            if (values.length) state.filters[input.name] = values;
        });
        const active = root.querySelector("[data-active-filters]");
        active.innerHTML = Object.entries(state.filters).map(([key, values]) => `<span><b>${escapeHtml(key)}</b>: ${escapeHtml(values.join(", "))}</span>`).join("") || "<span>No active filters</span>";
    }

    function exportUrl(category, type) { return `/business-performance/export/${category}/${type}/?${queryString()}`; }
    function escapeHtml(value) { const node = document.createElement("div"); node.textContent = String(value ?? ""); return node.innerHTML; }
    function escapeAttr(value) { return escapeHtml(value).replace(/"/g, "&quot;"); }

    root.querySelector("[data-filter-toggle]").addEventListener("click", () => { const panel = root.querySelector("[data-filter-panel]"); panel.hidden = !panel.hidden; });
    root.querySelector("[data-apply-filters]").addEventListener("click", () => { readFilters(); root.querySelector("[data-filter-panel]").hidden = true; state.page = 1; load(); });
    root.querySelector("[data-reset-filters]").addEventListener("click", () => { root.querySelectorAll("[data-filter-panel] [name]").forEach(input => input.value = ""); if (customer) root.querySelector('[name="customer"]').value = customer; readFilters(); load(); });
    root.querySelector("[data-retry]").addEventListener("click", load);
    root.querySelector("[data-top-n]")?.addEventListener("change", load);
    root.querySelectorAll("[data-table-search]").forEach(input => input.addEventListener("input", () => { state.search = input.value; state.page = 1; render(state.payload || {}); }));
    root.querySelector("[data-prev-page]")?.addEventListener("click", () => { state.page--; render(state.payload || {}); });
    root.querySelector("[data-next-page]")?.addEventListener("click", () => { state.page++; render(state.payload || {}); });
    root.querySelectorAll("[data-export]").forEach(button => button.addEventListener("click", () => location.href = exportUrl(button.dataset.export, "xlsx")));
    root.querySelectorAll("[data-export-current]").forEach(button => button.addEventListener("click", () => {
        const category = page === "parts-sales"
            ? "parts"
            : page === "machine-sales"
                ? "prime"
                : page === "services-sales"
                    ? "services"
                    : page === "rental-sales"
                        ? "rental"
                        : "customers";
        location.href = exportUrl(category, button.dataset.exportCurrent);
    }));
    if (customer) { state.filters.customer = [customer]; readFilters(); }
    load();
}());
