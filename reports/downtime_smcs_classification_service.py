from __future__ import annotations

import threading
import os
from datetime import timedelta
from decimal import Decimal

from django.db import close_old_connections
from django.utils import timezone

from .downtime_comment_normalization_service import DowntimeCommentNormalizationService
from .downtime_explorer_service import load_events
from .models import (
    DowntimeSMCSClassification,
    SMCSClassificationConfig,
    SMCSClassificationJob,
)
from .models import OpenAIUsageLog
from .smcs_ai_classification_service import SMCSAIClassificationService
from .smcs_candidate_retrieval_service import SMCSCandidateRetrievalService
from .smcs_deterministic_classification_service import SMCSDeterministicClassificationService


class DowntimeSMCSClassificationService:
    def __init__(self):
        self.normalizer = DowntimeCommentNormalizationService()
        self.deterministic = SMCSDeterministicClassificationService()
        self.candidates = SMCSCandidateRetrievalService()
        self.ai = SMCSAIClassificationService()

    @staticmethod
    def config() -> SMCSClassificationConfig:
        config, _ = SMCSClassificationConfig.objects.get_or_create(
            name="Default",
            defaults={
                "execution_mode": "Preview",
                "generic_comments_json": [
                    "Machine down", "Still down", "In progress", "Under repair",
                    "Breakdown", "Waiting", "Done",
                ],
            },
        )
        return config

    def classify_event_preview(
        self,
        event: dict,
        config: SMCSClassificationConfig,
        *,
        user=None,
        conversation_id="",
    ) -> dict:
        normalized = self.normalizer.normalize(event.get("Comment") or "")
        base = {
            "event_id": event.get("Event ID"),
            "comment": normalized.original,
            "downtime_hours": float(event.get("Duration") or 0),
            "equipment": event.get("Serial Number") or event.get("Equipment") or "",
            "model": event.get("Model") or "",
            "minesite": event.get("MineSite") or event.get("Site") or "",
            "downtime_driver": event.get("Downtime Driver") or "",
            "preview_only": True,
        }
        if normalized.is_empty or normalized.is_generic:
            return {
                **base,
                "classification_status": "unresolved",
                "primary_match": None,
                "match_method": "Unresolved",
                "confidence": 0,
                "requires_review": True,
                "review_reason": "Generic or insufficient comment",
                "evidence_phrases": [],
                "alternative_candidates": [],
                "ai_used": False,
            }
        deterministic = self.deterministic.classify(event, normalized, mode="Preview")
        if not deterministic["requires_ai"]:
            primary = deterministic["primary_candidate"]
            return {
                **base,
                "classification_status": "matched",
                "primary_match": primary,
                "match_method": primary["match_method"],
                "confidence": primary["confidence"],
                "requires_review": False,
                "review_reason": None,
                "evidence_phrases": deterministic.get("evidence_phrases", []),
                "alternative_candidates": [],
                "ai_used": False,
            }
        candidates = self.candidates.retrieve(
            event,
            normalized,
            deterministic.get("alternative_candidates"),
            mode="Preview",
            limit=config.max_candidates,
        )
        if not candidates:
            return {
                **base,
                "classification_status": "unresolved",
                "primary_match": None,
                "match_method": "Unresolved",
                "confidence": 0,
                "requires_review": True,
                "review_reason": "No approved SMCS candidate",
                "evidence_phrases": [],
                "alternative_candidates": [],
                "ai_used": False,
            }
        result = self.ai.classify(
            event,
            normalized,
            candidates,
            config,
            user=user,
            conversation_id=conversation_id,
        )
        primary = result.get("primary_match")
        return {
            **base,
            **result,
            "match_method": "AI Semantic Classification" if primary else "Unresolved",
            "confidence": int(primary.get("confidence") or 0) if primary else 0,
            "evidence_phrases": primary.get("evidence_phrases", []) if primary else [],
            "ai_used": True,
            "candidate_list": candidates,
        }

    def representative_sample(self, events: list[dict], limit: int) -> list[dict]:
        commented = [item for item in events if str(item.get("Comment") or "").strip()]
        buckets = [
            lambda text: "smcs" in text.casefold(),
            lambda text: any(term in text.casefold() for term in ("no defect", "found ok", "ruled out")),
            lambda text: any(term in text.casefold() for term in ("waiting", "part", "warehouse")),
            lambda text: len(text.split()) <= 3,
            lambda text: any(term in text.casefold() for term in ("replaced", "repaired", "failure", "leak")),
        ]
        selected, seen = [], set()
        for predicate in buckets:
            for event in commented:
                event_id = str(event.get("Event ID"))
                if event_id not in seen and predicate(str(event.get("Comment") or "")):
                    selected.append(event)
                    seen.add(event_id)
                    break
        for event in sorted(commented, key=lambda item: -float(item.get("Duration") or 0)):
            if len(selected) >= limit:
                break
            event_id = str(event.get("Event ID"))
            if event_id not in seen:
                selected.append(event)
                seen.add(event_id)
        return selected[:limit]

    def run_preview_job(self, job_id) -> SMCSClassificationJob:
        close_old_connections()
        job = SMCSClassificationJob.objects.select_related("explorer_session").get(pk=job_id)
        config = self.config()
        job.status = "Processing"
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
        try:
            events = load_events(job.explorer_session, limit=500)["rows"]
            sample = self.representative_sample(events, min(config.default_batch_size, 50))
            job.total_events = len(sample)
            job.save(update_fields=["total_events"])
            results = []
            for event in sample:
                try:
                    result = self.classify_event_preview(
                        event,
                        config,
                        user=job.user,
                        conversation_id=(
                            job.explorer_session.conversation.conversation_id
                            if job.explorer_session.conversation else ""
                        ),
                    )
                    results.append(result)
                    job.deterministic_matches += int(
                        result["match_method"] in {"Explicit SMCS Code", "Exact Description", "Synonym Match"}
                    )
                    job.ai_matches += int(result.get("ai_used") and result.get("primary_match") is not None)
                    status = result["classification_status"]
                    job.matched_events += int(status == "matched")
                    job.probable_events += int(status == "probable")
                    job.unresolved_events += int(status == "unresolved")
                except Exception as exc:
                    results.append({
                        "event_id": event.get("Event ID"),
                        "comment": event.get("Comment"),
                        "classification_status": "failed",
                        "requires_review": True,
                        "review_reason": str(exc),
                        "preview_only": True,
                        "ai_used": True,
                    })
                    job.failed_events += 1
                job.processed_events += 1
                job.save(update_fields=[
                    "processed_events", "matched_events", "probable_events",
                    "unresolved_events", "failed_events", "deterministic_matches", "ai_matches",
                ])
            total_hours = sum(float(item.get("downtime_hours") or 0) for item in results)
            matched_hours = sum(
                float(item.get("downtime_hours") or 0)
                for item in results if item.get("primary_match")
            )
            usage_logs = OpenAIUsageLog.objects.filter(
                user=job.user,
                feature="SMCS Comment Classification",
                usage_timestamp__gte=job.started_at,
            )
            usage_input = sum(item.input_tokens for item in usage_logs)
            usage_output = sum(item.output_tokens for item in usage_logs)
            usage_cost = sum(
                (item.estimated_cost or Decimal("0")) for item in usage_logs
            )
            job.result_json = {
                "mode": "Preview",
                "official_classifications_written": 0,
                "results": results,
                "comparison": {
                    "sample_events": len(results),
                    "deterministic_matches": job.deterministic_matches,
                    "hybrid_matches": sum(bool(item.get("primary_match")) for item in results),
                    "high_confidence_rate": round(
                        sum(int(item.get("confidence") or 0) >= config.auto_accept_threshold for item in results)
                        / len(results) * 100 if results else 0, 2
                    ),
                    "review_rate": round(
                        sum(bool(item.get("requires_review")) for item in results)
                        / len(results) * 100 if results else 0, 2
                    ),
                    "unresolved_rate": round(
                        sum(item.get("classification_status") == "unresolved" for item in results)
                        / len(results) * 100 if results else 0, 2
                    ),
                    "downtime_hour_coverage": round(
                        matched_hours / total_hours * 100 if total_hours else 0, 2
                    ),
                    "estimated_ai_calls": sum(bool(item.get("ai_used")) for item in results),
                    "actual_api_calls": usage_logs.count(),
                    "input_tokens": usage_input,
                    "output_tokens": usage_output,
                    "estimated_cost": round(float(usage_cost), 6),
                },
            }
            job.estimated_cost = Decimal(str(job.result_json["comparison"]["estimated_cost"]))
            job.status = "Partially Completed" if job.failed_events else "Completed"
        except Exception as exc:
            job.status = "Failed"
            job.error_message = str(exc)
        job.completed_at = timezone.now()
        job.save()
        close_old_connections()
        return job

    def start_preview(self, *, user, session) -> SMCSClassificationJob:
        config = self.config()
        feature_mode = os.getenv(
            "ENABLE_AI_SMCS_CLASSIFICATION",
            config.execution_mode,
        ).strip()
        if feature_mode not in {"Preview", "Admin Only", "Production"}:
            raise ValueError("AI SMCS classification is disabled.")
        existing = SMCSClassificationJob.objects.filter(
            user=user,
            explorer_session=session,
            mode="Preview",
            status__in=["Pending", "Processing"],
        ).first()
        if existing:
            return existing
        reusable = SMCSClassificationJob.objects.filter(
            user=user,
            explorer_session=session,
            mode="Preview",
            status__in=["Completed", "Partially Completed"],
            created_at__gte=timezone.now() - timedelta(minutes=30),
        ).order_by("-created_at").first()
        if reusable:
            return reusable
        job = SMCSClassificationJob.objects.create(
            user=user,
            explorer_session=session,
            mode="Preview",
        )
        thread = threading.Thread(target=self.run_preview_job, args=(job.id,), daemon=True)
        thread.start()
        return job


def serialize_preview_job(job: SMCSClassificationJob) -> dict:
    return {
        "job_id": str(job.id),
        "mode": job.mode,
        "status": job.status,
        "total_events": job.total_events,
        "processed_events": job.processed_events,
        "matched_events": job.matched_events,
        "probable_events": job.probable_events,
        "unresolved_events": job.unresolved_events,
        "failed_events": job.failed_events,
        "deterministic_matches": job.deterministic_matches,
        "ai_matches": job.ai_matches,
        "result": job.result_json,
        "error": job.error_message,
        "preview_only": True,
    }
