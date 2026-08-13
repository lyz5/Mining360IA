import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .active_directory_service import (
    ActiveDirectoryError,
    DirectoryIdentity,
    _split_groups,
    _user_allowed,
    authenticate_directory_user,
    identity_is_allowed,
    synchronize_identity,
    test_active_directory_connection,
)
from .models import ActiveDirectoryAuthenticationAuditLog, PlatformUser, SystemIntegrationConfig
from .system_configuration_service import decrypt_secrets, save_integration


def integration_payload(**overrides):
    settings = {
        "host": "dc01.example.local", "port": 636, "use_ssl": True, "start_tls": False,
        "validate_certificate": True, "ca_certificate_file": "C:/certs/corp-ca.pem", "connect_timeout": 10,
        "base_dn": "DC=example,DC=local", "netbios_domain": "NEEMBA", "bind_dn": "CN=svc-mining360,OU=Services,DC=example,DC=local",
        "bind_password": "technical-secret", "user_search_base": "OU=Users,DC=example,DC=local",
        "user_filter": "(&(objectCategory=person)(objectClass=user))", "username_attribute": "sAMAccountName",
        "upn_attribute": "userPrincipalName", "email_attribute": "mail", "display_name_attribute": "displayName",
        "object_id_attribute": "objectGUID", "group_membership_attribute": "memberOf",
        "allowed_groups": "Mining360-Users", "admin_groups": "Mining360-Admins",
        "reporting_groups": "Mining360-Reporting", "ai_groups": "Mining360-AI",
        "data_groups": "Mining360-Data", "sources_groups": "Mining360-Sources",
        "default_business_performance_role": "Viewer", "authentication_enabled": True,
        "create_users_on_login": True, "disable_missing_users": False, "maximum_sync_users": 5000,
    }
    settings.update(overrides)
    return {
        "name": "Corporate AD", "code": "active-directory-test", "integration_type": "Active Directory",
        "provider": "Microsoft Active Directory LDAP", "description": "Test", "is_default": True,
        "is_active": True, "settings": settings,
    }


class ActiveDirectoryConfigurationTests(TestCase):
    def test_password_is_encrypted_and_never_serialized_as_plaintext(self):
        item = save_integration(SystemIntegrationConfig(), integration_payload())
        self.assertNotIn("technical-secret", item.encrypted_secrets)
        self.assertNotIn("bind_password", item.settings_json)
        self.assertEqual(decrypt_secrets(item)["bind_password"], "technical-secret")
        self.assertEqual(item.configured_secret_keys, ["bind_password"])

    def test_group_filter_is_optional_for_global_manual_provisioning(self):
        item = save_integration(SystemIntegrationConfig(), integration_payload(allowed_groups=""))
        self.assertEqual(item.settings_json["allowed_groups"], "")

    def test_plain_ldap_without_starttls_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "LDAPS or StartTLS"):
            save_integration(SystemIntegrationConfig(), integration_payload(use_ssl=False, start_tls=False, port=389))

    def test_ldaps_and_starttls_cannot_be_enabled_together(self):
        with self.assertRaisesRegex(ValueError, "either LDAPS or StartTLS"):
            save_integration(SystemIntegrationConfig(), integration_payload(use_ssl=True, start_tls=True))

    def test_group_name_and_distinguished_name_normalize_to_same_value(self):
        self.assertEqual(
            _split_groups(["Mining360-Users", "CN=Mining360-Users,OU=Groups,DC=example,DC=local"]),
            {"mining360-users"},
        )

    @patch("reports.active_directory_service._server_and_connection")
    def test_connection_check_resolves_group_and_authorized_member(self, connection_factory):
        connection = connection_factory.return_value

        def search(*, search_filter, **kwargs):
            if "objectCategory=group" in search_filter:
                connection.entries = [SimpleNamespace(
                    entry_dn="CN=Mining360-Users,OU=Groups,DC=example,DC=local",
                )]
            else:
                connection.entries = [SimpleNamespace()]
            return True

        connection.search.side_effect = search
        item = save_integration(SystemIntegrationConfig(), integration_payload())
        result = test_active_directory_connection(item)
        self.assertEqual(result, {"users_found": 1, "groups_found": 1, "access_mode": "groups"})
        connection.unbind.assert_called_once()

    @patch("reports.active_directory_service._server_and_connection")
    def test_connection_check_supports_global_directory_mode(self, connection_factory):
        connection = connection_factory.return_value
        connection.search.side_effect = lambda **kwargs: setattr(connection, "entries", [SimpleNamespace()]) or True
        item = save_integration(SystemIntegrationConfig(), integration_payload(allowed_groups=""))
        result = test_active_directory_connection(item)
        self.assertEqual(result, {"users_found": 1, "groups_found": 0, "access_mode": "manual"})

    @patch("reports.active_directory_service._server_and_connection")
    def test_connection_check_rejects_unknown_authorized_group(self, connection_factory):
        connection = connection_factory.return_value
        connection.search.side_effect = lambda **kwargs: setattr(connection, "entries", []) or True
        item = save_integration(SystemIntegrationConfig(), integration_payload())
        with self.assertRaisesRegex(ActiveDirectoryError, r"group\(s\) not found"):
            test_active_directory_connection(item)
        connection.unbind.assert_called_once()


