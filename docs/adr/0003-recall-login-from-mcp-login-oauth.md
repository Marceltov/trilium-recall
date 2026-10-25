---
status: accepted
date: 2026-10-25
decision-makers: Marcel Bruckner
---

# Recall's OAuth login comes from the shared mcp-login-oauth library

## Context and Problem Statement

ADR 0002 gave `/mcp` an OAuth login with its own provider in `recall-engine/app/oauth.py`, adapted
from trilium-mcp. invoiceninja-mcp and paperless-ngx-mcp carry the same code, and the copies had
drifted. Should recall keep its copy?

## Considered Options

* Keep `oauth.py` and port fixes by hand.
* Use [mcp-login-oauth](https://github.com/Marceltov/mcp-login-oauth), the shared library for all of
  Marcel's FastMCP servers.

## Decision Outcome

Chosen: **the shared library**, pinned by git tag (`v0.1.1`). Recall supplies only its one-field form,
a constant-time password check and the same check for static Bearer tokens. Behaviour is unchanged
(the `rcl_` tokens, the password-derived store key, `/recall` static-only), and public clients can now
revoke.

### Consequences

* Good, because login fixes land once for every server.
* Bad, because the Docker builder stage needs `git` to fetch the tagged dependency (runtime image
  unchanged).
* Bad, because stored logins from 0.3.0 aren't carried over: claude.ai reconnects once after the update.
