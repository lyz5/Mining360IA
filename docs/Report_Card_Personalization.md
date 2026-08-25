# Report Card Personalization

## Scope

Mining 360 resolves each Reporting Hub card through a governed visual identity. The resolver is centralized in `reports/report_visual_identity.py`; templates do not independently choose assets or colors.

Resolution order:

1. approved manual thumbnail or approved library asset;
2. configured Power BI screenshot URL;
3. report illustration;
4. category illustration;
5. category icon;
6. neutral Mining 360 fallback.

The Hub never generates screenshots or AI descriptions during page load.

## Administration

Open `Config > Reporting`, select one report, then open `Visual Identity`.

Administrators can configure the governed category, accent, illustration, icon, badge, descriptions, tags, featured state, thumbnail source, focal point, and an approved asset. Desktop, laptop, mobile, and list previews update without saving.

Uploaded thumbnails accept PNG, JPEG, or WebP, up to 5 MB, with a minimum size of 600 x 225 and a landscape aspect ratio. Files are served through authenticated endpoints rather than public media URLs.

Initial identities are deliberately marked `Needs Review`. Publishing an approved configuration changes its effective identity state according to validation.

## Governance

- Accents, icons, illustrations, tags, and categories use controlled lists.
- Existing complete identities are not overwritten by seed migrations.
- Manual thumbnails and validated descriptions are excluded from bulk fallback replacement.
- Configuration and thumbnail changes use the existing report audit log.
- Broken or unavailable images fall back without exposing a browser broken-image state.

## Feature Flag

`ENABLE_REPORT_CARD_PERSONALIZATION` supports the standard Mining 360 modes: `Disabled`, `Admin Only`, `Pilot`, and `Production`.

When disabled, the Reporting Hub retains category-based fallback visuals and existing launch behavior.

## Deployment

1. Deploy application code and static assets.
2. Run `python manage.py migrate`.
3. Run `python manage.py check`.
4. Review `Config > Reporting` and filter Visual Identity by `Needs Review`.
5. Validate representative cards on desktop and mobile.
6. Move the feature flag from `Admin Only` to `Pilot`, then `Production`.

Power BI screenshot synchronization is intentionally not automatic. A screenshot may be configured only after a supported, secured capture process is available.

## Rollback

Preferred rollback is configuration-only:

1. set `ENABLE_REPORT_CARD_PERSONALIZATION=Disabled`;
2. restart the application;
3. retain the personalization tables and media for later reactivation.

Do not reverse migrations in production merely to disable the UI. If schema rollback is required in a disposable test environment, first back up the database and media directory, then migrate `reports` back to `0079` using the release's normal deployment process.

## Validation

Automated checks cover resolver priority, broken-asset fallback, upload validation, permissions, configuration persistence, Hub rendering, responsive grids, search, URL state, list view, and configuration preview modes. Browser artifacts are written to `.artifacts/reporting-hub` and `artifacts/reporting-configuration`.
