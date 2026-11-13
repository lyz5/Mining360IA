# Mining360 sunset login — 13 November 2026

Native refresh of `/login/`, using the user's sunset-mine reference. The existing
Windows/Active Directory sign-in, local/Microsoft fallback, CSRF fields, next
destination, account hint, password visibility and 14-day session preference are
preserved. No authentication view, identity, permission or integration setting
is changed. The Windows script matches the existing BODEFM file byte for byte.

## Presentation and assets

- Full-screen sunset mine from the reference, with its trucks, navy geometry and
  gold contours. A real glass card replaces the reference's baked-in interface.
- Warm white card, navy typography, yellow Windows action, subtle entry motion,
  visible keyboard focus, responsive layout and reduced-motion support.
- The existing form remains usable without JavaScript. Error messages are alerts;
  existing JavaScript still restores the form after an unsuccessful sign-in.
- Styles are isolated to `login-experience` in the new `login-premium.css`.
  The shared stylesheet and existing background image are unchanged.

Saved image: `reports/static/reports/images/login-mine-sunset-20261113.png`.
The source reference and generated original are retained separately. The image
was edited with the built-in imagegen tool, rather than generated as a UI page.

Final imagegen prompt:

> Edit the provided reference into a clean, production website background only.
> Preserve the original 16:9 composition, photorealistic open-pit mine at golden
> sunset, sky, hills, low sun on the far right, yellow haul trucks on the right-hand
> haul road, dark navy left side, translucent diagonal monogram-like geometry on
> the far left, and fine restrained gold contour lines and dots on the lower left.
> Remove the ENTIRE central white rounded login panel, all logos, brand names,
> lettering, headings, button, icons and UI. Seamlessly inpaint the mine benches,
> landscape, sky and roads behind the removed card, matching the existing light,
> perspective and photographic detail. There must be absolutely no login panel,
> no words, no numbers, no lettering, no buttons and no interface remaining
> anywhere. Do not add trucks or change their locations. Keep the right-side
> sunlight and existing vehicles visually recognizable. Natural crisp landscape
> with slightly softer central detail so a real HTML login card can be placed over
> it later. This is a background image asset, not a screenshot or mockup.

## Verification

`python reports/browser_checks/login_premium.py` passed in local Edge:

- Desktop 1672 × 941 and mobile 390 × 844, with no horizontal overflow.
- Background loads; the card, real button and credentials render.
- Keyboard activation, field focus and password visibility toggle.
- CSRF and the next destination are preserved.
- Failed form submission reopens credentials and clears the password.
- Reduced motion, JavaScript-disabled form, local/Microsoft fallback.
- No JavaScript errors.

Authentication is mocked only in the local browser check, so no real directory
password, account or authentication setting is used or modified. This verifies
the form and existing view wiring, not a new successful domain sign-in.
Private screenshots are in `.runlogs/login-premium/`.

## Release scope

The deployment script is derived from the existing verified Mining360 runtime
workflow, with an eight-target login-only allowlist, content hashes, scoped
backup/rollback, port ownership checks and health verification. Authentication
views, Windows JavaScript and governed Revenue code are hash-protected. Static
manifest additions preserve all existing mappings. No IIS, SQL, firewall, LDAP
or service startup configuration change is part of this release.

## BODEFM deployment and recovery

- Initial page commit: `a94af46399b34ffdca684dbe81fc26b97191487b`.
- Final presentation correction: `2980162b08a04c992e1be86561a69e18fd9e5bf0`.
- Final backup: `D:\Mining360Backups\LoginPremium_20261113_151057_2980162b`.
- Initial backup, restoring the previous login:
  `D:\Mining360Backups\LoginPremium_20261113_150232_a94af463`.
- Final manifest: `C:\Mining360\control\login-premium-2980162b\manifest.json`.
- Final log: `C:\Mining360\logs\login-premium-2980162b.log`.
- Deployment succeeded with application and database health `ok`. Authentication
  view, Windows script and governed Revenue file hashes were unchanged.
- Static manifest has 207 mappings; the 205 pre-existing mappings were preserved.
  Final login stylesheet is `login-premium.01a5cefb2c24.css`; the background is
  `login-mine-sunset-20261113.35db6069f53e.png`.

The first genuine HTTPS browser pass on BODEFM returned page/assets HTTP 200,
zero JavaScript errors, and passed the visible Windows-form interaction and
mobile overflow check. No credentials were submitted. The anonymous Parts page
still redirected to authentication (302). Complete page load and entrance
animation took 3.348 seconds in that observed run; this is not a performance SLA.
The final stylesheet makes the logo divider, gold accent and outline shield
independent of the older shared stylesheet installed on BODEFM.
The final genuine HTTPS browser pass also succeeded: page, final CSS and image
HTTP 200; outline shield confirmed; Windows form and mobile passed; no JavaScript
errors; application/database healthy; protected anonymous page still HTTP 302.
Observed full load including the entrance animation was 3.456 seconds. Final
captures are `login-live-desktop.png`, `login-live-mobile.png` and
`login-live-credentials.png` in the private screenshot directory.

Recovery uses the matching immutable manifest and `deploy_login_premium.ps1
-Rollback -BackupPath <matching backup>`. The final backup restores the first
new design; the initial backup restores the previous login. Review current hashes
before invoking either rollback. Private live screenshots and validation JSON
are retained in `.runlogs/login-premium/`.
