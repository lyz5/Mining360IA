# Mining360IA

## Business Performance

Mining360 includes a configurable Business Performance module backed by the official Power BI semantic model `Customer Fleet & Revenue Planning Model`.

Pages:

- `/business-performance/` - Executive overview
- `/business-performance/page/customers/` - Customer portfolio
- `/business-performance/customers/<customer>/` - Customer details
- `/business-performance/page/parts-sales/` - Parts sales and exports
- `/business-performance/page/machine-sales/` - Machine sales and exports
- `/business-performance/page/fleet-details/` - Fleet detail and exports
- `/business-performance/config/` - Administrator-only semantic model configuration

The module never recalculates configured Power BI KPIs in Python or JavaScript. DAX is generated from the controlled records in `bp_mappings`; raw free-form DAX is not accepted from the browser. Power BI authentication and RLS use the existing Mining360 execution flow.

Before first use, an administrator must validate the table, column and measure names under **Config > Business Performance**. Required mappings without a valid Power BI object produce an explicit configuration error.

Run validation with:

```powershell
python manage.py migrate
python manage.py check
python manage.py test reports
```

## Power BI Interaction

Administrators configure the analytical copilot under `/knowledge-base/` in the **Power BI Interaction** tab. Import reports first, discover page/visual/slicer metadata, review mappings, and mark approved records as `Validated`. The chatbot activates report navigation only after a validated report mapping exists.
