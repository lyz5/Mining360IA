from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase

from .revenue_query import active_revenue_snapshots


class ActiveRevenueQueryTests(SimpleTestCase):
    def test_sqlite_keeps_parameterized_active_scope(self):
        with patch.object(connection, "vendor", "sqlite"):
            sql, _params = active_revenue_snapshots().query.sql_with_params()
        self.assertNotIn("[active] = 1", sql)
        self.assertIn("active", sql)

    def test_sqlserver_repeats_scope_with_literal_for_filtered_index(self):
        with patch.object(connection, "vendor", "microsoft"):
            sql, params = active_revenue_snapshots().filter(
                source_account_code="restricted"
            ).query.sql_with_params()
        self.assertIn('"bm_revenue_source_snapshot".[active] = 1', sql)
        self.assertIn("source_account_code", sql)
        self.assertIn("restricted", params)
        self.assertIn(True, params)
