from __future__ import annotations

import json
from pathlib import Path
import shutil

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from codex_integration.app_server_turn import (
    AppServerTurnError,
    AppServerTurnInterrupted,
    AppServerTurnTimedOut,
    run_grounded_turn,
)
from codex_integration.contracts import AnswerStatus, RunStatus

from .models import CodexConversation, CodexEvidence, CodexMessage, CodexRun
from .general_conversation import looks_like_business_data_request
from .tools.fleet_inventory import fleet_analysis_from_question
from .tools.performance import availability_analysis_from_question
from .tools.revenue import revenue_analysis_from_question


TERMINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.PARTIALLY_SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.TIMED_OUT,
}


def _resolve_codex_cli_path() -> str:
    configured_path = str(getattr(settings, "CODEX_CHATBOT_CLI_PATH", "") or "").strip()
    discovered_path = shutil.which("codex")
    codex_home = Path(settings.CODEX_CHATBOT_HOME).expanduser()
    profile_cli_path = (
        codex_home.parent / "AppData" / "Roaming" / "npm" / "codex.cmd"
        if codex_home.name.lower() == ".codex"
        else None
    )
    if configured_path and Path(configured_path).is_file():
        return configured_path
    if discovered_path:
        return discovered_path
    if profile_cli_path and profile_cli_path.is_file():
        return str(profile_cli_path)
    raise AppServerTurnError(
        "Codex CLI is not available for the configured Codex application profile."
    )


def _deterministic_answer(evidence: dict) -> str:
    kind = evidence.get("kind")
    if kind == "revenue_access_restricted":
        return "Vous n’avez pas l’autorisation de consulter les informations financières de Business Overview."
    if kind == "revenue_unavailable":
        return "Les données Revenue gouvernées sont temporairement indisponibles pour cette demande."
    if kind == "revenue_scope_ambiguous":
        choices = ", ".join(evidence.get("candidates") or [])
        return f"Le périmètre Revenue est ambigu. Précisez l’un des groupes publiés suivants : {choices}."
    if kind == "availability_access_restricted":
        return "Vous n’avez pas l’autorisation de consulter les données de performance Fleet."
    if kind == "availability_unavailable":
        return "Les données gouvernées de disponibilité physique sont temporairement indisponibles pour cette demande."
    if kind == "availability_scope_ambiguous":
        choices = ", ".join(evidence.get("candidates") or [])
        return f"Le nom de MineSite est ambigu. Précisez l’un des sites suivants : {choices}."
    if kind == "availability_summary":
        context = evidence["context"]
        availability = evidence["availability"]
        filters = context.get("filters") or {}
        model = filters.get("model")
        site = filters.get("minesite")
        if model and site:
            entity = f"du modèle {model} à {site}"
        elif model:
            entity = f"du modèle {model}"
        elif site:
            entity = f"de {site}"
        else:
            entity = "du périmètre sélectionné"
        value = availability.get("formatted_value")
        if availability.get("raw_value") is None:
            return f"La disponibilité physique {entity} n’est pas disponible pour {context.get('period_label', 'la période sélectionnée')}."
        comparison = availability.get("comparison") or {}
        comparison_text = ""
        if comparison.get("delta_points") is not None:
            comparison_label = (
                "par rapport à la même période de l’année précédente"
                if context.get("period_code") == "ytd"
                else "par rapport aux 12 mois glissants précédents"
            )
            comparison_text = f", soit {comparison['delta_points']:+.2f} points {comparison_label}"
        period_label = "YTD" if context.get("period_code") == "ytd" else context.get("period_label", "la période sélectionnée")
        return (
            f"La disponibilité physique {entity} est de {value} pour {period_label} "
            f"({context.get('start_date') or 'date non disponible'} au {context.get('end_date') or 'date non disponible'})"
            f"{comparison_text}. Mesure officielle : {evidence.get('source_measure') or 'Physical Availability'}."
        )
    if kind == "revenue_summary":
        hero = evidence["hero"]
        context = evidence["context"]
        line = context["business_line"].replace("all_business", "Total Mining").title()
        comparison = hero.get("relative_delta")
        comparison_text = f", soit {comparison:+.1f} % par rapport à {context['comparison_label']}" if comparison is not None else ""
        return (
            f"Le Revenue {line} est de {hero['revenue']:,.2f} EUR pour {context['period_label']} "
            f"({context['start_date']} au {context['end_date']}){comparison_text}. "
            f"Réconciliation : {evidence['reconciliation']['status']}."
        )
    if kind == "machine_not_found":
        return f"Le numéro de série {evidence['serial_number']} n’a pas été trouvé dans votre périmètre Fleet autorisé."
    if kind == "machine_detail":
        machine = evidence["machine"]
        family = machine.get("equipment_family") or "famille non renseignée"
        brand = machine.get("brand") or "marque non renseignée"
        return (
            f"Le numéro de série {machine['serial_number']} correspond à l’équipement "
            f"{machine['equipment'] or 'non renseigné'}, modèle {machine['model'] or 'non renseigné'}, "
            f"famille {family}, marque {brand}, sur le site {machine['site']}."
        )
    if kind == "fleet_coverage":
        scope = evidence.get("site") or "votre périmètre autorisé"
        coverage = evidence["coverage_percent"]
        return (
            f"La couverture Fleet de {scope} porte sur {evidence['rows_total']} lignes : "
            f"numéro de série {coverage['serial_number']} %, modèle {coverage['model']} %, "
            f"famille {coverage['equipment_family']} % et marque {coverage['brand']} %."
        )
    if not evidence.get("site"):
        return "Les données gouvernées ont été récupérées, mais aucun résumé compatible n’est disponible pour cette réponse."
    models = evidence.get("models") or []
    model_text = ", ".join(
        f"{row['model']} ({row['equipment_count']})" for row in models[:5]
    )
    answer = (
        f"{evidence['site']} compte {evidence['equipment_count']} équipements distincts "
        f"et {evidence['serial_count']} numéros de série dans le snapshot Fleet actif."
    )
    if model_text:
        answer += f" Principaux modèles : {model_text}."
    return answer


