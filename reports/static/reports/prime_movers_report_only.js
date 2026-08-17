(function () {
  "use strict";

  const root = document.getElementById("prime-movers-workspace");
  if (!root) return;

  const container = document.getElementById("powerbi-report");
  const loading = document.getElementById("prime-report-status");
  const reportError = document.getElementById("prime-report-error");
  const reportErrorMessage = document.getElementById("prime-report-error-message");
  const status = document.getElementById("prime-context-status");
  const refreshButton = document.getElementById("prime-refresh-report");
  let report = null;
  let reportRendered = false;
  let operationalPageActivated = false;
  let reportLoadTimer = null;

  function csrfToken() {
    const item = document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith("csrftoken="));
    if (item) return decodeURIComponent(item.split("=").slice(1).join("="));
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function logEvent(event, detail) {
    fetch(root.dataset.eventUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(Object.assign({ event: event }, detail || {}))
    }).catch(function () {});
  }

  function showError(message, code) {
    window.clearTimeout(reportLoadTimer);
    loading.hidden = true;
    reportError.hidden = false;
    reportErrorMessage.textContent = message;
    logEvent("powerbi_error", { error_code: code || "POWERBI_EMBED_FAILED", error_message: message });
  }

  async function hideUnsupportedPowerAppsVisual() {
    const visualName = root.dataset.hiddenVisual;
    const targetPageName = root.dataset.targetPage;
    if (!report || !visualName || !targetPageName) return;

    const pages = await report.getPages();
    const targetPage = pages.find(page => page.name === targetPageName);
    if (!targetPage) throw new Error("The configured Prime Movers report page was not found.");
    const visuals = await targetPage.getVisuals();
    const visual = visuals.find(item => item.name === visualName);
    if (!visual) throw new Error("The configured Power Apps visual was not found on the Prime Movers page.");
    const models = window["powerbi-client"].models;
    if (visual.setVisualDisplayState && models.VisualContainerDisplayMode) {
      await visual.setVisualDisplayState(models.VisualContainerDisplayMode.Hidden);
    }
    await targetPage.setActive();
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
        settings: Object.assign({
          panes: { filters: { visible: false }, pageNavigation: { visible: true } }
        }, payload.config.settings || {})
      });
      if (root.dataset.safeInitialPage) config.pageName = root.dataset.safeInitialPage;

      loading.textContent = "Loading Power BI report...";
      report = window.powerbi.embed(container, config);
      reportLoadTimer = window.setTimeout(function () {
        if (!reportRendered) showError("Power BI did not finish loading within four minutes.", "POWERBI_LOAD_TIMEOUT");
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
            await hideUnsupportedPowerAppsVisual();
            return;
          } catch (error) {
            showError(error.message || "Power BI could not prepare the operational page.", "POWERAPPS_VISUAL_HIDE_FAILED");
            return;
          }
        }
        reportRendered = true;
        window.clearTimeout(reportLoadTimer);
        loading.hidden = true;
        reportError.hidden = true;
        logEvent("powerbi_rendered");
      });
      report.on("error", function (event) {
        const detail = event && event.detail || {};
        showError(detail.message || "Power BI rendering failed.", detail.errorCode);
      });
    } catch (error) {
      showError(error.message || "Power BI could not be loaded.");
    }
  }

  refreshButton.addEventListener("click", async function () {
    if (!report) return;
    refreshButton.disabled = true;
    status.textContent = "Refreshing Power BI report...";
    try {
      await report.refresh();
      status.textContent = "Power BI report refreshed.";
      logEvent("report_refreshed");
    } catch (error) {
      status.textContent = "The report could not be refreshed.";
      logEvent("powerbi_error", { error_code: "POWERBI_REFRESH_FAILED", error_message: error.message || "" });
    } finally {
      refreshButton.disabled = false;
    }
  });

  loadReport();
})();
