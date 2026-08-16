(function () {
  "use strict";
  const root = document.getElementById("prime-movers-workspace");
  if (!root) return;

  const container = document.getElementById("powerbi-report");
  const loading = document.getElementById("prime-report-status");
  const reportError = document.getElementById("prime-report-error");
  const reportErrorMessage = document.getElementById("prime-report-error-message");
  const status = document.getElementById("prime-context-status");
  const drawer = document.getElementById("prime-powerapps-drawer");
  const backdrop = document.getElementById("prime-drawer-backdrop");
  const frame = document.getElementById("prime-powerapps-frame");
  const appState = document.getElementById("prime-powerapps-state");
  const newTabButton = document.getElementById("prime-open-new-tab");
  const serialInput = document.getElementById("prime-serial");
  const siteInput = document.getElementById("prime-site");
  const modelInput = document.getElementById("prime-model");
  let report = null;
  let launchUrl = "";
  let reportRendered = false;
  let operationalPageActivated = false;
  let reportLoadTimer = null;
  let powerAppsContextId = "";
  let powerAppsReady = false;
  let powerAppsPreloadPromise = null;
  let selectionRequestVersion = 0;
  const secureCryptoAvailable = Boolean(window.isSecureContext && window.crypto && window.crypto.subtle);

  const initial = new URLSearchParams(window.location.search);
  serialInput.value = initial.get("serial_number") || "";
  siteInput.value = initial.get("minesite") || "";
  modelInput.value = initial.get("model") || "";

  function csrfToken() {
    const item = document.cookie.split(";").map(v => v.trim()).find(v => v.startsWith("csrftoken="));
    if (item) return decodeURIComponent(item.split("=").slice(1).join("="));
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  async function post(url, payload) {
    const response = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(payload || {})
    });
    const body = await response.json();
    if (!response.ok || !body.ok) {
      const error = new Error(body.error || "The operation could not be completed.");
      error.code = body.error_code || "UNKNOWN_ERROR";
      throw error;
    }
    return body;
  }

  function logEvent(event, detail) {
    post(root.dataset.eventUrl, Object.assign({ event: event }, detail || {})).catch(function () {});
  }

  function selectedContext() {
    return {
      serial_number: serialInput.value.trim(),
      minesite: siteInput.value.trim(),
      model: modelInput.value.trim(),
      page_name: "",
      filters: []
    };
  }

  function selectedTableRow(event) {
    const detail = event && event.detail || {};
    if (!detail.visual || detail.visual.type !== "tableEx") return null;
    const point = detail.dataPoints && detail.dataPoints[0];
    if (!point) return null;
    const fields = {};
    (point.identity || []).forEach(function (item) {
      const target = item.target || {};
      const key = String(target.column || target.measure || "").trim();
      if (key) fields[key] = item.equals ?? item.value ?? "";
    });
    const value = function () {
      for (let index = 0; index < arguments.length; index += 1) {
        const candidate = fields[arguments[index]];
        if (candidate !== undefined && candidate !== null && String(candidate).trim()) return String(candidate).trim();
      }
      return "";
    };
    const context = {
      equipment_id: value("Equipment", "Equipment ID"),
      serial_number: value("SN", "Serial Number", "SerialNumber"),
      minesite: value("Site", "MineSite", "Mine Site"),
      model: value("Model"),
      selected_status: value("Connectivity Status Real", "Status"),
      page_name: detail.page && detail.page.name || root.dataset.targetPage || "",
      filters: []
    };
    return context.serial_number && context.minesite && context.model ? context : null;
  }

  function openDrawer() {
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    backdrop.hidden = false;
    document.getElementById("prime-close-drawer").focus();
  }

  function closeDrawer() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    backdrop.hidden = true;
    document.getElementById("prime-open-form").focus();
  }

  function preloadPowerApps() {
    if (powerAppsPreloadPromise) return powerAppsPreloadPromise;
    appState.hidden = false;
    appState.textContent = "Loading Power Apps. Select a machine in the report when it is ready.";
    powerAppsPreloadPromise = post(root.dataset.launchContextUrl, { preload: true }).then(function (payload) {
      powerAppsContextId = payload.context_id;
      launchUrl = payload.launch_url;
      if (root.dataset.iframeEnabled === "true" && secureCryptoAvailable) {
        frame.src = launchUrl;
        frame.hidden = false;
      } else if (!secureCryptoAvailable) {
        appState.textContent = "Embedded Microsoft sign-in requires HTTPS. Use the secure new-tab action.";
      } else {
        appState.textContent = "Power Apps is ready to open with your corporate Microsoft identity.";
      }
      newTabButton.hidden = root.dataset.newTabEnabled !== "true";
      logEvent("powerapps_opened", { preload: true });
      return payload;
    }).catch(function (error) {
      powerAppsPreloadPromise = null;
      appState.textContent = error.message;
      logEvent("powerapps_error", { error_code: error.code, error_message: error.message });
      throw error;
    });
    return powerAppsPreloadPromise;
  }

  async function prepareOperationalPage() {
    const visualName = root.dataset.hiddenVisual;
    const targetPageName = root.dataset.targetPage;
    if (!report || !visualName || !targetPageName) return false;
    try {
      const pages = await report.getPages();
      const targetPage = pages.find(page => page.name === targetPageName);
      if (!targetPage) throw new Error("The configured Prime Movers report page was not found.");
      const visuals = await targetPage.getVisuals();
      const visual = visuals.find(item => item.name === visualName);
      if (!visual) throw new Error("The configured Power Apps visual was not found on the Prime Movers page.");
      if (visual.setVisualDisplayState && window["powerbi-client"].models.VisualContainerDisplayMode) {
        await visual.setVisualDisplayState(window["powerbi-client"].models.VisualContainerDisplayMode.Hidden);
      }
      await targetPage.setActive();
      return true;
    } catch (error) {
      logEvent("powerbi_error", { error_code: "POWERAPPS_VISUAL_HIDE_FAILED", error_message: error.message });
      throw error;
    }
  }

  async function loadReport() {
    try {
      if (!window.powerbi || !window["powerbi-client"]) throw new Error("Power BI client is unavailable.");
      loading.textContent = "Connecting to Power BI...";
      const response = await fetch(root.dataset.embedConfigUrl, { credentials: "same-origin" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Power BI embed configuration is unavailable.");
      const models = window["powerbi-client"].models;
      const config = Object.assign({}, payload.config, {
        tokenType: models.TokenType.Embed,
        permissions: models.Permissions.Read,
        settings: Object.assign({ panes: { filters: { visible: false }, pageNavigation: { visible: true } } }, payload.config.settings || {})
      });
      if (root.dataset.safeInitialPage) config.pageName = root.dataset.safeInitialPage;
      loading.textContent = "Loading Power BI report...";
      report = powerbi.embed(container, config);
      reportLoadTimer = window.setTimeout(function () {
        if (reportRendered) return;
        loading.hidden = true;
        reportError.hidden = false;
        reportErrorMessage.textContent = "Power BI did not finish loading within four minutes. Reload the report or contact the Reporting administrator.";
        logEvent("powerbi_error", { error_code: "POWERBI_LOAD_TIMEOUT", error_message: "Report was not rendered within 240 seconds." });
      }, 240000);
      report.on("loaded", function () {
        loading.textContent = "Preparing the report visuals...";
        logEvent("powerbi_loaded");
      });
      report.on("rendered", async function () {
        if (root.dataset.safeInitialPage && root.dataset.targetPage && !operationalPageActivated) {
          operationalPageActivated = true;
          loading.textContent = "Opening Prime Movers Operational Status...";
          try {
            await prepareOperationalPage();
            return;
          } catch (error) {
            window.clearTimeout(reportLoadTimer);
            loading.hidden = true;
            reportError.hidden = false;
            reportErrorMessage.textContent = error.message || "Power BI could not prepare the operational page.";
            return;
          }
        }
        reportRendered = true;
        window.clearTimeout(reportLoadTimer);
        loading.hidden = true;
        reportError.hidden = true;
        reportErrorMessage.textContent = "";
        logEvent("powerbi_rendered");
        preloadPowerApps().catch(function () {});
      });
      report.on("dataSelected", function (event) {
        const context = selectedTableRow(event);
        if (!context) return;
        serialInput.value = context.serial_number;
        siteInput.value = context.minesite;
        modelInput.value = context.model;
        status.textContent = `Opening operational status for ${context.serial_number}...`;
        logEvent("machine_selected", context);
        openPowerApps(context);
      });
      report.on("error", function (event) {
        window.clearTimeout(reportLoadTimer);
        const detail = event && event.detail || {};
        loading.hidden = true;
        reportError.hidden = false;
        reportErrorMessage.textContent = detail.message || "Power BI rendering failed.";
        logEvent("powerbi_error", { error_code: detail.errorCode || "POWERBI_EMBED_FAILED", error_message: detail.message || "" });
      });
    } catch (error) {
      loading.hidden = true;
      reportError.hidden = false;
      reportErrorMessage.textContent = error.message;
    }
  }

  async function openPowerApps(contextOverride) {
    const context = Object.assign({}, selectedContext(), contextOverride || {});
    if (!context.serial_number) {
      status.textContent = "Select one machine before opening the operational status form.";
      serialInput.focus();
      return;
    }
    openDrawer();
    appState.hidden = false;
    appState.textContent = `Updating the operational status form for ${context.serial_number}...`;
    const requestVersion = ++selectionRequestVersion;
    try {
      await preloadPowerApps();
      const payload = await post(root.dataset.launchContextUrl, Object.assign({}, context, { context_id: powerAppsContextId }));
      if (requestVersion !== selectionRequestVersion) return;
      if (payload.context_transfer && payload.context_transfer.status !== "transferred") {
        const error = new Error(payload.context_transfer.message || "The selected machine could not be transmitted to Power Apps.");
        error.code = payload.context_transfer.error_code || "DATAVERSE_CONTEXT_SYNC_FAILED";
        throw error;
      }
      if (powerAppsReady) appState.hidden = true;
      else appState.textContent = "Power Apps is still loading. The selected machine context is ready.";
      logEvent("powerapps_opened", context);
    } catch (error) {
      appState.textContent = error.message;
      if (error.code === "ENTRA_SESSION_MISSING") {
        const link = document.createElement("a");
        link.className = "button";
        link.href = root.dataset.connectUrl;
        link.textContent = "Connect corporate account";
        appState.append(document.createElement("br"), link);
      }
      logEvent("powerapps_error", { error_code: error.code, error_message: error.message });
    }
  }

  document.getElementById("prime-open-form").addEventListener("click", function () { openPowerApps(); });
  frame.addEventListener("load", function () {
    if (!frame.src || frame.hidden) return;
    powerAppsReady = true;
    appState.hidden = true;
    logEvent("powerapps_loaded", { context_id: powerAppsContextId });
  });
  document.getElementById("prime-close-drawer").addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);
  document.getElementById("prime-open-new-tab").addEventListener("click", function () {
    if (launchUrl) {
      window.open(launchUrl, "_blank", "noopener,noreferrer");
      logEvent("powerapps_new_tab", selectedContext());
    }
  });
  document.getElementById("prime-refresh-report").addEventListener("click", async function () {
    if (report) { await report.refresh(); status.textContent = "Power BI report refreshed."; logEvent("report_refreshed"); }
  });
  document.getElementById("prime-form-done").addEventListener("click", async function () {
    if (report) await report.refresh();
    closeDrawer();
    status.textContent = "Report refreshed after the operational status update.";
  });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape" && drawer.classList.contains("open")) closeDrawer(); });
  if (!secureCryptoAvailable && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    status.textContent = "Power Apps embedded authentication requires HTTPS. Secure new-tab mode will be used until HTTPS is configured.";
    logEvent("powerapps_error", {
      error_code: "SECURE_CONTEXT_REQUIRED",
      error_message: "Web Crypto is unavailable because Mining 360 is not running in a secure browser context."
    });
  }
  loadReport();
})();
