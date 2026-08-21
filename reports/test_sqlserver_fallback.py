import os
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from .sqlserver import connect
from .sqlserver_config_store import is_sqlserver_config_store_enabled


class SQLServerFallbackTests(SimpleTestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_config_sync_is_opt_in(self):
        self.assertFalse(is_sqlserver_config_store_enabled())

    @patch.dict(os.environ, {"MINING360_SQL_CONFIG_STORE": "1"}, clear=True)
    def test_config_sync_can_be_enabled_explicitly(self):
        self.assertTrue(is_sqlserver_config_store_enabled())

    @patch("reports.sqlserver.pytds.connect")
    @patch("reports.sqlserver.pyodbc.connect", side_effect=RuntimeError("ODBC TLS failure"))
    def test_configured_odbc_driver_falls_back_to_python_tds(self, odbc_connect, tds_connect):
        connection = MagicMock()
        tds_connect.return_value = connection

        with connect(
            server="sql.example.test",
            database="MiningProd",
            user="reader",
            password="secret",
            port=1433,
            driver="ODBC Driver 18 for SQL Server",
            timeout_seconds=5,
        ) as selected:
            self.assertIs(selected, connection)

        self.assertGreater(odbc_connect.call_count, 0)
        tds_connect.assert_called_once()
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    @patch("reports.sqlserver.pytds.connect")
    @patch("reports.sqlserver.pyodbc.connect", side_effect=RuntimeError("ODBC TLS failure"))
    def test_tds_transaction_rolls_back_when_browser_query_fails(self, _odbc_connect, tds_connect):
        connection = MagicMock()
        tds_connect.return_value = connection

        with self.assertRaisesRegex(RuntimeError, "query failed"):
            with connect(
                server="sql.example.test",
                database="MiningProd",
                user="reader",
                password="secret",
                driver="ODBC Driver 18 for SQL Server",
            ):
                raise RuntimeError("query failed")

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        connection.close.assert_called_once()
