"""Trilium note HTML → plain-text sections split at h2/h3 headings."""

import hashlib
import math
import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser as HTMLParser, LexborNode as Node

SECTION_TAGS = {"h2", "h3"}
LIST_TAGS = {"ul", "ol"}
# Containers whose children are blocks in their own right.
CONTAINER_TAGS = {"body", "div", "section", "article", "figure", "blockquote", "main", "details"}
SKIP_TAGS = {"script", "style", "img", "svg", "head"}


@dataclass(frozen=True)
class Section:
    heading_path: tuple[str, ...]
    text: str
    ordinal: int


def approx_tokens(s: str) -> int:
    return math.ceil(len(s.split()) * 1.3)


def content_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _inline(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(deep=True, separator="")).strip()


def _list_lines(node: Node, depth: int = 0) -> list[str]:
    lines = []
    for li in node.iter():
        if li.tag != "li":
            continue
        own, nested = [], []
        for child in li.iter(include_text=True):
            if child.tag in LIST_TAGS:
                nested.extend(_list_lines(child, depth + 1))
            elif child.tag == "-text":
                own.append(child.text_content or "")
            else:
                own.append(child.text(deep=True, separator=""))
        text = re.sub(r"\s+", " ", "".join(own)).strip()
        if text:
            lines.append("  " * depth + "- " + text)
        lines.extend(nested)
    return lines


def _table_lines(node: Node) -> list[str]:
    lines = []
    for tr in node.css("tr"):
        cells = [_inline(c) for c in tr.iter() if c.tag in ("td", "th")]
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


def _is_mermaid(pre: Node) -> bool:
    return any("language-mermaid" in (c.attributes.get("class") or "") for c in pre.css("code"))


def _blocks(node: Node):
    """Yield ("heading", level, text) and ("text", None, text) in document order."""
    pending_inline: list[str] = []

    def flush():
        text = re.sub(r"\s+", " ", "".join(pending_inline)).strip()
        pending_inline.clear()
        return text

    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text" or tag in ("span", "a", "strong", "em", "b", "i", "code", "u", "s", "sub", "sup", "mark", "br"):
            pending_inline.append(child.text_content if tag == "-text" else child.text(deep=True, separator=""))
            continue
        if (text := flush()):
            yield ("text", None, text)
        if tag in SKIP_TAGS:
            continue
        if tag in SECTION_TAGS:
            yield ("heading", int(tag[1]), _inline(child))
        elif tag in LIST_TAGS:
            if (lines := _list_lines(child)):
                yield ("text", None, "\n".join(lines))
        elif tag == "table":
            if (lines := _table_lines(child)):
                yield ("text", None, "\n".join(lines))
        elif tag == "pre":
            if not _is_mermaid(child):
                raw = child.text(deep=True, separator="").strip("\n")
                if raw.strip():
                    yield ("text", None, raw)
        elif tag in CONTAINER_TAGS:
            yield from _blocks(child)
        else:
            if (text := _inline(child)):
                yield ("text", None, text)
    if (text := flush()):
        yield ("text", None, text)


def _split_words(text: str, max_tokens: int) -> list[str]:
    words = text.split()
    per = max(1, int(max_tokens / 1.3))
    return [" ".join(words[i:i + per]) for i in range(0, len(words), per)]


def _chunk(paragraphs: list[str], max_tokens: int) -> list[str]:
    chunks, current = [], []
    for para in paragraphs:
        pieces = [para] if approx_tokens(para) <= max_tokens else _split_words(para, max_tokens)
        for piece in pieces:
            if current and approx_tokens("\n".join(current + [piece])) > max_tokens:
                chunks.append("\n".join(current))
                current = []
            current.append(piece)
    if current:
        chunks.append("\n".join(current))
    return chunks


def html_to_sections(html: str, max_tokens: int = 350, plain: bool = False) -> list[Section]:
    if not html or not html.strip():
        return []
    if plain:
        groups = [((), [p for p in html.strip().split("\n\n") if p.strip()])]
    else:
        body = HTMLParser(html).body
        if body is None:
            return []
        groups: list[tuple[tuple[str, ...], list[str]]] = [((), [])]
        h2 = None
        for kind, level, text in _blocks(body):
            if kind == "heading":
                if level == 2:
                    h2 = text
                    path = (text,)
                else:
                    path = (h2, text) if h2 else (text,)
                groups.append((path, []))
            else:
                groups[-1][1].append(text)
    sections = []
    for path, paragraphs in groups:
        for chunk in _chunk(paragraphs, max_tokens):
            sections.append(Section(path, chunk, len(sections)))
    return sections
