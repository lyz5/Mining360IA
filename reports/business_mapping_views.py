from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .ai_feature_rollout import feature_enabled
from .business_mapping_access_service import filter_minesites_for_user, filter_source_accounts_for_user, has_mapping_permission
from .business_mapping_alias_service import BusinessAccountAliasService, BusinessAccountOperatingCountryService
from .business_mapping_conflict_service import BusinessMappingConflictService
from .business_mapping_country_scope import normalize_operating_country, operating_country_options
from .business_mapping_country_account_service import CountryAccountService
from .business_mapping_key_account_service import KeyAccountService
from .business_mapping_publication_service import MappingPublicationError, MappingPublicationService
from .business_mapping_source_service import (
    MINING_DIVISION,
    MINING_REVENUE_LABELS,
    MINING_REVENUE_LOBS,
    BusinessMappingSourceSynchronizationService,
    enqueue_business_mapping_sync,
)
from .business_mapping_suggestion_service import AccountMineSiteSuggestionService
from .business_mapping_validation_service import AccountMineSiteValidationService, MappingValidationError
from .models import (
    AccountMineSiteCandidate,
    AccountMineSiteMapping,
    BusinessAccount,
    CountryAccount,
    CountryAccountMembership,
    EquipmentFleetAnalysis,
    KeyAccount,
    KeyAccountCountryMembership,
    KeyAccountMembership,
    MappingAuditLog,
    MappingPublication,
    MappingSynchronizationRun,
    MineSite,
    RevenueSourceSnapshot,
    RevenueSiteAllocationRule,
    SourceAccountRecord,
)


UNASSIGNED_COUNTRY_SCOPE = "UNASSIGNED"


logger = logging.getLogger(__name__)


def _revenue_period(request):
    available_years = list(RevenueSourceSnapshot.objects.filter(
        active=True, period_year__isnull=False,
    ).order_by("-period_year").values_list("period_year", flat=True).distinct())
    latest_year = available_years[0] if available_years else None
    if latest_year is None:
        sample = RevenueSourceSnapshot.objects.filter(active=True).select_related("synchronization_run").first()
        context_year = (sample.synchronization_run.source_context_json or {}).get("revenue_period_year") if sample else None
        try:
            latest_year = int(context_year)
        except (TypeError, ValueError):
            latest_year = None
    requested = request.GET.get("period", "ytd").strip().lower()
    if requested == "all":
        value = "all"
        year = None
        label = "All available periods"
    elif requested.isdigit() and int(requested) in available_years:
        year = int(requested)
        value = str(year)
        label = str(year)
    else:
        value = "ytd"
        year = latest_year
        label = f"YTD {latest_year}" if latest_year else "YTD period unavailable"
    return {
        "value": value,
        "year": year,
        "label": label,
        "available_years": available_years,
        "options": ([{"value": "ytd", "label": f"YTD {latest_year}" if latest_year else "YTD", "available": latest_year is not None}]
                    + [{"value": str(candidate), "label": str(candidate), "available": candidate in available_years} for candidate in range((latest_year or timezone.now().year) - 1, (latest_year or timezone.now().year) - 4, -1)]
                    + [{"value": "all", "label": "All periods", "available": bool(available_years)}]),
    }


def _mining_revenue(lob="", operating_country="", period="ytd"):
    queryset = RevenueSourceSnapshot.objects.filter(
        active=True,
        division__iexact=MINING_DIVISION,
        lob__in=MINING_REVENUE_LOBS,
    )
    latest_year = queryset.exclude(period_year=None).aggregate(latest=Max("period_year"))["latest"]
    normalized_lob = str(lob or "").strip().upper()
    if normalized_lob in MINING_REVENUE_LOBS:
        queryset = queryset.filter(lob=normalized_lob)
    normalized_period = str(period or "ytd").strip().lower()
    if normalized_period != "all":
        selected_year = int(normalized_period) if normalized_period.isdigit() else latest_year
        if selected_year:
            queryset = queryset.filter(period_year=selected_year)
        elif normalized_period.isdigit():
            queryset = queryset.none()
    requested_country = str(operating_country or "").strip().upper()
    if requested_country == UNASSIGNED_COUNTRY_SCOPE:
        unassigned_source_codes = SourceAccountRecord.objects.filter(active=True).filter(
            Q(canonical_account__assigned_operating_country="")
            | Q(canonical_account__assigned_operating_country__isnull=True)
            | Q(canonical_account__isnull=True)
        ).values("source_record_id")
        return queryset.filter(source_account_code__in=unassigned_source_codes)
    normalized_country = normalize_operating_country(requested_country)
    if normalized_country:
        assigned_source_codes = SourceAccountRecord.objects.filter(
            active=True,
            canonical_account__assigned_operating_country=normalized_country,
        ).values("source_record_id")
        manually_classified_source_codes = SourceAccountRecord.objects.filter(
            active=True,
        ).exclude(canonical_account__assigned_operating_country="").exclude(
            canonical_account__isnull=True,
        ).values("source_record_id")
        queryset = queryset.filter(
            Q(source_account_code__in=assigned_source_codes)
            | (
                Q(operating_country=normalized_country)
                & ~Q(source_account_code__in=manually_classified_source_codes)
            )
        )
    return queryset


def _selected_revenue_lob(request):
    value = request.GET.get("lob", "").strip().upper()
    return value if value in MINING_REVENUE_LOBS else ""


def _selected_country(request):
    value = str(request.GET.get("country", "")).strip().upper()
    return UNASSIGNED_COUNTRY_SCOPE if value == UNASSIGNED_COUNTRY_SCOPE else normalize_operating_country(value)


def _filter_source_accounts_by_operating_country(queryset, country):
    requested_country = str(country or "").strip().upper()
    if requested_country == UNASSIGNED_COUNTRY_SCOPE:
        return queryset.filter(
            Q(canonical_account__assigned_operating_country="")
            | Q(canonical_account__assigned_operating_country__isnull=True)
            | Q(canonical_account__isnull=True)
        ).distinct()
    country = normalize_operating_country(requested_country)
    if not country:
        return queryset
    revenue_codes = RevenueSourceSnapshot.objects.filter(active=True, operating_country=country).values("source_account_code")
    return queryset.filter(
        Q(canonical_account__assigned_operating_country=country)
        | Q(
            canonical_account__assigned_operating_country="",
            source_record_id__in=revenue_codes,
        )
        | Q(canonical_account__isnull=True, source_record_id__in=revenue_codes)
    ).distinct()


def _revenue_breakdown(queryset):
    values = {
        row["lob"]: row["value"] or Decimal("0")
        for row in queryset.values("lob").annotate(value=Sum("revenue_ytd_eur"))
    }
    return [
        {"code": lob, "label": MINING_REVENUE_LABELS[lob], "value": values.get(lob, Decimal("0"))}
        for lob in MINING_REVENUE_LOBS
    ]


def _equipment_summaries(normalized_sites):
    summaries = {}
    rows = EquipmentFleetAnalysis.objects.filter(
        active=True,
        normalized_site__in=set(normalized_sites),
    ).values("normalized_site", "serial_number", "model", "equipment_family")
    for row in rows:
        summary = summaries.setdefault(row["normalized_site"], {
            "count": 0, "serials": set(), "models": set(), "families": set(),
        })
        summary["count"] += 1
        if row["serial_number"]:
            summary["serials"].add(row["serial_number"])
        if row["model"]:
            summary["models"].add(row["model"])
        if row["equipment_family"]:
            summary["families"].add(row["equipment_family"])
    return {
        site: {
            "count": values["count"],
            "serial_count": len(values["serials"]),
            "models": sorted(values["models"])[:20],
            "families": sorted(values["families"])[:20],
            "source": "EquipmentList_MiningProd",
        }
        for site, values in summaries.items()
    }


