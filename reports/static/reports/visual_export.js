(() => {
    "use strict";

    const EXPORT_IGNORE_SELECTOR = "[data-export-ignore], [hidden]:not([data-export-context]), .trend-tooltip, .trend-skeleton";

    class VisualExportError extends Error {
        constructor(message, code = "VISUAL_EXPORT_FAILED") {
            super(message);
            this.name = "VisualExportError";
            this.code = code;
        }
    }

    function copyComputedStyles(source, clone) {
        const computed = window.getComputedStyle(source);
        for (const property of computed) {
            clone.style.setProperty(property, computed.getPropertyValue(property), computed.getPropertyPriority(property));
        }
        clone.style.animation = "none";
        clone.style.transition = "none";
        Array.from(source.children).forEach((child, index) => {
            if (clone.children[index]) copyComputedStyles(child, clone.children[index]);
        });
    }

    function loadImage(url) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => reject(new VisualExportError("The chart image could not be rendered."));
            image.src = url;
        });
    }

    function canvasBlob(canvas) {
        return new Promise((resolve, reject) => {
            canvas.toBlob((blob) => blob
                ? resolve(blob)
                : reject(new VisualExportError("The browser could not create the PNG.")), "image/png", 1);
        });
    }

    async function createPng(element, options = {}) {
        if (!(element instanceof Element)) {
            throw new VisualExportError("A valid visual export boundary is required.", "INVALID_EXPORT_BOUNDARY");
        }
        if (document.fonts?.ready) await document.fonts.ready;
        const rect = element.getBoundingClientRect();
        if (rect.width < 1 || rect.height < 1) {
            throw new VisualExportError("The chart is not visible.", "VISUAL_NOT_VISIBLE");
        }

        const clone = element.cloneNode(true);
        copyComputedStyles(element, clone);
        clone.querySelectorAll(EXPORT_IGNORE_SELECTOR).forEach((node) => node.remove());
        clone.removeAttribute("id");
        clone.style.width = `${rect.width}px`;
        clone.style.height = `${rect.height}px`;
        clone.style.maxWidth = "none";
        clone.style.margin = "0";
        clone.style.transform = "none";
        clone.style.boxSizing = "border-box";
        clone.style.overflow = "hidden";
        options.prepareClone?.(clone);

        const serialized = new XMLSerializer().serializeToString(clone);
        const background = options.background || "#ffffff";
        const foreignObject = `<div xmlns="http://www.w3.org/1999/xhtml" style="width:${rect.width}px;height:${rect.height}px;overflow:hidden;background:${background};">${serialized}</div>`;
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${rect.width}" height="${rect.height}" viewBox="0 0 ${rect.width} ${rect.height}"><foreignObject width="100%" height="100%">${foreignObject}</foreignObject></svg>`;
        // A blob: URL containing foreignObject taints Chromium canvases. A local
        // data: URL remains origin-clean and can safely be converted to PNG.
        const source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
        const image = await loadImage(source);
        const scale = Math.max(1, Math.min(Number(options.scale) || 2, 4));
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(rect.width * scale);
        canvas.height = Math.ceil(rect.height * scale);
        const context = canvas.getContext("2d");
        if (!context) throw new VisualExportError("Canvas rendering is unavailable.");
        context.scale(scale, scale);
        context.fillStyle = background;
        context.fillRect(0, 0, rect.width, rect.height);
        context.drawImage(image, 0, 0, rect.width, rect.height);
        return await canvasBlob(canvas);
    }

    async function writePngToClipboard(blobOrPromise) {
        if (!window.isSecureContext || !navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
            throw new VisualExportError("Image clipboard access is unavailable.", "CLIPBOARD_UNAVAILABLE");
        }
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blobOrPromise })]);
    }

    function safeFileName(value) {
        const name = String(value || "Mining360_Chart").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[_\.]+|[_\.]+$/g, "");
        return `${name || "Mining360_Chart"}.png`;
    }

    function downloadPng(blob, fileName) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = safeFileName(fileName);
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function notify(message, options = {}) {
        document.querySelector("[data-visual-export-notice]")?.remove();
        const notice = document.createElement("div");
        notice.className = `visual-export-notice${options.error ? " is-error" : ""}`;
        notice.dataset.visualExportNotice = "true";
        notice.setAttribute("role", options.error ? "alert" : "status");
        notice.setAttribute("aria-live", "polite");
        const text = document.createElement("span");
        text.textContent = message;
        notice.appendChild(text);
        if (options.actionLabel && options.onAction) {
            const action = document.createElement("button");
            action.type = "button";
            action.textContent = options.actionLabel;
            action.addEventListener("click", options.onAction);
            notice.appendChild(action);
        }
        document.body.appendChild(notice);
        if (!options.persistent) window.setTimeout(() => notice.remove(), 6000);
    }

    function bindCopyAction(options) {
        const { button, target } = options;
        if (!button || !target) return () => {};
        const french = String(options.language || document.documentElement.lang || "en").toLowerCase().startsWith("fr");
        const onClick = async () => {
            if (button.disabled || target.dataset.exportReady !== "true") return;
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
            let blob;
            try {
                // Start the clipboard operation during the click gesture. ClipboardItem
                // accepts a Blob promise while the high-resolution PNG is rendered.
                const blobPromise = createPng(target, options);
                await writePngToClipboard(blobPromise);
                blob = await blobPromise;
                notify(french
                    ? "Graphique copié. Collez-le dans PowerPoint avec Ctrl+V."
                    : "Chart copied. Paste it into PowerPoint with Ctrl+V.");
                options.onSuccess?.({ blob, method: "clipboard" });
            } catch (error) {
                notify(french
                    ? "Le presse-papiers image est indisponible. Téléchargez plutôt le PNG."
                    : "Image clipboard access is unavailable. Download the PNG instead.", {
                    error: true,
                    persistent: true,
                    actionLabel: french ? "Télécharger le PNG" : "Download PNG",
                    onAction: async () => {
                        try {
                            blob ||= await createPng(target, options);
                            downloadPng(blob, options.fileName);
                            options.onFallback?.({ blob, method: "download" });
                        } catch (downloadError) {
                            notify(downloadError.message || "PNG export failed.", { error: true });
                        }
                    },
                });
                options.onError?.(error);
            } finally {
                button.disabled = target.dataset.exportReady !== "true";
                button.removeAttribute("aria-busy");
            }
        };
        button.addEventListener("click", onClick);
        return () => button.removeEventListener("click", onClick);
    }

    window.Mining360VisualExport = Object.freeze({
        VisualExportError,
        createPng,
        writePngToClipboard,
        downloadPng,
        bindCopyAction,
    });
})();
