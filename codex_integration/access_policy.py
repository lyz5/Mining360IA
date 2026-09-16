"""Server-side access policy shared by the future Codex modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CodexPrincipal(Protocol):
    id: object
    is_authenticated: bool
    is_superuser: bool


@dataclass(frozen=True)
class CodexAccessConfiguration:
    chatbot_enabled: bool = False
    admin_enabled: bool = False
    chatbot_pilot_user_ids: frozenset[str] = frozenset()


def can_access_codex_chatbot(
    principal: CodexPrincipal,
    configuration: CodexAccessConfiguration,
) -> bool:
    if not configuration.chatbot_enabled or not principal.is_authenticated:
        return False
    if principal.is_superuser:
        return True
    return str(principal.id) in configuration.chatbot_pilot_user_ids


def can_access_codex_admin(
    principal: CodexPrincipal,
    configuration: CodexAccessConfiguration,
) -> bool:
    return bool(
        configuration.admin_enabled
        and principal.is_authenticated
        and principal.is_superuser
    )
