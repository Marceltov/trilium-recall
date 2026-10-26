# Shared rules for the Trilium Notes skills

<!-- Single source. Copied into every skills/*/reference/shared-rules.md by scripts/sync-shared.sh; edit this file, not the copies. -->

## Working with multiple instances

A user may have more than one Trilium Notes instance connected at once — each shows up as its own MCP server, so tool names are namespaced per instance: `mcp__trilium__search_notes` for the default instance, `mcp__trilium-work__search_notes` for one labeled `work`, and so on (see `trilium-manage-instances`). Every skill that calls Trilium Notes MCP tools resolves which instance to use like this:

1. Note which Trilium Notes tool prefixes are actually available in this conversation: `mcp__trilium([-_].+)?__*`, plus a claude.ai connector's (see below).
2. Exactly one exists → use it, no question asked.
3. More than one exists → check whether the user already named an instance in the conversation (by label, or something identifying like "the work one") and match it to the corresponding prefix.
4. Still ambiguous → ask once which instance, listing the available labels.
5. Use that one resolved prefix for every MCP tool call for the rest of the current task.

On claude.ai, the Claude desktop app or in Cowork, a Trilium Notes MCP server is connected as a connector instead, and its tools carry the connector's name as prefix (for example `mcp__claude_ai_<connector name>__search_notes`). Treat it like any other instance. If no Trilium Notes tools are available at all, say so and explain how to connect: in Claude Code with the `trilium-manage-instances` skill, on claude.ai by adding Trilium Notes' MCP server (through trilium-mcp-proxy) as a custom connector.
