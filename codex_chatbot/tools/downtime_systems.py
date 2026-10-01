"""Read configured downtime categories with semantic hours and full-scope shares."""
from datetime import date
import math
from reports.ai_config_service import get_metric_mapping, get_filter_mapping
from reports.homepage_availability_service import (
    HomepageAvailabilityService, HomepageAvailabilityError, _dax_column,
    _dax_string, _row_value, HOMEPAGE_PRODUCT_GROUP_CODES,
)


def parse_system_rows(rows, expected_total):
    total_rows=[r for r in rows if _row_value(r,'RowType')=='total']
    if len(total_rows)!=1:
        raise HomepageAvailabilityError('Downtime total is missing.',code='downtime_total_missing')
    total=_row_value(total_rows[0],'Hours')
    if total is None:
        return {'total_hours':None,'rows':[],'complete':False}
    total=float(total)
    if not math.isfinite(total) or total<0:
        raise HomepageAvailabilityError('Invalid downtime total.',code='downtime_invalid')
    result=[]
    for row in rows:
        if _row_value(row,'RowType')!='system':continue
        hours=float(_row_value(row,'Hours'))
        share=_row_value(row,'SharePercentage')
        share=float(share) if share is not None else None
        if not math.isfinite(hours) or hours<0 or (share is not None and not math.isfinite(share)):
            raise HomepageAvailabilityError('Invalid category values.',code='downtime_invalid')
        if total and (share is None or not math.isclose(share,hours/total*100,abs_tol=1e-6)):
            raise HomepageAvailabilityError('Category share does not reconcile.',code='downtime_reconciliation_failed')
        name=_row_value(row,'System')
        result.append({'system':str(name).strip() if name and str(name).strip() else 'Non classé',
                       'unclassified':not bool(name and str(name).strip()),'hours':hours,
                       'share_percentage':share,'hours_formatted':f'{hours:.2f} h',
                       'share_formatted':f'{share:.2f} %' if share is not None else 'Indisponible'})
    if not math.isclose(sum(r['hours'] for r in result),total,abs_tol=0.01):
        raise HomepageAvailabilityError('Category hours do not reconcile to the full total.',code='downtime_reconciliation_failed')
    if expected_total is None or not math.isclose(total,float(expected_total),abs_tol=0.01):
        raise HomepageAvailabilityError('Category total differs from Excellence Center.',code='downtime_reconciliation_failed')
    result.sort(key=lambda r:(-r['hours'],r['system']))
    return {'total_hours':total,'rows':result,'complete':True}


def system_breakdown(user,params,baseline):
    from reports.dashboard_snapshots import configuration
    if configuration().get('role')=='replica':
        raise HomepageAvailabilityError('System categories are not available from the configured snapshot replica.',code='downtime_snapshot_unsupported')
    service=HomepageAvailabilityService(user)
    request=service.request_from_params({**params,'metric':'availability','breakdown':'overall'})
    scope,role,principal=service._scope()
    merged=service._merge_filters(scope,request.filters)
    for key in merged:
        if key not in service.filter_mappings:
            raise HomepageAvailabilityError('Scope mapping is missing.',code='dimension_mapping_missing')
    metric=next((m for m in get_metric_mapping('performance') if m.get('is_active') and m['metric_code']=='downtime_hours'),None)
    mapping=next((m for m in get_filter_mapping('performance') if m.get('is_active') and m['filter_code']=='downtime_driver'),None)
    if not metric or not mapping:
        raise HomepageAvailabilityError('Downtime category mapping is missing.',code='downtime_mapping_missing')
    driver=_dax_column(mapping['powerbi_table_name'],mapping['powerbi_column_name'])
    measure=metric['powerbi_measure_name']
    context=baseline['context']
    try:
        start=date.fromisoformat(context['start_date']);end=date.fromisoformat(context['end_date'])
    except (KeyError,TypeError,ValueError):
        raise HomepageAvailabilityError('Verified dates are missing.',code='downtime_dates_missing') from None
    focus=service.filter_mappings.get('focus') or {'powerbi_table_name':'MineSiteList_MiningProd','powerbi_column_name':'Focus'}
    clauses=[f'TREATAS({{"Yes"}}, {_dax_column(focus["powerbi_table_name"],focus["powerbi_column_name"])})',*service._filter_clauses(merged)]
    allowed=''
    if 'model' in merged or params.get('breakdown') in {'model','equipment'}:
        group=service.filter_mappings.get('homepage_product_group') or {'powerbi_table_name':'ModelList_MiningProd','powerbi_column_name':'PrimeMovers'}
        reference=service.filter_mappings.get('homepage_model_reference') or {'powerbi_table_name':'ModelList_MiningProd','powerbi_column_name':'Model'}
        model=service.filter_mappings['model']
        codes=', '.join(_dax_string(x) for x in HOMEPAGE_PRODUCT_GROUP_CODES)
        allowed=f'VAR __AllowedModels = CALCULATETABLE(VALUES({_dax_column(reference["powerbi_table_name"],reference["powerbi_column_name"])}), TREATAS({{{codes}}}, {_dax_column(group["powerbi_table_name"],group["powerbi_column_name"])}))\n'
        clauses.append(f'TREATAS(__AllowedModels, {_dax_column(model["powerbi_table_name"],model["powerbi_column_name"])})')
    filters=', '.join(clauses)
    dax=f'''DEFINE
{allowed}VAR __Period = DATESBETWEEN('Date'[Date], DATE({start.year},{start.month},{start.day}), DATE({end.year},{end.month},{end.day}))
VAR __Total = CALCULATE({measure}, __Period, {filters})
VAR __Systems = CALCULATETABLE(SUMMARIZECOLUMNS({driver}, "Hours", {measure}), __Period, {filters})
EVALUATE UNION(
 ROW("RowType","total","System",BLANK(),"Hours",__Total,"SharePercentage",BLANK()),
 SELECTCOLUMNS(FILTER(__Systems, NOT ISBLANK([Hours])), "RowType","system","System",{driver},"Hours",[Hours],"SharePercentage",DIVIDE([Hours],__Total)*100)
)'''
    rows,_=service._execute(dax,merged,role,principal)
    result=parse_system_rows(rows,(baseline.get('summary') or {}).get('downtime_hours'))
    result.update(source_table=mapping['powerbi_table_name'],source_column=mapping['powerbi_column_name'],source_measure=measure,
                  percentage_definition='Category hours / full scoped downtime hours × 100; no top-N denominator')
    return result
