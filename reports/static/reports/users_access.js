(() => {
    const root = document.querySelector("[data-users-access]");
    if (!root) return;

    const $ = (selector, parent = document) => parent.querySelector(selector);
    const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
    const csrf = $("[name=csrfmiddlewaretoken]")?.value || "";
    const roleLabels = { excellence_center: "Excellence Center", business_overview: "Business Overview", site: "Site", reporting: "Reporting", chatbot: "Chatbot", resources: "Ressources", admin: "Admin", super_admin: "Super Admin" };
    const bpDescriptions = {
        "": "No access to Business Performance data.",
        Executive: "Organization-wide executive performance access.",
        "Business Manager": "Business-level performance management access.",
        "Country Manager": "Access limited to selected countries.",
        "Account Manager": "Access limited to selected customers.",
        MineSite: "Access strictly limited to one authorized MineSite across Mining 360, AI and Power BI.",
        Viewer: "Read-only access to the configured scope.",
        Administrator: "Full Business Performance administration.",
    };
    const state = {
        page: 1, pages: 1, query: "", status: "", role: "", source: "", bp: "", ordering: "display_name", audience: "neemba",
        users: [], options: null, form: null, mode: null, dirty: false, selectedResult: -1,
        usersController: null, directoryController: null, usersTimer: null, directoryTimer: null,
        lastDirectoryQuery: "", directoryCache: new Map(), confirmResolve: null,
    };
    const drawerLayer = $("[data-drawer-layer]", root);
    const confirmLayer = $("[data-confirm-layer]", root);
    const toastLayer = $("[data-toast]", root);
    document.body.append(drawerLayer, confirmLayer, toastLayer);

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
    }

    function initials(name) {
        return String(name || "User").split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase();
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json", "X-CSRFToken": csrf } : {}), ...(options.headers || {}) },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(payload.error || "The request could not be completed.");
            error.payload = payload;
            throw error;
        }
        return payload;
    }

    function toast(message) {
        const node = $("[data-toast]");
        node.textContent = message;
        node.hidden = false;
        clearTimeout(node._timer);
        node._timer = setTimeout(() => { node.hidden = true; }, 4200);
    }

    function setUsersState(name) {
        $("[data-users-loading]").hidden = name !== "loading";
        $("[data-users-error]").hidden = name !== "error";
        $("[data-users-table-wrap]").hidden = name !== "ready";
        $("[data-users-mobile]").hidden = name !== "ready";
        $("[data-users-empty]").hidden = name !== "empty";
    }

    async function loadUsers() {
        state.usersController?.abort();
        state.usersController = new AbortController();
        setUsersState("loading");
        const params = new URLSearchParams({ page: state.page, page_size: 25, ordering: state.ordering, audience: state.audience });
        if (state.query) params.set("q", state.query);
        if (state.status) params.set("status", state.status);
        if (state.role) params.set("role", state.role);
        if (state.source) params.set("access_source", state.source);
        if (state.bp) params.set("business_performance", state.bp);
        try {
            const payload = await api(`/api/access-control/users/?${params}`, { signal: state.usersController.signal });
            state.users = payload.results;
            state.pages = payload.pages || 1;
            renderUsers(payload);
        } catch (error) {
            if (error.name !== "AbortError") setUsersState("error");
        }
    }

    function roleChips(user) {
        if (!user.platform_roles.length) return '<span class="muted-value">No roles</span>';
        return `<div class="role-chips">${user.platform_roles.map(role => `<span>${escapeHtml(roleLabels[role] || role)}</span>`).join("")}</div>`;
    }

    function scopeText(user) {
        const parts = [];
        if (user.countries.length) parts.push(`${user.countries.length} ${user.countries.length === 1 ? "country" : "countries"}`);
        if (user.customers.length) parts.push(`${user.customers.length} ${user.customers.length === 1 ? "customer" : "customers"}`);
        if (user.minesites?.length) parts.push(user.minesites[0]);
        return parts.join(" · ") || "No scope";
    }

    function sourceLabel(source) {
        return source === "ad_groups" ? "AD Groups" : source === "mixed" ? "Mixed" : "Manual";
    }

    function renderUsers(payload) {
        const summary = payload.summary || {};
        $("[data-summary-total]").textContent = summary.total ?? payload.count;
        $("[data-summary-active]").textContent = summary.active ?? 0;
        $("[data-summary-admins]").textContent = summary.administrators ?? 0;
        $("[data-summary-ad]").textContent = summary.ad_managed ?? 0;
        $$("[data-audience-count]").forEach(node => { node.textContent = summary[node.dataset.audienceCount] ?? 0; });
        const platformUsers = state.audience === "system";
        $("#authorized-users-title").textContent = platformUsers ? "Utilisateurs créés dans Mining360" : "Utilisateurs Neemba";
        $("[data-result-count]").textContent = `${payload.count} ${payload.count === 1 ? "utilisateur" : "utilisateurs"}`;
        renderActiveFilters();
        if (!state.users.length) {
            setUsersState("empty");
            $("[data-pagination]").hidden = true;
            return;
        }
        const rows = state.users.map(user => `
            <tr tabindex="0" data-user-row="${user.id}" aria-label="Open access for ${escapeHtml(user.display_name)}">
                <td><div class="user-cell"><span class="user-avatar">${escapeHtml(initials(user.display_name))}</span><span><strong>${escapeHtml(user.display_name)}</strong><small title="${escapeHtml(user.upn)}">${escapeHtml(user.upn)}</small></span></div></td>
                <td>${roleChips(user)}</td>
                <td title="${escapeHtml([...user.countries, ...user.customers, ...(user.minesites || [])].join(", "))}">${escapeHtml(scopeText(user))}</td>
                <td>${escapeHtml(user.powerbi_rls_role || "Not configured")}</td><td><span class="source-badge">${user.auth_source === "local" ? "Créé dans Mining360" : "Neemba"}</span></td>
                <td><span class="status-badge status-badge--${user.status}">${user.status === "active" ? "Active" : "Disabled"}</span></td>
                <td><button type="button" class="access-icon-button row-more" data-user-open="${user.id}" aria-label="View access for ${escapeHtml(user.display_name)}">•••</button></td>
            </tr>`).join("");
        $("[data-users-tbody]").innerHTML = rows;
        $("[data-users-mobile]").innerHTML = state.users.map(user => `
            <article class="authorized-user-card" data-user-row="${user.id}">
                <div class="user-cell"><span class="user-avatar">${escapeHtml(initials(user.display_name))}</span><span><strong>${escapeHtml(user.display_name)}</strong><small>${escapeHtml(user.upn)}</small></span></div>
                ${roleChips(user)}<dl><div><dt>Périmètre</dt><dd>${escapeHtml(scopeText(user))}</dd></div><div><dt>Origine</dt><dd>${platformUsers ? "Créé dans Mining360" : "Neemba (annuaire d’entreprise)"}</dd></div></dl>
                <div class="mobile-user-footer"><span class="status-badge status-badge--${user.status}">${user.status === "active" ? "Active" : "Disabled"}</span><button class="button secondary" type="button" data-user-open="${user.id}">View access</button></div>
            </article>`).join("");
        setUsersState("ready");
        $("[data-pagination]").hidden = payload.pages <= 1;
        $("[data-page-summary]").textContent = `Page ${payload.page} of ${payload.pages}`;
        $("[data-page-label]").textContent = `${payload.page} / ${payload.pages}`;
        $("[data-page-prev]").disabled = payload.page <= 1;
        $("[data-page-next]").disabled = payload.page >= payload.pages;
    }

    function renderActiveFilters() {
        const node = $("[data-active-filters]");
        const filters = [["Search", state.query], ["Status", state.status], ["Role", roleLabels[state.role]], ["Source", state.source ? sourceLabel(state.source) : ""], ["Business Performance", state.bp === "none" ? "No access" : state.bp]]
            .filter(([, value]) => value);
        node.hidden = !filters.length;
        node.innerHTML = filters.map(([label, value]) => `<span>${escapeHtml(label)}: ${escapeHtml(value)}</span>`).join("");
    }

    async function loadOptions() {
        if (state.options) return state.options;
        state.options = await api("/api/access-control/options/");
        $("[data-filter-role]").innerHTML = '<option value="">All roles</option>' + state.options.platform_roles.map(role => `<option value="${escapeHtml(role.code)}">${escapeHtml(role.label)}</option>`).join("");
        return state.options;
    }

    function openDrawer(mode) {
        state.mode = mode;
        state.dirty = false;
        $("[data-drawer-layer]").hidden = false;
        document.body.classList.add("access-drawer-open");
        $("[data-drawer]").setAttribute("tabindex", "-1");
        $("[data-drawer]").focus();
    }

    function requestCloseDrawer() {
        if (state.dirty && !window.confirm("Discard unsaved changes?")) return;
        closeDrawer();
    }

    function closeDrawer() {
        $("[data-drawer-layer]").hidden = true;
        document.body.classList.remove("access-drawer-open");
        state.mode = null;
        state.form = null;
        state.dirty = false;
        state.directoryController?.abort();
    }

    async function startAdd() {
        openDrawer("search");
        $("[data-drawer-title]").textContent = "Add user from company directory";
        $("[data-directory-step]").hidden = false;
        $("[data-access-form]").hidden = true;
        $("[data-drawer-footer]").hidden = true;
        const input = $("[data-directory-query]");
        input.value = "";
        $("[data-directory-results]").innerHTML = "";
        $("[data-directory-state]").textContent = "Start typing at least two characters.";
        setTimeout(() => input.focus(), 30);
        loadOptions().catch(() => toast("Access options could not be loaded."));
    }

    async function searchDirectory(query) {
        const normalized = query.trim().replace(/\s+/g, " ");
        if (normalized.length < 2) {
            $("[data-directory-state]").textContent = "Start typing at least two characters.";
            $("[data-directory-results]").innerHTML = "";
            return;
        }
        if (state.directoryCache.has(normalized.toLowerCase())) return renderDirectory(state.directoryCache.get(normalized.toLowerCase()), normalized);
        state.directoryController?.abort();
        state.directoryController = new AbortController();
        $("[data-directory-state]").textContent = "Searching company directory...";
        try {
            const payload = await api(`/api/access-control/directory/search/?q=${encodeURIComponent(normalized)}`, { signal: state.directoryController.signal });
            state.directoryCache.set(normalized.toLowerCase(), payload.results);
            renderDirectory(payload.results, normalized);
        } catch (error) {
            if (error.name !== "AbortError") {
                $("[data-directory-state]").innerHTML = `The company directory could not be searched. <button type="button" data-directory-retry>Retry</button>`;
            }
        }
    }

    function renderDirectory(results, query) {
        state.selectedResult = -1;
        $("[data-directory-state]").textContent = results.length ? `${results.length} ${results.length === 1 ? "user" : "users"} found` : `No directory user found for “${query}”.`;
        $("[data-directory-results]").innerHTML = results.map((user, index) => `
            <div class="directory-result" role="option" tabindex="-1" data-directory-index="${index}" data-directory-id="${escapeHtml(user.directory_object_id)}">
                <span class="user-avatar">${escapeHtml(initials(user.display_name))}</span><span class="directory-result__identity"><strong>${escapeHtml(user.display_name)}</strong><small>${escapeHtml(user.upn)}</small><em>${escapeHtml(user.account_name || user.company || "Active Directory")}</em></span>
                <button type="button" class="button ${user.already_authorized ? "secondary" : ""}" data-directory-select="${index}">${user.already_authorized ? "View user" : "Configure access"}</button>
            </div>`).join("");
        $("[data-directory-results]")._results = results;
    }

    function selectDirectoryResult(index) {
        const resultsNode = $("[data-directory-results]");
        const user = resultsNode._results?.[index];
        if (!user) return;
        if (user.already_authorized) return editUser(user.mining360_user_id);
        showAccessForm({
            id: null, display_name: user.display_name, upn: user.upn, email: user.email,
            directory_object_id: user.directory_object_id, directory_username: user.directory_username,
            auth_source: "active_directory", platform_roles: [], ad_managed_roles: [], directory_roles_managed: false,
            business_performance_access: "", countries: [], customers: [], minesites: [], powerbi_rls_role: "", report_rls_roles: {}, status: "active",
        }, "add");
    }

    async function editUser(id) {
        openDrawer("edit");
        $("[data-drawer-title]").textContent = "User access";
        $("[data-directory-step]").hidden = true;
        $("[data-access-form]").hidden = false;
        $("[data-access-form]").innerHTML = '<div class="drawer-section-loading"><span></span><span></span><span></span></div>';
        try {
            const [payload] = await Promise.all([api(`/api/access-control/users/${id}/`), loadOptions()]);
            restoreAccessFormMarkup();
            showAccessForm(payload.user, "edit");
            loadAudit(id);
        } catch (error) {
            $("[data-access-form]").innerHTML = `<div class="users-error"><p>${escapeHtml(error.message)}</p></div>`;
        }
    }

    const accessFormTemplate = $("[data-access-form]").innerHTML;
    function restoreAccessFormMarkup() {
        $("[data-access-form]").innerHTML = accessFormTemplate;
    }

    function showAccessForm(user, mode) {
        if (!$("[data-form-name]")) restoreAccessFormMarkup();
        state.mode = mode;
        state.form = { ...user, platform_roles: [...(user.platform_roles || [])], countries: [...(user.countries || [])], customers: [...(user.customers || [])], minesites: [...(user.minesites || [])], report_rls_roles: { ...(user.report_rls_roles || {}) } };
        $("[data-directory-step]").hidden = true;
        $("[data-access-form]").hidden = false;
        $("[data-drawer-footer]").hidden = false;
        $("[data-drawer-title]").textContent = mode === "add" ? "Configure access" : "User access";
        $("[data-form-avatar]").textContent = initials(user.display_name);
        $("[data-form-name]").textContent = user.display_name;
        $("[data-form-upn]").textContent = user.upn;
        $("[data-form-source]").textContent = user.auth_source === "active_directory" ? "Active Directory" : "Local account";
        $("[data-directory-object-id]").value = user.directory_object_id || "";
        $("[data-directory-username]").value = user.directory_username || "";
        renderRoleOptions();
        renderBusinessOptions();
        const presets = state.options.site_access_profiles || [];
        $("[data-focus-profiles-section]").hidden = !presets.length || state.form.directory_roles_managed;
        $("[data-focus-site-profile]").innerHTML = '<option value="">Choose a Focus site profile</option>' + presets.map(preset => `<option value="${escapeHtml(preset.id)}">${escapeHtml(preset.label)}</option>`).join("");
        renderMultiSelect("countries");
        renderMultiSelect("customers");
        renderMultiSelect("minesites");
        renderEffectiveSummary();
        $("[data-history-section]").hidden = mode !== "edit";
        $("[data-status-action]").hidden = mode !== "edit";
        $("[data-status-action]").textContent = user.status === "active" ? "Disable user" : "Enable user";
        $("[data-status-action]").classList.toggle("danger", user.status === "active");
        $("[data-save-access]").textContent = mode === "add" ? "Add user" : "Save changes";
        const protectedAccount = !state.options.can_manage_administrators && state.form.platform_roles.some(role => ["admin", "super_admin"].includes(role));
        $("[data-save-access]").disabled = protectedAccount;
        $("[data-status-action]").disabled = protectedAccount;
        $("[data-protected-account]").hidden = !protectedAccount;
        state.dirty = false;
    }

    function renderRoleOptions() {
        const locked = state.form.directory_roles_managed;
        $("[data-ad-managed-row]").hidden = state.form.auth_source !== "active_directory";
        $("[data-directory-managed]").checked = locked;
        $("[data-role-options]").innerHTML = state.options.platform_roles.map(role => `
            <label class="platform-role-option ${locked ? "is-locked" : ""}">
                <input type="checkbox" value="${escapeHtml(role.code)}" data-role-checkbox ${state.form.platform_roles.includes(role.code) ? "checked" : ""} ${locked || role.assignable === false ? "disabled" : ""}>
                <span><strong>${escapeHtml(role.label)}</strong><small>${escapeHtml(role.description)}</small>${locked && state.form.ad_managed_roles.includes(role.code) ? "<em>Managed by AD group</em>" : ""}</span>
            </label>`).join("");
    }

    function renderBusinessOptions() {
        $("[data-bp-role]").innerHTML = state.options.business_performance_levels.map(option => `<option value="${escapeHtml(option.value)}" ${option.value === "Administrator" && !state.options.can_manage_administrators ? "disabled" : ""}>${escapeHtml(option.label)}</option>`).join("");
        $("[data-bp-role]").value = state.form.business_performance_access || "";
        $("[data-bp-description]").textContent = bpDescriptions[state.form.business_performance_access || ""] || "Configured business access.";
        $("[data-scope-fields]").hidden = !state.form.business_performance_access;
        $("[data-minesite-scope]").hidden = state.form.business_performance_access !== "MineSite";
        $$('[data-general-scope]').forEach(node => { node.hidden = state.form.business_performance_access === "MineSite"; });
        const rlsOptions = [...state.options.powerbi_rls_roles];
        if (state.form.business_performance_access === "MineSite" && state.form.minesites.length === 1 && !rlsOptions.some(option => option.value === state.form.powerbi_rls_role)) {
            rlsOptions.push({ value: state.form.powerbi_rls_role, label: state.form.powerbi_rls_role });
        }
        $("[data-rls-role]").innerHTML = rlsOptions.map(option => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("");
        $("[data-rls-role]").value = state.form.powerbi_rls_role || "";
        $("[data-rls-role]").disabled = state.form.business_performance_access === "MineSite";
        const siteRole = state.form.platform_roles.includes("site");
        $("[data-site-role-settings]").hidden = !siteRole;
        const selectedSite = state.form.minesites.length === 1 ? state.form.minesites[0] : "";
        state.form.report_rls_roles = siteRole && selectedSite
            ? Object.fromEntries(state.options.site_rls_reports.map(report => [report.report_id, report.roles_by_site[selectedSite]]).filter(([, role]) => role))
            : {};
        $("[data-site-report-rls]").innerHTML = state.options.site_rls_reports.length ? "<ul class=\"site-rls-report-list\">" + state.options.site_rls_reports.map(report => {
            const role = selectedSite ? report.roles_by_site[selectedSite] : "";
            return "<li><span><strong>" + escapeHtml(report.label) + "</strong><small>" + escapeHtml(report.dataset_name) + "</small></span><code>" + escapeHtml(role || (selectedSite ? "RLS unavailable for this site" : "Select one MineSite")) + "</code></li>";
        }).join("") + "</ul>" : "<p>No validated RLS-enabled reports are configured.</p>";
        const siteRlsOptions = state.options.powerbi_rls_roles.filter(option => option.value && option.value.toLowerCase() !== "global");
        $("[data-site-report-rls]").innerHTML = state.options.site_rls_reports.length ? state.options.site_rls_reports.map(report => `
            <label class="access-field"><span>${escapeHtml(report.label)}</span><select data-site-report-rls-id="${escapeHtml(report.report_id)}">
                <option value="">Select report RLS role</option>${siteRlsOptions.map(option => `<option value="${escapeHtml(option.value)}" ${state.form.report_rls_roles[report.report_id] === option.value ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}
            </select><small>${escapeHtml(report.dataset_name)}</small></label>`).join("") : '<p>No validated RLS-enabled reports are configured.</p>';
    }

    function renderMultiSelect(key) {
        const host = $(`[data-multiselect="${key}"]`);
        const options = state.options[key] || [];
        const selected = state.form[key] || [];
        host.innerHTML = `<div class="access-multiselect__control">${selected.map(value => `<span class="scope-chip">${escapeHtml(value)}<button type="button" data-remove-scope="${escapeHtml(value)}" aria-label="Remove ${escapeHtml(value)}">×</button></span>`).join("")}<input type="search" placeholder="Search ${key}..." data-scope-search="${key}" aria-label="Search ${key}"></div><div class="access-multiselect__menu" data-scope-menu hidden></div>`;
        host._options = options;
    }

    function showScopeMenu(key, query = "") {
        const host = $(`[data-multiselect="${key}"]`);
        const menu = $("[data-scope-menu]", host);
        const normalized = query.trim().toLowerCase();
        const matches = host._options.filter(option => !state.form[key].includes(option.value) && (!normalized || option.label.toLowerCase().includes(normalized))).slice(0, 20);
        menu.innerHTML = matches.length ? matches.map(option => `<button type="button" data-add-scope="${escapeHtml(option.value)}">${escapeHtml(option.label)}</button>`).join("") : '<span>No available values</span>';
        menu.hidden = false;
    }

    function renderEffectiveSummary() {
        const roles = state.form.platform_roles.map(role => roleLabels[role] || role);
        $("[data-effective-summary]").innerHTML = `
            <div><dt>Platform</dt><dd>${escapeHtml(roles.join(", ") || "No roles")}</dd></div>
            <div><dt>Business Performance</dt><dd>${escapeHtml(state.form.business_performance_access || "No access")}</dd></div>
            <div><dt>Countries</dt><dd>${escapeHtml(state.form.countries.join(", ") || "All permitted / none configured")}</dd></div>
            <div><dt>Customers</dt><dd>${escapeHtml(state.form.customers.join(", ") || "All permitted / none configured")}</dd></div>
            <div><dt>MineSite</dt><dd>${escapeHtml(state.form.minesites.join(", ") || "Not restricted by MineSite")}</dd></div>
            <div><dt>Power BI RLS</dt><dd>${escapeHtml(state.form.powerbi_rls_role || "Not configured")}</dd></div>
            <div><dt>Managed by AD</dt><dd>${state.form.directory_roles_managed ? escapeHtml(state.form.ad_managed_roles.map(role => roleLabels[role] || role).join(", ") || "Enabled") : "No"}</dd></div>`;
    }

    function markDirty() { state.dirty = true; renderEffectiveSummary(); }

    function formPayload() {
        return {
            directory_object_id: state.form.directory_object_id,
            directory_username: state.form.directory_username,
            upn: state.form.upn,
            platform_roles: state.form.platform_roles,
            directory_roles_managed: state.form.directory_roles_managed,
            business_performance_access: state.form.business_performance_access,
            countries: state.form.countries,
            customers: state.form.customers,
            minesites: state.form.minesites,
            powerbi_rls_role: state.form.powerbi_rls_role,
            report_rls_roles: state.form.report_rls_roles,
        };
    }

    async function saveAccess() {
        const button = $("[data-save-access]");
        button.disabled = true;
        button.textContent = state.mode === "add" ? "Adding user..." : "Saving...";
        clearFormErrors();
        try {
            const adding = state.mode === "add";
            const url = state.mode === "add" ? "/api/access-control/users/" : `/api/access-control/users/${state.form.id}/access/`;
            const method = state.mode === "add" ? "POST" : "PATCH";
            const payload = await api(url, { method, body: JSON.stringify(formPayload()) });
            state.dirty = false;
            closeDrawer();
            await loadUsers();
            toast(adding ? `${payload.user.display_name} has been added to Mining 360.` : `${payload.user.display_name}'s access has been updated.`);
        } catch (error) {
            const fields = error.payload?.field_errors || {};
            Object.entries(fields).forEach(([field, message]) => {
                const node = $(`[data-error-${field}]`);
                if (node) { node.textContent = message; node.hidden = false; }
            });
            const formError = $("[data-form-error]");
            formError.textContent = error.message;
            formError.hidden = false;
        } finally {
            button.disabled = false;
            button.textContent = state.mode === "add" ? "Add user" : "Save changes";
        }
    }

    function clearFormErrors() {
        $$('[class="field-error"]').forEach(node => { node.hidden = true; node.textContent = ""; });
        const formError = $("[data-form-error]");
        if (formError) formError.hidden = true;
    }

    async function loadAudit(id) {
        const node = $("[data-access-history]");
        node.innerHTML = '<p class="muted-value">Loading access history...</p>';
        try {
            const payload = await api(`/api/access-control/users/${id}/audit/`);
            node.innerHTML = payload.results.length ? payload.results.map(item => `<div><strong>${escapeHtml(item.action_label)}</strong><span>${escapeHtml(item.actor)}</span><time datetime="${escapeHtml(item.created_at)}">${new Date(item.created_at).toLocaleString("en-GB")}</time></div>`).join("") : '<p class="muted-value">No access changes recorded yet.</p>';
        } catch { node.innerHTML = '<p class="field-error">Access history could not be loaded.</p>'; }
    }

    function confirmAction(title, message, actionLabel) {
        $("[data-confirm-title]").textContent = title;
        $("[data-confirm-message]").textContent = message;
        $("[data-confirm-accept]").textContent = actionLabel;
        $("[data-confirm-layer]").hidden = false;
        return new Promise(resolve => { state.confirmResolve = resolve; });
    }

    async function toggleStatus() {
        const enabling = state.form.status !== "active";
        const confirmed = await confirmAction(enabling ? "Enable user" : `Disable ${state.form.display_name}?`, enabling ? "This user will regain access to Mining 360." : "The user will no longer be able to access Mining 360. Their access configuration will be preserved.", enabling ? "Enable user" : "Disable user");
        if (!confirmed) return;
        try {
            const payload = await api(`/api/access-control/users/${state.form.id}/status/`, { method: "POST", body: JSON.stringify({ active: enabling }) });
            state.form.status = payload.user.status;
            $("[data-status-action]").textContent = enabling ? "Disable user" : "Enable user";
            await loadUsers();
            toast(`${state.form.display_name} has been ${enabling ? "enabled" : "disabled"}.`);
        } catch (error) { toast(error.message); }
    }

    document.addEventListener("click", event => {
        const add = event.target.closest("[data-open-add]");
        if (add) return startAdd();
        if (event.target.closest("[data-drawer-close], [data-drawer-cancel]")) return requestCloseDrawer();
        const open = event.target.closest("[data-user-open], [data-user-row]");
        if (open && !event.target.closest("button[data-directory-select]")) return editUser(Number(open.dataset.userOpen || open.dataset.userRow));
        const select = event.target.closest("[data-directory-select]");
        if (select) return selectDirectoryResult(Number(select.dataset.directorySelect));
        if (event.target.closest("[data-directory-retry]")) return searchDirectory($("[data-directory-query]").value);
        const remove = event.target.closest("[data-remove-scope]");
        if (remove) { const key = remove.closest("[data-multiselect]").dataset.multiselect; state.form[key] = state.form[key].filter(value => value !== remove.dataset.removeScope); if (key === "minesites") state.form.powerbi_rls_role = ""; renderBusinessOptions(); renderMultiSelect(key); return markDirty(); }
        const addScope = event.target.closest("[data-add-scope]");
        if (addScope) { const key = addScope.closest("[data-multiselect]").dataset.multiselect; if (key === "minesites") { state.form[key] = [addScope.dataset.addScope]; state.form.powerbi_rls_role = addScope.dataset.addScope; } else state.form[key].push(addScope.dataset.addScope); renderBusinessOptions(); renderMultiSelect(key); return markDirty(); }
        if (event.target.closest("[data-save-access]")) return saveAccess();
        if (event.target.closest("[data-status-action]")) return toggleStatus();
        if (event.target.closest("[data-users-retry]")) return loadUsers();
        if (event.target.closest("[data-page-prev]")) { state.page--; return loadUsers(); }
        if (event.target.closest("[data-page-next]")) { state.page++; return loadUsers(); }
        if (event.target.closest("[data-confirm-cancel]")) { $("[data-confirm-layer]").hidden = true; state.confirmResolve?.(false); }
        if (event.target.closest("[data-confirm-accept]")) { $("[data-confirm-layer]").hidden = true; state.confirmResolve?.(true); }
    });

    document.addEventListener("change", event => {
        if (!state.form) return;
        if (event.target.matches("[data-focus-site-profile]")) {
            const preset = (state.options.site_access_profiles || []).find(item => item.id === event.target.value);
            if (!preset || state.form.directory_roles_managed) return;
            state.form.platform_roles = [...preset.platform_roles];
            state.form.business_performance_access = preset.business_performance_access;
            state.form.countries = [];
            state.form.customers = [];
            state.form.minesites = [...preset.minesites];
            state.form.powerbi_rls_role = preset.powerbi_rls_role;
            renderRoleOptions(); renderBusinessOptions();
            ["countries", "customers", "minesites"].forEach(renderMultiSelect);
            markDirty();
        }
        if (event.target.matches("[data-role-checkbox]")) {
            if (event.target.value === "site" && event.target.checked) {
                $$('[data-role-checkbox]').forEach(input => { if (input.value !== "site") input.checked = false; });
                state.form.business_performance_access = "MineSite";
                state.form.countries = [];
                state.form.customers = [];
            } else if (event.target.value !== "site" && event.target.checked) {
                const siteRole = $('[data-role-checkbox][value="site"]');
                if (siteRole?.checked) { siteRole.checked = false; state.form.report_rls_roles = {}; }
            }
            if (event.target.checked && ["admin", "super_admin"].includes(event.target.value)) {
                const other = $(`[data-role-checkbox][value="${event.target.value === "admin" ? "super_admin" : "admin"}"]`);
                if (other) other.checked = false;
            }
            state.form.platform_roles = $$('[data-role-checkbox]:checked').map(input => input.value);
            renderBusinessOptions(); renderMultiSelect("countries"); renderMultiSelect("customers"); renderMultiSelect("minesites"); markDirty();
        }
        if (event.target.matches("[data-directory-managed]")) {
            state.form.directory_roles_managed = event.target.checked;
            if (event.target.checked) state.form.platform_roles = [...state.form.ad_managed_roles];
            renderRoleOptions(); markDirty();
        }
        if (event.target.matches("[data-bp-role]")) {
            const previous = state.form.business_performance_access;
            if (!event.target.value && (state.form.countries.length || state.form.customers.length || state.form.minesites.length) && !window.confirm("Remove the existing Business Performance scopes?")) { event.target.value = previous; return; }
            state.form.business_performance_access = event.target.value;
            if (!event.target.value) { state.form.countries = []; state.form.customers = []; state.form.minesites = []; }
            if (event.target.value === "MineSite") { state.form.countries = []; state.form.customers = []; }
            else { state.form.minesites = []; }
            renderBusinessOptions(); renderMultiSelect("countries"); renderMultiSelect("customers"); renderMultiSelect("minesites"); markDirty();
        }
        if (event.target.matches("[data-rls-role]")) { state.form.powerbi_rls_role = event.target.value; markDirty(); }
        if (event.target.matches("[data-site-report-rls-id]")) { state.form.report_rls_roles[event.target.dataset.siteReportRlsId] = event.target.value; markDirty(); }
    });

    document.addEventListener("input", event => {
        if (event.target.matches("[data-users-search]")) {
            clearTimeout(state.usersTimer);
            state.usersTimer = setTimeout(() => { state.query = event.target.value.trim(); state.page = 1; loadUsers(); }, 300);
        }
        if (event.target.matches("[data-directory-query]")) {
            clearTimeout(state.directoryTimer);
            state.directoryTimer = setTimeout(() => searchDirectory(event.target.value), 300);
        }
        if (event.target.matches("[data-scope-search]")) showScopeMenu(event.target.dataset.scopeSearch, event.target.value);
    });

    document.addEventListener("focusin", event => {
        if (event.target.matches("[data-scope-search]")) showScopeMenu(event.target.dataset.scopeSearch, event.target.value);
    });

    document.addEventListener("keydown", event => {
        const row = event.target.closest("tr[data-user-row]");
        if (row && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            editUser(Number(row.dataset.userRow));
        }
    });

    $("[data-filter-status]").addEventListener("change", event => { state.status = event.target.value; state.page = 1; loadUsers(); });
    $("[data-filter-role]").addEventListener("change", event => { state.role = event.target.value; state.page = 1; loadUsers(); });
    $("[data-filter-source]").addEventListener("change", event => { state.source = event.target.value; state.page = 1; loadUsers(); });
    $("[data-filter-bp]").addEventListener("change", event => { state.bp = event.target.value; state.page = 1; loadUsers(); });
    $("[data-ordering]").addEventListener("change", event => { state.ordering = event.target.value; state.page = 1; loadUsers(); });

    $$("[data-users-audience]").forEach(tab => tab.addEventListener("click", () => {
        state.audience = tab.dataset.usersAudience;
        state.page = 1;
        $$("[data-users-audience]").forEach(node => node.setAttribute("aria-selected", String(node === tab)));
        const system = state.audience === "system";
        $("[data-audience-note]").textContent = system
            ? "Comptes créés directement dans Mining360. Ils ne proviennent pas de l’annuaire Neemba."
            : "Comptes Neemba synchronisés depuis Active Directory ou Microsoft Entra.";
        $("[data-users-search]").placeholder = system ? "Rechercher un utilisateur créé dans Mining360..." : "Rechercher un utilisateur Neemba...";
        loadUsers();
    }));

    $("[data-directory-query]").addEventListener("keydown", event => {
        const options = $$('[data-directory-index]');
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            state.selectedResult = Math.max(0, Math.min(options.length - 1, state.selectedResult + (event.key === "ArrowDown" ? 1 : -1)));
            options.forEach((node, index) => node.classList.toggle("is-selected", index === state.selectedResult));
            options[state.selectedResult]?.scrollIntoView({ block: "nearest" });
        } else if (event.key === "Enter" && state.selectedResult >= 0) { event.preventDefault(); selectDirectoryResult(state.selectedResult); }
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !$("[data-confirm-layer]").hidden) { $("[data-confirm-layer]").hidden = true; state.confirmResolve?.(false); return; }
        if (event.key === "Escape" && !$("[data-drawer-layer]").hidden) requestCloseDrawer();
        if (event.key === "Tab" && !$("[data-drawer-layer]").hidden) {
            const focusable = $$('button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex="0"]', $("[data-drawer]"))
                .filter(node => !node.hidden && node.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
    });

    Promise.all([loadOptions(), loadUsers()]).catch(() => {});
})();
