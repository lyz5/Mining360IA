# Mining 360 Active Directory Authentication

## Architecture

Mining 360 uses a technical read-only bind account to discover authorized users and their direct AD group memberships. A user login is validated with a separate LDAP bind using that user's distinguished name and password. Mining 360 never stores the user's Windows password.

Local Django authentication remains available only for platform administrators as an emergency path. Synced AD users receive an unusable local password.

## Information required from IT

- DNS name of a domain controller; prefer DNS over IP so LDAPS certificate hostname validation works;
- LDAPS port, normally `636`;
- Base DN and User Search Base;
- technical account Bind DN or UPN;
- technical account password through a secure channel;
- corporate CA certificate file installed on the Mining 360 server when it is not already trusted;
- login attribute: `sAMAccountName` or `userPrincipalName`;
- immutable object attribute: `objectGUID` or `objectSid`;
- an optional AD group filter; leave it empty for global-directory search with manual authorization;
- optional groups for Administrator, Reporting, AI, Data and Data Sources roles;
- a standard test user belonging to an authorized group.

The technical account requires directory read access only. It must not be a domain administrator.

## Configuration workflow

1. Sign in with the local Mining 360 platform administrator.
2. Open `/system-config/` and select **Connections**.
3. Edit **Corporate Active Directory**.
4. Enter the connection, search, attribute and group mappings.
5. Leave **Enable AD Authentication** off initially.
6. Save and select **Test**.
7. Confirm that the test reports global-directory search or resolves the configured group filter.
8. In global-directory mode, open **Users & Roles**, search for a person and explicitly add the account with its roles.
9. Use **Sync users** to refresh accounts already authorized in Mining 360; it does not bulk-import the global directory.
10. Test one synchronized standard account.
11. Enable AD Authentication only after the pilot succeeds.

## Security defaults

- LDAPS enabled;
- server certificate validation enabled;
- global-directory search does not grant application access;
- when no group filter is configured, only accounts explicitly provisioned in Users & Roles may authenticate;
- LDAP filter values escaped;
- secrets encrypted in the existing Mining 360 configuration vault;
- disabled AD accounts remain disabled in Mining 360;
- optional disable-missing-users behavior is off until explicitly enabled;
- authentication success, rejection and source IP are audited without passwords.

## Group behavior

The initial implementation uses direct `memberOf` memberships. Nested group expansion must be validated with the organization's AD design before relying on nested groups. Prefer assigning Mining 360 access through direct security-group membership during the pilot.

## Rollback

If authentication fails, set **Enable AD Authentication** off using the local platform administrator. Synced users and audit logs remain available, but AD login is no longer attempted. Do not deactivate the only local platform administrator.
