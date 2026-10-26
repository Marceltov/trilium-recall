<h1 align="center"><a href="https://trilium-recall.marceltov.de/">trilium-recall</a></h1>

<p align="center">
  <a href="https://trilium-recall.marceltov.de/">
    <img alt="Documentation" src="https://img.shields.io/badge/docs-trilium--recall.marceltov.de-2f7a27">
  </a>
  <a href="https://github.com/Marceltov/trilium-recall/pkgs/container/trilium-recall">
    <img alt="Image: ghcr.io/marceltov/trilium-recall" src="https://img.shields.io/badge/image-ghcr.io%2Fmarceltov%2Ftrilium--recall-blue">
  </a>
  <a href="LICENSE">
    <img alt="License: AGPL-3.0-or-later" src="https://img.shields.io/badge/License-AGPL--3.0--or--later-blue.svg">
  </a>
</p>

**Claude remembers what you wrote in [Trilium Notes](https://triliumnotes.org)**, without you saying "check my notes".

- **A small container next to Trilium** indexes your notes (keyword search plus a multilingual embedding model, German and English) and answers in a few milliseconds. It only reads, and its index can be rebuilt at any time.
- **An MCP server for any client** (claude.ai, Claude Code, …): add the URL and its instructions tell the model when to call `recall`. It gets up to three short passages with note IDs, a few hundred tokens, or nothing.
- **Automatic in Claude Code:** the optional plugin adds a prompt hook that checks every prompt before Claude sees it.

On a real 280-note Trilium: the right note among the first three for 86 % of questions (Trilium's own search: 41 %), nothing returned for 92 % of questions the notes can't answer, about 16 ms per lookup. [Measurements](https://trilium-recall.marceltov.de/measurements/)

It works on any Trilium. With an [LLM wiki](https://trilium-llm-wiki.marceltov.de/) in it, recall knows the wiki's structure and ranks its pages first.

**Full documentation: [trilium-recall.marceltov.de](https://trilium-recall.marceltov.de/)**

## Install

Run the container next to Trilium (compose snippet in the [docs](https://trilium-recall.marceltov.de/install/)), then add `https://<your engine>/mcp` to your MCP client. For automatic mode in Claude Code:

```
/plugin marketplace add Marceltov/trilium-recall
/plugin install trilium-recall
```

and ask Claude to "set up recall".

## What's inside

| Path | What it is |
|---|---|
| `engine/` | the container: indexer, ranking, `/recall` for the hook, `/mcp` for the tool ([engine/README.md](engine/README.md)) |
| `scripts/recall-hook.sh` | the `UserPromptSubmit` hook (`hooks/hooks.json`) |
| `skills/trilium-recall-setup/` | connects Claude Code to a running engine |
| `docs/` | the documentation site and the ADRs |

## License

[AGPL-3.0-or-later](LICENSE). Up to 0.4.x the code was part of trilium-llm-wiki under MIT.
