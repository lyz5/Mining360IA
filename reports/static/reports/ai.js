(function () {
    const storageKey = "mining360-ai-chat";
    const conversationKey = "mining360-ai-conversation-id";

    function csrfToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function formatValue(value) {
        if (value === null || value === undefined || value === "") {
            return "BLANK";
        }
        if (typeof value === "number") {
            return `${(value * 100).toFixed(2)}%`;
        }
        return String(value);
    }

    function setHidden(element, hidden) {
        if (element) {
            element.hidden = hidden;
        }
    }

    function updateComposerClearance() {
        const composer = document.querySelector(".ai-chat-composer");
        if (!composer) return;
        const clearance = Math.ceil(composer.getBoundingClientRect().height + 54);
        document.body.style.setProperty("--ai-composer-clearance", `${clearance}px`);
    }

    function afterNextPaint() {
        return new Promise((resolve) => {
            window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
        });
    }

    function scrollIntoConversationView(element, behavior = "smooth") {
        element?.scrollIntoView({ behavior, block: "center" });
    }

    function loadHistory() {
        try {
            const raw = sessionStorage.getItem(storageKey);
            const parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            return [];
        }
    }

    function saveHistory(messages) {
        try {
            sessionStorage.setItem(storageKey, JSON.stringify(messages.slice(-20)));
        } catch (error) {
            // ignore
        }
    }

    function renderContext(container, intent, metric, measure, validation) {
        if (!container) return;
        container.innerHTML = "";
        const items = [
            ["Section", intent.section],
            ["Metric", metric || intent.metric],
            ["Measure", measure],
        ];
        Object.entries(intent.filters || {}).forEach(([key, value]) => {
            items.push([key, value]);
        });
        if (validation) {
            const isValid = validation.valid === true || validation.status === "valid";
            items.push(["Validation", isValid ? "OK" : (validation.status || "Failed")]);
        }
        items.forEach(([label, value]) => {
            const dt = document.createElement("dt");
            dt.textContent = label;
            const dd = document.createElement("dd");
            dd.textContent = value;
            container.append(dt, dd);
        });
    }

    function renderTable(table, rows, summary) {
        if (!table) return;
        const data = summary || rows || [];
        table.innerHTML = "";
        if (!data.length) {
            const tbody = document.createElement("tbody");
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.textContent = "No rows returned.";
            tr.appendChild(td);
            tbody.appendChild(tr);
            table.appendChild(tbody);
            return;
        }
        const columns = Object.keys(data[0]);
        const thead = document.createElement("thead");
        const headRow = document.createElement("tr");
        columns.forEach((column) => {
            const th = document.createElement("th");
            th.textContent = column.replaceAll("_", " ");
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        data.forEach((row) => {
            const tr = document.createElement("tr");
            columns.forEach((column) => {
                const td = document.createElement("td");
                const value = row[column];
                td.textContent = column.includes("value") || column.includes("average") || column.includes("availability")
                    ? formatValue(value)
                    : value;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    const analyticalText = {
        en: {
            physicalAvailability: "Physical Availability",
            mineSite: "Mine Site",
            model: "Model",
            period: "Period",
            customer: "Customer",
            editContext: "Edit context",
            totalDowntime: "Total Downtime",
            eventCount: "Event Count",
            averageDuration: "Average Duration",
            keyTakeaway: "Key takeaway",
            topDrivers: "Top downtime drivers",
            driver: "Driver",
            downtimeHours: "Downtime Hours",
            share: "% of Total",
            cumulative: "Cumulative %",
            action: "Action",
            explore: "Explore",
            viewAll: "View all drivers",
            showTopFive: "Show top 5",
            showPareto: "Show Pareto",
            analyzeDriver: "Analyze a driver",
            affectedEquipment: "View affected equipment",
            showTrend: "Show trend",
            openPowerBI: "Open in Power BI",
            preview: "Preview",
            powerBIReport: "Power BI Report",
            relatedReports: "Related Reports",
            noDrivers: "No downtime driver is available for the selected context.",
            selectDriver: "Select a driver from the table to start the root cause analysis.",
            periodValues: {
                "last 12 months": "Last 12 Months",
                "year to date": "Year to Date",
                "month to date": "Month to Date",
            },
        },
    };

    function detectedLanguage(question) {
        return "en";
    }

    function localeFor(language) {
        return "en-US";
    }

    function localNumber(value, language, digits = 2) {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) return "N/A";
        return new Intl.NumberFormat(localeFor(language), {
            maximumFractionDigits: digits,
            minimumFractionDigits: digits,
        }).format(parsed);
    }

    function availabilityValue(rows) {
        for (const row of (Array.isArray(rows) ? rows : [])) {
            const key = Object.keys(row || {}).find((item) => String(item).toLowerCase().includes("availability"));
            if (!key) continue;
            const value = Number(row[key]);
            if (Number.isFinite(value)) return value * 100;
        }
        return null;
    }

    function displayFilterValue(key, value, language) {
        const raw = Array.isArray(value) ? value.join(", ") : String(value ?? "");
        if (key === "period") {
            return analyticalText[language].periodValues[raw.toLowerCase()] || raw;
        }
        return raw;
    }

    function contextLabel(key, language) {
        const labels = {
            minesite: analyticalText[language].mineSite,
            site: analyticalText[language].mineSite,
            model: analyticalText[language].model,
            period: analyticalText[language].period,
            customer: analyticalText[language].customer,
        };
        return labels[key] || key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    function renderAvailabilityOverview(body, diagnostics, options = {}) {
        const drivers = Array.isArray(diagnostics?.drivers) ? diagnostics.drivers : [];
        if (!body || diagnostics?.total_downtime_hours === undefined) return;
        const language = options.language || "en";
        const labels = analyticalText[language];
        const availability = availabilityValue(options.rows);
        const intentFilters = options.intent?.filters || {};
        const contextChips = Object.entries(intentFilters).map(([key, value]) => `
            <span class="ai-analysis-chip">
                <span class="ai-analysis-chip__icon" aria-hidden="true"></span>
                <span>
                    <small>${escapeHtml(contextLabel(key, language))}</small>
                    <strong>${escapeHtml(displayFilterValue(key, value, language))}</strong>
                </span>
            </span>
        `).join("");
        const totalEvents = drivers.reduce((total, item) => total + Number(item.event_count || 0), 0);
        const averageDuration = totalEvents ? Number(diagnostics.total_downtime_hours || 0) / totalEvents : null;
        const topThreeShare = drivers.slice(0, 3).reduce((total, item) => total + Number(item.share_percentage || 0), 0);
        const topThreeNames = drivers.slice(0, 3).map((item) => item.driver).join(", ");
        const takeaway = drivers.length
            ? `${topThreeNames} account for ${localNumber(topThreeShare, language, 1)}% of total downtime.`
            : labels.noDrivers;
        const knowledge = Array.isArray(options.resourceKnowledge?.results)
            ? options.resourceKnowledge.results
            : [];
        const knowledgeMarkup = knowledge.length ? `
            <section class="ai-resource-guidance">
                <div class="ai-resource-guidance__heading">
                    <strong>Validated Caterpillar guidance</strong>
                    <span>Resources Knowledge Base</span>
                </div>
                <div class="ai-resource-guidance__items">
                    ${knowledge.slice(0, 3).map((item) => `
                        <article>
                            <strong>${escapeHtml(item.title)}</strong>
                            ${item.recommendations?.length
                                ? `<ul>${item.recommendations.slice(0, 3).map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>`
                                : `<p>${escapeHtml(item.troubleshooting_procedure || item.inspection_procedure || item.symptom)}</p>`}
                            <a href="${escapeHtml(item.source.url)}">${escapeHtml(item.source.title)}${item.source.page ? ` · page ${item.source.page}` : ""}</a>
                        </article>
                    `).join("")}
                </div>
            </section>` : "";
        body.innerHTML = `
            <section class="ai-analytical-result-card">
                <div>
                    <span>${escapeHtml(labels.physicalAvailability)}</span>
                    <strong>${availability === null ? "N/A" : `${localNumber(availability, language)}%`}</strong>
                    <p>${Object.entries(intentFilters).map(([key, value]) => escapeHtml(displayFilterValue(key, value, language))).join(" · ")}</p>
                </div>
            </section>
            ${contextChips ? `
                <div class="ai-analysis-context">
                    <div class="ai-analysis-context__chips">${contextChips}</div>
                    <button type="button" class="ai-context-edit">${escapeHtml(labels.editContext)}</button>
                </div>
            ` : ""}
            <div class="ai-secondary-metrics">
                <article><span>${escapeHtml(labels.totalDowntime)}</span><strong>${localNumber(diagnostics.total_downtime_hours, language)} h</strong></article>
                ${totalEvents ? `<article><span>${escapeHtml(labels.eventCount)}</span><strong>${localNumber(totalEvents, language, 0)}</strong></article>` : ""}
                ${averageDuration !== null ? `<article><span>${escapeHtml(labels.averageDuration)}</span><strong>${localNumber(averageDuration, language)} h</strong></article>` : ""}
            </div>
            <section class="ai-key-takeaway">
                <strong>${escapeHtml(labels.keyTakeaway)}</strong>
                <p>${escapeHtml(takeaway)}</p>
            </section>
            ${knowledgeMarkup}
        `;
        body.querySelector(".ai-context-edit")?.addEventListener("click", () => {
            document.getElementById("ai-question")?.focus();
        });
    }

    function renderDriversTable(body, diagnostics, options = {}) {
        if (!body) return;
        const drivers = Array.isArray(diagnostics?.drivers) ? diagnostics.drivers : [];
        const language = options.language || "en";
        const labels = analyticalText[language];
        const expanded = Boolean(options.expanded);
        const visibleDrivers = expanded ? drivers : drivers.slice(0, 5);
        body.innerHTML = `
            <section class="ai-downtime-drivers-table" aria-label="${escapeHtml(labels.topDrivers)}">
                <div class="ai-downtime-drivers-table__header">
                    <div><strong>${escapeHtml(labels.topDrivers)}</strong></div>
                </div>
                ${visibleDrivers.length ? `
                    <div class="ai-downtime-drivers-table__scroll">
                        <table>
                            <thead><tr>
                                <th>${escapeHtml(labels.driver)}</th>
                                <th>${escapeHtml(labels.downtimeHours)}</th>
                                <th>${escapeHtml(labels.share)}</th>
                                <th>${escapeHtml(labels.cumulative)}</th>
                                <th><span class="sr-only">${escapeHtml(labels.action)}</span></th>
                            </tr></thead>
                            <tbody>${visibleDrivers.map((item, index) => `
                                <tr data-driver-index="${index}" tabindex="0">
                                    <td><strong>${escapeHtml(item.driver)}</strong></td>
                                    <td>${localNumber(item.hours, language)} h</td>
                                    <td>${localNumber(item.share_percentage, language, 1)}${language === "fr" ? " %" : "%"}</td>
                                    <td>${localNumber(item.cumulative_percentage, language, 1)}${language === "fr" ? " %" : "%"}</td>
                                    <td><button type="button" class="ai-driver-explore">${escapeHtml(labels.explore)} <span aria-hidden="true">&#x2192;</span></button></td>
                                </tr>
                            `).join("")}</tbody>
                        </table>
                    </div>
                    <div class="ai-driver-card-list">
                        ${visibleDrivers.map((item, index) => `
                            <button type="button" class="ai-driver-card" data-driver-index="${index}">
                                <strong>${escapeHtml(item.driver)}</strong>
                                <span>${localNumber(item.hours, language)} h · ${localNumber(item.share_percentage, language, 1)}${language === "fr" ? " %" : "%"}</span>
                                <small>${escapeHtml(labels.cumulative)}: ${localNumber(item.cumulative_percentage, language, 1)}${language === "fr" ? " %" : "%"}</small>
                            </button>
                        `).join("")}
                    </div>
                ` : `<p class="ai-analytical-empty">${escapeHtml(labels.noDrivers)}</p>`}
                <div class="ai-drivers-footer">
                    ${drivers.length > 5 ? `<button type="button" class="ai-text-action" data-toggle-drivers>${escapeHtml(expanded ? labels.showTopFive : labels.viewAll)}</button>` : ""}
                    <button type="button" class="ai-text-action" data-show-pareto>${escapeHtml(labels.showPareto)}</button>
                </div>
            </section>
        `;
        body.querySelectorAll("[data-driver-index]").forEach((row) => {
            const selectDriver = () => {
                const item = visibleDrivers[Number(row.dataset.driverIndex)];
                if (item && typeof options.onSelectDriver === "function") options.onSelectDriver(item);
            };
            row.addEventListener("click", selectDriver);
            row.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectDriver();
                }
            });
        });
        body.querySelector("[data-toggle-drivers]")?.addEventListener("click", () => {
            options.onToggleExpanded?.(!expanded);
        });
        body.querySelector("[data-show-pareto]")?.addEventListener("click", () => options.onShowPareto?.());
    }

    function renderDowntimeDiagnostics(body, diagnostics, options = {}) {
        const drivers = Array.isArray(diagnostics?.drivers) ? diagnostics.drivers : [];
        if (!body || diagnostics?.total_downtime_hours === undefined) return;
        const card = document.createElement("section");
        card.className = "ai-downtime-pareto";
        card.setAttribute("aria-label", "Downtime drivers Pareto");
        card.innerHTML = `
            <div class="ai-downtime-pareto__header">
                <div>
                    <span>Downtime analysis</span>
                    <strong>Pareto des principaux drivers</strong>
                </div>
                <label class="ai-downtime-pareto__worktype">
                    <span>Work Type</span>
                    <select aria-label="Filter downtime drivers by Work Type">
                        <option value="" ${!options.workType ? "selected" : ""}>All</option>
                        <option value="Planned" ${options.workType === "Planned" ? "selected" : ""}>Planned</option>
                        <option value="Unplanned" ${options.workType === "Unplanned" ? "selected" : ""}>Unplanned</option>
                    </select>
                </label>
                <div class="ai-downtime-pareto__total">
                    <strong>${Number(diagnostics.total_downtime_hours || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} h</strong>
                    <span>Total downtime</span>
                </div>
            </div>
            <div class="ai-downtime-pareto__legend">
                <span><i class="is-hours"></i>Downtime Hours</span>
                <span><i class="is-pareto"></i>Cumulative Pareto</span>
            </div>
            <div class="ai-downtime-pareto__chart"></div>
        `;
        const chart = card.querySelector(".ai-downtime-pareto__chart");
        if (!drivers.length) {
            chart.innerHTML = '<p class="ai-downtime-pareto__empty">No downtime driver returned for this context.</p>';
        } else {
            const width = 760;
            const height = 360;
            const left = 58;
            const right = 50;
            const top = 34;
            const bottom = 104;
            const plotWidth = width - left - right;
            const plotHeight = height - top - bottom;
            const step = plotWidth / drivers.length;
            const barWidth = Math.min(step * 0.62, 46);
            const maxHours = Math.max(...drivers.map((item) => Number(item.hours) || 0), 1);
            const baseline = top + plotHeight;
            const points = [];
            const content = [];
            drivers.forEach((item, index) => {
                const hours = Number(item.hours) || 0;
                const cumulative = Math.min(Math.max(Number(item.cumulative_percentage) || 0, 0), 100);
                const x = left + index * step + step / 2;
                const barHeight = hours / maxHours * plotHeight;
                const y = baseline - barHeight;
                const pointY = baseline - cumulative / 100 * plotHeight;
                const label = String(item.driver).length > 18
                    ? `${String(item.driver).slice(0, 17)}…`
                    : String(item.driver);
                points.push(`${x.toFixed(1)},${pointY.toFixed(1)}`);
                content.push(`
                    <g class="ai-pareto-bar-group" data-driver-index="${index}" tabindex="0" role="button">
                        <title>${escapeHtml(item.driver)}: ${hours.toLocaleString(undefined, { maximumFractionDigits: 2 })} h</title>
                        <rect x="${(x - barWidth / 2).toFixed(1)}" y="${y.toFixed(1)}"
                              width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"
                              rx="2" class="ai-pareto-bar"></rect>
                        <text x="${x.toFixed(1)}" y="${Math.max(y - 7, 14).toFixed(1)}"
                              class="ai-pareto-hours" text-anchor="middle">${hours.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
                    </g>
                    <text x="${x.toFixed(1)}" y="${(baseline + 18).toFixed(1)}"
                          transform="rotate(-42 ${x.toFixed(1)} ${(baseline + 18).toFixed(1)})"
                          class="ai-pareto-driver" text-anchor="end">${escapeHtml(label)}</text>
                    <circle cx="${x.toFixed(1)}" cy="${pointY.toFixed(1)}" r="6" class="ai-pareto-point"></circle>
                    <text x="${x.toFixed(1)}" y="${Math.max(pointY - 12, 13).toFixed(1)}"
                          class="ai-pareto-percent" text-anchor="middle">${cumulative.toFixed(0)}%</text>
                `);
            });
            const grid = [0, 0.5, 1].map((ratio) => {
                const y = baseline - ratio * plotHeight;
                return `
                    <line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" class="ai-pareto-grid"></line>
                    <text x="${left - 9}" y="${y + 4}" text-anchor="end" class="ai-pareto-axis">${(maxHours * ratio).toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
                    <text x="${width - right + 9}" y="${y + 4}" class="ai-pareto-axis">${Math.round(ratio * 100)}%</text>
                `;
            }).join("");
            chart.innerHTML = `
                <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Downtime Pareto chart">
                    ${grid}
                    ${content.join("")}
                    <polyline points="${points.join(" ")}" class="ai-pareto-line"></polyline>
                </svg>
            `;
            chart.querySelectorAll(".ai-pareto-bar-group").forEach((group) => {
                const selectDriver = () => {
                    const item = drivers[Number(group.dataset.driverIndex)];
                    if (item && typeof options.onSelectDriver === "function") options.onSelectDriver(item);
                };
                group.addEventListener("click", selectDriver);
                group.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectDriver();
                    }
                });
            });
        }
        const select = card.querySelector(".ai-downtime-pareto__worktype select");
        select?.addEventListener("change", async () => {
            if (typeof options.onWorkTypeChange !== "function") return;
            select.disabled = true;
            card.classList.add("is-loading");
            try {
                await options.onWorkTypeChange(select.value);
            } catch (error) {
                select.disabled = false;
                card.classList.remove("is-loading");
                window.alert(error.message || "Unable to refresh downtime drivers.");
            }
        });
        body.appendChild(card);
    }

    function renderMessages(container, messages) {
        if (!container) return;
        container.innerHTML = messages.map((message) => `
            <div class="ai-message ${message.role === "user" ? "user" : "assistant"}">
                <div class="ai-message__avatar">${message.role === "user" ? "You" : "AI"}</div>
                <div class="ai-message__content">
                    ${message.agent ? `<span class="ai-agent-badge">${escapeHtml(message.agent)}</span>` : ""}
                    <div class="ai-message__body">${escapeHtml(message.content).replaceAll("\n", "<br>")}</div>
                </div>
            </div>
        `).join("");
    }

    function setAnalyticalView(state, view, { scroll = false } = {}) {
        const normalized = view === "all_drivers" ? "summary" : view;
        state.activeAnalyticalView = view;
        document.querySelectorAll("[data-analytical-view]").forEach((section) => {
            section.hidden = section.dataset.analyticalView !== normalized;
        });
        const quickActions = document.getElementById("ai-analytical-quick-actions");
        const launcher = document.getElementById("ai-powerbi-launcher");
        const showSummaryActions = normalized === "summary";
        setHidden(quickActions, !showSummaryActions);
        setHidden(launcher, !showSummaryActions || !state.currentNavigation?.report_id);
        if (scroll) {
            document.getElementById("ai-analytical-content-area")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        window.dispatchEvent(new CustomEvent("mining360:analytical-context", {
            detail: {
                active_analysis: {
                    ...(state.currentIntent || {}),
                    downtime_driver: state.selectedDriver || null,
                    active_view: view,
                },
            },
        }));
    }

    async function openPowerBI(root, state, navigation) {
        if (!navigation?.report_id) return;
        const title = document.getElementById("ai-powerbi-title");
        const status = document.getElementById("ai-powerbi-status");
        const tabs = document.getElementById("ai-powerbi-report-tabs");
        setAnalyticalView(state, "powerbi_preview", { scroll: true });
        window.setTimeout(() => window.dispatchEvent(new Event("resize")), 80);
        title.textContent = navigation.display_name || navigation.report_name || "Relevant report";
        status.textContent = "Loading Power BI Report...";
        if (!window.Mining360PowerBIEmbed) {
            status.textContent = "Power BI is unavailable. The analytical result remains available.";
            return;
        }
        if (!state.powerbi) {
            state.powerbi = new window.Mining360PowerBIEmbed(
                document.getElementById("ai-powerbi-report"),
                {
                    embedConfigUrl: root.dataset.embedConfigUrl,
                    onEvent: (item) => {
                        state.powerbiEvents.push(item);
                        status.textContent = item.type.replaceAll("_", " ");
                    },
                },
            );
        }
        const options = [navigation, ...(navigation.alternative_reports || [])];
        tabs.replaceChildren();
        options.forEach((option, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `ai-report-tab${index === 0 ? " is-active" : ""}`;
            button.setAttribute("role", "tab");
            button.setAttribute("aria-selected", index === 0 ? "true" : "false");
            button.textContent = option.display_name || option.report_name || "Power BI report";
            button.addEventListener("click", async () => {
                tabs.querySelectorAll(".ai-report-tab").forEach((item) => {
                    item.classList.toggle("is-active", item === button);
                    item.setAttribute("aria-selected", item === button ? "true" : "false");
                });
                await openPowerBI(root, state, option);
            });
            tabs.appendChild(button);
        });
        try {
            await state.powerbi.navigate(navigation);
            status.textContent = (navigation.warnings || []).join(" ") || "Report synchronized.";
        } catch (error) {
            status.textContent = error.message || "The Power BI report could not be loaded.";
        }
    }

    function renderQuickActions(root, state, diagnostics, language) {
        const labels = analyticalText[language];
        const host = document.getElementById("ai-analytical-quick-actions");
        const drivers = diagnostics?.drivers || [];
        host.innerHTML = `
            <button type="button" data-quick-action="driver">${escapeHtml(labels.analyzeDriver)}</button>
            <button type="button" data-quick-action="equipment" ${drivers.length ? "" : "disabled"}>${escapeHtml(labels.affectedEquipment)}</button>
            <button type="button" data-quick-action="trend" ${state.currentNavigation?.report_id ? "" : "disabled"}>${escapeHtml(labels.showTrend)}</button>
            <button type="button" data-quick-action="powerbi" ${state.currentNavigation?.report_id ? "" : "disabled"}>${escapeHtml(labels.openPowerBI)}</button>
        `;
        host.querySelector('[data-quick-action="driver"]')?.addEventListener("click", () => {
            document.querySelector("#ai-drivers-content tbody tr")?.focus();
            document.getElementById("ai-drivers-view")?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
        host.querySelector('[data-quick-action="equipment"]')?.addEventListener("click", async () => {
            if (!drivers[0]) return;
            await state.openDriver(drivers[0]);
            window.Mining360DowntimeExplorer?.showTab("equipment");
        });
        host.querySelector('[data-quick-action="trend"]')?.addEventListener("click", () => openPowerBI(root, state, state.currentNavigation));
        host.querySelector('[data-quick-action="powerbi"]')?.addEventListener("click", () => openPowerBI(root, state, state.currentNavigation));
    }

    function renderPowerBILauncher(root, state, language) {
        const host = document.getElementById("ai-powerbi-launcher");
        const navigation = state.currentNavigation;
        if (!navigation?.report_id) {
            setHidden(host, true);
            return;
        }
        const labels = analyticalText[language];
        const filters = state.currentIntent?.filters || {};
        host.innerHTML = `
            <div>
                <span>${escapeHtml(labels.powerBIReport)}</span>
                <strong title="${escapeHtml(navigation.display_name || navigation.report_name || "")}">${escapeHtml(labels.relatedReports)}</strong>
                <small>${Object.entries(filters).map(([key, value]) => escapeHtml(displayFilterValue(key, value, language))).join(" · ")}</small>
            </div>
            <button type="button" data-powerbi-preview>${escapeHtml(labels.preview)}</button>
            <button type="button" data-powerbi-open>${escapeHtml(labels.openPowerBI)}</button>
        `;
        host.querySelector("[data-powerbi-preview]")?.addEventListener("click", () => openPowerBI(root, state, navigation));
        host.querySelector("[data-powerbi-open]")?.addEventListener("click", () => openPowerBI(root, state, navigation));
        setHidden(host, false);
    }

    async function runQuestion(root, state) {
        if (state.isLoading) return;
        const input = document.getElementById("ai-question");
        const question = input.value.trim();
        const inputMetadata = state.pendingInputMetadata || null;
        state.pendingInputMetadata = null;
        const loading = document.getElementById("ai-loading");
        const error = document.getElementById("ai-error");
        const errorText = document.getElementById("ai-error-text");
        const tableSection = document.getElementById("ai-table-section");
        const availabilityOverviewSection = document.getElementById("ai-availability-overview-section");
        const availabilityOverviewContent = document.getElementById("ai-availability-overview-content");
        const driversContent = document.getElementById("ai-drivers-content");
        const downtimeSection = document.getElementById("ai-downtime-section");
        const downtimeContent = document.getElementById("ai-downtime-content");
        const powerbiSection = document.getElementById("ai-powerbi-section");
        const daxSection = document.getElementById("ai-dax-section");
        const debugSection = document.getElementById("ai-debug-section");
        const contextList = document.getElementById("ai-context-list");
        const table = document.getElementById("ai-result-table");
        const dax = document.getElementById("ai-dax");
        const debug = document.getElementById("ai-debug");
        const chatThread = document.getElementById("ai-chat-thread");

        if (!question) {
            return;
        }
        state.isLoading = true;
        const sendButton = document.getElementById("ai-run-question");
        if (sendButton) {
            sendButton.disabled = true;
            sendButton.classList.add("is-loading");
            sendButton.setAttribute("aria-label", "Question en cours d’analyse");
        }

        state.messages.push({ role: "user", content: question });
        renderMessages(chatThread, state.messages);
        saveHistory(state.messages);
        input.value = "";
        input.style.height = "auto";
        updateComposerClearance();

        window.Mining360DowntimeExplorer?.resetForNewPrompt();
        availabilityOverviewContent?.replaceChildren();
        driversContent?.replaceChildren();
        downtimeContent?.replaceChildren();
        document.getElementById("ai-powerbi-report-tabs")?.replaceChildren();
        if (state.powerbi) {
            state.powerbi.reset();
        }
        state.currentIntent = null;
        state.currentNavigation = null;
        state.currentDiagnostics = null;
        state.selectedDriver = "";
        state.driversExpanded = false;

        setHidden(loading, false);
        setHidden(error, true);
        setHidden(tableSection, true);
        setHidden(availabilityOverviewSection, true);
        setHidden(downtimeSection, true);
        setHidden(powerbiSection, true);
        setHidden(daxSection, true);
        setHidden(debugSection, true);
        await afterNextPaint();
        scrollIntoConversationView(loading);

        try {
            const response = await fetch(root.dataset.aiAskUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                },
                body: JSON.stringify({
                    question,
                    conversation: state.messages,
                    conversation_id: state.conversationId,
                    input_metadata: inputMetadata,
                    agent_selection: document.getElementById("ai-agent-selection")?.value || "auto",
                }),
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Query failed.");
            }

            const assistantMessage = payload.chat_message || payload.answer?.interpretation || payload.answer?.answer || "Done.";
            state.messages.push({
                role: "assistant",
                content: assistantMessage,
                diagnostics: payload.availability_diagnostics || null,
                agent: payload.agent?.name || "",
            });
            renderMessages(chatThread, state.messages);
            saveHistory(state.messages);
            scrollIntoConversationView(chatThread.lastElementChild);

            const intent = payload.intent || payload.semantic_request || {};
            const language = detectedLanguage(question);
            const hasDowntimeDiagnostics = payload.availability_diagnostics?.total_downtime_hours !== undefined;
            state.currentIntent = intent;
            state.currentNavigation = payload.navigation || null;
            state.currentDiagnostics = payload.availability_diagnostics || null;
            state.currentQuestion = question;
            state.language = language;

            if (hasDowntimeDiagnostics && downtimeContent && availabilityOverviewContent && driversContent) {
                const refreshDiagnostics = async (workType) => {
                    const diagnosticsResponse = await fetch(root.dataset.availabilityDiagnosticsUrl, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                        body: JSON.stringify({ intent, work_type: workType, dataset_name: "FPR Global DB + RLS" }),
                    });
                    const diagnosticsPayload = await diagnosticsResponse.json();
                    if (!diagnosticsResponse.ok || !diagnosticsPayload.ok) {
                        throw new Error(diagnosticsPayload.error || "Unable to refresh downtime drivers.");
                    }
                    state.currentDiagnostics = diagnosticsPayload.diagnostics;
                    renderDiagnostics(diagnosticsPayload.diagnostics, workType);
                };
                state.openDriver = async (driver) => {
                    if (!driver || !window.Mining360DowntimeExplorer) return;
                    state.selectedDriver = driver.driver;
                    setAnalyticalView(state, "root_cause_explorer", { scroll: true });
                    await window.Mining360DowntimeExplorer.open({
                        action: "open_root_cause_explorer",
                        selected_dimension: "downtime_driver",
                        selected_value: driver.driver,
                        current_context: {
                            kpi: intent.metric || "availability",
                            filters: intent.filters || {},
                        },
                        source_question: question,
                        conversation_id: state.conversationId,
                        report_id: payload.navigation?.report_id || "",
                    });
                };
                const renderDrivers = () => renderDriversTable(driversContent, state.currentDiagnostics, {
                    language,
                    expanded: state.driversExpanded,
                    onSelectDriver: state.openDriver,
                    onToggleExpanded: (expanded) => {
                        state.driversExpanded = expanded;
                        setAnalyticalView(state, expanded ? "all_drivers" : "summary");
                        renderDrivers();
                    },
                    onShowPareto: () => {
                        downtimeContent.replaceChildren();
                        renderDowntimeDiagnostics(downtimeContent, state.currentDiagnostics, {
                            intent,
                            workType: state.workType || "",
                            onSelectDriver: state.openDriver,
                            onWorkTypeChange: refreshDiagnostics,
                        });
                        setAnalyticalView(state, "pareto", { scroll: true });
                    },
                });
                const renderDiagnostics = (diagnostics, workType = "") => {
                    state.workType = workType;
                    renderAvailabilityOverview(availabilityOverviewContent, diagnostics, {
                        intent,
                        rows: payload.rows,
                        language,
                        resourceKnowledge: payload.resource_knowledge,
                    });
                    renderDrivers();
                    if (state.activeAnalyticalView === "pareto") {
                        downtimeContent.replaceChildren();
                        renderDowntimeDiagnostics(downtimeContent, diagnostics, {
                            intent,
                            workType,
                            onSelectDriver: state.openDriver,
                            onWorkTypeChange: refreshDiagnostics,
                        });
                    }
                    renderQuickActions(root, state, diagnostics, language);
                    renderPowerBILauncher(root, state, language);
                };
                renderDiagnostics(payload.availability_diagnostics);
                setHidden(availabilityOverviewSection, false);
                setAnalyticalView(state, "summary");
                window.setTimeout(() => availabilityOverviewSection.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
            }

            renderContext(contextList, intent, payload.metric, payload.measure, payload.validation);
            renderTable(table, payload.rows, payload.summary);
            if (dax) dax.textContent = payload.dax || intent.dax || "";
            if (debug) debug.textContent = JSON.stringify(payload.debug || payload, null, 2);
            const isAdmin = root.dataset.isPlatformAdmin === "true";
            setHidden(tableSection, !isAdmin);
            setHidden(daxSection, !isAdmin);
            setHidden(debugSection, !isAdmin);
            if (payload.conversation_id) {
                state.conversationId = payload.conversation_id;
                sessionStorage.setItem(conversationKey, state.conversationId);
            }
        } catch (err) {
            errorText.textContent = err.message;
            setHidden(error, false);
            state.messages.push({ role: "assistant", content: `I could not process the question: ${err.message}` });
            renderMessages(chatThread, state.messages);
            saveHistory(state.messages);
            scrollIntoConversationView(chatThread.lastElementChild);
        } finally {
            state.isLoading = false;
            if (sendButton) {
                sendButton.disabled = false;
                sendButton.classList.remove("is-loading");
                sendButton.setAttribute("aria-label", "Send question");
            }
            setHidden(loading, true);
            input.focus({ preventScroll: true });
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        const root = document.querySelector("[data-ai-ask-url]");
        if (!root) {
            return;
        }
        const button = document.getElementById("ai-run-question");
        const input = document.getElementById("ai-question");
        const chatThread = document.getElementById("ai-chat-thread");
        const state = {
            messages: loadHistory(),
            conversationId: sessionStorage.getItem(conversationKey) || (window.crypto?.randomUUID?.() || String(Date.now())),
            powerbi: null,
            powerbiEvents: [],
            isLoading: false,
            activeAnalyticalView: "summary",
            currentIntent: null,
            currentNavigation: null,
            currentDiagnostics: null,
            selectedDriver: "",
            driversExpanded: false,
            workType: "",
            language: "en",
            openDriver: async () => {},
            pendingInputMetadata: null,
        };

        if (!state.messages.length) {
            state.messages = [
                {
                    role: "assistant",
                    content: "Hello. Ask me a question about availability, downtime, models, or sites.",
                },
            ];
        }
        renderMessages(chatThread, state.messages);
        updateComposerClearance();
        const composer = document.querySelector(".ai-chat-composer");
        if (composer && window.ResizeObserver) {
            const composerObserver = new ResizeObserver(updateComposerClearance);
            composerObserver.observe(composer);
        }
        window.addEventListener("resize", updateComposerClearance);

        button?.addEventListener("click", function () {
            runQuestion(root, state);
        });
        window.addEventListener("mining360:voice-transcription-ready", function (event) {
            state.pendingInputMetadata = event.detail || { input_mode: "voice" };
        });
        window.addEventListener("mining360:submit-question", function () {
            runQuestion(root, state);
        });
        input?.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                runQuestion(root, state);
            }
        });
        input?.addEventListener("input", function () {
            input.style.height = "auto";
            input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
            updateComposerClearance();
        });
        const fullscreenButton = document.getElementById("ai-report-fullscreen");
        const reportSection = document.getElementById("ai-powerbi-section");
        fullscreenButton?.addEventListener("click", async function () {
            try {
                if (document.fullscreenElement) {
                    await document.exitFullscreen();
                } else {
                    await reportSection.requestFullscreen();
                }
            } catch (error) {
                const status = document.getElementById("ai-powerbi-status");
                if (status) status.textContent = "Full screen is unavailable in this browser.";
            }
        });
        document.addEventListener("fullscreenchange", function () {
            if (!fullscreenButton) return;
            const active = document.fullscreenElement === reportSection;
            fullscreenButton.title = active ? "Exit full screen" : "View report in full screen";
            fullscreenButton.setAttribute("aria-label", fullscreenButton.title);
            window.setTimeout(() => window.dispatchEvent(new Event("resize")), 80);
        });
        const downtimeFullscreenButton = document.getElementById("ai-downtime-fullscreen");
        const downtimeSection = document.getElementById("ai-downtime-section");
        downtimeFullscreenButton?.addEventListener("click", async function () {
            try {
                if (document.fullscreenElement) {
                    await document.exitFullscreen();
                } else {
                    await downtimeSection.requestFullscreen();
                }
            } catch (error) {
                downtimeFullscreenButton.title = "Full screen is unavailable in this browser.";
            }
        });
        document.addEventListener("fullscreenchange", function () {
            if (!downtimeFullscreenButton) return;
            const active = document.fullscreenElement === downtimeSection;
            downtimeFullscreenButton.title = active
                ? "Exit full screen"
                : "View Downtime Drivers in full screen";
            downtimeFullscreenButton.setAttribute(
                "aria-label",
                downtimeFullscreenButton.title,
            );
        });
        document.querySelectorAll("[data-ai-view]").forEach((button) => {
            button.addEventListener("click", () => setAnalyticalView(state, button.dataset.aiView, { scroll: true }));
        });
        window.addEventListener("mining360:show-analytical-view", (event) => {
            setAnalyticalView(state, event.detail?.view || "summary", { scroll: true });
        });
        window.addEventListener("mining360:navigate-powerbi", async (event) => {
            const navigation = event.detail;
            if (!navigation?.report_id) return;
            state.currentNavigation = navigation;
            await openPowerBI(root, state, navigation);
        });
        document.querySelectorAll(".js-ai-example").forEach((example) => {
            example.addEventListener("click", function () {
                input.value = example.dataset.question || "";
                runQuestion(root, state);
            });
        });
    });
}());
