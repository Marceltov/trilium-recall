# engine

Hybrid search over Trilium instances: a Claude Code `UserPromptSubmit` hook (`POST /recall`) and an
MCP `recall` tool (`/mcp`). User docs: `docs/index.md` (published at https://trilium-recall.marceltov.de/).

## Commands

```bash
uv sync                                  # dev environment
uv run pytest -q app/tests --ignore=app/tests/live   # unit tests
./run-tests.sh -q                        # unit + live against the disposable fixture
bash scripts/fetch-model.sh .models/e5-small         # model for the ONNX tests (gitignored)
uv run python app/eval.py --url http://localhost:9191 --token dev-only-recall-password \
  --cases eval/fixture-cases.yaml --verbose          # score a running engine
```

## Layout

`app/` holds flat modules: `config` (env), `text` (HTML → sections), `embed` (ONNX e5-small,
hash stand-in for tests), `index` (SQLite: FTS5 + sqlite-vec + links), `trilium` (read-only
ETAPI), `sync` (build, poll, reconcile), `rank` (fusion + gate), `skip`, `sessions`,
`render`, `server` (Starlette + FastMCP), `eval`.

## Trilium 0.106 facts the code relies on (verified against the fixture and production)

- A search that **starts with `(`** returns nothing. Put the date clause first:
  `note.utcDateModified >= '…' and (note.type = text or note.type = code)`.
- Changing an **attribute** (label or relation) does **not** bump the note's
  `utcDateModified`; title and content changes do (content also changes `blobId`). So status
  and relation changes reach the index through the reconcile (every 30 min), not the poll.
- `~internalLink` relations are derived from links when content is **saved** (`PUT …/content`),
  not by `create-note`, and only for targets that exist at save time.
- Default search leaves out the hidden subtree and archived notes.

## Fixture

`fixture/trilium-data` is a committed Trilium v0.106.1 DB holding Trilium's demo notes plus a
synthetic wiki (`fixture/seed.py`, fixed `fx…` noteIds). `fixture/etapi.token` and
`dev-only-recall-password` are throwaway credentials for that instance only. Live tests are pinned
to `localhost:9190/9191` and never read the environment (`test_live_target.py` guards it).
To change the seed: start a clean copy, run `skills/trilium-llm-wiki/setup.py` and
`fixture/seed.py`, stop Trilium, commit the DB.

## Memory

The tokenizer is the model's SentencePiece file (same ids as `tokenizer.json`, ~60 MB instead
of ~280 MB). Embedding runs in padded-token batches of 1024. With `MALLOC_ARENA_MAX=2` and
`MALLOC_TRIM_THRESHOLD_=65536` (set in the Dockerfile) a full build peaks at about 300 MB.
