from dataclasses import dataclass
from unittest import TestCase

from codex_integration.access_policy import (
    CodexAccessConfiguration,
    can_access_codex_admin,
    can_access_codex_chatbot,
)


@dataclass(frozen=True)
class Principal:
    id: int
    is_authenticated: bool = True
    is_superuser: bool = False
    is_staff: bool = False


class CodexAccessPolicyTests(TestCase):
    def test_disabled_modules_deny_even_superuser(self):
        principal = Principal(id=1, is_superuser=True, is_staff=True)
        configuration = CodexAccessConfiguration()

        self.assertFalse(can_access_codex_chatbot(principal, configuration))
        self.assertFalse(can_access_codex_admin(principal, configuration))

    def test_explicit_pilot_can_access_chatbot_but_not_admin(self):
        principal = Principal(id=7)
        configuration = CodexAccessConfiguration(
            chatbot_enabled=True,
            admin_enabled=True,
            chatbot_pilot_user_ids=frozenset({"7"}),
        )

        self.assertTrue(can_access_codex_chatbot(principal, configuration))
        self.assertFalse(can_access_codex_admin(principal, configuration))

    def test_staff_status_does_not_grant_access(self):
        principal = Principal(id=9, is_staff=True)
        configuration = CodexAccessConfiguration(
            chatbot_enabled=True,
            admin_enabled=True,
        )

        self.assertFalse(can_access_codex_chatbot(principal, configuration))
        self.assertFalse(can_access_codex_admin(principal, configuration))

    def test_superuser_can_access_each_enabled_module(self):
        principal = Principal(id=1, is_superuser=True, is_staff=True)
        configuration = CodexAccessConfiguration(
            chatbot_enabled=True,
            admin_enabled=True,
        )

        self.assertTrue(can_access_codex_chatbot(principal, configuration))
        self.assertTrue(can_access_codex_admin(principal, configuration))

    def test_anonymous_principal_is_denied(self):
        principal = Principal(id=0, is_authenticated=False, is_superuser=True)
        configuration = CodexAccessConfiguration(
            chatbot_enabled=True,
            admin_enabled=True,
            chatbot_pilot_user_ids=frozenset({"0"}),
        )

        self.assertFalse(can_access_codex_chatbot(principal, configuration))
        self.assertFalse(can_access_codex_admin(principal, configuration))
