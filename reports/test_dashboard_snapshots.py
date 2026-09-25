from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch
from unittest.mock import MagicMock
from types import SimpleNamespace
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .dashboard_snapshots import cached_payload, scheduled_slot


class DashboardSnapshotTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = patch('reports.dashboard_snapshots.configuration', return_value={'role': 'origin', 'directory': self.temp.name})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.user = get_user_model().objects.create_user('snapshot-user')

    def test_schedule_is_four_utc_even_when_server_timezone_differs(self):
        self.assertEqual(scheduled_slot(datetime(2026, 9, 21, 3, 59, tzinfo=timezone.utc)), datetime(2026, 9, 20, 4, tzinfo=timezone.utc))
        self.assertEqual(scheduled_slot(datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)), datetime(2026, 9, 21, 4, tzinfo=timezone.utc))

    def test_persistent_snapshot_avoids_source_calls(self):
        calls = []
        def build():
            calls.append(True)
            return {'value': 12}
        first = cached_payload('business', self.user, {}, {'scope': ['A']}, build)
        second = cached_payload('business', self.user, {}, {'scope': ['A']}, build)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second['value'], first['value'])
        self.assertTrue(second['dashboard_snapshot']['cached'])

    def test_scope_user_and_filter_changes_never_reuse_other_payload(self):
        cached_payload('business', self.user, {}, {'scope': ['A']}, lambda: {'value': 1})
        self.assertEqual(cached_payload('business', self.user, {}, {'scope': ['B']}, lambda: {'value': 2})['value'], 2)
        self.assertEqual(cached_payload('business', self.user, {'country': 'SN'}, {'scope': ['A']}, lambda: {'value': 3})['value'], 3)
        other = get_user_model().objects.create_user('snapshot-other')
        self.assertEqual(cached_payload('business', other, {}, {'scope': ['A']}, lambda: {'value': 4})['value'], 4)

    def test_failed_refresh_retains_last_good_snapshot(self):
        cached_payload('excellence', self.user, {}, {}, lambda: {'value': 1})
        def fail():
            raise RuntimeError('source unavailable')
        with self.assertRaises(RuntimeError):
            cached_payload('excellence', self.user, {}, {}, fail, force=True)
        self.assertEqual(cached_payload('excellence', self.user, {}, {}, fail)['value'], 1)

    def test_atomic_write_does_not_leave_temporary_files(self):
        cached_payload('business', self.user, {}, {}, lambda: {'value': 1})
        self.assertFalse(list(Path(self.temp.name).glob('*.tmp')))

    def test_replica_checks_scope_and_keeps_last_copy_only_for_connection_failure(self):
        from .dashboard_snapshot_client import remote_snapshot
        from .business_command_center_service import BusinessCommandCenterInputError
        config = {'role': 'replica', 'directory': self.temp.name, 'deployment_target_id': 1,
                  'address': 'test-host', 'identity_file': 'unused-test-key'}
        contract = {'identity': 'snapshot-user', 'accounts': ['A']}
        target = SimpleNamespace(connection_host='bodefm', host_key_verified=True,
            host_key_fingerprint='approved', port=22, ssh_username='test')
        channel = MagicMock()
        channel.recv_exit_status.return_value = 0
        transport = MagicMock()
        transport.open_session.return_value = channel
        success = {'ok': True, 'contract': contract, 'payload': {'value': 12}}
        channel.makefile.return_value.read.return_value = json.dumps(success).encode()
        with patch('reports.dashboard_snapshot_client.configuration', return_value=config), \
             patch('reports.dashboard_snapshot_client.access_contract', return_value=contract) as scope, \
             patch('deployment.models.DeploymentTarget.objects.get', return_value=target), \
             patch('deployment.services.connection._fingerprint', return_value='approved'), \
             patch('reports.dashboard_snapshot_client.socket.create_connection') as connect, \
             patch('paramiko.Transport', return_value=transport), \
             patch('paramiko.Ed25519Key.from_private_key_file'):
            self.assertEqual(remote_snapshot('business', self.user, {})['value'], 12)
            path = next(Path(self.temp.name).glob('remote-*.json'))
            stored = json.loads(path.read_text())
            stored['received_at'] = '2020-01-01T00:00:00+00:00'
            path.write_text(json.dumps(stored))
            connect.side_effect = OSError('offline')
            self.assertTrue(remote_snapshot('business', self.user, {})['dashboard_snapshot']['offline'])
            scope.return_value = {**contract, 'accounts': ['B']}
            with self.assertRaises(BusinessCommandCenterInputError):
                remote_snapshot('business', self.user, {})
            scope.return_value = contract
            connect.side_effect = None
            channel.makefile.return_value.read.return_value = b'{"ok":false,"code":"access_denied"}'
            with self.assertRaises(BusinessCommandCenterInputError):
                remote_snapshot('business', self.user, {})
            self.assertFalse(path.exists())
            connect.side_effect = OSError('offline after access revocation')
            with self.assertRaises(BusinessCommandCenterInputError):
                remote_snapshot('business', self.user, {})
            connect.side_effect = None
            channel.makefile.return_value.read.return_value = json.dumps({**success, 'contract': {'accounts': ['B']}}).encode()
            with self.assertRaises(BusinessCommandCenterInputError):
                remote_snapshot('business', self.user, {})
