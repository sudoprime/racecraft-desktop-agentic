"""SessionCore robustness + on-track gating (loop 4, D sprint).

A menu/garage frame passes the numeric validators but is not a live lap
and must not stream. A parser that raises must not drop the session.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from racecraft.session_core import SessionCore


def _telemetry(is_racing=True):
    t = MagicMock()
    t.is_racing = is_racing
    return t


def _parser(telemetry, valid=True, raises=False):
    p = MagicMock()
    if raises:
        p.parse.side_effect = RuntimeError("parser shape change")
    else:
        p.parse.return_value = telemetry
    p.validate_data.return_value = valid
    return p


def _streaming():
    s = MagicMock()
    s.add_frame = AsyncMock()
    return s


def test_offtrack_frames_are_not_streamed():
    s = _streaming()
    core = SessionCore(_parser(_telemetry(is_racing=False)), s)
    core.session_active = True
    assert asyncio.run(core.process_raw(b"x")) is None
    assert core.frames == 0
    assert core.frames_skipped_offtrack == 1
    s.add_frame.assert_not_awaited()


def test_ontrack_frames_stream_normally():
    s = _streaming()
    core = SessionCore(_parser(_telemetry(is_racing=True)), s)
    core.session_active = True
    asyncio.run(core.process_raw(b"x"))
    assert core.frames == 1
    assert core.frames_skipped_offtrack == 0
    s.add_frame.assert_awaited_once()


def test_parser_exception_does_not_drop_session():
    s = _streaming()
    core = SessionCore(_parser(None, raises=True), s)
    core.session_active = True
    # must not raise; frame skipped; session still active for the next frame
    assert asyncio.run(core.process_raw(b"x")) is None
    assert core.parse_errors == 1
    assert core.session_active is True
    s.add_frame.assert_not_awaited()


def test_invalid_frames_still_skipped():
    s = _streaming()
    core = SessionCore(_parser(_telemetry(), valid=False), s)
    core.session_active = True
    asyncio.run(core.process_raw(b"x"))
    assert core.frames == 0
    s.add_frame.assert_not_awaited()
