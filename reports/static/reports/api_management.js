(() => {
    const root = document.querySelector("[data-api-management]");
    if (!root) return;

    const capabilities = [
        "text_generation", "structured_output", "tool_calling", "embeddings",
        "audio_transcription", "text_to_speech", "vision", "document_analysis",
        "streaming", "long_context", "json_mode", "function_calling"
    ];
    const state = { providers: [], models: [], useCases: [] };
    const csrf = () => document.cookie.split("; ").find(v => v.startsWith("csrftoken="))?.split("=")[1] || "";

    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: {
                "Accept": "application/json",
                ...(options.body ? {"Content-Type": "application/json", "X-CSRFToken": csrf()} : {}),
                ...(options.headers || {})
            }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) throw new Error(payload.error || payload.message || "Invalid server response.");
        return payload;
    }

    function status(message, type = "success") {
        const element = root.querySelector("[data-api-status]");
        element.hidden = !message;
        element.className = `api-management-status ${type}`;
        element.textContent = message || "";
    }

    function esc(value) {
        const node = document.createElement("span");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function renderKpis(summary) {
        const values = [
            ["Configured Providers", summary.configured_providers],
            ["Active Providers", summary.active_providers],
            ["Default Provider", summary.default_provider],
            ["Healthy Providers", summary.healthy_providers],
            ["Degraded", summary.degraded_providers],
            ["Failed Requests", summary.failed_requests],
            ["Fallback Rate", `${summary.fallback_rate}%`],
            ["Total API Cost", `$${Number(summary.total_cost || 0).toFixed(4)}`]
        ];
        root.querySelector("[data-api-kpis]").innerHTML = values.map(([label, value]) =>
            `<article><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`
        ).join("");
    }

    function badge(provider) {
        const label = provider.active ? provider.status.replaceAll("_", " ") : "inactive";
        return `<span class="api-status-badge ${esc(label)}">${esc(label)}</span>`;
    }

    function renderProviders() {
        root.querySelector("[data-provider-grid]").innerHTML = state.providers.map(provider => `
            <article class="api-provider-card">
                <header>
                    <div><p class="eyebrow">${esc(provider.provider_type.replaceAll("_", " "))}</p><h2>${esc(provider.name)}</h2></div>
                    ${badge(provider)}
                </header>
                <p>${esc(provider.description || "No provider description.")}</p>
                <dl>
                    <div><dt>Priority</dt><dd>${provider.priority}</dd></div>
                    <div><dt>Credential</dt><dd>${esc(provider.credential_status)}</dd></div>
                    <div><dt>Models</dt><dd>${provider.model_count}</dd></div>
                    <div><dt>Average latency</dt><dd>${Number(provider.average_latency || 0).toFixed(0)} ms</dd></div>
                    <div><dt>Success rate</dt><dd>${provider.success_rate == null ? "No data" : `${provider.success_rate}%`}</dd></div>
                    <div><dt>Spend</dt><dd>$${Number(provider.current_spend || 0).toFixed(4)}</dd></div>
                </dl>
                <div class="api-provider-capability-list">${provider.capabilities.slice(0, 6).map(item => `<span>${esc(item.replaceAll("_", " "))}</span>`).join("")}</div>
                <footer>
                    <button type="button" class="button secondary" data-provider-edit="${provider.id}">Configure</button>
                    <a class="button secondary" href="/ai-config/api-management/providers/${provider.id}/credential/">${provider.credential_status === "Not Configured" ? "Set Credential" : "Replace Credential"}</a>
                    <a class="button secondary" href="/ai-config/api-management/providers/${provider.id}/test/">Test</a>
                    <a class="button secondary" href="/ai-config/api-management/providers/${provider.id}/status/">${provider.active ? "Deactivate" : "Activate"}</a>
                    ${provider.is_default ? '<span class="api-default-label">Default</span>' : `<button type="button" class="button secondary" data-provider-default="${provider.id}">Set Default</button>`}
                </footer>
            </article>
        `).join("");
    }

    function renderModels() {
        const table = root.querySelector("[data-model-table]");
        table.innerHTML = `<thead><tr><th>Provider</th><th>Model</th><th>Family</th><th>Capabilities</th><th>Input Cost</th><th>Output Cost</th><th>Status</th><th>Default</th></tr></thead><tbody>${
            state.models.map(model => `<tr><td>${esc(model.provider)}</td><td><strong>${esc(model.display_name)}</strong><small>${esc(model.model_code)}</small></td><td>${esc(model.model_family)}</td><td>${esc(model.capabilities.join(", "))}</td><td>${model.input_cost_per_million == null ? "Not configured" : `$${model.input_cost_per_million}`}</td><td>${model.output_cost_per_million == null ? "Not configured" : `$${model.output_cost_per_million}`}</td><td>${model.active ? "Active" : "Inactive"}</td><td>${model.is_default_for_provider ? "Yes" : "No"}</td></tr>`).join("")
        }</tbody>`;
    }

    function providerOptions(selected = "") {
        return state.providers.map(item => `<option value="${item.id}" ${String(item.id) === String(selected) ? "selected" : ""}>${esc(item.name)}</option>`).join("");
    }

    function modelOptions(providerId, selected = "") {
        return state.models.filter(item => !providerId || String(item.provider_id) === String(providerId))
            .map(item => `<option value="${item.id}" ${String(item.id) === String(selected) ? "selected" : ""}>${esc(item.display_name)}</option>`).join("");
    }

    function renderRouting() {
        root.querySelector("[data-routing-list]").innerHTML = state.useCases.map(item => `
            <form class="api-routing-row" data-routing-id="${item.id}">
                <div><strong>${esc(item.display_name)}</strong><small>${esc(item.use_case_code)}</small></div>
                <label><span>Provider</span><select name="primary_provider_id">${providerOptions(item.primary_provider_id)}</select></label>
                <label><span>Model</span><select name="primary_model_id">${modelOptions(item.primary_provider_id, item.primary_model_id)}</select></label>
                <label><span>Selection</span><select name="selection_mode"><option value="priority" ${item.selection_mode === "priority" ? "selected" : ""}>Priority</option><option value="fixed" ${item.selection_mode === "fixed" ? "selected" : ""}>Fixed</option><option value="manual" ${item.selection_mode === "manual" ? "selected" : ""}>Manual</option></select></label>
                <label class="api-inline-toggle"><input type="checkbox" name="fallback_enabled" ${item.fallback_enabled ? "checked" : ""}> Fallback</label>
                <button type="submit" class="button secondary">Save</button>
            </form>
        `).join("");
    }

    function fillSelects() {
        root.querySelector("[data-playground-provider]").innerHTML = `<option value="">Automatic</option>${state.providers.filter(item => item.active).map(item => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join("")}`;
        root.querySelector("[data-playground-use-case]").innerHTML = state.useCases.map(item => `<option value="${esc(item.use_case_code)}">${esc(item.display_name)}</option>`).join("");
        root.querySelector("[data-model-provider]").innerHTML = providerOptions();
        updatePlaygroundModels();
    }

    function updatePlaygroundModels() {
        const providerCode = root.querySelector("[data-playground-provider]").value;
        const provider = state.providers.find(item => item.code === providerCode);
        root.querySelector("[data-playground-model]").innerHTML = `<option value="">Configured default</option>${state.models.filter(item => !provider || item.provider_id === provider.id).map(item => `<option value="${esc(item.model_code)}">${esc(item.display_name)}</option>`).join("")}`;
    }

    async function load() {
        status("Loading provider configuration...", "loading");
        try {
            const payload = await api(root.dataset.dashboardUrl);
            state.providers = payload.providers;
            state.models = payload.models;
            state.useCases = payload.use_cases;
            renderKpis(payload.summary);
            renderProviders();
            renderModels();
            renderRouting();
            fillSelects();
            status("");
        } catch (error) {
            status(error.message, "error");
        }
    }

    root.querySelectorAll("[data-api-tab]").forEach(button => button.addEventListener("click", async () => {
        root.querySelectorAll("[data-api-tab]").forEach(item => item.classList.toggle("is-active", item === button));
        root.querySelectorAll("[data-api-view]").forEach(view => view.hidden = view.dataset.apiView !== button.dataset.apiTab);
        if (button.dataset.apiTab === "health") await loadUsage();
    }));

    const providerDialog = root.querySelector("[data-provider-dialog]");
    const providerForm = root.querySelector("[data-provider-form]");
    root.querySelector("[data-provider-capabilities]").innerHTML = capabilities.map(item => `<label><input type="checkbox" name="capability" value="${item}"> ${esc(item.replaceAll("_", " "))}</label>`).join("");

    function openProvider(provider = null, credentialMode = false) {
        providerForm.reset();
        providerForm.elements.id.value = provider?.id || "";
        ["code", "name", "provider_type", "description", "base_url", "api_version", "priority", "selection_mode", "timeout_seconds", "retry_count", "monthly_budget"].forEach(field => {
            if (provider && provider[field] != null) providerForm.elements[field].value = provider[field];
        });
        ["active", "is_default", "allow_fallback"].forEach(field => providerForm.elements[field].checked = provider ? Boolean(provider[field]) : field === "allow_fallback");
        providerForm.querySelectorAll("[name='capability']").forEach(input => input.checked = Boolean(provider?.capabilities.includes(input.value)));
        providerForm.elements.code.disabled = Boolean(provider);
        if (credentialMode) {
            providerForm.elements.active.checked = true;
            root.querySelector("[data-provider-form-title]").textContent = `Set credential · ${provider.name}`;
        } else {
            root.querySelector("[data-provider-form-title]").textContent = provider ? `Configure ${provider.name}` : "Add Custom Provider";
        }
        providerDialog.showModal();
        if (credentialMode) window.setTimeout(() => providerForm.elements.credential.focus(), 0);
    }

    root.querySelector("[data-add-provider]").addEventListener("click", () => openProvider());
    root.addEventListener("click", async event => {
        const edit = event.target.closest("[data-provider-edit]");
        const setDefault = event.target.closest("[data-provider-default]");
        if (edit) openProvider(state.providers.find(item => item.id === Number(edit.dataset.providerEdit)));
        if (setDefault) {
            await api(`/api/ai/providers/${setDefault.dataset.providerDefault}/set-default/`, {method: "POST", body: "{}"});
            await load();
        }
    });

    providerForm.addEventListener("submit", async event => {
        event.preventDefault();
        const form = new FormData(providerForm);
        const id = form.get("id");
        const payload = Object.fromEntries(form.entries());
        payload.priority = Number(payload.priority);
        payload.timeout_seconds = Number(payload.timeout_seconds);
        payload.retry_count = Number(payload.retry_count);
        payload.monthly_budget = payload.monthly_budget || null;
        payload.active = providerForm.elements.active.checked;
        payload.is_default = providerForm.elements.is_default.checked;
        payload.allow_fallback = providerForm.elements.allow_fallback.checked;
        payload.capabilities = Array.from(providerForm.querySelectorAll("[name='capability']:checked")).map(item => item.value);
        delete payload.credential;
        delete payload.capability;
        try {
            let provider;
            if (id) {
                provider = (await api(`/api/ai/providers/${id}/`, {method: "PATCH", body: JSON.stringify(payload)})).item;
            } else {
                provider = (await api(root.dataset.providersUrl, {method: "POST", body: JSON.stringify(payload)})).item;
            }
            const credential = form.get("credential");
            if (credential) await api(`/api/ai/providers/${provider.id}/credentials/`, {method: "POST", body: JSON.stringify({credential})});
            providerDialog.close();
            await load();
            status("Provider configuration saved.");
        } catch (error) { status(error.message, "error"); }
    });

    const modelDialog = root.querySelector("[data-model-dialog]");
    const modelForm = root.querySelector("[data-model-form]");
    root.querySelector("[data-add-model]").addEventListener("click", () => { modelForm.reset(); modelDialog.showModal(); });
    modelForm.addEventListener("submit", async event => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(modelForm).entries());
        payload.provider_id = Number(payload.provider_id);
        ["active", "is_default_for_provider", "supports_structured_output", "supports_embeddings", "supports_audio_transcription"].forEach(field => payload[field] = modelForm.elements[field].checked);
        payload.capabilities = ["text_generation"];
        if (payload.supports_structured_output) payload.capabilities.push("structured_output");
        if (payload.supports_embeddings) payload.capabilities.push("embeddings");
        if (payload.supports_audio_transcription) payload.capabilities.push("audio_transcription");
        try {
            await api(root.dataset.modelsUrl, {method: "POST", body: JSON.stringify(payload)});
            modelDialog.close();
            await load();
            status("Provider model added.");
        } catch (error) { status(error.message, "error"); }
    });

    root.addEventListener("submit", async event => {
        const form = event.target.closest("[data-routing-id]");
        if (!form) return;
        event.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        data.primary_provider_id = Number(data.primary_provider_id);
        data.primary_model_id = Number(data.primary_model_id);
        data.fallback_enabled = form.elements.fallback_enabled.checked;
        try {
            await api(`${root.dataset.routingUrl}${form.dataset.routingId}/`, {method: "PATCH", body: JSON.stringify(data)});
            status("Use case routing saved.");
            await load();
        } catch (error) { status(error.message, "error"); }
    });

    root.querySelector("[data-playground-provider]").addEventListener("change", updatePlaygroundModels);
    root.querySelector("[data-playground-form]").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const payload = Object.fromEntries(new FormData(form).entries());
        payload.temperature = Number(payload.temperature);
        payload.maximum_output_tokens = Number(payload.maximum_output_tokens);
        const output = root.querySelector("[data-playground-result]");
        output.textContent = "Running provider test...";
        try {
            const result = await api(root.dataset.playgroundUrl, {method: "POST", body: JSON.stringify(payload)});
            output.textContent = JSON.stringify(result.result, null, 2);
            await load();
        } catch (error) { output.textContent = error.message; }
    });

    async function loadUsage() {
        try {
            const payload = await api(root.dataset.usageUrl);
            root.querySelector("[data-usage-table]").innerHTML = `<thead><tr><th>Provider</th><th>Requests</th><th>Failures</th><th>Fallbacks</th><th>Average Latency</th><th>Cost</th></tr></thead><tbody>${payload.items.map(item => `<tr><td>${esc(item.provider_code)}</td><td>${item.requests}</td><td>${item.failures}</td><td>${item.fallbacks}</td><td>${Number(item.latency || 0).toFixed(0)} ms</td><td>$${Number(item.cost || 0).toFixed(4)}</td></tr>`).join("")}</tbody>`;
        } catch (error) { status(error.message, "error"); }
    }

    root.querySelector("[data-health-all]").addEventListener("click", async () => {
        status("Running provider health checks...", "loading");
        try {
            const payload = await api(root.dataset.healthUrl, {method: "POST", body: "{}"});
            status(`Health checks completed for ${payload.items.length} active provider(s).`);
            await load();
        } catch (error) { status(error.message, "error"); }
    });

    load();
})();
