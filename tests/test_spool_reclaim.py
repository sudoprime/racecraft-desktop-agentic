"""Spool disk caps + crash recovery (loop 4, R14).

A crash leaves chunks under the OLD session_id; the next run gets a new
id and never drains them -> unbounded growth + permanent loss. Reclaim
bounds disk (age + byte cap, oldest-evicted); recovery resumes the
orphan's OWN session and uploads its chunks (never into a new session).
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from racecraft.streaming import StreamingClient


def _client(tmp_path, **env):
    import os
    for k, v in env.items():
        os.environ[k] = str(v)
    c = StreamingClient("http://api.test", MagicMock(),
                        spool_dir=str(tmp_path / "spool"))
    for k in env:
        os.environ.pop(k, None)
    return c


def _make_orphan(tmp_path, sid, n_chunks=2, mtime_days_ago=0.0, size=1000):
    d = tmp_path / "spool" / sid
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n_chunks):
        (d / f"chunk_{i:06d}.json.gz").write_bytes(b"x" * size)
    if mtime_days_ago:
        t = time.time() - mtime_days_ago * 86400
        import os
        for f in d.glob("*"):
            os.utime(f, (t, t))
        os.utime(d, (t, t))
    return d


def test_reclaim_deletes_aged_orphans(tmp_path):
    old = _make_orphan(tmp_path, "old-sess", mtime_days_ago=10)
    fresh = _make_orphan(tmp_path, "fresh-sess", mtime_days_ago=1)
    # constructor calls reclaim_spool (default max age 7d)
    _client(tmp_path)
    assert not old.exists(), "10-day-old orphan should be reclaimed"
    assert fresh.exists(), "1-day-old orphan should survive the age cut"


def test_reclaim_evicts_oldest_over_byte_cap(tmp_path):
    # three 5KB orphans, cap at 8KB -> oldest two evicted
    a = _make_orphan(tmp_path, "a", n_chunks=1, size=5000, mtime_days_ago=3)
    b = _make_orphan(tmp_path, "b", n_chunks=1, size=5000, mtime_days_ago=2)
    c = _make_orphan(tmp_path, "c", n_chunks=1, size=5000, mtime_days_ago=1)
    _client(tmp_path, RACECRAFT_SPOOL_MAX_BYTES=8000)
    assert not a.exists() and not b.exists()  # oldest evicted
    assert c.exists()                          # newest kept


def test_recovery_resumes_orphan_session_and_uploads(tmp_path):
    orphan = _make_orphan(tmp_path, "crashed-sess", n_chunks=3)
    c = _client(tmp_path)
    calls = []

    async def fake_authed_post(url, **kw):
        calls.append((url, kw))
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"analysis_id": "an-1"}
        r.raise_for_status.return_value = None
        return r
    c._authed_post = fake_authed_post

    n = asyncio.run(c.recover_orphan_sessions())
    assert n == 1
    assert not orphan.exists()  # drained + removed
    urls = [u for u, _ in calls]
    assert any("session/resume" in u for u in urls)
    assert sum("chunk/upload" in u for u in urls) == 3   # all chunks
    assert any("session/end" in u for u in urls)
    assert any("session/analyze" in u for u in urls)
    # chunks uploaded to the ORPHAN's session id, not a new one
    up = [kw for u, kw in calls if "chunk/upload" in u]
    assert all(kw["data"]["session_id"] == "crashed-sess" for kw in up)


def test_recovery_leaves_unresumable_orphan_for_reclaim(tmp_path):
    orphan = _make_orphan(tmp_path, "dead-sess", n_chunks=2)
    c = _client(tmp_path)

    async def fake_authed_post(url, **kw):
        r = MagicMock()
        r.status_code = 400  # not resumable (session gone)
        return r
    c._authed_post = fake_authed_post

    n = asyncio.run(c.recover_orphan_sessions())
    assert n == 0
    assert orphan.exists()  # left in place; reclaim's age/byte cap handles it


def test_reclaim_never_touches_active_session(tmp_path):
    c = _client(tmp_path)
    c.session_id = "active-1"
    active = _make_orphan(tmp_path, "active-1", mtime_days_ago=30)
    c.reclaim_spool()  # would delete by age, but it's the active session
    assert active.exists()