def _compose_with_codex(
    question: str,
    evidence: dict,
    native_thread_id: str,
    cancellation_requested=None,
) -> tuple[str, str, str]:
    if not getattr(settings, "CODEX_CHATBOT_APP_SERVER_ENABLED", False):
        return _deterministic_answer(evidence), native_thread_id, ""
    cli_path = _resolve_codex_cli_path()
    prompt_evidence = dict(evidence)
    if prompt_evidence.get("kind") == "availability_summary":
        prompt_evidence = {
            key: prompt_evidence.get(key)
            for key in (
                "kind", "context", "availability", "summary", "data_quality", "warnings",
                "source_table", "source_service", "source_measure", "definition", "presentation",
            )
        }
    if len(prompt_evidence.get("rows") or []) > 25:
        prompt_evidence["rows"] = prompt_evidence["rows"][:25]
        prompt_evidence["rows_prompt_limited"] = True
    prompt = (
        "Question utilisateur:\n"
        f"{question}\n\n"
        "Preuve métier vérifiée (JSON):\n"
        f"{json.dumps(prompt_evidence, ensure_ascii=False)}\n\n"
        "Réponds en français, de manière concise. Cite la table source et ne crée aucun chiffre."
    )
    result = run_grounded_turn(
        cli_path=cli_path,
        codex_home=Path(settings.CODEX_CHATBOT_HOME),
        workspace=Path(settings.CODEX_CHATBOT_WORKSPACE),
        prompt=prompt,
        native_thread_id=native_thread_id,
        timeout_seconds=float(getattr(settings, "CODEX_CHATBOT_TIMEOUT_SECONDS", 45)),
        cancellation_requested=cancellation_requested,
    )
    return result.answer, result.thread_id, result.turn_id


