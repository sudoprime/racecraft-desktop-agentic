"""
Ghost coach — offline prototype of the real-time coach trigger model
(platform loop 2, D2; design: racecraft-agentic/docs/REALTIME_COACH.md).

Replays a recorded session frame-by-frame through the corner-approach
trigger model and the rules engine, emitting a TIMESTAMPED cue script.
The pass criterion from the design doc: every corner cue must FINISH
(speech duration included) at least SAFETY_MARGIN_S before that corner's
braking point on that lap.

No audio, no network, no game: pure timing validation. The LLM per-lap
debrief from the hybrid design is represented by a template (`debrief`)
with the same information contract a cloud call would receive.

Run a demo:  python -m racecraft.coach.ghost
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

WORDS_PER_SECOND = 2.2          # ~130 wpm TTS speaking rate
SAFETY_MARGIN_S = 1.0           # cue must end this long before braking
GLOBAL_COOLDOWN_S = 8.0         # never speak more often than this
PER_TURN_COOLDOWN_LAPS = 1      # don't nag the same corner every lap
APPROACH_LEAD_S = 4.0           # aim to START a cue ~4s before turn-in


@dataclass
class Turn:
    number: int
    entry_pct: float
    apex_pct: float
    exit_pct: float
    name: str = ""


@dataclass
class Frame:
    t: float        # session time, seconds
    pct: float      # lap fraction 0..1
    speed: float    # m/s
    brake: float    # 0..1
    lap: int


@dataclass
class Cue:
    t_start: float
    t_end: float
    lap: int
    turn: Optional[int]
    kind: str       # "corner" | "debrief"
    text: str
    braking_point_t: Optional[float] = None

    @property
    def margin(self) -> Optional[float]:
        if self.braking_point_t is None:
            return None
        return self.braking_point_t - self.t_end


def speech_seconds(text: str) -> float:
    return max(0.8, len(text.split()) / WORDS_PER_SECOND)


class RulesEngine:
    """Per-corner cue selection from the session's own rolling baseline."""

    def __init__(self):
        self.best_apex: Dict[int, float] = {}     # turn -> best apex speed seen
        self.last_apex: Dict[int, float] = {}
        self.improvement: Dict[int, float] = {}   # last vs the PRIOR best (m/s)
        self.last_cued_lap: Dict[int, int] = {}

    def observe_apex(self, turn: Turn, speed: float):
        # delta vs the best BEFORE this observation — updating best first
        # made a personal best read as delta-zero, so praise never fired
        # (caught by the prototype's test suite)
        prev_best = self.best_apex.get(turn.number)
        self.improvement[turn.number] = (speed - prev_best) if prev_best is not None else 0.0
        self.last_apex[turn.number] = speed
        if prev_best is None or speed > prev_best:
            self.best_apex[turn.number] = speed

    def peek_cue(self, turn: Turn, lap: int) -> Optional[str]:
        """Candidate cue WITHOUT marking it spoken (the coach needs the
        text length to time the trigger). Cue texts are deliberately
        terse — the first prototype run proved a 19-word sentence ends
        6s AFTER the braking point."""
        if lap - self.last_cued_lap.get(turn.number, -99) <= PER_TURN_COOLDOWN_LAPS:
            return None
        best = self.best_apex.get(turn.number)
        last = self.last_apex.get(turn.number)
        if best is None or last is None:
            return None  # first flying lap: just observe
        delta_kmh = (best - last) * 3.6
        gain_kmh = self.improvement.get(turn.number, 0.0) * 3.6
        label = turn.name or f"turn {turn.number}"
        if delta_kmh > 3.0:
            return f"{label}: brake later, you're {delta_kmh:.0f} down"
        if gain_kmh > 2.0:
            return f"best {label} yet, keep that"
        return None

    def mark_cued(self, turn: Turn, lap: int):
        self.last_cued_lap[turn.number] = lap

    def debrief(self, lap: int, lap_time: float, best_time: Optional[float]) -> str:
        # 50ms tolerance: frame quantization must not turn an equal lap
        # into "0.0 off your best"
        if best_time is None or lap_time <= best_time + 0.05:
            return f"lap {lap}: {lap_time:.1f} — that's your benchmark now"
        gap = lap_time - best_time
        deltas = {n: self.best_apex[n] - self.last_apex.get(n, self.best_apex[n])
                  for n in self.best_apex}
        worst = max(deltas, key=deltas.get, default=None)
        # only name a corner when it actually explains time (>0.5 km/h down)
        where = (f", most of it in turn {worst}"
                 if worst is not None and deltas[worst] * 3.6 > 0.5 else "")
        return f"lap {lap}: {gap:.1f} off your best{where}"


