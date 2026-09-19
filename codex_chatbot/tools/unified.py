"""Read-only business capabilities; no legacy chat orchestration or API-key LLM."""
import json
import re
import unicodedata
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from reports.access_control import has_module_access, is_platform_admin
from reports.homepage_availability_service import HomepageAvailabilityService, HomepageAvailabilityError
from reports.homepage_fuel_service import HomepageFuelService
from reports.intent_extractor_service import extract_intent
from reports.resource_knowledge_search_service import search_resource_knowledge
from .minesite_resolution import resolve_minesite_from_question


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))


def unified_analysis(question,*,user):
    text=normalized(question)
    metrics=re.findall(r'\b(mtbf|mtbs|mttr|fuel|carburant|gasoil|consommation)\b',text)
    documentation = bool(re.search(r'\b(document(?:ation)?s?|procedures?|manuels?|manual|best practices|bonnes pratiques|maintenance|inspection|depannage)\b', text))
    if metrics and not documentation:
        if not (is_platform_admin(user) or has_module_access(user,'reporting')):
            return {'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED','text':'Vous n’avez pas accès aux données de performance.'}
        intent=extract_intent(question,'performance',allow_llm=False)
        filters=dict(intent.get('filters') or {})
        resolution=resolve_minesite_from_question(question,user=user)
        if resolution and resolution.ambiguous:
            return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':'Plusieurs sites correspondent. Précisez le MineSite.'}
        if resolution:filters.setdefault('minesite',resolution.semantic_name)
        if any(isinstance(v, (list, tuple)) and len(v) > 1 for v in filters.values()):
            return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':'Précisez un seul périmètre pour chaque filtre.'}
        filters = {k: (v[0] if v else '') if isinstance(v, (list, tuple)) else v for k, v in filters.items()}
        period=str(filters.get('period') or '').casefold()
        if period and period not in ('ytd','year to date','last 12 months','last_12_months','12 derniers mois','rolling 12 months'):
            return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':'Pour ces indicateurs, précisez YTD ou les 12 derniers mois.'}
        params={k:v for k,v in filters.items() if k in ('minesite','customer','model','family','equipment','serial_number')}
        params.update(period='last_12_months' if '12' in period else 'ytd',breakdown='overall')
        rows=[];payloads=[]
        for metric in dict.fromkeys('fuel' if m in ('fuel','carburant','gasoil','consommation') else m for m in metrics):
            try:
                service=HomepageFuelService(user) if metric=='fuel' else HomepageAvailabilityService(user)
                payload=service.get(service.request_from_params({**params,'metric':metric}))
            except (PermissionDenied,HomepageAvailabilityError) as exc:
                restricted=isinstance(exc,PermissionDenied) or getattr(exc,'status',503)==403
                return {'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED' if restricted else 'TEMPORARILY_UNAVAILABLE',
                        'text':'Périmètre non autorisé.' if restricted else 'La source de performance est temporairement indisponible.'}
            value=payload.get('metric') or payload.get('availability') or {}
            rows.append({'metric':metric.upper(),'period':(payload.get('context') or {}).get('period_label'),
                         'value':value.get('raw_value'),'formatted_value':value.get('formatted_value')})
            payloads.append({key:payload.get(key) for key in ('context','metric','data_quality','warnings','summary')})
        result={'kind':'governed_answer','answer_status':'ANSWERABLE' if all(r['value'] is not None for r in rows) else 'PARTIALLY_ANSWERABLE','source_table':'Excellence Center governed semantic services',
                'rows':rows,'payloads':payloads,
                'text':'\n'.join(f"{r['metric']} — {r['period']} : {r['formatted_value'] if r['formatted_value'] is not None else 'donnée indisponible'}" for r in rows)}
        return json.loads(json.dumps(result,cls=DjangoJSONEncoder))
    if documentation:
        if not (is_platform_admin(user) or has_module_access(user,'ai')):
            return {'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED','text':'Vous n’avez pas accès aux connaissances métier.'}
        payload=search_resource_knowledge(question,user=user,mode='Production',use_embeddings=False,limit=5)
        items=payload.get('results') or []
        return {'kind':'governed_answer','answer_status':'ANSWERABLE' if items else 'NEEDS_CLARIFICATION',
                'source_table':'Validated resource knowledge','knowledge':items,
                'text':'\n\n'.join(f"{x.get('title','Document')} — {x['source']['title']} (page {x['source'].get('page') or 'non précisée'})\n{x['source'].get('excerpt','')}\n{x['source']['url']}" for x in items)
                       if items else 'Aucun extrait documentaire validé ne correspond. Précisez le document ou l’équipement.'}
    return None
