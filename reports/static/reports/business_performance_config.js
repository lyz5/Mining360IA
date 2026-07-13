(function () {
    "use strict";
    const root = document.querySelector("[data-bp-config]");
    if (!root) return;
    const csrf = document.cookie.split("; ").find(item => item.startsWith("csrftoken="))?.split("=")[1] || "";
    root.querySelector("[data-mapping-search]").addEventListener("input", event => {
        const q = event.target.value.toLowerCase();
        root.querySelectorAll("[data-mapping-row]").forEach(row => row.hidden = !row.dataset.search.toLowerCase().includes(q));
    });
    root.querySelector("[data-save-config]").addEventListener("click", async () => {
        const button = root.querySelector("[data-save-config]");
        button.disabled = true;
        button.textContent = "Saving...";
        const payload = {};
        root.querySelectorAll(".bp-config-grid [name]").forEach(input => payload[input.name] = input.type === "number" && input.value !== "" ? Number(input.value) : input.value);
        payload.mappings = Array.from(root.querySelectorAll("[data-mapping-row]")).map(row => ({
            id: Number(row.dataset.id),
            display_name: row.querySelector('[name="display_name"]').value,
            table_name: row.querySelector('[name="table_name"]').value,
            object_name: row.querySelector('[name="object_name"]').value,
            format_string: row.querySelector('[name="format_string"]').value,
            is_active: row.querySelector('[name="is_active"]').checked,
        }));
        const toast = root.querySelector("[data-config-toast]");
        try {
            const response = await fetch(root.dataset.saveUrl, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(csrf) }, body: JSON.stringify(payload) });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Save failed.");
            toast.textContent = data.message;
            toast.className = "bp-toast success";
        } catch (exc) {
            toast.textContent = exc.message;
            toast.className = "bp-toast failed";
        } finally {
            toast.hidden = false;
            button.disabled = false;
            button.textContent = "Save Configuration";
            window.setTimeout(() => { toast.hidden = true; }, 5000);
        }
    });
    root.querySelector("[data-import-model]").addEventListener("click", async event => {
        const button = event.currentTarget;
        const toast = root.querySelector("[data-config-toast]");
        button.disabled = true; button.textContent = "Importing metadata...";
        try {
            const response = await fetch(button.dataset.importUrl, { method: "POST", headers: { "X-CSRFToken": decodeURIComponent(csrf), Accept: "application/json" } });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Import failed.");
            toast.textContent = data.message; toast.className = "bp-toast success"; toast.hidden = false;
            window.setTimeout(() => location.reload(), 1200);
        } catch (exc) {
            toast.textContent = exc.message; toast.className = "bp-toast failed"; toast.hidden = false;
        } finally {
            button.disabled = false; button.textContent = "Import & Match Model";
        }
    });
}());
