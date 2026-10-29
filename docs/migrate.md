# Moving to passageway

trilium-recall's engine has grown into **[passageway](https://passageway.marceltov.de/)**: the same retrieval (keywords plus a multilingual embedding model, a relevance gate, up to three passages or nothing), made source-agnostic, with Trilium as one connector among others, a choice of embedding models, a public evaluation harness and a published measurement. On this repository's own public fixture the passageway Trilium connector scores hit@3 0.92 and silence 1.0 against trilium-recall's 0.83 and 1.0 ([the connector](https://passageway.marceltov.de/connectors/trilium/)).

trilium-recall stays as it is and keeps working; new work happens in passageway. This page says what changes when you move.

## What stays the same

- The `recall` MCP tool, its instructions on connect, the up-to-three-passages answer and the silence when nothing fits.
- The prompt hook for Claude Code: passageway's hook reads a `recall.json` written for trilium-recall until you replace it, so the connection keeps working after the switch.
- Read-only access through ETAPI, the index that can always be deleted and rebuilt, the areas of an LLM wiki (`#llmWikiPart`, `#calendarRoot`), the wiki labels and relations.

## What changes

| trilium-recall | passageway |
|---|---|
| Image `ghcr.io/marceltov/trilium-recall` | Image `ghcr.io/marceltov/passageway` ([Run it](https://passageway.marceltov.de/deploy/)) |
| `RECALL_LOGIN_PASSWORD`, `RECALL_BASE_URL`, `RECALL_PORT`, `RECALL_POLL_SECONDS`, `RECALL_RECONCILE_SECONDS`, `RECALL_INSTRUCTIONS`, `RECALL_TOOL_DESCRIPTION` | The same names with `PASSAGEWAY_` instead of `RECALL_` |
| `RECALL_INSTANCES=main`, `TRILIUM_MAIN_URL`, `TRILIUM_MAIN_TOKEN` | One `[[connector]]` per instance in `passageway.toml` (below); the token stays an environment variable, referenced as `env:NAME` |
| `recall(query, instance=...)` | `recall(query, source=...)`: an instance is a source, named after its connector |
| `RECALL_MODEL_DIR` | `PASSAGEWAY_MODEL_DIR`; the model is fetched on first start, pinned and checksummed, or baked into the image |
| The trilium-recall plugin and `/trilium-recall-setup` | The passageway plugin (`/plugin marketplace add Marceltov/passageway`) and `/passageway-setup` |
| A summary shown in place of its source when it matched almost as well | Not carried over: a summary and its source link each other, and a hit shows the other as a related item ([ADR 0004](https://passageway.marceltov.de/adr/0004-no-summary-for-source-substitution/)) |

## The configuration

```toml
# /config/passageway.toml in the container, ~/.config/passageway/passageway.toml on a machine
[[connector]]
name = "main"                                   # the source name recall shows; was RECALL_INSTANCES
command = ["python", "-m", "passageway_connector_trilium"]
env = { URL = "http://trilium:8080", WEB_URL = "https://notes.example.org" }
secrets = { TOKEN = "env:TRILIUM_MAIN_TOKEN" }  # the same variable as before
```

```yaml
services:
  passageway:
    image: ghcr.io/marceltov/passageway:latest
    ports: ["9093:8082"]
    volumes:
      - passageway-data:/data
      - ./passageway.toml:/config/passageway.toml:ro
    environment:
      PASSAGEWAY_LOGIN_PASSWORD: ${RECALL_LOGIN_PASSWORD}   # the same secret keeps working for the hook and the tool
      PASSAGEWAY_BASE_URL: https://recall.example
      TRILIUM_MAIN_TOKEN: ${RECALL_ETAPI_TOKEN}
volumes:
  passageway-data:
```

The index is rebuilt from Trilium on the first start (about half a minute for a few hundred notes), so nothing is copied over. Keep the old container until the new one's `/health` says `ok`, then point the MCP client and the hook at the new URL (the same URL, if the port is reused).

## Measured, not promised

The parity above is on the public fixture in this repository (`eval/fixture-cases.yaml`), reproduced in passageway with the real model against an in-test ETAPI. The private question set behind the numbers on [Measurements](measurements.md) has not been run against passageway yet; that is the owner's check before the production instance moves.
