import sqlite3
from unittest.mock import Mock, patch
from django.db import OperationalError
from django.test import SimpleTestCase, RequestFactory
from .db_retry import retry_queue_transaction
from .access import codex_chatbot_access_required


def busy():
    cause = sqlite3.OperationalError('database is locked')
    cause.sqlite_errorcode = sqlite3.SQLITE_BUSY
    error = OperationalError('database is locked')
    error.__cause__ = cause
    return error


class QueueRetryTests(SimpleTestCase):
    @patch('codex_chatbot.db_retry.time.sleep')
    def test_transient_lock_retries_same_request(self, sleep):
        work = Mock(side_effect=[busy(), 'saved'])
        result = retry_queue_transaction(work)(request_id='same-id')
        self.assertEqual(result, 'saved')
        self.assertEqual(work.call_count, 2)
        self.assertEqual(work.call_args_list[0], work.call_args_list[1])

    @patch('codex_chatbot.db_retry.time.sleep')
    def test_persistent_lock_is_bounded(self, sleep):
        work = Mock(side_effect=busy())
        with self.assertRaises(OperationalError):
            retry_queue_transaction(work)()
        self.assertEqual(work.call_count, 4)

    def test_unrelated_error_is_not_retried(self):
        work = Mock(side_effect=OperationalError('missing table'))
        with self.assertRaises(OperationalError):
            retry_queue_transaction(work)()
        self.assertEqual(work.call_count, 1)

    @patch('codex_chatbot.access.chatbot_access_allowed', return_value=True)
    def test_database_busy_response_is_json(self, allowed):
        request = RequestFactory().post('/codex-chatbot/api/runs/')
        request.user = Mock(is_authenticated=True)
        response = codex_chatbot_access_required(Mock(side_effect=busy()))(request)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn(b'DATABASE_BUSY', response.content)

    def test_expired_session_is_json_for_api(self):
        request = RequestFactory().get('/codex-chatbot/api/runs/example/')
        request.user = Mock(is_authenticated=False)
        response = codex_chatbot_access_required(Mock())(request)
        self.assertEqual(response.status_code, 401)
        self.assertIn(b'AUTH_REQUIRED', response.content)
