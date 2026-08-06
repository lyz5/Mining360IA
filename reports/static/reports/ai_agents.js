(function () {
    "use strict";

    const csrfToken = () => document.cookie.split(";")
        .map((item) => item.trim())
        .find((item) => item.startsWith("csrftoken="))
        ?.split("=")[1] || "";
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
    const formatNumber = (value, digits = 0) => new Intl.NumberFormat("en-US", {
        maximumFractionDigits: digits,
    }).format(Number(value || 0));

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector("[data-agent-admin]");
        if (!root) return;
        const state = {
            agents: [], summary: {}, selected: null, activeTab: "general",
            providerConfiguration: null,
        };
        const cards = document.getElementById("agent-card-grid");
        const kpis = document.getElementById("agent-kpis");
        const modal = document.getElementById("agent-modal");
        const form = document.getElementById("agent-form");
        const formContent = document.getElementById("agent-form-content");
        const formTabs = document.getElementById("agent-form-tabs");
        const flash = document.getElementById("agent-flash");

        async function api(url, options = {}) {
            const response = await fetch(url, {
                ...options,
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                    ...(options.headers || {}),
                },
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Request failed.");
            return payload;
        }
        function notify(message, error = false) {
            flash.textContent = message;
            flash.classList.toggle("is-error", error);
            flash.hidden = false;
            window.setTimeout(() => { flash.hidden = true; }, 4500);
        }
        function renderKpis() {
            const values = [
                ["Total Agents", state.summary.total_agents],
                ["Active Agents", state.summary.active_agents],
                ["Validated Agents", state.summary.validated_agents],
                ["Routing Success", `${formatNumber(state.summary.routing_success_rate, 1)}%`],
                ["Clarification Rate", `${formatNumber(state.summary.clarification_rate, 1)}%`],
                ["Combined", state.summary.combined_executions],
                ["Avg. Response", `${formatNumber(state.summary.average_response_time)} ms`],
                ["API Cost", `$${formatNumber(state.summary.api_cost, 4)}`],
            ];
            kpis.innerHTML = values.map(([label, value]) => `
                <article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? 0)}</strong></article>
            `).join("");
        }
        function agentIcon(code) {
            return code === "machine_performance" ? "MP" : code === "mining_knowledge" ? "MK" : "AI";
        }
        function renderCards() {
            cards.innerHTML = state.agents.map((agent) => `
                <article class="agent-card" data-agent-id="${agent.id}" tabindex="0">
                    <header>
                        <span class="agent-card__icon agent-card__icon--${escapeHtml(agent.code)}">${agentIcon(agent.code)}</span>
                        <span class="status-badge ${agent.active ? "status-completed" : "status-unknown"}">${agent.active ? "Active" : "Inactive"}</span>
                    </header>
                    <p class="eyebrow">${escapeHtml(agent.agent_type.replaceAll("_", " "))}</p>
                    <h3>${escapeHtml(agent.name)}</h3>
                    <p>${escapeHtml(agent.description)}</p>
                    <div class="agent-card__tags">
                        <span>${agent.counts.capabilities} capabilities</span>
                        <span>${agent.counts.sources} sources</span>
                        <span>${agent.counts.tools} tools</span>
                    </div>
                    <dl>
                        <div><dt>Routing</dt><dd>${escapeHtml(agent.routing_mode)}</dd></div>
                        <div><dt>Confidence</dt><dd>${agent.minimum_confidence}%</dd></div>
                        <div><dt>Priority</dt><dd>${agent.priority}</dd></div>
                        <div><dt>Governance</dt><dd>${escapeHtml(agent.validation_status)}</dd></div>
                    </dl>
                    <footer>
                        <button type="button" class="button secondary" data-agent-edit="${agent.id}">Configure</button>
                        <button type="button" class="button secondary" data-agent-test="${agent.id}">Test</button>
                    </footer>
                </article>
            `).join("") || `<div class="empty-state">No AI agent is configured.</div>`;
        }
        async function loadAgents() {
            const payload = await api(root.dataset.agentsUrl);
            state.agents = payload.agents;
            state.summary = payload.summary;
            renderKpis();
            renderCards();
        }

        const tabs = [
            ["general", "General"],
            ["instructions", "Instructions"],
            ["routing", "Routing"],
            ["capabilities", "Capabilities"],
            ["intents", "Intents"],
            ["tools", "Tools"],
            ["sources", "Sources"],
            ["prompts", "Prompts"],
            ["api_provider", "API Provider"],
            ["permissions", "Permissions"],
            ["governance", "Governance"],
        ];
        function field(name, label, value = "", type = "text") {
            if (type === "textarea") {
                return `<label><span>${label}</span><textarea name="${name}" rows="7">${escapeHtml(value)}</textarea></label>`;
            }
            if (type === "checkbox") {
                return `<label class="agent-toggle"><input type="checkbox" name="${name}" ${value ? "checked" : ""}><span>${label}</span></label>`;
            }
            return `<label><span>${label}</span><input type="${type}" name="${name}" value="${escapeHtml(value)}"></label>`;
        }
        function relatedTable(type, items) {
            const labels = {
                capabilities: ["capability_code", "display_name"],
                intents: ["intent_code", "display_name"],
                tools: ["tool_code", "display_name"],
                sources: ["source_type", "source_name"],
                prompts: ["prompt_type", "name"],
            };
            const [code, name] = labels[type];
            return `
                <div class="agent-related-list">
                    ${items.map((item) => `
                        <article>
                            <div><strong>${escapeHtml(item[name])}</strong><span>${escapeHtml(item[code])}</span></div>
                            <span class="status-badge">${escapeHtml(item.validation_status)}</span>
                            ${"enabled" in item ? `<label class="agent-switch"><input type="checkbox" data-related-toggle="${type}" data-related-id="${item.id}" ${item.enabled ? "checked" : ""}><span></span></label>` : ""}
                        </article>
                    `).join("") || `<p class="empty-state">No ${escapeHtml(type)} configured.</p>`}
                </div>`;
        }
        function renderAgentForm() {
            const agent = state.selected || {
                code: "", name: "", agent_type: "machine_performance", description: "",
                routing_mode: "automatic", minimum_confidence: 85, priority: 50,
                active: true, is_default: false, allow_combined_execution: true,
                validation_status: "To Review", version: "1.0",
                capabilities: [], intents: [], tools: [], sources: [], prompts: [], permissions: {},
            };
            formTabs.innerHTML = tabs.map(([code, label]) => `
                <button type="button" class="${state.activeTab === code ? "is-active" : ""}" data-form-tab="${code}">${label}</button>
            `).join("");
            let html = "";
            if (state.activeTab === "general") html = `
                <div class="form-grid agent-form-grid">
                    ${field("code", "Agent Code", agent.code)}
                    ${field("name", "Agent Name", agent.name)}
                    <label><span>Agent Type</span><select name="agent_type">
                        <option value="machine_performance" ${agent.agent_type === "machine_performance" ? "selected" : ""}>Machine Performance</option>
                        <option value="mining_knowledge" ${agent.agent_type === "mining_knowledge" ? "selected" : ""}>Mining Knowledge</option>
                    </select></label>
                    ${field("owner", "Owner", agent.owner)}
                    ${field("version", "Version", agent.version)}
                    ${field("description", "Description", agent.description, "textarea")}
                    ${field("active", "Active", agent.active, "checkbox")}
                    ${field("is_default", "Default Agent", agent.is_default, "checkbox")}
                </div>`;
            else if (state.activeTab === "instructions") html = `
                <div class="agent-stack">
                    ${field("system_instructions", "System Instructions", agent.system_instructions, "textarea")}
                    ${field("response_instructions", "Response Instructions", agent.response_instructions, "textarea")}
                    ${field("clarification_instructions", "Clarification Instructions", agent.clarification_instructions, "textarea")}
                    ${field("combined_execution_instructions", "Combined Execution Instructions", agent.combined_execution_instructions, "textarea")}
                </div>`;
            else if (state.activeTab === "routing") html = `
                <div class="form-grid agent-form-grid">
                    <label><span>Routing Mode</span><select name="routing_mode">
                        ${["automatic", "manual", "disabled"].map((value) => `<option ${agent.routing_mode === value ? "selected" : ""}>${value}</option>`).join("")}
                    </select></label>
                    ${field("priority", "Priority", agent.priority, "number")}
                    ${field("minimum_confidence", "Minimum Confidence", agent.minimum_confidence, "number")}
                    ${field("allow_combined_execution", "Allow Combined Execution", agent.allow_combined_execution, "checkbox")}
                    ${field("clarification_message", "Clarification Message", agent.clarification_message, "textarea")}
                </div>`;
            else if (["capabilities", "intents", "tools", "sources", "prompts"].includes(state.activeTab)) {
                html = relatedTable(state.activeTab, agent[state.activeTab] || []);
            } else if (state.activeTab === "api_provider") {
                const config = state.providerConfiguration;
                if (!agent.id) {
                    html = `<p class="empty-state">Save the agent before assigning provider overrides.</p>`;
                } else if (!config) {
                    html = `<p class="empty-state"><span class="loading-spinner"></span> Loading provider configuration...</p>`;
                } else {
                    const providers = config.providers.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
                    const useCases = config.use_cases.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
                    html = `<div class="agent-provider-panel">
                        <p class="agent-form-note">Global API Management remains the default. Add an override only when this agent needs a different provider or model.</p>
                        <div class="form-grid agent-form-grid">
                            <label><span>Use Case</span><select id="agent-provider-use-case">${useCases}</select></label>
                            <label><span>Provider</span><select id="agent-provider-provider">${providers}</select></label>
                            <label><span>Model</span><select id="agent-provider-model"><option value="">Provider default</option></select></label>
                            ${field("agent_provider_priority", "Priority", 100, "number")}
                            ${field("agent_provider_fallback", "Allow Fallback", true, "checkbox")}
                            ${field("agent_provider_active", "Active", true, "checkbox")}
                        </div>
                        <button type="button" class="button primary" id="agent-provider-save">Add or Update Override</button>
                        <div class="agent-related-list agent-provider-list">
                            ${config.items.map((item) => `<article>
                                <div><strong>${escapeHtml(item.use_case_name)}</strong><span>${escapeHtml(item.provider)}${item.model ? ` · ${escapeHtml(item.model)}` : ""}</span></div>
                                <span class="status-badge">${item.active ? "Active" : "Inactive"}</span>
                                <b>Priority ${item.priority}</b>
                            </article>`).join("") || `<p class="empty-state">This agent uses the global provider configuration.</p>`}
                        </div>
                    </div>`;
                }
            } else if (state.activeTab === "permissions") html = `
                <div class="form-grid agent-form-grid">
                    ${field("can_export", "Can Export", agent.permissions?.can_export, "checkbox")}
                    ${field("can_access_comments", "Can Access Comments", agent.permissions?.can_access_comments, "checkbox")}
                    ${field("can_access_debug", "Can Access Debug", agent.permissions?.can_access_debug, "checkbox")}
                    <p class="agent-form-note">MineSite, Customer and Power BI Row-Level Security remain enforced by the existing services.</p>
                </div>`;
            else html = `
                <dl class="agent-governance">
                    <div><dt>Validation Status</dt><dd>
                        <select name="validation_status">
                            ${["Draft", "To Review", "Validated", "Rejected"].map((value) => `<option ${agent.validation_status === value ? "selected" : ""}>${value}</option>`).join("")}
                        </select>
                    </dd></div>
                    <div><dt>Created At</dt><dd>${escapeHtml(agent.created_at || "Not saved")}</dd></div>
                    <div><dt>Updated At</dt><dd>${escapeHtml(agent.updated_at || "Not saved")}</dd></div>
                    <div><dt>Validated At</dt><dd>${escapeHtml(agent.validated_at || "Not validated")}</dd></div>
                </dl>`;
            formContent.innerHTML = html;
            if (state.activeTab === "api_provider" && state.providerConfiguration) refreshAgentProviderModels();
        }
        function refreshAgentProviderModels() {
            const provider = document.getElementById("agent-provider-provider");
            const model = document.getElementById("agent-provider-model");
            if (!provider || !model || !state.providerConfiguration) return;
            const options = state.providerConfiguration.models
                .filter((item) => String(item.provider_id) === String(provider.value))
                .map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
            model.innerHTML = `<option value="">Provider default</option>${options}`;
        }
        async function loadAgentProviders() {
            if (!state.selected?.id) return;
            state.providerConfiguration = await api(`${root.dataset.agentsUrl}${state.selected.id}/providers/`);
            renderAgentForm();
        }
        async function openAgent(id = null) {
            state.activeTab = "general";
            state.providerConfiguration = null;
            if (id) {
                state.selected = (await api(`${root.dataset.agentsUrl}${id}/`)).agent;
            } else {
                state.selected = null;
            }
            document.getElementById("agent-modal-title").textContent = state.selected ? state.selected.name : "Create Agent";
            renderAgentForm();
            modal.hidden = false;
            modal.setAttribute("aria-hidden", "false");
        }
        function closeAgent() {
            modal.hidden = true;
            modal.setAttribute("aria-hidden", "true");
        }
        function formData() {
            const data = {};
            new FormData(form).forEach((value, key) => { data[key] = value; });
            form.querySelectorAll('input[type="checkbox"]').forEach((input) => { data[input.name] = input.checked; });
            ["priority", "minimum_confidence"].forEach((key) => {
                if (key in data) data[key] = Number(data[key]);
            });
            return data;
        }
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            try {
                const id = state.selected?.id;
                await api(id ? `${root.dataset.agentsUrl}${id}/` : root.dataset.agentsUrl, {
                    method: id ? "PATCH" : "POST",
                    body: JSON.stringify(formData()),
                });
                closeAgent();
                await loadAgents();
                notify("Agent configuration saved.");
            } catch (error) { notify(error.message, true); }
        });
        formTabs.addEventListener("click", (event) => {
            const button = event.target.closest("[data-form-tab]");
            if (!button) return;
            state.activeTab = button.dataset.formTab;
            renderAgentForm();
            if (state.activeTab === "api_provider") {
                loadAgentProviders().catch((error) => notify(error.message, true));
            }
        });
        modal.addEventListener("click", async (event) => {
            if (event.target.closest("[data-agent-close]")) closeAgent();
            const toggle = event.target.closest("[data-related-toggle]");
            if (toggle && state.selected) {
                try {
                    await api(`${root.dataset.agentsUrl}${state.selected.id}/${toggle.dataset.relatedToggle}/${toggle.dataset.relatedId}/`, {
                        method: "PATCH",
                        body: JSON.stringify({ enabled: toggle.checked }),
                    });
                    state.selected = (await api(`${root.dataset.agentsUrl}${state.selected.id}/`)).agent;
                    renderAgentForm();
                } catch (error) { notify(error.message, true); }
            }
            if (event.target.id === "agent-provider-save" && state.selected) {
                try {
                    await api(`${root.dataset.agentsUrl}${state.selected.id}/providers/`, {
                        method: "POST",
                        body: JSON.stringify({
                            use_case_id: Number(document.getElementById("agent-provider-use-case").value),
                            provider_id: Number(document.getElementById("agent-provider-provider").value),
                            model_id: Number(document.getElementById("agent-provider-model").value) || null,
                            priority: Number(form.elements.agent_provider_priority.value || 100),
                            fallback_enabled: form.elements.agent_provider_fallback.checked,
                            active: form.elements.agent_provider_active.checked,
                        }),
                    });
                    await loadAgentProviders();
                    notify("Agent provider override saved.");
                } catch (error) { notify(error.message, true); }
            }
        });
        formContent.addEventListener("change", (event) => {
            if (event.target.id === "agent-provider-provider") refreshAgentProviderModels();
        });
        cards.addEventListener("click", (event) => {
            const edit = event.target.closest("[data-agent-edit]");
            const test = event.target.closest("[data-agent-test]");
            if (edit) openAgent(edit.dataset.agentEdit);
            if (test) openTest(test.dataset.agentTest);
        });
        document.getElementById("agent-create").addEventListener("click", () => openAgent());
        document.getElementById("agent-refresh").addEventListener("click", loadAgents);

        document.querySelector(".agent-admin__tabs").addEventListener("click", async (event) => {
            const button = event.target.closest("[data-agent-view]");
            if (!button) return;
            document.querySelectorAll("[data-agent-view]").forEach((item) => item.classList.toggle("is-active", item === button));
            document.querySelectorAll("[data-agent-panel]").forEach((panel) => {
                const active = panel.dataset.agentPanel === button.dataset.agentView;
                panel.hidden = !active;
                panel.classList.toggle("is-active", active);
            });
            if (button.dataset.agentView === "router") await loadRouter();
            if (button.dataset.agentView === "logs") await loadLogs();
        });

        const routerForm = document.getElementById("agent-router-form");
        async function loadRouter() {
            const config = (await api(root.dataset.routerUrl)).configuration;
            Object.entries(config).forEach(([key, value]) => {
                const input = routerForm.elements[key];
                if (!input) return;
                if (input.type === "checkbox") input.checked = Boolean(value);
                else input.value = value ?? "";
            });
            document.getElementById("agent-router-rules").innerHTML = `
                <h3>Routing Rules</h3>
                ${config.rules.map((rule) => `
                    <article><div><strong>${escapeHtml(rule.name)}</strong><span>${escapeHtml(rule.rule_code)}</span></div>
                    <span>${escapeHtml(rule.selected_agent.replaceAll("_", " "))}</span><b>${rule.priority}</b></article>
                `).join("")}`;
        }
        routerForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const data = {};
            new FormData(routerForm).forEach((value, key) => { data[key] = value; });
            routerForm.querySelectorAll('input[type="checkbox"]').forEach((input) => { data[input.name] = input.checked; });
            data.minimum_confidence = Number(data.minimum_confidence);
            await api(root.dataset.routerUrl, { method: "PATCH", body: JSON.stringify(data) });
            notify("Router configuration saved.");
        });
        document.getElementById("agent-router-test").addEventListener("submit", async (event) => {
            event.preventDefault();
            const result = document.getElementById("agent-router-result");
            result.hidden = false;
            result.innerHTML = `<span class="loading-spinner"></span> Resolving question...`;
            try {
                const question = event.currentTarget.elements.question.value;
                const routing = (await api(root.dataset.routerTestUrl, {
                    method: "POST", body: JSON.stringify({ question }),
                })).routing;
                result.innerHTML = `
                    <span class="status-badge status-completed">${escapeHtml(routing.method)}</span>
                    <h3>${escapeHtml(routing.selected_agent_name || "Clarification Required")}</h3>
                    <strong>${routing.confidence}% confidence</strong>
                    <p>${escapeHtml(routing.reason)}</p>
                    <dl>
                        <div><dt>Intent</dt><dd>${escapeHtml(routing.intent)}</dd></div>
                        <div><dt>Matched Rule</dt><dd>${escapeHtml(routing.matched_rules.join(", ") || "None")}</dd></div>
                        <div><dt>Clarification</dt><dd>${routing.requires_clarification ? "Required" : "No"}</dd></div>
                    </dl>`;
            } catch (error) { result.textContent = error.message; }
        });

        async function loadLogs() {
            const logs = (await api(root.dataset.logsUrl)).logs;
            const table = document.getElementById("agent-logs-table");
            table.innerHTML = `
                <thead><tr><th>Date</th><th>Agent</th><th>Intent</th><th>Confidence</th><th>Status</th><th>Time</th><th>Question</th></tr></thead>
                <tbody>${logs.map((log) => `<tr>
                    <td>${escapeHtml(new Date(log.created_at).toLocaleString())}</td>
                    <td>${escapeHtml(log.selected_agent.replaceAll("_", " "))}</td>
                    <td>${escapeHtml(log.intent)}</td><td>${log.routing_confidence}%</td>
                    <td>${escapeHtml(log.status)}</td><td>${log.response_time_ms} ms</td>
                    <td>${escapeHtml(log.question)}</td>
                </tr>`).join("")}</tbody>`;
        }

        const testDialog = document.getElementById("agent-test-dialog");
        let testAgentId = null;
        function openTest(id) {
            testAgentId = id;
            document.getElementById("agent-test-question").value = "";
            document.getElementById("agent-test-result").hidden = true;
            testDialog.showModal();
        }
        document.getElementById("agent-test-current").addEventListener("click", () => {
            if (state.selected) openTest(state.selected.id);
        });
        document.getElementById("agent-run-test").addEventListener("click", async () => {
            const result = document.getElementById("agent-test-result");
            result.hidden = false;
            result.innerHTML = `<span class="loading-spinner"></span> Running agent...`;
            try {
                const payload = await api(`${root.dataset.agentsUrl}${testAgentId}/test/`, {
                    method: "POST",
                    body: JSON.stringify({ question: document.getElementById("agent-test-question").value }),
                });
                result.innerHTML = `<h3>${escapeHtml(payload.agent?.name || "")}</h3>
                    <p>${escapeHtml(payload.chat_message || payload.answer || "")}</p>
                    <pre>${escapeHtml(JSON.stringify(payload.routing || {}, null, 2))}</pre>`;
            } catch (error) { result.textContent = error.message; }
        });

        loadAgents().catch((error) => notify(error.message, true));
    });
}());
