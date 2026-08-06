(function () {
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
            .replaceAll("'", "&#039;");
    }

    function number(value, digits = 1) {
        const parsed = Number(value);
        return Number.isFinite(parsed)
            ? parsed.toLocaleString(undefined, { maximumFractionDigits: digits })
            : "N/A";
    }

    function rowValue(row, label) {
        const normalize = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
        const expected = normalize(label);
        const key = Object.keys(row || {}).find((item) => normalize(item).includes(expected));
        return key ? row[key] : null;
    }

    class DowntimeRootCauseExplorer {
        constructor(root) {
            this.root = root;
            this.app = document.getElementById("downtime-root-cause-explorer");
            this.baseUrl = root.dataset.downtimeExplorerBaseUrl;
            this.isAdmin = root.dataset.isPlatformAdmin === "true";
            this.state = {
                sessionId: "",
                context: {},
                selectedDriver: "",
                dimensions: [],
                activeTab: "overview",
                summary: {},
                limitations: [],
                sourcePayload: {},
            };
            this.bind();
        }

        async post(path, payload = {}) {
            const response = await fetch(path, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-CSRFToken": csrfToken(),
                },
                body: JSON.stringify(payload),
            });
            return this.parseResponse(response);
        }

        async get(path) {
            const response = await fetch(path, {
                credentials: "same-origin",
                headers: { "Accept": "application/json" },
            });
            return this.parseResponse(response);
        }

        async parseResponse(response) {
            const contentType = response.headers.get("content-type") || "";
            const body = await response.text();
            if (!contentType.toLowerCase().includes("application/json")) {
                const loginResponse = response.redirected
                    && /\/(?:login|accounts\/login)\//i.test(response.url);
                if (loginResponse || response.status === 401 || response.status === 403) {
                    throw new Error("Your session has expired. Sign in again and retry.");
                }
                throw new Error(
                    `The Downtime Root Cause Explorer received an invalid server response (HTTP ${response.status}).`
                );
            }

            let result;
            try {
                result = JSON.parse(body);
            } catch (_error) {
                throw new Error("The Downtime Root Cause Explorer received an invalid JSON response.");
            }
            if (!response.ok || !result.ok) {
                throw new Error(
                    result.error
                    || result.detail
                    || `Downtime Explorer request failed (HTTP ${response.status}).`
                );
            }
            return result;
        }

        endpoint(action) {
            return `${this.baseUrl}${this.state.sessionId}/${action}/`;
        }

        setStatus(message, mode = "loading") {
            const status = document.getElementById("dt-explorer-status");
            status.hidden = !message;
            status.className = `downtime-explorer__status is-${mode}`;
            status.innerHTML = message
                ? `<span class="loading-spinner" aria-hidden="true"></span>${escapeHtml(message)}`
                : "";
            if (mode !== "loading") {
                status.querySelector(".loading-spinner")?.remove();
            }
        }

        renderContext() {
            const filters = this.state.context.filters || {};
            const selections = this.state.context.selections || {};
            const chips = [
                ...Object.entries(filters),
                ...Object.entries(selections),
            ].map(([key, value]) => `
                <span><strong>${escapeHtml(key.replaceAll("_", " "))}</strong>${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</span>
            `);
            document.getElementById("dt-explorer-filters").innerHTML = chips.join("");
            const breadcrumb = [
                ["Availability", "overview"],
                ["Downtime Drivers", "overview"],
                ...Object.entries(selections).map(([key, value]) => [value, key]),
            ];
            document.getElementById("dt-explorer-breadcrumb").innerHTML = breadcrumb.map(
                ([label], index) => `${index ? '<i>›</i>' : ""}<button type="button" data-depth="${index}">${escapeHtml(label)}</button>`
            ).join("");
            document.querySelectorAll("#dt-explorer-breadcrumb button").forEach((button) => {
                button.addEventListener("click", async () => {
                    const depth = Number(button.dataset.depth || 0);
                    if (depth <= 1) {
                        await this.reset();
                        return;
                    }
                    const currentDepth = breadcrumb.length - 1;
                    for (let step = currentDepth; step > depth; step -= 1) {
                        await this.back();
                    }
                });
            });
            document.getElementById("dt-explorer-subtitle").textContent =
                `${this.state.selectedDriver} analysis with the active conversation filters.`;
        }

        renderSummary(summary) {
            this.state.summary = summary || {};
            const cards = [
                ["Downtime Hours", rowValue(summary, "Downtime Hours"), "h"],
                ["Contribution", Number(rowValue(summary, "Contribution") || 0) * 100, "%"],
                ["Event Count", rowValue(summary, "Event Count"), ""],
                ["Affected Equipment", rowValue(summary, "Affected Equipment"), ""],
                ["Average Duration", rowValue(summary, "Average Duration"), "h"],
                ["Median Duration", rowValue(summary, "Median Duration"), "h"],
                ["Longest Event", rowValue(summary, "Longest Event"), "h"],
            ];
            document.getElementById("dt-explorer-kpis").innerHTML = cards.map(
                ([label, value, unit]) => `
                    <article>
                        <span>${escapeHtml(label)}</span>
                        <strong>${number(value)}${unit ? ` ${unit}` : ""}</strong>
                    </article>
                `
            ).join("");
        }

        renderTable(rows, columns, options = {}) {
            if (!rows?.length) {
                return `<div class="downtime-explorer__empty">${escapeHtml(options.empty || "No data was found for the selected context.")}</div>`;
            }
            return `
                ${options.search ? '<input class="downtime-explorer__search" type="search" placeholder="Search results...">' : ""}
                <div class="downtime-explorer__table-wrap">
                    <table class="downtime-explorer__table">
                        <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
                        <tbody>${rows.map((row) => `
                            <tr ${options.clickDimension ? `data-value="${escapeHtml(rowValue(row, options.clickDimension) || "")}"` : ""}>
                                ${columns.map((column) => {
                                    const value = rowValue(row, column.key);
                                    return `<td>${column.number ? number(value, column.digits ?? 1) : escapeHtml(value ?? "")}${column.unit && value !== null ? ` ${column.unit}` : ""}</td>`;
                                }).join("")}
                            </tr>
                        `).join("")}</tbody>
                    </table>
                </div>
            `;
        }

        bindSearch(container) {
            const input = container.querySelector(".downtime-explorer__search");
            if (!input) return;
            input.addEventListener("input", () => {
                const query = input.value.trim().toLowerCase();
                container.querySelectorAll("tbody tr").forEach((row) => {
                    row.hidden = query && !row.textContent.toLowerCase().includes(query);
                });
            });
        }

        async open(payload) {
            this.state.sourcePayload = payload;
            this.app.hidden = false;
            this.setStatus("Opening Downtime Root Cause Explorer...");
            try {
                const result = await this.post(`${this.baseUrl}open/`, payload);
                this.state.sessionId = result.explorer_session_id;
                this.state.context = result.context || {};
                this.state.selectedDriver = result.selected_driver;
                this.state.dimensions = result.available_dimensions || [];
                this.state.limitations = result.limitations || [];
                this.renderContext();
                await this.loadSummary();
                await this.showTab("overview");
                this.setStatus("");
                return true;
            } catch (error) {
                this.setStatus(error.message, "error");
                return false;
            }
        }

        async loadSummary() {
            this.setStatus("Loading Power BI summary...");
            const result = await this.post(this.endpoint("summary"));
            this.renderSummary(result.summary || {});
        }

        setActiveTab(tab) {
            this.state.activeTab = tab;
            this.app.querySelectorAll("[data-dt-tab]").forEach((button) => {
                button.classList.toggle("is-active", button.dataset.dtTab === tab);
            });
        }

        async showTab(tab) {
            if (!this.state.sessionId) return;
            this.setActiveTab(tab);
            const content = document.getElementById("dt-explorer-content");
            this.setStatus(
                tab === "ai-insights" ? "" : `Loading ${tab.replaceAll("-", " ")}...`
            );
            try {
                if (tab === "root-causes") {
                    const result = await this.post(this.endpoint("smcs"));
                    const coverage = result.coverage || {};
                    content.innerHTML = `
                        <div class="downtime-explorer__section-head">
                            <div><span>CAT hierarchy</span><h3>SMCS Classification Engine</h3></div>
                            <span class="smcs-preview-badge">Preview</span>
                        </div>
                        <div class="downtime-explorer__notice">
                            <strong>Hybrid classification pipeline</strong>
                            Explicit SMCS codes, exact CAT descriptions and approved synonyms are evaluated first.
                            OpenAI is used only for unresolved or conflicting comments, and can select only from approved SMCS candidates.
                        </div>
                        <div class="downtime-explorer__coverage">
                            <article><span>Matched events</span><strong>${number(coverage.matched_event_count, 0)}</strong></article>
                            <article><span>Unmatched events</span><strong>${number(coverage.unmatched_event_count, 0)}</strong></article>
                            <article><span>Event coverage</span><strong>${number(coverage.event_coverage_percentage)}%</strong></article>
                            <article><span>SMCS groups</span><strong>${number((result.rows || []).length, 0)}</strong></article>
                        </div>
                        <div class="smcs-classification-actions" ${this.isAdmin ? "" : "hidden"}>
                            <button type="button" id="smcs-analyze-unmatched">Analyze Unmatched Comments</button>
                            <button type="button" disabled title="Available after Preview approval">Review AI Classifications</button>
                            <button type="button" disabled title="Available after Preview approval">Reprocess Low Confidence</button>
                            <button type="button" id="smcs-export-preview" disabled>Export Preview</button>
                        </div>
                        <div id="smcs-preview-progress" class="smcs-preview-progress" hidden></div>
                        <div id="smcs-preview-result"></div>
                        <h4 class="smcs-official-heading">Current deterministic breakdown</h4>
                        ${this.renderTable(result.rows, [
                            { label: "SMCS Code", key: "SMCS Code" },
                            { label: "Component / System", key: "SMCS Description" },
                            { label: "Downtime Hours", key: "Downtime Hours", number: true, unit: "h" },
                            { label: "Events", key: "Event Count", number: true, digits: 0 },
                            { label: "Equipment", key: "Affected Equipment", number: true, digits: 0 },
                            { label: "Match Method", key: "Match Method" },
                        ], { search: true, empty: "No explicit SMCS code or exact SMCS description was found in the selected event comments." })}
                    `;
                    this.bindSearch(content);
                    content.querySelector("#smcs-analyze-unmatched")?.addEventListener("click", () => this.startSMCSPreview());
                } else if (tab === "overview") {
                    const preferred = "work_type";
                    const dimension = this.state.dimensions.find((item) => item.code === preferred)
                        || this.state.dimensions.find((item) => item.code !== "downtime_driver");
                    const result = await this.post(this.endpoint("breakdown"), {
                        dimension: dimension?.code,
                    });
                    const rows = result.rows || [];
                    content.innerHTML = `
                        <div class="downtime-explorer__section-head">
                            <div><span>Breakdown</span><h3>${escapeHtml(dimension?.display_name || "Available dimension")}</h3></div>
                            <select id="dt-breakdown-dimension">
                                ${this.state.dimensions.filter((item) => item.code !== "downtime_driver").map((item) =>
                                    `<option value="${escapeHtml(item.code)}" ${item.code === dimension?.code ? "selected" : ""}>${escapeHtml(item.display_name)}</option>`
                                ).join("")}
                            </select>
                        </div>
                        ${this.renderTable(rows, [
                            { label: dimension?.display_name || "Dimension", key: dimension?.display_name || "" },
                            { label: "Downtime Hours", key: "Downtime Hours", number: true, unit: "h" },
                            { label: "Events", key: "Event Count", number: true, digits: 0 },
                            { label: "Equipment", key: "Affected Equipment", number: true, digits: 0 },
                            { label: "Average Duration", key: "Average Duration", number: true, unit: "h" },
                        ], { clickDimension: dimension?.display_name })}
                    `;
                    content.querySelector("#dt-breakdown-dimension")?.addEventListener("change", (event) => {
                        this.loadBreakdown(event.target.value);
                    });
                    content.querySelectorAll("tbody tr[data-value]").forEach((row) => {
                        row.addEventListener("click", () => this.selectDimension(dimension.code, row.dataset.value));
                    });
                } else if (tab === "equipment") {
                    const result = await this.post(this.endpoint("equipment"));
                    content.innerHTML = this.renderTable(result.rows, [
                        { label: "Serial Number", key: "SN" },
                        { label: "Equipment", key: "Equip" },
                        { label: "Model", key: "Model" },
                        { label: "MineSite", key: "Site" },
                        { label: "Downtime Hours", key: "Downtime Hours", number: true, unit: "h" },
                        { label: "Events", key: "Event Count", number: true, digits: 0 },
                        { label: "Longest Event", key: "Longest Event", number: true, unit: "h" },
                        { label: "Latest Event", key: "Latest Event Date" },
                    ], {
                        search: true,
                        clickDimension: "SN",
                        empty: "No affected equipment was found.",
                    });
                    this.bindSearch(content);
                    content.querySelectorAll("tbody tr[data-value]").forEach((row) => {
                        row.addEventListener("click", () => this.selectDimension("serial_number", row.dataset.value));
                    });
                } else if (tab === "events") {
                    const result = await this.post(this.endpoint("events"), { limit: 300 });
                    content.innerHTML = this.renderTable(result.rows, [
                        { label: "Event ID", key: "Event ID" },
                        { label: "Serial Number", key: "Serial Number" },
                        { label: "Equipment", key: "Equipment" },
                        { label: "Start", key: "Start Date" },
                        { label: "End", key: "End Date" },
                        { label: "Duration", key: "Duration", number: true, unit: "h" },
                        { label: "Work Type", key: "Work Type" },
                        { label: "Comment", key: "Comment" },
                    ], {
                        search: true,
                        clickDimension: "Event ID",
                        empty: "No downtime event was found for the selected context.",
                    });
                    this.bindSearch(content);
                    content.querySelectorAll("tbody tr[data-value]").forEach((row) => {
                        row.addEventListener("click", () => {
                            const event = result.rows.find((item) => item["Event ID"] === row.dataset.value);
                            if (event) this.showEventDetail(event);
                        });
                    });
                } else if (tab === "comments") {
                    const result = await this.post(this.endpoint("comments"));
                    const coverage = result.coverage || {};
                    content.innerHTML = `
                        <div class="downtime-explorer__coverage">
                            <article><span>Comments</span><strong>${number(coverage.commented_event_count, 0)}</strong></article>
                            <article><span>Event coverage</span><strong>${number(coverage.comment_rate)}%</strong></article>
                            <article><span>Downtime coverage</span><strong>${number(coverage.coverage_percentage)}%</strong></article>
                            <article><span>Missing comments</span><strong>${number(coverage.events_without_comment, 0)}</strong></article>
                        </div>
                        ${this.renderTable(result.rows, [
                            { label: "Event ID", key: "Event ID" },
                            { label: "Equipment", key: "Equipment" },
                            { label: "Date", key: "Start Date" },
                            { label: "Duration", key: "Duration", number: true, unit: "h" },
                            { label: "Comment", key: "Comment" },
                        ], { search: true, empty: "No comment is available for the selected downtime events." })}
                    `;
                    this.bindSearch(content);
                } else if (tab === "repeated") {
                    const result = await this.post(this.endpoint("repeated-failures"), { window_days: 90 });
                    content.innerHTML = `
                        <div class="downtime-explorer__notice"><strong>Detection logic</strong>${escapeHtml(result.logic)}</div>
                        ${this.renderTable(result.patterns, [
                            { label: "Serial Number", key: "serial_number" },
                            { label: "Driver", key: "downtime_driver" },
                            { label: "Work Type", key: "work_type" },
                            { label: "Events", key: "event_count", number: true, digits: 0 },
                            { label: "Downtime", key: "total_downtime_hours", number: true, unit: "h" },
                            { label: "First Event", key: "first_event_date" },
                            { label: "Last Event", key: "last_event_date" },
                        ], { empty: "No repeated failure pattern was found with the configured rule." })}
                    `;
                } else if (tab === "ai-insights") {
                    content.innerHTML = `
                        <div class="downtime-explorer__ai-start">
                            <h3>AI Root Cause Summary</h3>
                            <p>OpenAI will analyze only the filtered comments and will report evidence, coverage and limitations.</p>
                            <button type="button" id="dt-run-ai-analysis">Analyze Comments</button>
                        </div>
                    `;
                    content.querySelector("#dt-run-ai-analysis").addEventListener("click", () => this.runAIAnalysis());
                }
                this.setStatus("");
            } catch (error) {
                content.innerHTML = `<div class="downtime-explorer__empty is-error">${escapeHtml(error.message)} <button type="button" data-retry>Retry</button></div>`;
                content.querySelector("[data-retry]")?.addEventListener("click", () => this.showTab(tab));
                this.setStatus("", "error");
            }
        }

        async startSMCSPreview() {
            const button = document.getElementById("smcs-analyze-unmatched");
            const progress = document.getElementById("smcs-preview-progress");
            if (!button || !progress) return;
            button.disabled = true;
            progress.hidden = false;
            progress.textContent = "Preparing a representative Preview sample...";
            try {
                const job = await this.post(this.endpoint("smcs-classification/preview"));
                await this.pollSMCSPreview(job.job_id);
            } catch (error) {
                progress.classList.add("is-error");
                progress.textContent = error.message;
                button.disabled = false;
            }
        }

        async pollSMCSPreview(jobId) {
            const progress = document.getElementById("smcs-preview-progress");
            const button = document.getElementById("smcs-analyze-unmatched");
            const terminal = new Set(["Completed", "Partially Completed", "Failed", "Cancelled"]);
            while (true) {
                const job = await this.get(this.endpoint(`smcs-classification/jobs/${jobId}`));
                progress.textContent = `Analyzing ${number(job.processed_events, 0)} of ${number(job.total_events, 0)} comments - ${job.status}`;
                if (terminal.has(job.status)) {
                    if (job.status === "Failed") throw new Error(job.error || "SMCS Preview failed.");
                    this.renderSMCSPreview(job);
                    button.disabled = false;
                    return;
                }
                await new Promise((resolve) => setTimeout(resolve, 1200));
            }
        }

        renderSMCSPreview(job) {
            const host = document.getElementById("smcs-preview-result");
            const exportButton = document.getElementById("smcs-export-preview");
            const comparison = job.result?.comparison || {};
            const rows = job.result?.results || [];
            rows.forEach((row) => {
                row.current_exact_match = ["Explicit SMCS Code", "Exact Description", "Synonym Match"].includes(row.match_method)
                    ? `${row.primary_match?.smcs_code || ""} - ${row.primary_match?.smcs_description || ""}`
                    : "None";
                row.smcs_description = row.primary_match
                    ? `${row.primary_match.smcs_code} - ${row.primary_match.smcs_description}`
                    : "Unresolved";
                row.evidence_text = (row.evidence_phrases || []).join(" | ") || "None";
                row.alternatives_text = (row.alternative_candidates || []).map(
                    (item) => `${item.smcs_code || ""} ${item.smcs_description || ""} (${item.confidence || 0}%)`
                ).join(" | ") || "None";
            });
            host.innerHTML = `
                <div class="smcs-preview-summary">
                    <article><span>Exact coverage</span><strong>${number(comparison.deterministic_matches, 0)} events</strong></article>
                    <article><span>Hybrid coverage</span><strong>${number(comparison.hybrid_matches, 0)} events</strong></article>
                    <article><span>Downtime coverage</span><strong>${number(comparison.downtime_hour_coverage)}%</strong></article>
                    <article><span>High confidence</span><strong>${number(comparison.high_confidence_rate)}%</strong></article>
                    <article><span>Needs review</span><strong>${number(comparison.review_rate)}%</strong></article>
                    <article><span>Unresolved</span><strong>${number(comparison.unresolved_rate)}%</strong></article>
                </div>
                <div class="downtime-explorer__notice is-warning"><strong>Preview only</strong>No AI suggestion is included in the official SMCS aggregates. Official classifications written: 0.</div>
                ${this.renderTable(rows, [
                    { label: "Event ID", key: "event_id" },
                    { label: "Comment", key: "comment" },
                    { label: "Current Exact Match", key: "current_exact_match" },
                    { label: "Proposed AI Match", key: "smcs_description" },
                    { label: "Confidence", key: "confidence", number: true, unit: "%" },
                    { label: "Evidence", key: "evidence_text" },
                    { label: "Alternatives", key: "alternatives_text" },
                    { label: "Review Required", key: "requires_review" },
                ], { search: true, empty: "No event was selected for Preview." })}
            `;
            this.bindSearch(host);
            exportButton.disabled = false;
            exportButton.onclick = () => {
                const blob = new Blob([JSON.stringify(job.result, null, 2)], { type: "application/json" });
                const link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = `smcs_classification_preview_${job.job_id}.json`;
                link.click();
                URL.revokeObjectURL(link.href);
            };
        }

        async loadBreakdown(dimension) {
            const content = document.getElementById("dt-explorer-content");
            this.setStatus("Loading root cause breakdown...");
            try {
                const result = await this.post(this.endpoint("breakdown"), { dimension });
                const config = this.state.dimensions.find((item) => item.code === dimension);
                content.querySelector("tbody").innerHTML = (result.rows || []).map((row) => `
                    <tr data-value="${escapeHtml(rowValue(row, config.display_name) || "")}">
                        <td>${escapeHtml(rowValue(row, config.display_name) || "")}</td>
                        <td>${number(rowValue(row, "Downtime Hours"))} h</td>
                        <td>${number(rowValue(row, "Event Count"), 0)}</td>
                        <td>${number(rowValue(row, "Affected Equipment"), 0)}</td>
                        <td>${number(rowValue(row, "Average Duration"))} h</td>
                    </tr>
                `).join("");
                content.querySelectorAll("tbody tr").forEach((row) => {
                    row.addEventListener("click", () => this.selectDimension(dimension, row.dataset.value));
                });
                this.setStatus("");
            } catch (error) {
                this.setStatus(error.message, "error");
            }
        }

        async selectDimension(dimension, value) {
            if (!value) return;
            this.setStatus(`Applying ${dimension} filter...`);
            try {
                const result = await this.post(this.endpoint("select"), { dimension, value });
                this.state.context = result.context;
                this.renderContext();
                await this.loadSummary();
                await this.showTab(this.state.activeTab);
            } catch (error) {
                this.setStatus(error.message, "error");
            }
        }

        async runAIAnalysis() {
            const content = document.getElementById("dt-explorer-content");
            this.setStatus("Analyzing comments...");
            try {
                const result = await this.post(this.endpoint("analyze-comments"));
                const analysis = result.result || {};
                const coverage = analysis.coverage || {};
                content.innerHTML = `
                    <div class="downtime-explorer__coverage">
                        <article><span>Comments analyzed</span><strong>${number(coverage.commented_event_count, 0)}</strong></article>
                        <article><span>Events</span><strong>${number(coverage.event_count, 0)}</strong></article>
                        <article><span>Covered downtime</span><strong>${number(coverage.covered_downtime_hours)} h</strong></article>
                        <article><span>Coverage</span><strong>${number(coverage.coverage_percentage)}%</strong></article>
                    </div>
                    <section class="downtime-explorer__ai-summary">
                        <h3>Root Cause Summary</h3>
                        <p>${escapeHtml(analysis.summary || "Insufficient information.")}</p>
                    </section>
                    <div class="downtime-explorer__themes">
                        ${(analysis.themes || []).map((theme) => `
                            <article>
                                <span>${escapeHtml(theme.classification || "")}</span>
                                <h4>${escapeHtml(theme.name || "")}</h4>
                                <p>${escapeHtml(theme.summary || "")}</p>
                                <dl>
                                    <dt>Evidence</dt><dd>${number(theme.event_count, 0)} events</dd>
                                    <dt>Downtime</dt><dd>${number(theme.downtime_hours)} h</dd>
                                    <dt>Confidence</dt><dd>${number(theme.confidence)}%</dd>
                                </dl>
                            </article>
                        `).join("")}
                    </div>
                    ${(analysis.limitations || []).length ? `<div class="downtime-explorer__notice"><strong>Limitations</strong>${(analysis.limitations || []).map(escapeHtml).join("; ")}</div>` : ""}
                `;
                this.setStatus("");
            } catch (error) {
                content.innerHTML = `<div class="downtime-explorer__empty is-error">${escapeHtml(error.message)} <button type="button" id="dt-retry-ai">Retry analysis</button></div>`;
                content.querySelector("#dt-retry-ai")?.addEventListener("click", () => this.runAIAnalysis());
                this.setStatus("", "error");
            }
        }

        showEventDetail(event) {
            let dialog = document.getElementById("dt-event-detail-dialog");
            if (!dialog) {
                dialog = document.createElement("dialog");
                dialog.id = "dt-event-detail-dialog";
                dialog.className = "downtime-explorer__dialog";
                document.body.appendChild(dialog);
            }
            dialog.innerHTML = `
                <header>
                    <div><span>Downtime event</span><h3>${escapeHtml(event["Event ID"] || "")}</h3></div>
                    <button type="button" aria-label="Close">×</button>
                </header>
                <dl>
                    ${Object.entries(event).map(([key, value]) => `
                        <dt>${escapeHtml(key)}</dt>
                        <dd>${escapeHtml(value ?? "")}</dd>
                    `).join("")}
                </dl>
            `;
            dialog.querySelector("button").addEventListener("click", () => dialog.close());
            dialog.showModal();
        }

        async navigatePowerBI() {
            if (!this.state.sessionId) return;
            try {
                const result = await this.post(this.endpoint("navigate"));
                window.dispatchEvent(new CustomEvent("mining360:navigate-powerbi", {
                    detail: result.navigation,
                }));
            } catch (error) {
                this.setStatus(error.message, "error");
            }
        }

        resetForNewPrompt() {
            if (document.fullscreenElement === this.app) {
                document.exitFullscreen().catch(() => {});
            }
            this.state = {
                sessionId: "",
                context: {},
                selectedDriver: "",
                dimensions: [],
                activeTab: "overview",
                summary: {},
                limitations: [],
                sourcePayload: {},
            };
            this.app.hidden = true;
            document.getElementById("dt-explorer-filters").replaceChildren();
            document.getElementById("dt-explorer-breadcrumb").replaceChildren();
            document.getElementById("dt-explorer-kpis").replaceChildren();
            document.getElementById("dt-explorer-content").replaceChildren();
            this.setStatus("");
        }

        async reset() {
            if (!this.state.sessionId) return;
            const result = await this.post(this.endpoint("reset"));
            this.state.context = result.context;
            this.renderContext();
            await this.loadSummary();
            await this.showTab("overview");
        }

        async back() {
            if (!this.state.sessionId) {
                document.getElementById("ai-downtime-section")?.scrollIntoView({ behavior: "smooth" });
                return;
            }
            const result = await this.post(this.endpoint("back"));
            this.state.context = result.context;
            this.renderContext();
            await this.loadSummary();
            await this.showTab("overview");
        }

        closeToDrivers() {
            window.dispatchEvent(new CustomEvent("mining360:show-analytical-view", {
                detail: { view: "summary" },
            }));
        }

        bind() {
            this.app.querySelectorAll("[data-dt-tab]").forEach((button) => {
                button.addEventListener("click", () => this.showTab(button.dataset.dtTab));
            });
            this.app.querySelectorAll("[data-dt-action]").forEach((button) => {
                button.addEventListener("click", () => this.showTab(button.dataset.dtAction));
            });
            document.getElementById("dt-explorer-reset").addEventListener("click", () => this.reset());
            document.getElementById("dt-explorer-back").addEventListener("click", () => this.closeToDrivers());
            document.getElementById("dt-explorer-powerbi").addEventListener("click", () => this.navigatePowerBI());
            document.getElementById("dt-explorer-fullscreen").addEventListener("click", async () => {
                if (document.fullscreenElement) await document.exitFullscreen();
                else await this.app.requestFullscreen();
            });
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector("[data-downtime-explorer-base-url]");
        if (!root) return;
        window.Mining360DowntimeExplorer = new DowntimeRootCauseExplorer(root);
    });
}());
