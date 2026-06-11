"""
Ghost-coach prototype tests (platform loop 2, D2).

Pin the REALTIME_COACH.md pass criterion and the timing rules the
prototype's first runs taught us: cues fire from text length (longer =
earlier), all cues finish >= SAFETY_MARGIN_S before the braking point,
cooldowns hold, and the rules engine reacts to the session baseline.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.coach.ghost import (
    GhostCoach, RulesEngine, Turn, SAFETY_MARGIN_S, GLOBAL_COOLDOWN_S,
    speech_seconds, synthetic_session, timing_report,
)


@pytest.fixture(scope="module")
def replayed():
    turns, frames = synthetic_session(laps=4)
    coach = GhostCoach(turns)
    return coach.replay(frames)


class TestPassCriterion:
    def test_all_corner_cues_finish_before_braking(self, replayed):
        report = timing_report(replayed)
        assert report["corner_cues"] >= 1
        assert report["all_cues_in_time"] is True
        assert report["min_margin_s"] >= SAFETY_MARGIN_S

    def test_slow_corner_produces_a_brake_later_cue_next_lap(self, replayed):
        corner = [c for c in replayed if c.kind == "corner"]
        # lap 3 plants a slow T4 -> the cue must come on lap 4, about T4
        assert any(c.lap == 4 and c.turn == 4 and "brake later" in c.text
                   for c in corner)

    def test_debrief_every_completed_lap(self, replayed):
        debriefs = [c for c in replayed if c.kind == "debrief"]
        assert len(debriefs) == 3  # laps 1-3 complete; lap 4 ends the data
        assert "benchmark" in debriefs[0].text


class TestTimingRules:
    def test_longer_text_fires_earlier(self):
        short, long_ = "brake later", "turn four: brake noticeably later and carry the speed"
        assert speech_seconds(long_) > speech_seconds(short)

    def test_no_overlapping_speech(self, replayed):
        spoken = sorted(replayed, key=lambda c: c.t_start)
        for a, b in zip(spoken, spoken[1:]):
            assert b.t_start >= a.t_end - 1e-6

    def test_global_cooldown_between_corner_cues(self, replayed):
        corner = sorted((c for c in replayed if c.kind == "corner"),
                        key=lambda c: c.t_start)
        for a, b in zip(corner, corner[1:]):
            assert b.t_start - a.t_end >= GLOBAL_COOLDOWN_S - 1e-6


class TestRulesEngine:
    def test_first_lap_only_observes(self):
        r = RulesEngine()
        t = Turn(1, 0.05, 0.06, 0.07)
        assert r.peek_cue(t, 1) is None
        r.observe_apex(t, 25.0)
        assert r.peek_cue(t, 2) is None  # needs best AND last

    def test_praise_on_personal_best(self):
        r = RulesEngine()
        t = Turn(2, 0.1, 0.12, 0.14, name="the hairpin")
        r.observe_apex(t, 24.0)
        r.observe_apex(t, 25.5)  # better
        assert "best the hairpin" in r.peek_cue(t, 5)

    def test_per_turn_cooldown(self):
        r = RulesEngine()
        t = Turn(3, 0.2, 0.22, 0.24)
        r.observe_apex(t, 26.0)
        r.observe_apex(t, 22.0)  # 14 km/h down
        assert r.peek_cue(t, 5) is not None
        r.mark_cued(t, 5)
        assert r.peek_cue(t, 6) is None      # cooldown lap
        assert r.peek_cue(t, 7) is not None  # eligible again