def _compose_general_with_codex(
    question: str,
    conversation: CodexConversation,
    cancellation_requested=None,
) -> tuple[str, str, str]:
    if not getattr(settings, "CODEX_CHATBOT_APP_SERVER_ENABLED", False):
        raise AppServerTurnError("Codex general conversation is not enabled.")
    cli_path = _resolve_codex_cli_path()
    history = ""
    if not conversation.native_thread_id:
        messages = list(conversation.messages.order_by("created_at").values("role", "content")[:20])
        history = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
    prompt = (
        "Conversation applicative récente:\n"
        f"{history or 'Le thread Codex contient déjà le contexte précédent.'}\n\n"
        "Nouveau message utilisateur:\n"
        f"{question}\n\n"
        "Réponds naturellement dans la langue de l’utilisateur. Ne prétends pas avoir consulté "
        "Mining 360, Internet ou une source temps réel dans ce mode."
    )
    result = run_grounded_turn(
        cli_path=cli_path,
        codex_home=Path(settings.CODEX_CHATBOT_HOME),
        workspace=Path(settings.CODEX_CHATBOT_WORKSPACE),
        prompt=prompt,
        native_thread_id=conversation.native_thread_id,
        timeout_seconds=float(getattr(settings, "CODEX_CHATBOT_GENERAL_TIMEOUT_SECONDS", 120)),
        cancellation_requested=cancellation_requested,
        base_instructions=(
            "You are M360 Chatbot inside Mining 360. In general conversation mode, converse naturally "
            "and helpfully using general model knowledge. Do not use shell, files, web search, external tools, "
            "or claim access to current information. Never invent Mining 360 business values or internal facts. "
            "If internal business data is requested without verified evidence, clearly say that a governed "
            "Mining 360 capability is required."
        ),
    )
    return result.answer, result.thread_id, result.turn_id


def _set_progress(run: CodexRun, percent: int, label: str) -> None:
    run.progress_percent = max(0, min(100, percent))
    run.progress_label = label
    run.heartbeat_at = timezone.now()
    run.save(update_fields=["progress_percent", "progress_label", "heartbeat_at"])


def _result_payload(run: CodexRun, message: CodexMessage | None, runtime_mode: str) -> dict:
    return {
        "conversation_id": str(run.conversation_id),
        "message": None if message is None else {
            "id": str(message.id),
            "role": message.role,
            "content": message.content,
            "answer_status": message.answer_status,
        },
        "run_id": str(run.id),
        "runtime": {
            "mode": runtime_mode,
            "status": run.status,
            "native_thread_active": bool(run.native_thread_id),
        },
        "evidence": [
            {
                "label": item.label,
                "source_type": item.source_type,
                "value": item.value_json,
            }
            for item in run.evidence.all()
        ],
    }


