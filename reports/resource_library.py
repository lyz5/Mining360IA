import base64
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.urls import reverse


RESOURCE_ROOT = settings.BASE_DIR / "res" / "bp"
TEXT_EXTENSIONS = {".txt", ".csv", ".log", ".md"}
INLINE_EXTENSIONS = {".pdf", *TEXT_EXTENSIONS}
SKIPPED_RESOURCE_DIR_PREFIXES = ("_pdf_text_index",)


@dataclass(frozen=True)
class ResourceFile:
    id: str
    title: str
    filename: str
    extension: str
    section: str
    category: str
    level: str
    folder_path: str
    relative_path: str
    size: int
    size_label: str
    mime_type: str
    view_url: str
    raw_url: str
    is_pdf: bool
    is_text: bool


def clean_label(value: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", value).strip()


def safe_path_part(value: str, fallback: str = "General") -> str:
    cleaned = clean_label(str(value or "").strip()) or fallback
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def infer_root_category(title: str) -> tuple[str, str, str]:
    normalized = title.lower()
    rules = [
        (
            ("haul road", "operator", "payload", "mine site", "productivity", "video overlay"),
            "Application",
            "Productivity Analysis",
            "Tactical",
        ),
        (
            ("safety", "live work", "hsec"),
            "Maintenance & Repair",
            "HSEC - M&R",
            "Quick Win",
        ),
        (
            ("backlog",),
            "Maintenance & Repair",
            "Backlog Management",
            "Tactical",
        ),
        (
            ("planning", "roadmap", "nmi"),
            "Maintenance & Repair",
            "Planning & Scheduling",
            "Strategic",
        ),
        (
            ("condition", "diagnostic", "failure analysis", "monitor", "mtbf", "fluid cleanliness", "oil patch", "availability", "downtime"),
            "Maintenance & Repair",
            "Condition Monitoring",
            "Tactical",
        ),
        (
            ("pm ", "preventive", "filter", "cooling", "temperature", "oil drain", "air filters", "fuel filter"),
            "Maintenance & Repair",
            "Preventive Maintenance",
            "Quick Win",
        ),
        (
            ("component", "cylinder", "liner", "engine", "transmission", "final drive", "spindle", "pump", "camshaft", "brake"),
            "Component Life Management",
            "Removal & Installation",
            "Quick Win",
        ),
        (
            ("salvage", "metal spray", "honing", "lathe"),
            "Component Rebuild (CRC)",
            "Salvage Processes (Shop)",
            "Quick Win",
        ),
        (
            ("tool", "fixture", "apparatus", "stand", "wrench", "installation", "removal", "disassembly", "handling"),
            "Component Rebuild (CRC)",
            "Facility & Tooling",
            "Quick Win",
        ),
    ]
    for keywords, section, category, level in rules:
        if any(keyword in normalized for keyword in keywords):
            return section, category, level
    return "General Best Practices", "General", "General"


def classify_resource(relative_path: Path) -> tuple[str, str, str, str]:
    parts = relative_path.parts
    folder_path = relative_path.parent.as_posix()
    if folder_path == ".":
        folder_path = "Best Practice Maintenance and Repair"

    if len(parts) == 1:
        section, category, level = infer_root_category(relative_path.stem)
        return section, category, level, folder_path

    section = clean_label(parts[0])
    category = clean_label(parts[1]) if len(parts) >= 3 else "General"
    level = clean_label(parts[2]) if len(parts) >= 4 else "General"
    return section, category, level, folder_path


def encode_resource_id(relative_path: Path) -> str:
    value = relative_path.as_posix().encode("utf-8")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_resource_id(resource_id: str) -> Path:
    padding = "=" * (-len(resource_id) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{resource_id}{padding}").decode("utf-8")
    except Exception as exc:
        raise ValueError("Invalid resource id") from exc
    relative_path = Path(decoded)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Invalid resource path")
    return relative_path


def get_resource_path(resource_id: str) -> Path:
    relative_path = decode_resource_id(resource_id)
    path = (RESOURCE_ROOT / relative_path).resolve()
    root = RESOURCE_ROOT.resolve()
    if root not in path.parents and path != root:
        raise ValueError("Resource path outside library")
    if not path.is_file():
        raise FileNotFoundError("Resource file not found")
    return path


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def build_resource(path: Path) -> ResourceFile:
    relative_path = path.relative_to(RESOURCE_ROOT)
    resource_id = encode_resource_id(relative_path)
    extension = path.suffix.lower() or "file"
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    section, category, level, folder_path = classify_resource(relative_path)

    return ResourceFile(
        id=resource_id,
        title=path.stem,
        filename=path.name,
        extension=extension.lstrip(".").upper(),
        section=section,
        category=category,
        level=level,
        folder_path=folder_path,
        relative_path=relative_path.as_posix(),
        size=path.stat().st_size,
        size_label=format_size(path.stat().st_size),
        mime_type=mime_type,
        view_url=reverse("resource-detail", args=[resource_id]),
        raw_url=reverse("resource-file", args=[resource_id]),
        is_pdf=extension == ".pdf",
        is_text=extension in TEXT_EXTENSIONS,
    )


def is_skipped_resource_path(path: Path) -> bool:
    relative_path = path.relative_to(RESOURCE_ROOT)
    return bool(relative_path.parts) and relative_path.parts[0].startswith(SKIPPED_RESOURCE_DIR_PREFIXES)


def list_resources(
    query: str = "",
    section: str = "",
    category: str = "",
    level: str = "",
) -> list[ResourceFile]:
    if not RESOURCE_ROOT.exists():
        return []

    normalized_query = query.strip().lower()
    resources = []
    for path in RESOURCE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if is_skipped_resource_path(path):
            continue
        if path.suffix.lower() not in INLINE_EXTENSIONS:
            continue

        resource = build_resource(path)
        if section and resource.section != section:
            continue
        if category and resource.category != category:
            continue
        if level and resource.level != level:
            continue
        search_blob = (
            f"{resource.title} {resource.filename} {resource.section} "
            f"{resource.category} {resource.level} {resource.folder_path} {resource.extension}"
        ).lower()
        if normalized_query and normalized_query not in search_blob:
            continue
        resources.append(resource)

    return sorted(
        resources,
        key=lambda item: (item.section.lower(), item.category.lower(), item.level.lower(), item.title.lower()),
    )


def list_resource_facets() -> dict:
    resources = list_resources()
    sections = sorted({item.section for item in resources})
    return {
        "sections": sections,
        "categories": sorted({item.category for item in resources}),
        "levels": sorted({item.level for item in resources}),
        "section_cards": [
            {
                "name": section,
                "count": sum(1 for item in resources if item.section == section),
            }
            for section in sections
        ],
    }


def get_resource(resource_id: str) -> ResourceFile:
    return build_resource(get_resource_path(resource_id))


def read_text_resource(path: Path, limit: int = 500_000) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit)


def save_uploaded_resource(uploaded_file, *, title: str, section: str, category: str, level: str) -> ResourceFile:
    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in INLINE_EXTENSIONS:
        allowed = ", ".join(sorted(INLINE_EXTENSIONS))
        raise ValueError(f"Unsupported file type. Allowed extensions: {allowed}.")

    RESOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    section_part = safe_path_part(section, "User Uploads")
    category_part = safe_path_part(category, "General")
    level_part = safe_path_part(level, "General")
    target_dir = RESOURCE_ROOT / section_part / category_part / level_part
    target_dir.mkdir(parents=True, exist_ok=True)

    title_part = safe_path_part(title or Path(uploaded_file.name).stem, Path(uploaded_file.name).stem or "Document")
    target = target_dir / f"{title_part}{extension}"
    suffix = 2
    while target.exists():
        target = target_dir / f"{title_part}_{suffix}{extension}"
        suffix += 1

    with target.open("wb") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)

    return build_resource(target)
