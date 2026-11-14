"""Transparent review criteria, not a certified CAT classification or writeback."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata

VERSION = "2026-10-26.1"
EMPTY = {"", "(vide)", "(vides)", "none", "null", "n/a", "na", "not available"}
KINDS = {"missing": "Missing fields", "invalid": "Invalid data", "mismatch": "Possible mismatch", "review": "Needs clarification"}


def normal(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return re.sub(r"\s+", " ", "".join(c for c in value if not unicodedata.combining(c))).strip()


def missing(value):
    return normal(value) in EMPTY


def number(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def timestamp(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def evidence(row):
    result = {}
    for key in ("event_id", "yearmonth", "minesite", "serial_number", "model", "labour_type", "description_cat", "comment", "work_type", "downtime_hours", "start_hours", "end_hours"):
        value = row.get(key)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)
        if key == "comment":
            value = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email removed]", str(value or ""), flags=re.I)
            value = re.sub(r"(?<!\w)\+\d[\d ()-]{7,}\d(?!\w)", "[phone removed]", value)
        result[key] = value
    return result


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def check(row):
    result = []

    def add(code, kind, title, reason, recommendation=""):
        result.append({"rule_code": code, "kind": kind, "title": title, "reason": reason, "recommendation": recommendation})

    for field, label in (("labour_type", "Labour Type"), ("description_cat", "Description CAT"), ("comment", "Comment"), ("minesite", "MineSite"), ("serial_number", "Serial number")):
        if missing(row.get(field)):
            add("missing_" + field, "missing", label + " missing", "The field is blank or contains an empty-value marker.", "Complete it in MiningProd from the maintenance record, then Recheck.")
    hours = number(row.get("downtime_hours"))
    if hours is None:
        add("invalid_hours", "invalid", "Hours unavailable or invalid", "DowntimeHours is missing or is not a finite number.")
    elif hours < 0:
        add("negative_hours", "invalid", "Negative downtime hours", "DowntimeHours is below zero.")
    # A genuine zero is preserved. It is not automatically an error.
    start, end = timestamp(row.get("start_hours")), timestamp(row.get("end_hours"))
    if start and end and start.tzinfo == end.tzinfo and end < start:
        add("reversed_dates", "invalid", "End precedes start", "End Hours is earlier than Start Hours.")
    lab, cat, comment = normal(row.get("labour_type")), normal(row.get("description_cat")), normal(row.get("comment"))
    hydraulic = cat.startswith("hydraulic system (")
    if lab.startswith("1250 ") and cat == "power train":
        add("fuel_power_train", "mismatch", "Fuel / Power Train", "Labour Type identifies the fuel system but Description CAT is Power Train.", "Review Fuel System against the actual cause; this is a suggestion, not an approved mapping.")
    if lab.startswith("2500 ") and cat == "power train":
        add("dust_power_train", "mismatch", "Dust suppression / Power Train", "Dust-suppression equipment is assigned to Power Train.", "Review the water/dust-suppression circuit. Do not assume an auxiliary water pump is engine cooling.")
    if lab == "grease system" and hydraulic:
        add("grease_hydraulics", "mismatch", "Greasing / Hydraulic System", "Greasing and hydraulics have distinct available categories.", "Review Lubrication/Auto lube system against the comment and repair record.")
    if lab == "attachment" and cat == "fire suppression":
        add("attachment_fire", "mismatch", "Attachment / Fire Suppression", "The component families differ.", "If the comment confirms Ansul/fire suppression, review Labour Type rather than changing Description CAT.")
    if lab == "drive train" and cat == "steering system":
        add("drive_steering", "mismatch", "Drive train / Steering", "The two fields identify different component systems.", "Use the comment to determine which field needs correction.")
    if lab in {"carosserie", "carrosserie"} and cat == "hydraulic cylinder":
        add("body_cylinder", "mismatch", "Body / Hydraulic Cylinder", "The two fields identify different component families.", "Review Labour Type if the repair record confirms a cylinder fault.")
    if lab.startswith("material desgaste") and cat == "lubrication/auto lube system" and re.search(r"pompe.{0,20}graiss|grease pump", comment):
        add("wear_grease", "mismatch", "Wear material / Lubrication", "The comment identifies a grease-pump problem, while Labour Type identifies wear material.", "Review Labour Type against the repair record.")
    if lab.startswith("2000 ") and cat == "power train":
        add("drill_power_train", "review", "Drilling / Power Train", "This broad mapping may mix controls, rotation heads and other drilling components.", "Confirm subsystem definitions; not every drilling event is necessarily misclassified.")
    if lab.startswith("1000 ") and cat == "fire suppression":
        add("power_fire", "review", "Power system / Fire Suppression", "This combination may refer to an Ansul installation or to the cause of a fire.", "Review the cause and Labour Type before changing either field.")
    if lab == "caterpillar check" and cat == "opportune maint overrun":
        add("inspection_overrun", "review", "Inspection / Maintenance overrun", "An inspection alone does not establish that the planned maintenance window was exceeded.", "Confirm the planned window and actual work; the comment alone is insufficient.")
    if lab.startswith("driveline /") and cat == "undercarriage":
        add("driveline_tracks", "review", "Driveline / Undercarriage", "This may be a site-specific translation or grouping convention.", "Confirm the convention; track-related comments may support the existing Description CAT.")
    return result
