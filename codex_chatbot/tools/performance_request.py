"""Deterministic performance scope and date parsing, without LLM calculations."""
import calendar
import re
import unicodedata
from datetime import date, timedelta
from django.utils import timezone
from reports.performance_periods import bounds
from reports.temporal_expression_resolution_service import resolve_temporal_expression, MONTHS


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def parse_request(question, filters, today=None):
    today = today or timezone.localdate()
    text = normalized(question)
    params = {k:v for k,v in filters.items() if k in ('minesite','customer','model','family','equipment','serial_number')}
    family_match=re.search(r'\b(?:family|famille)\s*[:=]?\s+([a-z][a-z -]*?)(?=\s+(?:en|in|at|a|au|pour|for|ytd|mtd|par|by|du|from|sur)\b|[;,?]|$)',text)
    if family_match and not re.search(r'\b(?:par|by|per)\s+(?:family|famille)\b',text):
        params['family']=family_match.group(1).strip().upper()
    if params.get('family'):
        params['family']=re.split(r'\s+(?:en|in|ytd|mtd|par|by|depuis|du|from|sur)\b',str(params['family']),maxsplit=1,flags=re.I)[0].strip()
    dimensions = []
    for dimension, terms in [('minesite',r'sites?|minesites?'), ('model',r'models?|modeles?'),
                             ('family',r'famil(?:y|ies|le|les)'), ('equipment',r'equipments?|equipements?')]:
        if re.search(r'\b(?:par|by|per)\s+(?:les?\s+|tous les\s+|each\s+)?(?:'+terms+r')\b',text):
            dimensions.append(dimension)
    if len(dimensions)>1:
        raise ValueError('Choose one grouping: site, model, family, or equipment.')
    params['breakdown'] = dimensions[0] if dimensions else 'overall'
    monthly = bool(re.search(r'\b(?:par mois|by month|monthly|mensuel(?:le)?s?)\b',text))
    period = None
    iso = re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text)
    french = re.findall(r'\b(\d{2})/(\d{2})/(\d{4})\b',text)
    if iso or french:
        dates = [date.fromisoformat(item) for item in iso] if iso else [date(int(y),int(m),int(d)) for d,m,y in french]
        if len(dates)!=2:
            raise ValueError('Specify both start and end dates, for example 2026-01-01 to 2026-03-31.')
        start,end=dates
    elif re.search(r'\b(?:ytd|year to date)\b',text):
        years=re.findall(r'\b20\d{2}\b',text)
        if years and int(years[0])!=today.year:
            raise ValueError('For a previous year, specify an explicit start and end date.')
        period='ytd'
    elif re.search(r'\b(?:mtd|month to date)\b',text):
        start,end=today.replace(day=1),today
    elif re.search(r'\b(?:last year|previous year|annee derniere|annee precedente)\b',text):
        start,end=date(today.year-1,1,1),date(today.year-1,12,31)
    else:
        temporal=resolve_temporal_expression(question,reference_date=today)
        month_mentions=re.findall(r'\b(?:'+'|'.join(MONTHS)+r')\b',text)
        if len(month_mentions)>1 and (not temporal or temporal.get('type')!='month_range'):
            raise ValueError('Specify a continuous month range, for example January to March 2026.')
        if temporal and temporal.get('start_date'):
            start,end=date.fromisoformat(temporal['start_date']),date.fromisoformat(temporal['end_date'])
        elif temporal and temporal.get('type')=='rolling_months':
            months=temporal['months']
            if months==12:
                period='last_12_months'
            else:
                year,month=divmod(today.year*12+today.month-months,12)
                start,end=date(year,month+1,1),today
        else:
            years=re.findall(r'\b20\d{2}\b',text)
            if len(years)==1:
                start,end=date(int(years[0]),1,1),date(int(years[0]),12,31)
            elif len(years)>1:
                raise ValueError('Specify an explicit date range.')
            elif filters.get('period') and str(filters['period']).casefold() not in ('ytd','year to date','last 12 months','last_12_months'):
                raise ValueError('Specify a year, month, YTD, last 12 months, or explicit dates.')
            elif re.search(r'\b(?:yesterday|hier|week|semaine|quarter|trimestre)\b',text):
                raise ValueError('For that period, specify explicit start and end dates.')
            else:
                period='last_12_months' if '12' in str(filters.get('period','')) else 'ytd'
    if not period:
        period=f'custom:{start.isoformat()}:{end.isoformat()}'
    bounds(period)
    params['period']=period
    return params,monthly


def monthly_windows(period, reference_date):
    window=bounds(period)
    if window:
        start,end=window
    elif period=='ytd':
        start,end=date(reference_date.year,1,1),reference_date
    else:
        year,month=divmod(reference_date.year*12+reference_date.month-12,12)
        start,end=date(year,month+1,1),reference_date
    windows=[]
    while start<=end:
        last=min(date(start.year,start.month,calendar.monthrange(start.year,start.month)[1]),end)
        windows.append(f'custom:{start.isoformat()}:{last.isoformat()}')
        start=last+timedelta(days=1)
    if len(windows)>24:
        raise ValueError('Monthly comparisons are limited to 24 months per question.')
    return windows
