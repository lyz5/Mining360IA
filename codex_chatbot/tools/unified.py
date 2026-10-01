"""Read-only business capabilities; no legacy chat orchestration or API-key LLM."""
import json
import re
import unicodedata
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from reports.access_control import has_module_access, is_platform_admin
from reports.homepage_availability_service import HomepageAvailabilityService, HomepageAvailabilityError
from reports.homepage_fuel_service import HomepageFuelService
from reports.intent_extractor_service import extract_intent
from reports.resource_knowledge_search_service import search_resource_knowledge
from reports.resource_document_memory import is_document_question, search_document_memory
from .minesite_resolution import resolve_minesite_from_question
from .metric_intent import requested_metrics
from .performance_request import parse_request, monthly_windows, completed_ytd_period, label_completed_ytd
from .excellence_evidence import requested_views, evidence_sections, unavailable_views
from .performance_followup import needs_performance_context
from .downtime_systems import system_breakdown


def performance_payload(user, params):
    from reports.dashboard_snapshots import enabled, excellence_snapshot
    requested_period=params.get('period','ytd')
    try:
        resolved_period=completed_ytd_period(requested_period)
    except ValueError as exc:
        raise HomepageAvailabilityError(str(exc),code='no_completed_ytd_month',status=400) from None
    params={**params,'period':resolved_period}
    if enabled():
        payload=excellence_snapshot(user, params)
    else:
        service=HomepageFuelService(user) if params.get('metric')=='fuel' else HomepageAvailabilityService(user)
        payload=service.get(service.request_from_params(params))
    return label_completed_ytd(payload,requested_period,resolved_period)


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))


