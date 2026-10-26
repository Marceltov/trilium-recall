# Connect Claude

## Claude Code

Install the plugin and let it set up the connection:

```
/plugin marketplace add Marceltov/trilium-recall
/plugin install trilium-recall
```

Then ask Claude to "set up recall". The `trilium-recall-setup` skill asks for the engine URL and
password, checks `/health`, writes the hook's config (`recall.json` in the plugin's data folder,
readable only by you) and registers the `wiki-recall` MCP server. The hook works from the next
prompt, the tool from the next session.

To switch the hook off, ask Claude to remove recall, or delete `recall.json`.

## claude.ai and the Claude apps

Needs `RECALL_BASE_URL` and the reverse proxy. *Customize → Connectors → Add custom connector*, with
the URL `https://<your engine>/mcp`. claude.ai opens the engine's login page: enter
`RECALL_LOGIN_PASSWORD` once. Instead of logging in, you can also send the password as an
`Authorization: Bearer …` request header in the connector's advanced settings.

The `recall` tool then works in every chat, and in the desktop and mobile apps of the same account.

## Other MCP clients

Any client that speaks streamable HTTP: the URL `https://<your engine>/mcp`, with either the OAuth
login or the Bearer header.

## Why a plugin, and not just the MCP server?

The MCP tool alone works, and on claude.ai it's all there is. But a tool only runs when the model
decides to call it, and a model rarely stops to ask "do my notes know something about this?" before
it starts on a task. It doesn't know what it doesn't know.

The prompt hook turns that around: every prompt is checked, in about 16 ms, before Claude sees it.
When something relevant exists, Claude starts with it in the context; when nothing does, nothing is
added. That's what "on its own" means here, and a hook can only be shipped in a Claude Code plugin.
The plugin's other part, the setup skill, just writes the hook's config and registers the tool.

| | Prompt hook (Claude Code) | `recall` tool (any client) |
|---|---|---|
| When it runs | before every prompt | when the model calls it |
| Cost when nothing is relevant | nothing added | one tool call |
| Good for | context Claude didn't know to ask for | searching on purpose, mid-task |
