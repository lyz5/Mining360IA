# Mining360 Project Handoff

## Recovery Anchor

- Repository: `https://github.com/lyz5/Mining360IA.git`
- Branch: `perf/stable-powerbi-viewer-runtime-20260831`
- Verified commit: `c7ac2c06b4f6b949614de4db10e76e2ecf600b80`
- Local-data backup: `OneDrive - RESDELMAS/Bureau/Backup Documents/Mining360IA-Transfer-2026-09-18`
- Compressed archive: `Mining360IA-local-data-2026-09-18.tar.zst`
- Archive SHA-256: `40050725B4D7FCAC3AC5017404419C42DD849E517700CDA6323D49B8F3FCA20B`
- SQLite backup integrity: `PRAGMA quick_check = ok`

The Git repository does not contain `db.sqlite3`, local credentials, uploaded media, or private certificates. Restore those from the restricted backup.

## Product Map

Mining360 is a Django application with a native Windows Control Center and several governed business products:

- Business Overview: executive Revenue cockpit and default application home.
- Excellence Center: fleet KPI workspaces for Availability, MTBF, MTBS, MTTR and Fuel.
- Business Mapping Studio: administrative canonical Account, Country, MineSite and Key Account governance.
- Reporting: simple end-user report catalogue; technical health is under Config.
- M360 Chatbot and Codex Admin: separate from the legacy Mining360 AI implementation.
- Resources, Users, configuration, deployment and diagnostic workspaces.

## Governed Revenue

- Semantic model: `Customer Fleet & Revenue Planning Model`.
- Dataset ID: `a67ebcac-97d0-4d46-b84d-8109cd2c804a`.
- Revenue fact: `ChriffreAffaire`.
- Amount: `CA euro` grouped by governed transaction dimensions.
- Business lines: `PRIME`, `PARTS`, `SERVICE`, `RENTAL`, plus visible Unclassified.
- Intercompany channel is excluded.
- Default Business Overview scope remains Mining division `MI`.
- `All Divisions` explicitly combines `MI` Mining, `TP` Construction and `MO` Energy.
- Revenue extraction must remain partitioned into one DAX query per division. A combined query exceeded the Power BI response size and returned truncated data.
- Latest validated real-data YTD totals on 2026-09-15:
  - Mining: EUR 384,912,632.72.
  - All Divisions: EUR 555,393,509.65.
  - Both reconciled with zero difference at the configured tolerance.
- Machine and Parts operational detail remain Mining-only. The UI discloses this when All Divisions is active.

## Business Overview State

- Route: `/business-review/command-center/`.
- Default home and first navigation item.
- Workspaces: Executive, Mining Turnover, Sales, Projects & Tenders.
- Periods: YTD, MTD, Last Year, 2024, 2023 and inclusive Custom Range.
- Filters use governed IDs and preserve URL state.
- Customer Country Groups were removed from the Business Overview filter.
- Country labels use full governed names.
- Sales includes Machine Sales and Parts Classification only.
- Machine product groups use 11 governed groups, four cards per row.
- Non-CAT model/family prefix classification falls under governed Diverse/Other behavior.
- Revenue Trend supports YTD and MTD, data labels, fullscreen and copy.
- Real browser validation produced 18 desktop/tablet/mobile screenshots.

## Business Mapping

- Managers consume only Published mappings.
- Draft or Review mappings must never affect executive results.
- Source synchronization is automatic/current-data oriented; publication remains manual.
- Canonical Accounts, Country governance and Key Accounts feed Business Overview.
- Revenue without mapping remains visible and lowers confidence instead of disappearing.

## Excellence Center

- Fleet KPI selector supports Physical Availability, MTBF, MTBS, MTTR and Fuel.
- Official semantic measures include `Availability Per Equip`, `MTBF Per Equip`, `MTBS PER EQUIP` and `MTTR Per Equip`.
- Fuel uses the configured InspectData 4 Power Automate connection and the Fuel Monitoring semantic source.
- KPI pages preserve the same page architecture with KPI-specific hero, trend, distribution and decision support.

## AI Products

- Mining360 AI must remain operational and unchanged unless explicitly requested.
- M360 Chatbot and Codex Admin are separate products and menu items.
- M360 Chatbot has governed access to Business Overview and fleet measures.
- Answers must use verified measures and authorized scope; the model may explain values but must not calculate or invent them.

## Windows Control Center

- Native Tkinter application under `desktop/`.
- Runtime lifecycle logic is separate from UI logic.
- Full Restart must verify PID ownership, stop managed components safely, release ports, start in dependency order and verify readiness.
- Never kill an unknown process solely because it owns a Mining360 port.
- Never modify LDAP, TLS certificates, firewall or Production security automatically.

## Secrets and Local Configuration

- Integration secrets are stored in `SystemIntegrationConfig.encrypted_secrets` using Fernet.
- Active configured secret sets were verified decryptable for Power BI, Power Automate, OpenAI, SQL databases and Active Directory.
- JSON files remain as restricted fallback copies:
  - `powerbi_credentials.local.json`
  - `mining360_sqlserver.local.json`
  - `reports/live_sources_custom.json`
- Never commit these files or print secret values.
- Preserve `MINING360_CONFIG_ENCRYPTION_KEY`. If absent, preserve the exact Django `SECRET_KEY` used to derive the encryption key.

## Validation Baseline

- Business Overview and Business Mapping focused suite: 58 tests passed.
- Django system check: passed.
- Business Overview Playwright suite: 18 real-data screenshots passed across desktop, laptop, tablet and mobile.
- Git working tree was clean at commit `c7ac2c0` before this handoff document was added.

## Restore Procedure

1. Clone the repository and checkout the branch above.
2. Restore the Python environment and install project requirements.
3. Extract the restricted local-data archive.
4. Place `db.sqlite3` in the project root.
5. Restore local configuration files to their original paths.
6. Restore `media/` and approved certificates.
7. Restore the same configuration-encryption key before starting Django.
8. Run `python manage.py check` and `python manage.py migrate --check`.
9. Start Development and validate Business Overview, Excellence Center, M360 Chatbot and Config integrations.
10. Do not erase the previous-machine backup until this validation succeeds.

## Immediate Next Work

- Confirm OneDrive reports the backup archive as fully synchronized, not `Sync pending`.
- Restore and test on the replacement machine.
- Review lower Customer/Country/Key Account mapping coverage for Construction and Energy.
- Keep Sales Machine/Parts details labelled Mining-only until governed cross-division detail sources exist.
- Continue reversible changes and preserve reconciliation tests before deployment.

