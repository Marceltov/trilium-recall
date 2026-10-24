"""One SQLite file per Trilium instance: notes, sections, FTS5, sqlite-vec vectors and links.

Fully rebuildable from Trilium, so deleting the file is always safe.
"""

import json
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sqlite_vec

from text import Section

CHUNKER_VERSION = 1
SCHEMA_VERSION = 1
MAX_QUERY_TERMS = 64
# Function words in English and German: they match everywhere and say nothing about the topic.
STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does doing for from had has have how i if in into is it
its me my no not of on or our please should so than that the their them then there these they this to
us was we were what when where which who why will with would you your yes ok okay let lets just also
make get got about like any some
der die das den dem des ein eine einen einem einer eines und oder aber ist sind war waren bin bist hat
haben hatte ich du er sie es wir ihr mich mir dich dir uns euch sich mein meine dein wie was wo wann warum
wer welche welcher welches nicht kein keine mit von zu zum zur auf an am im in aus bei nach vor fur uber
unter um als auch noch schon nur so dass da dann denn doch ja nein mal bitte kann konnen soll sollte muss
mache machen wird werden wurde
""".split())


@dataclass
class NoteRecord:
    note_id: str
    title: str
    area: str  # "wiki" | "source" | "journal" | "other"
    wiki_type: str | None
    topics: list[str]
    status: str | None
    path: list[str]
    utc_modified: str
    content_hash: str
    attr_hash: str


@dataclass
class SectionHit:
    section_id: int
    note_id: str
    heading_path: tuple[str, ...]
    text: str
    score: float  # bm25 (lower is better) for FTS hits, cosine similarity for vector hits
    matched_terms: int = 0  # distinct query terms found in the section (FTS hits only)


def fold(s: str) -> str:
    """Lower-case and strip diacritics, the way the FTS tokenizer (remove_diacritics 2) does."""
    decomposed = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def terms(s: str) -> list[str]:
    return re.findall(r"\w+", fold(s))


def query_terms(s: str) -> list[str]:
    """Distinct content words of a query, in order."""
    return list(dict.fromkeys(t for t in terms(s) if t not in STOPWORDS))


class Index:
    def __init__(self, path: Path, embedder_name: str, dim: int):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._meta = {"embedder": embedder_name, "dim": str(dim),
                      "chunker": str(CHUNKER_VERSION), "schema": str(SCHEMA_VERSION)}
        self._dim = dim
        self.lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        if not self._stored_meta():
            self._create()

    # -- schema ------------------------------------------------------------------------------

    def _stored_meta(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT key, value FROM meta").fetchall())

    def _create(self) -> None:
        with self.lock:
            db = self._db
            db.execute("BEGIN")
            for table in ("notes", "sections", "links", "sections_fts", "sections_vocab", "sections_vec"):
                db.execute(f"DROP TABLE IF EXISTS {table}")
            db.execute("""CREATE TABLE notes (note_id TEXT PRIMARY KEY, title TEXT, area TEXT, wiki_type TEXT,
                          topics TEXT, status TEXT, path TEXT, utc_modified TEXT, content_hash TEXT, attr_hash TEXT)""")
            db.execute("""CREATE TABLE sections (id INTEGER PRIMARY KEY, note_id TEXT, ordinal INTEGER,
                          heading_path TEXT, text TEXT)""")
            db.execute("CREATE INDEX sections_note ON sections(note_id)")
            db.execute("CREATE TABLE links (src TEXT, rel TEXT, dst TEXT)")
            db.execute("CREATE INDEX links_src ON links(src)")
            db.execute("CREATE INDEX links_dst ON links(dst)")
            # '_' joins identifiers like wiki_type; '-' and '.' stay separators so "swap." matches "swap".
            db.execute("""CREATE VIRTUAL TABLE sections_fts USING fts5(title, heading, text,
                          tokenize="unicode61 remove_diacritics 2 tokenchars '_'")""")
            db.execute("CREATE VIRTUAL TABLE sections_vocab USING fts5vocab(sections_fts, row)")
            db.execute(f"""CREATE VIRTUAL TABLE sections_vec USING vec0(
                           embedding float[{self._dim}] distance_metric=cosine)""")
            db.execute("DELETE FROM meta")
            db.executemany("INSERT INTO meta VALUES (?, ?)", self._meta.items())
            db.execute("COMMIT")

    def needs_rebuild(self) -> bool:
        return self._stored_meta() != self._meta

    def reset(self) -> None:
        self._create()

    # -- writes ------------------------------------------------------------------------------

    def _delete_sections(self, note_id: str) -> None:
        ids = [r[0] for r in self._db.execute("SELECT id FROM sections WHERE note_id = ?", (note_id,))]
        for sid in ids:
            self._db.execute("DELETE FROM sections_fts WHERE rowid = ?", (sid,))
            self._db.execute("DELETE FROM sections_vec WHERE rowid = ?", (sid,))
        self._db.execute("DELETE FROM sections WHERE note_id = ?", (note_id,))

    def _write_note(self, rec: NoteRecord) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rec.note_id, rec.title, rec.area, rec.wiki_type, json.dumps(rec.topics), rec.status,
             json.dumps(rec.path), rec.utc_modified, rec.content_hash, rec.attr_hash))

    def upsert_note(self, rec: NoteRecord, sections: list[Section], vectors: np.ndarray) -> None:
        assert len(sections) == len(vectors)
        with self.lock:
            self._db.execute("BEGIN")
            try:
                self._delete_sections(rec.note_id)
                self._write_note(rec)
                for section, vector in zip(sections, vectors):
                    heading = " › ".join(section.heading_path)
                    cur = self._db.execute(
                        "INSERT INTO sections (note_id, ordinal, heading_path, text) VALUES (?, ?, ?, ?)",
                        (rec.note_id, section.ordinal, json.dumps(section.heading_path), section.text))
                    sid = cur.lastrowid
                    self._db.execute("INSERT INTO sections_fts (rowid, title, heading, text) VALUES (?, ?, ?, ?)",
                                     (sid, rec.title, heading, section.text))
                    self._db.execute("INSERT INTO sections_vec (rowid, embedding) VALUES (?, ?)",
                                     (sid, sqlite_vec.serialize_float32(np.asarray(vector, dtype=np.float32))))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def update_meta(self, rec: NoteRecord) -> None:
        with self.lock:
            self._write_note(rec)
            # The title is indexed with every section.
            self._db.execute("UPDATE sections_fts SET title = ? WHERE rowid IN "
                             "(SELECT id FROM sections WHERE note_id = ?)", (rec.title, rec.note_id))

    def set_links(self, note_id: str, edges: list[tuple[str, str]]) -> None:
        with self.lock:
            self._db.execute("BEGIN")
            self._db.execute("DELETE FROM links WHERE src = ?", (note_id,))
            self._db.executemany("INSERT INTO links VALUES (?, ?, ?)", [(note_id, rel, dst) for rel, dst in edges])
            self._db.execute("COMMIT")

    def delete_note(self, note_id: str) -> None:
        with self.lock:
            self._db.execute("BEGIN")
            self._delete_sections(note_id)
            self._db.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
            self._db.execute("DELETE FROM links WHERE src = ?", (note_id,))
            self._db.execute("COMMIT")

    # -- reads -------------------------------------------------------------------------------

    def note(self, note_id: str) -> NoteRecord | None:
        with self.lock:
            row = self._db.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        return NoteRecord(row[0], row[1], row[2], row[3], json.loads(row[4]), row[5], json.loads(row[6]),
                          row[7], row[8], row[9])

    def all_notes(self) -> dict[str, tuple[str, str]]:
        with self.lock:
            return {r[0]: (r[1], r[2]) for r in
                    self._db.execute("SELECT note_id, content_hash, attr_hash FROM notes")}

    def counts(self) -> tuple[int, int]:
        with self.lock:
            return (self._db.execute("SELECT count(*) FROM notes").fetchone()[0],
                    self._db.execute("SELECT count(*) FROM sections").fetchone()[0])

    def _query_terms(self, query: str) -> list[str]:
        unique = query_terms(query)
        if len(unique) <= MAX_QUERY_TERMS:
            return unique
        placeholders = ",".join("?" * len(unique))
        df = dict(self._db.execute(f"SELECT term, doc FROM sections_vocab WHERE term IN ({placeholders})", unique))
        known = [t for t in unique if t in df]
        return sorted(known, key=lambda t: df[t])[:MAX_QUERY_TERMS]

    def fts_search(self, query: str, k: int = 50) -> list[SectionHit]:
        with self.lock:
            query_terms = self._query_terms(query)
            if not query_terms:
                return []
            match = " OR ".join(f'"{t}"' for t in query_terms)
            rows = self._db.execute(
                """SELECT s.id, s.note_id, s.heading_path, s.text, bm25(sections_fts, 5.0, 2.0, 1.0) AS rank,
                          f.title, f.heading
                   FROM sections_fts f JOIN sections s ON s.id = f.rowid
                   WHERE sections_fts MATCH ? ORDER BY rank LIMIT ?""", (match, k)).fetchall()
        hits = []
        for sid, note_id, heading_path, text, rank, title, heading in rows:
            present = set(terms(f"{title} {heading} {text}"))
            hits.append(SectionHit(sid, note_id, tuple(json.loads(heading_path)), text, rank,
                                   sum(t in present for t in query_terms)))
        return hits

    def vec_search(self, vector: np.ndarray, k: int = 50) -> list[SectionHit]:
        with self.lock:
            rows = self._db.execute(
                """SELECT s.id, s.note_id, s.heading_path, s.text, v.distance
                   FROM (SELECT rowid, distance FROM sections_vec WHERE embedding MATCH ? AND k = ?) v
                   JOIN sections s ON s.id = v.rowid ORDER BY v.distance""",
                (sqlite_vec.serialize_float32(np.asarray(vector, dtype=np.float32)), k)).fetchall()
        return [SectionHit(sid, note_id, tuple(json.loads(hp)), text, 1.0 - dist)
                for sid, note_id, hp, text, dist in rows]

    def note_sections(self, note_id: str) -> list[SectionHit]:
        """All sections of a note in order, as hits with score 0."""
        with self.lock:
            rows = self._db.execute("SELECT id, heading_path, text FROM sections WHERE note_id = ? ORDER BY ordinal",
                                    (note_id,)).fetchall()
        return [SectionHit(sid, note_id, tuple(json.loads(hp)), text, 0.0) for sid, hp, text in rows]

    def section_vectors(self, section_ids: list[int]) -> dict[int, np.ndarray]:
        if not section_ids:
            return {}
        with self.lock:
            placeholders = ",".join("?" * len(section_ids))
            rows = self._db.execute(f"SELECT rowid, embedding FROM sections_vec WHERE rowid IN ({placeholders})",
                                    section_ids).fetchall()
        return {sid: np.frombuffer(blob, dtype=np.float32) for sid, blob in rows}

    def neighbours(self, note_id: str) -> list[tuple[str, str]]:
        with self.lock:
            rows = self._db.execute(
                "SELECT rel, dst FROM links WHERE src = ? UNION SELECT rel, src FROM links WHERE dst = ?",
                (note_id, note_id)).fetchall()
        return [(rel, other) for rel, other in rows if other != note_id]

    def sources_summarised_by(self, source_id: str) -> list[str]:
        with self.lock:
            return [r[0] for r in self._db.execute(
                "SELECT src FROM links WHERE rel = 'wikiSource' AND dst = ? ORDER BY src", (source_id,))]
