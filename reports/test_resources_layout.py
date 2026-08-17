from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class ResourcesLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("resources-user", password="test", is_staff=True)
        self.client.force_login(self.user)

    def test_resources_workspace_uses_viewport_fitted_layout(self):
        response = self.client.get(reverse("resources"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="resources-page-body"')
        self.assertContains(response, "resource-library-shell")
        self.assertContains(response, 'aria-label="Resource documents"')
        self.assertNotContains(response, 'class="workspace-band"')
        self.assertNotContains(response, 'class="summary-value"')
