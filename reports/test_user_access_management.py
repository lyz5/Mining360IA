import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .active_directory_service import DirectoryIdentity
from .models import PlatformUser, UserAccessAuditLog
from .user_access_service import authorized_users_queryset


class UsersAccessManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            "admin@example.com", password="secret", is_staff=True, is_superuser=True
        )
        self.admin_profile = PlatformUser.objects.create(
            azure_ad_id="admin-one", user_principal_name="admin@example.com",
            display_name="Mining Admin", django_user=self.admin, is_active=True,
            is_platform_admin=True, can_access_reporting=True, can_access_ai=True,
            can_access_data=True, can_access_sources=True,
        )
        self.client.force_login(self.admin)

    def render_navigation(self, user, active_section=""):
        request = RequestFactory().get("/")
        request.user = user
        return render_to_string(
            "reports/includes/app_nav.html",
            {"active_section": active_section},
            request=request,
        )

    def create_profile(self, upn="jane@example.com", **overrides):
        user = get_user_model().objects.create_user(upn, password="secret")
        values = {
            "azure_ad_id": f"local:{upn}", "user_principal_name": upn,
            "display_name": "Jane Example", "email": upn, "django_user": user,
            "is_active": True, "can_access_reporting": True,
            "business_performance_role": "Viewer",
            "business_performance_scope": {"country": ["Mali"], "customer": ["Fekola"]},
            "directory_roles_managed": False,
        }
        values.update(overrides)
        return PlatformUser.objects.create(**values)

    @override_settings(ENABLE_USERS_PAGE_REDESIGN="Production")
    def test_users_page_uses_redesigned_workspace(self):
        response = self.client.get(reverse("users-manage"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/users_access.html")
        self.assertContains(response, "Search by name, Windows account, email or UPN")
        self.assertNotContains(response, "Save roles")

    def test_data_and_sources_are_nested_inside_config_menu(self):
        html = self.render_navigation(self.admin, active_section="data")
        submenu_start = html.index('id="config-submenu"')
        submenu_end = html.index("</div>", submenu_start)
        data_link = f'href="{reverse("data-home")}"'
        sources_link = f'href="{reverse("data-sources")}"'

        self.assertGreater(html.index(data_link), submenu_start)
        self.assertLess(html.index(data_link), submenu_end)
        self.assertGreater(html.index(sources_link), submenu_start)
        self.assertLess(html.index(sources_link), submenu_end)
        self.assertIn('data-nav-group="config"', html)
        self.assertIn('aria-expanded="true"', html)

    def test_data_role_keeps_menu_access_without_admin_configuration_links(self):
        profile = self.create_profile(
            "data-user@example.com",
            can_access_reporting=False,
            can_access_data=True,
            can_access_sources=False,
        )
        html = self.render_navigation(profile.django_user, active_section="data")

        self.assertIn(f'href="{reverse("data-home")}"', html)
        self.assertNotIn(f'href="{reverse("data-sources")}"', html)
        self.assertNotIn(f'href="{reverse("system-config-home")}"', html)
        self.assertIn('aria-expanded="true"', html)

    def test_authorized_users_api_filters_and_paginates(self):
        jane = self.create_profile()
        self.create_profile(
            "disabled@example.com", display_name="Disabled Person",
            is_active=False, can_access_reporting=False, can_access_ai=True,
        )
        jane.refresh_from_db()
        self.assertTrue(jane.can_access_reporting)
        self.assertEqual(PlatformUser.objects.filter(display_name__icontains="Jane", can_access_reporting=True).count(), 1)
        self.assertEqual(authorized_users_queryset({"q": "Jane", "role": "reporting"}).count(), 1)
        response = self.client.get(reverse("access-control-users-api"), {"q": "Jane", "role": "reporting"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1, payload)
        self.assertEqual(payload["results"][0]["upn"], "jane@example.com")
        self.assertEqual(payload["summary"]["total"], 3)

    def test_non_admin_cannot_access_users_api(self):
        user = get_user_model().objects.create_user("viewer@example.com", password="secret")
        self.client.force_login(user)
        response = self.client.get(reverse("access-control-users-api"))
        self.assertIn(response.status_code, {302, 403})

    def test_directory_search_requires_two_characters(self):
        response = self.client.get(reverse("access-control-directory-search-api"), {"q": "d"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("two characters", response.json()["error"])

    @patch("reports.user_access_views.search_directory_identities")
    @patch("reports.user_access_views.active_directory_integration")
    def test_directory_search_marks_existing_user(self, integration, search):
        integration.return_value = SimpleNamespace(settings_json={"netbios_domain": "NEEMBA"})
        identity = DirectoryIdentity(
            object_id="object-1", username="jdoe", upn="jdoe@example.com",
            email="jdoe@example.com", display_name="Jane Doe", distinguished_name="CN=Jane",
            groups=[], disabled=False,
        )
        self.create_profile(
            "jdoe@example.com", directory_object_id="object-1", directory_username="jdoe",
            auth_source="active_directory",
        )
        search.return_value = [identity]
        response = self.client.get(reverse("access-control-directory-search-api"), {"q": "jane"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["results"][0]["already_authorized"])
        self.assertEqual(response.json()["results"][0]["account_name"], "NEEMBA\\jdoe")

    @patch("reports.user_access_service._business_options", return_value=(["Mali", "Guinea"], ["Fekola", "SNIM"], []))
    def test_access_update_is_validated_and_audited(self, _options):
        profile = self.create_profile()
        response = self.client.patch(
            reverse("access-control-update-api", args=[profile.pk]),
            data=json.dumps({
                "platform_roles": ["reporting", "ai"], "directory_roles_managed": False,
                "business_performance_access": "Viewer", "countries": ["Mali", "Guinea"],
                "customers": ["Fekola"], "powerbi_rls_role": "",
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertTrue(profile.can_access_ai)
        self.assertEqual(profile.business_performance_scope["country"], ["Mali", "Guinea"])
        self.assertTrue(UserAccessAuditLog.objects.filter(platform_user=profile, action="access_changed").exists())

    @patch("reports.user_access_service._business_options", return_value=(["Mali"], ["Fekola"], []))
    @patch("reports.user_access_service.identity_is_allowed", return_value=True)
    @patch("reports.user_access_service.find_directory_identity")
    @patch("reports.user_access_service.active_directory_integration")
    @patch("reports.user_access_service.synchronize_identity")
    def test_add_user_uses_directory_identity_and_one_transaction(self, synchronize, integration, find, _allowed, _options):
        identity = DirectoryIdentity(
            object_id="new-object", username="new.user", upn="new.user@example.com",
            email="new.user@example.com", display_name="New Directory User",
            distinguished_name="CN=New User", groups=[], disabled=False,
        )
        integration.return_value = SimpleNamespace()
        find.return_value = identity

        def create_identity(*_args):
            django_user = get_user_model().objects.create_user(identity.upn)
            profile = PlatformUser.objects.create(
                azure_ad_id="ad:new-object", user_principal_name=identity.upn,
                display_name=identity.display_name, email=identity.email, django_user=django_user,
                auth_source="active_directory", directory_object_id=identity.object_id,
                directory_username=identity.username, directory_roles_managed=True,
            )
            return profile.django_user

        synchronize.side_effect = create_identity
        response = self.client.post(
            reverse("access-control-users-api"),
            data=json.dumps({
                "directory_object_id": identity.object_id, "directory_username": identity.username,
                "upn": identity.upn, "platform_roles": ["reporting", "ai"],
                "directory_roles_managed": False, "business_performance_access": "Viewer",
                "countries": ["Mali"], "customers": ["Fekola"], "powerbi_rls_role": "",
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        profile = PlatformUser.objects.get(directory_object_id=identity.object_id)
        self.assertTrue(profile.can_access_reporting)
        self.assertTrue(profile.can_access_ai)
        self.assertFalse(profile.directory_roles_managed)
        self.assertTrue(UserAccessAuditLog.objects.filter(platform_user=profile, action="user_added").exists())

    @patch("reports.user_access_service._business_options", return_value=([], [], []))
    def test_ad_managed_roles_cannot_be_changed_while_management_remains_enabled(self, _options):
        profile = self.create_profile(
            auth_source="active_directory", directory_roles_managed=True,
            directory_object_id="object-2", can_access_reporting=True,
        )
        response = self.client.patch(
            reverse("access-control-update-api", args=[profile.pk]),
            data=json.dumps({
                "platform_roles": ["ai"], "directory_roles_managed": True,
                "business_performance_access": "", "countries": [], "customers": [],
                "powerbi_rls_role": "",
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Active Directory", response.json()["error"])

    def test_final_administrator_cannot_be_disabled(self):
        response = self.client.post(
            reverse("access-control-status-api", args=[self.admin_profile.pk]),
            data=json.dumps({"active": False}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("own account", response.json()["error"])

    @patch("reports.user_access_service._business_options", return_value=([], [], []))
    def test_unknown_rls_role_is_rejected(self, _options):
        profile = self.create_profile(business_performance_scope={})
        response = self.client.patch(
            reverse("access-control-update-api", args=[profile.pk]),
            data=json.dumps({
                "platform_roles": ["reporting"], "directory_roles_managed": False,
                "business_performance_access": "", "countries": [], "customers": [],
                "powerbi_rls_role": "invented-role",
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field_errors"].keys(), {"powerbi_rls_role"})

    def test_frontend_uses_debounce_and_request_cancellation(self):
        source = Path(__file__).with_name("static").joinpath("reports", "users_access.js").read_text(encoding="utf-8")
        self.assertIn("setTimeout(() => searchDirectory(event.target.value), 300)", source)
        self.assertIn("state.directoryController?.abort()", source)
        self.assertNotIn("data-directory-search-button", source)
