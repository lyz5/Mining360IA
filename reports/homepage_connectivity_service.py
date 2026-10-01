
from .excellence_filter_values import read_filters, merge_authorized_filters, option_filters, values, compact, prefix_clause, valid_prefix
"""Connectivity cards from the verified Neembers semantic model via inspectData5."""
import hashlib
import json
import time

from django.core.cache import cache
from django.utils import timezone

from .access_control import is_platform_admin
from .homepage_availability_service import (
    HomepageAvailabilityError, HomepageRequest, _as_float, _dax_column,
    _dax_string, _extract_rows, _row_value,
)
from .models import HomepageConfiguration, PowerBIReport
from .power_automate import execute_dax_via_flow


class HomepageConnectivityService:
    DATASET_NAME = 'Neemba Monthly Report_New'
    COLUMNS = {
        'minesite': ('EquipmentList_MiningProd', 'Site'),
        'model': ('EquipmentList_MiningProd', 'Model'),
        'equipment': ('EquipmentList_MiningProd', 'Equipment'),
    }
    SERIAL_COLUMN = ('EquipmentList_MiningProd', 'SN')
    MEASURES = {
        'total_assets': '[Nb Equip]', 'connected_count': '[Count Connected]',
        'reporting_count': '[Count Reporting]', 'connected_ratio': '[% Connected _]',
        'reporting_ratio': '[% Reporting_]',
    }

    def __init__(self, user=None):
        self.user = user
        self.config = HomepageConfiguration.objects.filter(active=True).order_by('id').first() or HomepageConfiguration()
        self.report = PowerBIReport.objects.filter(report_name__iexact=self.DATASET_NAME,
            is_active=True, validation_status='Validated').order_by('id').first()
        if not self.report:
            raise HomepageAvailabilityError('Neembers Connectivity is not configured and validated.',
                code='connectivity_model_missing', status=503)

    def request_from_params(self, params):
        period = 'current'
        if params.get('customer') or params.get('serial_number'):
            raise HomepageAvailabilityError('For Connectivity, select a site, model or equipment.',
                code='unsupported_connectivity_filter', status=400)
        breakdown = str(params.get('breakdown') or 'overall').casefold()
        if breakdown not in {'overall', *self.COLUMNS}:
            raise HomepageAvailabilityError('Unsupported grouping.', code='invalid_breakdown', status=400)
        filters = read_filters(params, (*self.COLUMNS, 'prefix'))
        return HomepageRequest('connectivity', period, breakdown, filters, 1, 2000, 'entity_asc', '')

    def _scope(self):
        if not self.user or not self.user.is_authenticated:
            raise HomepageAvailabilityError('Authentication required.', code='permission_denied', status=403)
        platform = getattr(self.user, 'platformuser', None)
        identity = str(getattr(platform, 'user_principal_name', '') or
            getattr(platform, 'email', '') or self.user.email or self.user.get_username()).strip()
        if is_platform_admin(self.user):
            return {}, self.report.default_rls_role or '', identity
        raw = getattr(platform, 'business_performance_scope', {}) or {}
        # Do not silently discard customer/account restrictions: no verified mapping exists here.
        if any(value for key, value in raw.items() if key not in {'minesite', 'minesites', 'sites', 'rls_role'}):
            raise HomepageAvailabilityError('Connectivity access scope has not been fully mapped.',
                code='connectivity_scope_unmapped', status=403)
        sites = raw.get('minesite') or raw.get('minesites') or raw.get('sites')
        sites = sites if isinstance(sites, list) else [sites] if sites else []
        sites = [str(site).strip() for site in sites if str(site or '').strip()]
        if not sites:
            raise HomepageAvailabilityError('An authorized MineSite scope is required for Connectivity.',
                code='connectivity_scope_required', status=403)
        return {'minesite': sites}, str(raw.get('rls_role') or self.report.default_rls_role or ''), identity

    @staticmethod
    def _merge_filters(scope, requested):
        return merge_authorized_filters(scope, requested)

    @classmethod
    def _clauses(cls, filters):
        return [prefix_clause(_dax_column(*cls.SERIAL_COLUMN), selected) if key == 'prefix' else
                f'TREATAS({{{", ".join(_dax_string(v) for v in selected)}}}, {_dax_column(*cls.COLUMNS[key])})'
                for key, selected in filters.items()]


    def build_dax(self, request, merged, scope):
        # This is the global filter read from the published report, not a new business rule.
        base = [ '''FILTER(ALL('FACT - PCR'[STRATEGY]), NOT('FACT - PCR'[STRATEGY] IN {"GOH","TOH"}))''']
        base.append('TREATAS({"Yes"}, \'MineSiteList_MiningProd\'[Focus])')
        args = ','.join(base + self._clauses(merged))
        measures = ','.join(f'"{key}",{measure}' for key, measure in self.MEASURES.items())
        summary = f'CALCULATETABLE(ROW("RowType","summary","Entity","Overall",{measures}),{args})'
        dimension = self.COLUMNS['minesite' if request.breakdown == 'overall' else request.breakdown]
        column = _dax_column(*dimension)
        select_values = ','.join(f'"{key}",[{key}]' for key in self.MEASURES)
        groups = f'SELECTCOLUMNS(SUMMARIZECOLUMNS({column},{args},{measures}),"RowType","breakdown","Entity",{column},{select_values})'
        parts = [summary, groups]
        for key, dimension in self.COLUMNS.items():
            # Remove only the requested value for this dropdown; never remove access restrictions.
            dropdown_filters = option_filters(merged, scope, key)
            option_args = ','.join(base + self._clauses(dropdown_filters))
            column = _dax_column(*dimension)
            blanks = ','.join(f'"{name}",BLANK()' for name in self.MEASURES)
            parts.append(f'SELECTCOLUMNS(SUMMARIZECOLUMNS({column},{option_args},"OptionCount",[Nb Equip]),"RowType","option_{key}","Entity",{column},{blanks})')
        serial_column = _dax_column(*self.SERIAL_COLUMN)
        prefix_args = ','.join(base + self._clauses(option_filters(merged, scope, 'prefix')))
        blanks = ','.join(f'"{name}",BLANK()' for name in self.MEASURES)
        parts.append(f'DISTINCT(SELECTCOLUMNS(FILTER(SUMMARIZECOLUMNS({serial_column},{prefix_args},"OptionCount",[Nb Equip]),LEN(TRIM({serial_column})) >= 3),"RowType","option_prefix","Entity",LEFT(UPPER(TRIM({serial_column})),3),{blanks}))')
        return 'EVALUATE UNION(' + ',\n'.join(parts) + ')'

    def _normalize(self, rows, request, elapsed):
        summary = next((r for r in rows if _row_value(r, 'RowType') == 'summary'), None)
        if summary is None:
            raise HomepageAvailabilityError('Connectivity returned no verified summary.', code='connectivity_empty_response', status=503)
        values = lambda row: {key: _as_float(_row_value(row, key)) for key in self.MEASURES}
        options = {key: set() for key in (*self.COLUMNS, 'prefix')}
        groups = []
        for row in rows:
            kind = str(_row_value(row, 'RowType') or '')
            entity = str(_row_value(row, 'Entity') or '').strip()
            if kind == 'breakdown' and entity:
                groups.append({'entity': entity, **values(row)})
            elif kind.startswith('option_') and kind[7:] in options and entity:
                if kind == "option_prefix" and not valid_prefix(entity):
                    continue
                options[kind[7:]].add(entity)
        return {'ok': True, 'context': {'metric_code': 'connectivity', 'metric_label': 'Connectivity',
            'period_code': 'current', 'period_label': 'Current state',
            'start_date': None, 'end_date': None,
            'filters': request.filters, 'breakdown': request.breakdown},
            'connectivity': values(summary), 'breakdown': sorted(groups, key=lambda r:r['entity'].casefold()),
            'filter_options': {key: sorted(items, key=str.casefold) for key, items in options.items()},
            'meta': {'cached': False, 'duration_ms': elapsed, 'retrieved_at': timezone.now().isoformat(),
                'source': 'Mine Monthly Report - Neembers', 'flow': 'inspectData5', 'measures': self.MEASURES}}

    def get(self, request, *, force_refresh=False):
        scope, role, identity = self._scope()
        merged = self._merge_filters(scope, request.filters)
        from .models import SystemIntegrationConfig
        connection_version = SystemIntegrationConfig.objects.filter(code='power-automate-dax').values_list('updated_at', flat=True).first()
        key_data = [self.user.pk, scope, role, identity, self.report.semantic_model_id,
            str(connection_version), request.period, request.breakdown, merged]
        key = 'homepage:connectivity:v5-prefix:' + hashlib.sha256(json.dumps(key_data,sort_keys=True).encode()).hexdigest()
        cached = None if force_refresh else cache.get(key)
        if cached is not None:
            return {**cached, 'meta': {**cached['meta'], 'cached': True}}
        started = time.monotonic()
        try:
            result = execute_dax_via_flow({'datasetId': self.report.semantic_model_id,
                'datasetName': self.DATASET_NAME, 'query': self.build_dax(request, merged, scope),
                'question': 'Mining360 Connectivity Excellence Center', 'section': 'connectivity',
                'filters': merged, 'rlsRole': role, 'roles': [role] if role else [], 'effectiveUser': identity})
            rows = _extract_rows(result)
        except Exception:
            raise HomepageAvailabilityError('Connectivity data is temporarily unavailable.',
                code='connectivity_unavailable', status=503) from None
        payload = self._normalize(rows, request, int((time.monotonic()-started)*1000))
        cache.set(key, payload, 60)
        return payload
