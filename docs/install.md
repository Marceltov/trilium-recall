# Run the engine

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

For claude.ai or remote clients, put the engine behind your TLS reverse proxy, like Trilium itself.

## The password

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

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `RECALL_LOGIN_PASSWORD` | required | Static Bearer token for `/recall` and `/mcp`, and the OAuth login password (0.3.0 renamed it from `RECALL_TOKEN`) |
| `RECALL_BASE_URL` | unset | Public `https://` URL. Set, `/mcp` also takes OAuth logins; unset, only the header works |
| `RECALL_INSTANCES` | required | Comma-separated names, one per Trilium Notes instance |
| `TRILIUM_<NAME>_URL`, `TRILIUM_<NAME>_TOKEN` | required | Per instance; `<NAME>` upper-cased, `-` → `_` |
| `RECALL_POLL_SECONDS` | `60` | How often changed notes are picked up |
| `RECALL_RECONCILE_SECONDS` | `1800` | Full comparison: deletions, moves, label changes |
| `RECALL_PORT` | `8082` | |
| `RECALL_INSTRUCTIONS` | when to call `recall` | Sent to MCP clients when they connect; most put it into the model's system prompt. Say what your notes cover and when to look them up |
| `RECALL_TOOL_DESCRIPTION` | a neutral text | What MCP clients read about the `recall` tool itself |

With several instances, one query searches all of them and each hit names its instance. Everyone
holding `RECALL_LOGIN_PASSWORD`, or logged in with it, can search every configured instance.
