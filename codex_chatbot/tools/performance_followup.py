"""Reuse verified scope for KPI follow-ups, never previous metric values."""
import re
from .performance_request import normalized
from .metric_intent import requested_metrics


def needs_performance_context(question):
    text = normalized(question)
    metrics = requested_metrics(question)
    performance = metrics or re.search(r'\b(?:downtimes?|heures? d.arret)\b', text)
    reference = re.search(r'\b(?:cette periode|meme periode|ce site|meme site|ces machines|ces equipements|this period|same period|same site|these machines)\b', text)
    if performance and reference:
        return True
    metric_words = r'(?:mtbf|mtbs|mttr|lph|fuel|carburant|consommation|disponibilite|dispo|availability|l\s*/\s*h)'
    # A bare KPI or an explicit continuation refers to the last verified scope.
    # Full standalone questions and definitions retain their existing routing.
    return bool(metrics and (
        re.fullmatch(r'\s*(?:(?:le|la|les|the)\s+)?' + metric_words + r'\s*[?!.,]*\s*', text)
        or re.match(r'^\s*(?:et|and|what about)\s+(?:(?:le|la|les|the)\s+)?' + metric_words + r'\b', text)
    ))


def context_from_evidence(evidence):
    if evidence.get('kind') == 'availability_summary':
        contexts = [evidence.get('context')]
    elif evidence.get('kind') == 'governed_answer':
        contexts = [p.get('context') for p in evidence.get('payloads') or []]
    else:
        return None
    scopes = []
    for context in contexts:
        if not context or context.get('metric_code') not in {'availability', 'mtbf', 'mtbs', 'mttr', 'fuel'}:
            return None
        if not context.get('period_code'):
            return None
        scope = {'period_code': context['period_code'], 'filters': {
            k: v for k, v in (context.get('filters') or {}).items()
            if k in {'minesite', 'model', 'family', 'equipment', 'serial_number', 'customer'}
        }}
        if scope not in scopes:
            scopes.append(scope)
    return scopes[0] if len(scopes) == 1 else None


def prior_performance_context(run):
    from ..models import CodexRun
    # Do not cross conversations, owners, or a more recent unrelated request.
    previous = CodexRun.objects.filter(
        conversation_id=run.conversation_id, user_id=run.user_id,
        conversation__owner_id=run.user_id, created_at__lt=run.created_at,
    ).order_by('-created_at').first()
    if previous is None:
        return None
    evidence = previous.evidence.order_by('retrieved_at').first()
    return context_from_evidence(evidence.value_json) if evidence else None