def _payload(request):
    try:
        return json.loads(request.body or b"{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise MappingValidationError("The request payload is invalid.", code="INVALID_JSON") from exc


def _error(exc):
    return JsonResponse({"ok": False, "error": {"code": getattr(exc, "code", "REQUEST_FAILED"), "message": str(exc), "fields": getattr(exc, "fields", {})}}, status=getattr(exc, "status", 400))


def _unexpected(message):
    logger.exception("Business Mapping Studio request failed")
    return JsonResponse({"ok": False, "error": {"code": "TEMPORARILY_UNAVAILABLE", "message": message, "fields": {}}}, status=503)


def _require(user, permission="view_business_mapping"):
    return has_mapping_permission(user, permission)


def _mapping_json(item, source_accounts=None):
    payload = {
        "id": str(item.id), "version": item.current_version, "status": item.relationship_status,
        "business_account_id": str(item.business_account_id),
        "account_role": item.account_role, "is_primary_site": item.is_primary_site,
        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
        "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        "allocation_status": item.revenue_allocation_status, "no_site_reason": item.no_site_reason,
        "minesite": None if not item.minesite_id else {"id": str(item.minesite_id), "name": item.minesite.canonical_minesite_name},
    }
    if source_accounts is not None:
        payload["source_accounts"] = source_accounts
    return payload


@login_required
def business_mapping_studio(request):
    if not _require(request.user):
        return HttpResponseForbidden("You do not have access to Business Mapping Studio.")
    return render(request, "reports/business_mapping_studio.html", {
        "active_section": "business-mapping",
        "can_edit": _require(request.user, "edit_business_mapping"),
        "can_remove": _require(request.user, "reject_business_mapping"),
        "can_validate": _require(request.user, "validate_business_mapping"),
        "can_publish": _require(request.user, "publish_business_mapping"),
        "can_sync": _require(request.user, "synchronize_business_mapping_sources"),
        "feature_flags": {
            "suggestions": feature_enabled("ENABLE_BUSINESS_MAPPING_SUGGESTIONS", request.user),
            "revenue_allocation": feature_enabled("ENABLE_BUSINESS_MAPPING_REVENUE_ALLOCATION", request.user),
            "publication": feature_enabled("ENABLE_BUSINESS_MAPPING_PUBLICATION", request.user),
        },
    })


@login_required
def overview_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    selected_country = _selected_country(request)
    source_accounts = filter_source_accounts_for_user(
        SourceAccountRecord.objects.filter(active=True), request.user,
    )
    if selected_country:
        source_accounts = _filter_source_accounts_by_operating_country(source_accounts, selected_country)
        scoped_account_codes = set(source_accounts.values_list("source_record_id", flat=True))
    else:
        scoped_account_codes = None
    scoped_account_ids = set(source_accounts.exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True))
    accounts = BusinessAccount.objects.filter(active=True, pk__in=scoped_account_ids)
    total = accounts.count()
    mapped_ids = AccountMineSiteMapping.objects.filter(active=True, relationship_status__in=["Validated", "Published"]).values_list("business_account_id", flat=True)
    no_site_ids = AccountMineSiteMapping.objects.filter(active=True, relationship_status="No MineSite Required").values_list("business_account_id", flat=True)
    mapped_count = accounts.filter(pk__in=mapped_ids).distinct().count()
    no_site_count = accounts.filter(pk__in=no_site_ids).distinct().count()
    selected_lob = _selected_revenue_lob(request)
    period = _revenue_period(request)
    all_mining_revenue = _mining_revenue("", selected_country, period["value"])
    latest_revenue = _mining_revenue(selected_lob, selected_country, period["value"])
    if scoped_account_codes is not None:
        all_mining_revenue = all_mining_revenue.filter(source_account_code__in=scoped_account_codes)
        latest_revenue = latest_revenue.filter(source_account_code__in=scoped_account_codes)
    revenue_total = latest_revenue.aggregate(value=Sum("revenue_ytd_eur"))["value"] or Decimal("0")
    mapped_code_query = SourceAccountRecord.objects.filter(canonical_account_id__in=mapped_ids, active=True)
    if selected_country:
        mapped_code_query = _filter_source_accounts_by_operating_country(mapped_code_query, selected_country)
    mapped_codes = set(mapped_code_query.values_list("source_record_id", flat=True))
    allocated_revenue = latest_revenue.filter(source_account_code__in=mapped_codes).aggregate(value=Sum("revenue_ytd_eur"))["value"] or Decimal("0")
    scoped_mappings = AccountMineSiteMapping.objects.filter(
        active=True,
        relationship_status__in=["Validated", "Published"],
        business_account_id__in=scoped_account_ids,
        minesite__isnull=False,
    )
    mapped_site_names = scoped_mappings.values_list("minesite__normalized_minesite_name", flat=True)
    fleet_analysis = EquipmentFleetAnalysis.objects.filter(active=True)
    if selected_country:
        country_site_names = MineSite.objects.filter(
            Q(country__iexact=selected_country) | Q(pk__in=scoped_mappings.values("minesite_id"))
        ).values_list("normalized_minesite_name", flat=True)
        fleet_analysis = fleet_analysis.filter(normalized_site__in=country_site_names)
    fleet_total = fleet_analysis.count()
    fleet_linked = fleet_analysis.filter(normalized_site__in=mapped_site_names).count()
    try:
        conflicts = BusinessMappingConflictService.list_conflicts(account_ids=scoped_account_ids)
        conflict_scan = {"status": "Completed", "evaluated_at": timezone.now().isoformat()}
    except Exception:
        logger.exception("Business Mapping conflict scan failed")
        conflicts = None
        conflict_scan = {"status": "Not Evaluated", "evaluated_at": None}
    active_revenue_snapshot = latest_revenue.select_related("synchronization_run").first()
    latest_run = active_revenue_snapshot.synchronization_run if active_revenue_snapshot else MappingSynchronizationRun.objects.filter(status="Completed").first()
    source_context = (latest_run.source_context_json or {}) if latest_run else {}
    period_year = source_context.get("revenue_period_year")
    return JsonResponse({"ok": True, "source_context": {
        "business_scope": {
            "country": selected_country or None,
            "label": selected_country or "Group",
            "fleet_basis": "Mapped MineSites and configured MineSite countries" if selected_country else "Authorized group fleet",
        },
        "revenue": {
            "kind": "ALL" if period["value"] == "all" else ("YTD" if period["value"] == "ytd" else "YEAR"),
            "year": period["year"],
            "previous_year": period["year"] - 1 if period["year"] else None,
            "data_through": source_context.get("semantic_data_through"),
            "label": period["label"],
            "selected_period": period["value"],
            "period_options": period["options"],
            "available_years": period["available_years"],
            "scope": "Mining",
            "division": MINING_DIVISION,
            "categories": list(MINING_REVENUE_LABELS.values()),
            "selected_lob": selected_lob or None,
            "selected_category": MINING_REVENUE_LABELS.get(selected_lob, "All Mining"),
        },
        "fleet": {
            "kind": source_context.get("fleet_snapshot_kind") or "current_source_snapshot",
            "snapshot_at": source_context.get("snapshot_completed_at") or (latest_run.completed_at.isoformat() if latest_run and latest_run.completed_at else None),
            "source": source_context.get("fleet_analysis_source") or "EquipmentList_MiningProd",
            "row_count": source_context.get("fleet_analysis_row_count") or fleet_total,
        },
        "mappings": {"kind": "current_database_state", "as_of": timezone.now().isoformat()},
        "synchronization_run_id": str(latest_run.id) if latest_run else None,
        "conflict_scan": conflict_scan,
    }, "count_definitions": {
        "canonical_accounts": "Distinct governed Business Accounts in the authorized source scope.",
        "source_records": "Active source Account records; several records may belong to one canonical Account.",
        "accounts_needing_review": "Canonical Accounts whose validation status is To Review.",
    }, "revenue_breakdown": _revenue_breakdown(all_mining_revenue), "summary": {
        "total_accounts": total, "accounts_classified": mapped_count + no_site_count,
        "total_source_records": source_accounts.count(),
        "accounts_unmapped": max(0, total - mapped_count - no_site_count),
        "accounts_needing_review": accounts.filter(validation_status="To Review").count(),
        "accounts_with_conflicts": None if conflicts is None else len({item.get("account_id") or item.get("mapping_id") for item in conflicts}),
        "no_minesite_required": no_site_count,
        "total_revenue_eur": revenue_total,
        "revenue_assigned_eur": allocated_revenue, "unallocated_revenue_eur": revenue_total - allocated_revenue,
        "fleet_linked": fleet_linked, "fleet_total": fleet_total,
        "account_coverage_pct": round(((mapped_count + no_site_count) / total * 100), 1) if total else 0,
        "revenue_coverage_pct": round((float(allocated_revenue / revenue_total) * 100), 1) if revenue_total else 0,
        "fleet_coverage_pct": round((fleet_linked / fleet_total * 100), 1) if fleet_total else 0,
    }})


@login_required
def equipment_analysis_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    allowed_sites = filter_minesites_for_user(
        MineSite.objects.filter(active=True), request.user,
    ).values_list("normalized_minesite_name", flat=True)
    queryset = EquipmentFleetAnalysis.objects.filter(active=True, normalized_site__in=allowed_sites)
    search = request.GET.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(site__icontains=search)
            | Q(equipment__icontains=search)
            | Q(model__icontains=search)
            | Q(serial_number__icontains=search)
            | Q(equipment_family__icontains=search)
        )
    for parameter, field in (("site", "site__iexact"), ("model", "model__iexact"), ("family", "equipment_family__iexact")):
        value = request.GET.get(parameter, "").strip()
        if value:
            queryset = queryset.filter(**{field: value})
    paginator = Paginator(queryset.order_by("site", "model", "equipment"), min(100, max(10, int(request.GET.get("page_size", 50)))))
    page = paginator.get_page(request.GET.get("page", 1))
    rows = list(page.object_list)
    snapshot_at = max((row.source_last_seen_at for row in rows), default=None)
    return JsonResponse({
        "count": paginator.count,
        "page": page.number,
        "pages": paginator.num_pages,
        "source": {
            "semantic_model": "FPR Global DB + RLS",
            "table": "EquipmentList_MiningProd",
            "snapshot_at": snapshot_at,
        },
        "results": [{
            "equipment_id": row.equipment_id,
            "site": row.site,
            "equipment": row.equipment,
            "model": row.model,
            "serial_number": row.serial_number,
            "equipment_family": row.equipment_family,
            "brand": row.brand,
            "status": row.source_status or None,
            "smu": row.smu,
        } for row in rows],
    })


