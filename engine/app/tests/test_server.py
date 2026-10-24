import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from config import Config, InstanceConfig
from embed import HashEmbedder
from rank import RankParams
from server import Engine, build_app, build_error_app, build_mcp
from tests.fake_etapi import build_world

OK = {"Authorization": "Bearer secret"}
BAD = {"Authorization": "Bearer wrong"}
QUERY = "proxmox swap OOM killer"


def make_engine(tmp_path, worlds):
    config = Config(token="secret", instances=[InstanceConfig(n, f"http://{n}/etapi", "e") for n in worlds],
                    data_dir=tmp_path)
    engine = Engine(config, HashEmbedder(), transports={n: w.etapi.transport() for n, w in worlds.items()})
    engine.params = RankParams(min_cos=0.2)
    engine.sync_all_once()
    return engine


@pytest.fixture
def world():
    return build_world()


@pytest.fixture
def engine(tmp_path, world):
    return make_engine(tmp_path, {"marcel": world})


@pytest.fixture
def client(engine):
    with TestClient(build_app(engine, background=False)) as c:
        yield c


def test_health_open_recall_needs_token(client):
    assert client.get("/health").status_code == 200
    assert client.post("/recall", json={"prompt": "x"}).status_code == 401
    assert client.post("/recall", json={"prompt": "x"}, headers=BAD).status_code == 401
    assert client.post("/mcp/", json={}).status_code == 401


def test_health_body(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["instances"]["marcel"]["notes"] == 10 and body["version"]


def test_recall_returns_context(client):
    r = client.post("/recall", json={"prompt": QUERY, "session_id": "s", "cwd": "/root/x"}, headers=OK).json()
    assert r["context"].startswith("Wiki recall (marcel)") and r["hits"] and "ms" in r


def test_recall_dedupes_per_session(client):
    body = {"prompt": QUERY, "session_id": "s"}
    assert client.post("/recall", json=body, headers=OK).json()["hits"]
    assert client.post("/recall", json=body, headers=OK).json()["context"] == ""


def test_skip_reported(client):
    assert client.post("/recall", json={"prompt": "ok"}, headers=OK).json() == {"context": "", "skipped": "confirmation"}


def test_bad_body_is_400(client):
    assert client.post("/recall", content=b"not json", headers=OK).status_code == 400
    assert client.post("/recall", json={"prompt": 5}, headers=OK).status_code == 400


def test_degraded_when_trilium_down(client, engine, world):
    world.fail = True
    engine.poll_once()
    assert client.get("/health").json()["status"] == "degraded"
    assert client.post("/recall", json={"prompt": QUERY}, headers=OK).json()["hits"]


def test_starting_before_first_sync(tmp_path, world):
    config = Config(token="secret", instances=[InstanceConfig("marcel", "http://m/etapi", "e")], data_dir=tmp_path)
    engine = Engine(config, HashEmbedder(), transports={"marcel": world.etapi.transport()})
    with TestClient(build_app(engine, background=False)) as c:
        assert c.get("/health").json()["status"] == "starting"


async def test_mcp_tool(engine):
    async with Client(build_mcp(engine)) as mcp:
        tools = await mcp.list_tools()
        assert [t.name for t in tools] == ["recall"] and "on your own" in tools[0].description
        out = await mcp.call_tool("recall", {"query": QUERY})
        assert out.data.startswith("Wiki recall (marcel)")
        none = await mcp.call_tool("recall", {"query": "sourdough hydration"})
        assert none.data == "Nothing relevant in the wiki for this query."


def test_two_instances_merge(tmp_path):
    a, b = build_world(), build_world()
    b.etapi.set_content(b.wiki_page, "<p>proxmox swap OOM killer on the bille box</p>")
    engine = make_engine(tmp_path, {"marcel": a, "bille": b})
    hits = engine.recall(QUERY)
    assert {h.instance for h in hits} == {"marcel", "bille"}
    assert {h.instance for h in engine.recall(QUERY, instance="bille")} == {"bille"}
    with TestClient(build_app(engine, background=False)) as c:
        text = c.post("/recall", json={"prompt": QUERY}, headers=OK).json()["context"]
    assert text.startswith("Wiki recall —") and "@bille" in text


def test_error_app_reports_message():
    with TestClient(build_error_app("RECALL_TOKEN is not set")) as c:
        r = c.get("/health")
        assert r.status_code == 503 and r.json() == {"status": "error", "error": "RECALL_TOKEN is not set"}
        assert c.post("/recall", json={"prompt": "x"}).status_code == 503


async def test_sync_loop_survives_a_crash_in_the_first_sync(engine):
    import asyncio
    calls = []

    def boom():
        raise RuntimeError("sqlite exploded")

    engine.sync_all_once = boom
    engine.poll_once = lambda: calls.append("poll")
    engine.config.poll_seconds = 0.01
    task = asyncio.create_task(engine.run_sync_forever())
    await asyncio.sleep(0.3)
    task.cancel()
    assert calls, "the loop stopped after the first sync failed"


async def test_mcp_unknown_instance_is_named(engine):
    async with Client(build_mcp(engine)) as mcp:
        out = await mcp.call_tool("recall", {"query": QUERY, "instance": "nope"})
        assert out.data == "Unknown instance 'nope'. Configured: marcel."


def test_recall_only_remembers_what_was_shown(client, engine, monkeypatch):
    import server
    shown_ids = []
    real_fit = server.fit

    def one_hit_fit(hits, max_tokens=400):
        text, shown = real_fit(hits[:1], max_tokens)
        shown_ids.extend(h.note_id for h in shown)
        return text, shown

    monkeypatch.setattr(server, "fit", one_hit_fit)
    body = {"prompt": "proxmox swap OOM killer homelab hub summary article", "session_id": "s2"}
    first = client.post("/recall", json=body, headers=OK).json()
    assert first["hits"] == shown_ids[:1]
    monkeypatch.setattr(server, "fit", real_fit)
    second = client.post("/recall", json=body, headers=OK).json()
    assert shown_ids[0] not in second["hits"]
