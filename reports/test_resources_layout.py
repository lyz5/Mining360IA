import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .resource_library import invalidate_resource_inventory, list_resources


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

    def test_resources_are_paginated_and_inventory_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(60):
                (root / f"document-{index:02d}.pdf").write_bytes(b"pdf")
            with patch("reports.resource_library.RESOURCE_ROOT", root):
                invalidate_resource_inventory()
                response = self.client.get(reverse("resources"))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["resources"]), 48)
                self.assertContains(response, "Page 1 of 2")

                (root / "new-document.pdf").write_bytes(b"pdf")
                self.assertEqual(len(list_resources()), 60)
                invalidate_resource_inventory()
                self.assertEqual(len(list_resources()), 61)
        invalidate_resource_inventory()
