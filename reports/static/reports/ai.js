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

    function notifySafeError(messageEn, messageFr) {
        window.alert(chatLanguage() === "fr" ? messageFr : messageEn);
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
            const rolling = raw.match(/^last (\d{1,3}) months?$/i);
            if (rolling) return `Last ${rolling[1]} Months`;
            const range = raw.match(/^(20\d{2})-(0[1-9]|1[0-2])\/(20\d{2})-(0[1-9]|1[0-2])$/);
            if (range) {
                const start = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" })
                    .format(new Date(`${range[1]}-${range[2]}-01T00:00:00Z`));
                const end = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" })
                    .format(new Date(`${range[3]}-${range[4]}-01T00:00:00Z`));
                return `${start} to ${end}`;
            }
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
                    <strong>${Number(diagnostics.total_downtime_hours || 0).toLocaleString("en-GB", { maximumFractionDigits: 2 })} h</strong>
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
                        <title>${escapeHtml(item.driver)}: ${hours.toLocaleString("en-GB", { maximumFractionDigits: 2 })} h</title>
                        <rect x="${(x - barWidth / 2).toFixed(1)}" y="${y.toFixed(1)}"
                              width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"
                              rx="2" class="ai-pareto-bar"></rect>
                        <text x="${x.toFixed(1)}" y="${Math.max(y - 7, 14).toFixed(1)}"
                              class="ai-pareto-hours" text-anchor="middle">${hours.toLocaleString("en-GB", { maximumFractionDigits: 0 })}</text>
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
                    <text x="${left - 9}" y="${y + 4}" text-anchor="end" class="ai-pareto-axis">${(maxHours * ratio).toLocaleString("en-GB", { maximumFractionDigits: 0 })}</text>
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
                notifySafeError("Downtime drivers are temporarily unavailable. Please retry.", "Les downtime drivers sont momentanément indisponibles. Veuillez réessayer.");
            }
        });
        body.appendChild(card);
    }

    function chatLanguage() {
        return String(document.documentElement.lang || navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en";
    }

    function suggestionQuestion(suggestion, values = {}) {
        let question = suggestion.question || "";
        Object.entries(values).forEach(([key, value]) => {
            question = question.replaceAll(`{${key}}`, String(value || ""));
        });
        return question;
    }

    function recordSuggestionEvent(suggestion, state, eventType, outcome = "") {
        return apiRequest("/api/ai/chat/suggestions/events/", {
            method: "POST",
            body: JSON.stringify({
                suggestion_code: suggestion.code,
                conversation_id: state.conversationId || "",
                event_type: eventType,
                outcome,
            }),
        }).catch(() => {});
    }

    function submitCertifiedSuggestion(suggestion, state, guidedValues = {}) {
        const input = document.getElementById("ai-question");
        if (!input || state.activeExecution.isLoading) return;
        const question = suggestionQuestion(suggestion, guidedValues).trim();
        if (!question) return;
        const requestId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        state.pendingSubmission = {
            source: "starter_suggestion",
            suggestion_code: suggestion.code,
            guided_values: guidedValues,
            idempotency_key: `suggestion:${suggestion.code}:${requestId}`,
        };
        input.value = question;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        recordSuggestionEvent(suggestion, state, "suggestion_clicked", "submitted");
        runQuestion(state.root, state);
    }

    function openGuidedSuggestion(suggestion, state) {
        const language = chatLanguage();
        const dialog = document.createElement("dialog");
        dialog.className = "ai-guided-suggestion";
        const fields = (suggestion.guided_inputs || []).map((field) => {
            const label = field[language === "fr" ? "label_fr" : "label_en"] || field.code;
            if (field.type === "authorized_entity_select") {
                return `<label><span>${escapeHtml(label)}</span><select name="${escapeHtml(field.code)}" ${field.required ? "required" : ""}><option value="">${language === "fr" ? "Sélectionner" : "Select"}</option>${(field.options || []).map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
            }
            return `<label><span>${escapeHtml(label)}</span><input name="${escapeHtml(field.code)}" type="text" ${field.required ? "required" : ""} autocomplete="off"></label>`;
        }).join("");
        dialog.innerHTML = `<form method="dialog"><header><strong>${escapeHtml(suggestion.label)}</strong><button type="button" data-guided-close aria-label="${language === "fr" ? "Fermer" : "Close"}">×</button></header><div class="ai-guided-suggestion__fields">${fields}</div><footer><button type="button" data-guided-cancel>${language === "fr" ? "Annuler" : "Cancel"}</button><button type="submit">${language === "fr" ? "Lancer" : "Run"}</button></footer></form>`;
        document.body.appendChild(dialog);
        const close = () => { dialog.close(); dialog.remove(); };
        dialog.querySelector("[data-guided-close]")?.addEventListener("click", close);
        dialog.querySelector("[data-guided-cancel]")?.addEventListener("click", close);
        dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
        dialog.querySelector("form")?.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!event.currentTarget.reportValidity()) return;
            const values = Object.fromEntries(new FormData(event.currentTarget).entries());
            recordSuggestionEvent(suggestion, state, "guided_flow_completed", "submitted");
            close();
            submitCertifiedSuggestion(suggestion, state, values);
        });
        recordSuggestionEvent(suggestion, state, "guided_flow_opened", "opened");
        dialog.showModal();
        dialog.querySelector("select, input")?.focus();
    }

    async function renderCertifiedEmptyState(container, state) {
        const requestId = (state.suggestionsRequestId || 0) + 1;
        state.suggestionsRequestId = requestId;
        const language = chatLanguage();
        container.innerHTML = `<div class="ai-chat-empty-state"><strong>Mining 360 AI</strong><p>${language === "fr" ? "Interrogez votre flotte autorisée, vos données de performance, vos rapports et les Best Practices validées." : "Ask about your authorized fleet, performance data, reports and validated Mining Best Practices."}</p><div class="ai-empty-prompts" aria-live="polite"><span>${language === "fr" ? "Chargement des suggestions disponibles…" : "Loading available suggestions…"}</span></div></div>`;
        try {
            const params = new URLSearchParams({ language });
            if (state.conversationId) params.set("conversation_id", state.conversationId);
            const payload = await apiRequest(`/api/ai/chat/suggestions/?${params}`);
            if (state.suggestionsRequestId !== requestId || state.conversationHistory.length) return;
            const host = container.querySelector(".ai-empty-prompts");
            const suggestions = payload.suggestions || [];
            if (!suggestions.length) {
                host.innerHTML = `<p>${language === "fr" ? "Les capacités disponibles sont actuellement limitées. Demandez-moi ce que je peux faire." : "Available capabilities are currently limited. Ask me what I can do."}</p>`;
                return;
            }
            host.innerHTML = suggestions.map((suggestion) => `<button type="button" data-certified-suggestion="${escapeHtml(suggestion.code)}"><strong>${escapeHtml(suggestion.label)}</strong>${suggestion.subtitle ? `<span>${escapeHtml(suggestion.subtitle)}</span>` : ""}</button>`).join("");
            host.querySelectorAll("[data-certified-suggestion]").forEach((button) => {
                const suggestion = suggestions.find((item) => item.code === button.dataset.certifiedSuggestion);
                button.addEventListener("click", () => {
                    if (!suggestion) return;
                    if (suggestion.action_type === "GUIDED_QUESTION") openGuidedSuggestion(suggestion, state);
                    else submitCertifiedSuggestion(suggestion, state);
                });
            });
        } catch (error) {
            if (state.suggestionsRequestId !== requestId) return;
            const host = container.querySelector(".ai-empty-prompts");
            if (host) host.innerHTML = `<p>${language === "fr" ? "Les suggestions ne sont pas disponibles pour le moment. Vous pouvez saisir votre question ci-dessous." : "Suggestions are temporarily unavailable. You can still type your question below."}</p>`;
        }
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
            renderCertifiedEmptyState(container, state);
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
                    ${message.role === "assistant" && message.message_type === "analytical_result" ? `<small class="ai-saved-result">Saved result · Calculated ${escapeHtml(new Date(message.created_at).toLocaleString("en-GB"))}</small>` : ""}
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

    function renderFleetPerformance(host, payload, intent, language, templateCode, message) {
        const performance = payload.fleet_performance || {};
        const metrics = Array.isArray(performance.metrics) ? performance.metrics : (payload.metrics || []);
        const coverage = performance.coverage || {};
        const coverageValue = Number(coverage.coverage_percentage);
        const coverageLabel = Number.isFinite(coverageValue)
            ? `${localNumber(coverageValue * 100, language)}%`
            : "Not available";
        const title = {
            fleet_performance_overview: "Fleet Performance",
            reliability_overview: "Reliability",
            multi_kpi_summary: "Performance KPIs",
            planned_unplanned_analysis: "Planned / Unplanned Downtime",
            fleet_performance_comparison: "Fleet Performance Comparison",
            fleet_performance_period_comparison: "Period Comparison",
            fleet_performance_trend: "Fleet Performance Trend",
            fleet_performance_ranking: "Fleet Performance Ranking",
            equipment_performance_detail: "Equipment Performance",
            component_analysis: "Component Analysis",
            pm_analysis: "PM Analysis",
            smu_tracking: "SMU Tracking",
            fleet_performance_benchmark: "Fleet Performance Benchmark",
        }[templateCode] || "Fleet Performance";
        const cards = metrics.map((metric) => `<article><span>${escapeHtml(metric.label || metric.code)}</span><strong>${escapeHtml(metric.formatted_value || "Not available")}</strong></article>`).join("");
        const rows = Array.isArray(performance.rows) ? performance.rows : (payload.rows || []);
        const table = rows.length > 1 ? analyticalRowsTable(rows, templateCode) : "";
        const performanceArtifact = (message?.artifacts || []).find((item) => item.artifact_type === "fleet_performance_analysis");
        const downloadEligible = !payload.action_eligibility || (payload.action_eligibility.eligible || []).includes("download_excel");
        host.innerHTML = `<section class="ai-adaptive-response ai-adaptive-response--wide ai-fleet-performance"><header><div><small>Machine Performance</small><strong>${escapeHtml(title)}</strong></div>${performanceArtifact && downloadEligible ? '<button type="button" class="ai-fleet-download">Download Excel</button>' : ""}</header><div class="ai-analysis-context__chips">${adaptiveContextMarkup(intent, language)}</div><div class="ai-secondary-metrics ai-fleet-performance-metrics">${cards}</div>${coverage.fleet_equipment == null ? "" : `<div class="ai-performance-coverage"><span>Data coverage</span><strong>${escapeHtml(coverageLabel)}</strong><small>${escapeHtml(coverage.equipment_with_data)} / ${escapeHtml(coverage.fleet_equipment)} equipment</small></div>`}${table}</section>`;
        const download = host.querySelector(".ai-fleet-download");
        download?.addEventListener("click", async () => {
            download.disabled = true;
            try {
                const result = await apiRequest("/api/performance/exports/", { method: "POST", body: JSON.stringify({ artifact_id: performanceArtifact.id, export_type: "fleet_performance_excel" }) });
                window.location.assign(result.download_url);
            } catch (error) {
                notifySafeError("The export service is temporarily unavailable.", "Le service d’export est momentanément indisponible.");
            } finally { download.disabled = false; }
        });
    }

    function renderFleetInventory(host, payload, message, language) {
        const fleet = payload.fleet_inventory || {};
        const allRows = Array.isArray(fleet.rows) ? fleet.rows : [];
        const fleetArtifact = (message.artifacts || []).find((item) => item.artifact_type === "fleet_equipment_table");
        const state = { query: "", model: fleet.context?.model || "", page: 1, pageSize: 25 };
        const downloadEligible = !payload.action_eligibility || (payload.action_eligibility.eligible || []).includes("download_excel");
        host.innerHTML = `<section class="ai-adaptive-response ai-fleet-inventory"><header><div><small>Machine Performance · Fleet Inventory</small><strong>${escapeHtml(fleet.context?.site || "Fleet")}</strong></div><div class="ai-fleet-metrics"><span><b>${escapeHtml(fleet.summary?.equipment_count ?? allRows.length)}</b> Equipment</span><span><b>${escapeHtml(fleet.summary?.model_count ?? 0)}</b> Models</span></div></header><div class="ai-fleet-models"></div><div class="ai-fleet-toolbar"><label><span class="sr-only">Search fleet</span><input type="search" placeholder="Search equipment or serial number"></label><label><span class="sr-only">Filter by Model</span><select><option value="">All models</option></select></label>${downloadEligible ? '<button type="button" class="ai-fleet-download">Download Excel</button>' : ""}</div><div class="ai-fleet-table-host"></div><footer><span class="ai-fleet-count"></span><label>Rows <select class="ai-fleet-page-size"><option>25</option><option>50</option><option>100</option></select></label><div class="ai-fleet-pager"><button type="button" data-page="previous" aria-label="Previous page">‹</button><span></span><button type="button" data-page="next" aria-label="Next page">›</button></div></footer></section>`;
        const section = host.querySelector(".ai-fleet-inventory");
        const modelSelect = section.querySelector(".ai-fleet-toolbar select");
        (fleet.by_model || []).forEach((item) => {
            const option = document.createElement("option");
            option.value = item.model;
            option.textContent = `${item.model} (${item.equipment_count})`;
            option.selected = String(item.model) === String(state.model);
            modelSelect.appendChild(option);
        });
        section.querySelector(".ai-fleet-models").innerHTML = (fleet.by_model || []).slice(0, 12).map((item) => `<button type="button" data-model="${escapeHtml(item.model)}"><strong>${escapeHtml(item.model)}</strong><span>${escapeHtml(item.equipment_count)}</span></button>`).join("");
        const draw = () => {
            const query = state.query.toLowerCase();
            const filtered = allRows.filter((row) => (!state.model || String(row.model) === state.model) && (!query || [row.equipment, row.model, row.serial_number].some((value) => String(value || "").toLowerCase().includes(query))));
            const pages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
            state.page = Math.min(state.page, pages);
            const start = (state.page - 1) * state.pageSize;
            const visible = filtered.slice(start, start + state.pageSize);
            section.querySelector(".ai-fleet-table-host").innerHTML = `<div class="ai-adaptive-table-wrap"><table class="ai-adaptive-table"><thead><tr><th>Site</th><th>Equipment</th><th>Model</th><th>Serial Number</th></tr></thead><tbody>${visible.map((row) => `<tr><td data-label="Site">${escapeHtml(row.site || "Not available")}</td><td data-label="Equipment">${escapeHtml(row.equipment || "Not available")}</td><td data-label="Model">${escapeHtml(row.model || "Unknown Model")}</td><td data-label="Serial Number">${escapeHtml(row.serial_number || "Not available")}</td></tr>`).join("")}</tbody></table></div>`;
            section.querySelector(".ai-fleet-count").textContent = `${filtered.length} equipment`;
            section.querySelector(".ai-fleet-pager span").textContent = `${state.page} / ${pages}`;
            section.querySelector('[data-page="previous"]').disabled = state.page <= 1;
            section.querySelector('[data-page="next"]').disabled = state.page >= pages;
        };
        section.querySelector('input[type="search"]').addEventListener("input", (event) => { state.query = event.target.value; state.page = 1; draw(); });
        modelSelect.addEventListener("change", (event) => { state.model = event.target.value; state.page = 1; draw(); });
        section.querySelectorAll("[data-model]").forEach((button) => button.addEventListener("click", () => { state.model = button.dataset.model; modelSelect.value = state.model; state.page = 1; draw(); }));
        section.querySelector(".ai-fleet-page-size").addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; draw(); });
        section.querySelector('[data-page="previous"]').addEventListener("click", () => { state.page -= 1; draw(); });
        section.querySelector('[data-page="next"]').addEventListener("click", () => { state.page += 1; draw(); });
        const download = section.querySelector(".ai-fleet-download");
        if (download) download.disabled = !fleetArtifact;
        download?.addEventListener("click", async () => {
            if (!fleetArtifact) return;
            download.disabled = true;
            try {
                const result = await apiRequest("/api/fleet/exports/", { method: "POST", body: JSON.stringify({ artifact_id: fleetArtifact.id, export_type: "fleet_excel" }) });
                window.location.assign(result.download_url);
            } catch (error) {
                notifySafeError("The export service is temporarily unavailable.", "Le service d’export est momentanément indisponible.");
            } finally { download.disabled = false; }
        });
        draw();
    }

    function renderEquipmentMasterDetail(host, payload) {
        const machine = payload.equipment_detail?.machine || {};
        const fields = [["Site", machine.site], ["Equipment", machine.equipment], ["Model", machine.model], ["Serial Number", machine.serial_number], ["Equipment Family", machine.equipment_family], ["Brand", machine.brand], ["Equipment ID", machine.equipment_id], ["Status", machine.status_display], ["SMU", machine.smu ?? "Not available"]];
        host.innerHTML = `<section class="ai-adaptive-response ai-equipment-detail"><header><small>Machine Performance · Equipment Details</small><strong>${escapeHtml(machine.equipment || machine.serial_number || "Equipment")}</strong></header><dl>${fields.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "Not available")}</dd></div>`).join("")}</dl></section>`;
    }

    function renderCapabilityCatalog(host, payload, state) {
        const catalog = payload.capability_catalog || {};
        const categories = Array.isArray(catalog.categories) ? catalog.categories : [];
        const language = catalog.language || "en";
        host.innerHTML = `<section class="ai-capability-catalog"><header><small>Mining 360 AI</small><strong>${language === "fr" ? "Capacités disponibles" : "Available capabilities"}</strong></header><div class="ai-capability-catalog__grid">${categories.map((category) => `<section class="ai-capability-category"><h3>${escapeHtml(category.name)}</h3>${(category.capabilities || []).map((capability) => `<article><div><strong>${escapeHtml(capability.name)}</strong>${capability.preview_only ? `<span>${language === "fr" ? "Aperçu admin · certification requise" : "Admin preview · certification required"}</span>` : (capability.readiness_status === "Limited" ? `<span>${language === "fr" ? "Limité" : "Limited"}</span>` : "")}</div><p>${escapeHtml(capability.description)}</p><div class="ai-capability-examples">${(capability.examples || []).map((example) => `<button type="button" data-capability-example="${escapeHtml(example)}" ${capability.preview_only ? "disabled" : ""}>${escapeHtml(example)}</button>`).join("")}</div></article>`).join("")}</section>`).join("")}</div></section>`;
        host.querySelectorAll("[data-capability-example]").forEach((button) => {
            button.addEventListener("click", () => {
                const input = document.getElementById("ai-question");
                if (!input) return;
                input.value = button.dataset.capabilityExample || "";
                input.dispatchEvent(new Event("input", { bubbles: true }));
                state.pendingSubmission = {
                    source: "capability_example",
                    idempotency_key: `capability:${window.crypto?.randomUUID?.() || Date.now()}`,
                };
                runQuestion(state.root, state);
            });
        });
    }

    function renderAnswerability(host, payload) {
        const decision = payload.answerability || {};
        const language = payload.content?.language || "en";
        const available = Array.isArray(payload.available_information) ? payload.available_information : [];
        const statusLabels = {
            ANSWERABLE: { fr: "Disponible", en: "Available" },
            NEEDS_CLARIFICATION: { fr: "Précision requise", en: "Clarification required" },
            INFORMATION_NOT_IN_CONFIGURED_SOURCES: { fr: "Non disponible dans les sources configurées", en: "Not available in configured sources" },
            FIELD_AVAILABLE_BUT_VALUE_MISSING: { fr: "Valeur non renseignée", en: "Value not recorded" },
            ENTITY_NOT_FOUND: { fr: "Équipement introuvable", en: "Equipment not found" },
            ACCESS_RESTRICTED: { fr: "Accès restreint", en: "Access restricted" },
            CAPABILITY_NOT_CONFIGURED: { fr: "Analyse non configurée", en: "Analysis not configured" },
            TEMPORARILY_UNAVAILABLE: { fr: "Source momentanément indisponible", en: "Source temporarily unavailable" },
            INSUFFICIENT_EVIDENCE: { fr: "Éléments insuffisants", en: "Insufficient evidence" },
            CONFLICTING_SOURCES: { fr: "Sources contradictoires", en: "Conflicting sources" },
            UNSUPPORTED_ACTION: { fr: "Action non disponible", en: "Action unavailable" },
            OUT_OF_SCOPE: { fr: "Hors périmètre configuré", en: "Outside configured scope" },
            LOW_CONFIDENCE: { fr: "Correspondance incertaine", en: "Uncertain match" },
        };
        const statusLabel = statusLabels[decision.status]?.[language] || (language === "fr" ? "Couverture non disponible" : "Coverage unavailable");
        const labels = {
            site: "Site", equipment: "Equipment", model: "Model", serial_number: "Serial Number",
            equipment_family: "Equipment Family", brand: "Brand", equipment_id: "Equipment ID", smu: "SMU",
        };
        host.innerHTML = `<section class="ai-answerability-card" data-answerability-status="${escapeHtml(decision.status || "")}"><header><strong>${language === "fr" ? "Couverture des données" : "Data coverage"}</strong><span>${escapeHtml(statusLabel)}</span></header>${available.length ? `<div><p>${language === "fr" ? "Informations actuellement disponibles :" : "Information currently available:"}</p><ul>${available.map((field) => `<li>${escapeHtml(labels[field] || field.replaceAll("_", " "))}</li>`).join("")}</ul></div>` : ""}</section>`;
    }

    const adaptiveResponseRenderers = {
        single_kpi: renderAdaptivePrimary,
        downtime_drivers: renderAdaptiveDiagnostics,
        root_cause_analysis: renderAdaptiveDiagnostics,
        performance_overview: renderAdaptiveRows,
        fleet_performance_overview: renderFleetPerformance,
        reliability_overview: renderFleetPerformance,
        multi_kpi_summary: renderFleetPerformance,
        planned_unplanned_analysis: renderFleetPerformance,
        fleet_performance_comparison: renderFleetPerformance,
        fleet_performance_period_comparison: renderFleetPerformance,
        fleet_performance_trend: renderFleetPerformance,
        fleet_performance_ranking: renderFleetPerformance,
        equipment_performance_detail: renderFleetPerformance,
        component_analysis: renderFleetPerformance,
        pm_analysis: renderFleetPerformance,
        smu_tracking: renderFleetPerformance,
        fleet_performance_benchmark: renderFleetPerformance,
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
                let activeWorkType = "";
                const renderPareto = (diagnostics) => {
                    pareto.replaceChildren();
                    renderDowntimeDiagnostics(pareto, diagnostics, {
                        intent,
                        workType: activeWorkType,
                        onSelectDriver: openDriver,
                        onWorkTypeChange: async (workType) => {
                            const refreshed = await apiRequest(root.dataset.availabilityDiagnosticsUrl, {
                                method: "POST",
                                body: JSON.stringify({
                                    intent,
                                    work_type: workType,
                                    dataset_name: "FPR Global DB + RLS",
                                }),
                            });
                            activeWorkType = refreshed.diagnostics?.work_type || workType;
                            renderPareto(refreshed.diagnostics || {});
                        },
                    });
                };
                renderPareto(payload.downtime_diagnostics || payload.availability_diagnostics);
            },
        };
        const templateCode = responseTemplateCode(payload);
        if (payload.capability_catalog) {
            renderCapabilityCatalog(content, payload, state);
        } else if (payload.answerability) {
            renderAnswerability(content, payload);
        } else if (payload.fleet_inventory) {
            renderFleetInventory(content, payload, message, language);
        } else if (payload.equipment_detail) {
            renderEquipmentMasterDetail(content, payload);
        } else if (payload.fleet_performance) {
            renderFleetPerformance(content, payload, intent, language, templateCode, message);
        } else if (templateCode === "legacy_availability_response") {
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
            button.addEventListener("click", async () => {
                if (action.code === "retry") {
                    const input = document.getElementById("ai-question");
                    if (!input || !question) return;
                    input.value = question;
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    runQuestion(root, state);
                    return;
                }
                if (action.code === "report_data_gap" && action.requirement_id) {
                    button.disabled = true;
                    try {
                        const result = await apiRequest("/api/ai/data-gaps/report/", {
                            method: "POST",
                            body: JSON.stringify({ requirement_id: action.requirement_id }),
                        });
                        button.textContent = result.message || (payload.content?.language === "fr" ? "Besoin enregistré" : "Requirement recorded");
                    } catch (error) {
                        button.disabled = false;
                        notifySafeError("The data requirement could not be recorded at this time.", "Le besoin de donnée ne peut pas être enregistré pour le moment.");
                    }
                    return;
                }
                const input = document.getElementById("ai-question");
                if (!input) return;
                input.value = action.prompt || button.textContent;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                state.pendingSubmission = {
                    source: "contextual_action",
                    action_code: action.code,
                    source_message_id: message.id,
                    idempotency_key: `action:${action.code}:${message.id}:${window.crypto?.randomUUID?.() || Date.now()}`,
                };
                runQuestion(root, state);
            });
            secondary.appendChild(button);
        });

        const navigationEligible = !payload.action_eligibility || (payload.action_eligibility.eligible || []).includes("open_powerbi");
        if (payload.navigation?.report_id && navigationEligible) {
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
        return date.toLocaleDateString("en-GB");
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
            notifySafeError("The conversation could not be deleted.", "La conversation ne peut pas être supprimée pour le moment.");
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
            notifySafeError("The conversation could not be archived.", "La conversation ne peut pas être archivée pour le moment.");
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
            notifySafeError("The retry could not be started.", "La nouvelle tentative ne peut pas être lancée pour le moment.");
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
            status.textContent = chatLanguage() === "fr"
                ? "Le rapport Power BI n'a pas pu etre charge."
                : "The Power BI report could not be loaded.";
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
        const submission = state.pendingSubmission || {};
        state.pendingInputMetadata = null;
        state.pendingSubmission = null;
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
        const clientExecutionId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        const abortController = new AbortController();
        state.activeExecution = { isLoading: true, clientMessageId: "", clientExecutionId, question, abortController };
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
        const loadingText = document.getElementById("ai-loading-text");
        if (loadingText) loadingText.textContent = detectedLanguage(question) === "fr" ? "Compréhension de votre question…" : "Understanding your question…";
        const slowTimer = window.setTimeout(() => {
            if (loadingText && state.activeExecution.clientExecutionId === clientExecutionId) {
                loadingText.textContent = detectedLanguage(question) === "fr" ? "Cette analyse prend plus de temps que prévu…" : "This analysis is taking longer than usual…";
            }
        }, 10000);
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
                signal: abortController.signal,
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                },
                body: JSON.stringify({
                    question,
                    conversation_id: state.conversationId,
                    client_message_id: clientMessageId,
                    client_execution_id: clientExecutionId,
                    idempotency_key: submission.idempotency_key || `manual:${clientMessageId}`,
                    source: submission.source || "manual",
                    suggestion_code: submission.suggestion_code || "",
                    action_code: submission.action_code || "",
                    source_message_id: submission.source_message_id || "",
                    guided_values: submission.guided_values || {},
                    input_metadata: inputMetadata,
                    agent_selection: document.getElementById("ai-agent-selection")?.value || "auto",
                }),
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                const requestError = new Error(payload.error || "Query failed.");
                requestError.status = response.status;
                requestError.code = payload.error_code || payload.answerability?.reason_code || "";
                requestError.retryAllowed = payload.retry?.allowed !== false;
                throw requestError;
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
            const cancelled = err?.name === "AbortError";
            const conversationLimit = err?.code === "CONVERSATION_LIMIT_REACHED" || err?.status === 409;
            const language = detectedLanguage(question);
            error.querySelector("strong").textContent = conversationLimit
                ? (language === "fr" ? "Limite de conversations atteinte" : "Conversation limit reached")
                : (language === "fr" ? "Requête momentanément indisponible" : "Request temporarily unavailable");
            errorText.textContent = cancelled
                ? (language === "fr" ? "Requête annulée." : "Request cancelled.")
                : conversationLimit
                    ? (language === "fr"
                        ? "Archivez ou supprimez une conversation active avant d'en créer une nouvelle."
                        : "Archive or delete an active conversation before creating a new one.")
                    : (language === "fr"
                        ? "La source nécessaire est momentanément indisponible. Vous pouvez réessayer."
                        : "The required source is temporarily unavailable. You can retry.");
            setHidden(error, cancelled);
            if (state.conversationId) {
                try {
                    await openConversation(root, state, state.conversationId);
                    await loadConversationList(root, state);
                } catch (reloadError) {
                    state.conversationHistory.push({ role: "assistant", content: errorText.textContent, status: cancelled ? "cancelled" : "failed" });
                    renderMessages(chatThread, state.conversationHistory, state);
                }
            }
            scrollIntoConversationView(chatThread.lastElementChild);
        } finally {
            window.clearTimeout(slowTimer);
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
            activeExecution: { isLoading: false, clientMessageId: "", clientExecutionId: "", question: "", abortController: null },
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
            pendingSubmission: null,
            suggestionsRequestId: 0,
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
            chatThread.innerHTML = `<div class="alert">${escapeHtml(chatLanguage() === "fr"
                ? "Les conversations n'ont pas pu etre chargees. Vous pouvez reessayer."
                : "Conversations could not be loaded. You can retry.")}</div>`;
        }
        const contextualDraft = new URLSearchParams(window.location.search).get("draft") || "";
        if (contextualDraft && input) {
            input.value = contextualDraft.slice(0, 2000);
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus({ preventScroll: true });
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
            saveInlineRename(root, state).catch(() => notifySafeError("The conversation could not be renamed.", "La conversation ne peut pas être renommée pour le moment."));
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
        document.getElementById("ai-cancel-execution")?.addEventListener("click", async () => {
            const active = state.activeExecution;
            if (!active.isLoading || !active.clientExecutionId) return;
            active.abortController?.abort();
            try {
                await apiRequest(`/api/ai/chat/executions/${encodeURIComponent(active.clientExecutionId)}/cancel/`, {
                    method: "POST",
                    body: "{}",
                });
            } catch (error) {
                window.setTimeout(() => apiRequest(`/api/ai/chat/executions/${encodeURIComponent(active.clientExecutionId)}/cancel/`, { method: "POST", body: "{}" }).catch(() => {}), 250);
            }
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
