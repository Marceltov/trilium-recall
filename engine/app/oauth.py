"""OAuth 2.1 login for the MCP endpoint, for clients that can't send a static header (claude.ai).

Adapted from trilium-mcp's TriliumOAuthProvider. FastMCP serves discovery, dynamic client
registration, /authorize, /token (PKCE) and /revoke on top of these methods; this module adds the
one page a human sees, /login, whose password is RECALL_LOGIN_PASSWORD. The same password also
works as a static Bearer token (the Claude Code hook and `claude mcp add -H`).
"""

import os

# Before anything imports caio (fastmcp's file store does): its io_uring/linux-aio backends take locked
# kernel memory per store and Docker's default seccomp blocks io_uring. Threads are plenty here.
os.environ.setdefault("CAIO_IMPL", "thread")

import asyncio  # noqa: E402
import hmac
import html
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp.server.auth import AccessToken, OAuthProvider
from fastmcp.server.auth.auth import ClientRegistrationOptions, RevocationOptions
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

# Issued codes and tokens carry this prefix, so a stale one is recognisably ours.
TOKEN_PREFIX = "rcl_"
STATIC_CLIENT_ID = "static-password"
PENDING_LOGIN_TTL = 10 * 60
AUTH_CODE_TTL = 5 * 60
ACCESS_TOKEN_TTL = 60 * 60
REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60
MAX_LOGIN_ATTEMPTS = 5
FAILED_LOGIN_DELAY = 1.0  # seconds; with MAX_LOGIN_ATTEMPTS, slows guessing to a crawl


def _page(inner: str, status: int = 200) -> HTMLResponse:
    body = ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<title>Wiki recall login</title><style>body{font-family:system-ui,sans-serif;max-width:32rem;"
            "margin:4rem auto;padding:0 1rem;line-height:1.5}input,button{font:inherit;padding:.4rem;"
            f"margin:.3rem 0;width:100%;box-sizing:border-box}}</style></head><body><h1>Wiki recall</h1>{inner}"
            "</body></html>")
    # DENY framing so the password form can't be clickjacked.
    return HTMLResponse(body, status_code=status, headers={"X-Frame-Options": "DENY"})


def _login_page(pending_id: str, client_name: str, redirect_host: str, error: str = "", status: int = 200):
    e = html.escape
    err = f'<p style="color:#b00">{e(error)}</p>' if error else ""
    return _page(
        f"{err}<p><b>{e(client_name)}</b> wants to search your wiki. After login you will be sent to "
        f"<b>{e(redirect_host)}</b>. Only continue if you started this.</p>"
        f'<form method="post"><input type="hidden" name="id" value="{e(pending_id)}">'
        '<label>Recall password <input type="password" name="password" autofocus required></label>'
        "<button>Authorize</button></form>", status)


def _dead_end_page(heading: str, what: str, status: int) -> HTMLResponse:
    """A login that can't continue. The usual cause is the client interrupting its own flow (claude.ai
    asking you to log in to claude.ai partway through, then dropping the finished login)."""
    return _page(
        f"<h2>{html.escape(heading)}</h2><p>{html.escape(what)}</p>"
        "<p><b>Fix:</b> go back to your app and use its Reconnect button, or remove the connector and add "
        "it again. Being logged in to the app first avoids the interruption.</p>", status)


