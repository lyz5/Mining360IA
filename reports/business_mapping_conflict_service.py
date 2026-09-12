from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import AccountMineSiteMapping, BusinessAccountAlias, RevenueSiteAllocationRule


class BusinessMappingConflictService:
    @staticmethod
    def list_conflicts(limit=200, account_ids=None) -> list[dict]:
        conflicts = []
        duplicate_aliases = BusinessAccountAlias.objects.filter(active=True, validation_status="Validated")
        mappings = AccountMineSiteMapping.objects.filter(active=True, relationship_status__in=["Validated", "Published"])
        allocations = RevenueSiteAllocationRule.objects.filter(status__in=["Validated", "Published"])
        if account_ids is not None:
            account_ids = set(account_ids)
            duplicate_aliases = duplicate_aliases.filter(canonical_account_id__in=account_ids)
            mappings = mappings.filter(business_account_id__in=account_ids)
            allocations = allocations.filter(business_account_id__in=account_ids)
        duplicate_aliases = duplicate_aliases.values("normalized_alias").annotate(total=Count("canonical_account", distinct=True)).filter(total__gt=1)
        for item in duplicate_aliases:
            conflicts.append({"type": "ALIAS_COLLISION", "severity": "High", "label": item["normalized_alias"], "message": "A validated alias is linked to several Accounts."})

        mappings = list(mappings.select_related("business_account", "minesite").order_by("business_account_id", "minesite_id", "account_role", "valid_from"))
        groups = defaultdict(list)
        for mapping in mappings:
            groups[(mapping.business_account_id, mapping.minesite_id, mapping.account_role)].append(mapping)
            if not mapping.business_account.active or (mapping.minesite_id and not mapping.minesite.active):
                conflicts.append({"type": "INACTIVE_REFERENCE", "severity": "High", "mapping_id": str(mapping.id), "message": "An active mapping references an inactive Account or MineSite."})
        for grouped in groups.values():
            for index, first in enumerate(grouped):
                for second in grouped[index + 1:]:
                    if (first.valid_to is None or second.valid_from is None or first.valid_to >= second.valid_from) and (second.valid_to is None or first.valid_from is None or second.valid_to >= first.valid_from):
                        conflicts.append({"type": "EFFECTIVE_DATE_OVERLAP", "severity": "High", "mapping_id": str(second.id), "message": "Validated mapping effective dates overlap."})

        allocation_groups = allocations.values("business_account_id", "lob", "division", "distribution_channel", "company_code", "branch_code", "valid_from").annotate(total=Sum("allocation_percentage")).filter(total__gt=Decimal("100.0001"))
        for item in allocation_groups:
            conflicts.append({"type": "ALLOCATION_EXCEEDS_100", "severity": "Critical", "account_id": str(item["business_account_id"]), "message": f"Active allocation totals {item['total']}%."})
        return conflicts[:limit]
