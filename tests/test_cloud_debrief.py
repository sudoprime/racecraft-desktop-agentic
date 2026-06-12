"""
Cloud debrief, mode B (D4, loop 2 iteration 41): lap completion routes the
summary through the hook; the cloud text is spoken on success and the
local template on ANY failure; the hook never blocks the frame path.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.coach.debrief import fetch_debrief, make_cloud_debrief_hook
from racecraft.coach.live import LiveCoach
from racecraft.coach.tts import LogBackend, TTSQueue
from tests.test_live_coach import SessionClock, TURNS, TRACK_LEN, synthetic_session


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, resp=None, exc=None, delay=0.0):
        self.resp, self.exc, self.delay = resp, exc, delay
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.resp


def test_fetch_debrief_success_and_failures():
    async def run():
        ok = FakeClient(FakeResp(200, {"text": " Box this lap. "}))
        assert await fetch_debrief(ok, "http://x", "tok", {"lap_time": 90}) == "Box this lap."
        assert ok.calls[0][0].endswith("/api/streaming/coach/debrief")

        assert await fetch_debrief(FakeClient(FakeResp(403)), "http://x", "t", {}) is None
        assert await fetch_debrief(FakeClient(FakeResp(200, {"text": ""})), "http://x", "t", {}) is None
        assert await fetch_debrief(FakeClient(exc=RuntimeError("net")), "http://x", "t", {}) is None
        # timeout path
        slow = FakeClient(FakeResp(200, {"text": "late"}), delay=8.0)
        import racecraft.coach.debrief as d
        old = d.DEBRIEF_TIMEOUT_S
        d.DEBRIEF_TIMEOUT_S = 0.05
        try:
            assert await fetch_debrief(slow, "http://x", "t", {}) is None
        finally:
            d.DEBRIEF_TIMEOUT_S = old
    asyncio.run(run())


def _coach_with_hook(client):
    clock = SessionClock()
    tts = TTSQueue(backend=LogBackend(), clock=clock)
    tts.verbosity = "all"
    hook = make_cloud_debrief_hook(tts, client, "http://x", lambda: "tok")
    coach = LiveCoach(TURNS, track_length_m=TRACK_LEN, tts=tts, debrief_hook=hook)
    return coach, clock, tts


def test_lap_completion_speaks_cloud_text():
    async def run():
        client = FakeClient(FakeResp(200, {"text": "Great lap, brake later into four."}))
        coach, clock, tts = _coach_with_hook(client)
        for f in synthetic_session(laps=3):
            clock.now = f.t
            coach.on_frame(f)
            await asyncio.sleep(0)  # let hook tasks run
        await asyncio.sleep(0.05)
        spoken = [t for _, t in tts.backend.spoken]
        assert any("Great lap" in t for t in spoken)
        # the summary the cloud saw carries lap_time
        assert client.calls and client.calls[0][1]["summary"]["lap_time"] > 30
    asyncio.run(run())


def test_cloud_failure_falls_back_to_template():
    async def run():
        client = FakeClient(FakeResp(502))
        coach, clock, tts = _coach_with_hook(client)
        for f in synthetic_session(laps=3):
            clock.now = f.t
            coach.on_frame(f)
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        spoken = [t for _, t in tts.backend.spoken]
        assert any("lap" in t.lower() for t in spoken)      # template debrief
        assert not any("Great lap" in t for t in spoken)
    asyncio.run(run())


def test_hook_without_event_loop_speaks_fallback():
    tts = TTSQueue(backend=LogBackend(), clock=lambda: 1000.0)
    tts.verbosity = "all"
    hook = make_cloud_debrief_hook(tts, FakeClient(FakeResp(200, {"text": "x"})),
                                   "http://x", lambda: "tok")
    hook({"lap_time": 91.0}, "template line about the lap")
    assert tts.backend.spoken and "template" in tts.backend.spoken[0][1]
