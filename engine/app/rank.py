"""Hybrid ranking: FTS5 + vectors fused, weighted by area, gated by an absolute relevance test."""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import numpy as np

from embed import Embedder
from index import Index, NoteRecord, SectionHit, fold, query_terms

EMBED_QUERY_CHARS = 2000
PASSAGE_CHARS = 240
GENERIC_PATH_PARTS = {"root", "home", "src", "app", "repo", "repos", "code", "projects", "workspace", "users",
                      "tmp", "git", "dev", "work"}


@dataclass
class RankParams:
    area_weight: dict[str, float] = field(
        default_factory=lambda: {"wiki": 1.0, "source": 0.8, "journal": 0.6, "other": 0.6})
    rrf_k: int = 60
    cos_weight: float = 1.0
    rrf_weight: float = 20.0
    context_boost: float = 0.05
    # e5 similarities sit in a narrow band: live matches 0.85–0.92, unrelated text ~0.80.
    min_cos: float = 0.83
    bm25_rescue_min_terms: int = 2
    top_n: int = 3
    max_links: int = 3
    candidates: int = 50
    # A summary stands in for its source when its own best similarity is at most this much lower.
    summary_slack: float = 0.05


@dataclass
class Hit:
    instance: str
    note_id: str
    title: str
    wiki_type: str | None
    topics: list[str]
    status: str | None
    area: str
    heading_path: tuple[str, ...]
    passage: str
    score: float
    links: list[tuple[str, str, str | None]]  # (note_id, title, wiki_type)
    via_source: str | None


@dataclass
class _Candidate:
    section: SectionHit
    cos: float = 0.0
    rrf: float = 0.0
    matched_terms: int = 0


def context_terms(cwd: str | None) -> list[str]:
    """Words from the last two meaningful folder names of the working directory.

    The engine cannot see the client's filesystem, so this works on the path string only.
    """
    if not cwd:
        return []
    parts = [p for p in reversed(PurePosixPath(cwd).parts) if p not in ("/", "") and p.lower() not in GENERIC_PATH_PARTS]
    out: list[str] = []
    for part in parts[:2]:
        for word in re.split(r"[-_.\s]+", part.lower()):
            if word and word not in GENERIC_PATH_PARTS and word not in out:
                out.append(word)
    return out