@login_required
def accounts_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    authorized_accounts = filter_source_accounts_for_user(
        SourceAccountRecord.objects.filter(active=True), request.user,
    )
    countries = [{"code": UNASSIGNED_COUNTRY_SCOPE, "label": "Country not validated"}, *operating_country_options()]
    authorized_account_ids = set(authorized_accounts.exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True))
    key_account_filters = list(KeyAccount.objects.filter(
        active=True,
        memberships__active=True,
        memberships__business_account_id__in=authorized_account_ids,
    ).distinct().order_by("key_account_name").values("id", "key_account_name"))
    if request.GET.get("view", "source").strip().casefold() == "canonical":
        return _canonical_account_groups_response(request, authorized_accounts, countries, key_account_filters, [])
    queryset = authorized_accounts.select_related("canonical_account").annotate(
        suggested_candidate_count=Count("minesite_candidates", filter=Q(minesite_candidates__status="Suggested"), distinct=True),
    ).prefetch_related(
        Prefetch(
            "canonical_account__minesite_mappings",
            queryset=AccountMineSiteMapping.objects.filter(active=True).select_related("minesite"),
            to_attr="active_bm_mappings",
        )
    )
    search = request.GET.get("search", "").strip()
    country = request.GET.get("country", "").strip().upper()
    if country:
        queryset = _filter_source_accounts_by_operating_country(queryset, country)
    key_account_filter = request.GET.get("key_account", "").strip()
    if key_account_filter == "unassigned":
        queryset = queryset.exclude(canonical_account__key_account_memberships__active=True)
    elif key_account_filter:
        queryset = queryset.filter(canonical_account__key_account_memberships__active=True, canonical_account__key_account_memberships__key_account_id=key_account_filter)
    status = request.GET.get("status", "").strip()
    if status == "Unmapped":
        queryset = queryset.exclude(canonical_account__minesite_mappings__active=True, canonical_account__minesite_mappings__relationship_status__in=["Validated", "Published", "No MineSite Required"])
    elif status:
        queryset = queryset.filter(canonical_account__minesite_mappings__relationship_status=status)
    selected_lob = _selected_revenue_lob(request)
    period = _revenue_period(request)
    sort = request.GET.get("sort", "revenue_desc").strip().casefold()
    page_size = min(100, max(10, int(request.GET.get("page_size", 30))))
    ranking_queryset = queryset.distinct()
    revenue_totals = {
        row["source_account_code"]: row["total"] or Decimal("0")
        for row in _mining_revenue(selected_lob, country, period["value"]).values("source_account_code").annotate(total=Sum("revenue_ytd_eur"))
    }
    revenue_rank = {
        row["pk"]: index
        for index, row in enumerate(sorted(
            ranking_queryset.values("pk", "source_record_id", "source_account_name"),
            key=lambda item: (
                -revenue_totals.get(item["source_record_id"], Decimal("0")),
                item["source_account_name"].casefold(),
                item["source_record_id"].casefold(),
            ),
        ), start=1)
    }
    base_queryset = ranking_queryset
    if search:
        base_queryset = base_queryset.filter(
            Q(source_account_name__icontains=search) | Q(canonical_account__canonical_account_name__icontains=search)
            | Q(canonical_account__aliases__alias__icontains=search, canonical_account__aliases__active=True)
            | Q(source_record_id__icontains=search) | Q(code_cic__icontains=search)
            | Q(company_code__icontains=search) | Q(branch_code__icontains=search) | Q(country__icontains=search)
        )
    if sort in {"revenue_asc", "revenue_desc"}:
        sortable_rows = list(base_queryset.values("pk", "source_record_id", "source_account_name"))
        if sort == "revenue_desc":
            sortable_rows.sort(key=lambda row: (
                -revenue_totals.get(row["source_record_id"], Decimal("0")),
                row["source_account_name"].casefold(),
                row["source_record_id"].casefold(),
            ))
        else:
            sortable_rows.sort(key=lambda row: (
                revenue_totals.get(row["source_record_id"], Decimal("0")),
                row["source_account_name"].casefold(),
                row["source_record_id"].casefold(),
            ))
        paginator = Paginator(sortable_rows, page_size)
        page = paginator.get_page(request.GET.get("page", 1))
        ordered_ids = [row["pk"] for row in page.object_list]
        records_by_id = {record.pk: record for record in base_queryset.filter(pk__in=ordered_ids)}
        records = [records_by_id[record_id] for record_id in ordered_ids if record_id in records_by_id]
    else:
        paginator = Paginator(base_queryset.order_by("source_account_name", "source_record_id"), page_size)
        page = paginator.get_page(request.GET.get("page", 1))
        records = list(page.object_list)
    codes = [record.source_record_id for record in records]
    revenue = {row["source_account_code"]: row for row in _mining_revenue(selected_lob, country, period["value"]).filter(source_account_code__in=codes).values("source_account_code").annotate(ytd=Sum("revenue_ytd_eur"))}
    account_ids = [record.canonical_account_id for record in records if record.canonical_account_id]
    assigned_country_by_account = dict(BusinessAccount.objects.filter(
        pk__in=account_ids,
    ).exclude(assigned_operating_country="").values_list("pk", "assigned_operating_country"))
    account_sites = {}
    for account_id, normalized_site in AccountMineSiteMapping.objects.filter(
        business_account_id__in=account_ids,
        active=True,
        relationship_status__in=["Validated", "Published"],
        minesite__isnull=False,
    ).values_list("business_account_id", "minesite__normalized_minesite_name"):
        account_sites.setdefault(account_id, set()).add(normalized_site)
    fleet_counts_by_site = {
        row["normalized_site"]: row["total"]
        for row in EquipmentFleetAnalysis.objects.filter(active=True).values("normalized_site").annotate(total=Count("pk"))
    }
    results = []
    for record in records:
        mapping_objects = getattr(record.canonical_account, "active_bm_mappings", []) if record.canonical_account_id else []
        mappings = [mapping.relationship_status for mapping in mapping_objects]
        item_revenue = revenue.get(record.source_record_id, {})
        results.append({
            "source_account_id": str(record.id), "source_account_name": record.source_account_name,
            "source_account_code": record.source_record_id,
            "canonical_account": None if not record.canonical_account_id else {"id": str(record.canonical_account_id), "name": record.canonical_account.canonical_account_name},
            "code_cic": record.code_cic, "company_code": record.company_code, "branch_code": record.branch_code,
            "company_name": ((record.source_payload_json or {}).get("revenue_company_name_values") or [None])[0],
            "country": record.origin_country or record.country,
            "origin_country": record.origin_country or record.country,
            "operating_countries": record.operating_countries_json or [],
            "assigned_operating_countries": [assigned_country_by_account[record.canonical_account_id]] if record.canonical_account_id in assigned_country_by_account else [],
            "business_account_ids": [str(record.canonical_account_id)] if record.canonical_account_id else [],
            "revenue_ytd": item_revenue.get("ytd"), "currency": "EUR",
            "revenue_rank": revenue_rank.get(record.pk),
            "fleet_count": sum(fleet_counts_by_site.get(site, 0) for site in account_sites.get(record.canonical_account_id, set())),
            "candidate_count": record.suggested_candidate_count,
            "mapping_status": mappings[0] if mappings else "Unmapped", "issue_count": 0,
            "version": max((mapping.current_version for mapping in mapping_objects), default=0),
        })
    return JsonResponse({
        "count": paginator.count,
        "page": page.number,
        "pages": paginator.num_pages,
        "filters": {"countries": countries, "key_accounts": key_account_filters},
        "results": results,
    })


