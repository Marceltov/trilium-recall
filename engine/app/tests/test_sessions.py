import time

from sessions import SessionMemory


def test_session_dedupe_five_prompts():
    m = SessionMemory()
    assert m.fresh("s", ["a", "b"]) == ["a", "b"]
    for _ in range(4):
        assert m.fresh("s", ["a", "b"]) == []
    assert m.fresh("s", ["b", "c"]) == ["c"]


def test_sessions_are_separate():
    m = SessionMemory()
    m.fresh("s1", ["a"])
    assert m.fresh("s2", ["a"]) == ["a"]


def test_no_session_id_records_nothing():
    m = SessionMemory()
    assert m.fresh(None, ["a"]) == ["a"] and m.fresh(None, ["a"]) == ["a"]


def test_session_expiry():
    m = SessionMemory(ttl_seconds=10)
    m.fresh("s", ["a"])
    m.sweep(now=time.time() + 11)
    assert m.fresh("s", ["a"]) == ["a"]


def test_activity_extends_session():
    m = SessionMemory(ttl_seconds=10)
    m.fresh("s", ["a"])
    m._seen["s"] = (time.time() - 8, m._seen["s"][1])
    m.fresh("s", ["b"])
    m.sweep(now=time.time() + 5)
    assert m.fresh("s", ["a"]) == []


def test_peek_does_not_record_until_record():
    m = SessionMemory()
    assert m.peek("s", ["a", "b"]) == ["a", "b"]
    assert m.peek("s", ["a", "b"]) == ["a", "b"]
    m.record("s", ["a"])
    assert m.peek("s", ["a", "b"]) == ["b"]
    assert m.peek(None, ["a"]) == ["a"]