def _passage(text: str, words: list[str]) -> str:
    if len(text) <= PASSAGE_CHARS:
        return text
    folded = fold(text)
    starts = [m.start() for t in words if (m := re.search(rf"\b{re.escape(t)}\b", folded))]
    anchor = min(starts) if starts else 0
    start = max(0, anchor - PASSAGE_CHARS // 3)
    end = min(len(text), start + PASSAGE_CHARS)
    start = max(0, end - PASSAGE_CHARS)
    # Snap to word boundaries.
    if start > 0:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < anchor else start
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start else end
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _gather(index: Index, embedder: Embedder, query: str, params: RankParams) -> tuple[dict[int, _Candidate], np.ndarray]:
    qvec = embedder.embed_queries([query[:EMBED_QUERY_CHARS]])[0]
    candidates: dict[int, _Candidate] = {}
    for rank_, hit in enumerate(index.fts_search(query, params.candidates)):
        c = candidates.setdefault(hit.section_id, _Candidate(hit))
        c.rrf += 1 / (params.rrf_k + rank_ + 1)
        c.matched_terms = hit.matched_terms
    for rank_, hit in enumerate(index.vec_search(qvec, params.candidates)):
        c = candidates.setdefault(hit.section_id, _Candidate(hit))
        c.rrf += 1 / (params.rrf_k + rank_ + 1)
    vectors = index.section_vectors(list(candidates))
    for sid, c in candidates.items():
        if sid in vectors:
            c.cos = float(vectors[sid] @ qvec)
    return candidates, qvec


def _note_best(index: Index, note_id: str, qvec: np.ndarray) -> tuple[SectionHit | None, float]:
    sections = index.note_sections(note_id)
    vectors = index.section_vectors([s.section_id for s in sections])
    best, best_cos = None, -1.0
    for s in sections:
        if s.section_id in vectors and (cos := float(vectors[s.section_id] @ qvec)) > best_cos:
            best, best_cos = s, cos
    return best, best_cos


def rank(instance: str, index: Index, embedder: Embedder, query: str, cwd: str | None = None,
         params: RankParams = RankParams(), limit: int = 3) -> list[Hit]:
    words = query_terms(query)
    candidates, qvec = _gather(index, embedder, query, params)
    if not candidates:
        return []
    ctx = context_terms(cwd)
    notes: dict[str, NoteRecord] = {}

    def note(nid: str) -> NoteRecord | None:
        if nid not in notes:
            notes[nid] = index.note(nid)
        return notes[nid]

    # Best section per note, scored.
    best: dict[str, tuple[float, _Candidate]] = {}
    for c in candidates.values():
        rec = note(c.section.note_id)
        if rec is None:
            continue
        score = params.area_weight.get(rec.area, 0.6) * (params.cos_weight * c.cos + params.rrf_weight * c.rrf)
        haystack = fold(" ".join([rec.title, *rec.topics]))
        if ctx and any(t in haystack for t in ctx):
            score += params.context_boost
        if rec.note_id not in best or score > best[rec.note_id][0]:
            best[rec.note_id] = (score, c)

    def passes(c: _Candidate) -> bool:
        return c.cos >= params.min_cos or c.matched_terms >= params.bm25_rescue_min_terms

    hits: list[Hit] = []
    used: set[str] = set()
    summary_first: dict[str, str] = {}  # hit note_id → summary to list first in its links
    for nid, (score, c) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        if len(hits) >= min(limit, params.top_n):
            break
        if nid in used or not passes(c):
            continue
        rec = note(nid)
        shown, section, via_source = rec, c.section, None
        if rec.area == "source":
            summaries = [s for s in index.sources_summarised_by(nid) if note(s)]
            scored = [(s, *_note_best(index, s, qvec)) for s in summaries]
            scored = [x for x in scored if x[1] is not None]
            if scored:
                sid, sec, cos = max(scored, key=lambda x: x[2])
                if cos >= c.cos - params.summary_slack and sid not in used:
                    shown, section, via_source = note(sid), sec, rec.title
                else:
                    summary_first[nid] = sid  # the source holds the detail; point at its summary
        if shown.wiki_type == "summary" and via_source is None:
            for rel, source_id in index.neighbours(shown.note_id):
                if rel == "wikiSource" and (src := note(source_id)) and src.area == "source":
                    via_source = src.title
                    used.add(source_id)  # the summary stands for it; don't show it again
                    break
        if shown.note_id in used:
            continue
        used.update({shown.note_id, nid})
        hits.append(Hit(instance, shown.note_id, shown.title, shown.wiki_type, shown.topics, shown.status,
                        shown.area, section.heading_path, _passage(section.text, words), score, [],
                        via_source))

    # Links: neighbours that were candidates first, then hubs, then the rest by id.
    candidate_notes = {c.section.note_id for c in candidates.values()}
    shown_ids = {h.note_id for h in hits} | used
    for hit in hits:
        neighbour_ids = {other for _, other in index.neighbours(hit.note_id)}
        first = summary_first.get(hit.note_id)
        ordered = sorted(neighbour_ids - shown_ids - {first},
                         key=lambda o: (o not in candidate_notes,
                                        (note(o).wiki_type if note(o) else None) != "hub", o))
        if first:
            ordered.insert(0, first)
        for other in ordered:
            rec = note(other)
            if rec is not None and len(hit.links) < params.max_links:
                hit.links.append((rec.note_id, rec.title, rec.wiki_type))
    return hits
