# BODEFM SSH service recovery — 1 November 2026

## Incident and evidence

The Mining360 deployment preflight initially timed out connecting to BODEFM on TCP port 22. RDP connectivity to `172.17.0.111:3389` succeeded. In the user's RDP session, the read-only checks showed:

- `Get-Service sshd`: `Stopped`.
- `Get-NetTCPConnection -LocalPort 22 -State Listen`: no listener.
- `OpenSSH-Server-In-TCP`: enabled, inbound, action `Allow`.

This identifies the immediate cause of the SSH timeout: the OpenSSH service was stopped, so BODEFM had no process listening on port 22. These results do not establish why the service stopped. The firewall rule's enabled state does not by itself explain or correct a stopped service.

## Recovery performed by the user

The user started the service in an elevated PowerShell session:

```powershell
Start-Service -Name sshd
Get-Service sshd
Get-NetTCPConnection -LocalPort 22 -State Listen
```

The subsequent output showed `sshd` as `Running`, listening on `[::]:22` and `0.0.0.0:22` (PID `21288` at the time of observation). The service startup type was not checked. Do not set it to Automatic without IT authorization.

## Deployment status after starting SSH

The user supplied a local credential file and explicitly authorized its use. Its password was read into process memory only; it was not printed, written to the repository, or stored in the managed credential database. Using the managed target's pinned host key, SSH authentication and the System Doctor remote checks succeeded. The target remains configured locally with its existing credential reference; no persistent credential setting was changed.

The normal deployment precheck reached `BODEFM` and confirmed the approved Windows Test target, pinned host key, runtime ownership and SQL connectivity. It stopped before transferring or running a release because the C: drive had **4.94 GB free of 199.66 GB**; the deployment safety threshold is 5 GB. Other precheck results included one warning. No deployment job was started and no remote files, database, or runtime were changed. A local Draft plan records this blocked attempt. The Revenue 05:00 change at commit `9e9e37f5b8f5863b73a09b219381e2bde2cb323b` on branch `fix/revenue-refresh-0500-20261031` remains pushed to GitHub and is not installed on BODEFM.

Before retrying, have IT free and verify adequate space on C: (at least the precheck minimum, with additional room for the staged release). Do not delete server files or bypass the precheck as part of the deployment. Once space is available, rerun System Doctor and the normal deployment workflow with the same approved target.

ChatGPT Desktop is blocked on Neemba machines. Although TCP/3389 is reachable, the current Codex tool session has no interactive RDP screen/keyboard channel. No `EncodedCommand` or encoded PowerShell command was used.

## Next-attempt instruction

Before the next BODEFM SSH deployment attempt, ask the user directly to check/start `sshd` in their authorized RDP session using an elevated PowerShell window. Have them verify that the service is `Running` and port 22 is listening, then rerun the managed deployment preflight. Do not change the firewall, service startup type, or Production deployment guard without IT authorization. Never ask the user to send a password or private key in chat.
