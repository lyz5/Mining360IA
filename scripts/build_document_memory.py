"""Create a verified, durable source memory; never generates knowledge claims."""
import argparse
from contextlib import closing
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def build(source, target, library):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError("Memory already exists; preserve it and use a new output path for a rebuild.")
    tmp = target.with_suffix(".building.sqlite3")
    if tmp.exists():
        raise RuntimeError("An unfinished build exists; inspect before retrying.")
    with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro", uri=True)) as src:
        docs = src.execute("SELECT id,path,sha256,pages FROM documents ORDER BY id").fetchall()
        actual = {p.relative_to(library).as_posix() for p in library.rglob("*.pdf")
                  if not any(x.startswith("_pdf_text_index") for x in p.relative_to(library).parts)}
        if actual != {d[1] for d in docs}:
            raise RuntimeError("Source inventory changed; re-extract new or removed documents first.")
        for ident, relative, digest, count in docs:
            path = (library / relative).resolve()
            if not path.is_relative_to(library.resolve()):
                raise RuntimeError("Unsafe source path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError("Source hash changed; re-extraction required.")
            pages = src.execute("SELECT page FROM pages WHERE document_id=? ORDER BY page",(ident,)).fetchall()
            if [p[0] for p in pages] != list(range(1,count+1)):
                raise RuntimeError("Page coverage mismatch")
        with closing(sqlite3.connect(tmp)) as dst:
            src.backup(dst)
    with closing(sqlite3.connect(tmp)) as db:
        db.executescript("""
            CREATE VIRTUAL TABLE source_search USING fts5(
              title,body,document_id UNINDEXED,page UNINDEXED,tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE reading_reviews (
              document_id INTEGER PRIMARY KEY, status TEXT NOT NULL,
              reviewed_pages TEXT NOT NULL, visual_pages TEXT NOT NULL,
              synthesis_json TEXT NOT NULL, source_sha256 TEXT NOT NULL, reviewed_at TEXT NOT NULL);
        """)
        db.executemany("INSERT INTO source_search VALUES(?,?,?,?)",
            [(Path(path).stem, re.sub(r"\s+", " ", text), ident, page)
             for ident,path,page,text in db.execute(
                 "SELECT d.id,d.path,p.page,p.text FROM documents d JOIN pages p ON p.document_id=d.id")])
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Integrity check failed")
        page_count = db.execute("SELECT count(*) FROM pages").fetchone()[0]
        chars = db.execute("SELECT sum(length(text)) FROM pages").fetchone()[0]
        assert db.execute("SELECT count(*) FROM source_search").fetchone()[0] == page_count
    os.replace(tmp,target)
    manifest = {"built_at":datetime.now(timezone.utc).isoformat(),"documents":len(docs),
        "unique_pdf_hashes":len({d[2] for d in docs}),"pages":page_count,"characters":chars,
        "source_hashes_verified":len(docs),"integrity":"ok",
        "memory_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
        "meaning":"Full source archive, not a claim of complete semantic or visual review."}
    target.with_suffix(".manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest

if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,default=ROOT/".runlogs/resource-reading-memory/resources.sqlite3")
    p.add_argument("--target",type=Path,default=ROOT/"var/resource-memory/corpus.sqlite3")
    p.add_argument("--library",type=Path,default=ROOT/"res/bp")
    a=p.parse_args()
    print(json.dumps(build(a.source,a.target,a.library),indent=2))
