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

    function renderDowntimeDiagnostics(body, diagnostics) {
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
        if (drivers.length) {
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
            const bars = [];
            const labels = [];
            drivers.forEach((item, index) => {
                const hours = Number(item.hours) || 0;
                const cumulative = Math.min(Math.max(Number(item.cumulative_percentage) || 0, 0), 100);
                const centerX = left + (index * step) + (step / 2);
                const barHeight = (hours / maxHours) * plotHeight;
                const barY = baseline - barHeight;
                const pointY = baseline - ((cumulative / 100) * plotHeight);
                const shortName = String(item.driver).length > 18
                    ? `${String(item.driver).slice(0, 17)}…`
                    : String(item.driver);
                points.push(`${centerX.toFixed(1)},${pointY.toFixed(1)}`);
                bars.push(`
                    <g>
                        <title>${escapeHtml(item.driver)}: ${hours.toLocaleString(undefined, { maximumFractionDigits: 2 })} h</title>
                        <rect x="${(centerX - barWidth / 2).toFixed(1)}" y="${barY.toFixed(1)}"
                              width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"
                              rx="2" class="ai-pareto-bar"></rect>
                        <text x="${centerX.toFixed(1)}" y="${Math.max(barY - 7, 14).toFixed(1)}"
                              class="ai-pareto-hours" text-anchor="middle">${hours.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
                    </g>
                `);
                labels.push(`
                    <text x="${centerX.toFixed(1)}" y="${(baseline + 18).toFixed(1)}"
                          transform="rotate(-42 ${centerX.toFixed(1)} ${(baseline + 18).toFixed(1)})"
                          class="ai-pareto-driver" text-anchor="end">${escapeHtml(shortName)}</text>
                    <g>
                        <circle cx="${centerX.toFixed(1)}" cy="${pointY.toFixed(1)}" r="6"
                                class="ai-pareto-point"></circle>
                        <text x="${centerX.toFixed(1)}" y="${Math.max(pointY - 12, 13).toFixed(1)}"
                              class="ai-pareto-percent" text-anchor="middle">${cumulative.toFixed(0)}%</text>
                    </g>
                `);
            });
            const grid = [0, 0.5, 1].map((ratio) => {
                const y = baseline - (ratio * plotHeight);
                const hours = maxHours * ratio;
                return `
                    <line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" class="ai-pareto-grid"></line>
                    <text x="${left - 9}" y="${y + 4}" text-anchor="end" class="ai-pareto-axis">${hours.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
                    <text x="${width - right + 9}" y="${y + 4}" class="ai-pareto-axis">${Math.round(ratio * 100)}%</text>
                `;
            }).join("");
            chart.innerHTML = `
                <svg viewBox="0 0 ${width} ${height}" role="img"
                     aria-label="Pareto chart of downtime hours by driver and cumulative percentage">
                    ${grid}
                    <text x="16" y="${top + plotHeight / 2}" transform="rotate(-90 16 ${top + plotHeight / 2})"
                          text-anchor="middle" class="ai-pareto-axis-title">Downtime Hours</text>
                    <text x="${width - 9}" y="${top + plotHeight / 2}" transform="rotate(-90 ${width - 9} ${top + plotHeight / 2})"
                          text-anchor="middle" class="ai-pareto-axis-title">Pareto</text>
                    ${bars.join("")}
                    <polyline points="${points.join(" ")}" class="ai-pareto-line"></polyline>
                    ${labels.join("")}
                </svg>
            `;
        } else {
            chart.innerHTML = '<p class="ai-downtime-pareto__empty">No downtime driver returned for this context.</p>';
        }
        body.appendChild(card);
    }

    function renderMessages(container, messages) {
        if (!container) return;
        container.innerHTML = messages.map((message) => `
            <div class="ai-message ${message.role === "user" ? "user" : "assistant"}">
                <div class="ai-message__avatar">${message.role === "user" ? "You" : "AI"}</div>
                <div class="ai-message__body">${escapeHtml(message.content).replaceAll("\n", "<br>")}</div>
            </div>
        `).join("");
    }

    async function runQuestion(root, state) {
        if (state.isLoading) return;
        const input = document.getElementById("ai-question");
        const question = input.value.trim();
        const loading = document.getElementById("ai-loading");
        const error = document.getElementById("ai-error");
        const errorText = document.getElementById("ai-error-text");
        const tableSection = document.getElementById("ai-table-section");
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

        setHidden(loading, false);
        setHidden(error, true);
        setHidden(tableSection, true);
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
            });
            renderMessages(chatThread, state.messages);
            saveHistory(state.messages);
            scrollIntoConversationView(chatThread.lastElementChild);

            const hasDowntimeDiagnostics = (
                payload.availability_diagnostics
                && payload.availability_diagnostics.total_downtime_hours !== undefined
            );
            if (hasDowntimeDiagnostics && downtimeContent) {
                downtimeContent.replaceChildren();
                renderDowntimeDiagnostics(
                    downtimeContent,
                    payload.availability_diagnostics,
                );
                setHidden(downtimeSection, false);
                const latestAssistantBody = chatThread.querySelector(
                    ".ai-message.assistant:last-child .ai-message__body"
                );
                if (latestAssistantBody) {
                    const downtimeButton = document.createElement("button");
                    downtimeButton.type = "button";
                    downtimeButton.className = "ai-inline-report-button";
                    downtimeButton.textContent = "View Downtime Drivers";
                    downtimeButton.addEventListener("click", () => {
                        downtimeSection.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                        });
                    });
                    latestAssistantBody.appendChild(downtimeButton);
                }
                if (!payload.navigation?.report_id) {
                    window.setTimeout(() => {
                        downtimeSection.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                        });
                    }, 80);
                }
            }

            const intent = payload.intent || payload.semantic_request || {};
            renderContext(contextList, intent, payload.metric, payload.measure, payload.validation);
            renderTable(table, payload.answer?.rows, payload.answer?.summary);
            dax.textContent = payload.dax || intent.dax || "";
            debug.textContent = JSON.stringify(payload.debug || payload, null, 2);
            setHidden(tableSection, false);
            setHidden(daxSection, false);
            setHidden(debugSection, false);
            if (payload.conversation_id) {
                state.conversationId = payload.conversation_id;
                sessionStorage.setItem(conversationKey, state.conversationId);
            }
            if (payload.navigation?.report_id) {
                const powerbiSection = document.getElementById("ai-powerbi-section");
                const powerbiTitle = document.getElementById("ai-powerbi-title");
                const powerbiStatus = document.getElementById("ai-powerbi-status");
                const reportTabs = document.getElementById("ai-powerbi-report-tabs");
                setHidden(powerbiSection, false);
                window.setTimeout(() => {
                    powerbiSection.scrollIntoView({ behavior: "smooth", block: "start" });
                }, 80);
                powerbiTitle.textContent = payload.navigation.display_name || payload.navigation.report_name || "Relevant report";
                powerbiStatus.textContent = "Opening report and applying filters...";
                const latestAssistantBody = chatThread.querySelector(".ai-message.assistant:last-child .ai-message__body");
                if (latestAssistantBody) {
                    const reportButton = document.createElement("button");
                    reportButton.type = "button";
                    reportButton.className = "ai-inline-report-button";
                    reportButton.textContent = `View ${payload.navigation.display_name || payload.navigation.report_name || "Power BI report"}`;
                    reportButton.addEventListener("click", () => {
                        powerbiSection.scrollIntoView({ behavior: "smooth", block: "start" });
                    });
                    latestAssistantBody.appendChild(reportButton);
                }
                if (!window.Mining360PowerBIEmbed) {
                    powerbiStatus.textContent = "Power BI JavaScript API is unavailable. Refresh the page and try again.";
                    return;
                }
                if (!state.powerbi) {
                    state.powerbi = new window.Mining360PowerBIEmbed(document.getElementById("ai-powerbi-report"), {
                        embedConfigUrl: root.dataset.embedConfigUrl,
                        onEvent: (event) => {
                            state.powerbiEvents.push(event);
                            powerbiStatus.textContent = event.type.replaceAll("_", " ");
                        },
                    });
                }
                try {
                    await state.powerbi.navigate(payload.navigation);
                    const reportOptions = [
                        payload.navigation,
                        ...(payload.navigation.alternative_reports || []),
                    ];
                    reportTabs.replaceChildren();
                    reportOptions.forEach((option, index) => {
                        const button = document.createElement("button");
                        button.type = "button";
                        button.className = `ai-report-tab${index === 0 ? " is-active" : ""}`;
                        button.setAttribute("role", "tab");
                        button.setAttribute("aria-selected", index === 0 ? "true" : "false");
                        button.textContent = option.display_name || option.report_name || "Power BI report";
                        button.addEventListener("click", async () => {
                            reportTabs.querySelectorAll(".ai-report-tab").forEach((item) => {
                                item.classList.remove("is-active");
                                item.setAttribute("aria-selected", "false");
                            });
                            button.classList.add("is-active");
                            button.setAttribute("aria-selected", "true");
                            powerbiTitle.textContent = option.display_name || option.report_name || "Relevant report";
                            powerbiStatus.textContent = "Opening report and applying filters...";
                            try {
                                await state.powerbi.navigate(option);
                                powerbiStatus.textContent = (option.warnings || []).join(" ") || "Report synchronized.";
                            } catch (reportError) {
                                powerbiStatus.textContent = reportError.message;
                            }
                        });
                        reportTabs.appendChild(button);
                    });
                    powerbiStatus.textContent = (payload.navigation.warnings || []).join(" ") || "Report synchronized.";
                    const logId = payload.debug?.interaction_log_id;
                    if (logId) {
                        const eventsUrl = root.dataset.interactionEventsUrl.replace("__LOG_ID__", logId);
                        fetch(eventsUrl, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                            body: JSON.stringify({ events: state.powerbiEvents }),
                        }).catch(() => {});
                    }
                } catch (navigationError) {
                    powerbiStatus.textContent = navigationError.message;
                }
            }
        } catch (err) {
            errorText.textContent = err.message;
            setHidden(error, false);
            state.messages.push({ role: "assistant", content: `Je n'ai pas pu exécuter la question: ${err.message}` });
            renderMessages(chatThread, state.messages);
            saveHistory(state.messages);
            scrollIntoConversationView(chatThread.lastElementChild);
        } finally {
            state.isLoading = false;
            if (sendButton) {
                sendButton.disabled = false;
                sendButton.classList.remove("is-loading");
                sendButton.setAttribute("aria-label", "Envoyer la question");
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
        const latestSavedDiagnostics = [...state.messages]
            .reverse()
            .find((message) => message?.diagnostics?.total_downtime_hours !== undefined)
            ?.diagnostics;
        if (latestSavedDiagnostics) {
            const savedDowntimeSection = document.getElementById("ai-downtime-section");
            const savedDowntimeContent = document.getElementById("ai-downtime-content");
            savedDowntimeContent.replaceChildren();
            renderDowntimeDiagnostics(savedDowntimeContent, latestSavedDiagnostics);
            setHidden(savedDowntimeSection, false);
        }
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
        document.querySelectorAll(".js-ai-example").forEach((example) => {
            example.addEventListener("click", function () {
                input.value = example.dataset.question || "";
                runQuestion(root, state);
            });
        });
    });
}());
