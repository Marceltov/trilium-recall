"""The compact text Claude gets, for the hook and the MCP tool alike."""

from rank import Hit
from text import approx_tokens

HEADER = "Wiki recall{instance} — read full pages with the Trilium MCP (get note by ID):"
SHORT_PASSAGE = 120


def _hit_lines(n: int, hit: Hit, several: bool, with_links: bool, passage: str) -> list[str]:
    tags = [hit.wiki_type or hit.area]
    if hit.topics:
        tags.append(",".join(hit.topics))
    if hit.status:
        tags.append(hit.status)
    line = f"{n}. {hit.title} [{' · '.join(tags)}] id={hit.note_id}"
    if several:
        line += f" @{hit.instance}"
    lines = [line]
    passage = " ".join(passage.split())  # one line: list breaks and blank lines cost tokens
    heading = " › ".join(hit.heading_path)
    lines.append(f'   § {heading}: "{passage}"' if heading else f'   "{passage}"')
    if hit.via_source:
        lines.append(f"   (summary of source: {hit.via_source})")
    if with_links and hit.links:
        links = ", ".join(f"{title} ({kind}) id={nid}" if kind else f"{title} id={nid}"
                          for nid, title, kind in hit.links)
        lines.append(f"   links: {links}")
    return lines


def _shorten(passage: str) -> str:
    if len(passage) <= SHORT_PASSAGE:
        return passage
    cut = passage[:SHORT_PASSAGE].rsplit(" ", 1)[0]
    return cut.rstrip("…") + "…"


def render(hits: list[Hit], max_tokens: int = 400) -> str:
    return fit(hits, max_tokens)[0]


def fit(hits: list[Hit], max_tokens: int = 400) -> tuple[str, list[Hit]]:
    """The text and the hits it actually contains (the budget may drop hits from the end)."""
    if not hits:
        return "", []
    several = len({h.instance for h in hits}) > 1
    header = HEADER.format(instance="" if several else f" ({hits[0].instance})")
    # Degrade until it fits: drop links, then shorten passages, then drop hits from the end.
    for count in range(len(hits), 0, -1):
        for with_links, short in ((True, False), (False, False), (False, True)):
            lines = [header]
            for n, hit in enumerate(hits[:count], 1):
                lines += _hit_lines(n, hit, several, with_links, _shorten(hit.passage) if short else hit.passage)
            text = "\n".join(lines)
            if approx_tokens(text) <= max_tokens:
                return text, hits[:count]
    return text, hits[:1]
