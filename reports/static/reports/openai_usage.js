(() => {
    const root = document.querySelector("[data-openai-usage-root]");
    if (!root) return;
    const state = { page: 1, pageSize: 25, filtersLoaded: false, payload: null };
    const csrf = () => document.cookie.split("; ").find(v => v.startsWith("csrftoken="))?.split("=")[1] || "";
    const money = (value, currency = "USD") => value == null ? "--" : new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
    const number = value => new Intl.NumberFormat(undefined, { notation: Math.abs(value || 0) >= 1000000 ? "compact" : "standard", maximumFractionDigits: 2 }).format(value || 0);
    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const query = () => {
        const params = new URLSearchParams({ page: state.page, page_size: state.pageSize });
        root.querySelectorAll("[data-filter]").forEach(el => { if (el.value) params.set(el.dataset.filter, el.value); });
        const search = root.querySelector("[data-usage-search]").value.trim();
        if (search) params.set("search", search);
        return params;
    };
    const showMessage = text => {
        const modal = document.querySelector("[data-usage-message]");
        modal.querySelector("[data-usage-message-text]").textContent = text;
        modal.hidden = false; modal.setAttribute("aria-hidden", "false");
    };
    document.querySelector("[data-usage-message-ok]").addEventListener("click", () => {
        const modal = document.querySelector("[data-usage-message]");
        modal.hidden = true; modal.setAttribute("aria-hidden", "true");
    });
    async function request(url, options = {}) {
        const response = await fetch(url, { credentials: "same-origin", ...options, headers: { "X-CSRFToken": csrf(), ...(options.headers || {}) } });
        const data = await response.json().catch(() => ({}));
        if (!response.ok && response.status !== 207) throw new Error(data.error || data.data?.warnings?.join(" ") || `Request failed (${response.status})`);
        return data;
    }
    function cards(summary, synced) {
        const currency = summary.currency || "USD";
        const items = [
            ["Spend This Month", money(summary.official_spend ?? summary.estimated_spend, currency), summary.displayed_spend_source],
            ["Monthly Budget", money(summary.monthly_budget, currency), "Internal limit"],
            ["Remaining Budget", money(summary.remaining_budget, currency), summary.budget_status],
            ["Budget Consumed", `${number(summary.budget_consumed_percentage)}%`, summary.budget_status],
            ["Month-End Forecast", money(summary.forecast_month_end, currency), "Last 7 days / MTD"],
            ["Total Tokens", number(summary.total_tokens), "Current selection"],
            ["Total Requests", number(summary.total_requests), "Current selection"],
            ["Voice Minutes", number(summary.voice_transcription_minutes), `${number(summary.voice_transcription_successful)} successful transcriptions`],
            ["Average Cost / Request", money(summary.average_cost_per_request, currency), summary.displayed_spend_source],
            ["Prepaid Credit", summary.prepaid_credit_balance == null ? "Unavailable" : money(summary.prepaid_credit_balance, currency), summary.credit_balance_status],
            ["Last Synchronization", synced ? new Date(synced).toLocaleString() : "Not synchronized", "UTC source"],
        ];
        root.querySelector("[data-usage-kpis]").innerHTML = items.map(([label, value, note]) => `
            <article class="usage-kpi-card ${escapeHtml(summary.budget_status || "")}">
                <span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note || "")}</small>
            </article>`).join("");
    }
    function budget(summary) {
        const used = summary.official_spend ?? summary.estimated_spend;
        root.querySelector("[data-budget-copy]").textContent = `${money(used, summary.currency)} used of ${money(summary.monthly_budget, summary.currency)}`;
        root.querySelector("[data-budget-percentage]").textContent = `${number(summary.budget_consumed_percentage)}%`;
        root.querySelector("[data-budget-progress]").style.width = `${Math.min(100, Math.max(0, summary.budget_consumed_percentage || 0))}%`;
        root.querySelector("[data-budget-progress]").dataset.status = summary.budget_status;
        root.querySelector("[data-budget-remaining]").textContent = `Remaining internal budget: ${money(summary.remaining_budget, summary.currency)}`;
        root.querySelector("[data-budget-source]").textContent = `${summary.displayed_spend_source} cost`;
    }
    function lineChart(container, rows, key, color = "#ffcd11") {
        if (!rows.length) { container.innerHTML = '<p class="usage-empty">No data for this period.</p>'; return; }
        const values = rows.map(row => Number(row[key] || 0));
        const max = Math.max(...values, 1);
        container.innerHTML = `<div class="usage-bars">${rows.map((row, i) => `
            <div class="usage-bar-item" title="${escapeHtml(row.date || row.day)}: ${number(values[i])}">
                <span style="height:${Math.max(3, values[i] / max * 100)}%;background:${color}"></span>
                <small>${escapeHtml(String(row.date || row.day || "").slice(5, 10))}</small>
            </div>`).join("")}</div>`;
    }
    function rankings(key, labelKey) {
        const container = root.querySelector(`[data-ranking="${key}"]`);
        const rows = state.payload[key] || [];
        if (!rows.length) { container.innerHTML = '<p class="usage-empty">No data available.</p>'; return; }
        const max = Math.max(...rows.map(row => Number(row.estimated_cost || row.tokens || 0)), 1);
        container.innerHTML = rows.slice(0, 8).map(row => {
            const label = row[labelKey] || "Unassigned";
            const value = Number(row.estimated_cost || 0);
            const width = Math.max(2, Number(row.estimated_cost || row.tokens || 0) / max * 100);
            return `<div class="usage-rank-row"><div><strong>${escapeHtml(label)}</strong><span>${number(row.requests)} requests</span></div><b>${money(value, state.payload.summary.currency)}</b><i><span style="width:${width}%"></span></i></div>`;
        }).join("");
    }
    function table(data) {
        const columns = ["Date and Time", "User", "Section", "Feature", "Model", "Input", "Cached", "Output", "Total", "Estimated Cost", "Latency", "Status"];
        root.querySelector("[data-usage-table]").innerHTML = `<thead><tr>${columns.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>${data.rows.map(row => `
            <tr>
                <td>${escapeHtml(new Date(row.usage_timestamp).toLocaleString())}</td><td>${escapeHtml(row.user || "System")}</td>
                <td>${escapeHtml(row.section)}</td><td>${escapeHtml(row.feature)}</td><td>${escapeHtml(row.model)}</td>
                <td>${number(row.input_tokens)}</td><td>${number(row.cached_input_tokens)}</td><td>${number(row.output_tokens)}</td>
                <td>${number(row.total_tokens)}</td><td>${money(row.estimated_cost, state.payload.summary.currency)}</td>
                <td>${number(row.latency_ms)} ms</td><td><span class="usage-status ${escapeHtml(row.status.toLowerCase())}">${escapeHtml(row.status)}</span></td>
            </tr>`).join("") || '<tr><td colspan="12">No usage records.</td></tr>'}</tbody>`;
        const first = data.total ? (data.page - 1) * data.page_size + 1 : 0;
        const last = Math.min(data.total, data.page * data.page_size);
        root.querySelector("[data-page-summary]").textContent = `${first}-${last} of ${data.total}`;
        root.querySelector("[data-page-previous]").disabled = data.page <= 1;
        root.querySelector("[data-page-next]").disabled = last >= data.total;
    }
    function fillOptions(options) {
        if (state.filtersLoaded) return;
        [["model", "models"], ["section", "sections"], ["feature", "features"], ["status", "statuses"]].forEach(([filter, key]) => {
            const select = root.querySelector(`[data-filter="${filter}"]`);
            (options[key] || []).forEach(value => select.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
        });
        state.filtersLoaded = true;
    }
    async function load() {
        const status = root.querySelector("[data-usage-state]");
        status.hidden = false; status.textContent = "Loading OpenAI usage...";
        try {
            const result = await request(`${root.dataset.dashboardUrl}?${query()}`);
            state.payload = result.data;
            fillOptions(state.payload.filter_options);
            cards(state.payload.summary, state.payload.last_synchronized_at);
            budget(state.payload.summary);
            lineChart(root.querySelector('[data-chart="daily_spend"]'), state.payload.daily_spend, "cost");
            lineChart(root.querySelector('[data-chart="daily_tokens"]'), state.payload.daily_tokens, "total", "#243c68");
            rankings("usage_by_model", "model"); rankings("usage_by_section", "section"); rankings("usage_by_feature", "feature");
            root.querySelector("[data-usage-alerts]").innerHTML = state.payload.alerts.map(a => `<div class="usage-alert ${escapeHtml(a.level)}">${escapeHtml(a.message)}</div>`).join("");
            table(state.payload.table);
            document.querySelectorAll("[data-export]").forEach(link => {
                link.href = `${link.dataset.export === "csv" ? root.dataset.exportCsv : root.dataset.exportJson}?${query()}`;
            });
            status.hidden = true;
        } catch (error) { status.textContent = error.message; status.classList.add("error"); }
    }
    root.querySelectorAll("[data-filter]").forEach(el => el.addEventListener("change", () => { state.page = 1; load(); }));
    let searchTimer;
    root.querySelector("[data-usage-search]").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.page = 1; load(); }, 350); });
    root.querySelector("[data-page-previous]").addEventListener("click", () => { state.page--; load(); });
    root.querySelector("[data-page-next]").addEventListener("click", () => { state.page++; load(); });
    root.querySelector("[data-usage-sync]").addEventListener("click", async event => {
        event.currentTarget.disabled = true; event.currentTarget.textContent = "Synchronizing...";
        try {
            const result = await request(root.dataset.syncUrl, { method: "POST" });
            showMessage(result.data.warnings?.length ? result.data.warnings.join(" ") : `Synchronization completed: ${result.data.usage_snapshots} usage and ${result.data.cost_snapshots} cost snapshots.`);
            await load();
        } catch (error) { showMessage(error.message); }
        finally { event.currentTarget.disabled = false; event.currentTarget.textContent = "Synchronize OpenAI Usage"; }
    });
    const modal = document.querySelector("[data-settings-modal]");
    const closeSettings = () => { modal.hidden = true; modal.setAttribute("aria-hidden", "true"); };
    document.querySelectorAll("[data-settings-close]").forEach(el => el.addEventListener("click", closeSettings));
    root.querySelector("[data-usage-settings]").addEventListener("click", async () => {
        const result = await request(root.dataset.settingsUrl);
        const form = document.querySelector("[data-settings-form]");
        Object.entries(result.data).forEach(([key, value]) => {
            const input = form.elements.namedItem(key);
            if (!input) return;
            if (input.type === "checkbox") input.checked = Boolean(value); else input.value = value ?? "";
        });
        form.querySelector("[data-admin-key-state]").textContent = result.data.admin_key_configured ? "Admin key configured securely in the backend." : "Admin key is not configured.";
        modal.hidden = false; modal.setAttribute("aria-hidden", "false");
    });
    document.querySelector("[data-settings-form]").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget; const payload = {};
        new FormData(form).forEach((value, key) => payload[key] = value);
        form.querySelectorAll('input[type="checkbox"]').forEach(input => payload[input.name] = input.checked);
        try {
            await request(root.dataset.settingsUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            closeSettings(); showMessage("OpenAI usage settings saved."); load();
        } catch (error) { showMessage(error.message); }
    });
    load();
})();
