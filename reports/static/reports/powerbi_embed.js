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
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Embed configuration unavailable.");
            return payload.config;
        }

        async embed(reportId) {
            if (!window.powerbi || !window["powerbi-client"]) throw new Error("Power BI JavaScript API is unavailable.");
            const models = window["powerbi-client"].models;
            const config = await this.requestConfig(reportId);
            config.tokenType = models.TokenType.Embed;
            config.permissions = models.Permissions.Read;
            config.settings = Object.assign({ panes: { filters: { visible: false }, pageNavigation: { visible: false } } }, config.settings || {});
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
            this.scheduleTokenRefresh(reportId);
            return this.report;
        }

        scheduleTokenRefresh(reportId) {
            window.clearTimeout(this.refreshTimer);
            this.refreshTimer = window.setTimeout(async () => {
                try {
                    const config = await this.requestConfig(reportId);
                    await this.report.setAccessToken(config.accessToken);
                    this.emit("token_refreshed", { reportId });
                    this.scheduleTokenRefresh(reportId);
                } catch (error) {
                    this.emit("token_refresh_failed", { message: error.message });
                }
            }, 45 * 60 * 1000);
        }

        async getPages() {
            if (!this.report || !this.loaded) throw new Error("The report is not loaded.");
            return this.report.getPages();
        }

        async setActivePage(pageInternalName) {
            if (!pageInternalName) return null;
            const pages = await this.getPages();
            const page = pages.find((item) => item.name === pageInternalName);
            if (!page) throw new Error(`Power BI page '${pageInternalName}' was not found.`);
            await page.setActive();
            this.emit("page_activated", { name: page.name, displayName: page.displayName });
            return page;
        }

        basicFilter(instruction) {
            return {
                $schema: "http://powerbi.com/product/schema#basic",
                target: { table: instruction.table, column: instruction.column },
                operator: instruction.operator || "In",
                values: instruction.values || [],
                filterType: window["powerbi-client"].models.FilterType.BasicFilter,
            };
        }

        async applyFilters(page, instructions) {
            const models = window["powerbi-client"].models;
            const pageFilters = [];
            const slicers = page ? await page.getSlicers() : [];
            for (const instruction of instructions || []) {
                const filter = this.basicFilter(instruction);
                let applied = false;
                if (instruction.scope === "slicer" && instruction.slicer_internal_name) {
                    const slicer = slicers.find((item) => item.name === instruction.slicer_internal_name);
                    if (slicer && typeof slicer.setSlicerState === "function") {
                        try {
                            await slicer.setSlicerState({ filters: [filter] });
                            applied = true;
                            this.emit("slicer_applied", { filterCode: instruction.filter_code, visual: slicer.name });
                        } catch (error) {
                            this.emit("slicer_failed", { filterCode: instruction.filter_code, message: error.message });
                        }
                    }
                }
                if (!applied) pageFilters.push(filter);
            }
            if (pageFilters.length && page) {
                await page.updateFilters(models.FiltersOperations.Replace, pageFilters);
                this.emit("page_filters_applied", { count: pageFilters.length });
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
            if (instructions.page_internal_name) page = await this.setActivePage(instructions.page_internal_name);
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

        async refreshReport() {
            if (this.report) await this.report.refresh();
        }
    }

    window.Mining360PowerBIEmbed = Mining360PowerBIEmbed;
}());
