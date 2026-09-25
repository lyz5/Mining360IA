"""Read-only, page-cited source retrieval. Source text is never a validated knowledge item."""
from __future__ import annotations

import hashlib
from contextlib import closing
import re
import sqlite3
import unicodedata
from pathlib import Path
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from .access_control import has_module_access, is_platform_admin
from .resource_library import RESOURCE_ROOT, encode_resource_id

STOP = set("""a an and are as at be by can could do does for from how i in is it me my of on or please that the their these this to use what when which why with would you your
au aux avec ce ces comment dans de des du elle en est et faire il je la le les leur lui ma me mes mon ne nos notre nous on ou par pas peux peut pour pourquoi que quel quelle quelles quels qui sa se ses son sur ta te tes toi ton tous tout tu un une vos votre vous
document documents documentation manual manuals practice practices best bonnes pratiques caterpillar cat according using explique expliquer donne""".split())
ALIASES = {
    "apres": ("after",), "stocker": ("storage",), "vilebrequins": ("crankshaft",),
    "entretien": ("maintenance",), "preventive": ("preventive", "pm"), "preventif": ("preventive", "pm"),
    "preventifs": ("preventive", "pm"), "prevention": ("preventive",), "panne": ("failure", "breakdown"),
    "pannes": ("failures", "breakdown"), "fiabilite": ("reliability",), "disponibilite": ("availability",),
    "arrets": ("shutdowns", "downtime"), "arret": ("shutdown", "downtime"), "huile": ("oil",),
    "huiles": ("oil",), "filtre": ("filter",), "filtres": ("filters",), "moteur": ("engine",),
    "frein": ("brake",), "freins": ("brakes", "brake"), "vilebrequin": ("crankshaft",),
    "arbres": ("shafts",), "cames": ("camshaft",), "stockage": ("storage",), "rangement": ("storage",),
    "refroidissement": ("cooling",), "surchauffe": ("overheating", "cooling"),
    "carburant": ("fuel",), "gasoil": ("fuel",), "gazole": ("fuel",), "consommation": ("consumption",),
    "routes": ("roads",), "pistes": ("roads",), "roulage": ("haul",), "pression": ("pressure",),
    "usure": ("wear",), "reparation": ("repair",), "reparations": ("repairs", "repair"),
    "planification": ("planning",), "ordonnancement": ("scheduling",),
    "securite": ("safety",), "echantillon": ("sample",), "echantillonnage": ("sampling",),
    "proprete": ("cleanliness",), "graissage": ("lubrication",), "lubrification": ("lubrication",),
    "comment": (), "ameliore": ("improve",), "ameliorer": ("improve",),
    "intervalle": ("interval",), "intervalles": ("intervals",), "objectif": ("target",),
    "objectifs": ("targets", "goals"), "indicateurs": ("metrics", "kpi"),
    "mtbf": ("mtbf", "reliability"), "mttr": ("mttr",), "mtbs": ("mtbs",),
}
DOCUMENT_INTENT = re.compile(
    r"\b(?:documents?|documentation|ressources?|resources?|procedures?|manuels?|manuals?|"
    r"best practices?|bonnes pratiques|maintenance|entretien|inspection|depannage|"
    r"crankshaft|camshaft|vilebrequin|contamination|lubrification|graissage|"
    r"troubleshoot\w*|preventive|preventif|haul roads?|backlog management)\b"
)
TECHNICAL_INTENT = re.compile(
    r"\b(?:how|why|comment|pourquoi|expliqu\w*|recommend\w*|recommand\w*|"
    r"causes?|diagnos\w*|reduire|reduce|improv\w*|amelior\w*|difference|definition)\b"
)
TECHNICAL_SUBJECT = re.compile(
    r"\b(?:mtbf|mttr|mtbs|availability|disponibilite|fuel|carburant|huile|oil|"
    r"freins?|brakes?|engine|moteur|cooling|refroidissement|surchauffe|"
    r"pannes?|failure\w*|pistes?|roads?|storage|stockage|wear|usure|reliability|fiabilite)\b"
)

def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).casefold())
                   if not unicodedata.combining(c))

def is_document_question(question):
    text = normalize(question)
    return bool(re.search(r"^\s*what (?:is|are) (?:the )?(?:mtbf|mtbs|mttr|physical availability)\s*[?.]?$", text) or DOCUMENT_INTENT.search(text) or
                (TECHNICAL_INTENT.search(text) and TECHNICAL_SUBJECT.search(text)))

def memory_path():
    return Path(getattr(settings, "RESOURCE_DOCUMENT_MEMORY_PATH",
                        settings.BASE_DIR / "var/resource-memory/corpus.sqlite3"))

def _authorize(user):
    if not getattr(user, "is_authenticated", False) or not (
            is_platform_admin(user) or has_module_access(user, "ai")):
        raise PermissionDenied("Resource knowledge access is required.")

