# Portable System Configuration

Mining360 stores enterprise-specific connections and runtime parameters in the graphical **Config > System Config** area. A new company can configure the application without changing Python or frontend code.

## Configuration areas

- **Overview**: readiness and connection status.
- **Connections**: Power BI, Power Automate, OpenAI, databases, data sources, storage, authentication and notifications.
- **Parameters**: organization, localization and runtime behavior.
- **Database Servers**: legacy database registry retained for compatibility.
- **Managed Tables**: synchronized Django and SQL configuration tables.

## Secret handling

Secrets are encrypted before they are stored in `SystemIntegrationConfig.encrypted_secrets`. API responses return only the mask `********` and the names of configured secret fields.

Production must define a stable Fernet key:

```text
MINING360_CONFIG_ENCRYPTION_KEY=<urlsafe-base64-encoded-32-byte-key>
```

The development fallback derives a key from Django's `SECRET_KEY`. Changing either key without re-encrypting stored secrets makes existing connector secrets unreadable.

Never commit local credential files, API keys, flow URLs or database passwords.

## Runtime precedence

During the migration period, connector values are resolved in this order:

1. Environment variable, for emergency deployment overrides.
2. Active default connection configured in System Config.
3. Legacy local JSON file, for backward compatibility only.

Legacy files should be removed after every deployment has been verified against the central registry.

## New company onboarding

1. Apply Django migrations.
2. Sign in as a platform administrator.
3. Open **Config > System Config**.
4. Configure and test the Power BI workspace and service principal.
5. Configure the Power Automate flows used by the installation.
6. Configure OpenAI and its administration key when usage synchronization is required.
7. Configure the application database, source systems and resource storage.
8. Set company name, timezone, language, currency, timeouts, cache and export limits.
9. Verify every connector. A connector is production-ready only when its status is `Connected`.
10. Configure report, semantic model, page, visual, slicer and business mappings in the existing Power BI Interaction and AI Config modules.

## Transition limitations

The central registry is now used by the main Power BI, Power Automate, OpenAI and SQL services. Some business mappings such as report aliases, RLS role aliases and KPI-specific page mappings remain in their existing database/configuration modules and should be migrated progressively rather than duplicated in System Config.
