(function () {
    "use strict";

    const root = document.querySelector(".resource-kb-shell");
    if (!root) return;

    const previewButton = root.querySelector("[data-kb-preview]");
    const rebuildButton = root.querySelector("[data-kb-rebuild]");
    const rebuildForm = root.querySelector("[data-kb-rebuild-form]");
    const previewHost = document.getElementById("resource-kb-preview");
    const progressHost = document.getElementById("resource-kb-progress");
    const searchForm = root.querySelector("[data-kb-search-form]");
    const searchResults = document.getElementById("resource-kb-search-results");
    const dialog = document.getElementById("resource-kb-item-dialog");
    const itemForm = dialog?.querySelector("[data-kb-item-form]");
    let previewReady = false;

    function csrfToken() {
        return document.cookie.split(";").map((item) => item.trim())
            .find((item) => item.startsWith("csrftoken="))?.split("=").slice(1).join("=") || "";
    }

    function escapeHtml(value) {
        const node = document.createElement("span");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function options() {
        return {
            with_ai: Boolean(root.querySelector("[data-kb-with-ai]")?.checked),
            with_embeddings: Boolean(root.querySelector("[data-kb-with-embeddings]")?.checked),
            force: Boolean(root.querySelector("[data-kb-force]")?.checked),
        };
    }

    async function request(url, init) {
        const response = await fetch(url, init);
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "Request failed.");
        return payload;
    }

    function setBusy(button, busy, label) {
        if (!button) return;
        if (!button.dataset.label) button.dataset.label = button.textContent;
        button.disabled = busy;
        button.textContent = busy ? label : button.dataset.label;
    }

    async function preview() {
        const settings = options();
        setBusy(previewButton, true, "Analyzing...");
        previewHost.hidden = false;
        previewHost.innerHTML = "<p>Analyzing documents without changing data...</p>";
        try {
            const params = new URLSearchParams({
                with_ai: String(settings.with_ai),
                with_embeddings: String(settings.with_embeddings),
            });
            const payload = await request(`${root.dataset.previewUrl}?${params}`);
            const data = payload.preview;
            previewHost.innerHTML = `
                <div><strong>Preview completed</strong><span>No data was changed.</span></div>
                <dl>
                    <div><dt>Documents</dt><dd>${data.documents}</dd></div>
                    <div><dt>To create</dt><dd>${data.create}</dd></div>
                    <div><dt>To update</dt><dd>${data.update}</dd></div>
                    <div><dt>Unchanged</dt><dd>${data.skip}</dd></div>
                    <div><dt>Estimated chunks</dt><dd>${data.estimated_chunks}</dd></div>
                    <div><dt>Pages</dt><dd>${data.pages}</dd></div>
                    <div><dt>Estimated sections</dt><dd>${data.estimated_sections}</dd></div>
                    <div><dt>OCR required</dt><dd>${data.ocr_required}</dd></div>
                    <div><dt>Potential duplicates</dt><dd>${data.potential_duplicates}</dd></div>
                    <div><dt>OpenAI calls</dt><dd>${data.expected_openai_calls}</dd></div>
                    <div><dt>API cost</dt><dd>$${Number(data.expected_api_cost || 0).toFixed(2)}</dd></div>
                </dl>
                <p>Processing mode: <strong>${escapeHtml(data.processing_mode)}</strong> · OpenAI calls: <strong>${data.expected_openai_calls}</strong> · API cost: <strong>$${Number(data.expected_api_cost || 0).toFixed(2)}</strong>.</p>`;
            previewReady = true;
            return true;
        } catch (error) {
            previewHost.innerHTML = `<p class="resource-kb-error">${escapeHtml(error.message)}</p>`;
            return false;
        } finally {
            setBusy(previewButton, false);
        }
    }

    async function pollRun(runId) {
        progressHost.hidden = false;
        const url = root.dataset.runUrlTemplate.replace("__RUN_ID__", runId);
        while (true) {
            const payload = await request(url);
            const run = payload.run;
            const percent = run.total_documents ? Math.round(run.processed_documents * 100 / run.total_documents) : 0;
            progressHost.innerHTML = `
                <div><strong>${escapeHtml(run.status)}</strong><span>${run.processed_documents} / ${run.total_documents} documents</span></div>
                <progress max="100" value="${percent}">${percent}%</progress>
                <p>${run.knowledge_created} knowledge items · ${run.embeddings_created} embeddings · ${run.failed_documents} failures</p>
                ${run.error_message ? `<p class="resource-kb-error">${escapeHtml(run.error_message)}</p>` : ""}`;
            if (["Completed", "Partially Completed", "Failed", "Cancelled"].includes(run.status)) {
                setBusy(rebuildButton, false);
                if (["Completed", "Partially Completed"].includes(run.status)) {
                    window.setTimeout(() => window.location.reload(), 900);
                }
                return;
            }
            await new Promise((resolve) => window.setTimeout(resolve, 1200));
        }
    }

    async function rebuild(resourceId) {
        setBusy(rebuildButton, true, "Starting...");
        try {
            const payload = await request(root.dataset.rebuildUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                body: JSON.stringify({ ...options(), resource_id: resourceId || "", force: Boolean(resourceId) || options().force }),
            });
            await pollRun(payload.run_id);
        } catch (error) {
            progressHost.hidden = false;
            progressHost.innerHTML = `<p class="resource-kb-error">${escapeHtml(error.message)}</p>`;
            setBusy(rebuildButton, false);
        }
    }

    function renderSearchResults(results) {
        searchResults.innerHTML = results.length ? results.map((item) => `
            <article>
                <div><strong>${escapeHtml(item.title)}</strong><span>${Math.round(item.score * 100)}% · ${escapeHtml(item.validation_status)}</span></div>
                <p>${escapeHtml(item.symptom || item.failure_mode || item.source.excerpt)}</p>
                ${item.recommendations?.length ? `<ul>${item.recommendations.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : ""}
                <a href="${escapeHtml(item.source.url)}">${escapeHtml(item.source.title)}${item.source.page ? ` · page ${item.source.page}` : ""}</a>
            </article>`).join("") : "<p>No authorized knowledge matches this search.</p>";
    }

    async function search(event) {
        event.preventDefault();
        const button = searchForm.querySelector("button[type='submit']");
        setBusy(button, true, "Searching...");
        try {
            const values = new FormData(searchForm);
            const payload = await request(root.dataset.searchUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                body: JSON.stringify({ query: values.get("query"), mode: values.get("mode"), limit: 8 }),
            });
            renderSearchResults(payload.results || []);
        } catch (error) {
            searchResults.innerHTML = `<p class="resource-kb-error">${escapeHtml(error.message)}</p>`;
        } finally {
            setBusy(button, false);
        }
    }

    async function editItem(id) {
        const url = root.dataset.itemUrlTemplate.replace("__ITEM_ID__", id);
        try {
            const payload = await request(url);
            const item = payload.item;
            itemForm.reset();
            Object.entries(item).forEach(([key, value]) => {
                const field = itemForm.elements.namedItem(key);
                if (!field || key === "source") return;
                field.value = Array.isArray(value) ? value.join("\n") : (value ?? "");
            });
            itemForm.elements.namedItem("id").value = id;
            dialog.querySelector("[data-kb-source]").innerHTML = `
                <strong>${escapeHtml(item.source.document)}${item.source.page ? ` · page ${item.source.page}` : ""}</strong>
                <blockquote>${escapeHtml(item.source.excerpt)}</blockquote>`;
            dialog.showModal();
        } catch (error) {
            window.alert(error.message);
        }
    }

    async function saveItem(event) {
        event.preventDefault();
        const values = new FormData(itemForm);
        const id = values.get("id");
        const body = Object.fromEntries(values.entries());
        itemForm.querySelectorAll("[data-list-field]").forEach((field) => {
            body[field.name] = field.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
        });
        const submit = itemForm.querySelector("button[type='submit']");
        setBusy(submit, true, "Enregistrement...");
        try {
            await request(root.dataset.itemUrlTemplate.replace("__ITEM_ID__", id), {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                body: JSON.stringify(body),
            });
            dialog.close();
            window.location.reload();
        } catch (error) {
            window.alert(error.message);
        } finally {
            setBusy(submit, false);
        }
    }

    previewButton?.addEventListener("click", preview);
    rebuildForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!previewReady && !(await preview())) return;
        const confirmed = window.confirm(
            "Build the initial Best Practices Knowledge Base locally? OpenAI calls: 0.",
        );
        if (confirmed) await rebuild("");
    });
    searchForm?.addEventListener("submit", search);
    itemForm?.addEventListener("submit", saveItem);
    dialog?.querySelector("[data-kb-dialog-close]")?.addEventListener("click", () => dialog.close());
    root.querySelectorAll("[data-kb-reindex]").forEach((button) => button.addEventListener("click", () => rebuild(button.dataset.kbReindex)));
    root.querySelectorAll("[data-kb-edit]").forEach((button) => button.addEventListener("click", () => editItem(button.dataset.kbEdit)));
    root.querySelectorAll("[data-kb-with-ai], [data-kb-with-embeddings], [data-kb-force]").forEach((input) => {
        input.addEventListener("change", () => {
            previewReady = false;
        });
    });
}());
