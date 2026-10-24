import pytest

from rank import Hit
from render import render
from text import approx_tokens


def hit(note_id, title, **kw):
    base = dict(instance="marcel", note_id=note_id, title=title, wiki_type="concept", topics=["homelab"],
                status="draft", area="wiki", heading_path=("Swap",), passage="CT 115 has no swap",
                score=1.0, links=[], via_source=None)
    base.update(kw)
    return Hit(**base)


@pytest.fixture
def two_hits():
    return [hit("prox", "Proxmox LXC memory", links=[("hub", "Homelab", "hub"), ("net", "Network", None)]),
            hit("sum", "Summary: Original Article", wiki_type="summary", topics=["homelab", "trilium"], status=None,
                heading_path=(), passage="the article about ballooning", via_source="Original Article")]


EXPECTED_TWO_HITS = """Wiki recall (marcel) — read full pages with the Trilium MCP (get note by ID):
1. Proxmox LXC memory [concept · homelab · draft] id=prox
   § Swap: "CT 115 has no swap"
   links: Homelab (hub) id=hub, Network id=net
2. Summary: Original Article [summary · homelab,trilium] id=sum
   "the article about ballooning"
   (summary of source: Original Article)"""


def test_render_exact(two_hits):
    assert render(two_hits) == EXPECTED_TWO_HITS


def test_render_empty():
    assert render([]) == ""


def test_render_source_without_type_uses_area():
    out = render([hit("s", "Clip", wiki_type=None, area="source", topics=[], status=None, heading_path=("A", "B"))])
    assert "1. Clip [source] id=s\n   § A › B: " in out


def test_render_several_instances():
    out = render([hit("a", "A"), hit("b", "B", instance="bille")])
    assert out.startswith("Wiki recall — read full pages")
    assert "id=a @marcel\n" in out and out.splitlines()[-2].endswith("id=b @bille") or "id=b @bille" in out


def test_render_budget():
    long = "word " * 120
    hits = [hit(str(i), f"Title {i}", passage=long, links=[(f"l{j}", f"Link {j} " * 5, "concept") for j in range(3)])
            for i in range(3)]
    out = render(hits)
    assert approx_tokens(out) <= 400 and out.startswith("Wiki recall")
    assert "1. Title 0" in out


def test_render_flattens_passage_whitespace():
    out = render([hit("a", "A", passage="first line\n- item one\n\n- item two")])
    assert '"first line - item one - item two"' in out


def test_fit_reports_the_hits_it_shows():
    from render import fit
    long = "word " * 150
    hits = [hit(str(i), f"Title {i} " + "x " * 120, passage=long) for i in range(3)]
    text, shown = fit(hits)
    assert text == render(hits) and 0 < len(shown) < 3
    assert [h.note_id for h in shown] == [str(i) for i in range(len(shown))]
