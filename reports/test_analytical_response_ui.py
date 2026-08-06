from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class AnalyticalResponseFrontendContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reports_dir = Path(settings.BASE_DIR) / "reports"
        cls.template = (
            cls.reports_dir / "templates" / "reports" / "ai.html"
        ).read_text(encoding="utf-8")
        cls.javascript = (
            cls.reports_dir / "static" / "reports" / "ai.js"
        ).read_text(encoding="utf-8")
        cls.styles = (
            cls.reports_dir / "static" / "reports" / "styles.css"
        ).read_text(encoding="utf-8")

    def test_heavy_views_are_inside_one_progressive_content_area(self):
        start = self.template.index('id="ai-analytical-content-area"')
        end = self.template.index('id="ai-analytical-quick-actions"')
        content_area = self.template[start:end]
        self.assertIn('id="ai-drivers-view"', content_area)
        self.assertIn('id="ai-downtime-section"', content_area)
        self.assertIn('id="downtime-root-cause-explorer"', content_area)
        self.assertIn('id="ai-powerbi-section"', content_area)

    def test_initial_driver_view_is_limited_to_five(self):
        self.assertIn("drivers.slice(0, 5)", self.javascript)
        self.assertIn('setAnalyticalView(state, "summary")', self.javascript)
        self.assertIn('setAnalyticalView(state, "pareto"', self.javascript)
        self.assertIn('setAnalyticalView(state, "root_cause_explorer"', self.javascript)

    def test_technical_details_are_admin_restricted(self):
        self.assertIn("{% if is_platform_admin %}", self.template)
        self.assertIn("Technical details", self.template)
        self.assertIn('root.dataset.isPlatformAdmin === "true"', self.javascript)

    def test_mobile_uses_driver_cards_without_horizontal_table(self):
        self.assertIn("@media (max-width: 600px)", self.styles)
        self.assertIn(".ai-driver-card-list", self.styles)
        self.assertIn(".ai-downtime-drivers-table__scroll", self.styles)

    def test_main_sidebar_navigation_is_vertically_scrollable(self):
        self.assertIn("height: 100dvh", self.styles)
        self.assertIn("overflow-y: auto", self.styles)
        self.assertIn("overscroll-behavior: contain", self.styles)
        self.assertIn("scrollbar-gutter: stable", self.styles)
