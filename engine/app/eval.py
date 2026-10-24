"""Score a running recall engine against a YAML file of cases.

    python app/eval.py --url http://localhost:9191 --token TOKEN --cases eval/fixture-cases.yaml [--enforce]

A case is {query, cwd?, expect: [noteId, ...] | none}. Prints one JSON object of metrics; with
--enforce, exits 1 below the v1 targets (hit@3 >= 0.8, silence >= 0.8, p95 < 300 ms).
"""

import argparse
import json
import math
import sys
import time

import httpx
import yaml

TARGETS = {"hit@3": 0.8, "silence": 0.8, "p95_ms": 300}


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))] if ordered else 0.0


def score(results: list[dict]) -> dict:
    answerable = [r for r in results if r["expect"] != "none"]
    unanswerable = [r for r in results if r["expect"] == "none"]
    reciprocal, hits = [], 0
    for r in answerable:
        ranks = [i for i, h in enumerate(r["hits"][:3], 1) if h in r["expect"]]
        hits += bool(ranks)
        reciprocal.append(1 / ranks[0] if ranks else 0.0)
    ms = [r["ms"] for r in results]
    return {
        "cases": len(results),
        "hit@3": hits / len(answerable) if answerable else 1.0,
        "mrr": sum(reciprocal) / len(answerable) if answerable else 1.0,
        "silence": sum(not r["hits"] for r in unanswerable) / len(unanswerable) if unanswerable else 1.0,
        "false_silence": sum(not r["hits"] for r in answerable) / len(answerable) if answerable else 0.0,
        "p50_ms": _percentile(ms, 0.5),
        "p95_ms": _percentile(ms, 0.95),
    }


def passes(metrics: dict) -> bool:
    return (metrics["hit@3"] >= TARGETS["hit@3"] and metrics["silence"] >= TARGETS["silence"]
            and metrics["p95_ms"] < TARGETS["p95_ms"])


def evaluate(url: str, token: str, cases: list[dict], transport: httpx.BaseTransport | None = None
             ) -> tuple[dict, list[dict]]:
    results = []
    with httpx.Client(base_url=url.rstrip("/"), transport=transport, timeout=30,
                      headers={"Authorization": f"Bearer {token}"}) as http:
        for case in cases:
            started = time.perf_counter()
            response = http.post("/recall", json={"prompt": case["query"], "session_id": None,
                                                  "cwd": case.get("cwd")})
            ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            results.append({"query": case["query"], "expect": case["expect"],
                            "hits": response.json().get("hits", []), "ms": round(ms, 1)})
    return score(results), results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--cases", required=True)
    p.add_argument("--enforce", action="store_true")
    p.add_argument("--verbose", action="store_true", help="also print every case's hits")
    args = p.parse_args()
    with open(args.cases) as f:
        cases = yaml.safe_load(f)
    metrics, results = evaluate(args.url, args.token, cases)
    if args.verbose:
        for r in results:
            mark = "ok " if (r["expect"] == "none") == (not r["hits"]) and (
                r["expect"] == "none" or set(r["hits"][:3]) & set(r["expect"])) else "BAD"
            print(f"{mark} {r['ms']:6.1f}ms {r['query'][:60]!r} → {r['hits']} (expect {r['expect']})")
    print(json.dumps(metrics))
    if args.enforce and not passes(metrics):
        sys.exit(1)


if __name__ == "__main__":
    main()
