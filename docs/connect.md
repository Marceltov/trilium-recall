# Connect Claude

Recall is an MCP server. Add its URL to your client and you're done: when the client connects, the
engine tells the model what the notes are for and when to call `recall` (its
[instructions](install.md#settings)). In Claude Code, the plugin adds an automatic mode on top.

## Any MCP client

The URL is `https://<your engine>/mcp`. Log in once with `RECALL_LOGIN_PASSWORD` on the engine's
login page (needs `RECALL_BASE_URL` and the reverse proxy), or send it as an
`Authorization: Bearer …` header.

=== "claude.ai and the Claude apps"

    *Customize → Connectors → Add custom connector*, paste the URL, and log in on the page that
    opens. The `recall` tool then works in every chat, and in the desktop and mobile apps of the
    same account.

=== "Claude Code"

    ```
    claude mcp add --transport http wiki-recall https://<your engine>/mcp -s user
    ```

    then `/mcp` → *Authenticate*. Or with the header instead of the login:
    `-H "Authorization: Bearer <password>"`.

=== "Other clients"

    Any client that speaks streamable HTTP, with the OAuth login or the Bearer header.

## Automatic mode in Claude Code: the plugin

With the MCP server alone, the model decides when to call `recall`. The instructions push it to
call early, but a model that thinks it knows the answer often skips the call, and that's exactly
when your notes would have corrected it.

The plugin adds a prompt hook that removes the decision: every prompt is checked, in about 16 ms,
before Claude sees it. When something relevant exists, Claude starts with it in the context; when
nothing does, nothing is added.

```
/plugin marketplace add Marceltov/trilium-recall
/plugin install trilium-recall
```

Then ask Claude to "set up recall". The `trilium-recall-setup` skill asks for the engine URL and
password, checks `/health`, writes the hook's config (`recall.json` in the plugin's data folder,
readable only by you) and registers the `wiki-recall` MCP server, so you get both. The hook works
from the next prompt, the tool from the next session. To switch the hook off, ask Claude to remove
recall, or delete `recall.json`.

| | MCP server (any client) | + plugin hook (Claude Code) |
|---|---|---|
| Setup | add the URL | install the plugin, "set up recall" |
| When recall runs | when the model calls it, nudged by the instructions | before every prompt |
| When nothing is relevant | one tool call with no result | nothing added |
| Good for | searching on purpose, mid-task | context Claude didn't know to ask for |

Hooks can only be shipped in a Claude Code plugin, so on claude.ai the MCP server with its
instructions is the whole story.
