(function () {
    const storageKey = "mining360-ai-chat";
    const conversationKey = "mining360-ai-conversation-id";
    const conversationSidebarKey = "mining360-ai-conversations-collapsed";
    const focusModeKey = "mining360-ai-focus-mode";
    const allowedAgentBadges = {
        machine_performance: "Machine Performance",
        mining_knowledge: "Mining Knowledge",
        combined: "Combined",
    };

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
        // The composer is a normal flex child. No artificial message padding is required.
        document.body.style.removeProperty("--ai-composer-clearance");
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
            const monthly = raw.match(/^(20\d{2})-(0[1-9]|1[0-2])$/);
            if (monthly) {
                return new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-US", {
                    month: "long",
                    year: "numeric",
                    timeZone: "UTC",
                }).format(new Date(`${raw}-01T00:00:00Z`));
            }
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

    function renderMessages(container, messages, state) {
        if (!container) return;
        const analyticalParking = document.getElementById("ai-analytical-content-area");
        ["downtime-root-cause-explorer", "ai-powerbi-section"].forEach((id) => {
            const view = document.getElementById(id);
            if (view && analyticalParking && view.parentElement !== analyticalParking) {
                view.hidden = true;
                analyticalParking.appendChild(view);
            }
        });
        if (!messages.length) {
            container.innerHTML = `
                <div class="ai-chat-empty-state">
                    <strong>Mining 360 AI</strong>
                    <p>Ask about machine performance, availability, downtime, affected equipment or mining best practices.</p>
                    <div class="ai-empty-prompts">
                        <button type="button" data-suggested-prompt="What is the availability at Essakane?">Availability at Essakane</button>
                        <button type="button" data-suggested-prompt="Show me the top downtime drivers.">Top downtime drivers</button>
                        <button type="button" data-suggested-prompt="Analyze repeated failures.">Analyze repeated failures</button>
                        <button type="button" data-suggested-prompt="What are the preventive maintenance best practices?">Preventive maintenance best practices</button>
                    </div>
                </div>
            `;
            container.querySelectorAll("[data-suggested-prompt]").forEach((button) => {
                button.addEventListener("click", () => {
                    const input = document.getElementById("ai-question");
                    if (!input) return;
                    input.value = button.dataset.suggestedPrompt || "";
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    input.focus();
                });
            });
            return;
        }
        container.innerHTML = messages.map((message) => {
            const agentCode = String(message.agent_code || message.agent || "").toLowerCase().replaceAll(" ", "_");
            const agentLabel = allowedAgentBadges[agentCode] || "";
            return `
            <div class="ai-message ${message.role === "user" ? "user" : "assistant"} ${message.status === "failed" ? "is-failed" : ""}" data-message-id="${escapeHtml(message.id || "")}">
                <div class="ai-message__avatar">${message.role === "user" ? "You" : "AI"}</div>
                <div class="ai-message__content">
                    ${agentLabel ? `<span class="ai-agent-badge">${escapeHtml(agentLabel)}</span>` : ""}
                    <div class="ai-message__body">${message.status === "processing" ? "Processing..." : escapeHtml(message.content).replaceAll("\n", "<br>")}</div>
                    ${message.role === "assistant" ? `<div class="ai-message__artifacts" data-message-artifacts></div>` : ""}
                    ${message.role === "assistant" && message.message_type === "analytical_result" ? `<small class="ai-saved-result">Saved result · Calculated ${escapeHtml(new Date(message.created_at).toLocaleString())}</small>` : ""}
                    ${message.role === "assistant" && message.status !== "processing" ? `<div class="ai-message__actions"><button type="button" data-copy-message>Copy</button>${message.message_type === "analytical_result" ? `<button type="button" data-refresh-message>Refresh analysis</button>` : ""}${message.status === "failed" ? `<button type="button" data-retry-message>Retry</button>` : ""}</div>` : ""}
                </div>
            </div>
        `; }).join("");
        container.querySelectorAll("[data-copy-message]").forEach((button) => {
            button.addEventListener("click", () => {
                const item = messages.find((message) => message.id === button.closest("[data-message-id]")?.dataset.messageId);
                if (item) navigator.clipboard?.writeText(item.content || "");
            });
        });
        container.querySelectorAll("[data-retry-message]").forEach((button) => {
            button.addEventListener("click", () => retryMessage(state, button.closest("[data-message-id]")?.dataset.messageId));
        });
        container.querySelectorAll("[data-refresh-message]").forEach((button) => {
            button.addEventListener("click", () => {
                const response = messages.find((message) => message.id === button.closest("[data-message-id]")?.dataset.messageId);
                const question = messages.find((message) => message.id === response?.parent_message_id);
                const input = document.getElementById("ai-question");
                if (!input || !question) return;
                input.value = question.content;
                const snapshot = (response.artifacts || []).find((item) => item.artifact_type === "response_snapshot");
                state.pendingInputMetadata = {
                    refresh_of_artifact_id: snapshot?.id || "",
                    refresh_of_message_id: response.id,
                };
                runQuestion(state.root, state);
            });
        });
        container.querySelectorAll(".ai-message").forEach((element, index) => {
            const message = messages[index];
            const host = element.querySelector("[data-message-artifacts]");
            if (host && message?.role === "assistant") {
                renderMessageArtifacts(state.root, state, message, host);
            }
        });
    }

    function responseSnapshotForMessage(message) {
        return (message.artifacts || []).find((item) => item.artifact_type === "response_snapshot") || null;
    }

    function responseTemplateCode(payload) {
        return payload?.presentation?.template_code
            || payload?.response_envelope?.presentation?.template_code
            || (payload?.availability_diagnostics?.total_downtime_hours !== undefined
                ? "legacy_availability_response"
                : "generic_analytical");
    }

    function adaptiveContextMarkup(intent, language) {
        return Object.entries(intent?.filters || {})
            .filter(([, value]) => value !== null && value !== "" && (!Array.isArray(value) || value.length))
            .map(([key, value]) => `<span class="ai-analysis-chip"><small>${escapeHtml(contextLabel(key, language))}</small><strong>${escapeHtml(displayFilterValue(key, value, language))}</strong></span>`)
            .join("");
    }

    function analyticalRowsTable(rows, templateCode) {
        const values = Array.isArray(rows) ? rows : [];
        if (!values.length) return '<p class="ai-analytical-empty">No data returned for this analytical scope.</p>';
        const columns = [...new Set(values.flatMap((row) => Object.keys(row || {})))].slice(0, 8);
        return `<div class="ai-adaptive-table-wrap"><table class="ai-adaptive-table"><thead><tr>${templateCode === "ranking" ? "<th>Rank</th>" : ""}${columns.map((key) => `<th>${escapeHtml(key.replaceAll("_", " "))}</th>`).join("")}</tr></thead><tbody>${values.slice(0, 50).map((row, index) => `<tr>${templateCode === "ranking" ? `<td>${index + 1}</td>` : ""}${columns.map((key) => `<td>${escapeHtml(row[key] ?? "-")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }

    function renderAdaptivePrimary(host, payload, intent, language) {
        const value = availabilityValue(payload.rows);
        const metric = intent.primary_metric || intent.metric || payload.metric || "KPI";
        const row = Array.isArray(payload.rows) ? payload.rows[0] : null;
        const rawValue = value === null && row ? Object.values(row).find((item) => Number.isFinite(Number(item))) : null;
        const displayValue = value !== null ? `${localNumber(value, language)}%` : (rawValue ?? "N/A");
        host.innerHTML = `<section class="ai-adaptive-response ai-adaptive-response--kpi"><div class="ai-analytical-result-card"><div><span>${escapeHtml(String(metric).replaceAll("_", " "))}</span><strong>${escapeHtml(displayValue)}</strong></div></div><div class="ai-analysis-context__chips">${adaptiveContextMarkup(intent, language)}</div></section>`;
    }

    function renderAdaptiveDiagnostics(host, payload, intent, language, options) {
        const diagnostics = payload.downtime_diagnostics || payload.availability_diagnostics || {};
        const drivers = Array.isArray(diagnostics.drivers) ? diagnostics.drivers : [];
        const events = drivers.reduce((total, item) => total + Number(item.event_count || 0), 0);
        const equipment = drivers.reduce((total, item) => Math.max(total, Number(item.affected_equipment || 0)), 0);
        host.innerHTML = `<section class="ai-adaptive-response"><div class="ai-analysis-context__chips">${adaptiveContextMarkup(intent, language)}</div><div class="ai-secondary-metrics"><article><span>Total Downtime</span><strong>${localNumber(diagnostics.total_downtime_hours || 0, language)} h</strong></article><article><span>Event Count</span><strong>${localNumber(events, language, 0)}</strong></article><article><span>Affected Equipment</span><strong>${localNumber(equipment, language, 0)}</strong></article></div><section class="ai-key-takeaway"><strong>${responseTemplateCode(payload) === "root_cause_analysis" ? "Diagnostic findings" : "Key takeaway"}</strong><p>${drivers.length ? `${drivers.slice(0, 3).map((item) => item.driver).join(", ")} are the leading contributors in this scope.` : "No downtime drivers were returned."}</p></section><div data-adaptive-drivers></div></section>`;
        renderDriversTable(host.querySelector("[data-adaptive-drivers]"), diagnostics, options);
    }

    function renderAdaptiveRows(host, payload, intent, language, templateCode) {
        const titles = {
            performance_overview: "Performance overview", equipment_detail: "Equipment detail",
            entity_comparison: "Entity comparison", period_comparison: "Period comparison",
            trend_analysis: "Trend analysis", ranking: "Ranking", affected_equipment: "Affected equipment",
            downtime_events: "Downtime events", repeated_failures: "Repeated failures",
            comment_analysis: "Comment analysis", smcs_breakdown: "SMCS breakdown",
            generic_analytical: "Analytical result",
        };
        host.innerHTML = `<section class="ai-adaptive-response ai-adaptive-response--wide"><header><strong>${escapeHtml(titles[templateCode] || "Analytical result")}</strong></header><div class="ai-analysis-context__chips">${adaptiveContextMarkup(intent, language)}</div>${analyticalRowsTable(payload.rows, templateCode)}</section>`;
    }

    const adaptiveResponseRenderers = {
        single_kpi: renderAdaptivePrimary,
        downtime_drivers: renderAdaptiveDiagnostics,
        root_cause_analysis: renderAdaptiveDiagnostics,
        performance_overview: renderAdaptiveRows,
        equipment_detail: renderAdaptiveRows,
        entity_comparison: renderAdaptiveRows,
        period_comparison: renderAdaptiveRows,
        trend_analysis: renderAdaptiveRows,
        ranking: renderAdaptiveRows,
        affected_equipment: renderAdaptiveRows,
        downtime_events: renderAdaptiveRows,
        repeated_failures: renderAdaptiveRows,
        comment_analysis: renderAdaptiveRows,
        smcs_breakdown: renderAdaptiveRows,
        generic_analytical: renderAdaptiveRows,
    };

    function renderMessageArtifacts(root, state, message, host) {
        const snapshotArtifact = responseSnapshotForMessage(message);
        const payload = snapshotArtifact?.payload;
        if (!payload) return;

        const intent = payload.intent || payload.semantic_request || {};
        const question = state.conversationHistory.find((item) => item.id === message.parent_message_id)?.content || "";
        const language = detectedLanguage(question);
        host.classList.add("ai-message-analytical-result");
        host.replaceChildren();
        const content = document.createElement("div");
        const secondary = document.createElement("div");
        secondary.className = "ai-message-artifact-actions";
        host.append(content, secondary);

        let expanded = false;
        const openDriver = async (driver) => {
            if (!driver || !window.Mining360DowntimeExplorer) return;
            state.activeInteractiveView = {
                type: "root_cause_explorer",
                sourceMessageId: message.id,
                intent: JSON.parse(JSON.stringify(intent)),
                navigation: JSON.parse(JSON.stringify(payload.navigation || {})),
                driver: driver.driver,
            };
            const explorer = document.getElementById("downtime-root-cause-explorer");
            host.appendChild(explorer);
            explorer.hidden = false;
            await window.Mining360DowntimeExplorer.open({
                action: "open_root_cause_explorer",
                selected_dimension: "downtime_driver",
                selected_value: driver.driver,
                current_context: {
                    kpi: intent.metric || "availability",
                    filters: JSON.parse(JSON.stringify(intent.filters || {})),
                },
                source_question: question,
                conversation_id: state.conversationId,
                report_id: payload.navigation?.report_id || "",
                source_message_id: message.id,
                source_artifact_id: snapshotArtifact.id,
            });
        };
        const diagnosticsOptions = {
            language,
            expanded,
            onSelectDriver: openDriver,
            onToggleExpanded: (value) => {
                expanded = value;
                renderAdaptiveDiagnostics(content, payload, intent, language, { ...diagnosticsOptions, expanded });
            },
            onShowPareto: () => {
                const pareto = document.createElement("div");
                pareto.className = "ai-inline-historical-pareto";
                content.after(pareto);
                renderDowntimeDiagnostics(pareto, payload.downtime_diagnostics || payload.availability_diagnostics, { intent, onSelectDriver: openDriver });
            },
        };
        const templateCode = responseTemplateCode(payload);
        if (templateCode === "legacy_availability_response") {
            const overview = document.createElement("div");
            const drivers = document.createElement("div");
            content.append(overview, drivers);
            renderAvailabilityOverview(overview, payload.availability_diagnostics, { intent, rows: payload.rows, language, resourceKnowledge: payload.resource_knowledge });
            renderDriversTable(drivers, payload.availability_diagnostics, diagnosticsOptions);
        } else if (templateCode === "powerbi_navigation") {
            content.innerHTML = '<section class="ai-adaptive-response"><strong>Power BI view ready</strong><p>Open the saved report context to continue.</p></section>';
        } else {
            const renderer = adaptiveResponseRenderers[templateCode] || adaptiveResponseRenderers.generic_analytical;
            renderer(content, payload, intent, language, templateCode === "downtime_drivers" || templateCode === "root_cause_analysis" ? diagnosticsOptions : templateCode);
        }

        const actions = payload.actions || payload.response_envelope?.actions || [];
        actions.filter((action) => action.code !== "open_powerbi").forEach((action) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "ai-text-action";
            button.textContent = action.label || String(action.code || "").replaceAll("_", " ");
            button.addEventListener("click", () => {
                const input = document.getElementById("ai-question");
                if (!input) return;
                input.value = button.textContent;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.focus();
            });
            secondary.appendChild(button);
        });

        if (payload.navigation?.report_id) {
            const powerbi = document.createElement("button");
            powerbi.type = "button";
            powerbi.textContent = "Open saved context in Power BI";
            powerbi.addEventListener("click", async () => {
                state.activeInteractiveView = {
                    type: "powerbi_preview",
                    sourceMessageId: message.id,
                    intent: JSON.parse(JSON.stringify(intent)),
                    navigation: JSON.parse(JSON.stringify(payload.navigation)),
                };
                state.currentIntent = state.activeInteractiveView.intent;
                state.currentNavigation = state.activeInteractiveView.navigation;
                const view = document.getElementById("ai-powerbi-section");
                host.appendChild(view);
                await openPowerBI(root, state, state.currentNavigation);
            });
            secondary.appendChild(powerbi);
        }
    }

    async function apiRequest(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                "X-CSRFToken": csrfToken(),
                ...(options.headers || {}),
            },
        });
        const payload = await response.json().catch(() => ({ ok: false, error: "Invalid server response." }));
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Request failed.");
        return payload;
    }

    function conversationUrl(root, id, suffix = "") {
        return `${root.dataset.conversationsUrl}${id}/${suffix}`;
    }

    function relativeActivity(value) {
        if (!value) return "No messages yet";
        const date = new Date(value);
        const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
        if (minutes < 1) return "Just now";
        if (minutes < 60) return `${minutes} min ago`;
        if (minutes < 1440) return `${Math.floor(minutes / 60)} h ago`;
        return date.toLocaleDateString();
    }

    function conversationPath(conversationId) {
        return conversationId ? `/ai/c/${conversationId}/` : "/ai/new/";
    }

    function conversationIdFromPath() {
        const match = window.location.pathname.match(/^\/ai\/c\/([0-9a-f-]+)\/?$/i);
        return match ? match[1] : "";
    }

    function updateConversationRoute(conversationId, { replace = false } = {}) {
        const method = replace ? "replaceState" : "pushState";
        const nextPath = conversationPath(conversationId);
        if (window.location.pathname !== nextPath) {
            window.history[method]({ conversationId: conversationId || "" }, "", nextPath);
        }
    }

    function closeConversationMenus() {
        document.querySelectorAll(".ai-conversation-item-menu[open], .ai-conversation-menu[open]").forEach((menu) => {
            menu.removeAttribute("open");
        });
    }

    function conversationGroup(value) {
        if (!value) return "Older";
        const activity = new Date(value);
        const today = new Date();
        const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        const startActivity = new Date(activity.getFullYear(), activity.getMonth(), activity.getDate());
        const days = Math.floor((startToday - startActivity) / 86400000);
        if (days <= 0) return "Today";
        if (days <= 7) return "Previous 7 days";
        return "Older";
    }

    function renderConversationList(root, state) {
        const list = document.getElementById("ai-conversation-list");
        const query = (document.getElementById("ai-conversation-search")?.value || "").trim().toLowerCase();
        const conversations = state.conversations.filter((item) => item.title.toLowerCase().includes(query));
        let lastGroup = "";
        list.innerHTML = conversations.length ? conversations.map((item) => {
            const group = conversationGroup(item.last_message_at || item.updated_at);
            const heading = group !== lastGroup ? `<div class="ai-conversation-group">${escapeHtml(group)}</div>` : "";
            lastGroup = group;
            return `${heading}
            <div class="ai-conversation-list-row ${item.id === state.conversationId ? "is-active" : ""}">
                <button type="button" class="ai-conversation-item" data-conversation-id="${item.id}" aria-current="${item.id === state.conversationId ? "page" : "false"}">
                    <span>${escapeHtml(item.title)}</span>
                    <small>${escapeHtml(relativeActivity(item.last_message_at))}</small>
                </button>
                <details class="ai-conversation-item-menu">
                    <summary aria-label="Actions for ${escapeHtml(item.title)}" title="Conversation actions">&#8943;</summary>
                    <div>
                        <button type="button" data-rename-conversation="${item.id}">Rename</button>
                        <button type="button" data-archive-conversation="${item.id}">Archive</button>
                        <button type="button" class="danger" data-delete-conversation="${item.id}">Delete</button>
                    </div>
                </details>
            </div>
        `; }).join("") : `<div class="ai-conversation-empty">No conversations found.</div>`;
        list.querySelectorAll("[data-conversation-id]").forEach((button) => {
            button.addEventListener("click", () => openConversation(root, state, button.dataset.conversationId));
        });
        list.querySelectorAll("[data-rename-conversation]").forEach((button) => {
            button.addEventListener("click", () => startInlineRename(state, button.dataset.renameConversation));
        });
        list.querySelectorAll("[data-delete-conversation]").forEach((button) => {
            button.addEventListener("click", () => deleteConversation(root, state, button.dataset.deleteConversation));
        });
        list.querySelectorAll("[data-archive-conversation]").forEach((button) => {
            button.addEventListener("click", () => archiveConversation(root, state, button.dataset.archiveConversation));
        });
        document.getElementById("ai-conversation-count").textContent = state.conversationCount;
        document.getElementById("ai-conversation-limit").textContent = state.conversationLimit;
        const newChat = document.getElementById("ai-new-conversation");
        if (newChat) {
            const atLimit = state.conversationCount >= state.conversationLimit;
            newChat.disabled = atLimit;
            newChat.title = atLimit
                ? `You have reached the limit of ${state.conversationLimit} active conversations. Delete or archive a conversation to create a new one.`
                : "New chat";
        }
    }

    async function loadConversationList(root, state) {
        const payload = await apiRequest(root.dataset.conversationsUrl);
        state.conversations = payload.results || [];
        state.conversationCount = payload.count || 0;
        state.conversationLimit = payload.max_active_conversations || 10;
        renderConversationList(root, state);
        return state.conversations;
    }

    function latestResponseSnapshot(messages) {
        for (let index = messages.length - 1; index >= 0; index -= 1) {
            const artifact = (messages[index].artifacts || []).find((item) => item.artifact_type === "response_snapshot");
            if (artifact?.payload) return { payload: artifact.payload, question: messages[index - 1]?.content || "" };
        }
        return null;
    }

    function clearAnalyticalResult(state) {
        window.Mining360DowntimeExplorer?.resetForNewPrompt();
        ["ai-availability-overview-content", "ai-drivers-content", "ai-downtime-content", "ai-powerbi-report-tabs"].forEach((id) => document.getElementById(id)?.replaceChildren());
        setHidden(document.getElementById("ai-availability-overview-section"), true);
        state.currentIntent = null;
        state.currentNavigation = null;
        state.currentDiagnostics = null;
        state.selectedDriver = "";
    }

    function restoreAnalyticalSnapshot(root, state, snapshot) {
        clearAnalyticalResult(state);
        if (!snapshot?.payload?.availability_diagnostics) return;
        const payload = snapshot.payload;
        const diagnostics = payload.availability_diagnostics;
        const intent = payload.intent || payload.semantic_request || {};
        const language = detectedLanguage(snapshot.question || "");
        const overview = document.getElementById("ai-availability-overview-content");
        const drivers = document.getElementById("ai-drivers-content");
        state.currentIntent = intent;
        state.currentNavigation = payload.navigation || null;
        state.currentDiagnostics = diagnostics;
        state.currentQuestion = snapshot.question;
        state.language = language;
        state.openDriver = async (driver) => {
            if (!driver || !window.Mining360DowntimeExplorer) return;
            state.selectedDriver = driver.driver;
            setAnalyticalView(state, "root_cause_explorer", { scroll: true });
            await window.Mining360DowntimeExplorer.open({
                action: "open_root_cause_explorer",
                selected_dimension: "downtime_driver",
                selected_value: driver.driver,
                current_context: { kpi: intent.metric || "availability", filters: intent.filters || {} },
                source_question: snapshot.question,
                conversation_id: state.conversationId,
                report_id: payload.navigation?.report_id || "",
            });
        };
        renderAvailabilityOverview(overview, diagnostics, { intent, rows: payload.rows, language, resourceKnowledge: payload.resource_knowledge });
        renderDriversTable(drivers, diagnostics, {
            language,
            expanded: false,
            onSelectDriver: state.openDriver,
            onToggleExpanded: (expanded) => {
                state.driversExpanded = expanded;
                renderDriversTable(drivers, diagnostics, { language, expanded, onSelectDriver: state.openDriver });
            },
            onShowPareto: () => {
                const host = document.getElementById("ai-downtime-content");
                host.replaceChildren();
                renderDowntimeDiagnostics(host, diagnostics, { intent, onSelectDriver: state.openDriver });
                setAnalyticalView(state, "pareto", { scroll: true });
            },
        });
        renderQuickActions(root, state, diagnostics, language);
        renderPowerBILauncher(root, state, language);
        setHidden(document.getElementById("ai-availability-overview-section"), false);
        setAnalyticalView(state, "summary");
    }

    async function openConversation(root, state, conversationId, { updateRoute = true, restoreScroll = true } = {}) {
        if (!conversationId) return;
        const thread = document.getElementById("ai-chat-thread");
        const scrollHost = document.getElementById("ai-message-scroll");
        if (state.conversationId && scrollHost) {
            state.scrollPositions[state.conversationId] = scrollHost.scrollTop;
        }
        thread.innerHTML = `<div class="ai-conversation-loading">Loading conversation...</div>`;
        const payload = await apiRequest(conversationUrl(root, conversationId, "messages/?page_size=50"));
        state.conversationId = conversationId;
        state.conversationHistory = payload.results || [];
        state.hasOlderMessages = Boolean(payload.has_more);
        state.nextBefore = payload.next_before;
        sessionStorage.setItem(conversationKey, conversationId);
        const composerInput = document.getElementById("ai-question");
        if (composerInput) {
            try { composerInput.value = localStorage.getItem(`mining360-ai-draft:${conversationId}`) || ""; } catch (error) { composerInput.value = ""; }
        }
        const conversation = payload.conversation;
        document.getElementById("ai-conversation-title").textContent = conversation.title;
        document.getElementById("ai-conversation-meta").textContent = `${conversation.last_agent_code ? conversation.last_agent_code.replaceAll("_", " ") + " · " : ""}${relativeActivity(conversation.last_message_at)}`;
        renderMessages(thread, state.conversationHistory, state);
        renderConversationList(root, state);
        if (updateRoute) updateConversationRoute(conversationId);
        if (scrollHost) {
            const savedPosition = restoreScroll ? state.scrollPositions[conversationId] : null;
            scrollHost.scrollTop = Number.isFinite(savedPosition) ? savedPosition : scrollHost.scrollHeight;
        }
        document.getElementById("ai-conversation-sidebar")?.classList.remove("is-open");
    }

    async function loadOlderMessages(root, state) {
        if (!state.conversationId || !state.hasOlderMessages || state.loadingOlder || !state.nextBefore) return;
        const thread = document.getElementById("ai-chat-thread");
        const scrollHost = document.getElementById("ai-message-scroll") || thread;
        state.loadingOlder = true;
        const previousHeight = scrollHost.scrollHeight;
        try {
            const payload = await apiRequest(conversationUrl(
                root,
                state.conversationId,
                `messages/?page_size=50&before=${encodeURIComponent(state.nextBefore)}`,
            ));
            state.conversationHistory = [...(payload.results || []), ...state.conversationHistory];
            state.hasOlderMessages = Boolean(payload.has_more);
            state.nextBefore = payload.next_before;
            renderMessages(thread, state.conversationHistory, state);
            scrollHost.scrollTop += scrollHost.scrollHeight - previousHeight;
        } finally {
            state.loadingOlder = false;
        }
    }

    function beginNewConversation(state, { updateRoute = true } = {}) {
        const input = document.getElementById("ai-question");
        const scrollHost = document.getElementById("ai-message-scroll");
        if (state.conversationId && scrollHost) state.scrollPositions[state.conversationId] = scrollHost.scrollTop;
        state.conversationId = "";
        state.conversationHistory = [];
        state.hasOlderMessages = false;
        state.nextBefore = null;
        sessionStorage.removeItem(conversationKey);
        document.getElementById("ai-conversation-title").textContent = "New conversation";
        document.getElementById("ai-conversation-meta").textContent = "Mining 360 AI";
        renderMessages(document.getElementById("ai-chat-thread"), [], state);
        renderConversationList(state.root, state);
        if (input) {
            try { input.value = localStorage.getItem("mining360-ai-draft:new") || ""; } catch (error) { input.value = ""; }
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
        }
        if (updateRoute) updateConversationRoute("");
        document.getElementById("ai-conversation-sidebar")?.classList.remove("is-open");
    }

    function startInlineRename(state, conversationId = state.conversationId) {
        const conversation = state.conversations.find((item) => item.id === conversationId);
        if (!conversation) return;
        if (conversationId !== state.conversationId) {
            openConversation(state.root, state, conversationId).then(() => startInlineRename(state, conversationId));
            return;
        }
        closeConversationMenus();
        const title = document.getElementById("ai-conversation-title");
        const form = document.getElementById("ai-conversation-rename-form");
        const input = document.getElementById("ai-conversation-title-input");
        if (!title || !form || !input) return;
        title.hidden = true;
        form.hidden = false;
        input.value = conversation.title;
        input.focus();
        input.select();
    }

    function cancelInlineRename() {
        document.getElementById("ai-conversation-title")?.removeAttribute("hidden");
        const form = document.getElementById("ai-conversation-rename-form");
        if (form) form.hidden = true;
    }

    async function saveInlineRename(root, state) {
        if (!state.conversationId) return;
        const input = document.getElementById("ai-conversation-title-input");
        const title = (input?.value || "").replace(/\s+/g, " ").trim();
        if (!title) {
            input?.setCustomValidity("Conversation title is required.");
            input?.reportValidity();
            return;
        }
        input?.setCustomValidity("");
        await apiRequest(conversationUrl(root, state.conversationId), {
            method: "PATCH",
            body: JSON.stringify({ title }),
        });
        cancelInlineRename();
        await loadConversationList(root, state);
        document.getElementById("ai-conversation-title").textContent = title;
    }

    async function deleteConversation(root, state, conversationId = state.conversationId) {
        if (!conversationId || !window.confirm("Delete this conversation?\n\nThis will remove the conversation from your chat history.")) return;
        try {
            await apiRequest(conversationUrl(root, conversationId), { method: "DELETE" });
            if (state.conversationId === conversationId) {
                sessionStorage.removeItem(conversationKey);
                state.conversationId = "";
            }
            const remaining = await loadConversationList(root, state);
            if (state.conversationId) {
                renderConversationList(root, state);
            } else if (remaining[0]) {
                await openConversation(root, state, remaining[0].id);
            } else {
                beginNewConversation(state);
            }
        } catch (error) {
            window.alert(error.message);
        }
    }

    async function archiveConversation(root, state, conversationId = state.conversationId) {
        if (!conversationId) return;
        try {
            await apiRequest(conversationUrl(root, conversationId, "archive/"), { method: "POST", body: "{}" });
            if (state.conversationId === conversationId) {
                sessionStorage.removeItem(conversationKey);
                state.conversationId = "";
            }
            const remaining = await loadConversationList(root, state);
            if (state.conversationId) renderConversationList(root, state);
            else if (remaining[0]) await openConversation(root, state, remaining[0].id);
            else beginNewConversation(state);
        } catch (error) {
            window.alert(error.message);
        }
    }

    async function retryMessage(state, messageId) {
        if (!state?.root || !state.conversationId || !messageId || state.activeExecution.isLoading) return;
        state.activeExecution.isLoading = true;
        try {
            await apiRequest(conversationUrl(state.root, state.conversationId, `messages/${messageId}/retry/`), { method: "POST", body: "{}" });
            await openConversation(state.root, state, state.conversationId);
            await loadConversationList(state.root, state);
        } catch (error) {
            window.alert(error.message);
        } finally {
            state.activeExecution.isLoading = false;
        }
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
            if (error.authenticationRequired && error.connectUrl) {
                const connect = document.createElement("a");
                connect.className = "button secondary ai-powerbi-connect";
                connect.href = error.connectUrl;
                connect.textContent = "Connect corporate account";
                status.append(document.createTextNode(" "), connect);
            }
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
        if (state.activeExecution.isLoading) return;
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
        state.activeExecution = { isLoading: true, clientMessageId: "", question };
        const sendButton = document.getElementById("ai-run-question");
        if (sendButton) {
            sendButton.disabled = true;
            sendButton.classList.add("is-loading");
            sendButton.setAttribute("aria-label", "Question en cours d’analyse");
        }

        const clientMessageId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        state.activeExecution.clientMessageId = clientMessageId;
        state.conversationHistory.push({ id: clientMessageId, role: "user", content: question, status: "completed" });
        renderMessages(chatThread, state.conversationHistory, state);
        input.value = "";
        try { localStorage.removeItem(`mining360-ai-draft:${state.conversationId || "new"}`); } catch (error) { /* optional */ }
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
                    conversation_id: state.conversationId,
                    client_message_id: clientMessageId,
                    input_metadata: inputMetadata,
                    agent_selection: document.getElementById("ai-agent-selection")?.value || "auto",
                }),
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Query failed.");
            }

            await openConversation(root, state, payload.conversation_id || state.conversationId);
            await loadConversationList(root, state);
            return;

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
            if (state.conversationId) {
                try {
                    await openConversation(root, state, state.conversationId);
                    await loadConversationList(root, state);
                } catch (reloadError) {
                    state.conversationHistory.push({ role: "assistant", content: `I could not process the question: ${err.message}`, status: "failed" });
                    renderMessages(chatThread, state.conversationHistory, state);
                }
            }
            scrollIntoConversationView(chatThread.lastElementChild);
        } finally {
            state.activeExecution = { isLoading: false, clientMessageId: "", question: "" };
            if (sendButton) {
                sendButton.disabled = false;
                sendButton.classList.remove("is-loading");
                sendButton.setAttribute("aria-label", "Send question");
            }
            setHidden(loading, true);
            input.focus({ preventScroll: true });
        }
    }

    document.addEventListener("DOMContentLoaded", async function () {
        const root = document.querySelector("[data-ai-ask-url]");
        if (!root) {
            return;
        }
        const button = document.getElementById("ai-run-question");
        const input = document.getElementById("ai-question");
        const chatThread = document.getElementById("ai-chat-thread");
        const state = {
            root,
            conversationHistory: [],
            conversations: [],
            conversationCount: 0,
            conversationLimit: 10,
            conversationId: conversationIdFromPath() || sessionStorage.getItem(conversationKey) || "",
            powerbi: null,
            powerbiEvents: [],
            activeExecution: { isLoading: false, clientMessageId: "", question: "" },
            activeInteractiveView: null,
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
            hasOlderMessages: false,
            nextBefore: null,
            loadingOlder: false,
            scrollPositions: {},
        };

        const storedFocusMode = localStorage.getItem(focusModeKey) || "compact";
        if (storedFocusMode !== "expanded") {
            document.body.classList.add("nav-collapsed");
            localStorage.setItem("mining360ia.navCollapsed", "1");
        }
        document.body.classList.toggle("ai-full-focus", storedFocusMode === "full");
        document.body.classList.toggle("ai-conversations-collapsed", localStorage.getItem(conversationSidebarKey) === "1");

        try {
            const conversations = await loadConversationList(root, state);
            const isNewRoute = window.location.pathname.replace(/\/$/, "") === "/ai/new";
            const selected = !isNewRoute && (conversations.find((item) => item.id === state.conversationId) || conversations[0]);
            if (selected) {
                await openConversation(root, state, selected.id, { updateRoute: true, restoreScroll: false });
            } else {
                beginNewConversation(state, { updateRoute: window.location.pathname !== "/ai/" });
            }
        } catch (error) {
            chatThread.innerHTML = `<div class="alert">${escapeHtml(error.message || "Unable to load conversations.")}</div>`;
        }
        updateComposerClearance();

        document.getElementById("ai-new-conversation")?.addEventListener("click", async () => {
            if (state.conversationCount >= state.conversationLimit) return;
            beginNewConversation(state);
        });
        let searchTimer = null;
        document.getElementById("ai-conversation-search")?.addEventListener("input", () => {
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(() => renderConversationList(root, state), 120);
        });
        document.getElementById("ai-open-conversations")?.addEventListener("click", () => document.getElementById("ai-conversation-sidebar")?.classList.add("is-open"));
        document.getElementById("ai-close-conversations")?.addEventListener("click", () => document.getElementById("ai-conversation-sidebar")?.classList.remove("is-open"));
        document.getElementById("ai-toggle-conversations")?.addEventListener("click", () => {
            const collapsed = !document.body.classList.contains("ai-conversations-collapsed");
            document.body.classList.toggle("ai-conversations-collapsed", collapsed);
            localStorage.setItem(conversationSidebarKey, collapsed ? "1" : "0");
            const button = document.getElementById("ai-toggle-conversations");
            button?.setAttribute("aria-label", collapsed ? "Show conversations" : "Collapse conversations");
            button?.setAttribute("title", collapsed ? "Show conversations" : "Collapse conversations");
        });
        document.getElementById("ai-focus-toggle")?.addEventListener("click", () => {
            const full = !document.body.classList.contains("ai-full-focus");
            document.body.classList.toggle("ai-full-focus", full);
            localStorage.setItem(focusModeKey, full ? "full" : "compact");
            const button = document.getElementById("ai-focus-toggle");
            button?.setAttribute("aria-label", full ? "Exit full focus" : "Enter full focus");
            button?.setAttribute("title", full ? "Exit full focus" : "Enter full focus");
        });
        document.getElementById("ai-rename-conversation")?.addEventListener("click", () => startInlineRename(state));
        document.getElementById("ai-archive-conversation")?.addEventListener("click", () => archiveConversation(root, state));
        document.getElementById("ai-delete-conversation")?.addEventListener("click", () => deleteConversation(root, state));
        document.getElementById("ai-conversation-rename-form")?.addEventListener("submit", (event) => {
            event.preventDefault();
            saveInlineRename(root, state).catch((error) => window.alert(error.message));
        });
        document.getElementById("ai-cancel-rename")?.addEventListener("click", cancelInlineRename);
        document.getElementById("ai-conversation-title-input")?.addEventListener("keydown", (event) => {
            if (event.key === "Escape") cancelInlineRename();
        });
        document.getElementById("ai-show-technical-details")?.addEventListener("click", () => {
            closeConversationMenus();
            const details = document.querySelector(".ai-technical-details");
            if (!details) return;
            details.hidden = false;
            details.open = true;
            details.scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
        const chatScrollHost = document.getElementById("ai-message-scroll") || chatThread;
        chatScrollHost?.addEventListener("scroll", () => {
            if (chatScrollHost.scrollTop < 80) loadOlderMessages(root, state).catch(() => {});
            const awayFromLatest = chatScrollHost.scrollHeight - chatScrollHost.scrollTop - chatScrollHost.clientHeight > 220;
            setHidden(document.getElementById("ai-jump-latest"), !awayFromLatest);
        });
        document.getElementById("ai-jump-latest")?.addEventListener("click", () => {
            chatScrollHost?.scrollTo({ top: chatScrollHost.scrollHeight, behavior: "smooth" });
        });
        window.addEventListener("popstate", () => {
            const routeConversationId = conversationIdFromPath();
            if (routeConversationId) {
                openConversation(root, state, routeConversationId, { updateRoute: false }).catch(() => beginNewConversation(state, { updateRoute: false }));
            } else {
                beginNewConversation(state, { updateRoute: false });
            }
        });
        let contextSaveTimer = null;
        window.addEventListener("mining360:analytical-context", (event) => {
            if (!state.conversationId) return;
            window.clearTimeout(contextSaveTimer);
            contextSaveTimer = window.setTimeout(() => {
                apiRequest(conversationUrl(root, state.conversationId, "context/"), {
                    method: "PATCH",
                    body: JSON.stringify({ active_analysis: event.detail?.active_analysis || {} }),
                }).catch(() => {});
            }, 250);
        });
        const draftKey = () => `mining360-ai-draft:${state.conversationId || "new"}`;
        input?.addEventListener("input", () => {
            try { localStorage.setItem(draftKey(), input.value); } catch (error) { /* optional */ }
        });
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
        document.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                document.getElementById("ai-conversation-sidebar")?.classList.add("is-open");
                document.getElementById("ai-conversation-search")?.focus();
            }
            if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "o") {
                event.preventDefault();
                if (state.conversationCount < state.conversationLimit) beginNewConversation(state);
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
