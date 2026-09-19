(function () {
    class Mining360PowerBIEmbed {
        constructor(container, options) {
            this.container = container;
            this.options = options || {};
            this.report = null;
            this.loaded = false;
            this.rendered = false;
            this.contextReady = false;
            this.events = [];
            this.refreshTimer = null;
            this.lifecycle = "idle";
            this.currentReportId = null;
            this.operationId = 0;
            this.embedPromise = null;
            this.configRequest = null;
            this.embedAbort = null;
            this.handlers = null;
            this.loadTimers = [];
            this.renderTimer = null;
            this.filterRevision = 0;
            this.filterQueue = Promise.resolve();
            this.appliedFilterFingerprint = "";
            this.slicerCache = new Map();
            this.metrics = {
                embedCallCount: 0,
                embedConfigRequestCount: 0,
                filterApplyCount: 0,
                instanceResetCount: 0,
                retryCount: 0,
            };
        }

        transition(next, details) {
            if (next === "requesting_embed_config") {
                this.finishLoadingSpinner();
                this.finishSpinner = window.m360AjaxSpinner?.begin();
            } else if (["ready", "rendered", "degraded", "disposing", "idle"].includes(next)) {
                this.finishLoadingSpinner();
            }
            const previous = this.lifecycle;
            this.lifecycle = next;
            this.emit("lifecycle", Object.assign({ previous, state: next }, details || {}));
        }

        emit(type, details) {
            if (type === "error") this.finishLoadingSpinner();
            const event = { type, details: details || {}, at: new Date().toISOString() };
            this.events.push(event);
            if (this.events.length > 100) this.events.shift();
            if (typeof this.options.onEvent === "function") this.options.onEvent(event);
        }

        async requestConfig(reportId, { signal, refresh = false } = {}) {
            if (!refresh && this.configRequest?.reportId === reportId) return this.configRequest.promise;
            const url = new URL(
                this.options.embedConfigUrl.replace("__REPORT_ID__", encodeURIComponent(reportId)),
                window.location.origin,
            );
            if (this.options.rlsRole) url.searchParams.set("role", this.options.rlsRole);
            url.searchParams.set("open_request_id", this.options.openRequestId || "");
            const execute = async (attempt = 0) => {
                this.metrics.embedConfigRequestCount += 1;
                const response = await fetch(url, {
                    credentials: "same-origin",
                    signal,
                    headers: { "X-Report-Open-ID": this.options.openRequestId || "" },
                });
                let payload = {};
                try { payload = await response.json(); } catch (_error) { /* normalized below */ }
                if (!response.ok || !payload.ok) {
                    const error = new Error(payload.error || "Embed configuration unavailable.");
                    const statusCodes = {
                        401: "EMBED_TOKEN_FAILED",
                        403: "REPORT_ACCESS_DENIED",
                        404: "REPORT_NOT_FOUND",
                        429: "POWERBI_RATE_LIMIT",
                    };
                    error.code = payload.error_code || statusCodes[response.status] || "EMBED_CONFIG_FAILED";
                    error.status = response.status;
                    error.retryAfter = Number(response.headers.get("Retry-After") || 0);
                    error.authenticationRequired = Boolean(payload.authentication_required);
                    error.connectUrl = payload.connect_url || "";
                    error.authenticationMode = payload.authentication_mode || "";
                    const transient = response.status === 429 || response.status >= 500;
                    if (transient && attempt < 1 && !signal?.aborted) {
                        this.metrics.retryCount += 1;
                        const waitMs = error.retryAfter ? error.retryAfter * 1000 : 750 + Math.round(Math.random() * 250);
                        await new Promise((resolve) => window.setTimeout(resolve, waitMs));
                        return execute(attempt + 1);
                    }
                    throw error;
                }
                return payload.config;
            };
            const promise = execute().finally(() => {
                if (this.configRequest?.promise === promise) this.configRequest = null;
            });
            if (!refresh) this.configRequest = { reportId, promise };
            return promise;
        }

        async embed(reportId) {
            if (this.report && this.currentReportId === reportId && this.loaded) return this.report;
            if (this.embedPromise && this.currentReportId === reportId) return this.embedPromise;
            if (this.report || this.embedPromise) this.dispose("report_change");
            this.currentReportId = reportId;
            const operationId = ++this.operationId;
            this.embedAbort = new AbortController();
            this.transition("requesting_embed_config", { reportId, operationId });
            this.embedPromise = this.initializeEmbed(reportId, operationId);
            try {
                return await this.embedPromise;
            } catch (error) {
                if (this.operationId === operationId) this.finishLoadingSpinner();
                throw error;
            } finally {
                if (this.operationId === operationId) this.embedPromise = null;
            }
        }

        finishLoadingSpinner() {
            this.finishSpinner?.();
            this.finishSpinner = null;
        }

        async initializeEmbed(reportId, operationId) {
            if (!window.powerbi || !window["powerbi-client"]) throw new Error("Power BI JavaScript API is unavailable.");
            const models = window["powerbi-client"].models;
            const config = await this.requestConfig(reportId, { signal: this.embedAbort.signal });
            const embedSessionId = config.embedSessionId || this.options.openRequestId || "";
            delete config.embedSessionId;
            if (operationId !== this.operationId) {
                const error = new Error("Stale report request ignored.");
                error.code = "STALE_REQUEST";
                throw error;
            }
            const isAad = String(config.tokenType || "").toLowerCase() === "aad";
            config.tokenType = isAad ? models.TokenType.Aad : models.TokenType.Embed;
            config.permissions = models.Permissions.Read;
            config.settings = Object.assign({ panes: { filters: { visible: false }, pageNavigation: { visible: false } } }, config.settings || {});
            const openingProfile = config.openingProfile || {};
            const displayOptions = {
                fit_to_page: models.DisplayOption.FitToPage,
                fit_to_width: models.DisplayOption.FitToWidth,
                actual_size: models.DisplayOption.ActualSize,
            };
            config.settings.layoutType = models.LayoutType.Custom;
            config.settings.customLayout = Object.assign({}, config.settings.customLayout || {}, {
                displayOption: displayOptions[openingProfile.displayOption] ?? models.DisplayOption.FitToPage,
            });
            config.settings.background = openingProfile.backgroundType === "transparent"
                ? models.BackgroundType.Transparent
                : models.BackgroundType.Default;
            delete config.openingProfile;
            if (isAad) {
                config.eventHooks = Object.assign({}, config.eventHooks || {}, {
                    accessTokenProvider: async () => {
                        try {
                            const refreshed = await this.requestConfig(reportId, { refresh: true });
                            return refreshed.accessToken || null;
                        } catch (error) {
                            this.emit("token_refresh_failed", { message: error.message, code: error.code || "" });
                            return null;
                        }
                    },
                });
            }
            this.transition("embedding", { reportId, operationId, embedSessionId });
            if (this.options.stableRuntime === false) {
                window.powerbi.reset(this.container);
                this.metrics.instanceResetCount += 1;
            }
            this.metrics.embedCallCount += 1;
            this.report = window.powerbi.embed(this.container, config);
            await new Promise((resolve, reject) => {
                let settled = false;
                const delayed = window.setTimeout(() => {
                    this.transition("degraded", { reportId, reason: "POWERBI_LOAD_DELAYED" });
                    this.emit("load_delayed", { reportId });
                }, Number(this.options.loadedWarningMs || (this.options.stableRuntime === false ? 120000 : 90000)));
                const fatal = window.setTimeout(() => {
                    if (settled || operationId !== this.operationId) return;
                    settled = true;
                    const error = new Error("The report is taking too long to load from Power BI.");
                    error.code = "POWERBI_LOAD_FAILED";
                    reject(error);
                }, Number(this.options.loadedTimeoutMs || (this.options.stableRuntime === false ? 120000 : 240000)));
                this.loadTimers = [delayed, fatal];
                const clearLoadTimers = () => {
                    this.loadTimers.forEach((timer) => window.clearTimeout(timer));
                    this.loadTimers = [];
                };
                this.handlers = {
                    loaded: () => {
                    if (settled || operationId !== this.operationId) return;
                    settled = true;
                    clearLoadTimers();
                    this.loaded = true;
                    this.transition("loaded", { reportId, operationId });
                    this.renderTimer = window.setTimeout(() => {
                        if (operationId !== this.operationId || this.lifecycle === "ready") return;
                        this.transition("degraded", { reportId, reason: "POWERBI_RENDER_DELAYED" });
                        this.emit("render_delayed", { reportId });
                    }, Number(this.options.renderedWarningMs || 120000));
                    this.emit("loaded", { reportId });
                    resolve();
                    },
                    rendered: () => {
                        if (operationId !== this.operationId) return;
                        window.clearTimeout(this.renderTimer);
                        this.renderTimer = null;
                        this.rendered = true;
                        this.transition(this.contextReady ? "ready" : "rendered", { reportId, operationId });
                        this.emit("rendered", { reportId });
                        if (this.contextReady) this.emit("ready", { reportId });
                    },
                    error: (event) => {
                    const details = event?.detail || {};
                    this.emit("error", details);
                    if (!settled) {
                        settled = true;
                        clearLoadTimers();
                        const error = new Error(details.message || "Power BI reported an error.");
                        error.code = details.errorCode || "POWERBI_LOAD_FAILED";
                        reject(error);
                    }
                    },
                    pageChanged: (event) => this.emit("page_changed", event?.detail || {}),
                    dataSelected: (event) => this.emit("data_selected", event?.detail || {}),
                };
                Object.entries(this.handlers).forEach(([name, handler]) => this.report.on(name, handler));
            });
            if (!isAad) this.scheduleTokenRefresh(reportId, config.expiresAt);
            return this.report;
        }

        scheduleTokenRefresh(reportId, expiresAt) {
            window.clearTimeout(this.refreshTimer);
            const delay = expiresAt
                ? Math.max(30000, (Number(expiresAt) * 1000) - Date.now() - (5 * 60 * 1000))
                : 45 * 60 * 1000;
            this.refreshTimer = window.setTimeout(
                () => this.refreshAccessToken(reportId, 1),
                Math.min(delay, 2147483647),
            );
        }

        async refreshAccessToken(reportId, retriesRemaining) {
            try {
                const config = await this.requestConfig(reportId, { refresh: true });
                if (!this.report || this.currentReportId !== reportId) return;
                await this.report.setAccessToken(config.accessToken);
                this.emit("token_refreshed", { reportId });
                this.scheduleTokenRefresh(reportId, config.expiresAt);
            } catch (error) {
                if (retriesRemaining > 0 && [0, 401, 429, 500, 502, 503, 504].includes(Number(error.status || 0))) {
                    this.metrics.retryCount += 1;
                    this.refreshTimer = window.setTimeout(
                        () => this.refreshAccessToken(reportId, retriesRemaining - 1),
                        2000,
                    );
                    return;
                }
                this.emit("token_refresh_failed", {
                    message: error.message,
                    code: error.code || "TOKEN_REFRESH_FAILED",
                    authenticationRequired: Boolean(error.authenticationRequired),
                    connectUrl: error.connectUrl || "",
                });
            }
        }

        async getPages() {
            if (!this.report || !this.loaded) throw new Error("The report is not loaded.");
            return this.report.getPages();
        }

        async setActivePage(pageInternalName, pageDisplayName) {
            if (!pageInternalName && !pageDisplayName) return null;
            const pages = await this.getPages();
            let page = pages.find((item) => item.name === pageInternalName);
            if (!page && pageDisplayName) {
                const expected = this.normalizeSemanticName(pageDisplayName);
                page = pages.find(
                    (item) => this.normalizeSemanticName(item.displayName) === expected,
                ) || pages.find((item) => {
                    const candidate = this.normalizeSemanticName(item.displayName);
                    return candidate.includes(expected) || expected.includes(candidate);
                });
                if (page) {
                    this.emit("page_resolved_by_display_name", {
                        requestedInternalName: pageInternalName,
                        requestedDisplayName: pageDisplayName,
                        resolvedInternalName: page.name,
                    });
                }
            }
            if (!page) {
                throw new Error(`Power BI page '${pageDisplayName || pageInternalName}' was not found.`);
            }
            await page.setActive();
            this.emit("page_activated", { name: page.name, displayName: page.displayName });
            return page;
        }

        basicFilter(instruction) {
            if (instruction.filter_type === "advanced") {
                return {
                    $schema: "http://powerbi.com/product/schema#advanced",
                    target: { table: instruction.table, column: instruction.column },
                    logicalOperator: "And",
                    conditions: instruction.conditions || [],
                    filterType: window["powerbi-client"].models.FilterType.AdvancedFilter,
                };
            }
            return {
                $schema: "http://powerbi.com/product/schema#basic",
                target: { table: instruction.table, column: instruction.column },
                operator: instruction.operator || "In",
                values: instruction.values || [],
                filterType: window["powerbi-client"].models.FilterType.BasicFilter,
            };
        }

        normalizeSemanticName(value) {
            return String(value || "")
                .normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "")
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, " ")
                .trim();
        }

        filterAliases(filterCode) {
            const aliases = {
                minesite: ["minesite", "mine site", "site", "site name"],
                model: ["model", "equipment model", "machine model", "modele"],
                family: ["family", "equipment family", "product group", "parent product group"],
                serial_number: ["serial number", "serial", "sn"],
                customer: ["customer", "customer code", "client"],
                period: ["period", "date", "year month", "month", "calendar"],
            };
            return aliases[filterCode] || [filterCode];
        }

        async describeSlicer(slicer) {
            let state = null;
            try {
                state = await slicer.getSlicerState();
            } catch (error) {
                this.emit("slicer_state_warning", { visual: slicer.name, message: error.message });
            }
            const filter = state?.filters?.[0] || {};
            const target = filter.target || state?.targets?.[0] || {};
            return {
                slicer,
                state,
                target,
                names: [
                    slicer.name,
                    slicer.title,
                    target.table,
                    target.column,
                    `${target.table || ""} ${target.column || ""}`,
                ].map((value) => this.normalizeSemanticName(value)).filter(Boolean),
            };
        }

        slicerMatchScore(description, instruction) {
            if (
                instruction.slicer_internal_name
                && description.slicer.name === instruction.slicer_internal_name
            ) return 1000;

            const aliases = this.filterAliases(instruction.filter_code)
                .map((value) => this.normalizeSemanticName(value));
            let score = 0;
            for (const name of description.names) {
                for (const alias of aliases) {
                    if (!alias) continue;
                    if (name === alias) score = Math.max(score, 300);
                    else if (name.endsWith(` ${alias}`) || name.startsWith(`${alias} `)) {
                        score = Math.max(score, 220);
                    } else if (name.includes(alias) && alias.length >= 4) {
                        score = Math.max(score, 140);
                    }
                }
            }
            return score;
        }

        async resolveSlicer(instruction, slicerDescriptions) {
            const candidates = slicerDescriptions
                .map((description) => ({
                    description,
                    score: this.slicerMatchScore(description, instruction),
                }))
                .filter((candidate) => candidate.score > 0)
                .sort((left, right) => right.score - left.score);
            return candidates[0]?.description || null;
        }

        canonicalFilters(instructions) {
            const normalized = (instructions || []).map((instruction) => ({
                filter_code: instruction.filter_code || "",
                table: instruction.table || "",
                column: instruction.column || "",
                filter_type: instruction.filter_type || "basic",
                operator: instruction.operator || "In",
                values: [...(instruction.values || [])].map(String).sort(),
                conditions: instruction.conditions || [],
                slicer_internal_name: instruction.slicer_internal_name || "",
            }));
            normalized.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
            return JSON.stringify(normalized);
        }

        async applyFilters(page, instructions) {
            const fingerprint = this.canonicalFilters(instructions);
            if (fingerprint === this.appliedFilterFingerprint) {
                this.emit("filters_unchanged", { count: (instructions || []).length });
                return { applied: false, unchanged: true };
            }
            const revision = ++this.filterRevision;
            const operation = async () => {
                if (revision !== this.filterRevision) return { applied: false, superseded: true };
                this.transition("applying_initial_context", { revision });
                const result = await this.applyFiltersNow(page, instructions, revision);
                if (revision === this.filterRevision) {
                    this.appliedFilterFingerprint = fingerprint;
                    this.metrics.filterApplyCount += 1;
                    this.transition("ready", { revision });
                }
                return result;
            };
            this.filterQueue = this.filterQueue.catch(() => {}).then(operation);
            return this.filterQueue;
        }

        async applyFiltersNow(page, instructions, revision) {
            const models = window["powerbi-client"].models;
            const pageFilters = [];
            const pageKey = page?.name || "active";
            const needsSlicerResolution = (instructions || []).some(
                (instruction) => Boolean(instruction.slicer_internal_name),
            );
            let slicerDescriptions = needsSlicerResolution ? this.slicerCache.get(pageKey) : [];
            if (needsSlicerResolution && !slicerDescriptions) {
                const slicers = page ? await page.getSlicers() : [];
                slicerDescriptions = await Promise.all(
                    slicers.map((slicer) => this.describeSlicer(slicer))
                );
                this.slicerCache.set(pageKey, slicerDescriptions);
            }
            for (const instruction of instructions || []) {
                if (revision !== this.filterRevision) return { applied: false, superseded: true };
                let applied = false;
                const matched = instruction.slicer_internal_name
                    ? await this.resolveSlicer(instruction, slicerDescriptions)
                    : null;
                if (matched && typeof matched.slicer.setSlicerState === "function") {
                    const target = matched.target || {};
                    const slicerInstruction = Object.assign({}, instruction, {
                        table: target.table || instruction.table,
                        column: target.column || instruction.column,
                    });
                    try {
                        await matched.slicer.setSlicerState({
                            filters: [this.basicFilter(slicerInstruction)],
                        });
                        applied = true;
                        this.emit("slicer_applied", {
                            filterCode: instruction.filter_code,
                            visual: matched.slicer.name,
                            table: slicerInstruction.table,
                            column: slicerInstruction.column,
                        });
                    } catch (error) {
                        this.emit("slicer_failed", {
                            filterCode: instruction.filter_code,
                            visual: matched.slicer.name,
                            message: error.message,
                        });
                    }
                }
                if (!applied) pageFilters.push({
                    instruction,
                    filter: this.basicFilter(instruction),
                });
            }
            if (pageFilters.length && page) {
                try {
                    await page.updateFilters(
                        models.FiltersOperations.ReplaceAll,
                        pageFilters.map((item) => item.filter),
                    );
                } catch (error) {
                    this.emit("page_filters_failed", { message: error.message });
                    throw error;
                }
                this.emit("page_filters_applied", {
                    count: pageFilters.length,
                    requested: pageFilters.length,
                });
            }
            return { applied: true, count: (instructions || []).length };
        }

        async focusVisual(page, visualInternalName, action) {
            if (!page || !visualInternalName) return;
            const visuals = await page.getVisuals();
            const visual = visuals.find((item) => item.name === visualInternalName);
            if (!visual) throw new Error(`Power BI visual '${visualInternalName}' was not found.`);
            if (["focus", "show"].includes(action || "focus") && typeof page.setVisualDisplayState === "function") {
                const mode = window["powerbi-client"].models.VisualContainerDisplayMode.Visible;
                await page.setVisualDisplayState(visual.name, mode);
            }
            this.emit("visual_resolved", { name: visual.name, title: visual.title, type: visual.type, action: action || "focus" });
        }

        async navigate(instructions) {
            if (!instructions?.report_id) return;
            if (!this.report || this.options.currentReportId !== instructions.report_id) {
                this.options.currentReportId = instructions.report_id;
                await this.embed(instructions.report_id);
            }
            let page = null;
            if (instructions.page_internal_name || instructions.page_display_name) {
                page = await this.setActivePage(
                    instructions.page_internal_name,
                    instructions.page_display_name,
                );
            }
            if (!page) {
                const pages = await this.getPages();
                page = pages.find((item) => item.isActive) || pages[0];
            }
            await this.applyFilters(page, instructions.filters || []);
            if (instructions.visual_internal_name) {
                try {
                    await this.focusVisual(page, instructions.visual_internal_name, instructions.visual_action);
                } catch (error) {
                    this.emit("visual_warning", { message: error.message });
                }
            }
            return page;
        }

        async discover() {
            const pages = await this.getPages();
            const result = [];
            for (let index = 0; index < pages.length; index += 1) {
                const page = pages[index];
                const visuals = await page.getVisuals();
                const visualPayload = [];
                for (const visual of visuals) {
                    const item = { name: visual.name, title: visual.title || "", type: visual.type || "", supportedActions: ["show", "read_filters"] };
                    if (visual.type === "slicer" && typeof visual.getSlicerState === "function") {
                        try {
                            const state = await visual.getSlicerState();
                            const target = state?.filters?.[0]?.target || {};
                            item.slicer = { table: target.table || "", column: target.column || "", filterCode: "unmapped" };
                        } catch (error) {
                            item.slicer = null;
                        }
                    }
                    visualPayload.push(item);
                }
                result.push({ name: page.name, displayName: page.displayName, order: index, visuals: visualPayload });
            }
            return result;
        }

        async clearFilters() {
            if (!this.report) return;
            await this.report.removeFilters();
            const pages = await this.getPages();
            for (const page of pages) {
                try {
                    await page.updateFilters(window["powerbi-client"].models.FiltersOperations.RemoveAll);
                    const slicers = await page.getSlicers();
                    for (const slicer of slicers) {
                        try { await slicer.setSlicerState({ filters: [] }); } catch (_error) { /* unsupported slicer */ }
                    }
                } catch (_error) { /* page may not expose filter APIs */ }
            }
            this.appliedFilterFingerprint = "";
        }

        async setFitMode(mode) {
            if (!this.report) throw new Error("The report is not loaded.");
            const models = window["powerbi-client"].models;
            const options = {
                fit_to_page: models.DisplayOption.FitToPage,
                fit_to_width: models.DisplayOption.FitToWidth,
                actual_size: models.DisplayOption.ActualSize,
            };
            if (!(mode in options)) throw new Error("Unsupported report fit mode.");
            await this.report.updateSettings({
                layoutType: models.LayoutType.Custom,
                customLayout: { displayOption: options[mode] },
            });
            this.emit("fit_mode_changed", { mode });
        }

        async getActivePage() {
            const pages = await this.getPages();
            return pages.find((page) => page.isActive) || pages[0] || null;
        }

        detachHandlers() {
            if (!this.report || !this.handlers || typeof this.report.off !== "function") return;
            Object.entries(this.handlers).forEach(([name, handler]) => {
                try { this.report.off(name, handler); } catch (_error) { /* already detached */ }
            });
            this.handlers = null;
        }

        dispose(reason = "dispose") {
            this.transition("disposing", { reason });
            this.operationId += 1;
            window.clearTimeout(this.refreshTimer);
            window.clearTimeout(this.renderTimer);
            this.loadTimers.forEach((timer) => window.clearTimeout(timer));
            this.loadTimers = [];
            this.refreshTimer = null;
            this.renderTimer = null;
            this.detachHandlers();
            this.loaded = false;
            this.rendered = false;
            this.contextReady = false;
            this.embedPromise = null;
            this.configRequest = null;
            this.embedAbort?.abort();
            this.embedAbort = null;
            this.filterRevision += 1;
            this.filterQueue = Promise.resolve();
            this.appliedFilterFingerprint = "";
            this.slicerCache.clear();
            if (this.report && window.powerbi && this.container) {
                this.metrics.instanceResetCount += 1;
                window.powerbi.reset(this.container);
            } else if (this.container) {
                this.container.replaceChildren();
            }
            this.report = null;
            this.currentReportId = null;
            this.options.currentReportId = null;
            this.transition("idle", { reason });
        }

        reset() {
            this.dispose("reset");
        }

        async refreshReport() {
            if (this.report) await this.report.refresh();
        }

        markReady(details) {
            this.contextReady = true;
            if (this.rendered) {
                this.transition("ready", details || {});
                this.emit("ready", details || {});
            } else {
                this.transition("degraded", Object.assign({ reason: "POWERBI_RENDER_PENDING" }, details || {}));
            }
        }
    }

    window.Mining360PowerBIEmbed = Mining360PowerBIEmbed;
}());
