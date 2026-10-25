import asyncio
import time
from pathlib import Path

import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from eval import evaluate, passes
from tests.live.conftest import ENGINE, RECALL_PASSWORD

CASES = Path(__file__).parents[3] / "eval" / "fixture-cases.yaml"


def recall(engine, prompt, session_id=None):
    r = engine.post("/recall", json={"prompt": prompt, "session_id": session_id})
    r.raise_for_status()
    return r.json()


def wait_for(fn, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(1)
    return False


def test_first_build_complete(engine):
    body = engine.get("/health").json()
    assert body["status"] == "ok"
    assert body["instances"]["fixture"]["notes"] >= 17


def test_plumbing_archived_and_hidden_never_returned(engine):
    for prompt in ["zebra lock claim fixture-session seeding", "zebra iptables legacy rules", "Options ETAPI tokens"]:
        hits = recall(engine, prompt)["hits"]
        assert "fxLockClaim" not in hits and "fxArchived" not in hits
        assert not [h for h in hits if h.startswith("_")]


def test_edit_shows_up_after_a_poll(engine, trilium):
    trilium.put("/notes/fxPackliste/content", content="<ul><li>Regenschirm mit Okapi-Muster</li></ul>",
                headers={"Content-Type": "text/plain"}).raise_for_status()
    assert wait_for(lambda: "fxPackliste" in recall(engine, "Okapi Regenschirm")["hits"])


def test_label_change_does_not_bump_modified_but_reaches_index(engine, trilium):
    note = trilium.get("/notes/fxEtapi").json()
    before = note["utcDateModified"]
    status = next(a for a in note["attributes"] if a["name"] == "wikiStatus" and a["noteId"] == "fxEtapi")
    trilium.patch(f"/attributes/{status['attributeId']}", json={"value": "reviewed"}).raise_for_status()
    # Trilium 0.106: an attribute change leaves utcDateModified alone, so only the reconcile sees it.
    assert trilium.get("/notes/fxEtapi").json()["utcDateModified"] == before
    assert wait_for(lambda: "reviewed" in recall(engine, "where do I create an ETAPI token")["context"], 40)


def test_mcp_tool_over_http():
    async def call():
        transport = StreamableHttpTransport(f"{ENGINE}/mcp", headers={"Authorization": f"Bearer {RECALL_PASSWORD}"})
        async with Client(transport) as c:
            return (await c.call_tool("recall", {"query": "which bridge carries the IoT VLAN"})).data
    assert "id=fxBridges" in asyncio.run(call())


def test_fixture_eval_meets_targets():
    metrics, results = evaluate(ENGINE, RECALL_PASSWORD, yaml.safe_load(CASES.read_text()))
    bad = [r for r in results if (r["expect"] == "none") != (not r["hits"])
           or (r["expect"] != "none" and not set(r["hits"]) & set(r["expect"]))]
    assert passes(metrics), (metrics, bad)