def _groups(query):
    tokens = list(dict.fromkeys(re.findall(r"[a-z0-9]+", normalize(query))))[:48]
    return [tuple(dict.fromkeys((t, *ALIASES.get(t, ()))))
            for t in tokens if t not in STOP and len(t) > 1][:18]

def _source_path(relative):
    root = Path(RESOURCE_ROOT).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".pdf":
        raise ValueError("Invalid source path")
    return path

def search_document_memory(query, *, user, limit=4, character_budget=38000):
    _authorize(user)
    groups = _groups(query)
    if not groups:
        return {"results": [], "status": "no_match"}
    path = memory_path()
    if not path.is_file():
        return {"results": [], "status": "unavailable"}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            expression = " OR ".join('"' + t + '"' for g in groups for t in g)
            candidates = db.execute("""
                SELECT s.document_id,s.page,s.body,s.title,bm25(source_search,5.0,1.0,0.0,0.0) rank
                FROM source_search s WHERE source_search MATCH ? ORDER BY rank LIMIT 100
            """, (expression,)).fetchall()
            ranked = []
            for row in candidates:
                title = set(re.findall(r"[a-z0-9]+", normalize(row["title"])))
                body = set(re.findall(r"[a-z0-9]+", normalize(row["body"])))
                matched = sum(bool(set(g) & (title | body)) for g in groups)
                if matched < min(2, len(groups)):
                    continue
                exact_title = normalize(row["title"]).strip() in normalize(query)
                score = (3.0 if exact_title else 0.0) + matched / len(groups) + sum(bool(set(g) & title) for g in groups) / len(groups)
                ranked.append((score, -row["rank"], row))
            ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
            selected = {}
            for _, _, row in ranked:
                doc_id = row["document_id"]
                if doc_id not in selected and len(selected) >= max(1, min(limit, 6)):
                    continue
                selected.setdefault(doc_id, [])
                if len(selected[doc_id]) < 3:
                    selected[doc_id].append(row["page"])
            results = []
            stale = 0
            used = 0
            seen_hashes = set()
            for doc_id, matches in selected.items():
                doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
                if doc["sha256"] in seen_hashes:
                    continue
                try:
                    source = _source_path(doc["path"])
                    if hashlib.sha256(source.read_bytes()).hexdigest() != doc["sha256"]:
                        stale += 1
                        continue
                except (OSError, ValueError):
                    stale += 1
                    continue
                seen_hashes.add(doc["sha256"])
                # Include whole short documents; on long references include neighboring pages.
                page_numbers = (list(range(1, doc["pages"] + 1)) if doc["pages"] <= 12 else
                                sorted({p for m in matches for p in (m-1,m,m+1) if 1 <= p <= doc["pages"]}))
                pages = []
                # Matching pages get first claim on the bounded context; no silent mid-page clipping.
                ordered = list(dict.fromkeys(matches + page_numbers))
                for number in ordered:
                    row = db.execute("""
                        SELECT p.page,p.text,a.method,a.note
                        FROM pages p LEFT JOIN page_annotations a
                        ON a.document_id=p.document_id AND a.page=p.page
                        WHERE p.document_id=? AND p.page=?
                    """, (doc_id, number)).fetchone()
                    if not row or used + len(row["text"]) > character_budget:
                        continue
                    used += len(row["text"])
                    pages.append({"page": number, "text": row["text"],
                                  "extraction": row["method"] or "PDF text",
                                  "limitation": row["note"] or "Figures and table geometry need original-page verification."})
                if not pages:
                    continue
                pages.sort(key=lambda p: p["page"])
                rid = encode_resource_id(Path(doc["path"]))
                url = reverse("resource-file", args=[rid])
                for page in pages:
                    page["url"] = url + "#page=" + str(page["page"])
                review = db.execute("SELECT * FROM reading_reviews WHERE document_id=?", (doc_id,)).fetchone()
                results.append({
                    "source_id": "S" + str(len(results)+1),
                    "title": Path(doc["path"]).stem, "resource_id": rid,
                    "sha256": doc["sha256"], "total_pages": doc["pages"],
                    "pages": pages, "matched_pages": matches,
                    "complete_document_in_context": len(pages) == doc["pages"],
                    "source_kind": "Original resource document; not a validated knowledge item",
                    "review_status": review["status"] if review else "Not yet fully reviewed",
                    "url": reverse("resource-detail", args=[rid]),
                })
            return {"results": results, "status": "ok" if results else ("stale" if stale else "no_match"),
                    "stale_documents_excluded": stale,
                    "limitations": "Extracted pages may omit figure details or misalign tables. Do not infer missing values."}
    except (sqlite3.Error, OSError):
        return {"results": [], "status": "unavailable"}
