"""Read the local Resources archive without modifying the application database."""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--search', help='SQLite FTS5 query, e.g. "backlog" AND "planning"')
parser.add_argument('--document', type=int)
parser.add_argument('--page', type=int)
parser.add_argument('--catalogue', action='store_true')
parser.add_argument('--offset', type=int, default=0)
parser.add_argument('--limit', type=int, default=30)
parser.add_argument('--coverage', action='store_true')
parser.add_argument('--reviews', action='store_true', help='Show explicitly authored review notes')
parser.add_argument('--progress', action='store_true')
args = parser.parse_args()
memory = root / 'var/resource-memory/corpus.sqlite3'
if not memory.exists():
    memory = root / '.runlogs/resource-reading-memory/resources.sqlite3'
db = sqlite3.connect(memory.as_uri() + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
if args.progress:
    count = db.execute('SELECT count(*) FROM reading_reviews').fetchone()[0]
    total = db.execute('SELECT count(*) FROM documents').fetchone()[0]
    print(json.dumps({'documents':total,'document_reviews':count,'not_fully_reviewed':total-count}))
elif args.reviews:
    for row in db.execute('SELECT r.*,d.path FROM reading_reviews r JOIN documents d ON d.id=r.document_id WHERE (? IS NULL OR r.document_id=?)',(args.document,args.document)):
        print(json.dumps(dict(row),ensure_ascii=False))
elif args.coverage:
    print(json.dumps({'largest':[dict(r) for r in db.execute('SELECT id,path,pages FROM documents ORDER BY pages DESC LIMIT 10')],
        'sparse':[dict(r) for r in db.execute("SELECT id,path,sparse_pages FROM documents WHERE sparse_pages != '[]'")]},ensure_ascii=False,indent=2))
elif args.document:
    d = db.execute('SELECT * FROM documents WHERE id=?', (args.document,)).fetchone()
    if not d: raise SystemExit('Unknown document')
    print(d['path'])
    for row in db.execute('SELECT page,text FROM pages WHERE document_id=? AND (? IS NULL OR page=?) ORDER BY page',(args.document,args.page,args.page)):
        print(f"\nPAGE {row['page']}\n{row['text']}")
elif args.search:
    for row in db.execute('''SELECT d.id,d.path,p.page,snippet(page_search,0,'[',']',' … ',48) AS excerpt
        FROM page_search p JOIN documents d ON d.id=p.document_id
        WHERE page_search MATCH ? ORDER BY rank LIMIT ?''',(args.search,args.limit)):
        print(json.dumps(dict(row),ensure_ascii=False))
elif args.catalogue:
    for d in db.execute('SELECT * FROM documents ORDER BY path LIMIT ? OFFSET ?', (args.limit,args.offset)):
        rows = db.execute('SELECT text FROM pages WHERE document_id=? ORDER BY page',(d['id'],)).fetchall()
        raw = re.sub(r'\s+', ' ', '\n'.join(r['text'] for r in rows)).strip()
        candidates = list(re.finditer(r'2\.0\s+Best Practice Description', raw, re.I))
        if candidates:
            raw = raw[candidates[-1].end():].strip()
        else:
            candidates = list(re.finditer(r'1\.0\s+Introduction',raw,re.I))
            if candidates: raw = raw[candidates[-1].end():].strip()
        print(f"{d['id']} | {Path(d['path']).stem} | {d['pages']}p | {raw[:250]}")
else:
    parser.error('Select --search, --document, --catalogue or --coverage')
