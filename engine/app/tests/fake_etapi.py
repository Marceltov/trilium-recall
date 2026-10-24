"""An in-memory Trilium ETAPI for the sync tests, served through httpx.MockTransport.

It understands exactly the search strings sync.py sends (see sync.CLASSIFY / SCOPE / SCOPE_SINCE),
which keeps the fake honest: a new query shape in sync.py fails here first.
"""

import itertools
import re
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field

import httpx

from sync import SCOPE

_ids = itertools.count(1)
SINCE = re.compile(r"^note\.utcDateModified >= '([^']+)' and \(" + re.escape(SCOPE) + r"\)$")


@dataclass
class FakeNote:
    note_id: str
    title: str
    type: str
    parents: list[str]
    content: str = ""
    attrs: list[tuple[str, str, str, bool]] = field(default_factory=list)  # (type, name, value, owned)
    archived: bool = False
    modified: str = "2026-10-24 10:00:00.000Z"
    blob: int = 0


class FakeEtapi:
    def __init__(self):
        self.notes: dict[str, FakeNote] = {}
        self.requests: list[tuple[str, str]] = []
        self.fail = False
        self.clock = 0

    def tick(self) -> str:
        """A modification time in Trilium's format, later than any earlier tick and than 'now'."""
        self.clock += 1
        stamp = datetime.now(UTC) + timedelta(milliseconds=self.clock)
        return stamp.strftime("%Y-%m-%d %H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"

    # -- building the world ----------------------------------------------------------------

    def add(self, title, parent="root", type="text", content="", labels=(), relations=(), note_id=None,
            inherited=()):
        nid = note_id or f"n{next(_ids)}"
        attrs = [("label", n, v, True) for n, v in labels] + [("relation", n, v, True) for n, v in relations]
        attrs += [("label", n, v, False) for n, v in inherited]
        self.notes[nid] = FakeNote(nid, title, type, [parent], content, attrs, blob=next(_ids))
        return nid

    def set_content(self, nid, content):
        n = self.notes[nid]
        n.content, n.blob, n.modified = content, next(_ids), self.tick()

    def add_label(self, nid, name, value, bump_modified=True):
        n = self.notes[nid]
        n.attrs = [a for a in n.attrs if a[1] != name] + [("label", name, value, True)]
        if bump_modified:
            n.modified = self.tick()

    def delete(self, nid):
        del self.notes[nid]

    def move(self, nid, under):
        self.notes[nid].parents = [under]

    # -- ETAPI -------------------------------------------------------------------------------

    def _ancestors(self, nid):
        seen, stack = set(), [nid]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.notes:
                continue
            seen.add(cur)
            stack.extend(self.notes[cur].parents)
        return seen

    def _json(self, n: FakeNote):
        return {"noteId": n.note_id, "title": n.title, "type": n.type, "blobId": f"b{n.blob}",
                "parentNoteIds": n.parents, "utcDateModified": n.modified,
                "attributes": [{"type": t, "name": name, "value": v,
                                "noteId": n.note_id if owned else "TEMPLATE"} for t, name, v, owned in n.attrs]}

    def _search(self, query, ancestor):
        notes = [n for n in self.notes.values() if not n.archived and not n.note_id.startswith("_")]
        if ancestor:
            notes = [n for n in notes if ancestor in self._ancestors(n.note_id)]
        if query.startswith("#") and "=" not in query:
            name = query[1:]
            return [n for n in notes if any(a[1] == name for a in n.attrs)]
        in_scope = [n for n in notes if n.type in ("text", "code")]
        if query == SCOPE:
            return in_scope
        if m := SINCE.match(query):
            return [n for n in in_scope if n.modified >= m.group(1)]
        raise AssertionError(f"fake ETAPI does not understand query {query!r}")

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.fail:
            return httpx.Response(503, text="down")
        path = request.url.path.removeprefix("/etapi")
        if path == "/notes":
            q = request.url.params
            hits = self._search(q["search"], q.get("ancestorNoteId"))
            return httpx.Response(200, json={"results": [self._json(n) for n in hits]})
        if m := re.fullmatch(r"/notes/([^/]+)/content", path):
            n = self.notes.get(m.group(1))
            return httpx.Response(200, text=n.content) if n else httpx.Response(404)
        if path == "/app-info":
            return httpx.Response(200, json={"appVersion": "fake"})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@dataclass
class World:
    etapi: FakeEtapi
    wiki: str
    locks: str
    hub: str
    wiki_page: str
    summary: str
    source: str
    day_note: str
    lock_claim: str
    template: str
    other_note: str
    archived: str

    def __getattr__(self, name):  # world.fail, world.set_content(...) etc. go to the fake
        return getattr(self.etapi, name)

    def __setattr__(self, name, value):
        if name == "fail":
            self.etapi.fail = value
        else:
            super().__setattr__(name, value)


def build_world() -> World:
    e = FakeEtapi()
    root = e.add("LLM Wiki", note_id="llmroot")
    wiki = e.add("Wiki", root, labels=[("llmWikiPart", "wiki")])
    sources = e.add("Sources", root, labels=[("llmWikiPart", "sources")])
    locks = e.add("Locks", root, labels=[("llmWikiPart", "locks")])
    templates = e.add("Templates", root, labels=[("llmWikiPart", "templates")])
    e.add("Views", root, labels=[("llmWikiPart", "views")])
    e.add("Schema", root, content="<p>the rules</p>", labels=[("llmWikiSchema", ""), ("llmWikiPart", "schema")])
    template = e.add("Wiki Concept", templates, content="<p>template body</p>")
    hub = e.add("Homelab", wiki, content="<p>Hub for the homelab</p>",
                labels=[("wikiTopic", "homelab")], inherited=[("wiki", ""), ("wikiType", "hub")])
    page = e.add("Proxmox LXC memory", hub,
                 content="<h2>Swap</h2><p>CT 115 has 2 GB and no swap; the OOM killer picks Trilium first.</p>",
                 labels=[("wikiTopic", "homelab"), ("wikiStatus", "draft")],
                 relations=[("internalLink", hub), ("relatesTo", hub)],
                 inherited=[("wiki", ""), ("wikiType", "concept")])
    year = e.add("2026", sources, type="book", labels=[("wikiSourceGroup", "2026")])
    source = e.add("Original Article", year, content="<p>raw article text about lxc memory</p>")
    summary = e.add("Summary: Original Article", hub, content="<p>summary of the article</p>",
                    labels=[("wikiTopic", "homelab")], relations=[("wikiSource", source)],
                    inherited=[("wiki", ""), ("wikiType", "summary")])
    cal = e.add("Journal", "root", type="book", labels=[("calendarRoot", "")])
    day = e.add("24 - Saturday", cal, content="<h2>Wiki</h2><ul><li>ingest: Original Article</li></ul>")
    claim = e.add("session: ingest", locks, content="<p>claude code</p>")
    other = e.add("Shopping list", "root", content="<p>milk</p>")
    archived = e.add("Old stuff", "root", content="<p>archived words</p>")
    e.notes[archived].archived = True
    e.add("Hidden thing", "root", note_id="_hidden_x", content="<p>hidden</p>")
    e.add("A drawing", "root", type="canvas")
    return World(e, wiki, locks, hub, page, summary, source, day, claim, template, other, archived)
