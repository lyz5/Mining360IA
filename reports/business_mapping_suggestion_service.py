from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .business_mapping_normalization_service import normalize_business_name
from .models import AccountMineSiteCandidate, BusinessAccountAlias, FleetSourceSnapshot, MappingEvidence, MineSite, SourceAccountRecord


class AccountMineSiteSuggestionService:
    VERSION = "1.0"

    @classmethod
    @transaction.atomic
    def generate_for_account(cls, source_account: SourceAccountRecord, limit: int = 5, minesites=None) -> list[AccountMineSiteCandidate]:
        scores: dict[str, dict] = {}
        account_name = source_account.normalized_account_name or normalize_business_name(source_account.source_account_name)

        if source_account.canonical_account_id:
            for mapping in source_account.canonical_account.minesite_mappings.filter(
                active=True, minesite__isnull=False, relationship_status__in=["Validated", "Published"],
            ).select_related("minesite"):
                scores[str(mapping.minesite_id)] = {
                    "site": mapping.minesite,
                    "score": 99,
                    "evidence": [("Historical mapping", "A prior human-validated mapping exists for this Account.", str(mapping.id), 99)],
                }

        alias_accounts = BusinessAccountAlias.objects.filter(
            normalized_alias=account_name, active=True, validation_status="Validated",
        ).values_list("canonical_account_id", flat=True)
        for mapping in MineSite.objects.filter(
            account_mappings__business_account_id__in=alias_accounts,
            account_mappings__active=True,
            account_mappings__relationship_status__in=["Validated", "Published"],
            active=True,
        ).distinct():
            item = scores.setdefault(str(mapping.id), {"site": mapping, "score": 0, "evidence": []})
            item["score"] = max(item["score"], 96)
            item["evidence"].append(("Validated alias", "The source Account name matches a validated Account alias.", source_account.source_account_name, 96))

        for fleet in FleetSourceSnapshot.objects.filter(active=True, normalized_customer=account_name).exclude(normalized_minesite_name=""):
            site = MineSite.objects.filter(active=True, normalized_minesite_name=fleet.normalized_minesite_name).first()
            if site:
                item = scores.setdefault(str(site.id), {"site": site, "score": 0, "evidence": []})
                item["score"] = max(item["score"], 90)
                item["evidence"].append(("Fleet Customer match", "Fleet Customer exactly matches the normalized Account name.", fleet.customer, 90))

        allowed_sites = minesites if minesites is not None else MineSite.objects.filter(active=True)
        allowed_ids = set(allowed_sites.values_list("id", flat=True))
        scores = {key: item for key, item in scores.items() if item["site"].id in allowed_ids}
        for site in allowed_sites:
            site_name = site.normalized_minesite_name
            if site_name and len(site_name) >= 4 and site_name in account_name:
                item = scores.setdefault(str(site.id), {"site": site, "score": 0, "evidence": []})
                item["score"] = max(item["score"], 72)
                item["evidence"].append(("MineSite name match", "The MineSite name appears in the Account name.", site.canonical_minesite_name, 72))
            if site.country and source_account.country and site.country.casefold() == source_account.country.casefold() and str(site.id) in scores:
                scores[str(site.id)]["score"] = min(100, scores[str(site.id)]["score"] + 5)
                scores[str(site.id)]["evidence"].append(("Country match", "Account and MineSite country match.", site.country, 5))

        results = []
        for item in sorted(scores.values(), key=lambda value: (-value["score"], value["site"].canonical_minesite_name))[:limit]:
            candidate, _ = AccountMineSiteCandidate.objects.update_or_create(
                source_account=source_account,
                candidate_minesite=item["site"],
                generation_version=cls.VERSION,
                defaults={
                    "business_account": source_account.canonical_account,
                    "confidence_score": item["score"],
                    "suggestion_method": "Deterministic",
                    "evidence_summary_json": [entry[1] for entry in item["evidence"]],
                    "conflict_summary_json": [],
                    "status": "Suggested",
                    "reviewed_by": None,
                    "reviewed_at": None,
                },
            )
            candidate.evidence.all().delete()
            for evidence_type, description, value, weight in item["evidence"]:
                MappingEvidence.objects.create(
                    candidate=candidate,
                    evidence_type=evidence_type,
                    source_system="Customer Fleet & Revenue Planning Model",
                    source_record_id=source_account.source_record_id,
                    description=description,
                    value=value,
                    weight=weight,
                )
            results.append(candidate)
        AccountMineSiteCandidate.objects.filter(source_account=source_account, generation_version=cls.VERSION).exclude(pk__in=[item.pk for item in results]).update(status="Expired", reviewed_at=timezone.now())
        return results
