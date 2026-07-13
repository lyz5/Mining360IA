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
            items.push(["Validation", validation.valid ? "OK" : "Failed"]);
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

    function renderMessages(container, messages) {
        if (!container) return;
        container.innerHTML = messages.map((message) => `
            <div class="ai-message ${message.role === "user" ? "user" : "assistant"}">
                <div class="ai-message__avatar">${message.role === "user" ? "You" : "AI"}</div>
                <div class="ai-message__body">${escapeHtml(message.content).replaceAll("\n", "<br>")}</div>
            </div>
        `).join("");
        container.scrollTop = container.scrollHeight;
    }

    async function runQuestion(root, state) {
        const input = document.getElementById("ai-question");
        const question = input.value.trim();
        const loading = document.getElementById("ai-loading");
        const error = document.getElementById("ai-error");
        const errorText = document.getElementById("ai-error-text");
        const tableSection = document.getElementById("ai-table-section");
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

        state.messages.push({ role: "user", content: question });
        renderMessages(chatThread, state.messages);
        saveHistory(state.messages);
        input.value = "";

        setHidden(loading, false);
        setHidden(error, true);
        setHidden(tableSection, true);
        setHidden(daxSection, true);

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
            state.messages.push({ role: "assistant", content: assistantMessage });
            renderMessages(chatThread, state.messages);
            saveHistory(state.messages);

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
            if (payload.navigation?.report_id && window.Mining360PowerBIEmbed) {
                const powerbiSection = document.getElementById("ai-powerbi-section");
                const powerbiTitle = document.getElementById("ai-powerbi-title");
                const powerbiStatus = document.getElementById("ai-powerbi-status");
                setHidden(powerbiSection, false);
                powerbiTitle.textContent = payload.navigation.display_name || payload.navigation.report_name || "Relevant report";
                powerbiStatus.textContent = "Opening report and applying filters...";
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
        } finally {
        setHidden(loading, true);
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

        button?.addEventListener("click", function () {
            runQuestion(root, state);
        });
        input?.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                runQuestion(root, state);
            }
        });
        document.querySelectorAll(".js-ai-example").forEach((example) => {
            example.addEventListener("click", function () {
                input.value = example.dataset.question || "";
                runQuestion(root, state);
            });
        });
    });
}());
