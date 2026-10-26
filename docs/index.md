# trilium-recall

trilium-recall lets Claude find what your Trilium Notes already know **on its own**, without you
saying "check my notes". It is a small container next to Trilium Notes that indexes your notes
(keyword search plus a multilingual embedding model, German and English) and answers in a few
milliseconds.

- **Claude Code:** a prompt hook sends each prompt to the engine. When your notes have something
  relevant, Claude gets up to three short passages (title, type, topic, the best lines, note ID and
  links), a few hundred tokens. When they have nothing, Claude gets nothing. The same note is not
  sent twice in one session, and a slow or unreachable engine never holds up a prompt (1.5 s limit).
- **Any MCP client:** a `recall` tool for searching on purpose, for example mid-task.

It reads Trilium Notes through ETAPI and never writes. Its index is rebuilt from Trilium Notes at
any time, so deleting it is safe.

It works on any Trilium. If you run an [LLM wiki](https://trilium-llm-wiki.marceltov.de/) in it,
recall knows the wiki's structure: wiki pages rank first, sources come as their summaries, and the
wiki's plumbing stays out of the index.

## 1. Run the container

Add a service to the compose file that runs your Trilium Notes:

```yaml
services:
  trilium:
    # ... your existing Trilium Notes service ...

  trilium-recall:
    image: ghcr.io/marceltov/trilium-recall:latest   # or pin a version
    restart: unless-stopped
    mem_limit: 600m
    environment:
      RECALL_LOGIN_PASSWORD: ${RECALL_LOGIN_PASSWORD}   # a long random string, see below
      RECALL_BASE_URL: https://recall.example           # public URL; turns on the OAuth login
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

Create an ETAPI token for the engine in Trilium Notes under *Options → ETAPI* (name it `recall-engine`).
Trilium Notes (0.106) has no read-only tokens, so this token could write. The engine only ever sends
GET requests; keep the token in its environment and nowhere else.

`docker compose up -d trilium-recall`, then `curl http://<host>:8082/health`. The first index build
takes about half a minute for a few hundred notes; `status` turns from `starting` to `ok`.

For claude.ai or remote clients, put the engine behind your TLS reverse proxy like the Trilium Notes
MCP server.

`RECALL_LOGIN_PASSWORD` is the engine's one secret, used two ways:

- **As a header:** Claude Code's hook, `claude mcp add -H` and a claude.ai connector's request
  headers send it as `Authorization: Bearer …`.
- **In the OAuth login:** with `RECALL_BASE_URL` set, a client can instead start from just the URL
  and open a login page that asks for it once. Nothing goes into the client's config; it holds only
  its own OAuth tokens, which refresh on their own.

Generate it with `openssl rand -hex 32` and keep it in your password manager. Changing it logs out
every OAuth client.

The login comes from the shared [mcp-login-oauth](https://github.com/Marceltov/mcp-login-oauth)
library, which trilium-mcp-proxy and the InvoiceNinja and Paperless MCP servers use too.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `RECALL_LOGIN_PASSWORD` | required | Static Bearer token for `/recall` and `/mcp`, and the OAuth login password (0.3.0 renamed it from `RECALL_TOKEN`) |
| `RECALL_BASE_URL` | unset | Public `https://` URL. Set, `/mcp` also takes OAuth logins; unset, only the header works |
| `RECALL_INSTANCES` | required | Comma-separated names, one per Trilium Notes instance |
| `TRILIUM_<NAME>_URL`, `TRILIUM_<NAME>_TOKEN` | required | Per instance; `<NAME>` upper-cased, `-` → `_` |
| `RECALL_POLL_SECONDS` | `60` | How often changed notes are picked up |
| `RECALL_RECONCILE_SECONDS` | `1800` | Full comparison: deletions, moves, label changes |
| `RECALL_PORT` | `8082` | |
| `RECALL_TOOL_DESCRIPTION` | a neutral text | What MCP clients read about the `recall` tool. Name what your notes cover, so the assistant knows when to call it |

With several instances, one query searches all of them and each hit names its instance. Everyone
holding `RECALL_LOGIN_PASSWORD`, or logged in with it, can search every configured instance.

### What gets indexed

All text and code notes, except archived notes and Trilium Notes' hidden notes. Journal notes are
recognised by `#calendarRoot`. With an LLM wiki, its plumbing (*Locks*, *Templates*, *Views*) is left
out, wiki pages rank first, then sources, then journal and other notes, and a source with a summary
page shows up as its summary unless the source itself holds the matching detail.

Edits appear within a minute. Label and relation changes (for example a page set to `reviewed`)
appear at the next full comparison, within 30 minutes, because Trilium Notes does not mark a note as
modified when only its attributes change.

## 2. Connect Claude Code

Install the plugin:

```
/plugin marketplace add Marceltov/trilium-recall
/plugin install trilium-recall
```

Then ask Claude to "set up recall". The `trilium-recall-setup` skill asks for the engine URL and token,
checks `/health`, writes the hook's config and registers the `wiki-recall` MCP server. To switch the
hook off, ask Claude to remove recall (or delete `recall.json` from the plugin data folder).

## 3. Connect claude.ai

Needs `RECALL_BASE_URL` and the reverse proxy. In claude.ai, *Customize → Connectors → Add custom
connector*, with the URL `https://<your engine>/mcp`. claude.ai opens the engine's login page: enter
`RECALL_LOGIN_PASSWORD` once. The `recall` tool then works in every chat, and on the desktop and
mobile apps of the same account.

## Checking quality

The engine ships an evaluation command. Write a YAML file of questions with the pages that should
answer them, plus some your notes cannot answer:

```yaml
- {query: "how are the guests backed up?", expect: [<noteId>]}
- {query: "Wie melde ich ein Gewerbe an?", expect: [<noteId>]}
- {query: "best sourdough hydration", expect: none}
```

and run it against the engine:

```bash
docker compose exec trilium-recall python eval.py --url http://localhost:8082 \
  --token "$RECALL_LOGIN_PASSWORD" --cases /data/cases.yaml --verbose
```

It reports hit@3 (the right page among the first three), silence on unanswerable questions and
latency. Keep your questions private: they describe your notes.

## Moving from trilium-llm-wiki

Up to 0.4.x the engine and the hook were part of
[trilium-llm-wiki](https://trilium-llm-wiki.marceltov.de/), and the image was
`ghcr.io/marceltov/trilium-llm-wiki-recall`. From 0.5.0:

- change the image to `ghcr.io/marceltov/trilium-recall`; the settings and the index volume stay
  the same;
- install this plugin. Its hook keeps reading the `recall.json` the old plugin wrote, and the
  `wiki-recall` MCP server registration stays as it is.
