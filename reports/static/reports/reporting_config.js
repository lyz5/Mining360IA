(() => {
    const root = document.querySelector("[data-reporting-config]");
    if (!root) return;

    const rows = [...root.querySelectorAll("[data-report-config-row]")];
    const search = root.querySelector("[data-report-config-search]");
    const empty = root.querySelector("[data-report-config-empty]");
    const csrf = root.querySelector("[name=csrfmiddlewaretoken]")?.value || "";

    function updateVisibility(input) {
        const label = input.closest("[data-report-config-row]")?.querySelector("[data-visibility-label]");
        if (label) label.textContent = input.checked ? "Visible" : "Hidden";
    }

    function refreshSearchValue(row, displayName) {
        const sourceName = row.dataset.reportName || "";
        row.dataset.search = `${sourceName} ${displayName}`.toLowerCase();
    }

    async function saveDisplayName(row) {
        const input = row.querySelector("[data-report-display-input]");
        const button = row.querySelector("[data-report-display-save]");
        const status = row.querySelector("[data-report-display-status]");
        const value = input.value.trim().replace(/\s+/g, " ");
        if (!value) {
            status.textContent = "Display name is required.";
            status.className = "is-error";
            input.focus();
            return;
        }
        input.value = value;
        button.disabled = true;
        input.disabled = true;
        status.textContent = "Saving...";
        status.className = "is-saving";
        try {
            const response = await fetch(row.dataset.displayNameUrl, {
                method: "PATCH",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({
                    display_name: value,
                    category: row.querySelector("[data-report-category]")?.value || "other",
                    description: row.querySelector("[data-report-description]")?.value || "",
                    tags: (row.querySelector("[data-report-tags]")?.value || "").split(",").map(item => item.trim()).filter(Boolean),
                    business_owner: row.querySelector("[data-report-owner]")?.value || "",
                    freshness_threshold_hours: row.querySelector("[data-report-freshness]")?.value || null,
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.error || "Display name could not be saved.");
            input.value = payload.report.display_name;
            row.querySelector("[data-report-display-title]").textContent = payload.report.display_name;
            refreshSearchValue(row, payload.report.display_name);
            status.textContent = "Saved";
            status.className = "is-saved";
        } catch (error) {
            status.textContent = error.message;
            status.className = "is-error";
        } finally {
            button.disabled = false;
            input.disabled = false;
        }
    }

    root.addEventListener("change", event => {
        if (event.target.matches("input[name='visible_report_ids']")) updateVisibility(event.target);
    });

    root.addEventListener("click", event => {
        const save = event.target.closest("[data-report-display-save]");
        if (save) return saveDisplayName(save.closest("[data-report-config-row]"));
        const reset = event.target.closest("[data-report-display-reset]");
        if (reset) {
            const row = reset.closest("[data-report-config-row]");
            const source = row.dataset.reportName || "";
            row.querySelector("[data-report-display-input]").value = source;
            return saveDisplayName(row);
        }
        const select = event.target.closest("[data-report-config-select]");
        if (select) {
            const checked = select.dataset.reportConfigSelect === "all";
            rows.forEach(row => {
                if (row.hidden) return;
                const input = row.querySelector("input[name='visible_report_ids']");
                input.checked = checked;
                updateVisibility(input);
            });
        }
    });

    root.addEventListener("keydown", event => {
        if (event.target.matches("[data-report-display-input]") && event.key === "Enter") {
            event.preventDefault();
            saveDisplayName(event.target.closest("[data-report-config-row]"));
        }
    });

    search?.addEventListener("input", () => {
        const query = search.value.trim().toLowerCase();
        let visibleRows = 0;
        rows.forEach(row => {
            row.hidden = Boolean(query) && !row.dataset.search.includes(query);
            if (!row.hidden) visibleRows += 1;
        });
        if (empty) empty.hidden = visibleRows !== 0;
    });
})();
