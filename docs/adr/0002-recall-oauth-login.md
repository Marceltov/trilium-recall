---
status: accepted
date: 2026-10-25
decision-makers: Marcel Bruckner
---

# Recall engine: OAuth login for /mcp with one engine password; instances stay deploy-time config

## Context and Problem Statement

The recall engine (ADR 0001) authenticated every client with one static Bearer token. claude.ai's
custom connector can't send a static header; it expects an OAuth login. How do claude.ai and other
OAuth-only clients get access to `recall` without weakening the engine's security boundary? Issue #6.

> **Correction (2026-10-26):** claude.ai custom connectors can send request headers (up to four,
> under the connector's advanced settings), so the static token works there too. The OAuth login is
> a convenience (just the URL, nothing pasted into the client's config), not a requirement. The
> decision below stands.

## Considered Options

* **Login with an instance's Trilium password**, the way trilium-mcp does: the engine checks the
  password through `/etapi/auth/login`, and each client sees only the instances it proved.
* **Login mints the engine's ETAPI tokens, and instances are added in the login page** (URL plus
  password). This needs no configuration, but it puts a URL input on a public page, which lets anyone
  make the engine send requests into the LAN or index a Trilium they control. Indexing would also
  depend on whoever logged in first.
* **One engine password (`RECALL_LOGIN_PASSWORD`)**, used both as the static Bearer token and as the
  OAuth login password. Instances and their ETAPI tokens stay in the deploy configuration.

## Decision Outcome

Chosen: **one engine password**. Which Trilium instances the engine reads, and with which tokens, is
decided at deploy time and kept in git and the secret store like the rest of the homelab. OAuth only
grants a client access to `recall`. One secret serves the header clients (the Claude Code hook,
`claude mcp add -H`) and the browser login, so nothing else has to be managed. `RECALL_TOKEN` is
renamed rather than kept beside it.

The OAuth provider is adapted from trilium-mcp's `TriliumOAuthProvider`: FastMCP's dynamic client
registration, PKCE, refresh rotation and revocation. The store is Fernet-encrypted on the index
volume, and its key is derived from the password. Copying it instead of sharing a package was a
deliberate choice: a shared package would mean reworking trilium-mcp for a single additional user.

### Consequences

* Good, because claude.ai, the desktop app and mobile connect with a one-time login, and
  `RECALL_BASE_URL` unset keeps the 0.2.0 behaviour.
* Good, because changing the password logs out every OAuth client, which is the revocation story.
* Bad, because access isn't scoped per instance: anyone with the password sees every configured
  instance. Per-person scoping would need per-person passwords, or the Trilium-password option.
* Bad, because the OAuth code now exists twice (here and in trilium-mcp), and fixes have to be
  applied to both.
