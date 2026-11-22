"""Refresh Parts classification from the existing invoice/accounting-date fact.

This allocates accounting EUR to invoice part groups, not to orders or cohorts.
InvoiceKey_V2 comes from the model. Invoice value is never copied to every line.
"""
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PartClassificationReference, PartSaleDetail, PartsSalesSynchronizationRun
from .parts_fulfillment_service import LogisticsSource, FulfillmentUnavailable, dax_date, dax_text, shift_month
from .parts_sales_service import PartsSalesSynchronizationService, _part_key

SOURCE = 'Mine Logistics Report / FactSalesAllocation'
METHOD = 'Accounting EUR allocated by signed invoiced quantity × actual net unit price, per invoice and accounting date'
PAGE_SIZE = 4000
MAX_ROWS = 1000000
PRECISION = Decimal('0.0000000001')
TOLERANCE = Decimal('0.01')
LLF = "'Neg_llf_complete'"
FACT = "'FactSalesAllocation'"
FIN = "'Global CA Detailled'"


def state_directory():
    root = Path(settings.BASE_DIR)
    shared = root.parent / 'shared'
    return Path(getattr(settings, 'PARTS_SALES_STATE_DIRECTORY', (shared if shared.is_dir() else root / '.runlogs') / 'parts-sales-refresh'))


@contextmanager
def import_lock():
    root = state_directory()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'import.lock').open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell(): stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try: yield True
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream, fcntl.LOCK_UN)


def number(value):
    try: result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise FulfillmentUnavailable('The Parts source returned an invalid amount.', 'INVALID_SOURCE_VALUE') from None
    if not result.is_finite():
        raise FulfillmentUnavailable('The Parts source returned an invalid amount.', 'INVALID_SOURCE_VALUE')
    return result


def definitions(start, end):
    return f'''VAR Facts = FILTER(ALL({FACT}), {FACT}[Date ecritures]>={dax_date(start)} && {FACT}[Date ecritures]<{dax_date(end)}+1)
VAR InvoiceKeys = DISTINCT(SELECTCOLUMNS(Facts,"k",{FACT}[INVOICEKEY_V2]))
VAR Lines = CALCULATETABLE({LLF}, REMOVEFILTERS('Date'), TREATAS(InvoiceKeys,{LLF}[INVOICEKEY_V2]))
VAR Accounts = FILTER(ALL({FIN}), {FIN}[Date ecritures]>={dax_date(start)} && {FIN}[Date ecritures]<{dax_date(end)}+1 && {FIN}[Division]="MI" && UPPER(TRIM({FIN}[LOB]))="PARTS" && UPPER(TRIM({FIN}[Canal de distribution]))<>"INTERCO")'''


def control_query(start, end):
    return f'''EVALUATE {definitions(start,end)} RETURN ROW(
"accounting_count",COUNTROWS(GROUPBY(Facts,{FACT}[INVOICEKEY_V2],{FACT}[Date ecritures])),
"account_count",COUNTROWS(GROUPBY(Accounts,{FIN}[INVOICEKEY_V2],{FIN}[Date ecritures],{FIN}[Code client Irium],{FIN}[Code Société],{FIN}[Code Succursale],{FIN}[Facture])),
"line_count",COUNTROWS(GROUPBY(Lines,{LLF}[INVOICEKEY_V2],{LLF}[NLLF_REFP],{LLF}[NLLF_CONSTP])),
"latest",MAXX(Facts,{FACT}[Date ecritures]),
"sales",CALCULATE([CA Comptable EUR],DATESBETWEEN('Date'[Date],{dax_date(start)},{dax_date(end)})))'''


