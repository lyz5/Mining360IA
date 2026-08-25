(() => {
    "use strict";

    const root = document.querySelector("[data-reporting-hub]");
    if (!root) return;

    const catalog = root.querySelector("[data-report-catalog]");
    const cards = Array.from(root.querySelectorAll("[data-report-card]"));
    const search = root.querySelector("[data-hub-search]");
    const searchState = root.querySelector("[data-search-state]");
    const categorySelect = root.querySelector("[data-category-filter]");
    const sortSelect = root.querySelector("[data-sort-filter]");
    const favoritesFilter = root.querySelector("[data-favorites-filter]");
    const resultCount = root.querySelector("[data-result-count]");
    const emptyState = root.querySelector("[data-report-empty]");
    const clearButtons = root.querySelectorAll("[data-clear-filters], [data-empty-clear]");
    const toast = root.querySelector("[data-reporting-toast]");
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const apiUrl = root.dataset.apiUrl;
    let requestController = null;
    let debounceTimer = null;
    let toastTimer = null;
    let allowedReportIds = null;
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

    const params = new URLSearchParams(window.location.search);
    const state = {
        q: params.get("q") || "",
        status: params.get("status") || "all",
        category: params.get("category") || "all",
        favorites: params.get("favorites") === "true",
        sort: params.get("sort") || "alphabetical",
        view: params.get("view") || localStorage.getItem("reportingHubView") || "grid",
    };

    function preserveHubReturnState() {
        sessionStorage.setItem("mining360.reportingHub.returnUrl", window.location.href);
        sessionStorage.setItem("mining360.reportingHub.scrollY", String(window.scrollY));
    }

    const embedPrefetches = new Map();
    function prefetchEmbedConfiguration(element) {
        const url = element?.dataset.embedPrefetchUrl;
        if (!url || embedPrefetches.has(url)) return;
        const task = fetch(url, {
            credentials: "same-origin",
            headers: { Accept: "application/json", "X-Mining360-Prefetch": "embed" },
        }).catch(() => null);
        embedPrefetches.set(url, task);
    }

    function bindEmbedPrefetch(element) {
        if (element.dataset.embedPrefetchBound === "1") return;
        element.dataset.embedPrefetchBound = "1";
        let timer = null;
        element.addEventListener("pointerenter", () => {
            timer = window.setTimeout(() => prefetchEmbedConfiguration(element), 120);
        });
        element.addEventListener("pointerleave", () => window.clearTimeout(timer));
        element.addEventListener("focusin", () => prefetchEmbedConfiguration(element));
        element.addEventListener("pointerdown", () => prefetchEmbedConfiguration(element));
    }

    function showToast(message, isError = false) {
        clearTimeout(toastTimer);
        toast.textContent = message;
        toast.classList.toggle("is-error", isError);
        toast.classList.add("is-visible");
        toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3200);
    }

    function updateUrl() {
        const next = new URLSearchParams();
        if (state.q) next.set("q", state.q);
        if (state.status !== "all") next.set("status", state.status);
        if (state.category !== "all") next.set("category", state.category);
        if (state.favorites) next.set("favorites", "true");
        if (state.sort !== "alphabetical") next.set("sort", state.sort);
        if (state.view !== "grid") next.set("view", state.view);
        const query = next.toString();
        history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
    }

    function normalizedTerms(value) {
        return value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    }

    function sortedCards(items) {
        return [...items].sort((a, b) => {
            const aName = a.querySelector("h3")?.textContent || "";
            const bName = b.querySelector("h3")?.textContent || "";
            if (state.sort === "alphabetical_desc") return bName.localeCompare(aName);
            if (state.sort === "status") return `${a.dataset.status}${aName}`.localeCompare(`${b.dataset.status}${bName}`);
            if (state.sort === "recently_refreshed") {
                const aRefresh = a.querySelector("[data-status-detail]")?.textContent || "";
                const bRefresh = b.querySelector("[data-status-detail]")?.textContent || "";
                return bRefresh.localeCompare(aRefresh);
            }
            return aName.localeCompare(bName);
        });
    }

    function applyFilters() {
        const terms = normalizedTerms(state.q);
        let visible = cards.filter((card) => {
            const matchesServer = !allowedReportIds || allowedReportIds.has(card.dataset.reportId);
            const matchesText = terms.every((term) => (card.dataset.search || "").includes(term));
            const matchesStatus = state.status === "all" || card.dataset.status === state.status;
            const matchesCategory = state.category === "all" || card.dataset.category === state.category;
            const matchesFavorite = !state.favorites || card.dataset.favorite === "true";
            return matchesServer && matchesText && matchesStatus && matchesCategory && matchesFavorite;
        });
        visible = sortedCards(visible);
        const visibleIds = new Set(visible.map((card) => card.dataset.reportId));
        cards.forEach((card) => { card.hidden = !visibleIds.has(card.dataset.reportId); });
        visible.forEach((card) => catalog.appendChild(card));
        resultCount.textContent = String(visible.length);
        emptyState.hidden = visible.length > 0;
        const hasFilters = Boolean(state.q || state.status !== "all" || state.category !== "all" || state.favorites);
        clearButtons.forEach((button) => { button.hidden = !hasFilters && button.hasAttribute("data-clear-filters"); });
        updateControls();
        updateUrl();
    }

    function updateControls() {
        search.value = state.q;
        categorySelect.value = state.category;
        sortSelect.value = state.sort;
        favoritesFilter.classList.toggle("is-active", state.favorites);
        favoritesFilter.setAttribute("aria-pressed", String(state.favorites));
        root.querySelectorAll("[data-status]").forEach((button) => {
            const active = button.dataset.status === state.status;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        root.querySelectorAll("[data-health-filter]").forEach((button) => {
            const active = button.dataset.healthFilter === state.status;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        root.querySelectorAll("[data-view]").forEach((button) => {
            const active = button.dataset.view === state.view;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        catalog.classList.toggle("is-list", state.view === "list");
    }

    async function fetchFilteredReports() {
        requestController?.abort();
        requestController = new AbortController();
        const query = new URLSearchParams({
            q: state.q,
            status: state.status,
            category: state.category,
            favorites: String(state.favorites),
            sort: state.sort,
        });
        searchState.textContent = "Searching...";
        try {
            const response = await fetch(`${apiUrl}?${query}`, {
                headers: { Accept: "application/json" },
                signal: requestController.signal,
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Reports could not be loaded.");
            allowedReportIds = new Set(payload.reports.map((report) => report.id));
            applyFilters();
            searchState.textContent = "";
        } catch (error) {
            if (error.name === "AbortError") return;
            searchState.textContent = "Unavailable";
            showToast("Report search is temporarily unavailable.", true);
        }
    }

    function scheduleFetch() {
        clearTimeout(debounceTimer);
        allowedReportIds = null;
        applyFilters();
        debounceTimer = setTimeout(fetchFilteredReports, 300);
    }

    function setStatus(status, scroll = false) {
        state.status = state.status === status && status !== "all" ? "all" : status;
        scheduleFetch();
        if (scroll) document.querySelector("#all-reports")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function clearFilters() {
        Object.assign(state, { q: "", status: "all", category: "all", favorites: false, sort: "alphabetical" });
        scheduleFetch();
        search.focus();
    }

    function createCompactFavorite(card) {
        const link = card.querySelector(".open-report-button").href;
        const name = card.querySelector("h3").textContent.trim();
        const category = card.querySelector(".report-category-label").textContent.trim();
        const item = document.createElement("a");
        item.href = link;
        item.dataset.compactReportId = card.dataset.reportId;
        item.innerHTML = `<span class="compact-report-mark ${card.dataset.category.replaceAll("_", "-")}"></span><span><strong></strong><small></small></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg>`;
        item.querySelector("strong").textContent = name;
        item.querySelector("small").textContent = category;
        return item;
    }

    function syncFavoriteSection(card, isFavorite) {
        const section = root.querySelector("[data-favorites-section]");
        const list = root.querySelector("[data-favorites-list]");
        list.querySelector(`[data-compact-report-id="${card.dataset.reportId}"]`)?.remove();
        if (isFavorite && list.children.length < 4) list.appendChild(createCompactFavorite(card));
        section.hidden = list.children.length === 0;
    }

    async function toggleFavorite(card) {
        const button = card.querySelector("[data-favorite-button]");
        if (button.classList.contains("is-saving")) return;
        const wasFavorite = card.dataset.favorite === "true";
        button.classList.add("is-saving");
        try {
            const response = await fetch(button.dataset.url, {
                method: wasFavorite ? "DELETE" : "POST",
                headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Favorite could not be updated.");
            const isFavorite = Boolean(payload.is_favorite);
            card.dataset.favorite = String(isFavorite);
            button.classList.toggle("is-favorite", isFavorite);
            button.setAttribute("aria-pressed", String(isFavorite));
            button.title = isFavorite ? "Remove from favorites" : "Add to favorites";
            button.setAttribute("aria-label", `${isFavorite ? "Remove" : "Add"} ${card.querySelector("h3").textContent.trim()} ${isFavorite ? "from" : "to"} favorites`);
            card.querySelector("[data-menu-favorite]").textContent = isFavorite ? "Remove favorite" : "Add to favorites";
            syncFavoriteSection(card, isFavorite);
            applyFilters();
            showToast(isFavorite ? "Report added to favorites." : "Report removed from favorites.");
        } catch (error) {
            showToast(error.message, true);
        } finally {
            button.classList.remove("is-saving");
        }
    }

    function statusPresentation(status, lastRefresh) {
        const code = String(status || "").toLocaleLowerCase().replaceAll(" ", "");
        if (["unknown", "inprogress", "running", "notstarted", "refreshing"].includes(code)) return ["refreshing", "Refreshing", "Refresh in progress"];
        if (code === "failed") return ["failed", "Failed", "Latest refresh needs attention"];
        if (code === "completed") return ["healthy", "Healthy", lastRefresh ? `Refreshed ${lastRefresh}` : "Refresh completed"];
        return ["no_refresh", "No Refresh", "No refresh history available"];
    }

    function updateCardStatus(card, payload) {
        const [code, label, detail] = statusPresentation(payload.status, payload.last_refresh);
        card.dataset.status = code;
        const line = card.querySelector("[data-report-status]");
        line.className = `report-status-line status-${code}`;
        line.querySelector("[data-status-label]").textContent = label;
        line.querySelector("[data-status-detail]").textContent = detail;
        const button = card.querySelector("[data-report-refresh]");
        button.classList.toggle("is-refreshing", Boolean(payload.is_refreshing));
        button.disabled = Boolean(payload.is_refreshing);
    }

    async function pollRefresh(card) {
        for (let attempt = 0; attempt < 60; attempt += 1) {
            await new Promise((resolve) => setTimeout(resolve, 5000));
            try {
                const response = await fetch(card.dataset.refreshUrl, { headers: { Accept: "application/json" } });
                const payload = await response.json();
                if (!response.ok || !payload.ok) throw new Error(payload.error || "Refresh status unavailable.");
                updateCardStatus(card, payload);
                if (!payload.is_refreshing) {
                    showToast(payload.status === "Failed" ? "The report refresh failed." : "The report refresh completed.", payload.status === "Failed");
                    scheduleFetch();
                    return;
                }
            } catch (error) {
                showToast(error.message, true);
                return;
            }
        }
        showToast("The refresh is still running in Power BI.");
    }

    async function refreshReport(card) {
        const button = card.querySelector("[data-report-refresh]");
        if (button.disabled || button.classList.contains("is-refreshing")) return;
        button.disabled = true;
        button.classList.add("is-refreshing");
        try {
            const response = await fetch(card.dataset.refreshUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.error || "The refresh could not be started.");
            updateCardStatus(card, payload);
            showToast("Report refresh started.");
            pollRefresh(card);
        } catch (error) {
            button.disabled = false;
            button.classList.remove("is-refreshing");
            showToast(error.message, true);
        }
    }

    function renderTroubleshooting(result) {
        const checks = result.checks || [];
        const actions = result.actions_taken || [];
        const manual = result.manual_actions || [];
        return `
            <p class="troubleshoot-summary">${escapeHtml(result.status || "Diagnostics completed")}</p>
            <div class="troubleshoot-checks">
                ${checks.map((item) => `<div class="troubleshoot-check"><span><strong>${escapeHtml(item.name || item.code)}</strong><small>${escapeHtml(item.value || "")}</small></span><em>${escapeHtml(item.status || "Checked")}</em></div>`).join("")}
            </div>
            ${actions.length ? `<section class="troubleshoot-actions"><h3>Automatic actions</h3>${actions.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</section>` : ""}
            ${manual.length ? `<section class="troubleshoot-actions"><h3>Administrator action required</h3>${manual.map((item) => `<p><strong>${escapeHtml(item.title)}</strong><br>${escapeHtml(item.detail || "")}</p>`).join("")}</section>` : ""}
        `;
    }

    async function troubleshootReport(card) {
        const dialog = root.querySelector("[data-report-troubleshoot-dialog]");
        const content = dialog.querySelector("[data-troubleshoot-content]");
        content.innerHTML = '<p class="troubleshoot-summary">Running Power BI diagnostics...</p>';
        dialog.showModal();
        try {
            const response = await fetch(card.dataset.troubleshootUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Accept": "application/json", "X-CSRFToken": csrfToken},
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Troubleshooting could not complete.");
            content.innerHTML = renderTroubleshooting(payload.result || {});
            if (payload.refresh) {
                updateCardStatus(card, payload.refresh);
                if (payload.refresh.is_refreshing) pollRefresh(card);
            }
        } catch (error) {
            content.innerHTML = `<p class="troubleshoot-summary">${escapeHtml(error.message)}</p>`;
        }
    }

    search.addEventListener("input", () => { state.q = search.value.trim(); scheduleFetch(); });
    categorySelect.addEventListener("change", () => { state.category = categorySelect.value; scheduleFetch(); });
    sortSelect.addEventListener("change", () => { state.sort = sortSelect.value; scheduleFetch(); });
    favoritesFilter.addEventListener("click", () => { state.favorites = !state.favorites; scheduleFetch(); });
    root.querySelectorAll("[data-status]").forEach((button) => button.addEventListener("click", () => setStatus(button.dataset.status)));
    root.querySelectorAll("[data-health-filter]").forEach((button) => button.addEventListener("click", () => setStatus(button.dataset.healthFilter, true)));
    root.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => {
        state.view = button.dataset.view;
        localStorage.setItem("reportingHubView", state.view);
        applyFilters();
    }));
    clearButtons.forEach((button) => button.addEventListener("click", clearFilters));

    cards.forEach((card) => {
        bindEmbedPrefetch(card);
        const openCard = (event) => {
            if (event.target.closest("a, button, input, select, textarea, [role='menu']")) return;
            preserveHubReturnState();
            window.location.assign(card.dataset.launchUrl);
        };
        card.addEventListener("click", openCard);
        card.addEventListener("keydown", (event) => {
            if ((event.key === "Enter" || event.key === " ") && event.target === card) {
                event.preventDefault();
                preserveHubReturnState();
                window.location.assign(card.dataset.launchUrl);
            }
        });
        const thumbnail = card.querySelector("[data-report-thumbnail]");
        thumbnail?.addEventListener("error", () => {
            thumbnail.hidden = true;
            card.querySelector(".report-card-visual")?.classList.add("has-image-fallback");
        }, { once: true });
        card.querySelector("[data-favorite-button]").addEventListener("click", () => toggleFavorite(card));
        card.querySelector("[data-report-refresh]").addEventListener("click", () => refreshReport(card));
        card.querySelector("[data-menu-favorite]").addEventListener("click", () => toggleFavorite(card));
        card.querySelector("[data-menu-refresh]").addEventListener("click", () => refreshReport(card));
        card.querySelectorAll("[data-report-troubleshoot]").forEach((button) => button.addEventListener("click", () => troubleshootReport(card)));
        const more = card.querySelector("[data-more-button]");
        const menu = card.querySelector("[data-actions-menu]");
        more.addEventListener("click", (event) => {
            event.stopPropagation();
            root.querySelectorAll("[data-actions-menu]").forEach((other) => { if (other !== menu) other.hidden = true; });
            menu.hidden = !menu.hidden;
            more.setAttribute("aria-expanded", String(!menu.hidden));
        });
    });
    root.querySelectorAll("[data-embed-prefetch-url]").forEach((element) => bindEmbedPrefetch(element));
    root.querySelectorAll("[data-troubleshoot-close]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
    document.addEventListener("click", (event) => {
        if (event.target.closest("a[href*='/reporting/reports/'], a[href*='/reports/']")) preserveHubReturnState();
        if (event.target.closest("[data-actions-menu], [data-more-button]")) return;
        root.querySelectorAll("[data-actions-menu]").forEach((menu) => { menu.hidden = true; });
        root.querySelectorAll("[data-more-button]").forEach((button) => button.setAttribute("aria-expanded", "false"));
    });
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        root.querySelectorAll("[data-actions-menu]").forEach((menu) => { menu.hidden = true; });
        root.querySelectorAll("[data-more-button]").forEach((button) => button.setAttribute("aria-expanded", "false"));
    });

    applyFilters();
    const returnUrl = sessionStorage.getItem("mining360.reportingHub.returnUrl");
    const returnScroll = Number(sessionStorage.getItem("mining360.reportingHub.scrollY") || 0);
    if (returnUrl === window.location.href && returnScroll > 0) {
        requestAnimationFrame(() => window.scrollTo({ top: returnScroll, behavior: "instant" }));
    }
    if (state.q || state.status !== "all" || state.category !== "all" || state.favorites) scheduleFetch();
    if (!navigator.connection?.saveData) {
        const recent = root.querySelector("[data-recent-section] [data-embed-prefetch-url]");
        if (recent) window.setTimeout(() => prefetchEmbedConfiguration(recent), 800);
    }
})();