def execute_persisted_run(run: CodexRun) -> dict:
    conversation = run.conversation
    user = run.user
    question = run.question
    if run.status == RunStatus.CANCEL_REQUESTED:
        run.status = RunStatus.CANCELLED
        run.completed_at = timezone.now()
        _set_progress(run, 100, "Traitement annulé.")
        run.save(update_fields=["status", "completed_at"])
        return _result_payload(run, None, "cancelled")

    run.status = RunStatus.RUNNING
    if run.started_at is None:
        run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])
    _set_progress(run, 10, "Résolution de la demande métier autorisée...")
    evidence = revenue_analysis_from_question(question, user=user)
    if evidence is None:
        evidence = availability_analysis_from_question(question, user=user)
    if evidence is None:
        evidence = fleet_analysis_from_question(question, user=user)

    restricted_kinds = {"revenue_access_restricted", "availability_access_restricted"}
    if evidence is not None and evidence.get("kind") not in restricted_kinds:
        _set_progress(run, 30, "Lecture des données gouvernées vérifiées...")
        run.tool_code = {
            "revenue_summary": "business_revenue_summary",
            "revenue_unavailable": "business_revenue_summary",
            "revenue_scope_ambiguous": "business_revenue_scope_resolution",
            "availability_summary": "fleet_physical_availability",
            "availability_unavailable": "fleet_physical_availability",
            "availability_scope_ambiguous": "minesite_resolution",
            "machine_detail": "fleet_machine_by_serial",
            "machine_not_found": "fleet_machine_by_serial",
            "fleet_coverage": "fleet_data_coverage",
        }.get(evidence.get("kind"), "fleet_inventory_by_site")
        run.save(update_fields=["tool_code"])
        evidence_reference = (
            evidence.get("freshness", {}).get("snapshot_id")
            or evidence.get("site")
            or evidence.get("serial_number")
            or "authorized-scope"
        )
        CodexEvidence.objects.get_or_create(
            run=run,
            source_type="DATABASE_TABLE",
            source_record_id=evidence_reference,
            defaults={
                "label": f"Governed analysis: {evidence_reference}",
                "value_json": evidence,
            },
        )

    if evidence is None and not looks_like_business_data_request(question):
        try:
            _set_progress(run, 35, "Conversation avec Codex...")
            answer, thread_id, turn_id = _compose_general_with_codex(
                question,
                conversation,
                cancellation_requested=lambda: CodexRun.objects.filter(
                    id=run.id,
                    status=RunStatus.CANCEL_REQUESTED,
                ).exists(),
            )
            conversation.native_thread_id = thread_id
            run.native_thread_id = thread_id
            run.native_turn_id = turn_id
            run.tool_code = "general_codex_conversation"
            answer_status = AnswerStatus.ANSWERABLE
            run.status = RunStatus.SUCCEEDED
            runtime_mode = "codex_app_server"
        except AppServerTurnInterrupted:
            run.status = RunStatus.CANCELLED
            run.completed_at = timezone.now()
            run.progress_percent = 100
            run.progress_label = "Traitement annulé."
            run.heartbeat_at = timezone.now()
            run.save()
            return _result_payload(run, None, "cancelled")
        except AppServerTurnTimedOut as exc:
            answer = "La conversation générale avec Codex a dépassé le délai autorisé. Réessayez dans un moment."
            answer_status = AnswerStatus.TEMPORARILY_UNAVAILABLE
            run.status = RunStatus.TIMED_OUT
            run.error_code = "CODEX_GENERAL_TIMEOUT"
            run.error_message = str(exc)
            runtime_mode = "codex_app_server"
        except AppServerTurnError as exc:
            answer = "La conversation générale avec Codex est temporairement indisponible."
            answer_status = AnswerStatus.TEMPORARILY_UNAVAILABLE
            run.status = RunStatus.PARTIALLY_SUCCEEDED
            run.error_code = "CODEX_GENERAL_UNAVAILABLE"
            run.error_message = str(exc)
            runtime_mode = "codex_app_server"
    elif evidence is None:
        answer = (
            "Cette question demande des données Mining 360 qui ne sont pas encore raccordées à un outil "
            "gouverné. Précisez le périmètre ou utilisez une capacité disponible."
        )
        answer_status = AnswerStatus.NEEDS_CLARIFICATION
        run.status = RunStatus.SUCCEEDED
        runtime_mode = "governed_tools"
    elif evidence.get("kind") in {
        "machine_not_found", "revenue_access_restricted", "revenue_unavailable",
        "revenue_scope_ambiguous",
        "availability_access_restricted", "availability_unavailable",
        "availability_scope_ambiguous",
    }:
        answer = _deterministic_answer(evidence)
        answer_status = {
            "machine_not_found": AnswerStatus.ENTITY_NOT_FOUND,
            "revenue_access_restricted": AnswerStatus.ACCESS_RESTRICTED,
            "revenue_unavailable": AnswerStatus.TEMPORARILY_UNAVAILABLE,
            "revenue_scope_ambiguous": AnswerStatus.NEEDS_CLARIFICATION,
            "availability_access_restricted": AnswerStatus.ACCESS_RESTRICTED,
            "availability_unavailable": AnswerStatus.TEMPORARILY_UNAVAILABLE,
            "availability_scope_ambiguous": AnswerStatus.NEEDS_CLARIFICATION,
        }[evidence.get("kind")]
        run.status = RunStatus.SUCCEEDED
        runtime_mode = "governed_tools"
    else:
        try:
            _set_progress(run, 55, "Synthèse Codex à partir des preuves vérifiées...")
            answer, thread_id, turn_id = _compose_with_codex(
                question,
                evidence,
                conversation.native_thread_id,
                cancellation_requested=lambda: CodexRun.objects.filter(
                    id=run.id,
                    status=RunStatus.CANCEL_REQUESTED,
                ).exists(),
            )
            conversation.native_thread_id = thread_id
            run.native_thread_id = thread_id
            run.native_turn_id = turn_id
            answer_status = AnswerStatus.ANSWERABLE
            run.status = RunStatus.SUCCEEDED
            runtime_mode = "codex_app_server" if turn_id else "governed_tools"
        except AppServerTurnInterrupted:
            run.status = RunStatus.CANCELLED
            run.completed_at = timezone.now()
            run.progress_percent = 100
            run.progress_label = "Traitement annulé."
            run.heartbeat_at = timezone.now()
            run.save()
            return _result_payload(run, None, "cancelled")
        except AppServerTurnTimedOut as exc:
            answer = _deterministic_answer(evidence)
            answer += " Codex a dépassé le délai autorisé; les valeurs affichées restent issues de la preuve vérifiée."
            answer_status = AnswerStatus.PARTIALLY_ANSWERABLE
            run.status = RunStatus.TIMED_OUT
            run.error_code = "CODEX_RUNTIME_TIMEOUT"
            run.error_message = str(exc)
            runtime_mode = "governed_fallback"
        except AppServerTurnError as exc:
            answer = _deterministic_answer(evidence)
            answer += " La reformulation Codex est temporairement indisponible; les valeurs affichées restent issues de la preuve vérifiée."
            answer_status = AnswerStatus.PARTIALLY_ANSWERABLE
            run.status = RunStatus.PARTIALLY_SUCCEEDED
            run.error_code = "CODEX_RUNTIME_UNAVAILABLE"
            run.error_message = str(exc)
            runtime_mode = "governed_fallback"

    final_status = run.status
    with transaction.atomic():
        persisted_status = CodexRun.objects.only("status").get(id=run.id).status
        if persisted_status == RunStatus.CANCEL_REQUESTED:
            run.status = RunStatus.CANCELLED
            run.completed_at = timezone.now()
            run.progress_percent = 100
            run.progress_label = "Traitement annulé."
            run.heartbeat_at = timezone.now()
            run.save()
            return _result_payload(run, None, "cancelled")
        run.status = final_status
        message = CodexMessage.objects.create(
            conversation=conversation,
            role="ASSISTANT",
            content=answer,
            answer_status=answer_status,
        )
        run.completed_at = timezone.now()
        run.result_message = message
        run.progress_percent = 100
        run.progress_label = "Réponse enregistrée."
        run.heartbeat_at = timezone.now()
        run.save()
        conversation.save()
    return _result_payload(run, message, runtime_mode)


def ask(*, user, question: str, conversation: CodexConversation | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("Question is required.")
    if conversation is not None and conversation.owner_id != user.id:
        raise PermissionError("Conversation does not belong to this user.")
    with transaction.atomic():
        if conversation is None:
            conversation = CodexConversation.objects.create(
                owner=user,
                title=question[:177] + ("..." if len(question) > 177 else ""),
            )
        CodexMessage.objects.create(conversation=conversation, role="USER", content=question)
        run = CodexRun.objects.create(
            conversation=conversation,
            user=user,
            question=question,
            status=RunStatus.RUNNING,
            started_at=timezone.now(),
        )
    return execute_persisted_run(run)
