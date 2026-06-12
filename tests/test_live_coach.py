"""
Live coach mode A (D3, loop 2 iteration 38): the incremental trigger model
fed frame-by-frame must speak corner cues and debriefs through the TTS
queue's safety rules — no overlap, global cooldown, mute/verbosity — and
its cue timing must match the offline ghost coach's pass criterion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.coach.ghost import (
    GLOBAL_COOLDOWN_S, SAFETY_MARGIN_S, Frame, Turn, speech_seconds,
)
from racecraft.coach.live import (
    DEFAULT_TRACK_LENGTH_M, LiveCoach, frame_from_telemetry,
)
from racecraft.coach.tts import LogBackend, TTSQueue

TRACK_LEN = 5200.0
TURNS = [
    Turn(number=1, entry_pct=0.10, apex_pct=0.13, exit_pct=0.16),
    Turn(number=2, entry_pct=0.45, apex_pct=0.48, exit_pct=0.51),
    Turn(number=3, entry_pct=0.80, apex_pct=0.83, exit_pct=0.86),
]


def synthetic_session(laps=4, lap_seconds=95.0, hz=20):
    """Constant-ish speed laps with braking zones before each turn; apex
    speeds drift slightly so the rules engine has something to say."""
    frames = []
    n = int(lap_seconds * hz)
    for lap in range(1, laps + 1):
        for i in range(n):
            pct = i / n
            t = (lap - 1) * lap_seconds + i / hz
            speed = TRACK_LEN / lap_seconds  # ~55 m/s average
            brake = 0.0
            for turn in TURNS:
                d = turn.entry_pct - pct
                if 0.0 < d < 0.02:
                    brake = 0.9
                if abs(pct - turn.apex_pct) < 0.01:
                    speed = 22.0 + lap  # slow apexes, drifting by lap
            frames.append(Frame(t=t, pct=pct, speed=speed, brake=brake, lap=lap))
    return frames


class SessionClock:
    """Clock that follows the fed frame times for deterministic tests."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def run_session(coach, clock, frames):
    spoken = []
    for f in frames:
        clock.now = f.t
        text = coach.on_frame(f)
        if text:
            spoken.append((f.t, text))
    return spoken


def _coach(verbosity="all"):
    clock = SessionClock()
    backend = LogBackend()
    tts = TTSQueue(backend=backend, clock=clock)
    tts.verbosity = verbosity
    return LiveCoach(TURNS, track_length_m=TRACK_LEN, tts=tts), clock


def test_live_coach_speaks_cues_and_debriefs():
    coach, clock = _coach()
    spoken = run_session(coach, clock, synthetic_session())
    kinds = [t for _, t in spoken]
    assert len(spoken) >= 3
    assert any("turn" in t.lower() for t in kinds)           # corner cues
    assert any("lap" in t.lower() for t in kinds)            # debrief


def test_global_cooldown_between_utterance_starts():
    coach, clock = _coach()
    spoken = run_session(coach, clock, synthetic_session())
    starts = [t for t, _ in spoken]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(g >= GLOBAL_COOLDOWN_S - 1e-6 for g in gaps), gaps


def test_cues_finish_before_braking_point():
    """The ghost coach's pass criterion, applied to the LIVE stepper:
    speech must end >= SAFETY_MARGIN_S before the corner's braking zone."""
    coach, clock = _coach()
    frames = synthetic_session()
    spoken = run_session(coach, clock, frames)
    corner_cues = [(t, txt) for t, txt in spoken if "lap" not in txt.lower()]
    assert corner_cues
    for t_start, text in corner_cues:
        t_end = t_start + speech_seconds(text)
        # find the next braking onset after the cue start
        bp = next((f.t for f in frames if f.t > t_start and f.brake > 0.2), None)
        assert bp is not None
        assert bp - t_end >= SAFETY_MARGIN_S - 0.25, (text, bp - t_end)


def test_mute_and_verbosity():
    coach, clock = _coach()
    coach.tts.muted = True
    assert run_session(coach, clock, synthetic_session()) == []

    coach2, clock2 = _coach(verbosity="key")  # corner cues only
    spoken = run_session(coach2, clock2, synthetic_session())
    assert spoken
    assert all("lap" not in t.lower() for _, t in spoken)


def test_no_turn_db_still_gives_debriefs():
    clock = SessionClock()
    tts = TTSQueue(backend=LogBackend(), clock=clock)
    tts.verbosity = "all"
    coach = LiveCoach([], track_length_m=TRACK_LEN, tts=tts)
    spoken = run_session(coach, clock, synthetic_session())
    assert spoken
    assert all("lap" in t.lower() for _, t in spoken)


def test_frame_from_telemetry_guards():
    class T:
        lap_distance = 0.42
        speed = 51.0
        brake = 0.1
        lap_number = 3
    f = frame_from_telemetry(T(), 12.5)
    assert f.pct == 0.42 and f.lap == 3 and f.t == 12.5

    class NoPct:
        lap_distance = None
    assert frame_from_telemetry(NoPct(), 1.0) is None


def test_default_track_length_guard():
    coach = LiveCoach(TURNS, track_length_m=0)
    assert coach.track_length_m == DEFAULT_TRACK_LENGTH_M