class GhostCoach:
    def __init__(self, turns: List[Turn]):
        self.turns = sorted(turns, key=lambda t: t.entry_pct)
        self.rules = RulesEngine()

    @staticmethod
    def _braking_point_t(frames: List[Frame], i_from: int,
                         i_entry: int) -> Optional[float]:
        """THIS corner's braking point: first sustained brake application
        from the cue start forward (a backward scan finds the previous
        corner's braking zone instead — the prototype's first bug)."""
        for f in frames[i_from:min(i_entry + 300, len(frames))]:
            if f.brake > 0.2:
                return f.t
        return frames[i_entry].t if i_entry < len(frames) else None

    def replay(self, frames: List[Frame]) -> List[Cue]:
        cues: List[Cue] = []
        speaking_until = -1e9
        last_lap = frames[0].lap if frames else 0
        lap_start_t = frames[0].t if frames else 0.0
        best_lap_time: Optional[float] = None
        crossed: Dict[tuple, bool] = {}

        for i, f in enumerate(frames):
            # lap completion -> debrief (spoken on the straight; latency-free zone)
            if f.lap != last_lap:
                lap_time = f.t - lap_start_t
                if last_lap >= 1 and lap_time > 30:
                    text = self.rules.debrief(last_lap, lap_time, best_lap_time)
                    if best_lap_time is None or lap_time < best_lap_time:
                        best_lap_time = lap_time
                    start = max(f.t, speaking_until)
                    cues.append(Cue(start, start + speech_seconds(text),
                                    last_lap, None, "debrief", text))
                    speaking_until = start + speech_seconds(text)
                last_lap, lap_start_t = f.lap, f.t

            for turn in self.turns:
                # apex observation (closest frame past apex_pct)
                if not crossed.get((f.lap, turn.number, "apex")) and f.pct >= turn.apex_pct:
                    crossed[(f.lap, turn.number, "apex")] = True
                    self.rules.observe_apex(turn, f.speed)

                # corner-approach trigger: fire when the time remaining to
                # turn-in just covers the speech duration + safety margin
                # (longer messages fire earlier — the trigger is derived
                # from the TEXT, the design doc's key timing rule)
                key = (f.lap, turn.number, "cue")
                dist_pct = turn.entry_pct - f.pct
                if not crossed.get(key) and 0.0 < dist_pct < 0.12:
                    time_to_entry = (dist_pct * 5200.0) / max(f.speed, 10.0)
                    text = self.rules.peek_cue(turn, f.lap)
                    if text is None:
                        if time_to_entry < 1.0:
                            crossed[key] = True  # nothing to say this lap
                        continue
                    needed = speech_seconds(text) + SAFETY_MARGIN_S + 0.5
                    if time_to_entry > needed + 1.5:
                        continue  # too early — keep approaching
                    crossed[key] = True
                    if f.t < speaking_until + GLOBAL_COOLDOWN_S:
                        continue
                    self.rules.mark_cued(turn, f.lap)
                    dur = speech_seconds(text)
                    i_entry = next((j for j in range(i, min(i + 1200, len(frames)))
                                    if frames[j].pct >= turn.entry_pct
                                    and frames[j].lap == f.lap), i)
                    bp = self._braking_point_t(frames, i, i_entry)
                    cues.append(Cue(f.t, f.t + dur, f.lap, turn.number,
                                    "corner", text, braking_point_t=bp))
                    speaking_until = f.t + dur
        return cues


def timing_report(cues: List[Cue]) -> dict:
    corner = [c for c in cues if c.kind == "corner"]
    margins = [c.margin for c in corner if c.margin is not None]
    return {
        "corner_cues": len(corner),
        "debriefs": len([c for c in cues if c.kind == "debrief"]),
        "min_margin_s": round(min(margins), 2) if margins else None,
        "all_cues_in_time": bool(margins) and all(m >= SAFETY_MARGIN_S for m in margins),
    }


# --- demo ------------------------------------------------------------------

def synthetic_session(laps: int = 4, hz: int = 60) -> tuple:
    """8-corner club lap, ~90s, with a deliberately slow T4 on lap 3."""
    import math
    turns = [Turn(n + 1, entry_pct=c - 0.018, apex_pct=c, exit_pct=c + 0.018)
             for n, c in enumerate([0.06, 0.18, 0.31, 0.43, 0.55, 0.67, 0.79, 0.92])]
    frames: List[Frame] = []
    t = 0.0
    for lap in range(1, laps + 1):
        n = int(90.0 * hz)
        for i in range(n):
            pct = i / n
            speed = 50.0
            brake = 0.0
            for turn in turns:
                d = min(abs(pct - turn.apex_pct), 1 - abs(pct - turn.apex_pct))
                infl = math.exp(-((d / 0.015) ** 2))
                apex = 26.0 - (6.0 if (lap == 3 and turn.number == 4) else 0.0)
                speed -= (50.0 - apex) * infl
                if -0.02 < (turn.apex_pct - pct) < 0.012:
                    brake = max(brake, infl)
            frames.append(Frame(t, pct, speed, brake, lap))
            t += 1.0 / hz
    return turns, frames


if __name__ == "__main__":
    turns, frames = synthetic_session()
    coach = GhostCoach(turns)
    cues = coach.replay(frames)
    for c in cues:
        margin = f"  margin={c.margin:+.1f}s" if c.margin is not None else ""
        print(f"[{c.t_start:7.1f}s] lap {c.lap} {c.kind:8s} {c.text}{margin}")
    print("\nreport:", timing_report(cues))
