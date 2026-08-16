# Prime Movers Power Apps context channel

## Purpose

The standalone Canvas App is loaded once. Mining 360 publishes each Power BI
table selection to Dataverse using the stable `contextId` passed at launch.
The Canvas App polls that row and updates its local selected-equipment record.

`PowerBIIntegration.Data` remains only as a fallback when the app is opened as
an actual Power BI visual. It is not available in the standalone iframe.

## Dataverse table

Create an organization-owned table in the `PrimeMoversLeaderShip` solution.

- Display name: `Mining 360 Prime Movers Context`
- Logical name: `pbi_mining360primemoverscontext`
- Entity set: `pbi_mining360primemoverscontexts`
- Primary name: `pbi_name`

Required columns:

| Display name | Logical name | Type |
| --- | --- | --- |
| Context ID | `pbi_contextid` | Text 100, required |
| Selection Version | `pbi_selectionversion` | Whole number |
| Equipment ID | `pbi_equipmentid` | Text 255 |
| Serial Number | `pbi_serialnumber` | Text 255 |
| MineSite | `pbi_minesite` | Text 255 |
| Customer | `pbi_customer` | Text 255 |
| Model | `pbi_model` | Text 255 |
| Selected Status | `pbi_selectedstatus` | Text 255 |
| User UPN | `pbi_userupn` | Text 320 |
| Entra Object ID | `pbi_entraobjectid` | Text 100 |
| Expires At | `pbi_expiresat` | Date and time, time-zone independent |

Create an alternate key on `pbi_contextid`.

## Runtime application user

In environment `90957e36-9c41-e969-ac5d-62bcb48b58f8`, add the existing
Mining 360 App Registration as a Dataverse Application User:

- Tenant ID: `7a1b77be-dbd5-45cb-8e11-b01cbec06667`
- Client ID: `f89997a9-d02d-4d03-9aea-0189f631af09`
- Environment URL: `https://org0458b935.crm12.dynamics.com`

Assign a least-privilege role with organization-level Create, Read and Write
only on `Mining 360 Prime Movers Context`. No permission on the comment table
is required for this technical identity.

Canvas users need organization-level Read on the context table. Their existing
permissions on `PrimeMoversEquipments` remain unchanged, so comment records are
still created by the real Microsoft user.

## Canvas App formulas

Add the context table as data source `Mining360PrimeMoversContexts`.

App `OnStart`:

```powerfx
Set(varContextId, Param("contextId"));
Set(varSelectionVersion, -1);
If(
    IsBlank(varContextId),
    Set(varSelectedEquipment, First(PowerBIIntegration.Data))
)
```

Add a hidden repeating Timer with a 1500 ms duration. `OnTimerEnd`:

```powerfx
If(
    !IsBlank(varContextId),
    Refresh(Mining360PrimeMoversContexts);
    With(
        {
            ctx: LookUp(
                Mining360PrimeMoversContexts,
                'Context ID' = varContextId
            )
        },
        If(
            !IsBlank(ctx) && ctx.'Selection Version' <> varSelectionVersion,
            Set(varSelectionVersion, ctx.'Selection Version');
            Set(
                varSelectedEquipment,
                {
                    SN: ctx.'Serial Number',
                    Site: ctx.MineSite,
                    Model: ctx.Model,
                    Equipment: ctx.'Equipment ID',
                    Status: ctx.'Selected Status'
                }
            );
            Reset(Comments);
            Reset(Downtypess)
        )
    )
)
```

Replace all `First(PowerBIIntegration.Data)` reads on the screen with
`varSelectedEquipment`. In the Save button, remove the assignment from
`PowerBIIntegration.Data` and make refresh conditional:

```powerfx
If(IsBlank(varContextId), PowerBIIntegration.Refresh())
```

The existing `Patch(PrimeMoversEquipments, ...)` remains user-delegated and
must not be moved to the Mining 360 backend.
