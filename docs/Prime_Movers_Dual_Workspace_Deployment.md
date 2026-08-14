# Prime Movers Operational Status - Dual Workspace

## Decision

Mining 360 uses the supported dual-workspace strategy:

- Power BI: service principal, embed token, `TokenType.Embed`.
- Power Apps: direct canvas application, browser Microsoft Entra session, real employee permissions.
- Context: short-lived opaque `contextId`, bound to the Mining 360 user.

Both exported Prime Movers PBIX variants contain the unsupported Power Apps custom visual. Mining 360 hides that visual and opens the canvas app separately. No Power BI token, client secret, username, machine identifier or comment is placed in the Power Apps URL.

## Discovered configuration

| Item | Value |
| --- | --- |
| Workspace ID | `a378c518-bfc4-4cd7-a49d-ba40394db80f` |
| Original report ID | `7965812a-e2d7-4950-9651-a148d8fdd235` |
| V2 report ID | `2fb4cc34-5dab-49d6-8667-0e5e29a6aedd` |
| Canvas App ID | `f344207c-d3a7-45b9-ae09-6cd27f1f18f6` |
| Tenant ID | `7a1b77be-dbd5-45cb-8e11-b01cbec06667` |
| Mining 360 Entra Client ID | `f89997a9-d02d-4d03-9aea-0189f631af09` |
| Power BI page | `7982fa20087810cade07` |
| Original visual | `36a5326c9e017bc36902` |
| V2 visual | `8a2c81ec43d7e077fa4c` |

The Power Apps Environment ID and official launch URL were not present in the repository or PBIX metadata. They must be copied from Power Apps details, not reconstructed.

## Required environment variables

```text
MINING360_PUBLIC_BASE_URL=https://<approved-mining360-dns>
ENTRA_REDIRECT_URI=https://<approved-mining360-dns>/auth/callback/
ENTRA_POST_LOGOUT_REDIRECT_URI=https://<approved-mining360-dns>/

ENABLE_PRIME_MOVERS_INTEGRATION_RECOVERY=Production
ENABLE_PRIME_MOVERS_DUAL_WORKSPACE=Production
ENABLE_PRIME_MOVERS_POWERAPPS_IFRAME=Pilot
ENABLE_PRIME_MOVERS_POWERAPPS_NEW_TAB=Production
ENABLE_PRIME_MOVERS_AUTH_DIAGNOSTICS=Admin Only
ENABLE_PRIME_MOVERS_USER_OWNS_DATA=Disabled
```

The `ENTRA_REDIRECT_URI` value is authoritative and must exactly match a Web redirect URI in the Entra App Registration. Production must use a trusted HTTPS DNS name. BODEFM currently has only an HTTP Mining 360 binding and no verified production DNS/certificate, so a production callback cannot be declared complete yet.

An HTTP network origin also makes an embedded `apps.powerapps.com` document an insecure context because its ancestor is insecure. MSAL-PKCE then cannot use `crypto.subtle` and returns `crypto_nonexistent`. Mining 360 detects this state and disables iframe login, offering the secure Power Apps new-tab fallback. HTTPS on the approved Mining 360 DNS remains the permanent fix.

## Microsoft Entra administrator action

In **Entra ID > App registrations > Mining 360 > Authentication**:

1. Add platform type **Web**.
2. Add exactly `https://<approved-mining360-dns>/auth/callback/`.
3. Keep localhost only in the Development registration.
4. Confirm delegated Microsoft Graph permission `User.Read` and grant consent according to policy.
5. Do not expose the app secret to the browser.

## Power Apps administrator action

1. Open canvas app `f344207c-d3a7-45b9-ae09-6cd27f1f18f6`.
2. Provide the official Web link and Environment ID to Mining 360 administration.
3. Share the app with the approved Entra security group.
4. Assign required Power Apps license, environment access, Dataverse roles and table permissions.
5. Replace direct dependencies on `PowerBIIntegration.Data` for the Mining 360 launch path:
   - read `Param("contextId")`;
   - resolve it through an Entra-protected custom connector or a governed temporary Dataverse context table;
   - validate the caller's Entra Object ID, context expiration and equipment authorization;
   - never treat possession of the GUID as authorization.
6. Keep the existing `PowerBIIntegration.Data` path only for supported Power BI Service usage if required.

PBIX inspection found context fields including Country, Equipment, Site/Customer, Model, Serial Number, hours, connectivity/subscription, reporting timestamp, status, Last Down Type and Last Comment. Map the same governed fields in the resolver.

## Mining 360 administration

After migration, open Django administration > **Prime Movers Integration Configurations** for both reports and set:

- Power Apps Environment ID;
- official `apps.powerapps.com` launch URL;
- validation status `Validated`;
- iframe enabled only after browser pilot;
- new-tab fallback enabled.

Then open **Prime Movers Integration Diagnostics** from the workspace. The readiness score must have no application-side blocker.

## Deployment

1. Deploy immutable application commit.
2. Apply `python manage.py migrate`.
3. Configure production environment variables.
4. Configure IIS/reverse proxy HTTPS binding and trusted certificate.
5. Register the exact Entra callback.
6. Configure the official Power Apps URL.
7. Pilot with one mapped employee in Edge and Chrome.
8. Promote feature flags from Admin Only to Pilot, then Production.

## Validation

For the pilot user, verify:

1. Mining 360 login uses the corporate directory account.
2. Corporate Microsoft connection creates a validated Entra mapping distinct from the AD object GUID.
3. Reporting and chatbot both open the Prime Movers workspace.
4. Power BI loads with `TokenType.Embed`.
5. The embedded Power Apps custom visual is hidden.
6. Selecting/confirming one serial creates a new opaque context.
7. Power Apps opens with the employee's Entra identity.
8. Dataverse `Created By`/`Modified By` is the employee.
9. Refresh retains the report and selected machine.
10. Blocking iframe authentication exposes the secure new-tab fallback.

## Rollback

1. Set `ENABLE_PRIME_MOVERS_DUAL_WORKSPACE=Disabled`.
2. Keep `ENABLE_PRIME_MOVERS_POWERAPPS_IFRAME=Disabled`.
3. The generic report viewer remains available.
4. If a database rollback is required, reverse migration `0067_prime_movers_dual_workspace`; it restores the original report to User-owns-data and the V2 report to its prior App-owns-data metadata.
5. No downtime event or Dataverse business row is changed by this migration.

## Known external blockers

- approved production HTTPS DNS and trusted certificate;
- exact Entra production callback registration;
- official Power Apps Environment ID and launch URL;
- canvas app context resolver implementation;
- app sharing, licensing and Dataverse permissions;
- end-to-end Dataverse write validation by a real corporate pilot user.

Mining 360 does not report these external prerequisites as successful until they are actually verified.
