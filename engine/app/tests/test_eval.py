import json

import httpx

from eval import evaluate, passes, score


def test_score_metrics():
    results = [
        {"expect": ["a"], "hits": ["x", "a"], "ms": 10},
        {"expect": ["b"], "hits": ["b"], "ms": 20},
        {"expect": ["c"], "hits": [], "ms": 30},
        {"expect": "none", "hits": [], "ms": 40},
        {"expect": "none", "hits": ["z"], "ms": 400},
    ]
    m = score(results)
    assert m["hit@3"] == 2 / 3 and m["mrr"] == (0.5 + 1 + 0) / 3
    assert m["silence"] == 0.5 and m["false_silence"] == 1 / 3
    assert m["p50_ms"] == 30 and m["p95_ms"] == 400 and m["cases"] == 5


def test_passes_thresholds():
    assert passes({"hit@3": 0.8, "silence": 0.8, "p95_ms": 299})
    assert not passes({"hit@3": 0.79, "silence": 1, "p95_ms": 10})
    assert not passes({"hit@3": 1, "silence": 1, "p95_ms": 300})


def test_evaluate_posts_each_case():
    seen = []

    def handler(request):
        body = json.loads(request.read())
        seen.append((request.headers["authorization"], body))
        return httpx.Response(200, json={"context": "x", "hits": ["a"] if body["prompt"] == "alpha" else []})

    cases = [{"query": "alpha", "expect": ["a"]}, {"query": "beta", "cwd": "/r/x", "expect": "none"}]
    m, results = evaluate("http://e", "tok", cases, transport=httpx.MockTransport(handler))
    assert m["hit@3"] == 1 and m["silence"] == 1
    assert seen[0] == ("Bearer tok", {"prompt": "alpha", "session_id": None, "cwd": None})
    assert seen[1][1]["cwd"] == "/r/x"
    assert [r["hits"] for r in results] == [["a"], []]
