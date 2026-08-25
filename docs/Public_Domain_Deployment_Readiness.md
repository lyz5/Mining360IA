# Mining 360 public-domain readiness

Target URL: `https://mining360.neemba.com`

## Prepared in the application release

- Django accepts the public and current internal host names.
- CSRF trusts the public HTTPS origin.
- IIS forwarded host and scheme are honored by Waitress and Django.
- Secure session and CSRF cookies remain enabled.
- Entra callback and post-logout URLs derive from the configured public base URL.
- Uploaded report visuals use `C:\Mining360\shared\media` and survive atomic releases.
- `deployment\windows\configure_public_domain.ps1` applies the non-secret machine settings after IT approval.

## Pending IT configuration

1. Create and validate public DNS for `mining360.neemba.com`.
2. Publish BODEFM through Microsoft Entra Application Proxy with pre-authentication.
3. Install at least two Application Proxy connectors for production resilience where possible.
4. Attach a valid TLS certificate for `mining360.neemba.com`.
5. Register `https://mining360.neemba.com/auth/callback/` in the Entra application.
6. Register `https://mining360.neemba.com/login/` as the post-logout redirect.
7. Assign the application to approved internal groups and B2B guest groups only.
8. Apply MFA, Conditional Access, guest access reviews, and a default-deny assignment policy.
9. Confirm outbound access from the connectors and BODEFM to Entra, Graph, Power BI, and required AI providers.
10. Do not expose Waitress port `8000`, SQL Server, or BODEFM directly to the Internet.

## Activation on BODEFM

Preview the settings first:

```powershell
& C:\Mining360\app\deployment\windows\configure_public_domain.ps1
```

After DNS, TLS, Application Proxy, and Entra redirects are confirmed, run from an elevated PowerShell session:

```powershell
& C:\Mining360\app\deployment\windows\configure_public_domain.ps1 -Apply
schtasks.exe /End /TN Mining360TestRuntime
schtasks.exe /Run /TN Mining360TestRuntime
```

Validate `/health/`, login, CSRF-protected POST actions, Reporting Hub, report embedding, RLS, and logout through the public URL before assigning external users.
