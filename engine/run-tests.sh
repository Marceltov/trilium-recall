#!/usr/bin/env bash
#
# Run the recall-engine tests against a clean, disposable fixture.
#
# Flow: stop containers -> reset the seeded DB -> (re)build & start -> wait for the
# engine's first build -> run pytest -> stop containers -> reset the DB (EXIT trap,
# so it also happens when a test fails).
#
# The reset runs with Trilium stopped: overwriting document.db while SQLite has it
# open corrupts it. Extra arguments go to pytest:
#   ./run-tests.sh                    # unit + live
#   ./run-tests.sh app/tests/live -q  # live only
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

reset_db() {
  # Trilium's entrypoint chowns its data dir; hand it back when we're not root (CI runner).
  if [ -n "$(find fixture/trilium-data ! -user "$(id -u)" -print -quit)" ]; then
    docker compose run --rm --no-deps --user root --entrypoint chown trilium \
      -R "$(id -u):$(id -g)" /home/node/trilium-data
  fi
  git checkout -- fixture/trilium-data/
  rm -f fixture/trilium-data/document.db-wal fixture/trilium-data/document.db-shm
}

cleanup() {
  echo "== Teardown: stopping containers and resetting DB =="
  docker compose stop
  reset_db
}
trap cleanup EXIT

docker compose stop
reset_db
# --wait blocks until the engine's healthcheck reports "ok" (first build done).
docker compose up -d --build --wait --wait-timeout 300
uv run pytest "${@:-app/tests}"
