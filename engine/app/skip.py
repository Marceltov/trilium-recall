"""Which prompts the hook should not search for: slash commands, confirmations, bare follow-ups."""

import re

from index import STOPWORDS, terms

CONFIRMATIONS = frozenset({
    "ok", "okay", "yes", "yep", "y", "no", "nope", "n", "ja", "nein", "go", "go on", "continue", "weiter",
    "mach", "mach weiter", "do it", "yes do it", "sure", "thanks", "danke", "good", "gut", "passt", "lgtm",
    "ship it", "approve", "approved", "stop", "done", "fertig", "klar", "alles klar", "perfekt", "perfect",
    "great", "nice", "cool",
})
# Words that only point back at the conversation ("and the other one?", "das andere auch").
FOLLOW_UP_WORDS = frozenset({
    "other", "one", "ones", "again", "too", "more", "next", "same", "thing", "else", "now", "here", "that",
    "this", "those", "andere", "anderen", "nochmal", "auch", "weiter", "dieses", "jetzt", "hier",
})
SHORT_WORDS = 5


def should_skip(prompt: str) -> str | None:
    text = prompt.strip()
    if not text:
        return "empty"
    if text.startswith("/"):
        return "slash"
    bare = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()
    if bare in CONFIRMATIONS:
        return "confirmation"
    words = terms(text)
    # A miss costs more than a stray hit: skip a short prompt only when it has no content word at all.
    if len(words) < SHORT_WORDS and all(w in STOPWORDS or w in FOLLOW_UP_WORDS for w in words):
        return "short"
    return None
