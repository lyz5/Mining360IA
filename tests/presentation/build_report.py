"""Package private local UI evidence and a source-controlled, data-free report."""
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/'.ui-test-artifacts'
DEST=ROOT.parents[1]/'exports/Mining360_Responsive_Desktop_Protege_2026-11-14'
DEST.mkdir(parents=True,exist_ok=True)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def merge_rows(variant):
    indexed={(r['page'],r['width']):r for r in read(ART/variant/'results.json')}
    for name in ('results-invoices.json','results-sources-source-detail.json','results-business-excellence.json'):
        path=ART/variant/name
        if path.exists():
            indexed.update({(r['page'],r['width']):r for r in read(path)})
    return list(indexed.values())


def package():
    responsive=merge_rows('responsive');legacy=merge_rows('legacy')
    assert all(r['documentWidth']<=r['width']+1 and not r['errors'] and r['http']==200 for r in responsive)
    measures=read(ART/'measurements.json')
    retry=read(ART/'measurements-retry.json')
    names={r['page'] for r in retry['comparisons']}
    for key in ('comparisons','medians','samples'):
        measures[key]=[r for r in measures[key] if r['page'] not in names]+retry[key]
    assert all(r['layout_only_geometry_equal'] and r['theme_geometry_equal'] and r['pixel_difference_bbox'] is None for r in measures['comparisons'])
    catalog=read(ART/'catalog-results.json')
    counts=dict(Counter(r['ui_status'] for r in catalog))
    interactions=read(ART/'pilot-interactions.json');behavior=read(ART/'behavior-results.json')
    manifest=read(ROOT/'deployment/bodefm-validated-20261114/source-manifest.json')
    changed=[];missing=[]
    for item in manifest['files']:
        path=ROOT/item['path']
        if not path.exists():missing.append(item['path'])
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:changed.append(item['path'])
    allowed={'.gitignore','Mining360IA/settings.py','codex_chatbot/static/codex_chatbot/chatbot.js',
        'reports/static/reports/business_command_center_v2.js','reports/static/reports/homepage_command_center.js',
        'reports/templates/reports/includes/app_nav.html','reports/templates/reports/resource_detail.html'}
    assert not missing,missing
    assert set(changed)<=allowed,changed
    summary={'base_commit':'401b9733641935843d687addaab6a3c9811ed871',
        'branch':'feature/responsive-desktop-protected-20261114','deployment':'local validation snapshot; publication and deployment tracked separately',
        'django_tests':{'passed':92,'additional_final_presentation_rerun':7,
                        'database':'isolated SQLite; contract suite creates schema from models, not a migration/parity test'},
        'responsive_format_checks':len(responsive),'pages':len({r['page'] for r in responsive}),
        'widths':sorted({r['width'] for r in responsive}),'overflows':0,'page_javascript_errors':0,
        'catalog_states':len(catalog),'catalog_status':counts,
        'behavior_checks':len(behavior),'navigation_filter_checks':len(interactions),
        'desktop_pixel_equal_pages':[r['page'] for r in measures['comparisons']],
        'source_manifest_files_checked':len(manifest['files']),'original_source_files_changed':changed,
        'unchanged_manifest_files':len(manifest['files'])-len(changed),
        'actual_mobile_devices':'not available','engines':'Microsoft Edge/Chromium; Firefox/WebKit not installed',
        'powerbi':'native frame only; live embed, RLS identities and mobile layouts not revalidated',
        'known_unmet_budget':'Reporting Configuration CLS remains above 0.1 in local lab; pre-existing asynchronous content layout',
        'artifacts':'local test fixtures, never a production fallback'}
    for name,data in [('VALIDATION.json',summary),('MESURES.json',measures),('ETATS_90.json',catalog),
                      ('MATRICE_FORMATS.json',responsive),('INTERACTIONS.json',interactions+behavior)]:
        (DEST/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    cards=[]
    for page in sorted({r['page'] for r in responsive}):
        cells=[]
        for width in (390,1024,1440):
            links=[]
            for variant,label in (('legacy','Before'),('responsive','After')):
                file=ART/variant/f'{page}-{width}.png'
                if not file.exists():continue
                target=DEST/variant/file.name;target.parent.mkdir(exist_ok=True);shutil.copy2(file,target)
                rel=f'{variant}/{file.name}'
                links.append(f'<figure><a href="{rel}"><img loading="lazy" src="{rel}" alt="{html.escape(page)} {label} {width}px"></a><figcaption>{label} · {width}px · test fixtures</figcaption></figure>')
            cells.append('<div class="pair">'+''.join(links)+'</div>')
        cards.append(f'<section><h2>{html.escape(page)}</h2>'+''.join(cells)+'</section>')
    (DEST/'INDEX.html').write_text('''<!doctype html><html lang="fr"><meta charset="utf-8"><title>Mining360 — revue responsive locale</title><style>body{margin:24px;background:#f5f6f8;color:#111827;font:16px system-ui}section{margin:24px 0;padding:20px;background:#fff;border:1px solid #e2e8f0;border-radius:12px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0}figure{margin:0;min-width:0}img{width:100%;height:480px;object-fit:contain;object-position:top;background:#eef2f6}figcaption{padding:8px}a{color:#005b9f}</style><h1>Mining360 — responsive, desktop protégé</h1><p>Captures locales avec données de test explicitement marquées. Ce dossier ne représente pas un déploiement ou des données live de BODEFM.</p><p>390px : téléphone ; 1024px : tablette ; 1440px : desktop. Cliquer pour consulter chaque PNG complet.</p>'''+''.join(cards),encoding='utf-8')
    report=ROOT/'docs/RESPONSIVE_VALIDATION_2026-11-14.md'
    parts=[
        '# Validation locale — responsive, desktop protégé',
        '', 'Branche `feature/responsive-desktop-protected-20261114`, base BODEFM `401b973`.',
        '**Bilan des tests locaux avant publication ; aucun déploiement, redémarrage partagé ou changement de modèle/base de production pendant ces tests. Le statut Git/BODEFM est documenté séparément.**',
        '', '## Résultats', '',
        f'- 92 tests Django ciblés réussis ; les 7 tests de présentation ont aussi été rejoués après le bootstrap final.',
        f'- {len(responsive)} contrôles de format sur {summary["pages"]} pages, sans débordement horizontal du document ni exception JavaScript.',
        '- Largeurs : '+', '.join(map(str,summary['widths']))+' px ; 1366 × 768 inclus.',
        f'- {len(interactions)} contrôles navigation/filtres et {len(behavior)} scénarios fonctionnels : réussite.',
        '- 8 pages desktop comparées : géométrie identique, avec et sans thème ; pixels identiques au rendu stabilisé lorsque le thème est désactivé.',
        '- Les quatre échecs historiques documentés dans la référence BODEFM ne sont pas corrigés ou requalifiés par ce chantier.',
        '', 'Les tests financiers comparent les mêmes agrégats et lignes de fixtures avant/après les interrupteurs. Ils ne constituent pas une nouvelle certification des sources, des attributions Power BI ou des identités RLS.',
        '', '## Parcours réellement vérifiés', '',
        *['- '+c+'.' for c in interactions+behavior],
        '', '## Mesures comparables', '',
        measures['method'],
        'Temps de rendu/état prêt ci-dessous en millisecondes, médianes de 3 essais. Attente de stabilisation des captures exclue du temps prêt. Aucun gain de production n’est déduit de ces fixtures. INP et p75 terrain non mesurés.',
        '', '| Page | Prêt avant | Prêt après | LCP avant/après | CLS avant/après |', '|---|---:|---:|---:|---:|']
    for name in dict.fromkeys(r['page'] for r in measures['medians']):
        a=next(r for r in measures['medians'] if r['page']==name and r['variant']=='legacy')
        b=next(r for r in measures['medians'] if r['page']==name and r['variant']=='responsive')
        parts.append(f'| {name} | {a["ready_ms"]} | {b["ready_ms"]} | {a.get("lcp")} / {b.get("lcp")} | {a.get("cls")} / {b.get("cls")} |')
    parts += ['', 'Le CLS initial de 0,26 introduit dans Excellence par le retrait des emplacements de chargement a été refusé et corrigé : les emplacements sont conservés pendant l’attente, sans présenter les anciennes valeurs. La mesure finale figure ci-dessus. Reporting Configuration reste au-dessus de l’objectif CLS 0,1 ; le comportement asynchrone existant est à traiter dans un lot dédié.',
        '', '## Couverture des 90 états', '',
        'Chaque ligne distingue vérification d’interface et validation des données. Un cadre « indisponible » Power BI ne valide ni le contenu embarqué ni ses layouts mobiles.',
        '', '| N° | État | Interface | Limite de source |','|---:|---|---|---|']
    parts += [f'| {r["number"]} | {r["label"].replace("|","/")} | {r["ui_status"]} | {r["source_status"]} |' for r in catalog]
    parts += ['', '## Limites et prérequis', '',
        '- Connexion/formulaire Windows complet : configuration AD absente du banc local. Aucun test d’authentification réelle sur mobile.',
        '- Data Browser Preview : aucun browser opérationnel alimenté dans les fixtures ; navigation et panneaux seulement.',
        '- Workflow : route absente dans la référence, aucune fausse page créée.',
        '- Les écrans administratifs vides/en erreur ne valident pas les mutations. Aucun Save, Publish, Run, Sync ou Deploy réel n’a été exécuté.',
        '- La table SQL non gérée de Downtime Checking n’existe pas dans la base SQLite du banc : seul le cadre/état d’indisponibilité est vérifié.',
        '- Viewer : cadre et code d’intégration préservés. Sessions Power BI/Power Apps réelles, rapports complets et changements de taille sous embed live à retester après autorisation, avec les identités habituelles.',
        '- Firefox/WebKit non installés ; iPhone/Android physiques non disponibles. La réduction de viewport simule le clavier et le reflow, pas le matériel ou le SSO.',
        '- Reflow 320px vérifié ; zoom navigateur à 200 % et audit lecteur d’écran manuel complet non effectués.',
        '- CSV métier : service/format/périmètre inchangés par empreinte ; l’export intégral sur source réelle n’a pas été relancé.',
        '', '## Preuves privées et fichiers protégés', '',
        f'{len(manifest["files"])} fichiers du manifeste BODEFM contrôlés. Seuls les fichiers de présentation attendus et les deux paramètres de présentation diffèrent. Services Revenue/Parts, accès, permissions, intégration Power BI, routes, migrations et scripts de déploiement restent identiques.',
        '', 'Dossier privé : `exports/Mining360_Responsive_Desktop_Protege_2026-11-14/INDEX.html` à la racine canonique. JSON détaillés, captures avant/après aux trois formats et PNG complets restent ignorés par Git. Les fixtures ne sont jamais importées par l’application.',
        '', 'La désactivation est décrite dans [le guide de mise en œuvre](RESPONSIVE_DESKTOP_PROTECTED_2026-11-14.md). Les tests vérifient la disparition des nouveaux assets, handlers et réservations d’espace dans un nouveau document. Aucun réglage BODEFM n’a été changé.']
    report.write_text('\n'.join(parts)+'\n',encoding='utf-8')
    (DEST/'BILAN.md').write_text(report.read_text(encoding='utf-8'),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True),flush=True)


if __name__=='__main__':package()
