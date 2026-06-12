"""SessionCore (platform loop 3, T3 part 2): the Qt-free session
lifecycle both the tray app and headless drive. Pins frame routing
(parse → validate → stats → coach → stream), coach-failure isolation,
finish-once semantics, and local-only (no streaming) collection."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from racecraft.session_core import SessionCore


def _parser(valid=True):
    p = MagicMock()
    p.parse.side_effect = lambda raw: {"frame": raw}
    p.validate_data.return_value = valid
    return p


def _streaming():
    s = MagicMock()
    s.start_session = AsyncMock(return_value="sess-1")
    s.add_frame = AsyncMock()
    s.end_session = AsyncMock()
    s.submit_for_analysis = AsyncMock(return_value="aid-1")
    return s


def test_frame_path_streams_and_hooks():
    seen = []
    s = _streaming()
    core = SessionCore(_parser(), s, on_frame=seen.append)
    asyncio.run(core.start("iracing", "T", "C"))
    asyncio.run(core.process_raw({"n": 1}, track_length=4000.0))

    assert core.frames == 1
    assert seen == [{"frame": {"n": 1}}]
    s.add_frame.assert_awaited_once()


def test_invalid_frames_are_skipped():
    s = _streaming()
    core = SessionCore(_parser(valid=False), s)
    asyncio.run(core.start("iracing", "T", "C"))
    asyncio.run(core.process_raw({"n": 1}))
    assert core.frames == 0
    s.add_frame.assert_not_awaited()


def test_coach_failure_never_breaks_collection():
    s = _streaming()
    core = SessionCore(_parser(), s)
    core.coach = MagicMock()
    core.coach.on_frame.side_effect = RuntimeError("coach bug")
    asyncio.run(core.start("iracing", "T", "C"))
    asyncio.run(core.process_raw({"n": 1}))
    s.add_frame.assert_awaited_once()  # streaming unaffected


def test_upload_failure_is_swallowed_and_logged():
    s = _streaming()
    s.add_frame = AsyncMock(side_effect=ConnectionError("net"))
    core = SessionCore(_parser(), s)
    asyncio.run(core.start("iracing", "T", "C"))
    asyncio.run(core.process_raw({"n": 1}))  # must not raise
    assert core.frames == 1


def test_finish_runs_exactly_once():
    s = _streaming()
    core = SessionCore(_parser(), s)
    asyncio.run(core.start("iracing", "T", "C"))
    assert asyncio.run(core.finish("notes")) == "aid-1"
    assert asyncio.run(core.finish("notes")) is None
    s.end_session.assert_awaited_once()
    s.submit_for_analysis.assert_awaited_once_with("notes")


def test_local_only_collection_without_streaming():
    core = SessionCore(_parser(), None)
    assert asyncio.run(core.start("iracing", "T", "C")) is None
    assert not core.session_active
    asyncio.run(core.process_raw({"n": 1}))  # parses, hooks, no upload
    assert core.frames == 1
    assert asyncio.run(core.finish()) is None
