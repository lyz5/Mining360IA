from unittest import TestCase
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from codex_integration.app_server_turn import AppServerTurnError, consume_turn_notification, run_grounded_turn


class AppServerTurnNotificationTests(TestCase):
    def test_web_search_notifications_are_counted_without_capturing_queries(self):
        ids = set()
        event = {"method":"item/completed", "params":{"item":{
            "type":"webSearch", "id":"search-1", "query":"Public information",
        }}}
        consume_turn_notification(event, [], ids)
        consume_turn_notification(event, [], ids)
        self.assertEqual(ids, {"search-1"})
    def test_pre_response_notifications_build_answer_and_complete_turn(self):
        answer_parts = []

        first_completed = consume_turn_notification(
            {"method": "item/agentMessage/delta", "params": {"delta": "CODEX_"}},
            answer_parts,
        )
        second_completed = consume_turn_notification(
            {"method": "item/agentMessage/delta", "params": {"delta": "RUNTIME_OK"}},
            answer_parts,
        )
        final_completed = consume_turn_notification(
            {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
            answer_parts,
        )

        self.assertFalse(first_completed)
        self.assertFalse(second_completed)
        self.assertTrue(final_completed)
        self.assertEqual("".join(answer_parts), "CODEX_RUNTIME_OK")

    def test_resume_reapplies_current_mode_instructions_and_isolation(self):
        transport = MagicMock()
        notifications = [
            {"method": "item/agentMessage/delta", "params": {"delta": "OK"}},
            {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            with patch("codex_integration.app_server_turn._JsonLineProcess", return_value=transport), patch(
                "codex_integration.app_server_turn._request",
                side_effect=[
                    ({"codexHome": str(home)}, []),
                    ({"thread": {"id": "existing-thread"}}, []),
                    ({"turn": {"id": "new-turn"}}, notifications),
                ],
            ) as request:
                result = run_grounded_turn(
                    cli_path="test-codex", codex_home=home, workspace=workspace,
                    prompt="Current question", native_thread_id="existing-thread",
                    base_instructions="Current mode instructions",
                )
                resume = request.call_args_list[1].kwargs
                self.assertEqual(resume["method"], "thread/resume")
                self.assertEqual(resume["params"]["baseInstructions"], "Current mode instructions")
                self.assertEqual(resume["params"]["sandbox"], "read-only")
                self.assertEqual(resume["params"]["approvalPolicy"], "never")
                self.assertEqual(resume["params"]["config"]["web_search"], "disabled")
                self.assertEqual(resume["params"]["cwd"], str(workspace.resolve()))
                self.assertEqual(result.answer, "OK")
        transport.close.assert_called_once()

    def test_busy_native_thread_is_replaced_once_before_submitting_turn(self):
        transport = MagicMock()
        with tempfile.TemporaryDirectory() as directory, patch(
            "codex_integration.app_server_turn._JsonLineProcess", return_value=transport
        ), patch("codex_integration.app_server_turn._request", side_effect=[
            ({"codexHome": directory}, []),
            AppServerTurnError("Thread already has an active runtime."),
            ({"thread": {"id": "replacement-thread"}}, []),
            ({"turn": {"id": "new-turn"}}, [
                {"method": "item/agentMessage/delta", "params": {"delta": "OK"}},
                {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
            ]),
        ]) as request:
            result = run_grounded_turn(
                cli_path="test-codex", codex_home=Path(directory)/"home",
                workspace=Path(directory)/"workspace", native_thread_id="busy-thread",
                prompt="Application history and current question", base_instructions="Current mode",
            )
            self.assertEqual(result.thread_id, "replacement-thread")
            self.assertEqual([call.kwargs['method'] for call in request.call_args_list],
                             ['initialize','thread/resume','thread/start','turn/start'])
            fresh = request.call_args_list[2].kwargs['params']
            self.assertEqual(fresh['sandbox'], 'read-only')
            self.assertEqual(fresh['baseInstructions'], 'Current mode')
            self.assertEqual(request.call_args_list[3].kwargs['params']['input'][0]['text'],
                             'Application history and current question')

    def test_resume_authentication_failure_is_not_retried_as_new_thread(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "codex_integration.app_server_turn._JsonLineProcess", return_value=MagicMock()
        ), patch("codex_integration.app_server_turn._request", side_effect=[
            ({"codexHome": directory}, []), AppServerTurnError("Authentication required."),
        ]) as request:
            with self.assertRaises(AppServerTurnError):
                run_grounded_turn(cli_path="test-codex", codex_home=Path(directory)/"home",
                    workspace=Path(directory)/"workspace", native_thread_id="old-thread", prompt="Hello")
            self.assertEqual(request.call_count, 2)
