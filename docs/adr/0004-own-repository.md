---
status: accepted
date: 2026-10-26
decision-makers: Marcel Bruckner
---

# Recall moves out of trilium-llm-wiki into its own repository and plugin

## Context and Problem Statement

ADR 0001 put the recall engine into the trilium-llm-wiki repository because the wiki was its first
user. It indexes every text and code note of a Trilium instance, though; the wiki only adds area
tags (`#llmWikiPart`) and page metadata, which come back empty without a wiki. Hidden behind the
wiki's name, it is invisible to people who want "Claude knows my notes" without running an LLM wiki.

## Considered Options

* Keep it in trilium-llm-wiki.
* Own repository `trilium-recall`: engine, prompt hook, setup skill and docs, as its own Claude Code
  plugin.

## Decision Outcome

Chosen: **own repository**, with the history of `recall-engine/` and its docs carried over
(`git filter-repo`). The engine lives in `engine/`, the image becomes `ghcr.io/<owner>/trilium-recall`
(versions continue at 0.5.0), the plugin is `trilium-recall`, the license AGPL-3.0-or-later. The
wiki's labels stay an optional extra, and the `recall` tool's description is configurable
(`RECALL_TOOL_DESCRIPTION`) instead of naming one person's wiki.

### Consequences

* Good, because recall can be found, installed and released on its own, and the wiki plugin gets
  smaller.
* Good, because nothing breaks for existing users: the hook reads a `recall.json` left by the wiki
  plugin, and the `wiki-recall` MCP server name stays.
* Bad, because a user of both now installs two plugins, and existing deployments change one image
  name.
