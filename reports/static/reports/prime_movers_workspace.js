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
  let reportLoadTimer = null;

  const initial = new URLSearchParams(window.location.search);
  serialInput.value = initial.get("serial_number") || "";
  siteInput.value = initial.get("minesite") || "";
  modelInput.value = initial.get("model") || "";

  function csrfToken() {
    const item = document.cookie.split(";").map(v => v.trim()).find(v => v.startsWith("csrftoken="));
    return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
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

  async function hideUnsupportedPowerAppsVisual() {
    const visualName = root.dataset.hiddenVisual;
    if (!report || !visualName) return;
    try {
      const pages = await report.getPages();
      for (const page of pages) {
        const visuals = await page.getVisuals();
        const visual = visuals.find(item => item.name === visualName);
        if (visual && visual.setVisualDisplayState && window["powerbi-client"].models.VisualContainerDisplayMode) {
          await visual.setVisualDisplayState(window["powerbi-client"].models.VisualContainerDisplayMode.Hidden);
        }
      }
    } catch (error) {
      logEvent("powerbi_error", { error_code: "POWERAPPS_VISUAL_HIDE_FAILED", error_message: error.message });
    }
  }

  async function loadReport() {
    try {
      if (!window.powerbi || !window["powerbi-client"]) throw new Error("Power BI client is unavailable.");
      const response = await fetch(root.dataset.embedConfigUrl, { credentials: "same-origin" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Power BI embed configuration is unavailable.");
      const models = window["powerbi-client"].models;
      const config = Object.assign({}, payload.config, {
        tokenType: models.TokenType.Embed,
        permissions: models.Permissions.Read,
        settings: Object.assign({ panes: { filters: { visible: false }, pageNavigation: { visible: true } } }, payload.config.settings || {})
      });
      report = powerbi.embed(container, config);
      reportLoadTimer = window.setTimeout(function () {
        if (reportRendered) return;
        loading.hidden = true;
        reportError.hidden = false;
        reportErrorMessage.textContent = "Power BI is taking too long to respond. Retry the page or contact the Reporting administrator.";
        logEvent("powerbi_error", { error_code: "POWERBI_LOAD_TIMEOUT", error_message: "Report was not rendered within 45 seconds." });
      }, 45000);
      report.on("loaded", async function () {
        await hideUnsupportedPowerAppsVisual();
        logEvent("powerbi_loaded");
      });
      report.on("rendered", async function () {
        reportRendered = true;
        window.clearTimeout(reportLoadTimer);
        loading.hidden = true;
        await hideUnsupportedPowerAppsVisual();
        logEvent("powerbi_rendered");
      });
      report.on("dataSelected", function (event) {
        const points = event && event.detail && event.detail.dataPoints || [];
        const values = points.flatMap(point => (point.identity || []).map(item => item.equals || item.value).filter(Boolean));
        if (values.length === 1 && !serialInput.value) serialInput.value = String(values[0]);
        status.textContent = values.length ? "Report selection captured. Confirm the machine before opening the form." : "";
      });
      report.on("error", function (event) {
        window.clearTimeout(reportLoadTimer);
        const detail = event && event.detail || {};
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

  async function openPowerApps() {
    const context = selectedContext();
    if (!context.serial_number) {
      status.textContent = "Select one machine before opening the operational status form.";
      serialInput.focus();
      return;
    }
    openDrawer();
    appState.hidden = false;
    appState.textContent = "Connecting corporate identity and preparing the selected machine...";
    frame.hidden = true;
    newTabButton.hidden = true;
    try {
      const payload = await post(root.dataset.launchContextUrl, context);
      launchUrl = payload.launch_url;
      if (root.dataset.iframeEnabled === "true") {
        frame.src = launchUrl;
        frame.hidden = false;
        appState.textContent = "Loading Power Apps... If Microsoft sign-in is blocked, use the secure new-tab action.";
      } else {
        appState.textContent = "Power Apps will open securely with your corporate Microsoft identity.";
      }
      newTabButton.hidden = root.dataset.newTabEnabled !== "true";
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

  document.getElementById("prime-open-form").addEventListener("click", openPowerApps);
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
  loadReport();
})();
