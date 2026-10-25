"""Drive the OAuth browser flow against the dev stack, as claude.ai would, then call the tool."""

import asyncio
import base64
import hashlib
import secrets

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.live.conftest import ENGINE, RECALL_PASSWORD

REDIRECT = "http://localhost:9/cb"


def _login(http: httpx.Client) -> str:
    """register -> authorize -> /login -> token; returns the access token."""
    client_id = http.post("/register", json={
        "client_name": "live-oauth", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}).json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = http.get("/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
                                       "code_challenge": challenge, "code_challenge_method": "S256", "state": "s"})
    pending = httpx.URL(r.headers["location"]).params["id"]
    r = http.post("/login", data={"id": pending, "password": RECALL_PASSWORD})
    code = httpx.URL(r.headers["location"]).params["code"]
    return http.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                     "client_id": client_id, "code_verifier": verifier}).json()["access_token"]


def test_oauth_login_then_recall_over_mcp():
    with httpx.Client(base_url=ENGINE, timeout=30) as http:
        assert http.post("/mcp", json={}).status_code == 401
        access = _login(http)

    async def call():
        transport = StreamableHttpTransport(f"{ENGINE}/mcp", headers={"Authorization": f"Bearer {access}"})
        async with Client(transport) as c:
            return (await c.call_tool("recall", {"query": "which bridge carries the IoT VLAN"})).data
    assert "id=fxBridges" in asyncio.run(call())
