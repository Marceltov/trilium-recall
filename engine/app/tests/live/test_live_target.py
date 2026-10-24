"""Guard: the live tests must never become configurable from the environment."""

from pathlib import Path

from tests.live import conftest

LIVE = Path(__file__).parent


def test_targets_are_pinned_to_the_fixture():
    assert conftest.ENGINE == "http://localhost:9191"
    assert conftest.TRILIUM == "http://localhost:9190/etapi"


def test_live_tests_never_read_the_environment():
    for f in LIVE.glob("*.py"):
        source = f.read_text()
        if f.name != "test_live_target.py":
            assert "os.environ" not in source and "getenv" not in source, f.name
