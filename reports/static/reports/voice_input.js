(function () {
    const root = document.querySelector("[data-voice-input-root]");
    const app = document.querySelector("[data-voice-transcribe-url]");
    if (!root || !app) return;

    const input = document.getElementById("ai-question");
    const button = document.getElementById("ai-voice-button");
    const panel = document.getElementById("ai-voice-panel");
    const status = document.getElementById("ai-voice-status");
    const duration = document.getElementById("ai-voice-duration");
    const cancelButton = document.getElementById("ai-voice-cancel");
    const level = document.getElementById("ai-voice-level");
    const privacy = document.getElementById("ai-voice-privacy");
    const privacyText = document.getElementById("ai-voice-privacy-text");
    const privacyContinue = document.getElementById("ai-voice-privacy-continue");
    const privacyCancel = document.getElementById("ai-voice-privacy-cancel");
    const acknowledgedKey = "mining360-voice-privacy-acknowledged";

    const labels = {
        en: {
            idle: "Speak instead of typing",
            permission: "Requesting microphone permission...",
            recording: "Recording",
            processing: "Transcribing audio...",
            ready: "Transcribed from audio. Review or edit before sending.",
            denied: "Microphone access was denied. Allow it in your browser settings to use voice input.",
            unavailable: "No microphone was detected.",
            unsupported: "Voice input is not supported by this browser.",
            insecure: "Voice input requires HTTPS or localhost.",
            empty: "No voice was detected. Please try again.",
            network: "Voice transcription is temporarily unavailable. You can still type your question.",
            maxDuration: "Maximum recording duration reached. Transcribing audio...",
            noVoice: "No voice detected",
            sending: "Sending in {seconds} seconds...",
            cancel: "Cancel",
            continue: "Continue",
        },
    };

    let config = null;
    let recorder = null;
    let stream = null;
    let chunks = [];
    let cancelled = false;
    let startedAt = 0;
    let timer = null;
    let maxTimer = null;
    let audioContext = null;
    let analyserFrame = null;
    let lastVoiceRequest = null;
    let autoSendTimer = null;
    let readyResetTimer = null;

    function csrfToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function language() {
        return "en";
    }

    function text(key) {
        return labels[language()][key] || labels.en[key] || key;
    }

    function setState(name, message) {
        root.dataset.voiceState = name;
        panel.hidden = name === "idle";
        status.textContent = message || text(name);
        button.classList.toggle("is-recording", name === "recording");
        button.disabled = ["permission", "processing"].includes(name);
        cancelButton.hidden = !["recording", "error"].includes(name);
        level.hidden = name !== "recording";
        button.setAttribute("aria-label", name === "recording" ? "Stop voice recording" : text("idle"));
        button.title = name === "recording" ? "Stop voice recording" : text("idle");
    }

    function formatDuration(seconds) {
        const safe = Math.max(0, Math.floor(seconds));
        return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
    }

    function supportedMimeType() {
        const candidates = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm"];
        const allowed = new Set(config.allowed_audio_formats || []);
        return candidates.find((candidate) => {
            const base = candidate.split(";")[0];
            return allowed.has(base) && MediaRecorder.isTypeSupported(candidate);
        }) || "";
    }

    function cleanRecording() {
        clearInterval(timer);
        clearTimeout(maxTimer);
        if (analyserFrame) cancelAnimationFrame(analyserFrame);
        if (audioContext) audioContext.close().catch(() => {});
        if (stream) stream.getTracks().forEach((track) => track.stop());
        timer = null;
        maxTimer = null;
        analyserFrame = null;
        audioContext = null;
        stream = null;
        recorder = null;
        chunks = [];
        duration.textContent = "";
        level.dataset.level = "";
    }

    function monitorLevel(mediaStream) {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) return;
        audioContext = new Context();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        audioContext.createMediaStreamSource(mediaStream).connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        let quietFrames = 0;
        const tick = () => {
            analyser.getByteFrequencyData(data);
            const average = data.reduce((sum, value) => sum + value, 0) / data.length;
            level.dataset.level = average < 5 ? "low" : average < 28 ? "normal" : "high";
            quietFrames = average < 3 ? quietFrames + 1 : 0;
            status.textContent = quietFrames > 300 ? text("noVoice") : text("recording");
            analyserFrame = requestAnimationFrame(tick);
        };
        tick();
    }

    async function beginRecording() {
        if (!window.isSecureContext && !["localhost", "127.0.0.1"].includes(location.hostname)) {
            setState("error", text("insecure"));
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
            setState("error", text("unsupported"));
            return;
        }
        const mimeType = supportedMimeType();
        if (!mimeType) {
            setState("error", text("unsupported"));
            return;
        }
        setState("permission", text("permission"));
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            });
        } catch (error) {
            const message = ["NotAllowedError", "SecurityError"].includes(error.name)
                ? text("denied")
                : ["NotFoundError", "DevicesNotFoundError"].includes(error.name)
                    ? text("unavailable")
                    : text("network");
            setState("error", message);
            return;
        }
        chunks = [];
        cancelled = false;
        recorder = new MediaRecorder(stream, { mimeType });
        recorder.addEventListener("dataavailable", (event) => {
            if (event.data?.size) chunks.push(event.data);
        });
        recorder.addEventListener("stop", async () => {
            const elapsed = Math.min((Date.now() - startedAt) / 1000, config.maximum_duration_seconds);
            const blob = new Blob(chunks, { type: recorder?.mimeType || mimeType });
            cleanRecording();
            if (!cancelled) await uploadAudio(blob, elapsed);
            else setState("idle", "");
        });
        startedAt = Date.now();
        recorder.start(500);
        setState("recording", `${text("recording")} 00:00`);
        timer = setInterval(() => {
            duration.textContent = formatDuration((Date.now() - startedAt) / 1000);
        }, 250);
        maxTimer = setTimeout(() => {
            if (recorder?.state === "recording") {
                status.textContent = text("maxDuration");
                recorder.stop();
            }
        }, config.maximum_duration_seconds * 1000);
        monitorLevel(stream);
    }

    function stopRecording(cancel) {
        if (!recorder || recorder.state !== "recording") return;
        cancelled = Boolean(cancel);
        recorder.stop();
    }

    async function uploadAudio(blob, elapsed) {
        if (!blob.size) {
            setState("error", text("empty"));
            return;
        }
        setState("processing", text("processing"));
        const requestId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        const mimeType = blob.type.split(";")[0];
        const extension = mimeType.includes("mp4") ? "m4a" : mimeType.split("/")[1] || "audio";
        const form = new FormData();
        form.append("audio_file", blob, `voice-${requestId}.${extension}`);
        form.append("request_id", requestId);
        form.append("conversation_id", sessionStorage.getItem("mining360-ai-conversation-id") || "");
        form.append("language_hint", config.default_language === "auto" ? "" : config.default_language);
        form.append("duration_seconds", elapsed.toFixed(3));
        form.append("mime_type", mimeType);
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), Math.max(10000, (config.timeout_seconds || 120) * 1000));
        try {
            const response = await fetch(app.dataset.voiceTranscribeUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
                body: form,
                signal: controller.signal,
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) throw new Error(payload.message || payload.error || text("network"));
            lastVoiceRequest = {
                input_mode: "voice",
                detected_language: payload.detected_language,
                voice_request_id: payload.request_id,
                audio_duration_seconds: payload.duration_seconds,
            };
            applyTranscription(payload.transcription);
        } catch (error) {
            setState("error", error.name === "AbortError" ? text("network") : error.message);
        } finally {
            clearTimeout(timeout);
        }
    }

    function notifyReady() {
        window.dispatchEvent(new CustomEvent("mining360:voice-transcription-ready", {
            detail: lastVoiceRequest || { input_mode: "voice" },
        }));
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
        setState("ready", text("ready"));
        window.clearTimeout(readyResetTimer);
        if (config.auto_send) {
            let seconds = 3;
            cancelButton.hidden = false;
            cancelButton.setAttribute("aria-label", "Cancel automatic send");
            cancelButton.title = "Cancel automatic send";
            status.textContent = text("sending").replace("{seconds}", seconds);
            autoSendTimer = window.setInterval(() => {
                seconds -= 1;
                if (seconds <= 0) {
                    window.clearInterval(autoSendTimer);
                    autoSendTimer = null;
                    window.dispatchEvent(new CustomEvent("mining360:submit-question"));
                    return;
                }
                status.textContent = text("sending").replace("{seconds}", seconds);
            }, 1000);
        } else {
            readyResetTimer = window.setTimeout(() => setState("idle", ""), 1800);
        }
    }

    function applyTranscription(transcription) {
        const transcript = String(transcription || "").trim();
        if (!transcript) {
            setState("error", text("empty"));
            return;
        }
        input.value = input.value.trim()
            ? `${input.value.trim()} ${transcript}`
            : transcript;
        notifyReady();
    }

    button.addEventListener("click", () => {
        if (root.dataset.voiceState === "recording") {
            stopRecording(false);
            return;
        }
        if (!sessionStorage.getItem(acknowledgedKey)) {
            privacy.hidden = false;
            privacyText.textContent = config.privacy_message || "";
            return;
        }
        beginRecording();
    });
    privacyContinue.addEventListener("click", () => {
        sessionStorage.setItem(acknowledgedKey, "1");
        privacy.hidden = true;
        beginRecording();
    });
    privacyCancel.addEventListener("click", () => {
        privacy.hidden = true;
        input.focus();
    });
    cancelButton.addEventListener("click", () => {
        if (recorder?.state === "recording") {
            stopRecording(true);
            return;
        }
        if (autoSendTimer) {
            window.clearInterval(autoSendTimer);
            autoSendTimer = null;
            setState("ready", text("ready"));
            readyResetTimer = window.setTimeout(() => setState("idle", ""), 1800);
            return;
        }
        setState("idle", "");
    });

    fetch(`${app.dataset.voiceConfigUrl}?language=${encodeURIComponent(language())}`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then((response) => response.json())
        .then((payload) => {
            config = payload.config;
            if (!payload.ok || !config?.enabled) return;
            privacyCancel.textContent = text("cancel");
            privacyContinue.textContent = text("continue");
            button.hidden = false;
            button.title = text("idle");
            setState("idle", "");
        })
        .catch(() => {});
}());
