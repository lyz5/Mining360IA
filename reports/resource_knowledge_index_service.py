from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import threading
from pathlib import Path

from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import (
    ResourceKnowledgeChunk,
    ResourceKnowledgeConfiguration,
    ResourceKnowledgeDocument,
    ResourceKnowledgeIndexRun,
    ResourceKnowledgeItem,
    ResourceKnowledgeSection,
)
from .resource_knowledge_ai_service import (
    create_embedding,
    embedding_model,
    extract_chunk_knowledge,
    extraction_model,
    extraction_reasoning_effort,
)
from .resource_knowledge_extraction_service import (
    PARSER_VERSION,
    build_chunks,
    file_sha256,
    normalize_extracted_text,
    normalized_search_text,
    parse_resource_document,
)
from .resource_library import (
    RESOURCE_ROOT,
    ResourceFile,
    get_resource,
    get_resource_path,
    list_best_practice_resources,
)


def _source_modified(path: Path):
    return timezone.datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.get_current_timezone())


def _manifest_records() -> dict[str, dict]:
    path = RESOURCE_ROOT / "_pdf_text_index" / "manifest.csv"
    if not path.exists():
        return {}
    result: dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            key = str(row.get("relative_path") or "").replace("\\", "/").casefold()
            try:
                result[key] = {
                    "text_chars": int(row.get("text_chars") or 0),
                    "pages": int(row.get("pages") or 0),
                    "status": str(row.get("status") or ""),
                }
            except (TypeError, ValueError):
                result[key] = {"text_chars": 0, "pages": 0, "status": "error"}
    return result


def _manifest_character_counts() -> dict[str, int]:
    return {
        key: int(value.get("text_chars") or 0)
        for key, value in _manifest_records().items()
    }


def _configuration() -> ResourceKnowledgeConfiguration:
    config, _ = ResourceKnowledgeConfiguration.objects.get_or_create(
        name="Best Practices Bootstrap",
    )
    return config


