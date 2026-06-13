"""Remote log + crash reporting (platform loop 4, M part 2).

Pins the non-negotiables: emit() never blocks and the bounded queue
drops oldest instead of growing; the worker POSTs the right batch shape;
crashes build a correct payload; the token-getter attaches auth; and a
dead endpoint never raises into the app.
"""
import logging
import time
from unittest.mock import MagicMock

import pytest

import racecraft.remote_log as rl
from racecraft.remote_log import RemoteLogHandler, report_crash, set_token_getter


@pytest.fixture(autouse=True)
def _reset_token():
    set_token_getter(lambda: None)
    yield
    set_token_getter(lambda: None)


def _handler_with_fake_client(monkeypatch, posts):
    # Build a handler but swap its httpx client for a recorder, and stop
    # the worker so we drive _post / _run deterministically.
    h = RemoteLogHandler("http://api.test", flush_interval=0.05)
    h._stop.set()
    h._worker.join(timeout=2)

    fake = MagicMock()
    fake.post.side_effect = lambda url, headers=None, json=None: posts.append(
        {"url": url, "headers": headers, "json": json})
    h._client = fake
    return h


def test_emit_enqueues_and_post_sends_batch(monkeypatch):
    posts = []
    h = _handler_with_fake_client(monkeypatch, posts)
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", None, None)
    h.emit(rec)
    batch = h._drain_batch()
    h._post(batch)
    assert len(posts) == 1
    body = posts[0]["json"]
    assert body["os"] and body["app_version"]
    assert body["entries"][0]["level"] == "error"
    assert body["entries"][0]["message"] == "boom"
    h.close()


def test_bounded_queue_drops_oldest_never_blocks(monkeypatch):
    posts = []
    h = _handler_with_fake_client(monkeypatch, posts)
    # tiny queue
    import queue
    h._q = queue.Queue(maxsize=3)
    for i in range(50):  # far more than maxsize — must not block/raise
        h.emit(logging.LogRecord("x", logging.ERROR, __file__, 1, f"m{i}",
                                 None, None))
    assert h._q.qsize() == 3
    # the survivors are the NEWEST
    msgs = [h._q.get_nowait()["message"] for _ in range(3)]
    assert msgs == ["m47", "m48", "m49"]
    h.close()


def test_token_getter_attaches_auth(monkeypatch):
    posts = []
    h = _handler_with_fake_client(monkeypatch, posts)
    set_token_getter(lambda: "tok-123")
    h.emit(logging.LogRecord("x", logging.WARNING, __file__, 1, "w", None, None))
    h._post(h._drain_batch())
    assert posts[0]["headers"]["Authorization"] == "Bearer tok-123"
    h.close()


def test_dead_endpoint_never_raises(monkeypatch):
    posts = []
    h = _handler_with_fake_client(monkeypatch, posts)
    h._client.post.side_effect = ConnectionError("backend down")
    # must swallow
    h._post([{"level": "error", "message": "x"}])
    h.close()


def test_report_crash_builds_payload(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)

    monkeypatch.setattr(rl.httpx, "Client", FakeClient)
    set_token_getter(lambda: "tok-9")
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys
        report_crash(*sys.exc_info(), "http://api.test",
                     context={"where": "test"})
    assert captured["url"].endswith("/api/desktop/crash")
    assert captured["headers"]["Authorization"] == "Bearer tok-9"
    body = captured["json"]
    assert body["exc_type"] == "ValueError"
    assert body["message"] == "kaboom"
    assert "ValueError: kaboom" in body["traceback"]
    assert body["context"] == {"where": "test"}


def test_report_crash_swallows_post_errors(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): raise ConnectionError("down")
    monkeypatch.setattr(rl.httpx, "Client", FakeClient)
    # must not raise
    try:
        raise RuntimeError("x")
    except RuntimeError:
        import sys
        report_crash(*sys.exc_info(), "http://api.test")


def test_install_sets_crash_hooks_without_handler_when_disabled():
    import sys
    before = sys.excepthook
    h = rl.install_remote_logging("http://api.test", enabled=False)
    assert h is None                       # no log stream
    assert sys.excepthook is not before    # but crash hook installed
    sys.excepthook = before                # restore for other tests
