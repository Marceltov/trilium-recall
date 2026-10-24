import pytest

from embed import HashEmbedder
from index import Index, NoteRecord
from rank import RankParams, context_terms, rank
from text import html_to_sections

P = RankParams(min_cos=0.2)


def put(idx, emb, note_id, title, html, area="wiki", wiki_type="concept", topics=("homelab",)):
    rec = NoteRecord(note_id, title, area, wiki_type if area == "wiki" else None, list(topics), "draft", [],
                     "2026-10-24 10:00:00.000Z", "c", "a")
    sections = html_to_sections(html)
    idx.upsert_note(rec, sections, emb.embed_passages([f"{title}: {s.text}" for s in sections]))


@pytest.fixture
def world_idx(tmp_path):
    emb = HashEmbedder()
    idx = Index(tmp_path / "i.db", emb.name, emb.dim)
    put(idx, emb, "hub", "Homelab", "<p>Hub page listing homelab pages</p>", wiki_type="hub")
    put(idx, emb, "prox", "Proxmox LXC memory", "<h2>Swap</h2><p>proxmox swap limit on CT 115 is zero</p>")
    put(idx, emb, "src1", "Forum post", "<p>proxmox swap limit on CT 115 is zero</p>", area="source")
    put(idx, emb, "art", "Original Article", "<p>exact quote from the article about ballooning</p>", area="source")
    put(idx, emb, "sum", "Summary: Original Article", "<p>the article about memory ballooning explained</p>",
        wiki_type="summary")
    put(idx, emb, "raw", "Unread Clip", "<p>kubernetes ingress annotations explained</p>", area="source")
    put(idx, emb, "detail", "Router manual", "<p>run ip link set vmbr0 mtu 9000 for jumbo frames</p>", area="source")
    put(idx, emb, "detsum", "Summary: Router manual", "<p>overview of the router capabilities</p>",
        wiki_type="summary")
    put(idx, emb, "net", "Network", "<p>bridge vmbr0 carries vlan 20</p>")
    put(idx, emb, "bk1", "Backup schedule", "<p>backup schedule nightly at 3</p>", topics=("trilium",))
    put(idx, emb, "bk2", "Backup schedule", "<p>backup schedule nightly at 3</p>", topics=("homelab",))
    idx.set_links("prox", [("internalLink", "hub"), ("internalLink", "net"), ("relatesTo", "bk2"),
                           ("internalLink", "missing")])
    idx.set_links("sum", [("wikiSource", "art"), ("internalLink", "hub")])
    idx.set_links("detsum", [("wikiSource", "detail")])
    return idx, emb


def test_wiki_beats_source_on_equal_text(world_idx):
    hits = rank("marcel", *world_idx, "proxmox swap limit", params=P)
    assert hits[0].note_id == "prox" and hits[0].area == "wiki"


def test_summary_stands_in_for_source(world_idx):
    hits = rank("marcel", *world_idx, "article about memory ballooning", params=P)
    assert hits[0].note_id == "sum" and hits[0].via_source == "Original Article"
    assert "art" not in [h.note_id for h in hits]


def test_source_keeps_detail_and_links_its_summary(world_idx):
    hits = rank("marcel", *world_idx, "ip link set mtu 9000", params=P)
    assert hits[0].note_id == "detail" and hits[0].links[0][0] == "detsum"


def test_unsummarised_source_shows_directly(world_idx):
    hits = rank("marcel", *world_idx, "kubernetes ingress annotations", params=P)
    assert hits[0].note_id == "raw" and hits[0].via_source is None


def test_nothing_relevant_returns_empty(world_idx):
    assert rank("marcel", *world_idx, "sourdough hydration", params=P) == []


def test_identifier_rescue(world_idx):
    strict = RankParams(min_cos=0.99, bm25_rescue_min_terms=2)
    assert [h.note_id for h in rank("marcel", *world_idx, "vmbr0 vlan tag", params=strict)][:1] == ["net"]
    assert rank("marcel", *world_idx, "vlan tag", params=strict) == []


def test_context_boost_breaks_tie(world_idx):
    a = rank("marcel", *world_idx, "backup schedule", cwd="/root/trilium/trilium-marcel", params=P)
    assert a[0].note_id == "bk1"
    b = rank("marcel", *world_idx, "backup schedule", cwd="/root/homelab-infra", params=P)
    assert b[0].note_id == "bk2"


def test_at_most_three_hits_and_links(world_idx):
    hits = rank("marcel", *world_idx, "homelab proxmox backup schedule vmbr0 article", params=P)
    assert len(hits) <= 3 and all(len(h.links) <= 3 for h in hits)
    assert len({h.note_id for h in hits}) == len(hits)


def test_links_skip_unknown_and_other_hits(world_idx):
    hit = rank("marcel", *world_idx, "proxmox swap limit", params=P, limit=1)[0]
    ids = [l[0] for l in hit.links]
    assert "missing" not in ids and "prox" not in ids
    assert ids[0] in ("net", "hub", "bk2")
    assert ("hub", "Homelab", "hub") in hit.links


def test_passage_is_short_and_around_match(world_idx):
    hit = rank("marcel", *world_idx, "proxmox swap limit", params=P)[0]
    assert hit.heading_path == ("Swap",) and "swap limit" in hit.passage and len(hit.passage) <= 250


def test_long_passage_cut_around_match(tmp_path):
    emb = HashEmbedder()
    idx = Index(tmp_path / "i.db", emb.name, emb.dim)
    put(idx, emb, "long", "Long", "<p>" + "filler " * 200 + "needle zebra here " + "filler " * 200 + "</p>")
    hit = rank("marcel", idx, emb, "needle zebra", params=RankParams(min_cos=0.2, bm25_rescue_min_terms=2))[0]
    assert "needle zebra" in hit.passage and hit.passage.startswith("…") and hit.passage.endswith("…")
    assert len(hit.passage) <= 250


def test_huge_and_hostile_query(world_idx):
    rank("marcel", *world_idx, 'Traceback "x" * NEAR( -y\n' * 2000, params=P)


def test_limit(world_idx):
    assert len(rank("marcel", *world_idx, "homelab proxmox backup", params=P, limit=1)) == 1


def test_context_terms():
    assert context_terms("/root/trilium/trilium-marcel") == ["trilium", "marcel"]
    assert context_terms("/home/me/src/app") == ["me"]
    assert context_terms(None) == [] and context_terms("/") == []


def test_links_prefer_wiki_over_journal(world_idx):
    idx, emb = world_idx
    put(idx, emb, "day", "16 - Friday", "<p>log: edited proxmox swap limit page</p>", area="journal")
    idx.set_links("day", [("internalLink", "prox")])
    hit = rank("marcel", idx, emb, "proxmox swap limit", params=P, limit=1)[0]
    # prox has three wiki neighbours (hub, net, bk2); a day note only fills a free slot.
    assert "day" not in [l[0] for l in hit.links] and len(hit.links) == 3
