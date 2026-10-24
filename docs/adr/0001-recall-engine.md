---
status: accepted
date: 2026-10-24
decision-makers: Marcel Bruckner
---

# Recall engine: a sidecar container in this repo, hooked into every prompt

## Context and Problem Statement

Claude is the main reader of the LLM wiki, but it only used the wiki when told to, and finding
something cost many ETAPI calls and tokens (a metadata-only `#wiki` search returned ~392K
characters). How does Claude find what the wiki knows on its own, fast and cheaply, without moving
the wiki out of Trilium Notes? Issue #4; design in the plugin's planning notes.

## Decision Drivers

* Automatic: no "check the wiki"; a miss costs more than a stray hit.
* Fast enough to run before every prompt (< 300 ms p95), and silent when nothing is relevant.
* German and English content; runs on a 2 GB homelab container, no GPU, no API dependency.
* Semantic search stays out of Trilium core (offline and bundle-size rules upstream).

## Considered Options

* Sidecar container (`recall-engine/` in this repo): SQLite FTS5 + sqlite-vec over sections,
  local multilingual-e5-small (int8 ONNX), a `UserPromptSubmit` hook and an MCP `recall` tool.
* Semantic search inside Trilium core or a Trilium script.
* Hosted embedding API instead of a local model.
* Search through the Trilium MCP only (no index), relying on the skill to search.

## Decision Outcome

Chosen option: the sidecar container, because it is the only one that is automatic (the hook),
fast (15–30 ms per query on the real wiki), works offline, and keeps Trilium untouched.

### Consequences

* Good, because measured on 49 private cases: hit@3 0.86, silence 0.92 on unanswerable questions.
* Good, because the index is rebuildable from Trilium at any time (~30 s for 265 notes).
* Bad, because there is a second artifact to release: the image `ghcr.io/<owner>/trilium-llm-wiki-recall`
  is versioned with `plugin.json` (`scripts/check-version.sh` fails a mismatching tag).
* Bad, because Trilium 0.106 has no read-only ETAPI tokens; the engine holds a writable token and
  stays read-only by construction (GET-only client, tested).
* Neutral, because the hook runs on every prompt in every repo: it skips slash commands and
  confirmations, is capped at 1.5 s, and stays silent when the engine is missing or slow.

### Confirmation

`recall-engine/run-tests.sh` (unit + live against a disposable Trilium, including a fixture eval
with `--enforce`), and `app/eval.py` against a real instance with a private case file.
