(() => {
    const app = document.querySelector('[data-business-mapping-app]');
    if (!app) return;
    if (window.matchMedia('(max-width: 780px)').matches) {
        document.body.classList.add('nav-collapsed');
        const navButton = document.querySelector('.js-toggle-nav');
        navButton?.setAttribute('aria-expanded', 'false');
        navButton?.setAttribute('aria-label', 'Open navigation');
    }

    const state = { page: 1, pages: 1, selected: null, detail: null, site: null, candidate: null, mapping: null, businessAccountId: null, evidenceIds: [], sourceContext: null, revenueLob: '', revenuePeriod: 'ytd', country: '', countryOptions: [], accountView: 'canonical', keyAccountFilter: '', keyAccountSort: 'revenue_desc', expandedAccounts: new Set(), keyAccounts: [], availableKeyMembers: [], availableKeyMemberCount: 0, selectedKeyAccountId: null };
    const csrf = app.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
    const $ = (selector) => document.querySelector(selector);
    const all = (selector) => [...document.querySelectorAll(selector)];
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    const money = (value) => new Intl.NumberFormat(document.documentElement.lang === 'fr' ? 'fr-FR' : 'en-GB', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(Number(value || 0));
    const countryName = (value) => {
        const country = String(value || '').trim();
        if (country.toUpperCase() === 'UNASSIGNED') return 'Country not validated';
        if (!country || country.length !== 2) return country;
        try {
            return new Intl.DisplayNames(
                [document.documentElement.lang === 'fr' ? 'fr-FR' : 'en-GB'],
                { type: 'region' },
            ).of(country.toUpperCase()) || country;
        } catch (_) {
            return country;
        }
    };
    const operatingCountryNames = (values) => (values || []).map(countryName).join(', ') || 'Not assigned';
    const requestId = () => crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    const withPageFilters = (url) => {
        const params = new URLSearchParams();
        if (state.revenueLob) params.set('lob', state.revenueLob);
        params.set('period', state.revenuePeriod);
        if (state.country) params.set('country', state.country);
        params.set('view', state.accountView);
        return params.size ? `${url}${url.includes('?') ? '&' : '?'}${params}` : url;
    };
    let syncPollTimer = null;

    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, ...(options.headers || {}) },
            ...options,
        });
        let data;
        try { data = await response.json(); } catch (_) { data = { error: { message: 'Mining 360 returned an invalid response.' } }; }
        if (!response.ok) {
            const error = new Error(data.error?.message || data.detail || 'The request could not be completed.');
            error.fields = data.error?.fields || {};
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function toast(message) {
        const node = $('[data-bm-toast]');
        node.textContent = message;
        node.hidden = false;
        window.clearTimeout(toast.timer);
        toast.timer = window.setTimeout(() => { node.hidden = true; }, 5000);
    }

    function openPublicationsPanel() {
        const tab = $('[data-bm-tab="published"]');
        if (!tab) return;
        all('[data-bm-tab]').forEach((item) => {
            item.classList.toggle('active', item === tab);
            item.setAttribute('aria-selected', item === tab ? 'true' : 'false');
        });
        all('[data-bm-panel]').forEach((panel) => {
            panel.hidden = panel.dataset.bmPanel !== 'published';
            panel.classList.toggle('active', !panel.hidden);
        });
        tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    async function loadPublicationHistory() {
        const container = $('[data-bm-publication-history]');
        if (!container || !app.dataset.publicationsUrl) return;
        try {
            const data = await api(app.dataset.publicationsUrl);
            const rows = data.results || [];
            container.innerHTML = rows.length ? `<h3>Published Versions</h3><div class="bm-publication-list">${rows.map((item) => `<div><strong>Version ${item.version}</strong><span>${escapeHtml(item.status)} · ${item.mapping_count} mappings${item.published_at ? ` · ${new Date(item.published_at).toLocaleString()}` : ''}</span></div>`).join('')}</div>` : '<p class="bm-empty">No Mapping version has been published yet.</p>';
        } catch (error) {
            container.innerHTML = `<p class="bm-empty">${escapeHtml(error.message)}</p>`;
        }
    }

    async function previewPublication() {
        const status = $('[data-bm-publication-status]');
        const metrics = $('[data-bm-publication-metrics]');
        const confirm = $('[data-bm-publication-confirm]');
        if (!status || !metrics || !confirm) return;
        confirm.disabled = true;
        status.innerHTML = '<strong>Generating publication preview...</strong><span>Validated mappings and conflicts are being checked.</span>';
        try {
            const data = await api(app.dataset.publicationPreviewUrl, { method: 'POST', body: '{}' });
            const preview = data.preview;
            const critical = (preview.conflicts || []).filter((item) => item.severity === 'Critical').length;
            status.innerHTML = `<strong>${preview.can_publish ? 'Ready to publish' : 'Publication blocked'}</strong><span>${critical ? `${critical} critical conflict${critical === 1 ? '' : 's'} must be resolved.` : 'No critical conflict blocks this version.'}</span>`;
            metrics.hidden = false;
            metrics.innerHTML = `<div><span>Mappings</span><strong>${preview.mapping_count}</strong></div><div><span>Accounts</span><strong>${preview.account_count}</strong></div><div><span>MineSites</span><strong>${preview.minesite_count}</strong></div><div><span>Added</span><strong>${preview.changes?.added?.length || 0}</strong></div><div><span>Changed</span><strong>${preview.changes?.changed?.length || 0}</strong></div><div><span>Removed</span><strong>${preview.changes?.removed?.length || 0}</strong></div>`;
            confirm.disabled = !preview.can_publish || preview.mapping_count === 0;
            toast(`${preview.mapping_count} validated mappings checked.`);
        } catch (error) {
            status.innerHTML = `<strong>Preview failed</strong><span>${escapeHtml(error.message)}</span>`;
            toast(error.message);
        }
    }

    async function publishMappingVersion() {
        const button = $('[data-bm-publication-confirm]');
        const reason = $('[data-bm-publication-reason]')?.value.trim() || '';
        if (!reason) {
            toast('Enter a publication reason before publishing.');
            $('[data-bm-publication-reason]')?.focus();
            return;
        }
        button.disabled = true;
        button.textContent = 'Publishing...';
        try {
            const data = await api(app.dataset.publicationsUrl, { method: 'POST', body: JSON.stringify({ reason }) });
            toast(`Mapping Version ${data.publication.version} published successfully.`);
            $('[data-bm-publication-reason]').value = '';
            await previewPublication();
            await loadPublicationHistory();
            await loadOverview();
        } catch (error) {
            toast(error.message);
        } finally {
            button.textContent = 'Publish Mapping Version';
        }
    }

    async function loadOverview() {
        try {
            const data = await api(withPageFilters(app.dataset.overviewUrl));
            const source = data.source_context || {};
            state.sourceContext = source;
            const revenueLabel = source.revenue?.label || 'YTD period unavailable';
            const periodSelect = $('[data-bm-period-select]');
            if (periodSelect && source.revenue?.period_options?.length) {
                periodSelect.innerHTML = source.revenue.period_options.map((option) => `<option value="${escapeHtml(option.value)}" ${option.available ? '' : 'disabled'}>${escapeHtml(option.label)}${option.available ? '' : ' · unavailable'}</option>`).join('');
                periodSelect.value = source.revenue.selected_period || state.revenuePeriod;
                state.revenuePeriod = periodSelect.value || 'ytd';
            }
            const fleetSource = source.fleet?.source || 'EquipmentList_MiningProd';
            const snapshotAt = source.fleet?.snapshot_at ? new Date(source.fleet.snapshot_at) : null;
            const mappingAsOf = source.mappings?.as_of ? new Date(source.mappings.as_of) : null;
            const selectedCategory = source.revenue?.selected_category || 'All Mining';
            const businessScope = source.business_scope?.country ? countryName(source.business_scope.country) : 'Group';
            $('[data-bm-context="revenue"]').textContent = `${businessScope} · Mining · ${selectedCategory} · ${revenueLabel}`;
            $('[data-bm-revenue-period]').textContent = `${revenueLabel} · Division MI`;
            $('[data-bm-revenue="TOTAL"]').textContent = money(data.summary?.total_revenue_eur || 0);
            (data.revenue_breakdown || []).forEach((item) => {
                const node = $(`[data-bm-revenue="${item.code}"]`);
                if (node) node.textContent = money(item.value);
            });
            $('[data-bm-context="fleet"]').textContent = snapshotAt && !Number.isNaN(snapshotAt.valueOf())
                ? `${fleetSource} · synchronized ${snapshotAt.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`
                : `${fleetSource} · snapshot date unavailable`;
            $('[data-bm-context="mappings"]').textContent = mappingAsOf && !Number.isNaN(mappingAsOf.valueOf())
                ? `Current database state · ${mappingAsOf.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`
                : 'Current database state';
            document.querySelectorAll('[data-bm-period-note]').forEach((node) => { node.textContent = revenueLabel; });
            Object.entries(data.summary || {}).forEach(([key, value]) => {
                const node = $(`[data-bm-metric="${key}"]`);
                if (!node) return;
                if (value === null || value === undefined) { node.textContent = 'Not Evaluated'; return; }
                node.textContent = key.endsWith('_pct') ? `${value}%` : key.includes('revenue') ? money(value) : Number(value || 0).toLocaleString();
            });
            $('[data-bm-conflict-count]').textContent = data.summary?.accounts_with_conflicts === null ? '(Not Evaluated)' : data.summary?.accounts_with_conflicts ? `(${data.summary.accounts_with_conflicts})` : '';
        } catch (error) { toast(error.message); }
    }

    function findAccountRow(list, accountId) {
        if (!accountId) return null;
        return [...list.querySelectorAll('[data-account-id]')].find((row) => row.dataset.accountId === accountId) || null;
    }

    async function loadAccounts({ preservePosition = false, focusAccountId = null } = {}) {
        const list = $('[data-bm-account-list]');
        const previousScrollTop = preservePosition ? list.scrollTop : 0;
        const previousRow = preservePosition ? findAccountRow(list, focusAccountId) : null;
        const previousRowTop = previousRow?.getBoundingClientRect().top;
        if (preservePosition) list.setAttribute('aria-busy', 'true');
        else list.innerHTML = '<p class="bm-empty">Loading Accounts...</p>';
        const params = new URLSearchParams({
            page: state.page,
            page_size: 30,
            search: $('[data-bm-account-search]').value,
            country: state.country,
            status: $('[data-bm-account-status]').value,
            sort: $('[data-bm-account-sort]').value,
            key_account: state.keyAccountFilter,
            lob: state.revenueLob,
            period: state.revenuePeriod,
            view: state.accountView,
        });
        try {
            const data = await api(`${app.dataset.accountsUrl}?${params}`);
            const countrySelect = $('[data-bm-country-scope]');
            const selectedCountry = state.country;
            state.countryOptions = data.filters?.countries || [];
            countrySelect.innerHTML = '<option value="">Group</option>' + (data.filters?.countries || []).map((country) =>
                `<option value="${escapeHtml(country.code || country)}">${escapeHtml(country.label || countryName(country))}</option>`
            ).join('');
            countrySelect.value = [...countrySelect.options].some((option) => option.value === selectedCountry) ? selectedCountry : '';
            const keyAccountSelect = $('[data-bm-key-account-filter]');
            keyAccountSelect.innerHTML = '<option value="">All Key Accounts</option><option value="unassigned">Unassigned to a Key Account</option>' + (data.filters?.key_accounts || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.key_account_name)}</option>`).join('');
            keyAccountSelect.value = [...keyAccountSelect.options].some((option) => option.value === state.keyAccountFilter) ? state.keyAccountFilter : '';
            state.pages = data.pages || 1;
            $('[data-bm-account-total]').textContent = Number(data.count || 0).toLocaleString();
            $('[data-bm-page]').textContent = `${data.page || 1} / ${state.pages}`;
            $('[data-bm-previous]').disabled = (data.page || 1) <= 1;
            $('[data-bm-next]').disabled = (data.page || 1) >= state.pages;
            list.innerHTML = data.results?.length ? data.results.map((item) => {
                const expanded = state.expandedAccounts.has(item.source_account_id);
                const sourceRecords = item.source_records || [];
                return `<div class="bm-account-entry ${expanded ? 'expanded' : ''}">
                    <button type="button" class="bm-account-row ${state.selected?.source_account_id === item.source_account_id ? 'active' : ''}" data-account-id="${escapeHtml(item.source_account_id)}">
                        <span class="bm-account-heading"><span class="bm-account-title">${escapeHtml(item.source_account_name)}</span><span class="bm-revenue-rank" title="Revenue rank in the current filtered scope">#${Number(item.revenue_rank || 0).toLocaleString()}</span></span>
                        <span class="bm-account-identity"><span>${escapeHtml(item.source_account_code)}</span>${item.code_cic ? `<span>CIC ${escapeHtml(item.code_cic)}</span>` : ''}${item.company_code ? `<span>Company ${escapeHtml(item.company_code)}${item.company_name ? ` · ${escapeHtml(item.company_name)}` : ''}</span>` : ''}${item.origin_country ? `<span>Origin: ${escapeHtml(countryName(item.origin_country))}</span>` : ''}</span>
                        <span class="bm-country-assignment ${item.assigned_operating_countries?.length ? 'assigned' : 'inferred'}"><span>${item.assigned_operating_countries?.length ? 'Assigned:' : 'Suggested from revenue:'}</span><strong>${escapeHtml(operatingCountryNames(item.assigned_operating_countries?.length ? item.assigned_operating_countries : item.operating_countries))}</strong></span>
                        ${item.source_record_count ? `<span class="bm-account-record-summary"><strong>${Number(item.source_record_count).toLocaleString()}</strong> source records${item.identity_status && item.identity_status !== 'Canonical' ? `<span class="bm-review-flag">${escapeHtml(item.identity_status)}</span>` : ''}</span>` : ''}
                        ${item.source_record_count ? `<span class="bm-account-groups"><span><small>Key Account</small><strong>${item.key_accounts?.length ? escapeHtml(item.key_accounts.join(', ')) : 'Not assigned'}</strong></span>${item.aliases?.length ? `<span><small>Aliases</small><strong>${escapeHtml(item.aliases.join(', '))}</strong></span>` : ''}</span>` : ''}
                        <span class="bm-row-meta"><span><small>Mining revenue · ${escapeHtml(state.sourceContext?.revenue?.label || state.revenuePeriod.toUpperCase())}</small><strong>${item.revenue_ytd === null ? 'Not available' : money(item.revenue_ytd)}</strong></span><span class="bm-status">${escapeHtml(item.mapping_status)}</span></span>
                    </button>
                    ${sourceRecords.length ? `<button type="button" class="bm-source-record-toggle" data-source-toggle="${escapeHtml(item.source_account_id)}" aria-expanded="${expanded}" aria-controls="bm-source-records-${escapeHtml(item.source_account_id)}">
                        <span>${expanded ? 'Hide' : 'View'} ${Number(sourceRecords.length).toLocaleString()} source record${sourceRecords.length === 1 ? '' : 's'}</span><span aria-hidden="true">${expanded ? '▲' : '▼'}</span>
                    </button>
                    <div class="bm-source-records" id="bm-source-records-${escapeHtml(item.source_account_id)}" ${expanded ? '' : 'hidden'}>
                        ${sourceRecords.map((source) => `<div class="bm-source-record">
                            <div><strong>${escapeHtml(source.source_record_id)}</strong><small>${source.code_cic ? `CIC ${escapeHtml(source.code_cic)}` : 'No CIC'}${source.company_code ? ` · Company ${escapeHtml(source.company_code)}${source.company_name ? ` (${escapeHtml(source.company_name)})` : ''}` : ''} · Origin: ${escapeHtml(countryName(source.origin_country || source.country))} · Operating: ${escapeHtml(operatingCountryNames(source.operating_countries))}</small></div>
                            <div><span>${source.source_record_revenue_ytd === null ? 'Not available' : money(source.source_record_revenue_ytd)}</span><small>${escapeHtml(source.source_system || 'Source')}</small></div>
                        </div>`).join('')}
                    </div>` : ''}
                </div>`;
            }).join('') : '<p class="bm-empty">No Account matches these filters.</p>';
            list.querySelectorAll('[data-account-id]').forEach((button) => button.addEventListener('click', () => selectAccount(button.dataset.accountId)));
            list.querySelectorAll('[data-source-toggle]').forEach((button) => button.addEventListener('click', () => {
                const accountId = button.dataset.sourceToggle;
                if (state.expandedAccounts.has(accountId)) state.expandedAccounts.delete(accountId);
                else state.expandedAccounts.add(accountId);
                const records = document.getElementById(button.getAttribute('aria-controls'));
                const expanded = state.expandedAccounts.has(accountId);
                button.setAttribute('aria-expanded', String(expanded));
                button.querySelector('span:first-child').textContent = `${expanded ? 'Hide' : 'View'} ${records.children.length.toLocaleString()} source record${records.children.length === 1 ? '' : 's'}`;
                button.querySelector('span:last-child').textContent = expanded ? '▲' : '▼';
                records.hidden = !expanded;
                button.closest('.bm-account-entry')?.classList.toggle('expanded', expanded);
            }));
            if (preservePosition) {
                list.scrollTop = previousScrollTop;
                const currentRow = findAccountRow(list, focusAccountId);
                if (currentRow && Number.isFinite(previousRowTop)) {
                    list.scrollTop += currentRow.getBoundingClientRect().top - previousRowTop;
                }
                currentRow?.focus({ preventScroll: true });
            }
        } catch (error) {
            if (preservePosition) toast(error.message);
            else list.innerHTML = `<p class="bm-empty">${escapeHtml(error.message)}</p>`;
        } finally {
            list.removeAttribute('aria-busy');
        }
    }

    async function selectAccount(id, preserveContext = false) {
        if (!preserveContext) {
            state.site = null; state.candidate = null; state.mapping = null; state.businessAccountId = null; state.evidenceIds = [];
            $('[data-bm-decision-form]')?.setAttribute('hidden', '');
        }
        try {
            const data = await api(withPageFilters(`${app.dataset.accountsUrl}${id}/`));
            state.detail = data;
            state.selected = { source_account_id: id, ...data.account };
            if (!state.businessAccountId) state.businessAccountId = data.account.business_account_id;
            document.querySelectorAll('.bm-account-row').forEach((row) => row.classList.toggle('active', row.dataset.accountId === id));
            renderDetail();
            $('[data-bm-generate]')?.removeAttribute('disabled');
        } catch (error) { toast(error.message); }
    }

    function renderCountryAccounts() {
        const list = $('[data-bm-country-list]');
        const detail = $('[data-bm-country-detail]');
        const available = $('[data-bm-country-available]');
        $('[data-bm-country-count]').textContent = Number(state.countryAccounts.length).toLocaleString();
        const selected = state.countryAccounts.find((item) => item.id === state.selectedCountryAccountId);
        list.innerHTML = `<button type="button" class="bm-key-group ${state.selectedCountryAccountId === null ? 'active' : ''}" data-country-account-id=""><strong>Unassigned canonical Accounts</strong><small>${Number(state.availableCountryMemberCount).toLocaleString()} Account(s)</small></button>` + state.countryAccounts.map((item) => `<button type="button" class="bm-key-group ${item.id === state.selectedCountryAccountId ? 'active' : ''}" data-country-account-id="${escapeHtml(item.id)}"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(countryName(item.country))} · ${Number(item.canonical_account_count).toLocaleString()} canonical Account(s)</small><small>${item.key_account ? `Key Account: ${escapeHtml(item.key_account.name)}` : 'Not assigned to a Key Account'}</small></button>`).join('');
        list.querySelectorAll('[data-country-account-id]').forEach((button) => button.addEventListener('click', async () => {
            state.selectedCountryAccountId = button.dataset.countryAccountId || null;
            await loadCountryAccounts($('[data-bm-country-search]')?.value || '');
        }));
        if (!selected) {
            detail.innerHTML = '<div class="bm-key-summary"><h3>Unassigned canonical Accounts</h3><p>Create or select a Country Account before adding an Account.</p></div>';
            available.innerHTML = state.availableCountryMembers.length ? `<div class="bm-key-members">${state.availableCountryMembers.map((member, index) => `<div class="bm-key-candidate"><div><strong>${escapeHtml(member.name)}</strong><small>Origin: ${escapeHtml(countryName(member.origin_country))} · Operating: ${escapeHtml(operatingCountryNames(member.operating_countries))} · ${member.revenue_ytd === null ? 'Revenue not available' : money(member.revenue_ytd)}</small></div>${app.dataset.canEdit === 'true' ? `<div class="bm-key-candidate-actions"><button type="button" class="button secondary small" data-country-create-from="${index}">Add as Country Account</button></div>` : ''}</div>`).join('')}</div>` : '<p class="bm-empty">No unassigned canonical Account matches the current filters.</p>';
            available.querySelectorAll('[data-country-create-from]').forEach((button) => button.addEventListener('click', () => createCountryAccountFromMember(state.availableCountryMembers[Number(button.dataset.countryCreateFrom)])));
            return;
        }
        detail.innerHTML = `<div class="bm-key-summary"><div class="bm-key-summary-head"><div><h3>${escapeHtml(selected.name)}</h3><p>Operating country: ${escapeHtml(countryName(selected.country))} · ${Number(selected.canonical_account_count).toLocaleString()} canonical Account(s)</p><p>${selected.key_account ? `Key Account: ${escapeHtml(selected.key_account.name)}` : 'Not assigned to a Key Account'}</p></div>${app.dataset.canEdit === 'true' ? '<div class="bm-key-actions"><button type="button" class="button secondary small" data-country-rename-open>Rename</button><button type="button" class="button danger small" data-country-delete-open>Delete</button></div>' : ''}</div>${app.dataset.canEdit === 'true' ? `<form class="bm-key-rename" data-country-rename-form hidden><label>Country Account name<input type="text" data-country-rename-name value="${escapeHtml(selected.name)}" required></label><div><button type="button" class="button secondary small" data-country-rename-cancel>Cancel</button><button type="submit" class="button small">Save name</button></div></form>` : ''}</div><div class="bm-key-members">${selected.members?.length ? selected.members.map((member) => `<div class="bm-key-member"><div><strong>${escapeHtml(member.name)}</strong><small>Origin: ${escapeHtml(countryName(member.origin_country))} · Operating: ${escapeHtml(operatingCountryNames(member.operating_countries))}</small></div>${app.dataset.canEdit === 'true' ? `<button type="button" class="button secondary small" data-country-remove='${escapeHtml(JSON.stringify(member.business_account_ids))}'>Remove</button>` : ''}</div>`).join('') : '<p class="bm-empty">No canonical Account has been added yet.</p>'}</div>`;
        available.innerHTML = app.dataset.canEdit === 'true' ? (state.availableCountryMembers.length ? `<div class="bm-key-members">${state.availableCountryMembers.map((member, index) => `<div class="bm-key-candidate"><div><strong>${escapeHtml(member.name)}</strong><small>Origin: ${escapeHtml(countryName(member.origin_country))} · Operating: ${escapeHtml(operatingCountryNames(member.operating_countries))} · ${member.revenue_ytd === null ? 'Revenue not available' : money(member.revenue_ytd)}</small></div><div class="bm-key-candidate-actions"><button type="button" class="button secondary small" data-country-add='${escapeHtml(JSON.stringify(member.business_account_ids))}'>Add</button><button type="button" class="button secondary small" data-country-create-from="${index}">Add as Country Account</button></div></div>`).join('')}</div>` : '<p class="bm-empty">No available canonical Account in this operating country matches the search.</p>') : '';
        detail.querySelectorAll('[data-country-remove]').forEach((button) => button.addEventListener('click', () => updateCountryMembers('DELETE', JSON.parse(button.dataset.countryRemove))));
        available.querySelectorAll('[data-country-add]').forEach((button) => button.addEventListener('click', () => updateCountryMembers('POST', JSON.parse(button.dataset.countryAdd))));
        available.querySelectorAll('[data-country-create-from]').forEach((button) => button.addEventListener('click', () => createCountryAccountFromMember(state.availableCountryMembers[Number(button.dataset.countryCreateFrom)])));
        detail.querySelector('[data-country-rename-open]')?.addEventListener('click', () => { detail.querySelector('[data-country-rename-form]').hidden = false; detail.querySelector('[data-country-rename-name]').focus(); });
        detail.querySelector('[data-country-rename-cancel]')?.addEventListener('click', () => { detail.querySelector('[data-country-rename-form]').hidden = true; });
        detail.querySelector('[data-country-rename-form]')?.addEventListener('submit', renameCountryAccount);
        detail.querySelector('[data-country-delete-open]')?.addEventListener('click', () => { $('[data-bm-country-delete-summary]').textContent = `Delete ${selected.name}?`; $('[data-bm-country-delete-reason]').value = ''; $('[data-bm-country-delete-error]').hidden = true; $('[data-bm-country-delete-dialog]').showModal(); });
    }

    async function loadCountryAccounts(accountSearch = '') {
        const params = new URLSearchParams({ country: state.country, lob: state.revenueLob, period: state.revenuePeriod, account_search: accountSearch, country_account_id: state.selectedCountryAccountId || '' });
        try {
            const data = await api(`${app.dataset.countryAccountsUrl}?${params}`);
            state.countryAccounts = data.country_accounts || [];
            state.availableCountryMembers = data.available_accounts || [];
            state.availableCountryMemberCount = Number(data.available_account_count || 0);
            if (state.selectedCountryAccountId && !state.countryAccounts.some((item) => item.id === state.selectedCountryAccountId)) state.selectedCountryAccountId = null;
            renderCountryAccounts();
        } catch (error) { $('[data-bm-country-error]').textContent = error.message; $('[data-bm-country-error]').hidden = false; }
    }

    async function updateCountryMembers(method, ids) {
        if (!state.selectedCountryAccountId) return;
        try {
            await api(`${app.dataset.countryAccountsUrl}${state.selectedCountryAccountId}/members/`, { method, body: JSON.stringify({ business_account_ids: ids }) });
            await Promise.all([loadCountryAccounts($('[data-bm-country-search]')?.value || ''), loadAccounts()]);
            toast(method === 'POST' ? 'Canonical Account added to the Country Account.' : 'Canonical Account removed from the Country Account.');
        } catch (error) { $('[data-bm-country-error]').textContent = error.message; $('[data-bm-country-error]').hidden = false; }
    }

    async function createCountryAccountFromMember(member) {
        if (!member?.business_account_ids?.length) return;
        const countrySelect = $('[data-bm-country-code]');
        const knownCountries = (member.operating_countries || []).filter((country) =>
            [...countrySelect.options].some((option) => option.value === country)
        );
        const resolvedCountry = state.country && knownCountries.includes(state.country)
            ? state.country
            : (knownCountries.length === 1 ? knownCountries[0] : '');
        if (!resolvedCountry) {
            state.pendingCountryMemberIds = member.business_account_ids;
            $('[data-bm-country-name]').value = member.name;
            countrySelect.value = '';
            $('[data-bm-country-create-submit]').textContent = 'Create and add';
            $('[data-bm-country-create]').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            countrySelect.focus();
            toast('Select the operating country, then create and add this Canonical Account.');
            return;
        }
        try {
            const data = await api(app.dataset.countryAccountsUrl, {
                method: 'POST',
                body: JSON.stringify({ name: member.name, country: resolvedCountry, business_account_ids: member.business_account_ids }),
            });
            state.selectedCountryAccountId = data.country_account.id;
            await Promise.all([loadCountryAccounts(), loadAccounts()]);
            toast(`${member.name} was added as a Country Account.`);
        } catch (error) { toast(error.message); }
    }

    async function renameCountryAccount(event) {
        event.preventDefault();
        const selected = state.countryAccounts.find((item) => item.id === state.selectedCountryAccountId);
        if (!selected) return;
        try {
            await api(`${app.dataset.countryAccountsUrl}${selected.id}/`, { method: 'PATCH', body: JSON.stringify({ name: event.currentTarget.querySelector('[data-country-rename-name]').value, version: selected.version }) });
            await Promise.all([loadCountryAccounts(), loadKeyAccounts(), loadAccounts()]);
            toast('Country Account name updated.');
        } catch (error) { $('[data-bm-country-error]').textContent = error.message; $('[data-bm-country-error]').hidden = false; }
    }

    async function deleteCountryAccount() {
        const selected = state.countryAccounts.find((item) => item.id === state.selectedCountryAccountId);
        if (!selected) return;
        const reason = $('[data-bm-country-delete-reason]').value.trim();
        if (!reason) { $('[data-bm-country-delete-error]').textContent = 'A deletion reason is required.'; $('[data-bm-country-delete-error]').hidden = false; return; }
        try {
            await api(`${app.dataset.countryAccountsUrl}${selected.id}/`, { method: 'DELETE', body: JSON.stringify({ reason, version: selected.version }) });
            state.selectedCountryAccountId = null;
            $('[data-bm-country-delete-dialog]').close();
            await Promise.all([loadCountryAccounts(), loadKeyAccounts(), loadAccounts()]);
            toast('Country Account deleted. Its canonical Accounts are now unassigned.');
        } catch (error) { $('[data-bm-country-delete-error]').textContent = error.message; $('[data-bm-country-delete-error]').hidden = false; }
    }

    function renderKeyAccounts() {
        const list = $('[data-bm-key-list]');
        const detail = $('[data-bm-key-detail]');
        const available = $('[data-bm-key-available]');
        $('[data-bm-key-count]').textContent = Number(state.keyAccounts.length).toLocaleString();
        const selected = state.keyAccounts.find((item) => item.id === state.selectedKeyAccountId);
        list.innerHTML = `<button type="button" class="bm-key-group ${state.selectedKeyAccountId === null ? 'active' : ''}" data-key-account-id="">
                <strong>Unassigned Canonical Accounts</strong>
                <small>${Number(state.availableKeyMemberCount).toLocaleString()} Canonical Account(s) without a Key Account</small>
                <small>Select to review the unassigned queue</small>
            </button>` + (state.keyAccounts.length ? state.keyAccounts.map((item) => `
            <button type="button" class="bm-key-group ${item.id === state.selectedKeyAccountId ? 'active' : ''}" data-key-account-id="${escapeHtml(item.id)}">
                <strong>${escapeHtml(item.name)}</strong>
                <small>${Number(item.canonical_account_count).toLocaleString()} Canonical Account(s) · ${item.revenue_ytd === null ? 'Revenue not available' : money(item.revenue_ytd)}</small>
                <small>${item.minesites?.length ? escapeHtml(item.minesites.join(', ')) : 'No mapped MineSite'}</small>
            </button>`).join('') : '');
        list.querySelectorAll('[data-key-account-id]').forEach((button) => button.addEventListener('click', () => {
            state.selectedKeyAccountId = button.dataset.keyAccountId || null;
            renderKeyAccounts();
        }));
        if (!selected) {
            detail.innerHTML = '<div class="bm-key-summary"><h3>Unassigned Canonical Accounts</h3><p>These Canonical Accounts do not currently belong to a Key Account. Select a group before using Add.</p></div>';
            available.innerHTML = state.availableKeyMembers.length ? `<div class="bm-key-members">${state.availableKeyMembers.map((member) => `<div class="bm-key-candidate"><div><strong>${escapeHtml(member.name)}</strong><small>${Number(member.source_record_count).toLocaleString()} Source Record(s) · ${escapeHtml(countryName(member.country))} · ${member.revenue_ytd === null ? 'Revenue not available' : money(member.revenue_ytd)}</small></div></div>`).join('')}</div>` : '<p class="bm-empty">No unassigned Canonical Account matches the current filters.</p>';
            return;
        }
        detail.innerHTML = `<div class="bm-key-summary"><div class="bm-key-summary-head"><div><h3>${escapeHtml(selected.name)}</h3><p>${Number(selected.canonical_account_count).toLocaleString()} canonical Account(s) · ${selected.revenue_ytd === null ? 'Revenue not available' : money(selected.revenue_ytd)}</p><p>${selected.minesites?.length ? `MineSites: ${escapeHtml(selected.minesites.join(', '))}` : 'No mapped MineSite'}</p></div>${app.dataset.canEdit === 'true' ? '<div class="bm-key-actions"><button type="button" class="button secondary small" data-key-rename-open>Rename</button><button type="button" class="button danger small" data-key-delete-open>Delete</button></div>' : ''}</div>
            ${app.dataset.canEdit === 'true' ? `<form class="bm-key-rename" data-key-rename-form hidden><label>Key Account name<input type="text" data-key-rename-name value="${escapeHtml(selected.name)}" required></label><div><button type="button" class="button secondary small" data-key-rename-cancel>Cancel</button><button type="submit" class="button small">Save name</button></div></form>` : ''}</div>
            <div class="bm-key-members">${selected.members?.length ? selected.members.map((member) => `<div class="bm-key-member"><div><strong>${escapeHtml(member.name)}</strong><small>${escapeHtml(countryName(member.country))} · ${Number(member.source_record_count).toLocaleString()} Source Record(s) · ${member.revenue_ytd === null ? 'Revenue not available' : money(member.revenue_ytd)}</small></div>${app.dataset.canEdit === 'true' ? `<button type="button" class="button secondary small" data-key-remove='${escapeHtml(JSON.stringify(member.business_account_ids))}'>Remove</button>` : ''}</div>`).join('') : '<p class="bm-empty">No Canonical Account has been added yet.</p>'}</div>`;
        available.innerHTML = app.dataset.canEdit === 'true' ? (state.availableKeyMembers.length ? `<div class="bm-key-members">${state.availableKeyMembers.map((member) => `<div class="bm-key-candidate"><div><strong>${escapeHtml(member.name)}</strong><small>${Number(member.source_record_count).toLocaleString()} Source Record(s) · ${escapeHtml(countryName(member.country))} · ${member.revenue_ytd === null ? 'Revenue not available' : money(member.revenue_ytd)}</small></div><button type="button" class="button secondary small" data-key-add='${escapeHtml(JSON.stringify(member.business_account_ids))}'>Add</button></div>`).join('')}</div>` : '<p class="bm-empty">No available Canonical Account matches the search.</p>') : '';
        detail.querySelectorAll('[data-key-remove]').forEach((button) => button.addEventListener('click', () => updateKeyMembers('DELETE', JSON.parse(button.dataset.keyRemove))));
        available.querySelectorAll('[data-key-add]').forEach((button) => button.addEventListener('click', () => updateKeyMembers('POST', JSON.parse(button.dataset.keyAdd))));
        detail.querySelector('[data-key-rename-open]')?.addEventListener('click', () => {
            detail.querySelector('[data-key-rename-form]').hidden = false;
            detail.querySelector('[data-key-rename-name]').focus();
        });
        detail.querySelector('[data-key-rename-cancel]')?.addEventListener('click', () => { detail.querySelector('[data-key-rename-form]').hidden = true; });
        detail.querySelector('[data-key-rename-form]')?.addEventListener('submit', renameKeyAccount);
        detail.querySelector('[data-key-delete-open]')?.addEventListener('click', () => {
            $('[data-bm-key-delete-summary]').textContent = `Delete ${selected.name}? Its Canonical Accounts will become unassigned.`;
            $('[data-bm-key-delete-reason]').value = '';
            $('[data-bm-key-delete-error]').hidden = true;
            $('[data-bm-key-delete-dialog]').showModal();
        });
    }

    async function loadKeyAccounts(accountSearch = '') {
        const params = new URLSearchParams({ country: state.country, lob: state.revenueLob, period: state.revenuePeriod, account_search: accountSearch, key_sort: state.keyAccountSort });
        try {
            const data = await api(`${app.dataset.keyAccountsUrl}?${params}`);
            state.keyAccounts = data.key_accounts || [];
            state.availableKeyMembers = data.available_accounts || [];
            state.availableKeyMemberCount = Number(data.available_account_count || 0);
            $('[data-bm-key-revenue-basis]').textContent = state.revenueLob ? ({ PRIME: 'Machine', PARTS: 'Parts', SERVICE: 'Service', RENTAL: 'Rental' }[state.revenueLob] || state.revenueLob) : 'All Mining';
            if (state.selectedKeyAccountId && !state.keyAccounts.some((item) => item.id === state.selectedKeyAccountId)) state.selectedKeyAccountId = null;
            renderKeyAccounts();
        } catch (error) {
            $('[data-bm-key-error]').textContent = error.message;
            $('[data-bm-key-error]').hidden = false;
        }
    }

    async function updateKeyMembers(method, businessAccountIds) {
        if (!state.selectedKeyAccountId) return;
        const errorNode = $('[data-bm-key-error]');
        errorNode.hidden = true;
        try {
            await api(`${app.dataset.keyAccountsUrl}${state.selectedKeyAccountId}/members/`, {
                method, body: JSON.stringify({ business_account_ids: businessAccountIds }),
            });
            await loadKeyAccounts($('[data-bm-key-search]')?.value || '');
            toast(method === 'POST' ? 'Canonical Account added to the Key Account.' : 'Canonical Account removed from the Key Account.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    }

    async function renameKeyAccount(event) {
        event.preventDefault();
        const selected = state.keyAccounts.find((item) => item.id === state.selectedKeyAccountId);
        if (!selected) return;
        const errorNode = $('[data-bm-key-error]');
        errorNode.hidden = true;
        try {
            await api(`${app.dataset.keyAccountsUrl}${selected.id}/`, {
                method: 'PATCH', body: JSON.stringify({ name: event.currentTarget.querySelector('[data-key-rename-name]').value, version: selected.version }),
            });
            await Promise.all([loadKeyAccounts($('[data-bm-key-search]')?.value || ''), loadAccounts()]);
            toast('Key Account name updated.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    }

    async function deleteKeyAccount() {
        const selected = state.keyAccounts.find((item) => item.id === state.selectedKeyAccountId);
        if (!selected) return;
        const reason = $('[data-bm-key-delete-reason]').value.trim();
        const errorNode = $('[data-bm-key-delete-error]');
        if (!reason) { errorNode.textContent = 'A deletion reason is required.'; errorNode.hidden = false; return; }
        const button = $('[data-bm-key-delete-confirm]');
        button.disabled = true;
        button.textContent = 'Deleting...';
        try {
            await api(`${app.dataset.keyAccountsUrl}${selected.id}/`, {
                method: 'DELETE', body: JSON.stringify({ reason, version: selected.version }),
            });
            state.selectedKeyAccountId = null;
            $('[data-bm-key-delete-dialog]').close();
            await Promise.all([loadKeyAccounts($('[data-bm-key-search]')?.value || ''), loadAccounts()]);
            toast('Key Account deleted. Canonical Accounts are now unassigned.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
        finally { button.disabled = false; button.textContent = 'Delete Key Account'; }
    }

    function renderAliases() {
        const panel = $('[data-bm-alias-panel]');
        const list = $('[data-bm-alias-list]');
        if (!panel || !list || !state.detail?.account?.business_account_id) {
            if (panel) panel.hidden = true;
            return;
        }
        panel.hidden = false;
        const aliases = state.detail.aliases || [];
        list.innerHTML = aliases.length ? `<div class="bm-alias-list">${aliases.map((item) => `<span class="bm-alias-chip">Previous: ${escapeHtml(item.alias)}${app.dataset.canEdit === 'true' ? `<button type="button" data-bm-alias-remove="${Number(item.id)}" aria-label="Remove alias ${escapeHtml(item.alias)}" title="Remove alias">×</button>` : ''}</span>`).join('')}</div>` : '<p class="bm-empty compact">No previous Canonical Account name.</p>';
        list.querySelectorAll('[data-bm-alias-remove]').forEach((button) => button.addEventListener('click', () => removeAlias(Number(button.dataset.bmAliasRemove))));
    }

    function renderOperatingCountry() {
        const panel = $('[data-bm-operating-country-panel]');
        const account = state.detail?.account;
        if (!panel || !account?.business_account_id) {
            if (panel) panel.hidden = true;
            return;
        }
        panel.hidden = false;
        const assigned = account.assigned_operating_country || '';
        const suggestions = account.operating_countries || [];
        $('[data-bm-operating-country-current]').textContent = assigned ? `Assigned: ${countryName(assigned)}` : 'Not manually assigned';
        $('[data-bm-operating-country-suggestion]').textContent = `Source suggestion: ${operatingCountryNames(suggestions)}`;
        const select = $('[data-bm-operating-country-input]');
        if (select) {
            select.innerHTML = '<option value="">Select a country</option>' + state.countryOptions.filter((country) => String(country.code || country).toUpperCase() !== 'UNASSIGNED').map((country) => `<option value="${escapeHtml(country.code || country)}">${escapeHtml(country.label || countryName(country))}</option>`).join('');
            select.value = assigned;
        }
        const submit = $('[data-bm-operating-country-form] button[type="submit"]');
        if (submit) submit.textContent = assigned ? 'Change' : 'Assign';
        const clear = $('[data-bm-operating-country-clear]');
        if (clear) clear.hidden = !assigned;
    }

    async function saveOperatingCountry(event) {
        event.preventDefault();
        const accountId = state.detail?.account?.business_account_id;
        const select = $('[data-bm-operating-country-input]');
        const errorNode = $('[data-bm-operating-country-error]');
        if (!accountId || !select?.value) return;
        errorNode.hidden = true;
        try {
            const data = await api(`${app.dataset.canonicalCountryUrl}${accountId}/operating-country/`, {
                method: 'POST', body: JSON.stringify({ country: select.value }),
            });
            state.detail.account.assigned_operating_country = data.assigned_operating_country || '';
            renderOperatingCountry();
            await Promise.all([loadAccounts(), loadOverview()]);
            toast(`Operating country assigned: ${countryName(data.assigned_operating_country)}.`);
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    }

    async function clearOperatingCountry() {
        const accountId = state.detail?.account?.business_account_id;
        const errorNode = $('[data-bm-operating-country-error]');
        if (!accountId) return;
        errorNode.hidden = true;
        try {
            const data = await api(`${app.dataset.canonicalCountryUrl}${accountId}/operating-country/`, {
                method: 'DELETE', body: '{}',
            });
            state.detail.account.assigned_operating_country = '';
            state.detail.account.operating_countries = data.suggested_operating_countries || [];
            renderOperatingCountry();
            await Promise.all([loadAccounts(), loadOverview()]);
            toast('Source country suggestion restored.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    }

    async function saveAlias(event) {
        event.preventDefault();
        const input = $('[data-bm-alias-input]');
        const errorNode = $('[data-bm-alias-error]');
        const businessAccountId = state.detail?.account?.business_account_id;
        if (!businessAccountId || !input?.value.trim()) return;
        errorNode.hidden = true;
        try {
            const data = await api(`${app.dataset.canonicalAliasesUrl}${businessAccountId}/aliases/`, {
                method: 'POST', body: JSON.stringify({ alias: input.value.trim() }),
            });
            state.detail.account.name = data.canonical_account?.name || input.value.trim();
            state.detail.aliases = data.aliases || [];
            input.value = '';
            renderDetail();
            await loadAccounts();
            toast('Canonical Account renamed. The previous name remains available as an alias.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    }

    async function removeAlias(aliasId) {
        const errorNode = $('[data-bm-alias-error]');
        const businessAccountId = state.detail?.account?.business_account_id;
        if (!businessAccountId) return;
        errorNode.hidden = true;
        try {
            const data = await api(`${app.dataset.canonicalAliasesUrl}${businessAccountId}/aliases/`, {
                method: 'DELETE', body: JSON.stringify({ alias_id: aliasId }),
            });
            state.detail.aliases = data.aliases || [];
            renderAliases();
            await loadAccounts();
            toast('Canonical Account alias removed.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    }

    function renderDetail() {
        const detail = state.detail;
        const selectedRank = document.querySelector(`.bm-account-row[data-account-id="${CSS.escape(detail.account.source_account_id)}"] .bm-revenue-rank`)?.textContent || '';
        $('[data-bm-selected-summary]').innerHTML = `<strong>${escapeHtml(detail.account.name)}</strong><span>${escapeHtml(detail.account.code)}${detail.account.country ? ` · ${escapeHtml(detail.account.country)}` : ''}${selectedRank ? ` · Revenue rank ${escapeHtml(selectedRank)}` : ''}</span>`;
        renderOperatingCountry();
        renderAliases();
        const list = $('[data-bm-candidate-list]');
        const currentMappings = detail.current_mappings || [];
        const existing = currentMappings.length ? `
            <section class="bm-existing-mappings" aria-label="Existing MineSite relationships">
                <div class="bm-subsection-heading"><strong>Existing MineSite relationships</strong><span>${currentMappings.length}</span></div>
                ${currentMappings.map((mapping) => `
                    <article class="bm-existing-mapping ${state.mapping?.id === mapping.id ? 'selected' : ''}" data-existing-row="${escapeHtml(mapping.id)}">
                        <button type="button" class="bm-existing-mapping-main" data-existing-mapping="${escapeHtml(mapping.id)}">
                            <span><strong>${escapeHtml(mapping.minesite?.name || mapping.no_site_reason || 'No MineSite Required')}</strong><small>${escapeHtml(mapping.status)}</small></span>
                            <span><strong>View</strong></span>
                        </button>
                        ${app.dataset.canRemove === 'true' ? `<button type="button" class="bm-remove-mapping" data-remove-mapping="${escapeHtml(mapping.id)}" aria-label="Remove mapping to ${escapeHtml(mapping.minesite?.name || mapping.no_site_reason || 'No MineSite Required')}" title="Remove mapping">×</button>` : ''}
                        ${mapping.source_accounts?.length ? `<details class="bm-mapping-sources"><summary>View ${Number(mapping.source_accounts.length).toLocaleString()} Source Account${mapping.source_accounts.length === 1 ? '' : 's'}</summary><div>${mapping.source_accounts.map((source) => `<article><strong>${escapeHtml(source.name)}</strong><span>${escapeHtml(source.code)}${source.code_cic ? ` · CIC ${escapeHtml(source.code_cic)}` : ''}${source.company_code ? ` · Company ${escapeHtml(source.company_code)}` : ''}</span>${source.company_name ? `<small>${escapeHtml(source.company_name)}</small>` : ''}</article>`).join('')}</div></details>` : '<p class="bm-mapping-source-empty">No authorized Source Account is attached.</p>'}
                    </article>`).join('')}
            </section>` : '';
        const candidates = detail.candidate_minesites?.length ? detail.candidate_minesites.map((item) => `
            <article class="bm-candidate" data-candidate-id="${escapeHtml(item.id)}">
                <div class="bm-candidate-head"><strong>${escapeHtml(item.minesite.name)}</strong><span class="bm-confidence">${Number(item.confidence)}%</span></div>
                <small>${escapeHtml(item.method)}${item.minesite.country ? ` · ${escapeHtml(item.minesite.country)}` : ''}</small>
                <ul class="bm-evidence">${(item.evidence || []).slice(0, 3).map((evidence) => `<li>${escapeHtml(evidence.description)}</li>`).join('')}</ul>
                <button type="button" class="button secondary small" data-select-candidate="${escapeHtml(item.id)}">Select</button>
            </article>`).join('') : '<p class="bm-empty">No additional governed candidate is available. Search for an authorized MineSite below.</p>';
        list.innerHTML = existing + candidates;
        list.querySelectorAll('[data-existing-mapping]').forEach((button) => button.addEventListener('click', () => {
            const mapping = currentMappings.find((item) => item.id === button.dataset.existingMapping);
            selectExistingMapping(mapping);
        }));
        list.querySelectorAll('[data-remove-mapping]').forEach((button) => button.addEventListener('click', () => {
            const mapping = currentMappings.find((item) => item.id === button.dataset.removeMapping);
            openRemoveMapping(mapping);
        }));
        list.querySelectorAll('[data-select-candidate]').forEach((button) => button.addEventListener('click', () => {
            const candidate = detail.candidate_minesites.find((item) => item.id === button.dataset.selectCandidate);
            selectSite(candidate.minesite, candidate);
        }));
        const manual = $('[data-bm-manual-site]');
        if (manual) manual.hidden = false;
        $('[data-bm-decision-form]')?.removeAttribute('hidden');
        if (!state.mapping && !state.site && currentMappings.length) selectExistingMapping(currentMappings[0]);
        else renderImpact();
    }

    function selectExistingMapping(mapping) {
        if (!mapping) return;
        state.mapping = mapping;
        state.businessAccountId = mapping.business_account_id || state.detail.account.business_account_id;
        state.site = mapping.minesite;
        state.candidate = null;
        state.evidenceIds = [];
        document.querySelectorAll('[data-existing-row]').forEach((node) => node.classList.toggle('selected', node.dataset.existingRow === mapping.id));
        document.querySelectorAll('.bm-candidate').forEach((node) => node.classList.remove('selected'));
        $('[data-bm-decision-form]')?.removeAttribute('hidden');
        renderImpact();
    }

    function applyPersistedMapping(mapping) {
        if (!mapping || !state.detail) return;
        const mappings = [...(state.detail.current_mappings || [])];
        const index = mappings.findIndex((item) => item.id === mapping.id);
        if (index >= 0) mappings[index] = mapping;
        else mappings.unshift(mapping);
        state.detail.current_mappings = mappings;
        state.mapping = mapping;
        state.site = mapping.minesite || null;
        state.candidate = null;
        state.evidenceIds = [];
        const selectedRow = document.querySelector(`.bm-account-row[data-account-id="${CSS.escape(state.selected.source_account_id)}"] .bm-status`);
        if (selectedRow) selectedRow.textContent = mapping.status || 'Draft';
        renderDetail();
    }

    async function reconcileAfterSave() {
        const accountId = state.selected?.source_account_id;
        const refreshes = [loadOverview(), loadAccounts()];
        if (accountId) refreshes.push(selectAccount(accountId, true));
        await Promise.allSettled(refreshes);
    }

    function openRemoveMapping(mapping) {
        if (!mapping) return;
        state.pendingRemoval = mapping;
        $('[data-bm-delete-summary]').innerHTML = `<strong>${escapeHtml(state.detail.account.name)}</strong><br>${escapeHtml(mapping.minesite?.name || mapping.no_site_reason || 'No MineSite Required')}`;
        $('[data-bm-delete-reason]').value = '';
        $('[data-bm-delete-error]').hidden = true;
        $('[data-bm-delete-dialog]').showModal();
        $('[data-bm-delete-reason]').focus();
    }

    async function confirmRemoveMapping() {
        const mapping = state.pendingRemoval;
        const reason = $('[data-bm-delete-reason]').value.trim();
        const errorNode = $('[data-bm-delete-error]');
        if (!mapping || !reason) {
            errorNode.textContent = 'Enter a removal reason.';
            errorNode.hidden = false;
            return;
        }
        const button = $('[data-bm-delete-confirm]');
        button.disabled = true;
        button.textContent = 'Removing...';
        try {
            const endpoint = `${app.dataset.draftUrl}${mapping.id}/archive/`;
            const data = await api(endpoint, { method: 'POST', body: JSON.stringify({ version: mapping.version, reason, idempotency_key: requestId() }) });
            if (!data.database_commit_confirmed) throw new Error('The database commit was not confirmed.');
            state.detail.current_mappings = (state.detail.current_mappings || []).filter((item) => item.id !== mapping.id);
            state.mapping = null;
            state.site = null;
            state.pendingRemoval = null;
            $('[data-bm-delete-dialog]').close();
            renderDetail();
            toast('Mapping removed from the current Mapping state. Published history is preserved.');
            await reconcileAfterSave();
        } catch (error) {
            errorNode.textContent = error.message;
            errorNode.hidden = false;
        } finally {
            button.disabled = false;
            button.textContent = 'Remove mapping';
        }
    }

    function selectSite(site, candidate = null) {
        state.mapping = null;
        state.site = site;
        state.candidate = candidate;
        state.evidenceIds = (candidate?.evidence || []).map((item) => item.id);
        document.querySelectorAll('.bm-candidate').forEach((node) => node.classList.toggle('selected', node.dataset.candidateId === candidate?.id));
        $('[data-bm-decision-form]')?.removeAttribute('hidden');
        const formError = $('[data-bm-form-error]');
        if (formError) formError.hidden = true;
        renderImpact();
    }

    function renderImpact() {
        const target = $('[data-bm-impact]');
        if (!state.detail) { target.innerHTML = '<p class="bm-empty">Revenue, fleet and validation warnings will appear here.</p>'; return; }
        const revenue = state.detail.revenue_summary || {};
        const fleet = state.candidate?.fleet_summary || state.site?.fleet_summary || state.detail.fleet_summary || {};
        const revenuePeriod = state.sourceContext?.revenue?.label || 'YTD';
        const previousYear = state.sourceContext?.revenue?.previous_year;
        const showComparison = state.revenuePeriod !== 'all' && previousYear;
        const selectedCategory = revenue.selected_category || 'All Mining';
        const categories = Object.fromEntries((revenue.by_category || []).map((item) => [item.code, item.value]));
        target.innerHTML = `
            <div class="bm-impact-summary">
                <div><span>${escapeHtml(revenue.scope_label || 'Account Revenue')} · ${escapeHtml(selectedCategory)} ${escapeHtml(revenuePeriod)}</span><strong>${revenue.ytd === null || revenue.ytd === undefined ? 'Not available' : money(revenue.ytd)}</strong></div>
                <div><span>${showComparison ? `Previous Year ${escapeHtml(previousYear)}` : 'Period comparison'}</span><strong>${showComparison ? (revenue.previous_year === null || revenue.previous_year === undefined ? 'Not available' : money(revenue.previous_year)) : 'Not applicable'}</strong></div>
                <div><span>Fleet</span><strong>${Number(fleet.count || 0).toLocaleString()}</strong></div>
                <div><span>Serial Numbers</span><strong>${Number(fleet.serial_count || 0).toLocaleString()}</strong></div>
            </div>
            <div class="bm-account-revenue-breakdown" aria-label="Mining revenue by business line">
                <div><span>Machine</span><strong>${money(categories.PRIME)}</strong></div>
                <div><span>Parts</span><strong>${money(categories.PARTS)}</strong></div>
                <div><span>Service</span><strong>${money(categories.SERVICE)}</strong></div>
                <div><span>Rental</span><strong>${money(categories.RENTAL)}</strong></div>
            </div>
            <p><strong>Models</strong><br>${escapeHtml((fleet.models || []).join(', ') || 'Not available')}</p>
            <p><strong>${state.mapping ? 'Current mapped MineSite' : 'Selected MineSite'}</strong><br>${escapeHtml(state.site?.name || state.mapping?.no_site_reason || 'Not selected')}${state.mapping ? ` · ${escapeHtml(state.mapping.status)}` : ''}</p>
            ${fleet.count && !revenue.ytd ? `<p class="bm-warning">This Account has fleet context but no revenue for ${escapeHtml(revenuePeriod)}.</p>` : ''}
            ${state.detail.current_mappings?.length ? `<p class="bm-warning">This Account already has ${state.detail.current_mappings.length} active MineSite mapping(s).</p>` : ''}`;
    }

    function validationPayload() {
        return {
            mapping_id: state.mapping?.id,
            version: state.mapping?.version || 0,
            business_account_id: state.businessAccountId || state.detail?.account.business_account_id,
            minesite_id: state.site?.id,
            account_role: 'Mapped Account',
            is_primary_site: false,
            valid_from: null,
            valid_to: null,
            candidate_id: state.candidate?.id || null,
            evidence_ids: state.evidenceIds,
            comment: '',
            mapping_method: state.candidate ? 'Deterministic suggestion validated by human' : 'Manual',
            allocation: {
                required: false,
            },
            idempotency_key: requestId(),
        };
    }

    function openValidation() {
        const payload = validationPayload();
        const missing = [];
        if (!payload.business_account_id) missing.push('Account');
        if (!payload.minesite_id) missing.push('MineSite');
        const formError = $('[data-bm-form-error]');
        if (missing.length) {
            const message = `Complete the following fields: ${missing.join(', ')}.`;
            if (formError) { formError.textContent = message; formError.hidden = false; }
            toast(message);
            if (!payload.minesite_id) $('[data-bm-minesite-search]')?.focus();
            return;
        }
        if (formError) formError.hidden = true;
        state.pendingValidation = payload;
        $('[data-bm-validation-review]').innerHTML = `<dl class="bm-review-list"><dt>Account</dt><dd>${escapeHtml(state.detail.account.name)}</dd><dt>MineSite</dt><dd>${escapeHtml(state.site.name)}</dd></dl>`;
        $('[data-bm-dialog-error]').hidden = true;
        $('[data-bm-validation-dialog]').showModal();
    }

    async function confirmValidation() {
        const button = document.querySelector('[data-bm-confirm]');
        button.disabled = true; button.textContent = 'Saving to Mining 360...';
        try {
            const url = state.mapping ? app.dataset.validateUrl.replace('/validate/', `/${state.mapping.id}/validate/`) : app.dataset.validateUrl;
            const data = await api(url, { method: 'POST', body: JSON.stringify(state.pendingValidation) });
            if (!data.database_commit_confirmed) throw new Error('The database commit was not confirmed.');
            applyPersistedMapping(data.mapping);
            $('[data-bm-validation-dialog]').close();
            toast('Mapping validated and saved in the Mining 360 database.');
            await reconcileAfterSave();
        } catch (error) {
            const node = $('[data-bm-dialog-error]'); node.textContent = error.message; node.hidden = false;
        } finally { button.disabled = false; button.textContent = 'Validate Mapping'; }
    }

    async function saveDraft() {
        const payload = validationPayload();
        if (!payload.business_account_id) { toast('Select an Account first.'); return; }
        const button = $('[data-bm-save-draft]'); button.disabled = true; button.textContent = 'Saving Draft...';
        try {
            const data = await api(app.dataset.draftUrl, { method: 'POST', body: JSON.stringify(payload) });
            applyPersistedMapping(data.mapping);
            toast('Draft saved in the Mining 360 database.');
            await reconcileAfterSave();
        } catch (error) { toast(error.message); }
        finally { button.disabled = false; button.textContent = 'Save as Draft'; }
    }

    async function recordNoSiteRequired() {
        const reason = $('[data-bm-no-site-reason]').value;
        if (!state.detail?.account.business_account_id || !reason) { toast('Select an Account and a No MineSite Required reason.'); return; }
        const payload = validationPayload();
        payload.minesite_id = null;
        payload.account_role = 'No MineSite Required';
        payload.no_site_reason = reason;
        payload.idempotency_key = requestId();
        try {
            const data = await api(app.dataset.noSiteUrl, { method: 'POST', body: JSON.stringify(payload) });
            if (!data.database_commit_confirmed) throw new Error('The database commit was not confirmed.');
            applyPersistedMapping(data.mapping);
            toast('No MineSite Required decision saved in the Mining 360 database.');
            await reconcileAfterSave();
        } catch (error) { toast(error.message); }
    }

    async function searchMineSites() {
        const query = $('[data-bm-minesite-search]').value.trim();
        const target = $('[data-bm-minesite-results]');
        if (query.length < 2) { target.innerHTML = ''; return; }
        try {
            const data = await api(`${app.dataset.minesitesUrl}?search=${encodeURIComponent(query)}`);
            target.innerHTML = data.results?.length ? data.results.map((item) => `<button type="button" data-site-id="${escapeHtml(item.id)}">${escapeHtml(item.name)} <small>${escapeHtml(item.country || '')}</small></button>`).join('') : '<p class="bm-empty">No authorized MineSite found.</p>';
            target.querySelectorAll('[data-site-id]').forEach((button) => button.addEventListener('click', () => selectSite(data.results.find((item) => item.id === button.dataset.siteId))));
        } catch (error) { target.innerHTML = `<p class="bm-empty">${escapeHtml(error.message)}</p>`; }
    }

    async function loadConflicts() {
        const target = $('[data-bm-conflicts]'); target.innerHTML = '<p class="bm-empty">Loading conflicts...</p>';
        try {
            const data = await api(withPageFilters(app.dataset.conflictsUrl));
            target.innerHTML = data.results?.length ? data.results.map((item) => `<div class="bm-conflict-row"><strong>${escapeHtml(item.type)}</strong><p>${escapeHtml(item.message)}</p></div>`).join('') : '<p class="bm-empty">No mapping conflict is currently detected.</p>';
        } catch (error) { target.innerHTML = `<p class="bm-empty">${escapeHtml(error.message)}</p>`; }
    }

    function renderSynchronization(run) {
        const panel = $('[data-bm-sync-progress]');
        if (!panel || !run) return;
        const progress = Math.max(0, Math.min(100, Number(run.progress_percent || 0)));
        panel.hidden = false;
        panel.dataset.status = run.status || '';
        $('[data-bm-sync-status]').textContent = run.display_status || run.status || 'Preparing';
        $('[data-bm-sync-stage]').textContent = run.stage || 'Preparing synchronization';
        $('[data-bm-sync-percent]').textContent = `${progress}%`;
        $('[data-bm-sync-bar]').value = progress;
        $('[data-bm-sync-bar]').textContent = `${progress}%`;
        const processed = Number(run.records_read || 0);
        const created = Number(run.records_created || 0);
        const updated = Number(run.records_updated || 0);
        const unchanged = Number(run.records_unchanged || 0);
        const rejected = Number(run.records_rejected || 0);
        const warnings = Number(run.warning_count || 0);
        const failures = Number(run.failure_count || 0);
        $('[data-bm-sync-counts]').textContent = processed || created || updated || unchanged || warnings || failures
            ? `${processed.toLocaleString()} read · ${created.toLocaleString()} created · ${updated.toLocaleString()} updated · ${unchanged.toLocaleString()} unchanged · ${rejected.toLocaleString()} rejected · ${warnings.toLocaleString()} warnings · ${failures.toLocaleString()} failures`
            : '';
        const button = $('[data-bm-sync]');
        if (button) {
            button.disabled = ['Queued', 'Running'].includes(run.status);
            button.textContent = button.disabled ? 'Synchronizing...' : 'Synchronize sources';
        }
    }

    async function pollSynchronization(run) {
        window.clearTimeout(syncPollTimer);
        try {
            const data = await api(run.status_url || `${app.dataset.syncUrl}${run.id}/`);
            const current = data.run || data;
            renderSynchronization(current);
            if (['Queued', 'Running'].includes(current.status)) {
                syncPollTimer = window.setTimeout(() => pollSynchronization(current), 1500);
                return;
            }
            if (['Completed', 'Partial'].includes(current.status)) {
                toast(current.status === 'Completed' ? 'Source synchronization completed.' : 'Synchronization completed with warnings.');
                await Promise.all([loadOverview(), loadAccounts()]);
            } else if (current.status === 'Failed') {
                toast('The source data is temporarily unavailable. Existing validated mappings remain available.');
            }
        } catch (error) {
            const button = $('[data-bm-sync]');
            if (button) { button.disabled = false; button.textContent = 'Synchronize sources'; }
            toast(error.message);
        }
    }

    async function restoreSynchronizationStatus() {
        if (!$('[data-bm-sync-progress]')) return;
        try {
            const data = await api(app.dataset.syncUrl);
            if (!data.run) return;
            renderSynchronization(data.run);
            if (['Queued', 'Running'].includes(data.run.status)) pollSynchronization(data.run);
        } catch (_) {
            // Page data remains usable when synchronization status cannot be loaded.
        }
    }

    let debounce;
    $('[data-bm-account-search]').addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(() => { state.page = 1; loadAccounts(); }, 250); });
    $('[data-bm-country-scope]').addEventListener('change', async (event) => {
        state.country = event.target.value;
        state.page = 1;
        state.selected = null; state.detail = null; state.site = null; state.candidate = null; state.mapping = null; state.businessAccountId = null; state.evidenceIds = [];
        $('[data-bm-selected-summary]').innerHTML = '<p class="bm-empty">Select one Account to review candidates and evidence.</p>';
        $('[data-bm-alias-panel]')?.setAttribute('hidden', '');
        $('[data-bm-operating-country-panel]')?.setAttribute('hidden', '');
        $('[data-bm-candidate-list]').innerHTML = '';
        $('[data-bm-decision-form]')?.setAttribute('hidden', '');
        $('[data-bm-manual-site]')?.setAttribute('hidden', '');
        $('[data-bm-generate]')?.setAttribute('disabled', '');
        renderImpact();
        const refreshes = [loadOverview(), loadAccounts()];
        if (!$('[data-bm-panel="conflicts"]').hidden) refreshes.push(loadConflicts());
        await Promise.all(refreshes);
    });
    $('[data-bm-account-status]').addEventListener('change', () => { state.page = 1; loadAccounts(); });
    $('[data-bm-alias-form]')?.addEventListener('submit', saveAlias);
    $('[data-bm-operating-country-form]')?.addEventListener('submit', saveOperatingCountry);
    $('[data-bm-operating-country-clear]')?.addEventListener('click', clearOperatingCountry);
    $('[data-bm-period-select]')?.addEventListener('change', async (event) => {
        state.revenuePeriod = event.target.value || 'ytd';
        state.page = 1;
        const refreshes = [loadOverview(), loadAccounts()];
        if ($('[data-bm-key-account-dialog]')?.open) refreshes.push(loadKeyAccounts($('[data-bm-key-search]')?.value || ''));
        if (state.selected?.source_account_id) refreshes.push(selectAccount(state.selected.source_account_id, true));
        await Promise.all(refreshes);
    });
    $('[data-bm-key-account-filter]').addEventListener('change', (event) => { state.keyAccountFilter = event.target.value; state.page = 1; loadAccounts(); });
    $('[data-bm-account-sort]').addEventListener('change', () => { state.page = 1; loadAccounts(); });
    all('[data-bm-account-view]').forEach((button) => button.addEventListener('click', async () => {
        state.accountView = button.dataset.bmAccountView;
        state.page = 1;
        all('[data-bm-account-view]').forEach((item) => {
            const active = item === button;
            item.classList.toggle('active', active);
            item.setAttribute('aria-pressed', String(active));
        });
        const accountId = state.selected?.source_account_id;
        await loadAccounts();
        if (accountId) await selectAccount(accountId);
    }));
    $('[data-bm-key-accounts]')?.addEventListener('click', async () => {
        $('[data-bm-key-error]').hidden = true;
        $('[data-bm-key-account-dialog]').showModal();
        await loadKeyAccounts();
    });
    all('[data-bm-key-close]').forEach((button) => button.addEventListener('click', () => $('[data-bm-key-account-dialog]').close()));
    all('[data-bm-key-delete-close]').forEach((button) => button.addEventListener('click', () => $('[data-bm-key-delete-dialog]').close()));
    $('[data-bm-key-delete-confirm]')?.addEventListener('click', deleteKeyAccount);
    $('[data-bm-key-create]')?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = $('[data-bm-key-name]');
        const errorNode = $('[data-bm-key-error]');
        errorNode.hidden = true;
        try {
            const data = await api(app.dataset.keyAccountsUrl, { method: 'POST', body: JSON.stringify({ name: input.value }) });
            state.selectedKeyAccountId = data.key_account.id;
            input.value = '';
            await loadKeyAccounts($('[data-bm-key-search]')?.value || '');
            toast('Key Account created and saved in Mining 360.');
        } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    });
    let keySearchDebounce;
    $('[data-bm-key-search]')?.addEventListener('input', (event) => {
        clearTimeout(keySearchDebounce);
        keySearchDebounce = setTimeout(() => loadKeyAccounts(event.target.value), 250);
    });
    $('[data-bm-key-sort]')?.addEventListener('change', (event) => {
        state.keyAccountSort = event.target.value;
        loadKeyAccounts($('[data-bm-key-search]')?.value || '');
    });
    all('[data-bm-revenue-filter]').forEach((button) => button.addEventListener('click', async () => {
        state.revenueLob = button.dataset.bmRevenueFilter || '';
        all('[data-bm-revenue-filter]').forEach((item) => {
            const active = item === button;
            item.classList.toggle('active', active);
            item.setAttribute('aria-pressed', String(active));
        });
        state.page = 1;
        const refreshes = [loadOverview(), loadAccounts()];
        if ($('[data-bm-key-account-dialog]')?.open) refreshes.push(loadKeyAccounts($('[data-bm-key-search]')?.value || ''));
        if (state.selected?.source_account_id) refreshes.push(selectAccount(state.selected.source_account_id, true));
        await Promise.all(refreshes);
    }));
    $('[data-bm-previous]').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadAccounts(); } });
    $('[data-bm-next]').addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; loadAccounts(); } });
    $('[data-bm-minesite-search]')?.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(searchMineSites, 250); });
    $('[data-bm-decision-form]')?.addEventListener('submit', (event) => { event.preventDefault(); openValidation(); });
    $('[data-bm-save-draft]')?.addEventListener('click', saveDraft);
    $('[data-bm-no-site]')?.addEventListener('click', recordNoSiteRequired);
    document.querySelector('[data-bm-confirm]')?.addEventListener('click', confirmValidation);
    $('[data-bm-delete-confirm]')?.addEventListener('click', confirmRemoveMapping);
    all('[data-bm-delete-close]').forEach((button) => button.addEventListener('click', () => $('[data-bm-delete-dialog]').close()));
    all('[data-bm-close]').forEach((button) => button.addEventListener('click', () => $('[data-bm-validation-dialog]').close()));
    $('[data-bm-generate]')?.addEventListener('click', async () => {
        try {
            await api(app.dataset.candidatesUrl, { method: 'POST', body: JSON.stringify({ source_account_id: state.selected.source_account_id }) });
            await selectAccount(state.selected.source_account_id); toast('Deterministic candidates refreshed.');
        } catch (error) { toast(error.message); }
    });
    $('[data-bm-sync]')?.addEventListener('click', async () => {
        const button = $('[data-bm-sync]');
        button.disabled = true;
        button.textContent = 'Starting...';
        try {
            const data = await api(app.dataset.syncUrl, { method: 'POST', body: '{}' });
            renderSynchronization(data.run);
            pollSynchronization(data.run);
        } catch (error) {
            button.disabled = false;
            button.textContent = 'Synchronize sources';
            toast(error.message);
        }
    });
    $('[data-bm-publish]')?.addEventListener('click', async () => {
        openPublicationsPanel();
        await previewPublication();
        await loadPublicationHistory();
    });
    $('[data-bm-publication-preview]')?.addEventListener('click', previewPublication);
    $('[data-bm-publication-confirm]')?.addEventListener('click', publishMappingVersion);
    all('[data-bm-tab]').forEach((button) => button.addEventListener('click', () => {
        all('[data-bm-tab]').forEach((item) => { item.classList.toggle('active', item === button); item.setAttribute('aria-selected', item === button ? 'true' : 'false'); });
        all('[data-bm-panel]').forEach((panel) => { panel.hidden = panel.dataset.bmPanel !== button.dataset.bmTab; panel.classList.toggle('active', !panel.hidden); });
        if (button.dataset.bmTab === 'conflicts') loadConflicts();
        if (button.dataset.bmTab === 'published') { previewPublication(); loadPublicationHistory(); }
    }));

    loadOverview();
    loadAccounts();
    restoreSynchronizationStatus();
})();
