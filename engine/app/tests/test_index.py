import numpy as np
import pytest

from embed import HashEmbedder
from index import Index, NoteRecord
from text import html_to_sections


@pytest.fixture
def emb():
    return HashEmbedder()


@pytest.fixture
def idx(tmp_path, emb):
    return Index(tmp_path / "i.db", emb.name, emb.dim)


def record(note_id, title, area="wiki", **kw):
    return NoteRecord(note_id=note_id, title=title, area=area, wiki_type=kw.get("wiki_type"),
                      topics=kw.get("topics", []), status=kw.get("status"), path=[],
                      utc_modified="2026-10-24 10:00:00.000Z", content_hash=kw.get("content_hash", "h"),
                      attr_hash=kw.get("attr_hash", "a"))


def add(idx, emb, note_id, title, html, **kw):
    sections = html_to_sections(html)
    vectors = emb.embed_passages([f"{title} › {' › '.join(s.heading_path)}: {s.text}" for s in sections])
    idx.upsert_note(record(note_id, title, **kw), sections, vectors)


def test_upsert_and_search(idx, emb):
    add(idx, emb, "n1", "Proxmox LXC", "<h2>Swap</h2><p>CT 115 has no swap</p>")
    add(idx, emb, "n2", "Pizza", "<p>dough</p>")
    hit = idx.fts_search("swap")[0]
    assert hit.note_id == "n1" and hit.heading_path == ("Swap",) and hit.matched_terms == 1
    assert idx.vec_search(emb.embed_queries(["swap ct 115"])[0])[0].note_id == "n1"


def test_matched_terms_counts_distinct_query_terms(idx, emb):
    add(idx, emb, "n1", "Net", "<p>bridge vmbr0 carries vlan 20</p>")
    assert idx.fts_search("vmbr0 vlan tag")[0].matched_terms == 2


def test_identifiers_findable(idx, emb):
    add(idx, emb, "n1", "Net", "<p>bridge vmbr0 and utcDateModified.</p>")
    assert idx.fts_search("vmbr0")[0].note_id == "n1"
    assert idx.fts_search("utcDateModified")[0].note_id == "n1"


def test_german_diacritics_folded(idx, emb):
    add(idx, emb, "n1", "Gewerbe", "<p>Die Gewerbeanmeldung beim Ordnungsamt in München</p>")
    assert idx.fts_search("munchen")[0].note_id == "n1"


def test_fts_syntax_never_raises(idx, emb):
    add(idx, emb, "n1", "X", "<p>x</p>")
    for q in ['"', "a*", "NEAR(", "col:val", "-x", "AND OR NOT", "x" * 20000, "", "   ", "😀"]:
        idx.fts_search(q)


def test_long_query_keeps_rarest_terms(idx, emb):
    add(idx, emb, "n1", "A", "<p>common zebra</p>")
    add(idx, emb, "n2", "B", "<p>common</p>")
    query = " ".join(["common"] * 10 + [f"filler{i}" for i in range(100)] + ["zebra"])
    assert idx.fts_search(query)[0].note_id == "n1"


def test_reupsert_replaces_sections(idx, emb):
    add(idx, emb, "n1", "T", "<p>alpha</p>")
    add(idx, emb, "n1", "T", "<p>beta</p>")
    assert idx.fts_search("alpha") == [] and idx.fts_search("beta")
    assert len(idx.vec_search(emb.embed_queries(["beta"])[0])) == 1


def test_delete_removes_everything(idx, emb):
    add(idx, emb, "n1", "T", "<p>alpha</p>")
    idx.set_links("n1", [("internalLink", "n2")])
    idx.delete_note("n1")
    assert idx.fts_search("alpha") == [] and idx.neighbours("n2") == [] and idx.note("n1") is None
    assert idx.vec_search(emb.embed_queries(["alpha"])[0]) == []


def test_links_both_directions(idx):
    idx.set_links("a", [("internalLink", "b"), ("wikiSource", "s")])
    assert ("internalLink", "a") in idx.neighbours("b")
    assert ("internalLink", "b") in idx.neighbours("a")
    assert idx.sources_summarised_by("s") == ["a"]
    idx.set_links("a", [])
    assert idx.neighbours("b") == []


def test_update_meta_and_all_notes(idx, emb):
    add(idx, emb, "n1", "T", "<p>alpha</p>", content_hash="c1", attr_hash="a1")
    rec = idx.note("n1")
    rec.status, rec.attr_hash = "reviewed", "a2"
    idx.update_meta(rec)
    assert idx.note("n1").status == "reviewed"
    assert idx.all_notes() == {"n1": ("c1", "a2")}


def test_section_vectors(idx, emb):
    add(idx, emb, "n1", "T", "<p>alpha</p>")
    hit = idx.fts_search("alpha")[0]
    vec = idx.section_vectors([hit.section_id])[hit.section_id]
    assert vec.shape == (emb.dim,) and np.isclose(np.linalg.norm(vec), 1)


def test_meta_mismatch_triggers_rebuild(tmp_path):
    assert not Index(tmp_path / "i.db", "hash-test", 384).needs_rebuild()
    other = Index(tmp_path / "i.db", "multilingual-e5-small-int8", 384)
    assert other.needs_rebuild()
    other.reset()
    assert not other.needs_rebuild() and other.all_notes() == {}


def test_counts(idx, emb):
    add(idx, emb, "n1", "T", "<h2>a</h2><p>x</p><h2>b</h2><p>y</p>")
    assert idx.counts() == (1, 2)