def page_query(kind, start, end, cursor=''):
    if kind == 'accounting':
        grouped = f'''GROUPBY(Facts,{FACT}[INVOICEKEY_V2],{FACT}[Date ecritures],"amount",SUMX(CURRENTGROUP(),{FACT}[AccountingCA_EUR]))'''
        fields = f'''"invoice_key",{FACT}[INVOICEKEY_V2],"date",{FACT}[Date ecritures],"amount",[amount],
"cursor",{FACT}[INVOICEKEY_V2]&UNICHAR(166)&FORMAT({FACT}[Date ecritures],"yyyy-MM-dd")'''
    elif kind == 'accounts':
        grouped = f'''GROUPBY(Accounts,{FIN}[INVOICEKEY_V2],{FIN}[Date ecritures],{FIN}[Code client Irium],{FIN}[Code Société],{FIN}[Code Succursale],{FIN}[Facture],"amount",SUMX(CURRENTGROUP(),{FIN}[CA euro]))'''
        fields = f'''"invoice_key",{FIN}[INVOICEKEY_V2],"date",{FIN}[Date ecritures],"account",{FIN}[Code client Irium],"company",{FIN}[Code Société],"branch",{FIN}[Code Succursale],"invoice",{FIN}[Facture],"amount",[amount],
"cursor",{FIN}[INVOICEKEY_V2]&UNICHAR(166)&FORMAT({FIN}[Date ecritures],"yyyy-MM-dd")&UNICHAR(166)&{FIN}[Code client Irium]'''
    elif kind == 'lines':
        grouped = f'''GROUPBY(Lines,{LLF}[INVOICEKEY_V2],{LLF}[NLLF_REFP],{LLF}[NLLF_CONSTP],"weight",SUMX(CURRENTGROUP(),{LLF}[NLLF_QTEFAC]*{LLF}[NLLF_PXNREEL]),"quantity",SUMX(CURRENTGROUP(),{LLF}[NLLF_QTEFAC]),"lines",COUNTX(CURRENTGROUP(),1))'''
        fields = f'''"invoice_key",{LLF}[INVOICEKEY_V2],"part",{LLF}[NLLF_REFP],"brand",{LLF}[NLLF_CONSTP],"weight",[weight],"quantity",[quantity],"lines",[lines],
"cursor",{LLF}[INVOICEKEY_V2]&UNICHAR(166)&{LLF}[NLLF_REFP]&UNICHAR(166)&{LLF}[NLLF_CONSTP]'''
    else:
        raise ValueError('Unknown Parts source page.')
    return f'''EVALUATE {definitions(start,end)}
VAR Projected = SELECTCOLUMNS({grouped},{fields})
RETURN TOPN({PAGE_SIZE+1},FILTER(Projected,[cursor]>{dax_text(cursor)}),[cursor],ASC)
ORDER BY [cursor] ASC'''


