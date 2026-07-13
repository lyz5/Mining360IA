(function () {
    const form = document.querySelector("[data-source-form]");
    if (!form) {
        return;
    }

    const engineSelect = form.querySelector("#engine");

    function currentEngine() {
        if (engineSelect) {
            return engineSelect.value || "SQL Server";
        }
        return form.dataset.defaultEngine || "SQL Server";
    }

    function setSectionState(section, active) {
        section.hidden = !active;
        section.querySelectorAll("input, select, textarea").forEach((field) => {
            if (field.name === "engine") {
                return;
            }
            if (active) {
                field.disabled = false;
                if (field.dataset.wasRequired === "1") {
                    field.required = true;
                }
            } else {
                if (field.required) {
                    field.dataset.wasRequired = "1";
                }
                field.required = false;
                field.disabled = true;
            }
        });
    }

    function syncSections() {
        const engine = currentEngine();
        form.querySelectorAll("[data-engine-section]").forEach((section) => {
            const active = section.dataset.engineSection === engine;
            setSectionState(section, active);
        });
    }

    if (engineSelect) {
        engineSelect.addEventListener("change", syncSections);
    }

    syncSections();
})();
