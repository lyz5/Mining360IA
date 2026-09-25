"""Explicit metric mentions shared by routing and inventory fallback guards."""
import re
import unicodedata


def requested_metrics(question):
    text=''.join(c for c in unicodedata.normalize('NFKD',question.casefold()) if not unicodedata.combining(c))
    matches=[]
    patterns={
        'availability':r'\b(?:availability|disponibilite|dispo)\b',
        'mtbf':r'\bmtbf\b', 'mtbs':r'\bmtbs\b', 'mttr':r'\bmttr\b',
        'fuel':r"\b(?:fuel|carburant|gasoil|consommation|lph)\b|\bl\s*/\s*h\b|\blit(?:re|er)s?\s*(?:/|par|per|a\s+l[’'])\s*(?:h\b|heures?\b|hours?\b)|\bconsommation\s+horaire\b",
    }
    for metric,pattern in patterns.items():
        match=re.search(pattern,text)
        if match:matches.append((match.start(),metric))
    return [metric for _,metric in sorted(matches)]
