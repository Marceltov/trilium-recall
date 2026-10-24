# Recall engine

Optional. The recall engine lets Claude find what your wiki already knows **on its own**, without
you saying "check the wiki". It is a small container next to Trilium Notes that indexes your notes
(keyword search plus a multilingual embedding model, German and English) and answers in a few
milliseconds.

- **Claude Code:** a prompt hook sends each prompt to the engine. When the wiki has something
  relevant, Claude gets up to three short passages (title, type, topic, the best lines, note ID and
  links), a few hundred tokens. When it has nothing, Claude gets nothing. The same page is not sent
  twice in one session, and a slow or unreachable engine never holds up a prompt (1.5 s limit).
- **Any MCP client:** a `recall` tool for searching on purpose, for example mid-task.

It reads Trilium Notes through ETAPI and never writes. Its index is rebuilt from Trilium Notes at
any time, so deleting it is safe.

## 1. Run the container

Add a service to the compose file that runs your Trilium Notes:

```yaml
services:
  trilium:
    # ... your existing Trilium Notes service ...

  trilium-recall:
    image: ghcr.io/marceltov/trilium-llm-wiki-recall:latest   # or pin a version
    restart: unless-stopped
    mem_limit: 600m
    environment:
      RECALL_TOKEN: ${RECALL_TOKEN}          # a long random string; clients send it as a bearer token
      RECALL_INSTANCES: main
      TRILIUM_MAIN_URL: http://trilium:8080
      TRILIUM_MAIN_TOKEN: ${RECALL_ETAPI_TOKEN}
    volumes:
      - recall-index:/data
    ports:
      - "8082:8082"

volumes:
  recall-index:
```

Create the ETAPI token in Trilium Notes under *Options → ETAPI*. The engine only reads, but a Trilium
Notes ETAPI token can write, so keep it in the engine's environment and nowhere else.

`docker compose up -d trilium-recall`, then `curl http://<host>:8082/health`. The first index build
takes about half a minute for a few hundred notes; `status` turns from `starting` to `ok`.

For claude.ai or remote clients, put the engine behind your TLS reverse proxy like the Trilium Notes
MCP server.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `RECALL_TOKEN` | required | Bearer token for `/recall` and `/mcp` |
| `RECALL_INSTANCES` | required | Comma-separated names, one per Trilium Notes instance |
| `TRILIUM_<NAME>_URL`, `TRILIUM_<NAME>_TOKEN` | required | Per instance; `<NAME>` upper-cased, `-` → `_` |
| `RECALL_POLL_SECONDS` | `60` | How often changed notes are picked up |
| `RECALL_RECONCILE_SECONDS` | `1800` | Full comparison: deletions, moves, label changes |
| `RECALL_PORT` | `8082` | |

With several instances, one query searches all of them and each hit names its instance. Everyone
holding `RECALL_TOKEN` can search every configured instance.

### What gets indexed

All text and code notes, except the wiki's plumbing (*Locks*, *Templates*, *Views*), archived notes
and Trilium Notes' hidden notes. Wiki pages rank first, then sources, then journal and other notes. A
source with a summary page shows up as its summary unless the source itself holds the matching
detail.

Edits appear within a minute. Label and relation changes (for example a page set to `reviewed`)
appear at the next full comparison, within 30 minutes, because Trilium Notes does not mark a note as
modified when only its attributes change.

## 2. Connect Claude Code

Ask Claude to "set up wiki recall". The `trilium-recall-setup` skill asks for the engine URL and token,
checks `/health`, writes the hook's config and registers the `wiki-recall` MCP server. To switch the
hook off, ask Claude to remove wiki recall (or delete `recall.json` from the plugin data folder).

## Checking quality

The engine ships an evaluation command. Write a YAML file of questions with the pages that should
answer them, plus some the wiki cannot answer:

```yaml
- {query: "how are the guests backed up?", expect: [<noteId>]}
- {query: "Wie melde ich ein Gewerbe an?", expect: [<noteId>]}
- {query: "best sourdough hydration", expect: none}
```

and run it against the engine:

```bash
docker compose exec trilium-recall python eval.py --url http://localhost:8082 \
  --token "$RECALL_TOKEN" --cases /data/cases.yaml --verbose
```

It reports hit@3 (the right page among the first three), silence on unanswerable questions and
latency. Keep your questions private: they describe your notes.