def _canonical_account_groups_response(request, authorized_accounts, countries, key_account_filters, _country_account_filters=None):
    """Group the queue without merging legal identities based on display name alone."""
    search = request.GET.get("search", "").strip()
    country = request.GET.get("country", "").strip().upper()
    if country:
        authorized_accounts = _filter_source_accounts_by_operating_country(authorized_accounts, country)
    records = list(authorized_accounts.select_related("canonical_account").order_by("normalized_account_name", "source_record_id"))
    selected_lob = _selected_revenue_lob(request)
    period = _revenue_period(request)
    source_codes = [record.source_record_id for record in records]
    revenue_by_source = {
        row["source_account_code"]: row["value"] or Decimal("0")
        for row in _mining_revenue(selected_lob, country, period["value"]).filter(source_account_code__in=source_codes).values("source_account_code").annotate(value=Sum("revenue_ytd_eur"))
    }
    mapping_statuses = {}
    for account_id, status in AccountMineSiteMapping.objects.filter(
        active=True,
        business_account_id__in={record.canonical_account_id for record in records if record.canonical_account_id},
    ).values_list("business_account_id", "relationship_status"):
        mapping_statuses.setdefault(account_id, set()).add(status)
    key_account_membership = {
        account_id: (str(key_id), key_name)
        for account_id, key_id, key_name in KeyAccountMembership.objects.filter(
            active=True,
            business_account_id__in={record.canonical_account_id for record in records if record.canonical_account_id},
        ).values_list("business_account_id", "key_account_id", "key_account__key_account_name")
    }
    country_group_membership = {
        account_id: (str(group_id), group_name, group_country)
        for account_id, group_id, group_name, group_country in CountryAccountMembership.objects.filter(
            active=True,
            country_account__active=True,
            business_account_id__in={record.canonical_account_id for record in records if record.canonical_account_id},
        ).values_list(
            "business_account_id",
            "country_account_id",
            "country_account__country_account_name",
            "country_account__country",
        )
    }
    aliases_by_account = {}
    for account_id, alias in BusinessAccount.objects.filter(
        pk__in={record.canonical_account_id for record in records if record.canonical_account_id},
        aliases__active=True,
    ).values_list("pk", "aliases__alias"):
        aliases_by_account.setdefault(str(account_id), set()).add(alias)
    groups = {}
    for record in records:
        origin_country = record.origin_country or record.country
        # Origin country remains part of legal identity; operating country is a commercial scope.
        key = (record.normalized_account_name, origin_country.casefold())
        group = groups.setdefault(key, {
            "name": record.canonical_account.canonical_account_name if record.canonical_account_id else record.source_account_name,
            "country": origin_country,
            "operating_countries": set(),
            "assigned_operating_countries": set(),
            "records": [],
            "canonical_ids": set(),
            "revenue": Decimal("0"),
            "statuses": set(),
            "key_accounts": set(),
            "key_account_ids": set(),
            "customer_country_groups": set(),
            "customer_country_group_ids": set(),
            "search_values": [],
        })
        group["canonical_ids"].add(str(record.canonical_account_id) if record.canonical_account_id else "")
        group["operating_countries"].update(record.operating_countries_json or [])
        if record.canonical_account_id and record.canonical_account.assigned_operating_country:
            group["assigned_operating_countries"].add(record.canonical_account.assigned_operating_country)
        group["statuses"].update(mapping_statuses.get(record.canonical_account_id, set()))
        if key_account_membership.get(record.canonical_account_id):
            key_id, key_name = key_account_membership[record.canonical_account_id]
            group["key_account_ids"].add(key_id)
            group["key_accounts"].add(key_name)
        if country_group_membership.get(record.canonical_account_id):
            country_group_id, country_group_name, country_group_country = country_group_membership[record.canonical_account_id]
            group["customer_country_group_ids"].add(country_group_id)
            group["customer_country_groups"].add((country_group_name, country_group_country))
        group["search_values"].extend([
            record.source_account_name, record.source_record_id, record.code_cic,
            record.company_code, record.branch_code, record.country,
            record.canonical_account.canonical_account_name if record.canonical_account_id else "",
            *(aliases_by_account.get(str(record.canonical_account_id), set())),
        ])
        source_revenue = revenue_by_source.get(record.source_record_id, Decimal("0"))
        group["revenue"] += source_revenue
        group["records"].append({
            "id": str(record.id), "source_system": record.source_system, "source_record_id": record.source_record_id,
            "code_cic": record.code_cic, "company_code": record.company_code, "branch_code": record.branch_code,
            "company_name": ((record.source_payload_json or {}).get("revenue_company_name_values") or [None])[0],
            "country": origin_country, "origin_country": origin_country,
            "operating_countries": record.operating_countries_json or [], "source_record_revenue_ytd": source_revenue,
        })
    results = []
    for group in groups.values():
        canonical_ids = {value for value in group["canonical_ids"] if value}
        representative = group["records"][0]
        if search:
            normalized_search = search.casefold()
            representative = next((
                source_record for source_record in group["records"]
                if source_record["source_record_id"].casefold() == normalized_search
                or str(source_record["code_cic"] or "").casefold() == normalized_search
            ), representative)
        results.append({
            "record_type": "canonical_group",
            "source_account_id": representative["id"],
            "source_account_name": group["name"],
            "source_account_code": representative["source_record_id"],
            "code_cic": representative["code_cic"],
            "company_code": representative["company_code"],
            "company_name": representative["company_name"],
            "branch_code": representative["branch_code"],
            "country": group["country"],
            "origin_country": group["country"],
            "operating_countries": sorted(group["operating_countries"]),
            "revenue_ytd": group["revenue"],
            "currency": "EUR",
            "source_record_count": len(group["records"]),
            "canonical_identity_count": len(canonical_ids),
            "business_account_ids": sorted(canonical_ids),
            "assigned_operating_countries": sorted(group["assigned_operating_countries"]),
            "identity_status": "Canonical" if len(canonical_ids) == 1 else "Needs canonical review",
            "key_accounts": sorted(group["key_accounts"]),
            "key_account_ids": sorted(group["key_account_ids"]),
            "customer_country_group_ids": sorted(group["customer_country_group_ids"]),
            "customer_country_groups": [
                {"name": name, "country": group_country}
                for name, group_country in sorted(group["customer_country_groups"])
            ],
            "aliases": sorted({alias for account_id in canonical_ids for alias in aliases_by_account.get(account_id, set())}),
            "source_records": group["records"],
            "mapping_status": sorted(group["statuses"])[0] if group["statuses"] else "Unmapped",
            "issue_count": max(0, len(canonical_ids) - 1),
            "search_text": " ".join(str(value or "") for value in group["search_values"]).casefold(),
        })
    status = request.GET.get("status", "").strip()
    if status == "Unmapped":
        results = [item for item in results if item["mapping_status"] == "Unmapped"]
    elif status:
        results = [item for item in results if item["mapping_status"] == status]
    key_account_filter = request.GET.get("key_account", "").strip()
    if key_account_filter == "unassigned":
        results = [item for item in results if not item["key_account_ids"]]
    elif key_account_filter:
        results = [item for item in results if key_account_filter in item["key_account_ids"]]
    ranked = sorted(results, key=lambda item: (-item["revenue_ytd"], item["source_account_name"].casefold(), item["source_account_code"].casefold()))
    for rank, item in enumerate(ranked, start=1):
        item["revenue_rank"] = rank
    if search:
        results = [item for item in results if search.casefold() in item["search_text"]]
    for item in results:
        item.pop("search_text", None)
    sort = request.GET.get("sort", "revenue_desc").strip().casefold()
    if sort == "revenue_desc":
        results.sort(key=lambda item: (-item["revenue_ytd"], item["source_account_name"].casefold()))
    elif sort == "revenue_asc":
        results.sort(key=lambda item: (item["revenue_ytd"], item["source_account_name"].casefold()))
    else:
        results.sort(key=lambda item: (item["source_account_name"].casefold(), item["country"].casefold()))
    paginator = Paginator(results, min(100, max(10, int(request.GET.get("page_size", 30)))))
    page = paginator.get_page(request.GET.get("page", 1))
    return JsonResponse({"count": paginator.count, "page": page.number, "pages": paginator.num_pages, "view": "canonical", "filters": {"countries": countries, "key_accounts": key_account_filters}, "results": list(page.object_list)})


def _country_account_payload(item, allowed_account_ids, source_codes_by_account, revenue_by_source):
    memberships = [membership for membership in item.memberships.all() if membership.active and membership.business_account_id in allowed_account_ids]
    member_ids = {membership.business_account_id for membership in memberships}
    source_codes = {code for account_id in member_ids for code in source_codes_by_account.get(account_id, set())}
    revenue_values = [revenue_by_source[code] for code in source_codes if code in revenue_by_source]
    key_membership = next((membership for membership in item.key_memberships.all() if membership.active), None)
    grouped_members = []
    for membership in memberships:
        account = membership.business_account
        origin_country = account.origin_country or account.country
        codes = source_codes_by_account.get(account.id, set())
        values = [revenue_by_source[code] for code in codes if code in revenue_by_source]
        grouped_members.append({
            "name": account.canonical_account_name,
            "canonical_account_code": account.canonical_account_code,
            "origin_country": origin_country,
            "operating_countries": account.operating_countries_json or [],
            "business_account_ids": [str(account.id)],
            "source_record_count": len(codes),
            "revenue_ytd": sum(values, Decimal("0")) if values else None,
        })
    return {
        "id": str(item.id), "code": item.country_account_code, "name": item.country_account_name,
        "country": item.country, "description": item.description, "version": item.version,
        "canonical_account_count": len(member_ids),
        "revenue_ytd": sum(revenue_values, Decimal("0")) if revenue_values else None,
        "key_account": None if not key_membership else {"id": str(key_membership.key_account_id), "name": key_membership.key_account.key_account_name},
        "members": sorted(grouped_members, key=lambda value: (value["revenue_ytd"] is None, -(value["revenue_ytd"] or Decimal("0")), value["name"].casefold())),
    }


