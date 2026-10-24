"""Live tests drive the dev stack from docker-compose.yaml (run-tests.sh starts it).

The targets are pinned to the in-repo fixture and never read from the environment: the
plugin exports TRILIUM_* for a real instance into every shell, and honouring them would
point these mutating tests at a production Trilium.
"""

from pathlib import Path

import httpx
import pytest

ENGINE = "http://localhost:9191"
TRILIUM = "http://localhost:9190/etapi"
RECALL_TOKEN = "dev-only-recall-token"
ETAPI_TOKEN = (Path(__file__).parents[3] / "fixture" / "etapi.token").read_text().strip()


def _reachable() -> bool:
    try:
        return httpx.get(f"{ENGINE}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def pytest_collection_modifyitems(items):
    if not _reachable():
        skip = pytest.mark.skip(reason=f"dev stack not running at {ENGINE} (use run-tests.sh)")
        for item in items:
            if "/live/" in str(item.fspath) and "test_live_target" not in str(item.fspath):
                item.add_marker(skip)


@pytest.fixture
def engine():
    with httpx.Client(base_url=ENGINE, headers={"Authorization": f"Bearer {RECALL_TOKEN}"}, timeout=30) as c:
        yield c


@pytest.fixture
def trilium():
    with httpx.Client(base_url=TRILIUM, headers={"Authorization": ETAPI_TOKEN}, timeout=30) as c:
        yield c
