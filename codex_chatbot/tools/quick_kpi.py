"""Render simple, verified KPI lookups without a language-model round trip."""
import re
import unicodedata
from codex_chatbot.response_language import question_language, period_label


METRICS = {'availability', 'mtbf', 'mtbs', 'mttr', 'fuel'}


def quick_kpi_answer(question, evidence):
    text = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold())
                   if not unicodedata.combining(c))
    # Explanations, comparisons, documentation and recommendations still use AI.
    if re.search(r'\b(?:pourquoi|why|comment|how|expli\w*|analys\w*|interpret\w*|'
                 r'compar\w*|versus|vs|ecart\w*|evolution|trend|tendance|cause\w*|'
                 r'recommand\w*|recommend\w*|conseil\w*|amelior\w*|improv\w*|'
                 r'plan|action\w*|objectif\w*|target\w*|benchmark\w*|normal|'
                 r'bon|bonne|good|bad|definition|signifi\w*|mean\w*|calcul\w*)\b', text):
        return None
    lookup_text = re.sub(r'^\s*(?:et|and|what about)\s+', '', text)
    if not re.match(r'^\s*(?:donne\w*|affiche\w*|montre\w*|quel\w*|combien|'
                    r'give|show|what|get|le\b|la\b|les\b|the\b|dispo\w*|'
                    r'availability\b|mtbf\b|mtbs\b|mttr\b|fuel\b|lph\b|'
                    r'consommation\b|carburant\b|l\s*/\s*h\b)', lookup_text):
        return None
    kind = evidence.get('kind')
    if kind == 'availability_summary':
        payloads = [{**evidence, 'metric': evidence.get('availability')}]
    elif (kind == 'governed_answer' and evidence.get('answer_status') == 'ANSWERABLE'
          and not evidence.get('requested_views') and not evidence.get('document_sources')
          and not evidence.get('unavailable_sections')):
        payloads = evidence.get('payloads') or []
        rows = evidence.get('rows') or []
        if len(rows) != len(payloads) or any(r.get('dimension') or r.get('entity') for r in rows):
            return None
    else:
        return None
    if not payloads or len(payloads) > 5:
        return None
    language = question_language(question, evidence.get('language') or 'en')
    english = language == 'en'
    sections = []
    for payload in payloads:
        context = payload.get('context') or {}
        metric = payload.get('metric') or {}
        code = context.get('metric_code')
        if (code not in METRICS or context.get('breakdown') != 'overall'
                or not context.get('start_date') or not context.get('end_date')
                or metric.get('raw_value') is None or not metric.get('formatted_value')
                or metric.get('quality_status', 'valid') != 'valid'):
            return None
        filters = context.get('filters') or {}
        labels = {'minesite': 'MineSite' if english else 'Site',
                  'model': 'Model' if english else 'Modèle',
                  'equipment': 'Equipment' if english else 'Équipement',
                  'family': 'Family' if english else 'Famille'}
        scope = ' / '.join(f'{labels.get(k, k)}: {v}' for k, v in filters.items())
        scope = scope or ('Authorized scope' if english else 'Périmètre autorisé')
        label = {'availability': 'Physical availability' if english else 'Disponibilité physique',
                 'fuel': 'Fuel consumption (L/h)' if english else 'Consommation de carburant (L/h)'}.get(code, code.upper())
        lines = [f'**{label} : {metric["formatted_value"]}**', scope,
                 f'{period_label(context, language)} — {context["start_date"]} / {context["end_date"]}']
        equipment = (payload.get('summary') or {}).get('equipment_count')
        if equipment is not None:
            lines.append(f'{equipment} ' + ('equipment' if english else 'équipements'))
        quality = payload.get('data_quality') or {}
        freshness = []
        if quality.get('latest_available_date'):
            freshness.append(('Latest source date: ' if english else 'Dernière date source : ') + str(quality['latest_available_date']))
        if quality.get('last_refresh_at'):
            freshness.append(('Refreshed: ' if english else 'Actualisation : ') + str(quality['last_refresh_at']))
        if quality.get('is_stale'):
            freshness.append('Source marked stale.' if english else 'La source est signalée comme ancienne.')
        if quality.get('completeness') is None:
            freshness.append('Full coverage not confirmed.' if english else 'Couverture complète non confirmée.')
        if freshness:
            lines.append(' · '.join(freshness))
        for warning in payload.get('warnings') or []:
            if isinstance(warning, str):
                lines.append(warning)
            else:
                # Do not silently discard structured warnings.
                return None
        source = evidence.get('source_table') or 'Excellence Center governed semantic services'
        if evidence.get('source_measure'):
            source += ' · ' + evidence['source_measure']
        lines.append('Source : ' + source)
        sections.append('\n\n'.join(lines))
    return '\n\n'.join(sections)