@login_required
@require_http_methods(["GET", "POST"])
def country_accounts_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    if request.method == "POST":
        try:
            data = _payload(request)
            service = CountryAccountService(request.user)
            member_ids = data.get("business_account_ids", [])
            item = service.create_with_members(
                data.get("name"), data.get("country"), member_ids, data.get("description", ""),
            ) if member_ids else service.create(data.get("name"), data.get("country"), data.get("description", ""))
            return JsonResponse({"ok": True, "database_commit_confirmed": True, "country_account": {"id": str(item.id), "name": item.country_account_name, "country": item.country, "version": item.version}}, status=201)
        except MappingValidationError as exc:
            return _error(exc)
        except Exception:
            return _unexpected("The Country Account could not be created.")
    selected_country = _selected_country(request)
    selected_lob = _selected_revenue_lob(request)
    period = _revenue_period(request)
    records = filter_source_accounts_for_user(SourceAccountRecord.objects.filter(active=True), request.user)
    if selected_country:
        records = _filter_source_accounts_by_operating_country(records, selected_country)
    records = list(records.exclude(canonical_account_id=None).select_related("canonical_account"))
    allowed_ids = {record.canonical_account_id for record in records}
    source_codes_by_account = {}
    for record in records:
        source_codes_by_account.setdefault(record.canonical_account_id, set()).add(record.source_record_id)
    revenue_by_source = {
        row["source_account_code"]: row["value"] or Decimal("0")
        for row in _mining_revenue(selected_lob, selected_country, period["value"]).filter(source_account_code__in={record.source_record_id for record in records}).values("source_account_code").annotate(value=Sum("revenue_ytd_eur"))
    }
    queryset = CountryAccount.objects.filter(active=True).filter(Q(memberships__active=True, memberships__business_account_id__in=allowed_ids) | Q(created_by=request.user)).distinct().prefetch_related("memberships__business_account", "key_memberships__key_account")
    if selected_country:
        queryset = queryset.filter(country__iexact=selected_country)
    selected_id = request.GET.get("country_account_id", "").strip()
    selected_item = queryset.filter(pk=selected_id).first() if selected_id else None
    search = request.GET.get("account_search", "").strip().casefold()
    available = []
    selected_item_country = selected_item.country if selected_item else selected_country
    selected_member_ids = set()
    if selected_item:
        selected_member_ids = set(CountryAccountMembership.objects.filter(
            country_account=selected_item,
            active=True,
        ).values_list("business_account_id", flat=True))
    active_memberships = {
        account_id: (group_id, group_name, group_country, group_description)
        for account_id, group_id, group_name, group_country, group_description in CountryAccountMembership.objects.filter(
            active=True,
            country_account__active=True,
            business_account_id__in=allowed_ids,
        ).values_list(
            "business_account_id",
            "country_account_id",
            "country_account__country_account_name",
            "country_account__country",
            "country_account__description",
        )
    }
    active_group_member_counts = dict(CountryAccountMembership.objects.filter(
        active=True,
        country_account__active=True,
        business_account_id__in=allowed_ids,
    ).values("country_account_id").annotate(member_count=Count("business_account_id")).values_list("country_account_id", "member_count"))
    grouped = {}
    for record in records:
        if record.canonical_account_id in selected_member_ids:
            continue
        account = record.canonical_account
        account_country = CountryAccountService.account_operating_country(account)
        if selected_item_country and account_country != selected_item_country:
            continue
        search_text = f"{account.canonical_account_name} {account.canonical_account_code} {record.source_account_name} {record.source_record_id} {record.code_cic}".casefold()
        if search and search not in search_text:
            continue
        origin_country = account.origin_country or account.country
        key = account.id
        group = grouped.setdefault(key, {"account_id": account.id, "name": account.canonical_account_name, "canonical_account_code": account.canonical_account_code, "origin_country": origin_country, "operating_countries": set(), "business_account_ids": set(), "source_codes": set(), "operating_country": account_country})
        group["operating_countries"].update(record.operating_countries_json or [])
        group["business_account_ids"].add(str(account.id))
        group["source_codes"].add(record.source_record_id)
    for group in grouped.values():
        source_codes = group.pop("source_codes")
        values = [revenue_by_source[code] for code in source_codes if code in revenue_by_source]
        group["business_account_ids"] = sorted(group["business_account_ids"])
        group["operating_countries"] = sorted(group["operating_countries"])
        group["revenue_ytd"] = sum(values, Decimal("0")) if values else None
        current_group = active_memberships.get(group.pop("account_id"))
        if current_group and (
            current_group[3] != CountryAccountService.AUTOMATIC_GROUP_DESCRIPTION
            or active_group_member_counts.get(current_group[0], 0) > 1
        ):
            continue
        group["current_group"] = None if not current_group else {
            "id": str(current_group[0]), "name": current_group[1], "country": current_group[2],
        }
        available.append(group)
    available.sort(key=lambda value: (-(value["revenue_ytd"] or Decimal("0")), value["name"].casefold()))
    group_search = request.GET.get("group_search", "").strip()
    effective_group_search = group_search or search
    if effective_group_search:
        queryset = queryset.filter(
            Q(country_account_name__icontains=effective_group_search)
            | Q(country_account_code__icontains=effective_group_search)
            | Q(memberships__business_account__canonical_account_name__icontains=effective_group_search, memberships__active=True)
        ).distinct()
    group_count = queryset.count()
    listed_groups = list(queryset.order_by("country", "country_account_name")[:200])
    if selected_item and selected_item not in listed_groups:
        listed_groups.append(selected_item)
    payloads = [_country_account_payload(item, allowed_ids, source_codes_by_account, revenue_by_source) for item in listed_groups]
    payloads.sort(key=lambda value: (value["revenue_ytd"] is None, -(value["revenue_ytd"] or Decimal("0")), value["name"].casefold()))
    return JsonResponse({"country_accounts": payloads, "group_count": group_count, "available_account_count": len(available), "available_accounts": available[:100]})


@login_required
@require_http_methods(["PATCH", "DELETE"])
def country_account_detail_api(request, country_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        data = _payload(request)
        service = CountryAccountService(request.user)
        item = service.rename(country_account_id, data.get("name"), data.get("version")) if request.method == "PATCH" else service.archive(country_account_id, data.get("reason"), data.get("version"))
        return JsonResponse({"ok": True, "database_commit_confirmed": True, "country_account": {"id": str(item.id), "name": item.country_account_name, "country": item.country, "version": item.version, "active": item.active}})
    except MappingValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError):
        return _error(MappingValidationError("The Country Account version is invalid.", code="INVALID_VERSION"))
    except Exception:
        return _unexpected("The Country Account could not be updated.")


