"""Keeps one instance's Index in step with Trilium: full build, incremental poll, periodic reconcile."""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from embed import Embedder
from index import Index, NoteRecord
from text import html_to_sections
from trilium import EtapiClient

log = logging.getLogger(__name__)

SCOPE = "note.type = text or note.type = code"
# Trilium 0.106 returns nothing for a query that starts with "(", so the date clause goes first.
SCOPE_SINCE = "note.utcDateModified >= '{since}' and (" + SCOPE + ")"
# #llmWikiPart value → area of everything below it; None = excluded (plumbing, not knowledge).
CLASSIFY = {
    "wiki": "wiki",
    "sources": "source",
    "locks": None,
    "templates": None,
    "views": None,
    "schema": "wiki",  # the rulebook holds standing preferences worth recalling
}
POLL_MARGIN = timedelta(seconds=120)
LINK_RELATIONS = ("internalLink", "relatesTo", "wikiSource")


@dataclass
class SyncStatus:
    last_ok: datetime | None = None
    last_error: str | None = None
    notes: int = 0
    sections: int = 0


def _owned(note: dict, name: str) -> list[dict]:
    return [a for a in note["attributes"] if a["name"] == name and a["noteId"] == note["noteId"]]


def _labels(note: dict, name: str) -> list[str]:
    """Values of a label, owned or inherited from a template, empty values dropped, order kept."""
    values = [a["value"] for a in note["attributes"] if a["type"] == "label" and a["name"] == name and a["value"]]
    return list(dict.fromkeys(values))


def _attr_hash(note: dict, area: str) -> str:
    attrs = sorted((a["type"], a["name"], a["value"]) for a in note["attributes"])
    payload = json.dumps([attrs, note["title"], sorted(note["parentNoteIds"]), area])
    return hashlib.sha256(payload.encode()).hexdigest()


