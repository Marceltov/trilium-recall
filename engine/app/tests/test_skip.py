import pytest

from skip import should_skip


@pytest.mark.parametrize("p", ["/clear", "/superpowers:brainstorming foo", "ok", "Ja!", "go on", "and the other one?",
                               "", "   ", "danke 👍", "yes do it", "LGTM.", "mach weiter"])
def test_skips(p):
    assert should_skip(p)


@pytest.mark.parametrize("p", ["fix CT 115 swap", "vmbr0?", "Why is Trilium slow", "wie war das mit dem Gewerbe?",
                               "restart authentik", "ok so how do backups of trilium work again", "check the karakeep-sync"])
def test_recalls(p):
    assert should_skip(p) is None


def test_reasons():
    assert should_skip("/clear") == "slash"
    assert should_skip("ok") == "confirmation"
    assert should_skip("and that one?") == "short"
    assert should_skip("") == "empty"