@login_required
@require_http_methods(["POST", "DELETE"])
def country_account_members_api(request, country_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        data = _payload(request)
        service = CountryAccountService(request.user)
        item = service.add_members(country_account_id, data.get("business_account_ids", [])) if request.method == "POST" else service.remove_members(country_account_id, data.get("business_account_ids", []))
        return JsonResponse({"ok": True, "database_commit_confirmed": True, "country_account": {"id": str(item.id), "name": item.country_account_name, "version": item.version}})
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The Country Account membership could not be saved.")


@login_required
@require_http_methods(["POST"])
def assign_operating_country_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    return JsonResponse({
        "detail": "Direct country assignment is no longer available. Create a Country Account and add Canonical Accounts from the Country Accounts workspace.",
        "code": "MANUAL_COUNTRY_ACCOUNT_REQUIRED",
    }, status=410)


def _key_account_payload(item, allowed_account_ids, source_codes_by_account, revenue_by_source, sites_by_account):
    country_memberships = [
        membership for membership in item.country_memberships.all()
        if membership.active and membership.country_account.active
    ]
    country_groups = []
    group_member_ids = set()
    for membership in country_memberships:
        member_ids = {
            entry.business_account_id
            for entry in membership.country_account.memberships.all()
            if entry.active and entry.business_account_id in allowed_account_ids
        }
        group_member_ids.update(member_ids)
        group_source_codes = {
            code for account_id in member_ids for code in source_codes_by_account.get(account_id, set())
        }
        group_values = [revenue_by_source[code] for code in group_source_codes if code in revenue_by_source]
        country_groups.append({
            "id": str(membership.country_account_id),
            "name": membership.country_account.country_account_name,
            "country": membership.country_account.country,
            "canonical_account_count": len(member_ids),
            "revenue_ytd": sum(group_values, Decimal("0")) if group_values else None,
        })
    account_memberships = [
        membership for membership in item.memberships.all()
        if membership.active and membership.business_account_id in allowed_account_ids
    ]
    member_ids = group_member_ids | {membership.business_account_id for membership in account_memberships}
    source_codes = {code for account_id in member_ids for code in source_codes_by_account.get(account_id, set())}
    revenue_values = [revenue_by_source[code] for code in source_codes if code in revenue_by_source]
    revenue = sum(revenue_values, Decimal("0")) if revenue_values else None
    sites = sorted({site for account_id in member_ids for site in sites_by_account.get(account_id, set())})
    grouped_members = []
    accounts_by_id = {membership.business_account_id: membership.business_account for membership in account_memberships}
    for country_membership in country_memberships:
        for membership in country_membership.country_account.memberships.all():
            if membership.active and membership.business_account_id in allowed_account_ids:
                accounts_by_id[membership.business_account_id] = membership.business_account
    for account in accounts_by_id.values():
        codes = source_codes_by_account.get(account.id, set())
        values = [revenue_by_source[code] for code in codes if code in revenue_by_source]
        grouped_members.append({
            "business_account_ids": [str(account.id)],
            "name": account.canonical_account_name,
            "country": account.origin_country or account.country,
            "source_record_count": len(codes),
            "revenue_ytd": sum(values, Decimal("0")) if values else None,
        })
    return {
        "id": str(item.id), "code": item.key_account_code, "name": item.key_account_name,
        "description": item.description, "version": item.version,
        "canonical_account_count": len(member_ids), "business_account_record_count": len(member_ids),
        "revenue_ytd": revenue, "minesites": sites,
        "customer_country_groups": sorted(country_groups, key=lambda value: (value["country"], value["name"].casefold())),
        "members": sorted(grouped_members, key=lambda value: (value["revenue_ytd"] is None, -(value["revenue_ytd"] or Decimal("0")), value["name"].casefold())),
    }


@login_required
@require_http_methods(["GET", "POST"])
def key_accounts_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    if request.method == "POST":
        try:
            data = _payload(request)
            item = KeyAccountService(request.user).create(data.get("name"), data.get("description", ""))
            return JsonResponse({"ok": True, "key_account": {"id": str(item.id), "name": item.key_account_name, "version": item.version}}, status=201)
        except MappingValidationError as exc:
            return _error(exc)
        except Exception:
            return _unexpected("The Key Account could not be created.")

    selected_country = _selected_country(request)
    selected_lob = _selected_revenue_lob(request)
    period = _revenue_period(request)
    authorized_records = filter_source_accounts_for_user(SourceAccountRecord.objects.filter(active=True), request.user)
    if selected_country:
        authorized_records = _filter_source_accounts_by_operating_country(authorized_records, selected_country)
    authorized_records = list(authorized_records.exclude(canonical_account_id=None).select_related("canonical_account"))
    allowed_ids = {record.canonical_account_id for record in authorized_records}
    source_codes_by_account = {}
    for record in authorized_records:
        source_codes_by_account.setdefault(record.canonical_account_id, set()).add(record.source_record_id)
    all_source_codes = {record.source_record_id for record in authorized_records}
    revenue_by_source = {
        row["source_account_code"]: row["value"] or Decimal("0")
        for row in _mining_revenue(selected_lob, selected_country, period["value"]).filter(source_account_code__in=all_source_codes)
        .values("source_account_code").annotate(value=Sum("revenue_ytd_eur"))
    }
    sites_by_account = {}
    for account_id, site_name in AccountMineSiteMapping.objects.filter(
        active=True, business_account_id__in=allowed_ids,
        relationship_status__in=["Validated", "Published"], minesite__isnull=False,
    ).values_list("business_account_id", "minesite__canonical_minesite_name"):
        sites_by_account.setdefault(account_id, set()).add(site_name)
    key_accounts = KeyAccount.objects.filter(active=True).filter(
        Q(memberships__active=True, memberships__business_account_id__in=allowed_ids)
        | Q(country_memberships__active=True, country_memberships__country_account__memberships__active=True, country_memberships__country_account__memberships__business_account_id__in=allowed_ids)
        | Q(created_by=request.user)
    ).distinct().prefetch_related("memberships__business_account", "country_memberships__country_account__memberships__business_account")
    account_search = request.GET.get("account_search", "").strip().casefold()
    assigned_group_ids = set(KeyAccountCountryMembership.objects.filter(active=True).values_list("country_account_id", flat=True))
    available_groups = []
    group_queryset = CountryAccount.objects.filter(
        active=True,
        memberships__active=True,
        memberships__business_account_id__in=allowed_ids,
    ).exclude(pk__in=assigned_group_ids).distinct().prefetch_related("memberships__business_account")
    if selected_country:
        group_queryset = group_queryset.filter(country=selected_country)
    for country_group in group_queryset:
        member_ids = {
            membership.business_account_id
            for membership in country_group.memberships.all()
            if membership.active and membership.business_account_id in allowed_ids
        }
        source_codes = {code for account_id in member_ids for code in source_codes_by_account.get(account_id, set())}
        if account_search and account_search not in f"{country_group.country_account_name} {country_group.country_account_code} {country_group.country} {' '.join(source_codes)}".casefold():
            continue
        values = [revenue_by_source[code] for code in source_codes if code in revenue_by_source]
        available_groups.append({
            "id": str(country_group.id),
            "name": country_group.country_account_name,
            "country": country_group.country,
            "canonical_account_count": len(member_ids),
            "source_record_count": len(source_codes),
            "revenue_ytd": sum(values, Decimal("0")) if values else None,
        })
    available_groups.sort(key=lambda value: (value["revenue_ytd"] is None, -(value["revenue_ytd"] or Decimal("0")), value["name"].casefold()))
    key_account_results = [_key_account_payload(item, allowed_ids, source_codes_by_account, revenue_by_source, sites_by_account) for item in key_accounts]
    key_sort = request.GET.get("key_sort", "revenue_desc").strip().casefold()
    if key_sort == "revenue_asc":
        key_account_results.sort(key=lambda item: (item["revenue_ytd"] is None, item["revenue_ytd"] or Decimal("0"), item["name"].casefold()))
    elif key_sort == "name":
        key_account_results.sort(key=lambda item: item["name"].casefold())
    else:
        key_account_results.sort(key=lambda item: (item["revenue_ytd"] is None, -(item["revenue_ytd"] or Decimal("0")), item["name"].casefold()))
    return JsonResponse({
        "key_accounts": key_account_results,
        "available_country_group_count": len(available_groups),
        "available_country_groups": available_groups[:100],
    })


@login_required
@require_http_methods(["PATCH", "DELETE"])
def key_account_detail_api(request, key_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        data = _payload(request)
        service = KeyAccountService(request.user)
        if request.method == "PATCH":
            item = service.rename(key_account_id, data.get("name"), data.get("version"))
            return JsonResponse({
                "ok": True, "database_commit_confirmed": True,
                "key_account": {"id": str(item.id), "name": item.key_account_name, "version": item.version},
            })
        item = service.archive(key_account_id, data.get("reason"), data.get("version"))
        return JsonResponse({
            "ok": True, "database_commit_confirmed": True,
            "key_account": {"id": str(item.id), "name": item.key_account_name, "version": item.version, "active": False},
        })
    except MappingValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError):
        return _error(MappingValidationError("The Key Account version is invalid.", code="INVALID_VERSION"))
    except Exception:
        return _unexpected("The Key Account could not be updated.")


@login_required
@require_http_methods(["POST", "DELETE"])
def key_account_members_api(request, key_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        data = _payload(request)
        service = KeyAccountService(request.user)
        if request.method == "POST":
            item = service.add_members(key_account_id, data.get("business_account_ids", []))
        else:
            item = service.remove_members(key_account_id, data.get("business_account_ids", []))
        return JsonResponse({"ok": True, "key_account": {"id": str(item.id), "name": item.key_account_name, "version": item.version}, "database_commit_confirmed": True})
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The Key Account membership could not be saved.")


@login_required
@require_http_methods(["POST", "DELETE"])
def key_account_country_members_api(request, key_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        data = _payload(request)
        service = KeyAccountService(request.user)
        item = service.add_country_members(key_account_id, data.get("country_account_ids", [])) if request.method == "POST" else service.remove_country_members(key_account_id, data.get("country_account_ids", []))
        return JsonResponse({"ok": True, "database_commit_confirmed": True, "key_account": {"id": str(item.id), "name": item.key_account_name, "version": item.version}})
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The Key Account Country Account membership could not be saved.")


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def canonical_account_aliases_api(request, business_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        service = BusinessAccountAliasService(request.user)
        if request.method == "POST":
            item = service.create(business_account_id, _payload(request).get("alias"))
        elif request.method == "DELETE":
            item = service.archive(business_account_id, _payload(request).get("alias_id"))
        else:
            _, aliases = service.list(business_account_id)
            return JsonResponse({"aliases": [{"id": item.pk, "alias": item.alias, "source": item.source_system, "status": item.validation_status} for item in aliases]})
        account, aliases = service.list(business_account_id)
        return JsonResponse({
            "ok": True,
            "database_commit_confirmed": True,
            "alias": {"id": item.pk, "alias": item.alias, "active": item.active},
            "canonical_account": {"id": str(account.pk), "name": account.canonical_account_name},
            "aliases": [{"id": value.pk, "alias": value.alias, "source": value.source_system, "status": value.validation_status} for value in aliases],
        })
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The Canonical Account alias could not be saved.")


@login_required
@require_http_methods(["POST", "DELETE"])
def canonical_account_operating_country_api(request, business_account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        service = BusinessAccountOperatingCountryService(request.user)
        account = (
            service.assign(business_account_id, _payload(request).get("country"))
            if request.method == "POST"
            else service.clear(business_account_id)
        )
        return JsonResponse({
            "ok": True,
            "database_commit_confirmed": True,
            "business_account_id": str(account.pk),
            "assigned_operating_country": account.assigned_operating_country or None,
            "suggested_operating_countries": account.operating_countries_json or [],
        })
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The Canonical Account operating country could not be saved.")


@login_required
def account_detail_api(request, account_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    authorized_records = filter_source_accounts_for_user(
        SourceAccountRecord.objects.select_related("canonical_account").filter(active=True), request.user,
    )
    selected_country = _selected_country(request)
    if selected_country:
        authorized_records = _filter_source_accounts_by_operating_country(authorized_records, selected_country)
    record = authorized_records.filter(pk=account_id).first()
    if not record:
        return JsonResponse({"detail": "Not found"}, status=404)
    canonical_view = request.GET.get("view", "source").strip().casefold() == "canonical"
    peer_records = authorized_records.filter(pk=record.pk)
    if canonical_view:
        peer_records = authorized_records.filter(
            normalized_account_name=record.normalized_account_name,
            country__iexact=record.country,
        )
    peer_records = list(peer_records.select_related("canonical_account"))
    peer_ids = [item.id for item in peer_records]
    canonical_ids = {item.canonical_account_id for item in peer_records if item.canonical_account_id}
    allowed_site_ids = filter_minesites_for_user(MineSite.objects.filter(active=True), request.user).values_list("pk", flat=True)
    candidates = AccountMineSiteCandidate.objects.filter(
        source_account_id__in=peer_ids, status="Suggested", candidate_minesite_id__in=allowed_site_ids,
    ).select_related("candidate_minesite").prefetch_related("evidence").order_by("-confidence_score")[:5]
    selected_lob = _selected_revenue_lob(request)
    period = _revenue_period(request)
    source_codes = [item.source_record_id for item in peer_records]
    all_account_revenue = _mining_revenue("", selected_country, period["value"]).filter(source_account_code__in=source_codes)
    revenue = _mining_revenue(selected_lob, selected_country, period["value"]).filter(source_account_code__in=source_codes)
    previous_revenue = _mining_revenue(selected_lob, selected_country, str(period["year"] - 1)).filter(source_account_code__in=source_codes) if period["year"] else RevenueSourceSnapshot.objects.none()
    selected_revenue_value = revenue.aggregate(value=Sum("revenue_ytd_eur"))["value"] if revenue.exists() else None
    if previous_revenue.exists():
        previous_revenue_value = previous_revenue.aggregate(value=Sum("revenue_ytd_eur"))["value"]
    elif period["value"] == "ytd" and revenue.exists():
        previous_revenue_value = revenue.aggregate(value=Sum("revenue_previous_year_eur"))["value"]
    else:
        previous_revenue_value = None
    mappings = AccountMineSiteMapping.objects.select_related("business_account", "minesite").filter(
        active=True, business_account_id__in=canonical_ids,
    ) if canonical_ids else AccountMineSiteMapping.objects.none()
    source_accounts_by_canonical = {}
    for peer in peer_records:
        if not peer.canonical_account_id:
            continue
        source_accounts_by_canonical.setdefault(peer.canonical_account_id, []).append({
            "id": str(peer.id),
            "name": peer.source_account_name,
            "code": peer.source_record_id,
            "code_cic": peer.code_cic,
            "company_code": peer.company_code,
            "company_name": ((peer.source_payload_json or {}).get("revenue_company_name_values") or [None])[0],
            "origin_country": peer.origin_country or peer.country,
        })
    preferred_account_id = mappings.values_list("business_account_id", flat=True).first() or record.canonical_account_id
    preferred_account = BusinessAccount.objects.filter(pk=preferred_account_id).first() if preferred_account_id else None
    mapping_site_names = list(mappings.exclude(minesite__isnull=True).values_list("minesite__normalized_minesite_name", flat=True))
    fleet_by_site = _equipment_summaries(
        mapping_site_names + [item.candidate_minesite.normalized_minesite_name for item in candidates]
    )
    account_fleet = {"count": 0, "serial_count": 0, "models": [], "families": [], "source": "EquipmentList_MiningProd"}
    if mapping_site_names:
        rows = EquipmentFleetAnalysis.objects.filter(active=True, normalized_site__in=mapping_site_names)
        account_fleet = {
            "count": rows.count(),
            "serial_count": rows.exclude(serial_number="").values("serial_number").distinct().count(),
            "models": list(rows.exclude(model="").values_list("model", flat=True).distinct()[:20]),
            "families": list(rows.exclude(equipment_family="").values_list("equipment_family", flat=True).distinct()[:20]),
            "source": "EquipmentList_MiningProd",
        }
    aliases = BusinessAccountAliasService(request.user).list(preferred_account_id)[1] if preferred_account_id else []
    return JsonResponse({
        "account": {"source_account_id": str(record.id), "business_account_id": str(preferred_account_id) if preferred_account_id else None, "name": preferred_account.canonical_account_name if canonical_view and preferred_account else record.source_account_name, "code": record.source_record_id, "code_cic": record.code_cic, "country": record.origin_country or record.country, "origin_country": record.origin_country or record.country, "operating_countries": record.operating_countries_json or [], "assigned_operating_country": preferred_account.assigned_operating_country if preferred_account else "", "view": "canonical" if canonical_view else "source", "source_record_count": len(peer_records), "source_account_codes": source_codes},
        "revenue_summary": {"scope": "Mining", "scope_label": "Canonical Account Revenue" if canonical_view else "Source Record Revenue", "division": MINING_DIVISION, "selected_lob": selected_lob or None, "selected_category": MINING_REVENUE_LABELS.get(selected_lob, "All Mining"), "period": period["value"], "period_label": period["label"], "ytd": selected_revenue_value, "previous_year": previous_revenue_value, "by_category": _revenue_breakdown(all_account_revenue) if all_account_revenue.exists() else []},
        "fleet_summary": account_fleet,
        "aliases": [{"id": item.pk, "alias": item.alias, "source": item.source_system, "status": item.validation_status} for item in aliases],
        "current_mappings": [
            _mapping_json(item, source_accounts_by_canonical.get(item.business_account_id, []))
            for item in mappings
        ],
        "candidate_minesites": [{"id": str(item.id), "minesite": {"id": str(item.candidate_minesite_id), "name": item.candidate_minesite.canonical_minesite_name, "country": item.candidate_minesite.country}, "confidence": item.confidence_score, "method": item.suggestion_method, "evidence": [{"id": evidence.pk, "type": evidence.evidence_type, "description": evidence.description, "weight": evidence.weight} for evidence in item.evidence.all()], "conflicts": item.conflict_summary_json, "fleet_summary": fleet_by_site.get(item.candidate_minesite.normalized_minesite_name, {"count": 0, "serial_count": 0, "models": [], "families": [], "source": "EquipmentList_MiningProd"})} for item in candidates],
        "permissions": {"can_edit": _require(request.user, "edit_business_mapping"), "can_validate": _require(request.user, "validate_business_mapping"), "can_publish": _require(request.user, "publish_business_mapping")},
    })


@login_required
@require_http_methods(["POST"])
def generate_candidates_api(request):
    if not _require(request.user, "propose_business_mapping") or not feature_enabled("ENABLE_BUSINESS_MAPPING_SUGGESTIONS", request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        payload = _payload(request)
        record = filter_source_accounts_for_user(
            SourceAccountRecord.objects.filter(active=True), request.user,
        ).get(pk=payload.get("source_account_id"))
        candidates = AccountMineSiteSuggestionService.generate_for_account(
            record, minesites=filter_minesites_for_user(MineSite.objects.filter(active=True), request.user),
        )
        return JsonResponse({"ok": True, "candidate_count": len(candidates)})
    except (MappingValidationError, SourceAccountRecord.DoesNotExist) as exc:
        return _error(exc if isinstance(exc, MappingValidationError) else MappingValidationError("Account not found.", status=404))
    except Exception:
        return _unexpected("Candidate generation is temporarily unavailable.")


@login_required
def minesites_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    queryset = filter_minesites_for_user(MineSite.objects.filter(active=True), request.user)
    search = request.GET.get("search", "").strip()
    if search:
        queryset = queryset.filter(Q(canonical_minesite_name__icontains=search) | Q(minesite_code__icontains=search))
    return JsonResponse({"results": [{"id": str(item.id), "code": item.minesite_code, "name": item.canonical_minesite_name, "country": item.country, "status": item.status} for item in queryset[:100]]})


def _validation_service(request):
    return AccountMineSiteValidationService(request.user, request.META.get("REMOTE_ADDR"), "Business Mapping Studio 1.0")


@login_required
@require_http_methods(["POST"])
def mappings_api(request):
    try:
        return JsonResponse(_validation_service(request).save_draft(_payload(request)))
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping could not be saved in Mining 360. No validation was recorded.")


@login_required
@require_http_methods(["PATCH"])
def mapping_detail_api(request, mapping_id):
    try:
        payload = _payload(request)
        payload["mapping_id"] = str(mapping_id)
        return JsonResponse(_validation_service(request).save_draft(payload))
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping could not be saved in Mining 360. No validation was recorded.")


@login_required
@require_http_methods(["POST"])
def validate_mapping_api(request, mapping_id=None):
    try:
        return JsonResponse(_validation_service(request).validate(_payload(request), mapping_id))
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping could not be saved in Mining 360. No validation was recorded.")


@login_required
@require_http_methods(["POST"])
def archive_mapping_api(request, mapping_id):
    try:
        return JsonResponse(_validation_service(request).archive(_payload(request), mapping_id))
    except MappingValidationError as error:
        return _error(error)
    except Exception:
        return _unexpected("The mapping could not be removed from the current Mapping state.")


@login_required
@require_http_methods(["POST"])
def no_site_required_api(request, mapping_id=None):
    try:
        return JsonResponse(_validation_service(request).validate(_payload(request), mapping_id, no_site_required=True))
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping could not be saved in Mining 360. No validation was recorded.")


@login_required
@require_http_methods(["POST"])
def bulk_validate_api(request):
    if not feature_enabled("ENABLE_BUSINESS_MAPPING_BULK_VALIDATION", request.user) or not _require(request.user, "bulk_validate_business_mapping"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        payload = _payload(request)
        items = payload.get("mappings") or []
        if not items or len(items) > 100:
            raise MappingValidationError("Select between 1 and 100 mappings for bulk validation.")
        with transaction.atomic():
            results = [_validation_service(request).validate(item, item.get("mapping_id")) for item in items]
        return JsonResponse({"ok": True, "total_selected": len(items), "validated": len(results), "failed": 0, "skipped": 0, "results": results})
    except MappingValidationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping batch could not be saved. No validation was recorded.")


@login_required
@require_http_methods(["POST"])
def allocations_api(request):
    if not feature_enabled("ENABLE_BUSINESS_MAPPING_REVENUE_ALLOCATION", request.user) or not _require(request.user, "manage_revenue_allocations"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        payload = _payload(request)
        mapping = AccountMineSiteMapping.objects.select_related("business_account", "minesite").filter(pk=payload.get("mapping_id"), active=True).first()
        if not mapping or not mapping.minesite_id:
            raise MappingValidationError("Select a valid Account and MineSite mapping.")
        _validation_service(request)._enforce_scope(mapping)
        percentage = Decimal(str(payload.get("allocation_percentage")))
        if percentage < 0 or percentage > 100:
            raise MappingValidationError("Allocation percentage must be between 0 and 100.")
        valid_from = date.fromisoformat(str(payload.get("valid_from")))
        scope = {
            "business_account": mapping.business_account, "lob": str(payload.get("lob") or ""),
            "division": str(payload.get("division") or ""), "distribution_channel": str(payload.get("distribution_channel") or ""),
            "company_code": str(payload.get("company_code") or ""), "branch_code": str(payload.get("branch_code") or ""),
        }
        with transaction.atomic():
            total = RevenueSiteAllocationRule.objects.select_for_update().filter(**scope, status__in=["Validated", "Published"]).aggregate(value=Sum("allocation_percentage"))["value"] or Decimal("0")
            if total + percentage > Decimal("100.0001"):
                raise MappingValidationError("The active allocation exceeds 100% for the selected scope.", code="ALLOCATION_EXCEEDS_100")
            rule = RevenueSiteAllocationRule.objects.create(
                **scope, minesite=mapping.minesite, allocation_method=str(payload.get("allocation_method") or "Fixed percentage"),
                allocation_percentage=percentage, valid_from=valid_from, valid_to=date.fromisoformat(payload["valid_to"]) if payload.get("valid_to") else None,
                status="Validated", validated_by=request.user, validated_at=timezone.now(),
            )
            MappingAuditLog.objects.create(actor=request.user, action="Revenue allocation changed", entity_type="RevenueSiteAllocationRule", entity_id=str(rule.id), new_value_json={"mapping_id": str(mapping.id), "percentage": str(percentage), "lob": scope["lob"]})
        return JsonResponse({"ok": True, "allocation": {"id": str(rule.id), "percentage": rule.allocation_percentage, "status": rule.status}, "database_commit_confirmed": True})
    except (MappingValidationError, InvalidOperation, ValueError, TypeError) as exc:
        return _error(exc if isinstance(exc, MappingValidationError) else MappingValidationError("The allocation payload is invalid."))
    except Exception:
        return _unexpected("The revenue allocation could not be saved in Mining 360.")


@login_required
@require_http_methods(["POST"])
def reject_candidate_api(request, candidate_id):
    if not _require(request.user, "reject_business_mapping"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    candidate = AccountMineSiteCandidate.objects.filter(pk=candidate_id).first()
    if not candidate:
        return JsonResponse({"detail": "Not found"}, status=404)
    candidate.status = "Rejected"
    candidate.reviewed_by = request.user
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    MappingAuditLog.objects.create(actor=request.user, action="Candidate rejected", entity_type="AccountMineSiteCandidate", entity_id=str(candidate.id), reason=str(_payload(request).get("reason") or ""))
    return JsonResponse({"ok": True})


@login_required
def conflicts_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    source_accounts = filter_source_accounts_for_user(SourceAccountRecord.objects.filter(active=True), request.user)
    selected_country = _selected_country(request)
    if selected_country:
        source_accounts = _filter_source_accounts_by_operating_country(source_accounts, selected_country)
    account_ids = source_accounts.exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True)
    return JsonResponse({"results": BusinessMappingConflictService.list_conflicts(account_ids=account_ids)})


@login_required
@require_http_methods(["GET", "POST"])
def publications_api(request):
    if request.method == "GET":
        if not _require(request.user):
            return JsonResponse({"detail": "Forbidden"}, status=403)
        return JsonResponse({"results": [{"id": str(item.id), "version": item.version, "status": item.status, "mapping_count": item.mapping_count, "published_at": item.published_at} for item in MappingPublication.objects.all()[:100]]})
    if not feature_enabled("ENABLE_BUSINESS_MAPPING_PUBLICATION", request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    try:
        publication = MappingPublicationService(request.user, request.META.get("REMOTE_ADDR")).publish(str(_payload(request).get("reason") or ""))
        return JsonResponse({"ok": True, "publication": {"id": str(publication.id), "version": publication.version, "status": publication.status}})
    except (MappingPublicationError, MappingValidationError) as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping publication could not be completed.")


@login_required
def publication_detail_api(request, publication_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    publication = MappingPublication.objects.filter(pk=publication_id).first()
    if not publication:
        return JsonResponse({"detail": "Not found"}, status=404)
    return JsonResponse({"id": str(publication.id), "version": publication.version, "status": publication.status, "mapping_count": publication.mapping_count, "snapshot": publication.snapshot_json, "changes": publication.change_summary_json, "published_at": publication.published_at})


@login_required
@require_http_methods(["POST"])
def publication_preview_api(request):
    if not feature_enabled("ENABLE_BUSINESS_MAPPING_PUBLICATION", request.user) or not _require(request.user, "publish_business_mapping"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    return JsonResponse({"ok": True, "preview": MappingPublicationService(request.user).preview()})


@login_required
@require_http_methods(["POST"])
def rollback_publication_api(request, publication_id):
    if not feature_enabled("ENABLE_BUSINESS_MAPPING_PUBLICATION", request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    publication = MappingPublication.objects.filter(pk=publication_id).first()
    if not publication:
        return JsonResponse({"detail": "Not found"}, status=404)
    try:
        result = MappingPublicationService(request.user, request.META.get("REMOTE_ADDR")).rollback(publication, str(_payload(request).get("reason") or ""))
        return JsonResponse({"ok": True, "publication": {"id": str(result.id), "version": result.version}})
    except MappingPublicationError as exc:
        return _error(exc)
    except Exception:
        return _unexpected("The mapping rollback could not be completed.")


def _synchronization_run_json(run):
    effective_status = run.status
    reference_time = run.started_at or run.created_at
    heartbeat = run.heartbeat_at or reference_time
    stale_after = timedelta(minutes=2 if effective_status == "Queued" else 15)
    stale = effective_status in {"Queued", "Running"} and heartbeat and heartbeat < timezone.now() - stale_after
    if stale:
        effective_status = "Failed"
        MappingSynchronizationRun.objects.filter(pk=run.pk, status__in=["Queued", "Running"]).update(
            status="Failed",
            completed_at=timezone.now(),
            progress_percent=100,
            stage_code="worker_timeout",
            stage_label="Synchronization worker stopped responding",
            failure_count=1,
            errors_json=[{"code": "SYNCHRONIZATION_WORKER_TIMEOUT", "message": "The synchronization worker stopped responding."}],
        )
    progress_by_status = {
        "Queued": (10, "Waiting for the synchronization worker"),
        "Running": (55, "Retrieving and validating source data"),
        "Completed": (100, "Source synchronization completed"),
        "Partial": (85, "One source component could not be processed"),
        "Failed": (100, "Source synchronization failed"),
        "Cancelled": (100, "Source synchronization cancelled"),
    }
    fallback_progress, fallback_stage = progress_by_status.get(effective_status, (0, "Preparing synchronization"))
    progress = run.progress_percent if run.progress_percent or effective_status == "Queued" else fallback_progress
    stage = run.stage_label or fallback_stage
    if stale:
        stage = "Synchronization did not start within the expected time. You can retry."
    display_status = {
        "Queued": "Not Started", "Running": "Running", "Completed": "Completed",
        "Partial": "Partially Completed", "Failed": "Failed", "Cancelled": "Cancelled",
    }.get(effective_status, effective_status)
    if effective_status == "Completed" and run.warnings_json:
        display_status = "Completed with Warnings"
    return {
        "id": str(run.id),
        "status": effective_status,
        "display_status": display_status,
        "stored_status": run.status,
        "stale": stale,
        "progress_percent": progress,
        "stage": stage,
        "source": run.source,
        "records_read": run.records_read,
        "records_created": run.records_created,
        "records_updated": run.records_updated,
        "records_unchanged": run.records_unchanged,
        "records_rejected": run.records_rejected,
        "failure_count": run.failure_count,
        "warning_count": len(run.warnings_json or []),
        "error_count": len(run.errors_json or []),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "status_url": f"/api/business-mapping/synchronization/{run.id}/",
    }


@login_required
@require_http_methods(["GET", "POST"])
def synchronization_api(request):
    if request.method == "GET":
        if not _require(request.user):
            return JsonResponse({"detail": "Forbidden"}, status=403)
        run = MappingSynchronizationRun.objects.first()
        return JsonResponse({"ok": True, "run": _synchronization_run_json(run) if run else None})
    if not _require(request.user, "synchronize_business_mapping_sources"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    active_run = MappingSynchronizationRun.objects.filter(
        status__in=["Queued", "Running"],
        created_at__gte=timezone.now() - timedelta(minutes=15),
    ).first()
    if active_run:
        serialized = _synchronization_run_json(active_run)
        if serialized["status"] == "Queued":
            enqueue_business_mapping_sync(active_run)
        elif serialized["status"] == "Failed":
            active_run = None
        if active_run:
            return JsonResponse({"ok": True, "run": serialized, "reused": True}, status=200)
    run = BusinessMappingSourceSynchronizationService(request.user).queue()
    enqueue_business_mapping_sync(run)
    return JsonResponse({"ok": True, "run": _synchronization_run_json(run), "reused": False}, status=202)


@login_required
def synchronization_status_api(request, run_id):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    run = MappingSynchronizationRun.objects.filter(pk=run_id).first()
    if not run:
        return JsonResponse({"detail": "Not found"}, status=404)
    return JsonResponse({"ok": True, "run": _synchronization_run_json(run)})


@login_required
def audit_api(request):
    if not _require(request.user, "view_business_mapping_audit"):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    rows = MappingAuditLog.objects.select_related("actor")[:200]
    return JsonResponse({"results": [{"id": item.pk, "action": item.action, "entity_type": item.entity_type, "entity_id": item.entity_id, "actor": item.actor.get_username() if item.actor else None, "reason": item.reason, "timestamp": item.timestamp} for item in rows]})


@login_required
def published_mapping_api(request):
    if not _require(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    publication = MappingPublication.objects.filter(status="Published").order_by("-version").first()
    return JsonResponse({"publication_version": publication.version if publication else None, "results": (publication.snapshot_json or {}).get("mappings", []) if publication else []})
