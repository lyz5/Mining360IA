from unittest import TestCase

from codex_integration.app_server_turn import consume_turn_notification


class AppServerTurnNotificationTests(TestCase):
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
