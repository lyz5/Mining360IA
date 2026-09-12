from __future__ import annotations

import hashlib
import json
import threading
import time
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .business_mapping_source_service import _extract_rows
from .models import (
    PowerBIReport,
    ReconciliationAccountingEntry,
    ReconciliationBufferSyncRun,
    ReconciliationDeliveryInvoiceLink,
    ReconciliationInvoiceHeader,
    ReconciliationOrderHeader,
    ReconciliationOrderLine,
    ReconciliationSourceSnapshot,
)
from .power_automate import PowerAutomateTransientError, execute_dax_via_flow
from .powerbi import execute_dataset_dax
from .reconciliation_service import RevenueOrderReconciliationService


LOGISTICS_MODEL = "Mine Logistics Report"
CA_MODEL = "Customer Fleet & Revenue Planning Model"
DEFAULT_CA_DATASET_ID = "a67ebcac-97d0-4d46-b84d-8109cd2c804a"
PAGE_SIZE = 40000
MAX_SOURCE_ROWS = 2000000


class ReconciliationBufferError(RuntimeError):
    pass


def _normalized(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text.casefold() if char.isalnum())


def _value(row, *names, default=""):
    lookup = {_normalized(str(key).split("[")[-1].rstrip("]")): value for key, value in (row or {}).items()}
    for name in names:
        value = lookup.get(_normalized(name))
        if value is not None:
            return value
    return default


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _fingerprint(row, position):
    raw = json.dumps(row, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(f"{raw}|{position}".encode("utf-8")).hexdigest()


class SemanticReconciliationBufferService:
    SOURCE_DEFINITIONS = {
        "ORDER_HEADERS": {
            "source": "'OrderHeader'",
            "cursor": "COMBINEVALUES(\"|\", COALESCE(\"\" & 'OrderHeader'[CODESOCIETE], \"\"), COALESCE(\"\" & 'OrderHeader'[CODESUCC], \"\"), COALESCE(\"\" & 'OrderHeader'[NUMEROCOMMANDE], \"\"), COALESCE(\"\" & 'OrderHeader'[PK], \"\"))",
            "columns": """
    "nent_soc", 'OrderHeader'[CODESOCIETE],
    "nent_succ", 'OrderHeader'[CODESUCC],
    "nent_numcde", 'OrderHeader'[NUMEROCOMMANDE],
    "order_header_key", 'OrderHeader'[PK],
    "nent_numcli", 'OrderHeader'[NUMCLIENT],
    "customer_name", 'OrderHeader'[NOMCLIENT],
    "nent_datecde", 'OrderHeader'[DATECOMMANDE],
    "eta", 'OrderHeader'[ETA],
    "order_type", 'OrderHeader'[TYPECOMMANDE],
    "urgency", 'OrderHeader'[URGENCE],
    "line_count", 'OrderHeader'[NOMBRELIGNE],
    "currency", 'OrderHeader'[DEVISE],
    "transport", 'OrderHeader'[TRANSPORT],
    "description", 'OrderHeader'[LIBELLECOMMANDE],
    "invoicing_status", 'OrderHeader'[STATUTFACTURATION],
    "order_status", 'OrderHeader'[STATUTORDERS],
    "order_amount", 'OrderHeader'[ORDER_AMOUNT],
    "amount_eur", 'OrderHeader'[MontantEUR],
    "operation_type", 'OrderHeader'[Type_Operation],
    "subsidiary_reference", 'OrderHeader'[REFERENCE_CMDE_FILIALE],
    "international_reference", 'OrderHeader'[REFERENCE_CMDE_INTERNATIONALE]
""",
        },
        "ORDERS": {
            "source": "'OrderLineItems'",
            "cursor": "COMBINEVALUES(\"|\", COALESCE(\"\" & 'OrderLineItems'[CODESOCIETE], \"\"), COALESCE(\"\" & 'OrderLineItems'[CODESUCCURSALE], \"\"), COALESCE(\"\" & 'OrderLineItems'[NUMEROCOMMANDE], \"\"), COALESCE(\"\" & 'OrderLineItems'[NUMEROLIGNE], \"\"), COALESCE(\"\" & 'OrderLineItems'[SK], \"\"))",
            "columns": """
    "nlig_soc", 'OrderLineItems'[CODESOCIETE],
    "nlig_succ", 'OrderLineItems'[CODESUCCURSALE],
    "nlig_numcde", 'OrderLineItems'[NUMEROCOMMANDE],
    "nlig_nolign", 'OrderLineItems'[NUMEROLIGNE],
    "order_header_key", 'OrderLineItems'[SK],
    "nlig_numcli", 'OrderLineItems'[NUMEROCLIENT],
    "customer_name", LOOKUPVALUE(
        Customuer_base[CBSE_NOMCLI],
        Customuer_base[CBSE_NUMCLI], 'OrderLineItems'[NUMEROCLIENT]
    ),
    "nlig_refp", 'OrderLineItems'[REFERENCEP],
    "nlig_datecde", 'OrderLineItems'[DATECOMMANDE],
    "nlig_qtecde", 'OrderLineItems'[QUANTITECDE],
    "nlig_qtefac", 'OrderLineItems'[QUANTITEFACTUREE],
    "nlig_qteliv", 'OrderLineItems'[QUANTITELIV],
    "nlig_pxvteht", 'OrderLineItems'[AMOUNTNET],
    "StatutGlobal", 'OrderLineItems'[StatutGlobal]
""",
        },
        "DELIVERY_INVOICE": {
            "source": "'Neg_llf'",
            "cursor": "COMBINEVALUES(\"|\", COALESCE(\"\" & 'Neg_llf'[NLLF_SOC], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_SUCC], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_NUMCDE], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_NOLIGN], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_NUMLIV], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_NUMFAC], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_REFP], \"\"), COALESCE(\"\" & 'Neg_llf'[NLLF_HISTO], \"\"), COALESCE(\"\" & 'Neg_llf'[INTEGRATION_DATE], \"\"))",
            "columns": """
    "nllf_soc", 'Neg_llf'[NLLF_SOC],
    "nllf_succ", 'Neg_llf'[NLLF_SUCC],
    "nllf_numcde", 'Neg_llf'[NLLF_NUMCDE],
    "nllf_nolign", 'Neg_llf'[NLLF_NOLIGN],
    "nllf_numcli", 'Neg_llf'[NLLF_NUMCLI],
    "nllf_numliv", 'Neg_llf'[NLLF_NUMLIV],
    "nllf_numfac", 'Neg_llf'[NLLF_NUMFAC],
    "nllf_succfac", 'Neg_llf'[NLLF_SUCCFAC],
    "nllf_refp", 'Neg_llf'[NLLF_REFP],
    "nllf_qtecde", 'Neg_llf'[NLLF_QTECDE],
    "nllf_qtefac", 'Neg_llf'[NLLF_QTEFAC],
    "nllf_qteliv", 'Neg_llf'[NLLF_QTELIV],
    "nllf_pxvteht", 'Neg_llf'[NLLF_PXVTEHT],
    "nllf_pos", 'Neg_llf'[NLLF_POS],
    "nllf_natop", 'Neg_llf'[NLLF_NATOP]
""",
        },
        "INVOICES": {
            "source": "'Neg_FAC'",
            "cursor": "COMBINEVALUES(\"|\", COALESCE(\"\" & 'Neg_FAC'[NFAC_SOC], \"\"), COALESCE(\"\" & 'Neg_FAC'[NFAC_SUCC], \"\"), COALESCE(\"\" & 'Neg_FAC'[NFAC_SERV], \"\"), COALESCE(\"\" & 'Neg_FAC'[NFAC_NUMFAC], \"\"), COALESCE(\"\" & 'Neg_FAC'[NFAC_HASHCODE], \"\"))",
            "columns": """
    "nfac_soc", 'Neg_FAC'[NFAC_SOC],
    "nfac_succ", 'Neg_FAC'[NFAC_SUCC],
    "nfac_serv", 'Neg_FAC'[NFAC_SERV],
    "nfac_numfac", 'Neg_FAC'[NFAC_NUMFAC],
    "nfac_numfacm", 'Neg_FAC'[NFAC_NUMFACM],
    "nfac_numcli", 'Neg_FAC'[NFAC_NUMCLI],
    "nfac_datefac", 'Neg_FAC'[NFAC_DATEFAC],
    "nfac_code", 'Neg_FAC'[NFAC_CODE],
    "nfac_pos", 'Neg_FAC'[NFAC_POS],
    "nfac_devise", 'Neg_FAC'[NFAC_DEVISE]
""",
        },
        "ACCOUNTING_REVENUE": {
            "source": "FILTER('ChriffreAffaire', 'ChriffreAffaire'[Division] = \"MI\")",
            "cursor": "COALESCE(\"\" & 'ChriffreAffaire'[feca_eca_sk], \"\")",
            "columns": """
    "entry_id", 'ChriffreAffaire'[feca_eca_sk],
    "company_code", 'ChriffreAffaire'[Code Société],
    "branch_code", 'ChriffreAffaire'[Code Succursale],
    "customer_number", 'ChriffreAffaire'[Code client Irium],
    "document_number", 'ChriffreAffaire'[Facture],
    "accounting_date", 'ChriffreAffaire'[Date ecritures],
    "debit_eur", 'ChriffreAffaire'[Montant débit Euro],
    "credit_eur", 'ChriffreAffaire'[Montant credit Euro],
    "consolidated_amount", 'ChriffreAffaire'[CA euro],
    "lob", 'ChriffreAffaire'[LOB],
    "journal_code", 'ChriffreAffaire'[Code journal],
    "entry_label", 'ChriffreAffaire'[Libellé écriture comptable]
""",
        },
    }

    def __init__(self, user=None):
        self.user = user

    def queue(self):
        return ReconciliationBufferSyncRun.objects.create(initiated_by=self.user, heartbeat_at=timezone.now())

    @staticmethod
    def _progress(run, percent, code, label, **updates):
        values = {"progress_percent": percent, "stage_code": code, "stage_label": label, "heartbeat_at": timezone.now(), **updates}
        ReconciliationBufferSyncRun.objects.filter(pk=run.pk).update(**values)

    @staticmethod
    def _query(dataset_id, dataset_name, dax):
        try:
            return execute_dataset_dax(dataset_id, dax), "Power BI ExecuteQueries"
        except Exception as direct_error:
            payload = execute_dax_via_flow({
                "datasetId": dataset_id,
                "datasetName": dataset_name,
                "query": dax,
                "question": "Mining 360 Invoice Tracking buffer synchronization",
                "section": "invoice_tracking",
                "filters": {},
                "roles": [],
            })
            return _extract_rows(payload), f"Power Automate fallback ({type(direct_error).__name__})"

    @classmethod
    def build_page_query(cls, kind, last_cursor="", page_size=PAGE_SIZE):
        definition = cls.SOURCE_DEFINITIONS[kind]
        escaped_cursor = str(last_cursor).replace('"', '""')
        return f"""
DEFINE
    VAR ProjectedRows =
        SELECTCOLUMNS(
            {definition['source']},
            "_cursor", {definition['cursor']},
            {definition['columns']}
        )
    VAR RemainingRows = FILTER(ProjectedRows, [_cursor] > "{escaped_cursor}")
EVALUATE
    TOPN({page_size + 1}, RemainingRows, [_cursor], ASC)
ORDER BY [_cursor] ASC
"""

    def _iter_pages(self, dataset_id, dataset_name, kind, *, last_cursor="", total=0):
        while True:
            for page_attempt in range(4):
                try:
                    rows, method = self._query(
                        dataset_id,
                        dataset_name,
                        self.build_page_query(kind, last_cursor),
                    )
                    break
                except PowerAutomateTransientError:
                    if page_attempt >= 3:
                        raise
                    time.sleep(2 ** page_attempt)
            page = rows[:PAGE_SIZE]
            if not page:
                return
            next_cursor = str(_value(page[-1], "_cursor"))
            if not next_cursor or next_cursor <= last_cursor:
                raise ReconciliationBufferError(
                    f"{kind} returned an invalid semantic pagination cursor."
                )
            if len(rows) > PAGE_SIZE and str(_value(rows[PAGE_SIZE], "_cursor")) == next_cursor:
                raise ReconciliationBufferError(
                    f"{kind} has duplicate records at a pagination boundary; no rows were skipped."
                )
            total += len(page)
            if total > MAX_SOURCE_ROWS:
                raise ReconciliationBufferError(
                    f"{kind} exceeds the certified source limit of {MAX_SOURCE_ROWS} rows."
                )
            yield page, method, total
            if len(rows) <= PAGE_SIZE:
                return
            last_cursor = next_cursor

    @transaction.atomic
    def _persist_page(self, kind, snapshot, rows, offset):
        if kind == "ORDER_HEADERS":
            ReconciliationOrderHeader.objects.bulk_create([
                ReconciliationOrderHeader(
                    snapshot=snapshot, source_record_id=_fingerprint(row, offset + i),
                    semantic_order_key=str(_value(row, "order_header_key")),
                    company_code=str(_value(row, "nent_soc")), branch_code=str(_value(row, "nent_succ")),
                    order_number=str(_value(row, "nent_numcde")), customer_number=str(_value(row, "nent_numcli")),
                    customer_name=str(_value(row, "customer_name")), order_date=_date(_value(row, "nent_datecde")),
                    eta=_date(_value(row, "eta")), order_type=str(_value(row, "order_type")),
                    urgency=str(_value(row, "urgency")), line_count=_decimal(_value(row, "line_count")),
                    currency=str(_value(row, "currency")), transport=str(_value(row, "transport")),
                    description=str(_value(row, "description")), invoicing_status=str(_value(row, "invoicing_status")),
                    order_status=str(_value(row, "order_status")), order_amount=_decimal(_value(row, "order_amount")),
                    amount_eur=_decimal(_value(row, "amount_eur")), operation_type=str(_value(row, "operation_type")),
                    subsidiary_reference=str(_value(row, "subsidiary_reference")),
                    international_reference=str(_value(row, "international_reference")), source_payload_json=row,
                ) for i, row in enumerate(rows)
            ], batch_size=1000)
        elif kind == "ORDERS":
            ReconciliationOrderLine.objects.bulk_create([
                ReconciliationOrderLine(
                    snapshot=snapshot, source_record_id=_fingerprint(row, offset + i),
                    semantic_order_key=str(_value(row, "order_header_key")),
                    company_code=str(_value(row, "nlig_soc")), branch_code=str(_value(row, "nlig_succ")),
                    order_number=str(_value(row, "nlig_numcde")), line_number=str(_value(row, "nlig_nolign")),
                    customer_number=str(_value(row, "nlig_numcli")), customer_name=str(_value(row, "customer_name")),
                    part_number=str(_value(row, "nlig_refp", "nlig_ref")),
                    order_date=_date(_value(row, "nlig_datecde")), ordered_quantity=_decimal(_value(row, "nlig_qtecde")),
                    current_invoiced_quantity=_decimal(_value(row, "nlig_qtefac")), current_delivered_quantity=_decimal(_value(row, "nlig_qteliv")),
                    net_amount=_decimal(_value(row, "nlig_pxvteht")), status=str(_value(row, "StatutGlobal", "nlig_pos")), source_payload_json=row,
                ) for i, row in enumerate(rows)
            ], batch_size=1000)
        elif kind == "DELIVERY_INVOICE":
            ReconciliationDeliveryInvoiceLink.objects.bulk_create([
                ReconciliationDeliveryInvoiceLink(
                    snapshot=snapshot, source_record_id=_fingerprint(row, offset + i),
                    company_code=str(_value(row, "nllf_soc")), order_branch_code=str(_value(row, "nllf_succ")),
                    order_number=str(_value(row, "nllf_numcde")), line_number=str(_value(row, "nllf_nolign")),
                    customer_number=str(_value(row, "nllf_numcli")), delivery_number=str(_value(row, "nllf_numliv")),
                    invoice_number=str(_value(row, "nllf_numfac")), cancellation_invoice_number=str(_value(row, "nllf_numfacann")),
                    invoice_branch_code=str(_value(row, "nllf_succfac")), invoice_service_code=str(_value(row, "nllf_servfac")),
                    part_number=str(_value(row, "nllf_refp", "nllf_ref")), ordered_quantity=_decimal(_value(row, "nllf_qtecde")),
                    invoiced_quantity=_decimal(_value(row, "nllf_qtefac")), delivered_quantity=_decimal(_value(row, "nllf_qteliv")),
                    net_amount=_decimal(_value(row, "nllf_pxvteht")), line_status=str(_value(row, "nllf_pos")),
                    operation_nature=str(_value(row, "nllf_natop")), source_payload_json=row,
                ) for i, row in enumerate(rows)
            ], batch_size=1000)
        elif kind == "INVOICES":
            ReconciliationInvoiceHeader.objects.bulk_create([
                ReconciliationInvoiceHeader(
                    snapshot=snapshot, source_record_id=_fingerprint(row, offset + i),
                    company_code=str(_value(row, "nfac_soc")), branch_code=str(_value(row, "nfac_succ")),
                    service_code=str(_value(row, "nfac_serv")), invoice_number=str(_value(row, "nfac_numfac")),
                    master_invoice_number=str(_value(row, "nfac_numfacm")), customer_number=str(_value(row, "nfac_numcli")),
                    invoice_date=_date(_value(row, "nfac_datefac")), transaction_origin=str(_value(row, "nfac_code")),
                    invoice_status=str(_value(row, "nfac_pos")), currency=str(_value(row, "nfac_devise")), source_payload_json=row,
                ) for i, row in enumerate(rows)
            ], batch_size=1000)
        else:
            ReconciliationAccountingEntry.objects.bulk_create([
                ReconciliationAccountingEntry(
                    snapshot=snapshot, source_record_id=str(_value(row, "entry_id")) or _fingerprint(row, offset + i),
                    company_code=str(_value(row, "company_code")), branch_code=str(_value(row, "branch_code")),
                    customer_number=str(_value(row, "customer_number")), document_number=str(_value(row, "document_number")),
                    entry_type=str(_value(row, "journal_code")), accounting_date=_date(_value(row, "accounting_date")),
                    debit_amount=_decimal(_value(row, "debit_eur")), credit_amount=_decimal(_value(row, "credit_eur")),
                    consolidated_amount=_decimal(_value(row, "consolidated_amount")), source_payload_json=row,
                ) for i, row in enumerate(rows)
            ], batch_size=1000)

    def _synchronize_source(self, run, kind, dataset_id, dataset_name, percent):
        source_version = f"{run.id}:{kind}"
        snapshot = ReconciliationSourceSnapshot.objects.filter(
            source_kind=kind,
            source_version=source_version,
        ).order_by("-created_at").first()
        if snapshot and snapshot.status == "Ready":
            return snapshot, {
                "rows": snapshot.row_count,
                "methods": snapshot.metadata_json.get("methods", []),
                "paged": True,
                "resumed": True,
            }
        if snapshot:
            total = snapshot.row_count
            last_cursor = str(snapshot.metadata_json.get("last_cursor") or "")
            if total and not last_cursor:
                raise ReconciliationBufferError(
                    f"{kind} cannot resume because its persisted cursor is missing."
                )
            snapshot.status = "Loading"
            snapshot.save(update_fields=["status"])
            methods = set(snapshot.metadata_json.get("methods", []))
        else:
            snapshot = ReconciliationSourceSnapshot.objects.create(
                source_kind=kind,
                source_name=dataset_name,
                source_version=source_version,
                status="Loading",
                extracted_at=timezone.now(),
            )
            methods = set()
            total = 0
            last_cursor = ""
        try:
            for page, method, total in self._iter_pages(
                dataset_id,
                dataset_name,
                kind,
                last_cursor=last_cursor,
                total=total,
            ):
                self._persist_page(kind, snapshot, page, total - len(page))
                methods.add(method)
                snapshot.row_count = total
                snapshot.metadata_json = {
                    "methods": sorted(methods),
                    "paged": True,
                    "page_size": PAGE_SIZE,
                    "last_cursor": str(_value(page[-1], "_cursor")),
                }
                snapshot.save(update_fields=["row_count", "metadata_json"])
                self._progress(
                    run, percent, kind.casefold(),
                    f"Loading {kind.replace('_', ' ').title()}: {total:,} rows",
                )
            snapshot.status = "Ready"
            snapshot.row_count = total
            snapshot.metadata_json = {
                "methods": sorted(methods),
                "paged": True,
                "page_size": PAGE_SIZE,
                "completed": True,
            }
            snapshot.save(update_fields=["status", "row_count", "metadata_json"])
            return snapshot, {"rows": total, "methods": sorted(methods), "paged": True}
        except Exception:
            persisted_total = {
                "ORDER_HEADERS": ReconciliationOrderHeader,
                "ORDERS": ReconciliationOrderLine,
                "DELIVERY_INVOICE": ReconciliationDeliveryInvoiceLink,
                "INVOICES": ReconciliationInvoiceHeader,
                "ACCOUNTING_REVENUE": ReconciliationAccountingEntry,
            }[kind].objects.filter(snapshot=snapshot).count()
            snapshot.status = "Failed"
            snapshot.row_count = persisted_total
            if not persisted_total:
                snapshot.metadata_json = {}
            snapshot.save(update_fields=["status", "row_count", "metadata_json"])
            raise

    @staticmethod
    def _link_order_headers(order_snapshot, header_snapshot):
        lines = ReconciliationOrderLine.objects.filter(snapshot=order_snapshot)
        headers = ReconciliationOrderHeader.objects.filter(snapshot=header_snapshot)
        semantic_headers = {
            key: pk for pk, key in headers.exclude(semantic_order_key="").values_list("pk", "semantic_order_key")
        }
        business_headers = {
            (company, branch, order): pk
            for pk, company, branch, order in headers.values_list(
                "pk", "company_code", "branch_code", "order_number"
            )
        }
        updates = []
        for pk, semantic_key, company, branch, order in lines.filter(order_header__isnull=True).values_list(
            "pk", "semantic_order_key", "company_code", "branch_code", "order_number"
        ).iterator(chunk_size=10000):
            header_id = semantic_headers.get(semantic_key) if semantic_key else None
            header_id = header_id or business_headers.get((company, branch, order))
            if header_id:
                updates.append((header_id, pk))

        if updates:
            table = connection.ops.quote_name(ReconciliationOrderLine._meta.db_table)
            with transaction.atomic(), connection.cursor() as db_cursor:
                db_cursor.executemany(
                    f"UPDATE {table} SET order_header_id = %s WHERE id = %s",
                    updates,
                )
        return lines.filter(order_header__isnull=False).count()

    @staticmethod
    def backfill_semantic_order_keys(order_snapshot, header_snapshot):
        def update_model(model, snapshot):
            table = connection.ops.quote_name(model._meta.db_table)
            pending = []
            for item in model.objects.filter(snapshot=snapshot, semantic_order_key="").only(
                "pk", "source_payload_json"
            ).iterator(chunk_size=5000):
                cursor = str(_value(item.source_payload_json, "_cursor"))
                semantic_key = cursor.rsplit("|", 1)[-1] if cursor else ""
                if not semantic_key:
                    continue
                pending.append((semantic_key, item.pk))
                if len(pending) >= 5000:
                    with transaction.atomic(), connection.cursor() as db_cursor:
                        db_cursor.executemany(
                            f"UPDATE {table} SET semantic_order_key = %s WHERE id = %s",
                            pending,
                        )
                    pending.clear()
            if pending:
                with transaction.atomic(), connection.cursor() as db_cursor:
                    db_cursor.executemany(
                        f"UPDATE {table} SET semantic_order_key = %s WHERE id = %s",
                        pending,
                    )

        update_model(ReconciliationOrderHeader, header_snapshot)
        update_model(ReconciliationOrderLine, order_snapshot)

    @staticmethod
    def hydrate_order_line_customer_names(order_snapshot, customer_rows):
        customers = {}
        for row in customer_rows:
            customer_number = str(_value(row, "CBSE_NUMCLI", "customer_number"))
            customer_name = str(_value(row, "CBSE_NOMCLI", "customer_name")).strip()
            if customer_number and customer_name:
                customers[customer_number] = customer_name
        if not customers:
            return 0

        table = connection.ops.quote_name(ReconciliationOrderLine._meta.db_table)
        updates = [
            (customer_name, order_snapshot.pk.hex, customer_number)
            for customer_number, customer_name in customers.items()
        ]
        with transaction.atomic(), connection.cursor() as db_cursor:
            db_cursor.executemany(
                f"UPDATE {table} SET customer_name = %s "
                "WHERE snapshot_id = %s AND customer_number = %s AND customer_name = ''",
                updates,
            )
        return ReconciliationOrderLine.objects.filter(
            snapshot=order_snapshot,
        ).exclude(customer_name="").count()

    def process(self, run, *, raise_on_error=True):
        run.status = "Running"
        run.started_at = timezone.now()
        run.completed_at = None
        run.errors_json = []
        run.save(update_fields=["status", "started_at", "completed_at", "errors_json"])
        try:
            logistics = PowerBIReport.objects.filter(is_active=True, report_name__iexact=LOGISTICS_MODEL).first()
            if not logistics or not logistics.semantic_model_id:
                raise ReconciliationBufferError("Mine Logistics Report semantic model is not configured.")
            ca_dataset_id = getattr(settings, "BUSINESS_MAPPING_DATASET_ID", DEFAULT_CA_DATASET_ID)
            snapshots = {}
            source_status = {}
            stages = (("ORDER_HEADERS", 8), ("ORDERS", 18), ("DELIVERY_INVOICE", 32), ("INVOICES", 45))
            for kind, percent in stages:
                self._progress(run, percent, kind.casefold(), f"Retrieving {kind.replace('_', ' ').title()} from Mine Logistics Report")
                snapshots[kind], source_status[kind] = self._synchronize_source(
                    run, kind, logistics.semantic_model_id, LOGISTICS_MODEL, percent
                )
            self._progress(run, 55, "accounting_revenue", "Retrieving CA Combine from Customer Fleet & Revenue Planning Model")
            snapshots["ACCOUNTING_REVENUE"], source_status["ACCOUNTING_REVENUE"] = self._synchronize_source(
                run, "ACCOUNTING_REVENUE", ca_dataset_id, CA_MODEL, 55
            )
            self._progress(run, 80, "linking_order_headers", "Linking Order Headers to Order Lines")
            source_status["ORDER_HEADERS"]["linked_order_lines"] = self._link_order_headers(
                snapshots["ORDERS"], snapshots["ORDER_HEADERS"]
            )
            self._progress(run, 90, "reconciling", "Reconciling Orders, Invoices and CA")
            reconciliation = RevenueOrderReconciliationService(self.user).execute(
                order_snapshot=snapshots["ORDERS"], link_snapshot=snapshots["DELIVERY_INVOICE"],
                invoice_snapshot=snapshots["INVOICES"], accounting_snapshot=snapshots["ACCOUNTING_REVENUE"],
            )
            warnings = list(reconciliation.warnings_json)
            run.status = "Completed with Warnings" if warnings else "Completed"
            run.progress_percent = 100
            run.stage_code = "completed"
            run.stage_label = "Invoice Tracking buffers and reconciliation completed"
            run.source_status_json = {**source_status, "reconciliation_run_id": str(reconciliation.pk)}
            run.warnings_json = warnings
            run.completed_at = timezone.now()
            run.heartbeat_at = timezone.now()
            run.save()
            return run
        except Exception as exc:
            run.status = "Failed"
            run.progress_percent = 100
            run.stage_code = "failed"
            run.stage_label = "Semantic-model synchronization failed"
            run.errors_json = [{"code": "SEMANTIC_BUFFER_SYNC_FAILED", "message": str(exc)[:1000]}]
            run.completed_at = timezone.now()
            run.heartbeat_at = timezone.now()
            run.save()
            if raise_on_error:
                raise
            return run

    @transaction.atomic
    def _persist(self, run, datasets, source_status):
        now = timezone.now()
        snapshots = {}
        for kind, rows in datasets.items():
            source_name = CA_MODEL if kind == "ACCOUNTING_REVENUE" else LOGISTICS_MODEL
            snapshot = ReconciliationSourceSnapshot.objects.create(
                source_kind=kind, source_name=source_name, source_version=f"{run.id}:{kind}",
                status="Ready", extracted_at=now, row_count=len(rows), metadata_json=source_status[kind],
            )
            snapshots[kind] = snapshot

        ReconciliationOrderLine.objects.bulk_create([
            ReconciliationOrderLine(
                snapshot=snapshots["ORDERS"], source_record_id=_fingerprint(row, i),
                company_code=str(_value(row, "nlig_soc")), branch_code=str(_value(row, "nlig_succ")),
                order_number=str(_value(row, "nlig_numcde")), line_number=str(_value(row, "nlig_nolign")),
                customer_number=str(_value(row, "nlig_numcli")), customer_name=str(_value(row, "customer_name")),
                part_number=str(_value(row, "nlig_refp", "nlig_ref")),
                order_date=_date(_value(row, "nlig_datecde")), ordered_quantity=_decimal(_value(row, "nlig_qtecde")),
                current_invoiced_quantity=_decimal(_value(row, "nlig_qtefac")), current_delivered_quantity=_decimal(_value(row, "nlig_qteliv")),
                net_amount=_decimal(_value(row, "nlig_pxvteht")), status=str(_value(row, "StatutGlobal", "nlig_pos")), source_payload_json=row,
            ) for i, row in enumerate(datasets["ORDERS"])
        ], batch_size=1000)
        ReconciliationDeliveryInvoiceLink.objects.bulk_create([
            ReconciliationDeliveryInvoiceLink(
                snapshot=snapshots["DELIVERY_INVOICE"], source_record_id=_fingerprint(row, i),
                company_code=str(_value(row, "nllf_soc")), order_branch_code=str(_value(row, "nllf_succ")),
                order_number=str(_value(row, "nllf_numcde")), line_number=str(_value(row, "nllf_nolign")),
                customer_number=str(_value(row, "nllf_numcli")), delivery_number=str(_value(row, "nllf_numliv")),
                invoice_number=str(_value(row, "nllf_numfac")), cancellation_invoice_number=str(_value(row, "nllf_numfacann")),
                invoice_branch_code=str(_value(row, "nllf_succfac")), invoice_service_code=str(_value(row, "nllf_servfac")),
                part_number=str(_value(row, "nllf_refp", "nllf_ref")), ordered_quantity=_decimal(_value(row, "nllf_qtecde")),
                invoiced_quantity=_decimal(_value(row, "nllf_qtefac")), delivered_quantity=_decimal(_value(row, "nllf_qteliv")),
                net_amount=_decimal(_value(row, "nllf_pxvteht")), line_status=str(_value(row, "nllf_pos")),
                operation_nature=str(_value(row, "nllf_natop")), source_payload_json=row,
            ) for i, row in enumerate(datasets["DELIVERY_INVOICE"])
        ], batch_size=1000)
        ReconciliationInvoiceHeader.objects.bulk_create([
            ReconciliationInvoiceHeader(
                snapshot=snapshots["INVOICES"], source_record_id=_fingerprint(row, i),
                company_code=str(_value(row, "nfac_soc")), branch_code=str(_value(row, "nfac_succ")),
                service_code=str(_value(row, "nfac_serv")), invoice_number=str(_value(row, "nfac_numfac")),
                master_invoice_number=str(_value(row, "nfac_numfacm")), customer_number=str(_value(row, "nfac_numcli")),
                invoice_date=_date(_value(row, "nfac_datefac")), transaction_origin=str(_value(row, "nfac_code")),
                invoice_status=str(_value(row, "nfac_pos")), currency=str(_value(row, "nfac_devise")), source_payload_json=row,
            ) for i, row in enumerate(datasets["INVOICES"])
        ], batch_size=1000)
        ReconciliationAccountingEntry.objects.bulk_create([
            ReconciliationAccountingEntry(
                snapshot=snapshots["ACCOUNTING_REVENUE"], source_record_id=str(_value(row, "entry_id")) or _fingerprint(row, i),
                company_code=str(_value(row, "company_code")), branch_code=str(_value(row, "branch_code")),
                customer_number=str(_value(row, "customer_number")), document_number=str(_value(row, "document_number")),
                entry_type=str(_value(row, "journal_code")), accounting_date=_date(_value(row, "accounting_date")),
                debit_amount=_decimal(_value(row, "debit_eur")), credit_amount=_decimal(_value(row, "credit_eur")),
                consolidated_amount=_decimal(_value(row, "consolidated_amount")), source_payload_json=row,
            ) for i, row in enumerate(datasets["ACCOUNTING_REVENUE"])
        ], batch_size=1000)
        return snapshots

    def start_background(self, run):
        def worker():
            close_old_connections()
            try:
                self.process(
                    ReconciliationBufferSyncRun.objects.get(pk=run.pk),
                    raise_on_error=False,
                )
            finally:
                close_old_connections()

        threading.Thread(target=worker, name=f"reconciliation-buffer-{run.pk}", daemon=True).start()
