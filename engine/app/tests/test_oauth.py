"""OAuth login for /mcp (RECALL_BASE_URL set): the login page's password is RECALL_LOGIN_PASSWORD."""

import base64
import hashlib
import secrets

import httpx
import pytest
from starlette.testclient import TestClient

import oauth
from config import Config, InstanceConfig
from embed import HashEmbedder
from rank import RankParams
from server import Engine, build_app
from tests.fake_etapi import build_world

BASE = "http://localhost:8082"
PASSWORD = "secret"
REDIRECT = "http://localhost:9/cb"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(oauth, "FAILED_LOGIN_DELAY", 0)


def make_engine(data_dir, base_url=BASE):
    world = build_world()
    config = Config(password=PASSWORD, base_url=base_url, data_dir=data_dir,
                    instances=[InstanceConfig("marcel", "http://marcel/etapi", "e")])
    engine = Engine(config, HashEmbedder(), transports={"marcel": world.etapi.transport()})
    engine.params = RankParams(min_cos=0.2)
    engine.sync_all_once()
    return engine


@pytest.fixture
def client(tmp_path):
    with TestClient(build_app(make_engine(tmp_path), background=False), base_url=BASE) as c:
        yield c


def register(http, name="claude.ai"):
    r = http.post("/register", json={"client_name": name, "redirect_uris": [REDIRECT],
                                     "token_endpoint_auth_method": "none",
                                     "grant_types": ["authorization_code", "refresh_token"],
                                     "response_types": ["code"]})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def authorize(http, client_id):
    """Start a login; returns (pending id, PKCE verifier)."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = http.get("/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
                                       "code_challenge": challenge, "code_challenge_method": "S256", "state": "s"},
                 follow_redirects=False)
    assert r.status_code == 302, r.text
    return httpx.URL(r.headers["location"]).params["id"], verifier


def login(http, name="claude.ai"):
    """register -> authorize -> /login -> token; returns the token JSON plus client_id."""
    client_id = register(http, name)
    pending, verifier = authorize(http, client_id)
    r = http.post("/login", data={"id": pending, "password": PASSWORD}, follow_redirects=False)
    assert r.status_code == 302, r.text
    code = httpx.URL(r.headers["location"]).params["code"]
    r = http.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                  "client_id": client_id, "code_verifier": verifier})
    assert r.status_code == 200, r.text
    return {**r.json(), "client_id": client_id}


def mcp_status(http, token):
    return http.post("/mcp", json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"}).status_code


def test_discovery_names_the_public_url(client):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"].rstrip("/") == BASE
    assert meta["authorization_endpoint"] == f"{BASE}/authorize"
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == f"{BASE}/mcp"


def test_mcp_without_token_points_to_the_login(client):
    r = client.post("/mcp", json=INIT, headers=MCP_HEADERS)
    assert r.status_code == 401
    assert "resource_metadata" in r.headers["www-authenticate"]


def test_login_gives_access_to_mcp(client):
    tokens = login(client)
    assert tokens["access_token"].startswith("rcl_")
    assert mcp_status(client, tokens["access_token"]) == 200


def test_login_page_names_the_client_escaped(client):
    pending, _ = authorize(client, register(client, name="<script>x</script>"))
    page = client.get("/login", params={"id": pending})
    assert page.status_code == 200
    assert "&lt;script&gt;" in page.text and "<script>x" not in page.text
    assert page.headers["x-frame-options"] == "DENY"


def test_wrong_password_shows_the_form_again(client):
    pending, _ = authorize(client, register(client))
    r = client.post("/login", data={"id": pending, "password": "nope"}, follow_redirects=False)
    assert r.status_code == 401 and "Wrong password" in r.text and 'name="password"' in r.text


def test_too_many_wrong_passwords_end_the_login(client):
    pending, _ = authorize(client, register(client))
    for _ in range(oauth.MAX_LOGIN_ATTEMPTS):
        client.post("/login", data={"id": pending, "password": "nope"}, follow_redirects=False)
    r = client.post("/login", data={"id": pending, "password": PASSWORD}, follow_redirects=False)
    assert r.status_code == 400 and "location" not in r.headers


def test_login_link_works_once(client):
    pending, _ = authorize(client, register(client))
    assert client.post("/login", data={"id": pending, "password": PASSWORD}, follow_redirects=False).status_code == 302
    again = client.post("/login", data={"id": pending, "password": PASSWORD}, follow_redirects=False)
    assert again.status_code == 200 and "already completed" in again.text


def test_static_password_still_works(client):
    assert mcp_status(client, PASSWORD) == 200
    assert client.post("/recall", json={"prompt": "proxmox swap OOM killer"},
                       headers={"Authorization": f"Bearer {PASSWORD}"}).status_code == 200


def test_recall_endpoint_takes_only_the_static_password(client):
    tokens = login(client)
    r = client.post("/recall", json={"prompt": "x"}, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 401


def test_unknown_bearer_is_rejected(client):
    assert mcp_status(client, "rcl_made-up") == 401
    assert mcp_status(client, "wrong") == 401


def test_refresh_rotates_and_the_old_access_token_dies(client):
    tokens = login(client)
    r = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                    "client_id": tokens["client_id"]})
    assert r.status_code == 200
    assert mcp_status(client, r.json()["access_token"]) == 200
    assert mcp_status(client, tokens["access_token"]) == 401


def test_logins_survive_a_restart_and_are_stored_encrypted(tmp_path):
    with TestClient(build_app(make_engine(tmp_path), background=False), base_url=BASE) as first:
        tokens = login(first)
    stored = b"".join(p.read_bytes() for p in (tmp_path / "oauth").rglob("*") if p.is_file())
    assert stored and tokens["access_token"].encode() not in stored
    with TestClient(build_app(make_engine(tmp_path), background=False), base_url=BASE) as second:
        assert mcp_status(second, tokens["access_token"]) == 200


def test_without_base_url_there_is_no_login(tmp_path):
    with TestClient(build_app(make_engine(tmp_path, base_url=None), background=False), base_url=BASE) as c:
        assert c.get("/.well-known/oauth-authorization-server").status_code == 401
        assert c.post("/register", json={}).status_code == 401
        assert mcp_status(c, PASSWORD) == 200


def test_file_store_uses_threads_not_kernel_aio():
    # io_uring/linux-aio rings take locked kernel memory per store and Docker's seccomp blocks io_uring.
    import caio
    assert caio.AsyncioContext.__module__ == "caio.thread_aio_asyncio"
