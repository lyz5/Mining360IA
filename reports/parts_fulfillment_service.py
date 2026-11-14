"""Read existing Mine Logistics measures; never rebuild invoice allocation or cohorts."""
from __future__ import annotations

import calendar
import hashlib
import os
import re
import requests
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import powerbi, power_automate
from .access_control import is_platform_admin, has_module_access
from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names
from .models import PowerBIReport, ReportingReportPreference

MEASURES = {
    'orders': 'Order Intake EUR', 'sales': 'CA Comptable EUR',
    'current': 'CA Current Month', 'last': 'CA Last Month', 'older': 'CA +2 Months',
    'unallocated': 'CA Unallocated', 'future': 'CA Future Order',
    'difference': 'CA Reconciliation Difference',
}
COHORTS = {
    'current': 'Current Month', 'last': 'Last Month', 'older': '2+ Months',
    'unallocated': 'Unallocated', 'future': 'Future Order',
}
FIELDS = {
    'accounting_date': 'Date ecritures', 'order_date': 'PQ_SingleOrderInvoices.Order Date',
    'order_key': 'PQ_SingleOrderInvoices.PK_V2', 'invoice_key': 'InvoiceKey_V2',
    'cohort': 'SalesCohort', 'amount': 'AccountingCA_EUR',
}
FACT = "'FactSalesAllocation'"
CENT = Decimal('.01')


class FulfillmentUnavailable(Exception):
    def __init__(self, message, code='SOURCE_UNAVAILABLE'):
        self.code = code
        super().__init__(message)


def month_start(value):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', str(value or '')):
        raise ValueError('Choose a month in YYYY-MM format.')
    return date.fromisoformat(value + '-01')


def shift_month(value, offset):
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def dax_date(value):
    return f'DATE({value.year},{value.month},{value.day})'


def dax_text(value):
    return '"' + str(value).replace('"', '""') + '"'


def normal_row(row):
    return {key.rsplit('[', 1)[-1].rstrip(']'): value for key, value in row.items()}


