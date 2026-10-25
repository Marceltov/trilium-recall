---
name: trilium-recall-setup
description: Connect Claude Code to a running recall engine for the LLM wiki (the trilium-llm-wiki-recall container) — set its URL and token once, so a prompt hook injects relevant wiki passages automatically and the `recall` MCP tool is available; also list or remove that connection. Use when the user asks to set up, connect, configure, check or remove wiki recall / the recall engine, or says Claude should find wiki knowledge on its own.
---

# Set up wiki recall

The recall engine is a separate container next to Trilium Notes (see the docs page *Recall engine*:
https://trilium-llm-wiki.marceltov.de/recall/). It indexes the wiki and answers "does the wiki know
something about this?" in a few milliseconds. Once connected, Claude Code gets two things:

- a **prompt hook** (`UserPromptSubmit`, shipped with this plugin) that sends each prompt to the engine
  and adds up to three short wiki passages to the context when something relevant exists, and nothing
  otherwise;
- the **`recall` MCP tool** (server name `wiki-recall`), for searching on purpose mid-task.

The connection is two pieces, both written by this skill: the hook's config file
`recall.json` in the plugin data folder, and the MCP server registration. Never print the password.

## On claude.ai, the desktop app or Cowork

There is no hook and no `claude` CLI there. Add a custom connector (*Customize → Connectors → Add
custom connector*) with the engine's public HTTPS URL ending in `/mcp`. claude.ai opens the engine's
login page; the password is the engine's `RECALL_LOGIN_PASSWORD`. This needs `RECALL_BASE_URL` set on
the engine (0.3.0 or later): without it, the connector gets a 401 and no login page. Everything below
applies to Claude Code.

## Determine the operation

**Add** (default), **check**, or **remove**.

## Add

1. Ask for the engine URL (for example `https://trilium-recall.example`, no path) and the `RECALL_LOGIN_PASSWORD`
   the container was started with (called `RECALL_TOKEN` before 0.3.0). If the user does not know it,
   it is in the engine's environment (its compose file or secret store), not in Trilium.
2. Check it: `curl -s <url>/health`. Expect JSON with `"status": "ok"` (or `"starting"` while the first
   index build runs). `"error"` names the misconfiguration; stop and report it.
3. Write the hook config, readable only by the user. The plugin data folder is `$CLAUDE_PLUGIN_DATA`,
   falling back to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugin-data/trilium-llm-wiki`:

   ```bash
   dir="${CLAUDE_PLUGIN_DATA:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugin-data/trilium-llm-wiki}"
   mkdir -p "$dir" && umask 077 && python3 -c 'import json,sys; json.dump({"url": sys.argv[1], "token": sys.argv[2]}, open(sys.argv[3], "w"))' "<url>" "<password>" "$dir/recall.json"
   ```

4. Register the MCP server (user scope, same as the Trilium instances):

   ```bash
   claude mcp add --transport http wiki-recall "<url>/mcp" -H "Authorization: Bearer <password>" -s user
   ```

   If `wiki-recall` already exists, `claude mcp remove wiki-recall -s user` first.
5. Confirm: `claude mcp get wiki-recall`, then a test request through the hook's path:

   ```bash
   curl -s -H "Authorization: Bearer <password>" -H 'Content-Type: application/json' \
     -d '{"prompt": "<a question the wiki can answer>"}' "<url>/recall"
   ```

   A `context` starting with `Wiki recall` means it works. The hook takes effect from the next prompt;
   the MCP tool from the next session.

## Check

`curl -s <url>/health` (URL from `recall.json`) and `claude mcp get wiki-recall`. Report the status,
note and section counts, `last_ok` and any `last_error`.

## Remove

Delete `recall.json` from the plugin data folder (the hook then does nothing) and run
`claude mcp remove wiki-recall -s user`.

## Using recall

When the `recall` tool is available, call it yourself before a homelab or infrastructure task, when
you hit an unfamiliar error, host or service, and before a decision the wiki may already have made.
Hits carry note IDs; read a full page with the Trilium Notes MCP.