class Syncer:
    def __init__(self, name: str, client: EtapiClient, index: Index, embedder: Embedder):
        self.name = name
        self.client = client
        self.index = index
        self.embedder = embedder
        self.status = SyncStatus()
        self._cursor: datetime | None = None
        self._area_roots: set[str] = set()

    # -- scanning ----------------------------------------------------------------------------

    def _roots(self) -> tuple[dict[str, str | None], str | None]:
        """Area roots: noteId → area (None = excluded), plus the journal root."""
        roots: dict[str, str | None] = {}
        for note in self.client.search("#llmWikiPart"):
            for attr in _owned(note, "llmWikiPart"):
                if attr["value"] in CLASSIFY:
                    roots[note["noteId"]] = CLASSIFY[attr["value"]]
        calendars = [n for n in self.client.search("#calendarRoot") if _owned(n, "calendarRoot")]
        journal = calendars[0]["noteId"] if calendars else None
        self._area_roots = set(roots) | ({journal} if journal else set())
        return roots, journal

    def _scan(self, query: str) -> tuple[dict[str, tuple[dict, str]], set[str]]:
        """Notes matching the query: in-scope noteId → (note, area), and the excluded noteIds."""
        roots, journal = self._roots()
        notes = {n["noteId"]: n for n in self.client.search(query)}
        area: dict[str, str | None] = {}
        # Excluded wins over everything, then wiki > source > journal; the rest is "other".
        ordered = [r for r, a in roots.items() if a is None] + \
                  [r for r, a in roots.items() if a == "wiki"] + \
                  [r for r, a in roots.items() if a == "source"] + ([journal] if journal else [])
        for root in ordered:
            label = roots.get(root, "journal")
            for note in self.client.search(query, ancestor=root):
                if note["noteId"] in notes:
                    area.setdefault(note["noteId"], label)
        in_scope, excluded = {}, set()
        for nid, note in notes.items():
            a = area.get(nid, "other")
            if a is None:
                excluded.add(nid)
            else:
                in_scope[nid] = (note, a)
        return in_scope, excluded

    def _path(self, note: dict, titles: dict[str, str]) -> list[str]:
        path, parents, seen = [], note["parentNoteIds"], set()
        # Ancestor titles below the area root (Wiki, Sources, Journal), nearest last.
        while (parents and parents[0] in titles and parents[0] not in seen
               and parents[0] not in self._area_roots and len(path) < 4):
            seen.add(parents[0])
            path.insert(0, titles[parents[0]][0])
            parents = titles[parents[0]][1]
        return path

    def _record(self, note: dict, area: str, titles: dict) -> NoteRecord:
        status = _labels(note, "wikiStatus")
        wiki_type = _labels(note, "wikiType")
        return NoteRecord(
            note_id=note["noteId"], title=note["title"], area=area,
            wiki_type=wiki_type[0] if wiki_type else None, topics=_labels(note, "wikiTopic"),
            status=status[0] if status else None, path=self._path(note, titles),
            utc_modified=note["utcDateModified"], content_hash=note["blobId"],
            attr_hash=_attr_hash(note, area))

    # -- applying ----------------------------------------------------------------------------

    def _apply(self, in_scope: dict[str, tuple[dict, str]], titles: dict) -> int:
        known = self.index.all_notes()
        changed = 0
        for nid, (note, area) in in_scope.items():
            rec = self._record(note, area, titles)
            old = known.get(nid)
            if old is None or old[0] != rec.content_hash:
                self._embed_note(rec, note)
            elif old[1] != rec.attr_hash:
                self.index.update_meta(rec)
            else:
                continue
            self.index.set_links(nid, [(a["name"], a["value"]) for a in note["attributes"]
                                       if a["type"] == "relation" and a["name"] in LINK_RELATIONS
                                       and a["noteId"] == nid])
            changed += 1
        return changed

    def _embed_note(self, rec: NoteRecord, note: dict) -> None:
        content = self.client.content(rec.note_id)
        sections = html_to_sections(content, plain=note["type"] == "code")
        passages = [f"{rec.title} › {' › '.join(s.heading_path)}: {s.text}" if s.heading_path
                    else f"{rec.title}: {s.text}" for s in sections]
        self.index.upsert_note(rec, sections, self.embedder.embed_passages(passages))

    @staticmethod
    def _titles(in_scope: dict[str, tuple[dict, str]]) -> dict[str, tuple[str, list[str]]]:
        return {nid: (note["title"], note["parentNoteIds"]) for nid, (note, _) in in_scope.items()}

    def _guarded(self, work) -> int:
        started = datetime.now(UTC)
        try:
            changed = work()
        except (httpx.HTTPError, ValueError, KeyError) as e:
            self.status.last_error = f"{type(e).__name__}: {e}"
            log.warning("sync %s failed: %s", self.name, self.status.last_error)
            return 0
        self._cursor = started
        self.status.last_ok = started
        self.status.last_error = None
        self.status.notes, self.status.sections = self.index.counts()
        return changed

    # -- public ------------------------------------------------------------------------------

    def full_build(self) -> None:
        def work():
            # Scan before reset: during an outage the old index keeps serving.
            in_scope, _ = self._scan(SCOPE)
            self.index.reset()
            return self._apply(in_scope, self._titles(in_scope))
        self._guarded(work)

    def reconcile(self) -> int:
        def work():
            in_scope, _ = self._scan(SCOPE)
            changed = 0
            for nid in set(self.index.all_notes()) - set(in_scope):
                self.index.delete_note(nid)
                changed += 1
            # Parents outside the scan (books, the root) simply end the path.
            return changed + self._apply(in_scope, self._titles(in_scope))
        return self._guarded(work)

    def poll(self) -> int:
        if self._cursor is None:
            return self.reconcile()

        def work():
            since = (self._cursor - POLL_MARGIN).strftime("%Y-%m-%d %H:%M:%S")
            in_scope, excluded = self._scan(SCOPE_SINCE.format(since=since))
            changed = 0
            for nid in excluded & set(self.index.all_notes()):
                self.index.delete_note(nid)
                changed += 1
            titles = {nid: (title, []) for nid, title in self.index.titles().items()}
            titles.update(self._titles(in_scope))
            return changed + self._apply(in_scope, titles)
        return self._guarded(work)