def preview_library(
    *,
    with_ai: bool = False,
    with_embeddings: bool = False,
    resource_id: str = "",
    category: str = "",
    only_new: bool = False,
    limit: int | None = None,
) -> dict:
    resources = [get_resource(resource_id)] if resource_id else list_best_practice_resources()
    if category:
        resources = [
            item for item in resources
            if item.category.casefold() == category.casefold()
            or item.section.casefold() == category.casefold()
        ]
    if limit:
        resources = resources[:max(0, int(limit))]
    existing = {
        item.relative_path.casefold(): item
        for item in ResourceKnowledgeDocument.objects.all()
    }
    manifest_records = _manifest_records()
    manifest = {
        key: int(value.get("text_chars") or 0)
        for key, value in manifest_records.items()
    }
    create_count = update_count = unchanged_count = 0
    estimated_chunks = 0
    examples = []
    total_pages = 0
    sizes: dict[int, int] = {}
    for resource in resources:
        path = get_resource_path(resource.id)
        sizes[path.stat().st_size] = sizes.get(path.stat().st_size, 0) + 1
        total_pages += int(
            (manifest_records.get(resource.relative_path.casefold()) or {}).get("pages") or 1
        )
        current = existing.get(resource.relative_path.casefold())
        modified = _source_modified(path)
        metadata = current.metadata_json if current else {}
        configuration_matches = bool(
            metadata.get("parser_version") == PARSER_VERSION
            and metadata.get("processing_mode") == "Deterministic Bootstrap"
        )
        unchanged = bool(
            current
            and current.file_size == path.stat().st_size
            and current.source_updated_at
            and abs((current.source_updated_at - modified).total_seconds()) < 1
            and current.status == "Indexed"
            and configuration_matches
        )
        action = "skip" if unchanged else ("update" if current else "create")
        if only_new and action != "create":
            continue
        if action == "create":
            create_count += 1
        elif action == "update":
            update_count += 1
        else:
            unchanged_count += 1
        chars = manifest.get(resource.relative_path.casefold(), max(path.stat().st_size // 3, 1))
        chunk_estimate = max(1, math.ceil(chars / 3_800)) if action != "skip" else 0
        estimated_chunks += chunk_estimate
        if action != "skip" and len(examples) < 20:
            examples.append({
                "resource_id": resource.id,
                "title": resource.title,
                "action": action,
                "estimated_chunks": chunk_estimate,
            })
    return {
        "mode": "Preview",
        "documents": len(resources),
        "create": create_count,
        "update": update_count,
        "skip": unchanged_count,
        "estimated_chunks": estimated_chunks,
        "pages": total_pages,
        "estimated_sections": estimated_chunks,
        "tables_found": 0,
        "images_found": 0,
        "potential_duplicates": sum(count - 1 for count in sizes.values() if count > 1),
        "potential_conflicts": 0,
        "supported_files": len(resources),
        "unsupported_files": 0,
        "new_versions": update_count,
        "ocr_required": sum(
            1 for resource in resources
            if manifest.get(resource.relative_path.casefold(), 1) == 0
        ),
        "estimated_embedding_calls": 0,
        "estimated_extraction_calls": 0,
        "expected_openai_calls": 0,
        "expected_api_cost": 0,
        "extraction_model": "Local deterministic parsers",
        "reasoning_effort": "Not applicable",
        "embedding_model": "Disabled",
        "processing_mode": "Deterministic Bootstrap",
        "examples": examples,
    }


def _knowledge_key(document, chunk, item: dict) -> str:
    stable = json.dumps({
        "resource": document.resource_id,
        "chunk": chunk.content_hash,
        "title": item.get("title"),
        "component": item.get("component"),
        "symptom": item.get("symptom"),
        "recommendations": item.get("recommendations"),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


RECOMMENDATION_PATTERN = re.compile(
    r"\b(must|should|shall|recommended|recommend|ensure|avoid|inspect|review|verify|check|maintain|monitor)\b",
    re.IGNORECASE,
)


def _deterministic_recommendations(content: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", normalize_extracted_text(content))
    return [
        sentence.strip()
        for sentence in sentences
        if 20 <= len(sentence.strip()) <= 700 and RECOMMENDATION_PATTERN.search(sentence)
    ][:20]


def _save_deterministic_knowledge(document, chunk) -> int:
    recommendations = _deterministic_recommendations(chunk.content)
    item = {
        "title": chunk.heading or f"{document.title} · page {chunk.page_start or 1}",
        "component": "",
        "symptom": "",
        "recommendations": recommendations,
    }
    key = _knowledge_key(document, chunk, item)
    existing = ResourceKnowledgeItem.objects.filter(knowledge_key=key).first()
    if existing and existing.validation_status == "Validated":
        return 0
    defaults = {
        "document": document,
        "chunk": chunk,
        "title": item["title"][:1000],
        "business_domain": document.section[:255],
        "best_practices": recommendations,
        "recommendations": recommendations,
        "source_excerpt": chunk.content[:4000],
        "source_page": chunk.page_start,
        "confidence": 85 if recommendations else 70,
        "extraction_source": "Best Practice Resource",
        "validation_status": "To Review",
        "validation_notes": (
            "Created by deterministic local parsing. Review the source excerpt "
            "before validation."
        ),
        "is_active": True,
    }
    _, created = ResourceKnowledgeItem.objects.update_or_create(
        knowledge_key=key,
        defaults=defaults,
    )
    return int(created)


def _save_knowledge(document, chunk, result: dict) -> int:
    created = 0
    if result.get("document_version") and not document.document_version:
        document.document_version = str(result["document_version"])[:80]
        document.save(update_fields=["document_version", "updated_at"])
    for item in result.get("knowledge_items") or []:
        key = _knowledge_key(document, chunk, item)
        defaults = {
            "document": document,
            "chunk": chunk,
            "title": str(item.get("title") or document.title)[:1000],
            "business_domain": str(item.get("business_domain") or document.section)[:255],
            "equipment": str(item.get("equipment") or "")[:500],
            "equipment_model": str(item.get("equipment_model") or "")[:255],
            "system": str(item.get("system") or "")[:500],
            "component": str(item.get("component") or "")[:500],
            "subcomponent": str(item.get("subcomponent") or "")[:500],
            "symptom": str(item.get("symptom") or ""),
            "failure_mode": str(item.get("failure_mode") or ""),
            "fault_codes": item.get("fault_codes") or [],
            "probable_causes": item.get("probable_causes") or [],
            "occurrence_conditions": str(item.get("occurrence_conditions") or ""),
            "possible_impacts": str(item.get("possible_impacts") or ""),
            "inspection_procedure": str(item.get("inspection_procedure") or ""),
            "troubleshooting_procedure": str(item.get("troubleshooting_procedure") or ""),
            "best_practices": item.get("best_practices") or [],
            "recommendations": item.get("recommendations") or [],
            "safety_instructions": item.get("safety_instructions") or [],
            "criticality": str(item.get("criticality") or ""),
            "source_excerpt": str(item.get("source_excerpt") or "")[:4000],
            "source_page": chunk.page_start,
            "confidence": max(0, min(float(item.get("confidence") or 0), 100)),
            "extraction_source": "AI Generated",
            "validation_status": "To Review",
            "is_active": True,
        }
        _, was_created = ResourceKnowledgeItem.objects.update_or_create(
            knowledge_key=key,
            defaults=defaults,
        )
        created += int(was_created)
    return created


def index_resource(
    resource: ResourceFile,
    *,
    user=None,
    with_ai: bool = False,
    with_embeddings: bool = False,
    force: bool = False,
) -> dict:
    path = get_resource_path(resource.id)
    source_modified = _source_modified(path)
    digest = file_sha256(path)
    document, _ = ResourceKnowledgeDocument.objects.get_or_create(
        relative_path=resource.relative_path,
        defaults={
            "resource_id": resource.id,
            "title": resource.title,
            "filename": resource.filename,
            "file_hash": digest,
        },
    )
    config = _configuration()
    metadata = document.metadata_json or {}
    configuration_matches = bool(
        metadata.get("parser_version") == PARSER_VERSION
        and metadata.get("processing_config_version") == config.parser_config_version
        and metadata.get("processing_mode") == "Deterministic Bootstrap"
    )
    if (
        not force
        and document.file_hash == digest
        and document.status == "Indexed"
        and configuration_matches
    ):
        return {"status": "skipped", "document_id": str(document.id), "chunks": 0, "knowledge": 0, "embeddings": 0}

    document.resource_id = resource.id
    document.title = resource.title
    document.filename = resource.filename
    document.section = resource.section
    document.category = resource.category
    document.level = resource.level
    document.file_hash = digest
    document.file_size = path.stat().st_size
    document.mime_type = resource.mime_type
    document.source_updated_at = source_modified
    document.status = "Processing"
    document.parser_version = PARSER_VERSION
    document.processing_config_version = config.parser_config_version
    document.last_error = ""
    document.is_active = True
    document.save()

    parsed = parse_resource_document(path)
    if parsed.ocr_required and not config.enable_resource_ocr:
        raise ValueError("Skipped — OCR Required")
    chunks = build_chunks(
        parsed.pages,
        sections=parsed.sections,
        tables=parsed.tables if config.preserve_tables else [],
        maximum_tokens=config.maximum_chunk_tokens,
        minimum_tokens=config.minimum_chunk_tokens,
    )
    errors = []
    embeddings_created = knowledge_created = 0
    with transaction.atomic():
        document.knowledge_items.filter(is_active=True).exclude(
            validation_status="Validated",
        ).update(
            is_active=False,
            validation_notes="Source document changed; previous extraction retained for audit.",
        )
        document.chunks.all().delete()
        document.sections.all().delete()
        section_objects = ResourceKnowledgeSection.objects.bulk_create([
            ResourceKnowledgeSection(
                document=document,
                title=item.title[:1000],
                section_number=item.section_number[:80],
                level=item.level,
                page_start=item.page_start,
                page_end=item.page_end,
                sort_order=item.sort_order,
                content=item.content,
                normalized_content=normalized_search_text(item.content),
                validation_status="To Review",
            )
            for item in parsed.sections
        ])
        section_lookup = {
            (item.title, item.page_start): item
            for item in section_objects
        }
        chunk_objects = ResourceKnowledgeChunk.objects.bulk_create([
            ResourceKnowledgeChunk(
                document=document,
                section=section_lookup.get((item.heading, item.page_start)),
                chunk_index=item.index,
                page_start=item.page_start,
                page_end=item.page_end,
                heading=item.heading,
                heading_path=item.heading_path,
                chunk_type=item.chunk_type,
                content=item.content,
                normalized_content=normalized_search_text(item.content),
                source_reference=item.source_reference,
                language=parsed.language,
                content_hash=item.content_hash,
                character_count=len(item.content),
                token_count=item.token_count,
                embedding_status="Disabled",
                validation_status="To Review",
                extraction_metadata={
                    "source": parsed.parser_name,
                    "parser_version": parsed.parser_version,
                    "pages": [item.page_start, item.page_end],
                    "resource_id": resource.id,
                    "resource_title": resource.title,
                    "resource_category": "Best Practices",
                    "document_version": document.document_version,
                    "heading_path": item.heading_path,
                },
            )
            for item in chunks
        ])

    for chunk in chunk_objects:
        try:
            knowledge_created += _save_deterministic_knowledge(document, chunk)
        except Exception as exc:
            errors.append(f"Chunk {chunk.chunk_index}: {exc}")

    document.page_count = len(parsed.pages)
    document.section_count = len(section_objects)
    document.chunk_count = len(chunk_objects)
    document.knowledge_count = document.knowledge_items.filter(is_active=True).count()
    document.table_count = len(parsed.tables)
    document.image_count = len(parsed.visuals)
    document.parser_name = parsed.parser_name
    document.parser_version = parsed.parser_version
    document.language = parsed.language
    document.validation_status = (
        document.validation_status
        if document.validation_status == "Validated"
        else "To Review"
    )
    document.status = "Partial" if errors else "Indexed"
    document.indexed_at = timezone.now()
    document.last_error = "\n".join(errors[:20])
    document.metadata_json = {
        "processing_mode": "Deterministic Bootstrap",
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "processing_config_version": config.parser_config_version,
        "embedding_mode": config.embedding_mode,
        "openai_calls": 0,
        "api_cost": 0,
        "tables": len(parsed.tables),
        "visual_assets": len(parsed.visuals),
        "errors": len(errors),
    }
    document.save()
    return {
        "status": document.status,
        "document_id": str(document.id),
        "chunks": len(chunk_objects),
        "knowledge": knowledge_created,
        "embeddings": embeddings_created,
        "errors": errors,
    }


def run_index_job(run_id) -> None:
    close_old_connections()
    run = ResourceKnowledgeIndexRun.objects.get(pk=run_id)
    run.status = "Processing"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at", "updated_at"])
    options = run.result_json.get("options") or {}
    with_ai = False
    with_embeddings = False
    force = bool(options.get("force", False))
    resources = [get_resource(run.resource_id)] if run.resource_id else list_best_practice_resources()
    category = str(options.get("category") or "").strip()
    if category:
        resources = [
            item for item in resources
            if item.category.casefold() == category.casefold()
            or item.section.casefold() == category.casefold()
        ]
    if options.get("only_new"):
        existing_paths = {
            value.casefold()
            for value in ResourceKnowledgeDocument.objects.values_list("relative_path", flat=True)
        }
        resources = [
            item for item in resources
            if item.relative_path.casefold() not in existing_paths
        ]
    limit = int(options.get("limit") or 0)
    if limit > 0:
        resources = resources[:limit]
    run.total_documents = len(resources)
    run.save(update_fields=["total_documents", "updated_at"])
    failures = []
    for resource in resources:
        try:
            result = index_resource(
                resource,
                user=run.user,
                with_ai=with_ai,
                with_embeddings=with_embeddings,
                force=force,
            )
            if result["status"] == "skipped":
                run.skipped_documents += 1
            else:
                run.indexed_documents += 1
            run.chunks_created += result.get("chunks", 0)
            run.knowledge_created += result.get("knowledge", 0)
            run.embeddings_created += result.get("embeddings", 0)
        except Exception as exc:
            run.failed_documents += 1
            failures.append({"resource": resource.relative_path, "error": str(exc)})
        run.processed_documents += 1
        run.save()
    run.status = "Partially Completed" if failures else "Completed"
    run.completed_at = timezone.now()
    run.error_message = "\n".join(item["error"] for item in failures[:20])
    run.result_json = {**run.result_json, "failures": failures}
    run.save()
    close_old_connections()


def start_index_job(
    *,
    user=None,
    resource_id: str = "",
    with_ai: bool = False,
    with_embeddings: bool = False,
    force: bool = False,
    category: str = "",
    only_new: bool = False,
    limit: int = 0,
) -> ResourceKnowledgeIndexRun:
    run = ResourceKnowledgeIndexRun.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        scope="Document" if resource_id else "Library",
        resource_id=resource_id,
        result_json={
            "options": {
                "with_ai": False,
                "with_embeddings": False,
                "force": force,
                "category": category,
                "only_new": only_new,
                "limit": max(0, int(limit or 0)),
                "processing_mode": "Deterministic Bootstrap",
                "expected_openai_calls": 0,
                "expected_api_cost": 0,
            }
        },
    )
    thread = threading.Thread(target=run_index_job, args=(run.id,), daemon=True)
    thread.start()
    return run