class PartsSalesModelSynchronizationService:
    def __init__(self, user, *, source=None):
        # Same Global-only authorized source contract as Parts Fulfillment.
        self.source = source or LogisticsSource(user)
        self.user = user

    def query(self, dax):
        for attempt in range(3):
            try:
                return self.source.query(dax)
            except FulfillmentUnavailable as exc:
                if attempt == 2 or exc.code not in {'SOURCE_QUERY_FAILED','SOURCE_CONNECTION_FAILED','SOURCE_UNAVAILABLE'}:
                    raise
                time.sleep(2 ** attempt)

    def control(self, start, end):
        rows = self.query(control_query(start,end))
        if len(rows) != 1: raise FulfillmentUnavailable('Parts source controls are unavailable.')
        row = rows[0]
        counts = {name:int(row.get(name) or 0) for name in ('accounting_count','account_count','line_count')}
        if any(v < 0 or v > MAX_ROWS for v in counts.values()):
            raise FulfillmentUnavailable('Parts source exceeds the validated import limit.')
        if counts['accounting_count'] and row.get('sales') is None:
            raise FulfillmentUnavailable('The accounting measure is unavailable.')
        return {**counts,'sales':number(row.get('sales') or 0),'latest':str(row['latest'])[:10] if row.get('latest') else None}

    def read(self, kind, start, end, expected):
        rows, cursor = [], ''
        seen = set()
        while True:
            result = self.query(page_query(kind,start,end,cursor))
            page = result[:PAGE_SIZE]
            for row in page:
                key = str(row.get('cursor') or '')
                if not key or key in seen or not str(row.get('invoice_key') or ''):
                    raise FulfillmentUnavailable('Parts source contains incomplete or duplicate page identifiers.')
                seen.add(key)
                rows.append(row)
            if len(rows) > MAX_ROWS:
                raise FulfillmentUnavailable('Parts source exceeds the validated import limit.')
            if len(result) <= PAGE_SIZE: break
            next_cursor = str(page[-1]['cursor'])
            if next_cursor == cursor or str(result[PAGE_SIZE].get('cursor')) == next_cursor:
                raise FulfillmentUnavailable('Parts source pagination did not advance safely.')
            cursor = next_cursor
        if len(rows) != expected:
            raise FulfillmentUnavailable('Parts source was truncated or changed during import; the previous detail is retained.')
        return rows

    def allocations(self, start, end, controls, counters):
        facts = self.read('accounting',start,end,controls['accounting_count'])
        accounts = self.read('accounts',start,end,controls['account_count'])
        lines = self.read('lines',start,end,controls['line_count'])
        account_map, line_map = defaultdict(list), defaultdict(list)
        for row in accounts: account_map[(row['invoice_key'],str(row['date'])[:10])].append(row)
        for row in lines:
            number(row.get('weight')); number(row.get('quantity'))
            if int(row.get('lines') or 0) <= 0: raise FulfillmentUnavailable('Invalid source line count.')
            line_map[row['invoice_key']].append(row)
        fact_total = sum((number(row['amount']) for row in facts if row.get('amount') is not None),Decimal(0))
        if abs(fact_total-controls['sales']) > TOLERANCE:
            raise FulfillmentUnavailable('Invoice/date accounting totals do not reconcile to CA Comptable EUR.')
        for row in facts:
            if row.get('amount') is None:
                counters['blank_accounting'] += 1
                continue
            invoice, raw_date = row['invoice_key'],str(row['date'])[:10]
            business_date = date.fromisoformat(raw_date)
            if not start <= business_date <= end: raise FulfillmentUnavailable('Unexpected accounting date.')
            amount = number(row.get('amount'))
            metadata = account_map.get((invoice,raw_date),[])
            if abs(sum((number(item['amount']) for item in metadata if item.get('amount') is not None),Decimal(0))-amount) > TOLERANCE:
                raise FulfillmentUnavailable('Accounting customer scope differs from the invoice/date fact.')
            source_lines = line_map.get(invoice,[])
            if len(metadata) != 1 or not str(metadata[0].get('account') or '').strip():
                counters['ambiguous_customer'] += 1
                continue
            if not source_lines:
                counters['no_lines'] += 1
                continue
            total = sum((number(item['weight']) for item in source_lines),Decimal(0))
            if total == 0:
                counters['zero_weight'] += 1
                continue
            meta = metadata[0]
            remaining = amount.quantize(PRECISION,rounding=ROUND_HALF_UP)
            for index, line in enumerate(source_lines):
                allocated = remaining if index == len(source_lines)-1 else (amount*number(line['weight'])/total).quantize(PRECISION,rounding=ROUND_HALF_UP)
                remaining -= allocated
                identity = json.dumps([invoice,raw_date,line.get('part') or '',line.get('brand') or ''],ensure_ascii=True)
                counters['read'] += 1
                counters['allocated'] += allocated
                yield {'source_record_id':'model:'+hashlib.sha256(identity.encode()).hexdigest(),
                    'invoice_key':invoice,'source_line_count':int(line['lines']),
                    'business_date':raw_date,'company_code':str(meta.get('company') or ''),
                    'branch_code':str(meta.get('branch') or ''),'customer_code':str(meta['account']),
                    'customer_name':'','invoice_number':str(meta.get('invoice') or ''),
                    'part_number':str(line.get('part') or ''),'normalized_part_number':_part_key(line.get('part')),
                    'brand':str(line.get('brand') or ''),'invoiced_quantity':str(line['quantity']),
                    'source_line_amount':str(line['weight']),'allocated_revenue_eur':str(allocated),'active':True}

    def synchronize(self, start=None, end=None):
        end = end or timezone.localdate()
        with import_lock() as acquired:
            if not acquired: raise FulfillmentUnavailable('A Parts detail import is already running.', 'SOURCE_BUSY')
            run = PartsSalesSynchronizationRun.objects.create(source_context_json={
                'source':SOURCE,'allocation_method':METHOD,'source_user_id':str(self.user.pk) if getattr(self.user,'pk',None) is not None else None})
            counters = defaultdict(int); counters['allocated'] = Decimal(0)
            stage_path = None
            try:
                bounds = self.query(f'''EVALUATE ROW("first",MIN({FACT}[Date ecritures]),"last",MAX({FACT}[Date ecritures]))''')
                if len(bounds)!=1 or not bounds[0].get('first'):
                    raise FulfillmentUnavailable('No accounting source is available; existing Parts detail is retained.')
                start = start or date.fromisoformat(str(bounds[0]['first'])[:10])
                if start>end or end>timezone.localdate(): raise ValueError('Choose a valid accounting date range up to today.')
                run.source_context_json.update(start_date=start.isoformat(),end_date=end.isoformat())
                run.save(update_fields=['source_context_json'])
                if not PartClassificationReference.objects.filter(active=True,classification_status='Classified').exists() and PartSaleDetail.objects.filter(active=True,classification_status='Classified').exists():
                    raise FulfillmentUnavailable('Restore the verified CAT reference catalog before refreshing classified Parts detail.','CLASSIFICATION_REFERENCE_REQUIRED')
                initial = self.control(start,end)
                month = start.replace(day=1)
                with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=state_directory(),prefix='stage-',suffix='.jsonl',delete=False) as stage:
                    stage_path = Path(stage.name)
                    while month <= end:
                        following = shift_month(month,1)
                        month_end = min(end,following-timedelta(days=1))
                        a,b = max(start,month),month_end
                        controls = self.control(a,b)
                        for payload in self.allocations(a,b,controls,counters):
                            stage.write(json.dumps(payload,ensure_ascii=True)+'\n')
                        month = following
                if self.control(start,end) != initial:
                    raise FulfillmentUnavailable('The accounting source changed during import; existing Parts detail is retained.')
                now = timezone.now()
                with transaction.atomic():
                    batch = []
                    with stage_path.open(encoding='utf-8') as stage:
                        for line in stage:
                            payload = json.loads(line)
                            payload['business_date'] = date.fromisoformat(payload['business_date'])
                            for key in ('invoiced_quantity','source_line_amount','allocated_revenue_eur'): payload[key] = number(payload[key])
                            batch.append(payload)
                            if len(batch) >= 500:
                                PartsSalesSynchronizationService._persist(batch,run,now,counters,skip_unchanged=True)
                                batch = []
                        if batch: PartsSalesSynchronizationService._persist(batch,run,now,counters,skip_unchanged=True)
                    from django.db.models import Sum
                    written = PartSaleDetail.objects.filter(synchronization_run=run).aggregate(value=Sum('allocated_revenue_eur'))['value'] or Decimal(0)
                    if abs(written-counters['allocated']) > TOLERANCE:
                        raise FulfillmentUnavailable('Stored Parts amounts differ from the validated source allocation.')
                    run.records_deactivated = PartSaleDetail.objects.filter(active=True,business_date__range=(start,end)).exclude(synchronization_run=run).update(active=False)
                    warnings = [f'{counters[key]} invoice/date groups: {label}.' for key,label in (
                        ('no_lines','no matching invoice lines'),('ambiguous_customer','no unique accounting customer'),
                        ('zero_weight','zero net invoice-line value'),('blank_accounting','accounting amount is blank; not allocated')) if counters[key]]
                    run.status = 'Completed with Warnings' if warnings else 'Completed'
                    run.data_through_date = date.fromisoformat(initial['latest']) if initial['latest'] else None
                    run.records_read = counters['read']; run.records_created = counters['created']
                    run.records_updated = counters['updated']; run.records_unchanged = counters['unchanged']
                    run.classified_records = PartSaleDetail.objects.filter(active=True,synchronization_run=run,classification_status='Classified').count()
                    run.allocated_revenue_eur = counters['allocated']; run.warnings_json = warnings
                    run.source_context_json.update(accounting_total=str(initial['sales']),matched_total=str(counters['allocated']),
                        accounting_groups=initial['accounting_count'],exceptions={k:counters[k] for k in ('no_lines','ambiguous_customer','zero_weight','blank_accounting')})
                    run.completed_at = timezone.now(); run.save()
                return run
            except Exception as exc:
                run.status='Failed'; run.completed_at=timezone.now()
                run.error_message='Parts detail import failed validation or source access. Previous active detail retained.'
                code = getattr(exc,'code','SOURCE_UNAVAILABLE')
                run.source_context_json['error_code'] = code if code in {'CLASSIFICATION_REFERENCE_REQUIRED','SOURCE_BUSY','INVALID_SOURCE_VALUE','SOURCE_QUERY_FAILED','SOURCE_CONNECTION_FAILED','SOURCE_UNAVAILABLE'} else 'SOURCE_UNAVAILABLE'
                run.save(update_fields=['status','completed_at','error_message','source_context_json'])
                raise
            finally:
                if stage_path: stage_path.unlink(missing_ok=True)
