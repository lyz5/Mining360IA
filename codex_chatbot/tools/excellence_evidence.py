"""Expose existing Excellence payload sections without recalculating business KPIs."""
import re
from .performance_request import normalized


def requested_views(question):
    text=normalized(question)
    patterns={
        'trend':r'\b(?:trend|trends|tendance|tendances|evolution)\b',
        'distribution':r'\b(?:distribution|histogramme|histogram|repartition)\b',
        'statistics':r'\b(?:statistics|statistiques|median|mediane|percentiles?|quartiles?|p25|p75)\b',
        'ranking':r'\b(?:top|bottom|best|worst|meilleurs?|pires?|classement|ranking|lowest|highest|plus eleve|plus faible|moins performant)\b',
        'details':r'\b(?:details?|detaille|detaillee)\b|\b(?:liste|list|par|by)\s+(?:des?\s+)?(?:machines?|equipments?|equipements?)\b',
        'summary':r'\b(?:summary|resume|synthese|downtime|heures? d.arret|nombre|count|combien)\b',
        'downtime':r'\b(?:downtime|heures? d.arret)\b.*\b(?:drivers?|causes?|top|principal|principaux)\b|\b(?:drivers?|causes?|top|principal|principaux)\b.*\b(?:downtime|heures? d.arret)\b',
        'target':r'\b(?:target|targets|objectif|objectifs|cible|ecart|gap)\b',
        'quality':r'\b(?:freshness|fraicheur|actualisation|refresh|qualite|quality|updated|mise a jour)\b',
        'comparison':r'\b(?:comparison|comparaison|compare|compared|versus|vs|variation|change|benchmark)\b',
    }
    if re.search(r'\b(?:tout|toutes les informations|all information|full overview|complete overview|bilan complet)\b',text):
        return set(patterns)-{'downtime'}
    return {key for key,pattern in patterns.items() if re.search(pattern,text)}


def unavailable_views(payload,metric,views):
    value=payload.get('metric') or {}
    decision=payload.get('decision_support') or {}
    available={
        'trend':payload.get('trend'),
        'distribution':payload.get('distribution') if metric=='fuel' else payload.get('breakdown'),
        'statistics':payload.get('statistics'),
        'ranking':decision.get('lowest_observed') or payload.get('top_performers') or payload.get('bottom_performers'),
        'details':payload.get('equipment') if metric=='fuel' else payload.get('breakdown'),
        'summary':payload.get('summary'),'quality':payload.get('data_quality'),
        'downtime':metric!='fuel' and any(row.get('downtime_hours') is not None for row in payload.get('breakdown') or []),
        'target':metric=='availability' and value.get('target_raw') is not None,
        'comparison':value.get('comparison') or value.get('benchmark_formatted'),
    }
    return sorted(view for view in views if not available.get(view))


def evidence_sections(payload, metric, views):
    """Return bounded, labelled tables plus full scalar evidence for the requested views."""
    tables=[]
    context=payload.get('context') or {}
    prefix=f"{metric.upper()} · {context.get('period_label','')}"
    def add(title,rows,columns):
        if rows:
            tables.append({'title':prefix+' · '+title,'rows':rows[:100], 'total_rows':len(rows),
                           'columns':columns,'truncated':len(rows)>100})
    def scalars(title,value):
        if not isinstance(value,dict):return
        rows=[{'field':key.replace('_',' ').title(),'value':item} for key,item in value.items()
              if item is not None and isinstance(item,(str,int,float,bool))]
        add(title,rows,[['field','Indicator'],['value','Value']])
    if 'trend' in views:
        add('Trend',payload.get('trend') or [],[['period','Period'],['formatted_value','Value']])
    if 'distribution' in views:
        add('Distribution',payload.get('distribution') or [],[['lph','Band upper bound (L/h)'],['count','Equipment'],['percentage','Share (%)']])
        if metric!='fuel':
            add('Scope breakdown',payload.get('breakdown') or [],[['entity','Entity'],['formatted_value','Value'],['equipment_count','Equipment']])
    if 'statistics' in views:scalars('Statistics (L/h)' if metric=='fuel' else 'Statistics',payload.get('statistics'))
    if 'ranking' in views:
        decision=payload.get('decision_support') or {}
        add('Lowest observed' if metric=='fuel' else 'Top performers',decision.get('lowest_observed') or payload.get('top_performers') or [],
            [['entity','Entity'],['formatted_value','Value'],['model','Model'],['minesite','MineSite']])
        add('Highest observed' if metric=='fuel' else 'Bottom performers',decision.get('highest_observed') or payload.get('bottom_performers') or [],
            [['entity','Entity'],['formatted_value','Value'],['model','Model'],['minesite','MineSite']])
    if 'details' in views:
        rows=payload.get('equipment') if metric=='fuel' else payload.get('breakdown')
        add('Equipment details',rows or [],[['equipment' if metric=='fuel' else 'entity','Equipment'],
            ['lph' if metric=='fuel' else 'formatted_value','L/h' if metric=='fuel' else 'Value'],
            ['model','Model'],['minesite','MineSite']])
        pagination=payload.get('breakdown_pagination') or {}
        if metric!='fuel' and rows and pagination.get('count',0)>len(rows):
            tables[-1]['total_rows']=pagination['count'];tables[-1]['truncated']=True
    if 'summary' in views:scalars('Summary',payload.get('summary'))
    if 'downtime' in views and metric!='fuel':
        add('Equipment by recorded downtime (not root causes)',payload.get('breakdown') or [],
            [['entity','Equipment'],['downtime_hours','Downtime hours'],['model','Model'],['minesite','MineSite']])
    if 'quality' in views:
        scalars('Data freshness',payload.get('data_quality'))
        scalars('Snapshot',payload.get('dashboard_snapshot'))
    if 'target' in views and metric=='availability':
        value=payload.get('metric') or {}
        scalars('Target',{key:value.get(key) for key in ('target_formatted','gap_points','status','customer_type')})
    if 'comparison' in views:
        value=payload.get('metric') or {}
        scalars('Comparison',value.get('comparison'))
        if metric=='fuel':scalars('Benchmark',{'benchmark':value.get('benchmark_formatted')})
    return tables
