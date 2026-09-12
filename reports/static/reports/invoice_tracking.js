(() => {
  const root = document.querySelector("[data-invoice-tracking]");
  if (!root) return;
  const get = selector => root.querySelector(selector);
  const csrf = get("input[name=csrfmiddlewaretoken]")?.value || "";
  const state = { page: 1, pages: 1, timer: null, poll: null };
  const fmt = (value, digits = 0) => value == null || value === "" ? "Not available" : new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(Number(value));
  const money = value => value == null || value === "" ? "Not available" : new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(Number(value));
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

  function params() {
    return new URLSearchParams({
      page: state.page, page_size: 150,
      view: get("[data-it-view]").value,
      search: get("[data-it-search]").value.trim(),
      status: get("[data-it-status]").value,
      company: get("[data-it-company]").value,
      date_from: get("[data-it-date-from]").value,
      date_to: get("[data-it-date-to]").value,
      header_customer: get("[data-it-header-customer]").value.trim(),
      header_order_type: get("[data-it-header-order-type]").value,
      header_order_status: get("[data-it-header-order-status]").value,
      header_invoicing_status: get("[data-it-header-invoicing-status]").value,
      header_transport: get("[data-it-header-transport]").value,
      header_urgency: get("[data-it-header-urgency]").value,
      sort: get("[data-it-sort]").value,
    });
  }

  function updateSelect(element, values, label) {
    const selected = element.value;
    element.innerHTML = '<option value="">' + label + "</option>" + values.map(value => '<option value="' + esc(value) + '">' + esc(value) + "</option>").join("");
    if (values.includes(selected)) element.value = selected;
  }

  function schedulePoll(id) {
    clearTimeout(state.poll);
    state.poll = setTimeout(async () => {
      try {
        const response = await fetch(root.dataset.syncUrl + id + "/", { headers: { Accept: "application/json" } });
        const payload = await response.json();
        renderSync(payload.sync);
        if (!["Queued", "Running"].includes(payload.sync.status)) {
          await loadOverview();
          await loadRows();
        }
      } catch (_) {
        schedulePoll(id);
      }
    }, 1500);
  }

  function renderSync(sync) {
    const panel = get("[data-it-sync-panel]");
    if (!sync) { panel.hidden = true; return; }
    panel.hidden = false;
    get("[data-it-sync-status]").textContent = sync.status;
    get("[data-it-sync-label]").textContent = sync.stage_label || "";
    get("[data-it-progress]").value = sync.progress_percent || 0;
    get("[data-it-progress-label]").textContent = (sync.progress_percent || 0) + "%";
    const source = sync.source_status || {};
    get("[data-it-source-progress]").innerHTML = Object.entries(source)
      .filter(([, value]) => value && typeof value === "object")
      .map(([key, value]) => "<span>" + esc(key.replaceAll("_", " ")) + ": " + fmt(value.rows) + " rows</span>").join("");
    const errors = sync.errors || [];
    const error = get("[data-it-sync-error]");
    error.hidden = !errors.length;
    error.textContent = errors.map(item => item.message || item.code).join(" ");
    const running = ["Queued", "Running"].includes(sync.status);
    const button = get("[data-it-sync]");
    if (button) { button.disabled = running; button.textContent = running ? "Synchronizing..." : "Synchronize & Reconcile"; }
    if (running) schedulePoll(sync.id);
  }

  function renderOverview(payload) {
    renderSync(payload.sync);
    const rec = payload.reconciliation;
    if (!rec) return;
    get("[data-it-rule]").textContent = rec.rule_version;
    get("[data-it-updated]").textContent = rec.completed_at ? "Completed " + new Date(rec.completed_at).toLocaleString() : rec.status;
    const summary = rec.summary || {};
    const counts = summary.status_counts || {};
    const exceptions = Object.entries(counts).filter(([key]) => !["MATCHED", "PARTIALLY_INVOICED"].includes(key)).reduce((total, [, value]) => total + value, 0);
    const values = {
      processed: summary.link_rows_processed, matched: counts.MATCHED || 0,
      partial: counts.PARTIALLY_INVOICED || 0, exceptions,
      invoices: summary.distinct_invoice_headers_matched,
      accounting: summary.distinct_accounting_entries_matched,
    };
    Object.entries(values).forEach(([key, value]) => {
      const node = get('[data-it-kpi="' + key + '"]');
      if (node) node.textContent = fmt(value);
    });
  }

  async function loadOverview() {
    const response = await fetch(root.dataset.overviewUrl, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Invoice Tracking overview is unavailable.");
    renderOverview(await response.json());
  }

  async function synchronize() {
    const button = get("[data-it-sync]");
    if (button) button.disabled = true;
    const response = await fetch(root.dataset.syncUrl, { method: "POST", headers: { "X-CSRFToken": csrf, Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Synchronization could not be started.");
    renderSync(payload.sync);
  }

  function renderRows(payload) {
    state.pages = payload.pages || 1;
    state.page = payload.page || 1;
    updateSelect(get("[data-it-status]"), payload.filters.statuses || [], "All statuses");
    updateSelect(get("[data-it-company]"), (payload.filters.companies || []).filter(Boolean), "All companies");
    const headerOptions = payload.filters.order_headers || {};
    updateSelect(get("[data-it-header-order-type]"), headerOptions.order_type || [], "All types");
    updateSelect(get("[data-it-header-order-status]"), headerOptions.order_status || [], "All order statuses");
    updateSelect(get("[data-it-header-invoicing-status]"), headerOptions.invoicing_status || [], "All invoicing statuses");
    updateSelect(get("[data-it-header-transport]"), headerOptions.transport || [], "All transport modes");
    updateSelect(get("[data-it-header-urgency]"), headerOptions.urgency || [], "All urgency levels");
    const body = get("[data-it-rows]");
    const orderView = payload.view === "orders";
    get("[data-it-header-filters]").hidden = !orderView;
    get("[data-it-head]").innerHTML = orderView
      ? "<th>Billing status</th><th>Order status</th><th>Company</th><th>Customer Name</th><th>Customer No.</th><th>Order / Line</th><th>Order date</th><th>ETA</th><th>Type / Transport</th><th>Part</th><th class=\"num\">Ordered</th><th class=\"num\">Delivered</th><th class=\"num\">Invoiced</th><th>CA Combine</th><th>Invoice</th><th class=\"num\">CA Amount</th><th>Control</th>"
      : "<th>Status</th><th>Company</th><th>Customer</th><th>Order / Line</th><th>Part</th><th>Delivery</th><th>Invoice</th><th>Invoice Date</th><th class=\"num\">Ordered</th><th class=\"num\">Delivered</th><th class=\"num\">Invoiced</th><th class=\"num\">Line Amount</th><th class=\"num\">CA Amount</th><th>Controls</th>";
    if (!payload.results.length) {
      body.innerHTML = '<tr><td colspan="' + (orderView ? "17" : "14") + '" class="it-empty">No line matches the current filters.</td></tr>';
    } else {
      body.innerHTML = payload.results.map(row => {
        if (orderView) {
          const typeTransport = [row.order_type, row.transport].filter(Boolean).join(" · ") || "Not available";
          return "<tr><td><span class=\"it-status " + esc(row.billing_status) + "\">" + esc(row.billing_status.replaceAll("_", " ")) + "</span></td>" +
            "<td>" + esc(row.operational_status || row.header_order_status || "Not available") + "</td>" +
            "<td>" + esc(row.company) + "-" + esc(row.branch) + "</td><td><strong>" + esc(row.customer_name || "Not recorded in Mine Logistics") + "</strong></td><td>" + esc(row.customer_number || "Not recorded") + "</td>" +
            "<td><strong>" + esc(row.order_number) + "</strong><br><small>Line " + esc(row.order_line) + "</small></td>" +
            "<td>" + esc(row.order_date || "Not available") + "</td><td>" + esc(row.eta || "Not available") + "</td>" +
            "<td>" + esc(typeTransport) + "</td><td>" + esc(row.part_number) + "</td>" +
            '<td class="num">' + fmt(row.ordered_quantity, 2) + '</td><td class="num">' + fmt(row.delivered_quantity, 2) + "</td>" +
            '<td class="num">' + fmt(row.invoiced_quantity, 2) + '</td><td><span class="it-ca ' + (row.ca_combine_present ? "present" : "missing") + '">' + (row.ca_combine_present ? "Yes" : "No") + "</span></td>" +
            "<td>" + esc(row.invoice_number || "Not available") + "<br><small>" + esc(row.invoice_date || "") + "</small></td>" +
            '<td class="num">' + money(row.accounting_amount) + "</td><td>" + esc(row.control_reason) + "</td></tr>";
        }
        const controls = [...(row.warnings || []), row.cancellation_invoice ? "Cancelled by " + row.cancellation_invoice : ""].filter(Boolean).join(", ") || "Passed";
        return "<tr><td><span class=\"it-status " + esc(row.status) + "\">" + esc(row.status.replaceAll("_", " ")) + "</span></td>" +
          "<td>" + esc(row.company) + "</td><td>" + esc(row.customer) + "</td>" +
          "<td><strong>" + esc(row.order_number) + "</strong><br><small>Line " + esc(row.order_line) + "</small></td>" +
          "<td>" + esc(row.part_number) + "</td><td>" + esc(row.delivery_number) + "</td>" +
          "<td><strong>" + esc(row.invoice_number) + "</strong></td><td>" + esc(row.invoice_date || "Not available") + "</td>" +
          '<td class="num">' + fmt(row.ordered_quantity, 2) + '</td><td class="num">' + fmt(row.delivered_quantity, 2) + "</td>" +
          '<td class="num">' + fmt(row.invoiced_quantity, 2) + '</td><td class="num">' + money(row.line_amount) + "</td>" +
          '<td class="num">' + money(row.accounting_amount) + "<br><small>" + fmt(row.accounting_entry_count) + " entries</small></td>" +
          '<td title="' + esc(controls) + '">' + esc(controls) + "</td></tr>";
      }).join("");
    }
    get("[data-it-count]").textContent = fmt(payload.count) + " records";
    get("[data-it-page]").textContent = "Page " + state.page + " of " + state.pages;
    get("[data-it-prev]").disabled = state.page <= 1;
    get("[data-it-next]").disabled = state.page >= state.pages;
    get("[data-it-export]").href = root.dataset.exportUrl + "?" + params();
  }

  async function loadRows() {
    const response = await fetch(root.dataset.rowsUrl + "?" + params(), { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Reconciled lines are unavailable.");
    renderRows(await response.json());
  }

  get("[data-it-sync]")?.addEventListener("click", () => synchronize().catch(showError));
  function showError(error) {
    get("[data-it-sync-panel]").hidden = false;
    const node = get("[data-it-sync-error]"); node.hidden = false; node.textContent = error.message;
  }
  ["[data-it-view]", "[data-it-status]", "[data-it-company]", "[data-it-date-from]", "[data-it-date-to]", "[data-it-sort]"].forEach(selector => get(selector).addEventListener("change", () => { state.page = 1; loadRows().catch(showError); }));
  ["[data-it-header-order-type]", "[data-it-header-order-status]", "[data-it-header-invoicing-status]", "[data-it-header-transport]", "[data-it-header-urgency]"].forEach(selector => get(selector).addEventListener("change", () => { state.page = 1; loadRows().catch(showError); }));
  get("[data-it-header-customer]").addEventListener("input", () => { clearTimeout(state.timer); state.timer = setTimeout(() => { state.page = 1; loadRows().catch(showError); }, 250); });
  get("[data-it-clear-header-filters]").addEventListener("click", () => {
    ["[data-it-header-customer]", "[data-it-header-order-type]", "[data-it-header-order-status]", "[data-it-header-invoicing-status]", "[data-it-header-transport]", "[data-it-header-urgency]"].forEach(selector => { get(selector).value = ""; });
    state.page = 1; loadRows().catch(showError);
  });
  get("[data-it-search]").addEventListener("input", () => { clearTimeout(state.timer); state.timer = setTimeout(() => { state.page = 1; loadRows().catch(showError); }, 250); });
  get("[data-it-prev]").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadRows().catch(showError); } });
  get("[data-it-next]").addEventListener("click", () => { if (state.page < state.pages) { state.page += 1; loadRows().catch(showError); } });
  Promise.all([loadOverview(), loadRows()]).catch(showError);
})();
