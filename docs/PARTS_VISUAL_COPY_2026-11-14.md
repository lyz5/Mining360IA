# Parts Fulfillment visual copy — 14 November 2026

The user requested removal of the `Sales — Future Order` page legend entry and
the same Copy visual action used in Business Overview.

## Presentation and financial scope

The exact `Sales — Future Order` entry is removed from the trend legend. The
source cohort is retained in the stack, accessible tooltips and accounting
details so the displayed total continues to include all five source measures.
Nothing is filtered out of CA or reclassified as Unallocated. The existing
financial reconciliation and model definitions are unchanged.

## Copy behavior

Copy controls appear on both KPI cards, the sales-origin card, the trend and
the opened cohort-detail table. The existing `Mining360VisualExport` engine and
`dashboard_visual_copy.css` are reused. Both installed BODEFM dependencies were
read and compared with the local copies; they match and are not modified.

Buttons copy the currently rendered visual as a 2× PNG for pasting into Office.
They are disabled during loading or a source failure. If clipboard access is
denied, the existing Download PNG fallback remains available. Filenames include
the accounting month; detail filenames additionally include cohort and page.
The image of the detail table covers its visible page, with its page indicator;
the separate full-filter CSV export is unchanged.

Copy controls, chart interaction help and detail form controls are excluded from
the image. The detail's search context is retained as text. Page-sprite SVG icons
are inlined into the export clone so they render without the original document.
The clipboard/download workflow operates entirely on already visible DOM data;
it fetches no additional source rows and changes no access permission.

## Validation

The local Edge browser harness passed with no JavaScript errors:

- Four summary copy actions and the detail-table copy generate valid PNG blobs.
- Clipboard denial produces a downloadable PNG with the selected month in its name.
- Loading/error states disable copying; month changes update context.
- Signed cohorts remain plotted and Future Order remains in the total while its
  trend legend entry is absent, including a nonzero Future Order case.
- Existing chart, detail, search, CSV, responsive and error-state checks pass.
- A PNG of the real BODEFM aggregate snapshot was inspected visually: chart bars,
  colors, legend, amounts and inline SVG icon render, without the copy control.

The browser test uses a private in-memory clipboard stand-in, preserving the
workstation user's clipboard. The real shared PNG renderer and ClipboardItem
payload are exercised. Private evidence is in `.runlogs/parts-fulfillment/`.
