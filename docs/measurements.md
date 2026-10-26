# Measurements

Measured with the engine's own evaluation command (`eval.py`) on 0.5.0, 2026-10-26. Each case is a
question plus the note that should answer it, or `none` for questions the notes can't answer.

## On a real Trilium

The author's Trilium: 279 notes in 860 sections, mostly an LLM wiki about a homelab, tools and
paperwork, in German and English. 49 cases: 37 answerable, 12 unanswerable. The questions stay
private, because they describe the notes.

| | |
|---|---|
| **hit@3**: the right note among the first three | **0.86** (32 of 37) |
| **MRR**: how high the right note ranks (1 = always first) | **0.82** |
| **silence**: nothing returned for an unanswerable question | **0.92** (11 of 12) |
| **false silence**: nothing returned although a note answers it | **0.03** (1 of 37) |
| **latency** per lookup, p50 / p95 | **15–16 ms / 19–33 ms** (three runs) |

The engine runs in a homelab container with a 600 MB memory limit and no GPU.

### Compared with Trilium's own search

The same 49 cases, answered with Trilium's full-text search through its MCP server (measured
2026-10-26):

| | hit@3 | calls per question | silent when nothing fits |
|---|---|---|---|
| **trilium-recall** | **0.86** | 1 | 92 % of the time |
| Trilium search, the question as one query | 0.41 | 1 | not measured |
| Trilium search, one query per keyword | 0.78 | 5.3 on average | never |

Trilium's search needs the exact words of the note. Recall also finds paraphrases and questions
asked in the other language, and it says nothing when nothing fits, instead of returning whatever
contains a keyword.

## On the public fixture

`engine/fixture/` holds a disposable Trilium (Trilium's demo notes plus a small synthetic wiki) and
`engine/eval/fixture-cases.yaml` 17 cases for it: 12 answerable, 5 unanswerable. CI runs them on
every change. These are the numbers anyone can reproduce:

| | |
|---|---|
| hit@3 | 0.83 (10 of 12) |
| MRR | 0.83 |
| silence | 1.0 (5 of 5) |
| false silence | 0.17 (2 of 12) |
| latency p50 / p95 | 8.5–9.4 ms / 11.5–17.7 ms (three runs) |

```bash
cd engine
docker compose up -d --build --wait      # fixture Trilium on :9190, engine on :9191
uv run python app/eval.py --url http://localhost:9191 --token dev-only-recall-password \
  --cases eval/fixture-cases.yaml --verbose
docker compose stop
```

`./run-tests.sh` does the same with the full test suite and resets the fixture's database afterwards.

## Measure your own


Write a YAML file of questions with the pages that should
answer them, plus some your notes cannot answer:

```yaml
- {query: "how are the guests backed up?", expect: [<noteId>]}
- {query: "Wie melde ich ein Gewerbe an?", expect: [<noteId>]}
- {query: "best sourdough hydration", expect: none}
```

and run it against the engine:

```bash
docker compose exec trilium-recall python eval.py --url http://localhost:8082 \
  --token "$RECALL_LOGIN_PASSWORD" --cases /data/cases.yaml --verbose
```

It reports hit@3 (the right page among the first three), silence on unanswerable questions and
latency. Keep your questions private: they describe your notes.
