"""Presentation language only; never changes business scope or evidence values."""
import re
import unicodedata


def question_language(question, fallback='en'):
    text = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold())
                   if not unicodedata.combining(c))
    # Grammatical words outweigh metric names, which are often English in French requests.
    fr = len(re.findall(r'\b(?:donne|montre|affiche|quel|quelle|quels|quelles|combien|pourquoi|comment|et|le|la|les|des|du|pour|depuis|sur|cette|moi)\b', text))
    en = len(re.findall(r'\b(?:give|show|what|which|how|why|and|the|for|since|this|please|with)\b', text))
    if fr != en:
        return 'fr' if fr > en else 'en'
    if re.search(r'\b(?:disponibilite|consommation|carburant|bonjour|merci|annee)\b', text):
        return 'fr'
    if re.search(r'\b(?:availability|fuel|hello|thanks|reporting|connected)\b', text):
        return 'en'
    return fallback


def run_language(run):
    language = question_language(run.question, None)
    if language:
        return language
    # Only this owner's conversation, only earlier user questions.
    previous = run.conversation.runs.filter(
        user_id=run.user_id, created_at__lt=run.created_at,
    ).order_by('-created_at').values_list('question', flat=True)[:20]
    for question in previous:
        language = question_language(question, None)
        if language:
            return language
    return 'en'


def period_label(context, language):
    label = context.get('period_label') or ''
    code = context.get('period_code') or ''
    if code == 'ytd' or 'ytd' in label.casefold():
        return 'YTD — completed months' if language == 'en' else 'YTD — mois terminés'
    if code == 'last_12_months':
        return 'Last 12 months' if language == 'en' else '12 derniers mois'
    # Exact dates follow this label; avoid leaking a source-language month label.
    return 'Selected period' if language == 'en' else 'Période sélectionnée'


def governed_notice(text, language):
    """Translate known application notices, leaving source content untouched."""
    pairs = {
        'Précisez le site, le modèle et la période : aucun périmètre de performance unique n’est disponible dans la demande précédente.': 'Specify the site, model and period: no unique performance scope is available from the previous request.',
        'Vous n’avez pas accès aux données de performance.': 'You do not have access to performance data.',
        'Vous n’avez pas accès aux connaissances métier.': 'You do not have access to business knowledge.',
        'Plusieurs sites correspondent. Précisez le MineSite.': 'Several sites match. Specify the MineSite.',
        'Précisez un seul périmètre pour chaque filtre.': 'Specify a single scope for each filter.',
        'Périmètre non autorisé.': 'Unauthorized scope.',
        'La source de performance est temporairement indisponible.': 'The performance source is temporarily unavailable.',
        'Quelle mesure Excellence Center souhaitez-vous : disponibilité, MTBF, MTTR, MTBS ou consommation (L/h) ?': 'Which Excellence Center metric do you mean: Availability, MTBF, MTTR, MTBS or Fuel (L/h)?',
        'Aucune donnée disponible pour le périmètre demandé.': 'No data is available for the requested scope.',
        'La source centrale n’a pas renvoyé la période demandée.': 'The central snapshot did not return the requested date range.',
        'La source centrale ne prend pas encore en charge ce regroupement.': 'The central snapshot service does not yet support this grouping.',
    }
    mapping = pairs if language == 'en' else {en: fr for fr, en in pairs.items()}
    return mapping.get(text, text)


def governed_rows_answer(evidence):
    """Render verified scalar/ranking evidence without translating source identifiers."""
    english = evidence.get('language') == 'en'
    if evidence.get('fixed_top_downtime_count') == 10:
        sections = []
        for payload in evidence.get('payloads') or []:
            context = payload['context']
            systems = payload['downtime_systems']
            entries = systems['rows'][:10]
            scope = ' / '.join(str(v) for v in (context.get('filters') or {}).values())
            lines = [f"Top {len(entries)} {'downtime drivers' if english else 'catégories d’arrêt'} — {scope}",
                     f"{context.get('start_date', '')} / {context.get('end_date', '')}",
                     '| System / category | Downtime hours | Share of total |' if english else '| Système / catégorie | Heures d’arrêt | Part du total |',
                     '|---|---:|---:|']
            for item in entries:
                name = item['system'].replace('|', '/').replace('\n', ' ')
                lines.append(f"| {name} | {item['hours_formatted']} | {item['share_formatted']} |")
            if systems['total_hours'] is not None:
                lines.append(("Total downtime: " if english else "Total des heures d’arrêt : ") + f"{systems['total_hours']:.2f} h.")
            lines.append('Shares include all categories, not only this ranking.' if english else 'Les parts comprennent toutes les catégories, pas seulement ce classement.')
            if len(entries) < 10:
                lines.append(f"Only {len(entries)} categories are available." if english else f"Seulement {len(entries)} catégories disponibles.")
            sections.append('\n'.join(lines))
        sections.append('Source : DowntimeData_MiningProd. ' + (
            'Configured categories and official downtime hours measure; categories are not a root-cause diagnosis.' if english else
            'Catégories configurées et mesure officielle des heures d’arrêt ; les catégories ne constituent pas un diagnostic de causes racines.'))
        if evidence.get('unavailable_sections'):
            sections.append(('Unavailable: ' if english else 'Indisponible : ') + ', '.join(evidence['unavailable_sections']))
        return '\n\n'.join(sections)
    return governed_notice(evidence['text'], 'en' if english else 'fr')