class RecallOAuthProvider(OAuthProvider):
    def __init__(self, *, base_url: str, password: str, store: AsyncKeyValue):
        super().__init__(base_url=base_url,
                         client_registration_options=ClientRegistrationOptions(enabled=True),
                         revocation_options=RevocationOptions(enabled=True))
        self.password = password
        self.store = store

    # -- clients and codes ----------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = await self.store.get(client_id, collection="clients")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self.store.put(client_info.client_id, client_info.model_dump(mode="json"), collection="clients")

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        pending_id = secrets.token_urlsafe(32)
        await self.store.put(pending_id, {"client_id": client.client_id, "params": params.model_dump(mode="json"),
                                          "attempts": 0},
                             collection="pending", ttl=PENDING_LOGIN_TTL)
        return f"{str(self.base_url).rstrip('/')}/login?id={pending_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        data = await self.store.get(authorization_code, collection="codes")
        if not data or data["client_id"] != client.client_id:
            return None
        return AuthorizationCode.model_validate(data)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        if not await self.store.get(authorization_code.code, collection="codes"):
            raise TokenError("invalid_grant", "Authorization code not found or already used.")
        await self.store.delete(authorization_code.code, collection="codes")
        return await self._issue(client.client_id, authorization_code.scopes)

    # -- tokens -----------------------------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        data = await self.store.get(refresh_token, collection="refresh")
        if not data or data["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=data["client_id"], scopes=data["scopes"],
                            expires_at=data["expires_at"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        data = await self.store.get(refresh_token.token, collection="refresh")
        if not data:
            raise TokenError("invalid_grant", "Refresh token not found or already used.")
        if not set(scopes) <= set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Requested scopes exceed the original grant.")
        await self._drop(data["access"], refresh_token.token)  # rotate: the old pair dies
        return await self._issue(client.client_id, scopes or refresh_token.scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = await self.store.get(token, collection="access")
        if not data:
            return None
        return AccessToken(token=token, client_id=data["client_id"], scopes=data["scopes"],
                           expires_at=data["expires_at"])

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token.encode(), self.password.encode()):
            return AccessToken(token=token, client_id=STATIC_CLIENT_ID, scopes=[])
        return await self.load_access_token(token) if token.startswith(TOKEN_PREFIX) else None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            data = await self.store.get(token.token, collection="refresh")
            pair = (data["access"], token.token) if data else None
        else:
            data = await self.store.get(token.token, collection="access")
            pair = (token.token, data["refresh"]) if data else None
        if pair:
            await self._drop(*pair)

    # -- the login page ---------------------------------------------------------------------

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        return [*super().get_routes(mcp_path), Route("/login", self._login, methods=["GET", "POST"])]

    async def _login(self, request: Request):
        form = await request.form() if request.method == "POST" else request.query_params
        pending_id = str(form.get("id", ""))
        pending = await self.store.get(pending_id, collection="pending") if pending_id else None
        if not pending:
            return _dead_end_page("Login link expired or already used",
                                  "Login links work once, for 10 minutes, and end after "
                                  f"{MAX_LOGIN_ATTEMPTS} wrong passwords.", 400)
        if pending.get("done"):
            # A browser re-submitted a login that already succeeded (seen with claude.ai's flow).
            return _dead_end_page("Login already completed",
                                  "Your password was accepted a moment ago and the browser sent the form a "
                                  "second time. If your app shows the connector without tools, it dropped "
                                  "that finished login.", 200)
        params = AuthorizationParams.model_validate(pending["params"])
        client = await self.get_client(pending["client_id"])
        client_name = (client.client_name if client else None) or pending["client_id"]
        redirect = str(params.redirect_uri)
        page = (pending_id, client_name, urlsplit(redirect).netloc or redirect)
        if request.method == "GET":
            return _login_page(*page)

        # The password is compared and dropped: never stored, never logged.
        if not hmac.compare_digest(str(form.get("password", "")).encode(), self.password.encode()):
            await asyncio.sleep(FAILED_LOGIN_DELAY)
            attempts = pending["attempts"] + 1
            if attempts >= MAX_LOGIN_ATTEMPTS:
                await self.store.delete(pending_id, collection="pending")
            else:
                await self.store.put(pending_id, {**pending, "attempts": attempts}, collection="pending",
                                     ttl=PENDING_LOGIN_TTL)
            return _login_page(*page, error="Wrong password.", status=401)

        # Keep a short-lived marker instead of deleting, so a replayed form gets an honest answer.
        await self.store.put(pending_id, {"done": True}, collection="pending", ttl=PENDING_LOGIN_TTL)
        code = AuthorizationCode(code=TOKEN_PREFIX + secrets.token_urlsafe(32), client_id=pending["client_id"],
                                 scopes=params.scopes or [], expires_at=time.time() + AUTH_CODE_TTL,
                                 code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
                                 redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                                 resource=params.resource)
        await self.store.put(code.code, code.model_dump(mode="json"), collection="codes", ttl=AUTH_CODE_TTL)
        return RedirectResponse(construct_redirect_uri(redirect, code=code.code, state=params.state),
                                status_code=302)

    async def _issue(self, client_id: str, scopes: list[str]) -> OAuthToken:
        access = TOKEN_PREFIX + secrets.token_urlsafe(32)
        refresh = TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = int(time.time())
        common = {"client_id": client_id, "scopes": scopes}
        await self.store.put(access, {**common, "refresh": refresh, "expires_at": now + ACCESS_TOKEN_TTL},
                             collection="access", ttl=ACCESS_TOKEN_TTL)
        await self.store.put(refresh, {**common, "access": access, "expires_at": now + REFRESH_TOKEN_TTL},
                             collection="refresh", ttl=REFRESH_TOKEN_TTL)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TOKEN_TTL,
                          refresh_token=refresh, scope=" ".join(scopes) or None)

    async def _drop(self, access: str, refresh: str) -> None:
        await self.store.delete(access, collection="access")
        await self.store.delete(refresh, collection="refresh")


def build_oauth_provider(base_url: str, password: str, data_dir: Path) -> RecallOAuthProvider:
    """Provider on a Fernet-encrypted file store keyed by the password: changing
    RECALL_LOGIN_PASSWORD turns every stored login into a miss, so all clients log in again."""
    root = data_dir / "oauth"
    root.mkdir(parents=True, exist_ok=True)
    files = FileTreeStore(data_directory=root,
                          key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(root),
                          collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(root))
    store = FernetEncryptionWrapper(key_value=files, source_material=password, salt="trilium-recall-oauth",
                                    raise_on_decryption_error=False)
    return RecallOAuthProvider(base_url=base_url, password=password, store=store)
