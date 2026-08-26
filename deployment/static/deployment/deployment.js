(() => {
    const root = document.querySelector("[data-deployment-root]");
    if (!root) return;

    const state = { targets: [], plans: [], releases: [], flags: {} };
    const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
    const csrf = () => document.cookie.split("; ").find((part) => part.startsWith("csrftoken="))?.split("=")[1] || "";
    const status = (message = "", error = false) => {
        const node = root.querySelector("[data-status]");
        node.textContent = message;
        node.classList.toggle("is-error", error);
    };
    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: {"Accept":"application/json", "Content-Type":"application/json", "X-CSRFToken":csrf(), ...(options.headers || {})},
        });
        const type = response.headers.get("content-type") || "";
        if (!type.includes("application/json")) {
            if (response.status === 403) {
                throw new Error("Your security session expired or the CSRF token is missing. Refresh this page and retry.");
            }
            throw new Error(`Invalid server response (${response.status}).`);
        }
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
        return payload;
    }
    const badge = (value) => `<span class="deployment-badge" data-status="${esc(value)}">${esc(value)}</span>`;
    const actionButton = (label, attr, id, secondary = true) => `<button type="button" class="button ${secondary ? "secondary" : ""}" ${attr}="${esc(id)}">${esc(label)}</button>`;

    function renderTargets() {
        const list = root.querySelector("[data-target-list]");
        list.innerHTML = state.targets.map((item) => `
            <article class="deployment-target">
                <div class="deployment-target-head"><div><h3>${esc(item.name)}</h3><p>${esc(item.dns_name || item.hostname || item.ip_address)} · ${esc(item.environment)}</p></div>${badge(item.status)}</div>
                <div class="deployment-target-grid">
                    <div><span>Operating system</span><strong>${esc(item.operating_system || item.os_family)}</strong></div>
                    <div><span>Connection</span><strong>${esc(item.connection_mode.toUpperCase())} · ${esc(item.port)}</strong></div>
                    <div><span>Credential</span><strong>${esc(item.credential_status)}</strong></div>
                    <div><span>Approval</span><strong>${item.is_approved ? "Approved" : "Required"}</strong></div>
                    <div><span>Host key</span><strong>${item.host_key_verified ? "Verified" : "Not verified"}</strong></div>
                    <div><span>Last check</span><strong>${item.last_connection_test_at ? new Date(item.last_connection_test_at).toLocaleString() : "Never"}</strong></div>
                </div>
                <div class="deployment-actions">
                    ${item.is_approved ? actionButton("Deploy latest main", "data-quick-deploy", item.id, false) : ""}
                    ${actionButton("Test connection", "data-test-target", item.id)}
                    ${actionButton("Run pre-check", "data-precheck-target", item.id)}
                    ${actionButton("Troubleshoot", "data-troubleshoot-target", item.id)}
                    ${actionButton("System Doctor", "data-system-doctor-target", item.id)}
                    ${actionButton("Repair safe issues", "data-system-repair-target", item.id)}
                    ${actionButton("Credential", "data-credential-target", item.id)}
                    ${!item.is_approved ? actionButton("Approve target", "data-approve-target", item.id, false) : ""}
                </div>
            </article>
        `).join("") || `<p>No target server is registered.</p>`;
    }

    function renderPlans() {
        root.querySelector("[data-plan-list]").innerHTML = state.plans.map((item) => `
            <tr><td><strong>${esc(item.name)}</strong></td><td>${esc(item.target_name)}</td><td>${esc(item.release_version || "-")}</td><td>${badge(item.status)}</td><td>${new Date(item.created_at).toLocaleString()}</td><td>${actionButton("Dry Run", "data-dry-run", item.id)}</td></tr>
        `).join("") || `<tr><td colspan="6">No deployment plan has been created.</td></tr>`;
    }

    function renderReleases() {
        root.querySelector("[data-release-list]").innerHTML = state.releases.map((item) => `
            <tr><td><strong>${esc(item.version)}</strong></td><td>${esc(item.git_branch || "-")}</td><td><code>${esc((item.git_commit || "-").slice(0, 12))}</code></td><td>${badge(item.status)}</td><td>${item.status !== "Validated" ? actionButton("Validate", "data-validate-release", item.id) : ""}</td></tr>
        `).join("") || `<tr><td colspan="5">No application release is available.</td></tr>`;
    }

    function renderReadiness() {
        const labels = {
            deployment_process: "Deployment Process",
            remote_deployment: "Remote Deployment",
            production_deployment: "Production Deployment",
            deployment_agent: "Deployment Agent",
            automatic_rollback: "Automatic Rollback",
            offline_deployment: "Offline Deployment",
        };
        root.querySelector("[data-readiness]").innerHTML = Object.entries(labels).map(([key, label]) => `<div class="deployment-flag"><strong>${label}</strong>${badge(state.flags[key] ?? "Disabled")}</div>`).join("");
    }

    function fillPlanOptions() {
        root.querySelector("[data-plan-target]").innerHTML = state.targets.map((item) => `<option value="${item.id}">${esc(item.name)} · ${esc(item.environment)}</option>`).join("");
        root.querySelector("[data-plan-release]").innerHTML = state.releases.map((item) => `<option value="${item.id}">${esc(item.version)} · ${esc(item.status)}</option>`).join("");
    }

    function showResult(title, result) {
        const dialog = root.querySelector("[data-result-dialog]");
        dialog.querySelector("[data-result-title]").textContent = title;
        dialog.querySelector("[data-result-content]").removeAttribute("aria-busy");
        const checks = result.checks || result.precheck?.checks || [];
        const validations = result.validation_checks || [];
        const actions = result.actions_taken || [];
        const manualActions = result.manual_actions || [];
        dialog.querySelector("[data-result-content]").innerHTML = `
            ${result.status ? `<p>${badge(result.status)}</p>` : ""}
            <div class="deployment-check-list">${[...checks, ...validations].map((item) => `<div class="deployment-check"><div><strong>${esc(item.name || item.code)}</strong><small>${esc(item.value || item.message || "")}</small>${item.recommendation ? `<small class="deployment-check-action">Recommended: ${esc(item.recommendation)}</small>` : ""}</div>${badge(item.status)}</div>`).join("")}</div>
            ${result.message ? `<p>${esc(result.message)}</p>` : ""}
            ${actions.length ? `<section class="deployment-remediation"><h3>Automatic actions</h3>${actions.map((item) => `<p>${esc(item)}</p>`).join("")}</section>` : ""}
            ${manualActions.length ? `<section class="deployment-remediation is-manual"><h3>Administrator action required</h3>${manualActions.map((item) => `<div><strong>${esc(item.title)}</strong><p>${esc(item.detail || "")}</p>${item.command ? `<code>${esc(item.command)}</code>` : ""}</div>`).join("")}</section>` : ""}
            ${result.host_key_fingerprint ? `<p><strong>SSH host key:</strong> <code>${esc(result.host_key_fingerprint)}</code></p>` : ""}
            ${result.changes_applied === 0 ? `<p><strong>No target change was applied.</strong></p>` : ""}
        `;
        dialog.showModal();
    }

    function showCheckPending(title, message) {
        const dialog = root.querySelector("[data-result-dialog]");
        dialog.querySelector("[data-result-title]").textContent = title;
        const content = dialog.querySelector("[data-result-content]");
        content.setAttribute("aria-busy", "true");
        content.innerHTML = `<div class="deployment-check-pending"><i class="deployment-spinner" aria-hidden="true"></i><div><strong>${esc(message)}</strong><p>This can take up to one minute. Do not close the page.</p></div></div>`;
        if (!dialog.open) dialog.showModal();
    }

    function showJob(job) {
        const dialog = root.querySelector("[data-result-dialog]");
        dialog.querySelector("[data-result-title]").textContent = "Mining360 Deployment";
        const logs = job.logs || [];
        const isActive = ["Preparing", "Queued", "Running", "Waiting for Manual Action"].includes(job.status);
        dialog.querySelector("[data-result-content]").innerHTML = `
            <div class="deployment-job-summary">
                <span class="deployment-job-state">${isActive ? '<i class="deployment-spinner" aria-hidden="true"></i>' : ""}${badge(job.status)}</span>
                <strong>${esc(job.progress_percentage)}%</strong>
            </div>
            <div class="deployment-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${esc(job.progress_percentage)}"><i style="width:${Math.max(0, Math.min(100, Number(job.progress_percentage) || 0))}%"></i></div>
            <p>${esc(job.current_step ? `Current step: ${job.current_step}` : "Waiting for deployment worker...")}</p>
            ${job.failure_message ? `<p class="deployment-error">${esc(job.failure_message)}</p>` : ""}
            ${job.status === "Failed" && job.target_id ? `<button type="button" class="button secondary" data-troubleshoot-target="${esc(job.target_id)}">Troubleshoot failure</button>` : ""}
            <div class="deployment-job-logs">${logs.map((log) => `<p><time>${new Date(log.created_at).toLocaleTimeString()}</time><strong>${esc(log.level)}</strong>${esc(log.message)}</p>`).join("")}</div>
        `;
        if (!dialog.open) dialog.showModal();
    }

    function showDeploymentPending() {
        showJob({
            status: "Preparing",
            progress_percentage: 5,
            current_step: "Synchronizing the latest Git release and running readiness checks...",
            logs: [],
        });
        const content = root.querySelector("[data-result-content]");
        content.setAttribute("aria-busy", "true");
    }

    function showDeploymentError(message) {
        const dialog = root.querySelector("[data-result-dialog]");
        dialog.querySelector("[data-result-title]").textContent = "Deployment could not start";
        dialog.querySelector("[data-result-content]").innerHTML = `
            <div class="deployment-inline-error" role="alert">
                <strong>Deployment failed</strong>
                <p>${esc(message)}</p>
            </div>
        `;
        dialog.querySelector("[data-result-content]").removeAttribute("aria-busy");
        if (!dialog.open) dialog.showModal();
    }

    function setDeployButtonLoading(button, loading) {
        if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
        button.disabled = loading;
        button.setAttribute("aria-busy", String(loading));
        button.textContent = loading ? "Deploying..." : button.dataset.defaultLabel;
    }

    function setActionButtonLoading(button, loading, label = "Checking...") {
        if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
        button.disabled = loading;
        button.setAttribute("aria-busy", String(loading));
        button.textContent = loading ? label : button.dataset.defaultLabel;
    }

    const sleep = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
    async function trackJob(jobId) {
        let networkFailures = 0;
        for (let attempt = 0; attempt < 300; attempt += 1) {
            try {
                const payload = await api(`/api/deployment/jobs/${jobId}/`);
                networkFailures = 0;
                showJob(payload.job);
                if (["Succeeded", "Failed", "Cancelled", "Rolled Back"].includes(payload.job.status)) {
                    await load();
                    status(payload.job.status === "Succeeded" ? "Deployment completed successfully." : "Deployment did not complete.", payload.job.status !== "Succeeded");
                    return;
                }
            } catch (error) {
                networkFailures += 1;
                status("Application restart in progress. Reconnecting...", false);
                if (networkFailures > 20) throw error;
            }
            await sleep(3000);
        }
        throw new Error("Deployment status timed out.");
    }

    async function load() {
        status("Loading deployment configuration...");
        try {
            const payload = await api(root.dataset.dashboardUrl);
            state.targets = payload.targets;
            state.plans = payload.plans;
            state.releases = payload.releases;
            state.flags = payload.feature_flags;
            Object.entries(payload.summary).forEach(([key, value]) => { const node = root.querySelector(`[data-kpi="${key}"]`); if (node) node.textContent = value; });
            renderTargets(); renderPlans(); renderReleases(); renderReadiness(); fillPlanOptions();
            status("");
        } catch (error) { status(error.message, true); }
    }

    root.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
        root.querySelectorAll("[data-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
        root.querySelectorAll("[data-view]").forEach((view) => { view.hidden = view.dataset.view !== button.dataset.tab; });
    }));
    root.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
    root.querySelector("[data-refresh]").addEventListener("click", load);
    root.querySelector("[data-add-target]").addEventListener("click", () => root.querySelector("[data-target-dialog]").showModal());
    root.querySelector("[data-create-plan]").addEventListener("click", () => root.querySelector("[data-plan-dialog]").showModal());

    root.querySelector("[data-credential-form]").addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(event.currentTarget));
        const targetId = payload.target_id;
        delete payload.target_id;
        try {
            await api(`/api/deployment/targets/${targetId}/credential/`, {method:"POST", body:JSON.stringify(payload)});
            event.currentTarget.closest("dialog").close();
            event.currentTarget.reset();
            await load();
            status("Deployment credential configured.");
        } catch (error) { status(error.message, true); }
    });

    root.querySelector("[data-target-form]").addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(event.currentTarget));
        payload.port = Number(payload.port);
        try { await api(root.dataset.targetsUrl, {method:"POST", body:JSON.stringify(payload)}); event.currentTarget.closest("dialog").close(); event.currentTarget.reset(); await load(); }
        catch (error) { status(error.message, true); }
    });
    root.querySelector("[data-plan-form]").addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(event.currentTarget));
        payload.target_id = Number(payload.target_id); payload.release_id = Number(payload.release_id);
        try { await api(root.dataset.plansUrl, {method:"POST", body:JSON.stringify(payload)}); event.currentTarget.closest("dialog").close(); await load(); }
        catch (error) { status(error.message, true); }
    });

    root.addEventListener("click", async (event) => {
        const test = event.target.closest("[data-test-target]");
        const precheck = event.target.closest("[data-precheck-target]");
        const troubleshoot = event.target.closest("[data-troubleshoot-target]");
        const systemDoctor = event.target.closest("[data-system-doctor-target]");
        const systemRepair = event.target.closest("[data-system-repair-target]");
        const approve = event.target.closest("[data-approve-target]");
        const dryRun = event.target.closest("[data-dry-run]");
        const validate = event.target.closest("[data-validate-release]");
        const quickDeploy = event.target.closest("[data-quick-deploy]");
        const credential = event.target.closest("[data-credential-target]");
        if (credential) {
            const target = state.targets.find((item) => item.id === Number(credential.dataset.credentialTarget));
            const form = root.querySelector("[data-credential-form]");
            form.reset();
            form.elements.target_id.value = target.id;
            form.elements.name.value = `${target.name} SSH`;
            form.elements.username.value = target.ssh_username || "";
            root.querySelector("[data-credential-dialog]").showModal();
            return;
        }
        if (quickDeploy) {
            setDeployButtonLoading(quickDeploy, true);
            showDeploymentPending();
            status("Synchronizing the latest Git release and running readiness checks...");
            try {
                const payload = await api(root.dataset.quickDeployUrl, {
                    method: "POST",
                    body: JSON.stringify({target_id: Number(quickDeploy.dataset.quickDeploy), confirmation: "DEPLOY"}),
                });
                root.querySelector("[data-result-content]").removeAttribute("aria-busy");
                showJob(payload.job);
                await trackJob(payload.job.id);
            } catch (error) {
                showDeploymentError(error.message);
                status(error.message, true);
            }
            finally { setDeployButtonLoading(quickDeploy, false); }
            return;
        }
        const action = test || precheck || troubleshoot || systemDoctor || systemRepair || approve || dryRun || validate;
        if (!action) return;
        const pendingTitle = systemRepair ? "System Doctor Repair" : systemDoctor ? "Mining360 System Doctor" : troubleshoot ? "Deployment Troubleshooting" : test ? "Connection Test" : precheck ? "Server Pre-check" : "Controlled Check";
        const pendingMessage = systemDoctor || systemRepair ? "Checking database, migrations, integrations, runtime, release and deployment readiness..." : troubleshoot ? "Diagnosing the server, deployment runtime and folder permissions..." : test ? "Testing DNS, TCP, SSH and credentials..." : "Checking server readiness...";
        setActionButtonLoading(action, true, systemRepair ? "Repairing..." : systemDoctor ? "Diagnosing..." : troubleshoot ? "Troubleshooting..." : "Checking...");
        if (test || precheck || troubleshoot || systemDoctor || systemRepair) showCheckPending(pendingTitle, pendingMessage);
        status("Running controlled check...");
        try {
            if (test) { const payload = await api(`/api/deployment/targets/${test.dataset.testTarget}/test-connection/`, {method:"POST", body:"{}"}); showResult("Connection Test", payload.result); }
            if (precheck) { const payload = await api(`/api/deployment/targets/${precheck.dataset.precheckTarget}/precheck/`, {method:"POST", body:"{}"}); showResult("Server Pre-check", payload.result); }
            if (troubleshoot) { const payload = await api(`/api/deployment/targets/${troubleshoot.dataset.troubleshootTarget}/troubleshoot/`, {method:"POST", body:"{}"}); showResult("Deployment Troubleshooting", payload.result); }
            if (systemDoctor) { const payload = await api(`/api/deployment/targets/${systemDoctor.dataset.systemDoctorTarget}/system-doctor/`, {method:"POST", body:JSON.stringify({repair:false})}); showResult("Mining360 System Doctor", payload.result); }
            if (systemRepair) { const payload = await api(`/api/deployment/targets/${systemRepair.dataset.systemRepairTarget}/system-doctor/`, {method:"POST", body:JSON.stringify({repair:true})}); showResult("System Doctor · Safe Repair", payload.result); }
            if (approve) await api(`/api/deployment/targets/${approve.dataset.approveTarget}/approve/`, {method:"POST", body:"{}"});
            if (dryRun) { const payload = await api(`/api/deployment/plans/${dryRun.dataset.dryRun}/dry-run/`, {method:"POST", body:"{}"}); showResult("Deployment Readiness Report", payload.result); }
            if (validate) await api(`/api/deployment/releases/${validate.dataset.validateRelease}/validate/`, {method:"POST", body:"{}"});
            await load();
        } catch (error) { showDeploymentError(error.message); status(error.message, true); }
        finally { setActionButtonLoading(action, false); }
    });
    load();
})();
