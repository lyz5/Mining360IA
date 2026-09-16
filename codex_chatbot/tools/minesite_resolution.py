from __future__ import annotations

from dataclasses import dataclass
import re

from reports.business_mapping_access_service import (
    authorized_minesite_names,
    filter_minesites_for_user,
)
from reports.business_mapping_normalization_service import normalize_business_name
from reports.models import EquipmentFleetAnalysis, MineSite, MineSiteAlias


@dataclass(frozen=True)
class MineSiteResolution:
    canonical_name: str | None
    semantic_name: str | None
    matched_alias: str | None
    match_method: str | None
    candidates: tuple[str, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


def _contains(normalized_question: str, normalized_candidate: str) -> bool:
    return bool(normalized_candidate) and f" {normalized_candidate} " in f" {normalized_question} "


def _authorized_fleet_names(user) -> list[str]:
    names = list(
        EquipmentFleetAnalysis.objects.filter(active=True)
        .exclude(site="")
        .values_list("site", flat=True)
        .distinct()
    )
    scope = authorized_minesite_names(user)
    if scope is None:
        return names
    allowed = {normalize_business_name(value) for value in scope}
    return [name for name in names if normalize_business_name(name) in allowed]


def resolve_minesite_from_question(question: str, *, user) -> MineSiteResolution | None:
    normalized_question = normalize_business_name(question)
    sites = list(filter_minesites_for_user(MineSite.objects.filter(active=True), user))
    sites_by_normalized = {site.normalized_minesite_name: site for site in sites}
    fleet_names = _authorized_fleet_names(user)
    fleet_by_normalized = {normalize_business_name(name): name for name in fleet_names}

    # Each lookup value maps to one or more canonical/semantic names. Multiple
    # destinations are retained so short names never select a site silently.
    lookup: dict[str, list[tuple[str, str, str]]] = {}

    def add(term: str, canonical: str, semantic: str, method: str) -> None:
        normalized = normalize_business_name(term)
        if not normalized:
            return
        item = (canonical, semantic, method)
        if item not in lookup.setdefault(normalized, []):
            lookup[normalized].append(item)

    for site in sites:
        semantic = fleet_by_normalized.get(site.normalized_minesite_name, site.canonical_minesite_name)
        add(site.canonical_minesite_name, site.canonical_minesite_name, semantic, "canonical_name")
        add(site.minesite_code, site.canonical_minesite_name, semantic, "canonical_code")
        short_name = re.split(r"\s*/\s*|\s+-\s+", site.canonical_minesite_name, maxsplit=1)[0].strip()
        if normalize_business_name(short_name) != site.normalized_minesite_name:
            add(short_name, site.canonical_minesite_name, semantic, "canonical_short_name")

    if sites:
        aliases = MineSiteAlias.objects.filter(
            minesite__in=sites,
            active=True,
            validation_status="Validated",
        ).select_related("minesite")
        for alias in aliases:
            semantic = fleet_by_normalized.get(
                alias.minesite.normalized_minesite_name,
                alias.minesite.canonical_minesite_name,
            )
            add(alias.alias, alias.minesite.canonical_minesite_name, semantic, "validated_alias")

    for fleet_name in fleet_names:
        normalized = normalize_business_name(fleet_name)
        site = sites_by_normalized.get(normalized)
        add(
            fleet_name,
            site.canonical_minesite_name if site else fleet_name,
            fleet_name,
            "fleet_source_name",
        )

    matches = [
        (len(term.split()), len(term), term, destinations)
        for term, destinations in lookup.items()
        if _contains(normalized_question, term)
    ]
    if not matches:
        return None
    best_size = max((words, chars) for words, chars, _, _ in matches)
    best = [item for item in matches if item[:2] == best_size]
    destinations = {
        (canonical, semantic, method, term)
        for _, _, term, values in best
        for canonical, semantic, method in values
    }
    canonical_names = sorted({item[0] for item in destinations}, key=str.casefold)
    if len(canonical_names) > 1:
        return MineSiteResolution(None, None, best[0][2], "ambiguous_alias", tuple(canonical_names))
    canonical = canonical_names[0]
    selected = sorted(
        (item for item in destinations if item[0] == canonical),
        key=lambda item: (item[2] != "validated_alias", item[2]),
    )[0]
    return MineSiteResolution(canonical, selected[1], selected[3], selected[2])