class ActiveDirectoryIdentityTests(TestCase):
    def setUp(self):
        self.item = save_integration(SystemIntegrationConfig(), integration_payload())

    def identity(self, **overrides):
        data = {
            "object_id": "f96f3db6-5648-41c9-b174-9f17861766ba", "username": "jdoe",
            "upn": "jdoe@example.local", "email": "jdoe@example.local", "display_name": "Jane Doe",
            "distinguished_name": "CN=Jane Doe,OU=Users,DC=example,DC=local",
            "groups": ["Mining360-Users", "Mining360-AI", "Mining360-Reporting"], "disabled": False,
        }
        data.update(overrides)
        return DirectoryIdentity(**data)

    def test_group_authorization_is_case_insensitive_and_deny_by_default(self):
        self.assertTrue(_user_allowed(self.identity(groups=["MINING360-USERS"]), self.item.settings_json))
        self.assertFalse(_user_allowed(self.identity(groups=["Other"]), self.item.settings_json))
        config = dict(self.item.settings_json); config["allowed_groups"] = ""
        self.assertFalse(_user_allowed(self.identity(), config))

    def test_sync_creates_unusable_local_password_and_module_rights(self):
        user = synchronize_identity(self.identity(), self.item)
        platform = user.platformuser
        self.assertFalse(user.has_usable_password())
        self.assertEqual(platform.auth_source, "active_directory")
        self.assertEqual(platform.directory_object_id, self.identity().object_id)
        self.assertTrue(platform.can_access_ai)
        self.assertTrue(platform.can_access_reporting)
        self.assertFalse(platform.can_access_data)
        self.assertFalse(platform.is_platform_admin)

    def test_disabled_identity_cannot_remain_active(self):
        user = synchronize_identity(self.identity(disabled=True), self.item)
        self.assertFalse(user.is_active)
        self.assertFalse(user.platformuser.is_active)

    def test_global_directory_identity_can_be_selected_without_group(self):
        config = dict(self.item.settings_json)
        config["allowed_groups"] = ""
        self.item.settings_json = config
        self.item.save(update_fields=["settings_json"])
        self.assertTrue(identity_is_allowed(self.item, self.identity(groups=[])))

    @patch("reports.active_directory_service._server_and_connection")
    @patch("reports.active_directory_service.find_directory_identity")
    def test_global_directory_login_requires_manual_provisioning(self, find_identity, connection_factory):
        config = dict(self.item.settings_json)
        config["allowed_groups"] = ""
        self.item.settings_json = config
        self.item.save(update_fields=["settings_json"])
        find_identity.return_value = self.identity(groups=[])
        with self.assertRaisesRegex(ActiveDirectoryError, "not been authorized"):
            authenticate_directory_user("jdoe", "valid-password")
        connection_factory.assert_not_called()


class ActiveDirectoryBackendTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("reports.active_directory_backend.authenticate_directory_user")
    def test_backend_authenticates_and_audits_directory_user(self, directory_auth):
        user = get_user_model().objects.create_user("jdoe@example.local")
        PlatformUser.objects.create(
            azure_ad_id="ad:one", user_principal_name="jdoe@example.local", display_name="Jane Doe",
            django_user=user, auth_source="active_directory", directory_object_id="one", is_active=True,
        )
        directory_auth.return_value = user
        request = self.factory.post("/login/", REMOTE_ADDR="10.0.0.12", HTTP_USER_AGENT="Browser")
        authenticated = authenticate(request, username="jdoe", password="valid-password")
        self.assertEqual(authenticated, user)
        audit = ActiveDirectoryAuthenticationAuditLog.objects.get()
        self.assertEqual(audit.status, "success")
        self.assertEqual(audit.source_ip, "10.0.0.12")

    @patch("reports.active_directory_backend.authenticate_directory_user")
    def test_backend_rejects_group_failure_without_exposing_detail(self, directory_auth):
        directory_auth.side_effect = ActiveDirectoryError("Not allowed", code="group_not_allowed")
        request = self.factory.post("/login/", REMOTE_ADDR="10.0.0.13")
        self.assertIsNone(authenticate(request, username="outsider", password="secret"))
        self.assertEqual(ActiveDirectoryAuthenticationAuditLog.objects.get().status, "blocked")


class ActiveDirectoryAdminApiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin", password="local-admin", is_staff=True)
        self.client.force_login(self.admin)
        self.item = save_integration(SystemIntegrationConfig(), integration_payload())

    @patch("reports.views.synchronize_directory")
    def test_admin_can_start_synchronization(self, synchronize):
        synchronize.return_value = SimpleNamespace(
            pk=1, status="Completed", discovered_users=4, created_users=2, updated_users=2,
            disabled_users=0, skipped_users=0, failed_users=0, error_message="",
        )
        response = self.client.post(reverse("system-active-directory-sync-api", args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run"]["created_users"], 2)

    def test_non_admin_cannot_synchronize(self):
        user = get_user_model().objects.create_user("viewer", password="password")
        self.client.force_login(user)
        response = self.client.post(reverse("system-active-directory-sync-api", args=[self.item.pk]))
        self.assertIn(response.status_code, {302, 403})

    def test_login_page_switches_to_windows_wording(self):
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Sign in with Windows")
        self.assertContains(response, "data-windows-login")
        self.assertContains(response, "Corporate Windows account")
        self.assertContains(response, "Keep me signed in on this device")
        self.assertContains(response, "data-password-toggle")
        self.assertNotContains(response, "Continue with Microsoft")

    def test_login_page_uses_web_server_windows_identity_as_hint(self):
        self.client.logout()
        response = self.client.get(reverse("login"), REMOTE_USER="NEEMBA\\diagnepa")
        self.assertContains(response, 'data-server-username="NEEMBA\\diagnepa"')

    @patch("reports.views.authenticate")
    def test_keep_signed_in_creates_persistent_session_without_storing_password(self, authenticate_user):
        self.client.logout()
        authenticate_user.return_value = self.admin
        response = self.client.post(reverse("login"), {
            "username": "admin", "password": "not-stored", "keep_signed_in": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertNotIn("password", self.client.session)

    @patch("reports.views.authenticate")
    def test_default_login_session_expires_with_browser(self, authenticate_user):
        self.client.logout()
        authenticate_user.return_value = self.admin
        response = self.client.post(reverse("login"), {
            "username": "admin", "password": "not-stored",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    @patch("reports.views.search_directory_identities")
    @override_settings(ENABLE_USERS_PAGE_REDESIGN="Disabled")
    def test_user_search_displays_canonical_windows_account(self, search):
        search.return_value = [DirectoryIdentity(
            object_id="directory-abass", username="abass", upn="abass@example.local",
            email="abass@example.local", display_name="Abass Example",
            distinguished_name="CN=Abass Example,OU=Users,DC=example,DC=local",
            groups=["Mining360-Users"], disabled=False,
        )]
        response = self.client.get(reverse("users-manage"), {"q": "abass"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NEEMBA\\abass")
        self.assertContains(response, "Abass Example")

    @patch("reports.views.find_directory_identity")
    def test_selecting_directory_user_assigns_manual_roles(self, find_identity):
        find_identity.return_value = DirectoryIdentity(
            object_id="directory-abass", username="abass", upn="abass@example.local",
            email="abass@example.local", display_name="Abass Example",
            distinguished_name="CN=Abass Example,OU=Users,DC=example,DC=local",
            groups=["Mining360-Users"], disabled=False,
        )
        response = self.client.post(reverse("users-add"), {
            "azure_ad_id": "directory-abass", "display_name": "Untrusted Browser Name",
            "user_principal_name": "abass@example.local", "email": "wrong@example.local",
            "directory_source": "active_directory", "directory_username": "abass",
            "can_access_ai": "on", "can_access_data": "on", "business_performance_role": "Viewer",
        })
        self.assertEqual(response.status_code, 302)
        platform = PlatformUser.objects.get(directory_object_id="directory-abass")
        self.assertEqual(platform.display_name, "Abass Example")
        self.assertTrue(platform.can_access_ai)
        self.assertTrue(platform.can_access_data)
        self.assertFalse(platform.directory_roles_managed)

    @patch("reports.views.find_directory_identity")
    def test_direct_post_cannot_add_user_outside_authorized_groups(self, find_identity):
        find_identity.return_value = DirectoryIdentity(
            object_id="directory-outsider", username="outsider", upn="outsider@example.local",
            email="outsider@example.local", display_name="Outside User",
            distinguished_name="CN=Outside User,OU=Users,DC=example,DC=local",
            groups=["Unrelated-Group"], disabled=False,
        )
        response = self.client.post(reverse("users-add"), {
            "azure_ad_id": "directory-outsider", "user_principal_name": "outsider@example.local",
            "directory_source": "active_directory", "directory_username": "outsider", "can_access_ai": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PlatformUser.objects.filter(directory_object_id="directory-outsider").exists())
