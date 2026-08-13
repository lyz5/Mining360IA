(function () {
    class Mining360PowerBIEmbed {
        constructor(container, options) {
            this.container = container;
            this.options = options || {};
            this.report = null;
            this.loaded = false;
            this.events = [];
            this.refreshTimer = null;
        }

        emit(type, details) {
            const event = { type, details: details || {}, at: new Date().toISOString() };
            this.events.push(event);
            if (this.events.length > 100) this.events.shift();
            if (typeof this.options.onEvent === "function") this.options.onEvent(event);
        }

        async requestConfig(reportId) {
            const url = this.options.embedConfigUrl.replace("__REPORT_ID__", encodeURIComponent(reportId));
            const response = await fetch(url, { credentials: "same-origin" });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                const error = new Error(payload.error || "Embed configuration unavailable.");
                error.code = payload.error_code || "embed_configuration_failed";
                error.authenticationRequired = Boolean(payload.authentication_required);
                error.connectUrl = payload.connect_url || "";
                error.authenticationMode = payload.authentication_mode || "";
                throw error;
            }
            return payload.config;
        }

        async embed(reportId) {
            if (!window.powerbi || !window["powerbi-client"]) throw new Error("Power BI JavaScript API is unavailable.");
            const models = window["powerbi-client"].models;
            const config = await this.requestConfig(reportId);
            const isAad = String(config.tokenType || "").toLowerCase() === "aad";
            config.tokenType = isAad ? models.TokenType.Aad : models.TokenType.Embed;
            config.permissions = models.Permissions.Read;
            config.settings = Object.assign({ panes: { filters: { visible: false }, pageNavigation: { visible: false } } }, config.settings || {});
            if (isAad) {
                config.eventHooks = Object.assign({}, config.eventHooks || {}, {
                    accessTokenProvider: async () => {
                        try {
                            const refreshed = await this.requestConfig(reportId);
                            return refreshed.accessToken || null;
                        } catch (error) {
                            this.emit("token_refresh_failed", { message: error.message, code: error.code || "" });
                            return null;
                        }
                    },
                });
            }
            window.powerbi.reset(this.container);
            this.report = window.powerbi.embed(this.container, config);
            await new Promise((resolve, reject) => {
                const timeout = window.setTimeout(() => reject(new Error("Power BI report loading timed out.")), 120000);
                this.report.on("loaded", () => {
                    window.clearTimeout(timeout);
                    this.loaded = true;
                    this.emit("loaded", { reportId });
                    resolve();
                });
                this.report.on("rendered", () => this.emit("rendered", { reportId }));
                this.report.on("error", (event) => {
                    const details = event?.detail || {};
                    this.emit("error", details);
                    reject(new Error(details.message || "Power BI reported an error."));
                });
            });
            this.scheduleTokenRefresh(reportId, config.expiresAt);
            return this.report;
        }

        scheduleTokenRefresh(reportId, expiresAt) {
            window.clearTimeout(this.refreshTimer);
            const delay = expiresAt
                ? Math.max(30000, (Number(expiresAt) * 1000) - Date.now() - (5 * 60 * 1000))
                : 45 * 60 * 1000;
            this.refreshTimer = window.setTimeout(async () => {
                try {
                    const config = await this.requestConfig(reportId);
                    await this.report.setAccessToken(config.accessToken);
                    this.emit("token_refreshed", { reportId });
                    this.scheduleTokenRefresh(reportId, config.expiresAt);
                } catch (error) {
                    this.emit("token_refresh_failed", {
                        message: error.message,
                        code: error.code || "",
                        authenticationRequired: Boolean(error.authenticationRequired),
                        connectUrl: error.connectUrl || "",
                    });
                }
            }, delay);
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

        async applyFilters(page, instructions) {
            const models = window["powerbi-client"].models;
            const pageFilters = [];
            const slicers = page ? await page.getSlicers() : [];
            const slicerDescriptions = await Promise.all(
                slicers.map((slicer) => this.describeSlicer(slicer))
            );
            for (const instruction of instructions || []) {
                let applied = false;
                const matched = await this.resolveSlicer(instruction, slicerDescriptions);
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
                    await page.updateFilters(models.FiltersOperations.RemoveAll);
                } catch (error) {
                    this.emit("page_filters_clear_warning", { message: error.message });
                }
                let appliedCount = 0;
                for (const item of pageFilters) {
                    try {
                        await page.updateFilters(models.FiltersOperations.Add, [item.filter]);
                        appliedCount += 1;
                        this.emit("page_filter_applied", {
                            filterCode: item.instruction.filter_code,
                            table: item.instruction.table,
                            column: item.instruction.column,
                        });
                    } catch (error) {
                        this.emit("page_filter_failed", {
                            filterCode: item.instruction.filter_code,
                            table: item.instruction.table,
                            column: item.instruction.column,
                            message: error.message,
                        });
                    }
                }
                this.emit("page_filters_applied", {
                    count: appliedCount,
                    requested: pageFilters.length,
                });
            }
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
            if (this.report) await this.report.removeFilters();
        }

        reset() {
            window.clearTimeout(this.refreshTimer);
            this.refreshTimer = null;
            this.loaded = false;
            this.report = null;
            this.options.currentReportId = null;
            if (window.powerbi && this.container) {
                window.powerbi.reset(this.container);
            } else if (this.container) {
                this.container.replaceChildren();
            }
        }

        async refreshReport() {
            if (this.report) await this.report.refresh();
        }
    }

    window.Mining360PowerBIEmbed = Mining360PowerBIEmbed;
}());