def unified_analysis(question,*,user,inherited_context=None):
    text=normalized(question)
    metrics=requested_metrics(question)
    views=requested_views(question)
    if 'downtime_systems' in views:metrics=['availability']
    if 'downtime' in views:views.discard('ranking')
    if not metrics and re.search(r'\bexcellence(?: center)?\b',text):
        metrics=['availability','mtbf','mttr','mtbs','fuel']
    if not metrics and re.search(r'\b(?:downtimes?|heures? d.arret)\b',text):
        metrics=['availability']
    followup=needs_performance_context(question)
    if followup and not inherited_context:
        return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION',
                'text':'Précisez le site, le modèle et la période : aucun périmètre de performance unique n’est disponible dans la demande précédente.'}
    if not metrics and views & {'trend','distribution','statistics','target','quality'} and not re.search(r'\b(?:fleet|flotte|inventaire|inventory|couverture|coverage)\b',text):
        return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION',
                'text':'Which Excellence Center metric do you mean: Availability, MTBF, MTTR, MTBS or Fuel (L/h)?'}
    if metrics == ['availability'] and not followup:
        try:
            basic,monthly=parse_request(question,{})
            if basic['period'] in ('ytd','last_12_months') and basic['breakdown']=='overall' and not basic.get('family') and not monthly and not views:
                metrics=[]  # Preserve the existing dedicated Availability presentation.
        except ValueError:
            pass  # Report the invalid period below, never silently fall back to YTD.
    documentation = is_document_question(question)
    if metrics and not documentation:
        if not (is_platform_admin(user) or has_module_access(user,'reporting')):
            return {'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED','text':'Vous n’avez pas accès aux données de performance.'}
        extraction_question=re.sub(r'\b(?:par|by|per)\s+(?:les?\s+|tous les\s+|each\s+)?(?:sites?|minesites?|modeles?|models?|famil(?:y|ies|le|les)|equipments?|equipements?)\b','',text)
        intent=extract_intent(question if extraction_question==text else extraction_question,'performance',allow_llm=False)
        filters=dict(intent.get('filters') or {})
        if followup:
            filters={**inherited_context['filters'],**filters}
        resolution=resolve_minesite_from_question(question,user=user)
        if resolution and resolution.ambiguous:
            return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':'Plusieurs sites correspondent. Précisez le MineSite.'}
        if resolution:
            if followup and not (intent.get('filters') or {}).get('minesite'):
                filters['minesite']=resolution.semantic_name
            else:
                filters.setdefault('minesite',resolution.semantic_name)
        if any(isinstance(v, (list, tuple)) and len(v) > 1 for v in filters.values()):
            return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':'Précisez un seul périmètre pour chaque filtre.'}
        filters = {k: (v[0] if v else '') if isinstance(v, (list, tuple)) else v for k, v in filters.items()}
        try:
            params,monthly=parse_request(question,filters)
            explicit_ytd = re.search(r"\b(?:ytd|year to date|depuis le debut de l[’']annee|since the beginning of the year)\b", text)
            if followup and not explicit_ytd and params['period']=='ytd':
                params['period']=inherited_context['period_code']
            if 'details' in views and params['breakdown']=='overall':
                params.update(breakdown='equipment',page_size=100)
            elif 'details' in views and params['breakdown']=='equipment':
                params['page_size']=100
            if 'downtime' in views:
                params.update(breakdown='equipment',ordering='downtime_desc',page_size=100)
            if 'downtime_systems' in views:
                params['breakdown']='overall'
            periods=monthly_windows(params['period'],timezone.localdate()) if monthly else [params['period']]
            if len(periods)*len(metrics)>36:
                raise ValueError('Limit this comparison to 36 metric/month combinations.')
        except ValueError as exc:
            return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':str(exc)}
        rows=[];payloads=[];tables=[];unavailable=[]
        for metric, period in ((metric,period) for metric in dict.fromkeys(metrics) for period in periods):
            try:
                payload=performance_payload(user,{**params,'metric':metric,'period':period})
                if 'downtime_systems' in views:
                    payload={**payload,'downtime_systems':system_breakdown(user,{**params,'period':period},payload)}
            except (PermissionDenied,HomepageAvailabilityError) as exc:
                if getattr(exc,'status',503)==400:
                    return {'kind':'governed_answer','answer_status':'NEEDS_CLARIFICATION','text':str(exc)}
                restricted=isinstance(exc,PermissionDenied) or getattr(exc,'status',503)==403
                return {'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED' if restricted else 'TEMPORARILY_UNAVAILABLE',
                        'text':'Périmètre non autorisé.' if restricted else 'La source de performance est temporairement indisponible.'}
            value=payload.get('metric') or payload.get('availability') or {}
            context=payload.get('context') or {}
            if period.startswith('custom:') and context.get('period_code')!=period:
                return {'kind':'governed_answer','answer_status':'TEMPORARILY_UNAVAILABLE',
                        'text':'The central snapshot did not return the requested date range.'}
            if 'downtime_systems' in views:
                for item in payload['downtime_systems']['rows']:
                    rows.append({'metric':'DOWNTIME','period':context.get('period_label'),
                                 'entity':item['system'],'dimension':'downtime_driver','value':item['hours'],
                                 'formatted_value':item['hours_formatted'],'share_percentage':item['share_percentage']})
            elif params['breakdown']!='overall':
                if context.get('breakdown')!=params['breakdown']:
                    return {'kind':'governed_answer','answer_status':'TEMPORARILY_UNAVAILABLE',
                            'text':'The central snapshot service does not yet support this grouping.'}
                for item in payload.get('breakdown') or []:
                    downtime='downtime' in views
                    item_value=item.get('downtime_hours') if downtime else item.get('metric_value',item.get('raw_value'))
                    rows.append({'metric':'DOWNTIME' if downtime else metric.upper(),'period':context.get('period_label'),
                                 'entity':item.get('entity'),'dimension':params['breakdown'],
                                 'value':item_value,
                                 'formatted_value':(f'{item_value:.2f} h' if item_value is not None else None) if downtime else item.get('formatted_value')})
            else:
                rows.append({'metric':metric.upper(),'period':context.get('period_label'),
                             'value':value.get('raw_value'),'formatted_value':value.get('formatted_value')})
            tables.extend(evidence_sections(payload,metric,views))
            unavailable.extend(f'{metric.upper()}: {view}' for view in unavailable_views(payload,metric,views))
            evidence_keys=['context','metric','data_quality','warnings','summary','dashboard_snapshot','meta']
            if 'downtime_systems' in views:evidence_keys+=['downtime_systems']
            if views & {'ranking','summary'}:evidence_keys+=['decision_support','key_takeaway']
            if 'statistics' in views:evidence_keys+=['statistics']
            payloads.append({key:payload.get(key) for key in evidence_keys})
        result={'kind':'governed_answer','answer_status':'ANSWERABLE' if rows and all(r['value'] is not None for r in rows) else 'PARTIALLY_ANSWERABLE','source_table':'Excellence Center governed semantic services',
                'rows':rows,'payloads':payloads,'tables':tables,'requested_views':sorted(views),'unavailable_sections':unavailable,
                'text':'\n'.join(f"{r['metric']} — {r.get('entity','Selected scope')} — {r['period']} : {r['formatted_value'] if r['formatted_value'] is not None else 'Unavailable'}" for r in rows) or 'No data is available for the requested scope.'}
        if unavailable:
            result['answer_status']='PARTIALLY_ANSWERABLE'
            result['text']+='\nUnavailable in this snapshot: '+', '.join(unavailable)+'.'
        if followup:
            result['inherited_scope']=inherited_context
        if 'downtime_systems' in views:
            result['source_table']='DowntimeData_MiningProd / configured downtime category and hours mappings'
            result['text']='\n'.join(f"{r['entity']} — {r['period']} : {r['formatted_value']} ({r['share_percentage']:.2f} % du downtime total)" if r['share_percentage'] is not None else f"{r['entity']} : {r['formatted_value']} (part indisponible)" for r in rows)
            result['text']+='\nCatégories enregistrées dans la source ; aucune fusion de systèmes ni diagnostic de cause racine. Le dénominateur comprend toutes les catégories, y compris celles non classées.'
            if re.search(r'\b(?:top|drivers?|principaux|principales)\b',text):
                sections=[]
                for payload in payloads:
                    systems=payload['downtime_systems'];context=payload['context']
                    entries=systems['rows'][:10]
                    scope=' / '.join(str(v) for v in (context.get('filters') or {}).values()) or 'Périmètre autorisé'
                    lines=[f"Top {len(entries)} downtime drivers — {scope}",
                           f"Période : {context.get('period_label', '')} ({context.get('start_date', '')} au {context.get('end_date', '')})",
                           '', '| Système / catégorie | Heures d’arrêt | Part du total |', '|---|---:|---:|']
                    for item in entries:
                        label=item['system'].replace('|','/').replace('\n',' ')
                        lines.append(f"| {label} | {item['hours_formatted']} | {item['share_formatted']} |")
                    if systems['total_hours'] is not None:
                        lines.append(f"\nDowntime total du périmètre : {systems['total_hours']:.2f} h. Les parts utilisent toutes les catégories du périmètre, pas seulement ce classement.")
                    if len(entries)<10:lines.append(f"Seulement {len(entries)} catégories disponibles ; aucune catégorie ajoutée artificiellement.")
                    sections.append('\n'.join(lines))
                result['text']='\n\n'.join(sections)+'\n\nSource : DowntimeData_MiningProd, classification configurée et mesure officielle des heures d’arrêt. Les catégories enregistrées ne constituent pas un diagnostic de causes racines.'
                result['fixed_top_downtime_count']=10
            if unavailable:result['text']+='\nCertaines données demandées sont indisponibles : '+', '.join(unavailable)
        if 'downtime' in views:
            result['text']+='\nClassement des équipements par heures d’arrêt enregistrées ; les causes des pannes ne sont pas établies par ces données.'
        return json.loads(json.dumps(result,cls=DjangoJSONEncoder))
    if documentation:
        if not (is_platform_admin(user) or has_module_access(user,'ai')):
            return {'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED','text':'Vous n’avez pas accès aux connaissances métier.'}
        payload=search_resource_knowledge(question,user=user,mode='Production',use_embeddings=False,limit=5)
        items=payload.get('results') or []
        memory=search_document_memory(question,user=user)
        sources=memory.get('results') or []
        available=bool(items or sources)
        return {
            'kind':'governed_answer',
            'answer_status':'ANSWERABLE' if available else (
                'TEMPORARILY_UNAVAILABLE' if memory.get('status') in ('unavailable','stale') else 'NEEDS_CLARIFICATION'),
            'source_table':'Resources original documents and separately validated knowledge',
            'knowledge':items, 'document_sources':sources,
            'document_memory_status':memory.get('status'),
            'document_limits':memory.get('limitations'),
            'text':(
                'Relevant source pages are available below. A technical synthesis could not be generated; '
                'consult these pages before applying a recommendation.\n' +
                '\n'.join(f"[{x['title']}]({x['url']}) — PDF pages " +
                          ', '.join(str(p['page']) for p in x['pages']) for x in sources)
                if sources else (
                    '\n\n'.join(f"{x.get('title','Document')} — {x['source']['title']} "
                                f"(PDF page {x['source'].get('page') or 'unspecified'})\n"
                                f"{x['source'].get('excerpt','')}\n{x['source']['url']}" for x in items)
                    if items else 'No verified source passage is available for this question. '
                                  'Specify the document, component or technical subject.'
                )
            ),
        }
    return None
