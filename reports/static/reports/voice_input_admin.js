(function () {
    const root = document.querySelector("[data-voice-admin-url]");
    const form = document.getElementById("voice-config-form");
    const status = document.getElementById("voice-config-status");
    if (!root || !form) return;

    const booleanFields = new Set([
        "enabled",
        "auto_detect_language",
        "auto_send",
        "store_audio",
        "stop_recording_after_silence",
    ]);
    const numberFields = new Set([
        "maximum_duration_seconds",
        "maximum_file_size_mb",
        "retention_duration_days",
        "daily_user_limit_minutes",
        "request_rate_limit_per_minute",
        "maximum_concurrent_transcriptions",
        "timeout_seconds",
        "retry_count",
    ]);

    function csrfToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function showStatus(message, error) {
        status.hidden = false;
        status.textContent = message;
        status.classList.toggle("error", Boolean(error));
    }

    function applyConfig(config) {
        const pilotField = form.elements.namedItem("pilot_user_ids");
        if (pilotField) {
            pilotField.innerHTML = (config.available_users || []).map((user) =>
                `<option value="${Number(user.id)}">${String(user.label || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")}</option>`
            ).join("");
            const selected = new Set((config.pilot_user_ids || []).map(Number));
            Array.from(pilotField.options).forEach((option) => {
                option.selected = selected.has(Number(option.value));
            });
        }
        Object.entries(config || {}).forEach(([name, value]) => {
            const field = form.elements.namedItem(name);
            if (!field) return;
            if (name === "pilot_user_ids") return;
            if (booleanFields.has(name)) field.checked = Boolean(value);
            else if (name === "allowed_audio_formats") field.value = (value || []).join(", ");
            else field.value = value ?? "";
        });
    }

    function payload() {
        const result = {};
        Array.from(form.elements).forEach((field) => {
            if (!field.name) return;
            if (field.name === "pilot_user_ids") {
                result[field.name] = Array.from(field.selectedOptions).map((option) => Number(option.value));
                return;
            }
            if (booleanFields.has(field.name)) result[field.name] = field.checked;
            else if (numberFields.has(field.name)) result[field.name] = Number(field.value);
            else if (field.name === "allowed_audio_formats") {
                result[field.name] = field.value.split(",").map((item) => item.trim()).filter(Boolean);
            } else result[field.name] = field.value;
        });
        return result;
    }

    async function load() {
        try {
            const response = await fetch(root.dataset.voiceAdminUrl, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Unable to load voice configuration.");
            applyConfig(data.config);
        } catch (error) {
            showStatus(error.message, true);
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = form.querySelector('[type="submit"]');
        submit.disabled = true;
        showStatus("Saving voice configuration...", false);
        try {
            const response = await fetch(root.dataset.voiceAdminUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken(),
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify(payload()),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Unable to save voice configuration.");
            applyConfig(data.config);
            showStatus("Voice input configuration saved.", false);
        } catch (error) {
            showStatus(error.message, true);
        } finally {
            submit.disabled = false;
        }
    });

    load();
}());