def money(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise FulfillmentUnavailable('The source returned an invalid monetary value.')
    return format(number, 'f')


def cents(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def report_for(user):
    if not has_module_access(user, 'reporting'):
        raise FulfillmentUnavailable('Reporting access is required for this source.', 'SOURCE_ACCESS_REQUIRED')
    reports = PowerBIReport.objects.filter(report_name__iexact='Mine Logistics Report', is_active=True)
    if not is_platform_admin(user):
        reports = reports.filter(validation_status='Validated')
    report = reports.first()
    if not report or not report.semantic_model_id or not report.workspace_id:
        raise FulfillmentUnavailable('Mine Logistics Report needs an active configured semantic model.', 'SOURCE_NOT_CONFIGURED')
    if not is_platform_admin(user) and ReportingReportPreference.objects.filter(report_id=report.report_id, is_visible=False).exists():
        raise FulfillmentUnavailable('This source is not available for your account.', 'SOURCE_ACCESS_REQUIRED')
    return report


class LogisticsSource:
    """The registered flow is the existing supported query path for this dataset.

    Neither a service-principal REST query nor a flow payload role proves end-user
    RLS. Until a delegated query contract is verified, global reads are admin-only.
    """
    def __init__(self, user):
        self.user = user
        self.report = report_for(user)
        accounts = authorized_account_codes(user)
        sites = authorized_minesite_names(user)
        if not is_platform_admin(user) or accounts is not None or sites is not None:
            raise FulfillmentUnavailable(
                'A verified query identity enforcing your Power BI scope is required. Your access has not been widened.',
                'SCOPED_QUERY_NOT_CONFIGURED')
        if self.report.requires_user_identity or self.report.authentication_mode != 'app_owns_data' or self.report.default_rls_role.casefold() != 'global':
            raise FulfillmentUnavailable('This report requires a verified delegated query identity.', 'SCOPED_QUERY_NOT_CONFIGURED')
        self.refresh_id, self.last_refresh = self.refresh_state()

    def refresh_state(self):
        key = 'parts-fulfillment:refresh:' + hashlib.sha256(f'{self.report.workspace_id}:{self.report.semantic_model_id}'.encode()).hexdigest()
        result = cache.get(key)
        if result is not None:
            return result
        result = ('unknown', None)
        try:
            response = powerbi.HTTP.get(
                f'{powerbi.powerbi_root()}/groups/{self.report.workspace_id}/datasets/{self.report.semantic_model_id}/refreshes?$top=1',
                headers={'Authorization': f'Bearer {powerbi.get_access_token()}'}, timeout=(3, 5))
            if response.status_code == 200:
                runs = response.json().get('value', [])
                if runs:
                    run = runs[0]
                    last_refresh = run.get('endTime') if run.get('status') == 'Completed' else None
                    result = (str(run.get('requestId') or '') + ':' + str(run.get('status')) + ':' + str(run.get('endTime')), last_refresh)
        except Exception:
            pass  # A missing refresh history must not invent a timestamp or hide available data.
        cache.set(key, result, 60)
        return result

    def query(self, dax):
        # Short bounded transport; the existing generic flow helper can retry for
        # several minutes, which is inappropriate for an interactive dashboard.
        try:
            url = power_automate.get_flow_url(self.report.report_name)
            if url:
                payload = {'datasetId': self.report.semantic_model_id, 'datasetName': self.report.report_name,
                           'query': dax, 'question': 'Parts Orders & Sales Fulfillment',
                           'metric': 'Parts Fulfillment', 'measure': 'Existing model measures',
                           'filters': {}, 'roles': ['Global'], 'rlsRole': 'Global'}
                response = None
                for attempt in range(2):
                    try:
                        response = power_automate.HTTP.post(url, json=payload, timeout=(4, 20))
                        if response.status_code not in (429, 502, 503, 504) or attempt:
                            break
                    except requests.RequestException:
                        if attempt:
                            raise FulfillmentUnavailable('The configured Mine Logistics query connection could not be reached securely. Please retry.', 'SOURCE_CONNECTION_FAILED') from None
            else:
                token = powerbi.get_access_token()
                response = powerbi.HTTP.post(
                    f'{powerbi.powerbi_root()}/groups/{self.report.workspace_id}/datasets/{self.report.semantic_model_id}/executeQueries',
                    headers={'Authorization': f'Bearer {token}'},
                    json={'queries': [{'query': dax}], 'serializerSettings': {'includeNulls': True}}, timeout=(5, 35))
            if response.status_code != 200:
                code = 'SOURCE_AUTHORIZATION_REQUIRED' if response.status_code in (401, 403) else 'SOURCE_QUERY_FAILED'
                raise FulfillmentUnavailable('Mine Logistics could not execute the requested measures. Check source permissions and model fields, then retry.', code)
            body = response.json()
            if (body.get('error') or any(item.get('error') or any(table.get('error') for table in item.get('tables', [])) for item in body.get('results', []))):
                raise FulfillmentUnavailable('The source rejected the query or returned a partial result.', 'SOURCE_QUERY_FAILED')
            rows = body.get('firstTableRows')
            if rows is None:
                rows = body['results'][0]['tables'][0]['rows']
            if not isinstance(rows, list):
                raise ValueError('Invalid query response')
            return [normal_row(row) for row in rows]
        except FulfillmentUnavailable:
            raise
        except Exception:
            # Never return signed flow URLs, tokens or upstream exception bodies.
            raise FulfillmentUnavailable('Mine Logistics is temporarily unavailable. Please retry.') from None

    def cached_query(self, dax, ttl=90):
        scope = (self.user.pk, self.report.pk, self.report.semantic_model_id,
                 self.report.updated_at.isoformat(), self.report.configuration_version,
                 self.report.authentication_mode, self.report.default_rls_role,
                 authorized_account_codes(self.user), authorized_minesite_names(self.user), getattr(self, 'refresh_id', 'unknown'))
        digest = hashlib.sha256((repr(scope) + dax).encode()).hexdigest()
        key = 'parts-fulfillment:v1:' + digest
        result = cache.get(key)
        if result is None:
            lock = key + ':loading'
            if not cache.add(lock, True, 90):
                raise FulfillmentUnavailable('This source query is already running. Please retry shortly.', 'SOURCE_BUSY')
            try:
                result = self.query(dax)
                cache.set(key, result, min(ttl, 45) if getattr(self, 'refresh_id', 'unknown') == 'unknown' else ttl)
            finally:
                cache.delete(lock)
        return result


def monthly_dax(today):
    # Each date context is passed to the model's own measures. In particular the
    # Order Intake measure owns its order-date relationship; no invoice-derived orders.
    expressions = ',\n'.join(
        f'"{key}", VAR s=[MonthStart] RETURN CALCULATE([{name}], DATESBETWEEN(\'Date\'[Date],s,MIN(EOMONTH(s,0),{dax_date(today)})))'
        for key, name in MEASURES.items())
    return f'''EVALUATE
VAR Months = FILTER(DISTINCT(SELECTCOLUMNS(FILTER(ALL('Date'[Date]), NOT ISBLANK('Date'[Date])), "MonthStart", DATE(YEAR('Date'[Date]),MONTH('Date'[Date]),1))), [MonthStart] <= {dax_date(today)})
VAR ValuesByMonth = ADDCOLUMNS(Months, {expressions},
    "coverage", VAR s=[MonthStart] RETURN CALCULATE(MAX({FACT}[Date ecritures]), DATESBETWEEN('Date'[Date],s,MIN(EOMONTH(s,0),{dax_date(today)}))))
RETURN FILTER(ValuesByMonth, NOT(ISBLANK([orders]) && ISBLANK([sales])))
ORDER BY [MonthStart]'''


def reconciliation(row):
    if any(row.get(k) is None for k in ('sales', 'difference', *COHORTS)):
        return {'status': 'unavailable', 'label': 'Reconciliation unavailable', 'difference': row.get('difference')}
    arithmetic = cents(row['sales']) - sum(cents(row[k]) for k in COHORTS)
    source_diff = cents(row['difference'])
    ok = abs(arithmetic) <= CENT and abs(source_diff) <= CENT
    return {'status': 'reconciled' if ok else 'warning', 'label': 'Reconciled' if ok else 'Data quality warning',
            'difference': str(source_diff), 'arithmetic_difference': str(arithmetic)}


class PartsFulfillmentService:
    def __init__(self, user, source=None, today=None):
        self.user = user
        self.source = source or LogisticsSource(user)
        self.today = today or timezone.localdate()

    def summary(self, selected=None):
        rows = self.source.cached_query(monthly_dax(self.today))
        series = []
        for row in rows:
            raw = str(row.get('MonthStart') or '')[:10]
            try:
                start = date.fromisoformat(raw)
            except ValueError:
                raise FulfillmentUnavailable('The source calendar did not return valid months.') from None
            if start > self.today or start.day != 1:
                raise FulfillmentUnavailable('The source calendar did not return valid months.')
            item = {'month': start.strftime('%Y-%m'), **{key: money(row.get(key)) for key in MEASURES},
                    'coverage': str(row['coverage'])[:10] if row.get('coverage') else None}
            # A successfully evaluated blank cohort in a nonblank sales month
            # contributes zero to additive reconciliation. Preserve that provenance.
            item['blank_cohorts'] = [key for key in COHORTS if item[key] is None]
            if item['sales'] is not None:
                for key in item['blank_cohorts']:
                    item[key] = '0'
            item['reconciliation'] = reconciliation(item)
            series.append(item)
        series.sort(key=lambda row: row['month'])
        if len({r['month'] for r in series}) != len(series):
            raise FulfillmentUnavailable('Duplicate monthly aggregates were returned.')
        months = [r['month'] for r in series]
        if not months:
            return {'ready': True, 'empty': True, 'months': [], 'series': [], 'message': 'No data is available in the source for your scope.'}
        if selected:
            start = month_start(selected)
            if selected not in months:
                return {'ready': True, 'empty': True, 'months': months, 'selected_month': selected, 'series': [], 'message': 'No source data for this month.'}
        else:
            completed = [m for m in months if m < self.today.strftime('%Y-%m')]
            selected = (completed or months)[-1]
            start = month_start(selected)
        current = next(r for r in series if r['month'] == selected)
        previous = next((r for r in series if r['month'] == shift_month(start, -1).strftime('%Y-%m')), None)
        partial = selected == self.today.strftime('%Y-%m')
        comparable = bool(getattr(settings, 'PARTS_FULFILLMENT_COMPARABILITY_CONFIRMED', os.getenv('PARTS_FULFILLMENT_COMPARABILITY_CONFIRMED') == '1'))
        changes = {}
        for key in ('orders', 'sales'):
            previous_value = previous.get(key) if previous else None
            reason = 'Month to date: a comparable elapsed prior period is not available.' if partial else None
            if previous_value is None or current.get(key) is None or Decimal(previous_value) <= 0:
                reason = reason or 'A positive, comparable previous-month value is not available.'
            changes[key] = {'percent': None if reason else str((Decimal(current[key]) - Decimal(previous_value)) / Decimal(previous_value) * 100),
                            'reason': reason}
        realization = None
        if comparable and current['orders'] is not None and current['current'] is not None and Decimal(current['orders']) > 0:
            realization = str(Decimal(current['current']) / Decimal(current['orders']) * 100)
        return {'ready': True, 'empty': False, 'months': months, 'selected_month': selected,
                'month_to_date': partial, 'kpis': current, 'changes': changes,
                'realization_percent': realization,
                'realization_note': None if realization is not None else 'EUR, tax basis and business scope comparability have not been confirmed, or Order Intake is not positive.',
                'older_sales': None if current['last'] is None or current['older'] is None else str(Decimal(current['last']) + Decimal(current['older'])),
                'series': [r for r in series if shift_month(start, -11).strftime('%Y-%m') <= r['month'] <= selected],
                'source': {'model': 'Mine Logistics Report', 'currency': 'EUR', 'last_refresh': getattr(self.source, 'last_refresh', None) if isinstance(getattr(self.source, 'last_refresh', None), str) else None,
                           'measure_map': MEASURES, 'coverage': current['coverage'],
                           'scope': 'Expected scope: Mining / MI · PARTS · excluding INTERCO',
                           'scope_note': 'Source measure definitions govern the scope. Order Intake date logic and tax/scope comparability require metadata review. Valid blank cohorts contribute zero; source failures never do.'}}

    def details(self, params, export=False):
        month = month_start(params.get('month'))
        if month > self.today:
            raise ValueError('Future accounting months are not available.')
        cohort = params.get('cohort', '')
        if cohort and cohort not in COHORTS:
            raise ValueError('Unknown cohort.')
        search = str(params.get('search', '')).strip()
        if len(search) > 100:
            raise ValueError('Search is limited to 100 characters.')
        sort = params.get('sort', 'accounting_date')
        if sort not in ('accounting_date', 'order_date', 'amount'):
            raise ValueError('Unsupported sort field.')
        direction = str(params.get('direction', 'desc')).lower()
        if direction not in ('asc', 'desc'):
            raise ValueError('Unsupported sort direction.')
        page = 1 if export else int(params.get('page', 1))
        if page < 1 or page > 2000:
            raise ValueError('Page is outside the supported range.')
        size = 10001 if export else 25
        end = min(date(month.year, month.month, calendar.monthrange(month.year, month.month)[1]), self.today)
        filters = [f"DATESBETWEEN('Date'[Date],{dax_date(month)},{dax_date(end)})"]
        if cohort:
            filters.append(f'KEEPFILTERS({FACT}[SalesCohort]={dax_text(COHORTS[cohort])})')
        if search:
            literal_search = search.replace('~', '~~').replace('*', '~*').replace('?', '~?')
            filters.append(f'FILTER({FACT},CONTAINSSTRING({FACT}[PQ_SingleOrderInvoices.PK_V2],{dax_text(literal_search)}) || CONTAINSSTRING({FACT}[InvoiceKey_V2],{dax_text(literal_search)}))')
        groups = ','.join(f'{FACT}[{FIELDS[k]}]' for k in FIELDS if k != 'amount')
        projection = ','.join(f'"{k}",[{v}]' for k, v in FIELDS.items() if k != 'amount')
        sort_keys = [sort] + [k for k in ('accounting_date', 'order_date', 'order_key', 'invoice_key', 'cohort') if k != sort]
        sort_args = ','.join(f'[{k}],{direction.upper() if k == sort else "ASC"}' for k in sort_keys)
        order_args = ','.join(f'[{k}] {direction.upper() if k == sort else "ASC"}' for k in sort_keys)
        measure_total = f"CALCULATE([{MEASURES[cohort or 'sales']}], DATESBETWEEN('Date'[Date],{dax_date(month)},{dax_date(end)}))"
        # A TOPN with all group keys forms a stable server-side page, including ties.
        query_base = f'''EVALUATE
VAR DetailBase = CALCULATETABLE({FACT}, {','.join(filters)})
VAR DetailGroups = GROUPBY(DetailBase,{groups},"amount",SUMX(CURRENTGROUP(),{FACT}[AccountingCA_EUR]))
VAR DetailRows = SELECTCOLUMNS(DetailGroups,{projection},"amount",[amount])
'''
        # Separate bounded aggregates and page reads. Mixing the control row and
        # transaction rows in a UNION made the live model query exceed its budget.
        controls = self.source.cached_query(query_base + f'''RETURN ROW("kind","meta","total_rows",COUNTROWS(DetailRows),"detail_total",SUMX(DetailRows,[amount]),"measure_total",{measure_total})''', ttl=45)
        meta = next((r for r in controls if r.get('kind') == 'meta'), None)
        if meta is None:
            raise FulfillmentUnavailable('The detail query did not return its controls.')
        count = int(meta.get('total_rows') or 0)
        if export and count > 10000:
            raise ValueError('The filtered export exceeds 10,000 rows. Refine the search before exporting; no partial export was created.')
        page_query = query_base + f'''VAR DetailPageRows = EXCEPT(TOPN({page * size},DetailRows,{sort_args}),TOPN({(page-1)*size},DetailRows,{sort_args}))
RETURN DetailPageRows
ORDER BY {order_args}'''
        result = self.source.cached_query(page_query, ttl=45) if count else []
        rows = []
        for row in result:
            item = {key: row.get(key) for key in FIELDS}
            for key in ('order_key', 'invoice_key'):
                if item[key] is not None and not isinstance(item[key], str):
                    raise FulfillmentUnavailable('Source identifiers must be text to preserve leading zeros.')
            item['amount'] = money(item['amount'])
            for key in ('accounting_date', 'order_date'):
                item[key] = str(item[key])[:10] if item[key] else None
            rows.append(item)
        detail_total, control_total = money(meta.get('detail_total')), money(meta.get('measure_total'))
        detail_check = 'filtered' if search else 'unavailable'
        if not search and detail_total is not None and control_total is not None:
            detail_check = 'reconciled' if abs(cents(detail_total) - cents(control_total)) <= CENT else 'warning'
        return {'ready': True, 'month': month.strftime('%Y-%m'), 'cohort': COHORTS.get(cohort, 'All cohorts'),
                'search': search, 'page': page, 'page_size': size, 'total_rows': count,
                'pages': max(1, (count + size - 1) // size), 'total': detail_total,
                'control_total': control_total, 'reconciliation': detail_check,
                'rows': rows, 'export_scope': 'All rows matching the accounting month, cohort and search; maximum 10,000 rows.'}
