"""Chunk-loss elimination in StreamingClient (platform loop 3, T3).

The old _flush popped the buffer THEN uploaded: one failed POST silently
destroyed ~10s of telemetry and left a chunk-number gap. Now: bounded
retries, disk spool on failure (survives crashes), oldest-first drain on
later flushes and a full drain at session end, and 401→refresh→retry on
every authenticated call.
"""
import asyncio
import gzip
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from racecraft.streaming import StreamingClient


class FakeAuth:
    def __init__(self):
        self.bearer_token = "tok-1"
        self.refresh_calls = 0

    async def refresh(self):
        self.refresh_calls += 1
        self.bearer_token = f"tok-{self.refresh_calls + 1}"
        return True


def _resp(status=200):
    r = MagicMock()
    r.status_code = status
    if status >= 400:
        import httpx
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status}", request=MagicMock(), response=r)
    else:
        r.raise_for_status.return_value = None
    return r


def make_client(tmp_path, post_results):
    """post_results: list of status codes / exceptions consumed per POST."""
    auth = FakeAuth()
    c = StreamingClient("http://api.test", auth, samples_per_chunk=2,
                        spool_dir=str(tmp_path / "spool"), upload_attempts=2)
    c.session_id = "sess-1"
    seq = iter(post_results)
    calls = []

    async def fake_post(url, headers=None, **kw):
        calls.append({"url": url, "headers": headers, **kw})
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return _resp(item)

    c.client = MagicMock()
    c.client.post = fake_post
    return c, calls, auth


def _fill(c, n=2):
    for i in range(n):
        c._buffer.append({"i": i})


def test_failed_upload_spools_to_disk_not_oblivion(tmp_path):
    import httpx
    c, calls, _ = make_client(tmp_path, [
        httpx.ConnectError("down"), httpx.ConnectError("down")])  # 2 attempts
    _fill(c)
    asyncio.run(c._flush())

    spooled = list((tmp_path / "spool" / "sess-1").glob("chunk_*.json.gz"))
    assert len(spooled) == 1, "failed chunk must be spooled, not dropped"
    data = json.loads(gzip.decompress(spooled[0].read_bytes()))
    assert data == [{"i": 0}, {"i": 1}], "spooled payload is the full chunk"
    assert c.chunks_uploaded == 0


def test_spooled_chunk_drains_on_next_flush(tmp_path):
    import httpx
    c, calls, _ = make_client(tmp_path, [
        httpx.ConnectError("down"), httpx.ConnectError("down"),  # chunk 0 fails
        200,                                                      # chunk 1 ok
        200,                                                      # spooled chunk 0 ok
    ])
    _fill(c)
    asyncio.run(c._flush())   # chunk 0 -> spool; same-flush drain retries it OK
    _fill(c)
    asyncio.run(c._flush())   # chunk 1 up

    assert c.chunks_uploaded == 2
    assert list((tmp_path / "spool" / "sess-1").glob("*")) == []
    # the drained upload re-used the ORIGINAL chunk number (call 3 of 4)
    assert calls[2]["data"]["chunk_number"] == "0"
    assert calls[3]["data"]["chunk_number"] == "1"


def test_transient_failure_retries_within_flush(tmp_path):
    import httpx
    c, calls, _ = make_client(tmp_path, [httpx.ConnectError("blip"), 200])
    _fill(c)
    asyncio.run(c._flush())
    assert c.chunks_uploaded == 1
    assert not (tmp_path / "spool" / "sess-1").exists() or \
        list((tmp_path / "spool" / "sess-1").glob("*")) == []


def test_401_triggers_refresh_and_retry(tmp_path):
    c, calls, auth = make_client(tmp_path, [401, 200])
    _fill(c)
    asyncio.run(c._flush())
    assert auth.refresh_calls == 1
    assert c.chunks_uploaded == 1
    # second attempt carried the refreshed token
    assert calls[-1]["headers"]["Authorization"] == "Bearer tok-2"


def test_end_session_drains_fully(tmp_path):
    import httpx
    # upload_attempts=1 keeps the call sequence deterministic:
    # flush N: new chunk fails (1 post) + drain retries chunk 0, fails (1 post)
    fails = [httpx.ConnectError("down")] * 6
    c, calls, auth = make_client(tmp_path, fails + [200, 200, 200, 200])
    c.upload_attempts = 1
    for _ in range(3):
        _fill(c)
        asyncio.run(c._flush())
    spool = tmp_path / "spool" / "sess-1"
    assert len(list(spool.glob("*"))) == 3

    asyncio.run(c.end_session())  # drains all 3 spooled + posts session/end

    assert list(spool.glob("*")) == []
    assert c.chunks_uploaded == 3
    assert calls[-1]["url"].endswith("/api/streaming/session/end")
