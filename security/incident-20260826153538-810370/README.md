# Security incident evidence package

Ticket: `20260826153538-810370`

Observed window: 26 August 2026, 15:09-15:12

Target: `BODEFM`

## Administrative command reported by SentinelOne

```text
C:\Mining360\venv\Scripts\python.exe C:\Mining360\app\manage.py shell -c "from reports.models import SystemIntegrationConfig; import json; print(json.dumps([{'id':x.id,'name':x.name,'type':x.integration_type,'active':x.is_active,'default':x.is_default,'settings':x.settings_json,'has_secrets':bool(x.encrypted_secrets)} for x in SystemIntegrationConfig.objects.filter(integration_type='Active Directory')],default=str))"
```

Purpose: inspect the Active Directory integration configuration while diagnosing authentication failures.

Data read by the command:

- integration identifier and name;
- integration type;
- active/default flags;
- non-secret `settings_json` configuration;
- a boolean indicating whether encrypted secrets existed.

The command did not call the application decryption service and did not print the `encrypted_secrets` value. Its use was nevertheless too broad for routine production diagnosis and has been discontinued.

## PowerShell execution mechanism present at the time

The Mining360 remote deployment implementation used Python to encode allowlisted PowerShell command text as UTF-16LE/Base64 and invoke:

```text
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand <base64-payload>
```

The implementation was located in:

- `deployment/os_adapters.py`, function `_powershell`;
- `deployment/services/execution.py`, function `_encoded_command`.

The one-click deployment channel also transferred `deployment/windows/deploy_release.ps1` through the authenticated SSH/SFTP connection. That script checked out one validated Git commit and executed the controlled deployment steps. This combination can match an EDR analytic for encoded PowerShell plus download/execution even when used for legitimate administration.

## Source snapshot supplied

The attached `mining360-incident-source-c1b7ef2.zip` is generated directly from Git commit:

```text
c1b7ef2 - Fix reporting catalog initialization on SQL Server
```

This was the latest repository commit during the beginning of the incident window. The archive contains:

- `deployment/os_adapters.py`;
- `deployment/services/execution.py`;
- `deployment/services/remote.py`;
- `deployment/windows/deploy_release.ps1`.

The later System Doctor commit `706bf9d` was committed at 15:38 UTC, after the 15:09-15:12 alert window.

SHA-256 values of the supplied source files at `c1b7ef2`:

```text
deployment/os_adapters.py                    97d75f0741df0763f91a18965f620cf42d14c2c3ccc12f1941268a0a7c407b76
deployment/services/execution.py             555b89f90290d353195ffb46826a8f502053c4b76b36cd83a7af9e6cfdad6cfd
deployment/services/remote.py                f84d15a36b29d80cf865e473c327fdae600641ef0fbcaf24bf1ca5518bed0e0e
deployment/windows/deploy_release.ps1        4daad482fc4074c2dd2f77394503e080be7ffa520e784e724e4715a6d649bad0
```

None matches the quarantined SHA-256 `73ccd824fc2882f395e9666ec5c04abd12acc0871af485761da532f72e4ef78b`. The quarantined item may therefore be a generated PowerShell/EDR artifact or another downloaded file; SentinelOne telemetry is required to identify it conclusively.

## Payload confirmation required from SentinelOne

The exact Base64 value is not present in the ticket text. Security should export the complete PowerShell command line from SentinelOne telemetry. It can be decoded without execution using:

```powershell
[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('<base64-payload>'))
```

The decoded text can then be compared with the allowlisted commands in the supplied `deployment/os_adapters.py` and `deployment/services/execution.py` files.

## Remediation implemented on 27 August 2026

- removed all use of `-EncodedCommand` from Mining360 deployment sources;
- removed `ExecutionPolicy Bypass` from remote commands;
- remote PowerShell command text is now transparent and inspectable;
- retained pinned SSH host-key validation and named command allowlists;
- documented that ad-hoc `manage.py shell -c` is prohibited for routine diagnosis;
- retained application audit logs for diagnosis, repair and deployment actions;
- added automated tests that fail if encoded PowerShell or policy bypass returns.

Do not create a broad SentinelOne exclusion for `python.exe`, `powershell.exe`, SSH, or `C:\Mining360`. Any temporary exception should be restricted to the reviewed service account, script hash, target path and approved maintenance window.
