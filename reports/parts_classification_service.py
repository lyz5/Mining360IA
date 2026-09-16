from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from pyxlsb import open_workbook

from .models import PartClassificationReference, PartsClassificationImportRun, PartsMajorClassReference


MAJOR_CLASSES = {
    "1": "UNDERCARRIAGE",
    "2": "ENGINE",
    "3": "GROUND ENGAGING TOOLS",
    "5": "DRIVE TRAIN AND STEERING PARTS",
    "6": "HYDRAULICS",
    "7": "FILTERS AND FLUIDS",
    "8": "ELECTRONICS & ELECTRICAL COMPONENTS",
    "9": "STRUCTURAL, APPEARANCE, AND OTHER PARTS",
}
UPDATE_FIELDS = (
    "part_number", "major_class", "minor_class", "ppc", "classification_status",
    "conflict_variants_json", "source_sheet", "source_row_number", "source_hash",
    "active", "import_run", "source_last_seen_at",
)


def _text(value):
    return str(value or "").strip()


def _part_key(value):
    return "".join(character for character in _text(value).upper() if character.isalnum())


def _header(value):
    normalized = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(normalized.casefold().split())


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PartsClassificationImportService:
    BATCH_SIZE = 4000

    @classmethod
    def import_file(cls, path, *, user=None):
        source_path = Path(path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Parts classification file not found: {source_path}")
        run = PartsClassificationImportRun.objects.create(source_file_name=source_path.name, imported_by=user)
        now = timezone.now()
        counters = Counter()
        major_counts = Counter()
        warnings = []
        try:
            with transaction.atomic(), open_workbook(str(source_path)) as workbook:
                major_objects = {}
                for order, (code, description) in enumerate(MAJOR_CLASSES.items(), start=1):
                    item, _ = PartsMajorClassReference.objects.update_or_create(
                        code=code,
                        defaults={"description": description, "display_order": order, "active": True},
                    )
                    major_objects[code] = item

                for sheet_name in workbook.sheets:
                    with workbook.get_sheet(sheet_name) as sheet:
                        rows = sheet.rows()
                        headers = [_header(cell.v) for cell in next(rows)]
                        index = {name: position for position, name in enumerate(headers)}
                        required = {"reference jad", "major class", "minor class", "ppc"}
                        missing = required - set(index)
                        if missing:
                            raise ValueError(
                                f"Sheet {sheet_name} is missing columns: {', '.join(sorted(missing))}"
                            )
                        batch = []
                        for row_number, row in enumerate(rows, start=2):
                            values = [cell.v for cell in row]
                            counters["read"] += 1
                            part_number = _text(values[index["reference jad"]] if index["reference jad"] < len(values) else "")
                            normalized = _part_key(part_number)
                            if not normalized:
                                counters["blank"] += 1
                                continue
                            major = _text(values[index["major class"]] if index["major class"] < len(values) else "")
                            minor = _text(values[index["minor class"]] if index["minor class"] < len(values) else "").upper()
                            ppc = _text(values[index["ppc"]] if index["ppc"] < len(values) else "").upper()
                            major_counts[major or "Blank"] += 1
                            batch.append({
                                "part_number": part_number,
                                "normalized_part_number": normalized,
                                "major": major,
                                "minor": minor,
                                "ppc": ppc,
                                "sheet": sheet_name,
                                "row": row_number,
                            })
                            if len(batch) >= cls.BATCH_SIZE:
                                cls._persist_batch(batch, run, now, major_objects, counters)
                                batch = []
                        if batch:
                            cls._persist_batch(batch, run, now, major_objects, counters)

                counters["deactivated"] = PartClassificationReference.objects.filter(active=True).exclude(
                    import_run=run
                ).update(active=False)
                conflict_count = PartClassificationReference.objects.filter(
                    active=True, classification_status="Conflict"
                ).count()
                unknown = sorted(set(major_counts) - set(MAJOR_CLASSES) - {"Blank"})
                if unknown:
                    warnings.append("Unknown Major Class codes: " + ", ".join(unknown))
                if counters["blank"]:
                    warnings.append(f"{counters['blank']} source rows have no part number.")
                if conflict_count:
                    warnings.append(f"{conflict_count} part numbers have conflicting classifications and are excluded from automatic analysis.")

                run.status = "Completed with Warnings" if warnings else "Completed"
                run.source_file_hash = _file_hash(source_path)
                run.source_sheets_json = list(workbook.sheets)
                run.records_read = counters["read"]
                run.records_created = counters["created"]
                run.records_updated = counters["updated"]
                run.records_unchanged = counters["unchanged"]
                run.records_deactivated = counters["deactivated"]
                run.conflict_count = conflict_count
                run.major_class_counts_json = dict(major_counts)
                run.warnings_json = warnings
                run.completed_at = timezone.now()
                run.save()
            return run
        except Exception as exc:
            run.status = "Failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
            raise

    @classmethod
    def _persist_batch(cls, rows, run, now, major_objects, counters):
        grouped = {}
        for row in rows:
            entry = grouped.setdefault(row["normalized_part_number"], {"latest": row, "variants": set()})
            entry["variants"].add((row["major"], row["minor"], row["ppc"]))
            entry["latest"] = row
        existing = {
            item.normalized_part_number: item
            for item in PartClassificationReference.objects.filter(normalized_part_number__in=grouped)
        }
        creates = []
        updates = []
        for key, entry in grouped.items():
            row = entry["latest"]
            variants = set(entry["variants"])
            item = existing.get(key)
            if item and item.classification_status == "Conflict":
                variants.update(tuple(value) for value in item.conflict_variants_json)
            elif item:
                variants.add((item.major_class_id or "", item.minor_class, item.ppc))
            conflict = len(variants) > 1
            payload = {
                "part_number": row["part_number"],
                "major_class": None if conflict else major_objects.get(row["major"]),
                "minor_class": "" if conflict else row["minor"],
                "ppc": "" if conflict else row["ppc"],
                "classification_status": "Conflict" if conflict else "Classified",
                "conflict_variants_json": [list(value) for value in sorted(variants)] if conflict else [],
                "source_sheet": row["sheet"],
                "source_row_number": row["row"],
                "active": True,
            }
            hash_payload = dict(payload)
            hash_payload["major_class"] = getattr(payload["major_class"], "code", "")
            payload["source_hash"] = _hash(hash_payload)
            if item is None:
                creates.append(PartClassificationReference(
                    normalized_part_number=key, import_run=run, source_last_seen_at=now, **payload
                ))
                counters["created"] += 1
            else:
                changed = item.source_hash != payload["source_hash"] or not item.active
                for field, value in payload.items():
                    setattr(item, field, value)
                item.import_run = run
                item.source_last_seen_at = now
                updates.append(item)
                counters["updated" if changed else "unchanged"] += 1
        PartClassificationReference.objects.bulk_create(creates, batch_size=cls.BATCH_SIZE)
        PartClassificationReference.objects.bulk_update(updates, UPDATE_FIELDS, batch_size=cls.BATCH_SIZE)
