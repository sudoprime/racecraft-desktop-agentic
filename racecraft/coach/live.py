"""
Live coach, mode A (D3 — racecraft-agentic docs/REALTIME_COACH.md;
owner-approved premium feature, local rules + local TTS, $0/hour).

Incremental version of the ghost-coach trigger model: the same
RulesEngine and timing math, but fed one frame at a time from the live
collector (no lookahead — the offline replay's braking-point scan is a
validation tool, not a runtime need). Turn database comes from the
platform's track cache via GET /api/tracks/turns; when the track isn't
cached yet the coach stays silent for corner cues and still gives lap
debriefs.
"""
from typing import List, Optional

from racecraft.coach.ghost import (
    SAFETY_MARGIN_S,
    Frame,
    RulesEngine,
    Turn,
    speech_seconds,
)
from racecraft.coach.tts import TTSQueue

DEFAULT_TRACK_LENGTH_M = 5000.0


async def fetch_turns(client, api_base_url: str, bearer_token: str,
                      track_name: str,
                      track_config: Optional[str] = None):
    """Fetch (turns, track_length_m) from the platform; ([], default) when
    the track isn't cached or the call fails — the coach degrades, never
    blocks a session."""
    try:
        params = {"track_name": track_name}
        if track_config:
            params["track_config"] = track_config
        resp = await client.get(
            f"{api_base_url}/api/tracks/turns", params=params,
            headers={"Authorization": f"Bearer {bearer_token}"})
        if resp.status_code != 200:
            return [], DEFAULT_TRACK_LENGTH_M
        data = resp.json()
        turns = [Turn(number=t["number"], entry_pct=t["entry_pct"],
                      apex_pct=t["apex_pct"], exit_pct=t["exit_pct"],
                      name=t.get("name", ""))
                 for t in data.get("turns", [])]
        length = float(data.get("track_length") or DEFAULT_TRACK_LENGTH_M)
        return turns, length
    except Exception:
        return [], DEFAULT_TRACK_LENGTH_M


def frame_from_telemetry(telemetry, t: float) -> Optional[Frame]:
    """Build a coach Frame from a NormalizedTelemetry sample; None when the
    sample lacks the lap fraction (no cues possible without it)."""
    pct = getattr(telemetry, "lap_distance", None)
    if pct is None or not 0.0 <= pct <= 1.0:
        return None
    return Frame(t=t, pct=float(pct),
                 speed=float(getattr(telemetry, "speed", 0.0) or 0.0),
                 brake=float(getattr(telemetry, "brake", 0.0) or 0.0),
                 lap=int(getattr(telemetry, "lap_number", 0) or 0))


class LiveCoach:
    """Feed me frames; I talk (through the TTSQueue's safety rules)."""

    def __init__(self, turns: List[Turn], track_length_m: float = DEFAULT_TRACK_LENGTH_M,
                 tts: Optional[TTSQueue] = None):
        self.turns = sorted(turns, key=lambda t: t.entry_pct)
        self.track_length_m = max(float(track_length_m or 0) or DEFAULT_TRACK_LENGTH_M, 500.0)
        self.rules = RulesEngine()
        self.tts = tts or TTSQueue()
        self._crossed = {}
        self._last_lap: Optional[int] = None
        self._lap_start_t = 0.0
        self._best_lap_time: Optional[float] = None

    def on_frame(self, f: Frame) -> Optional[str]:
        """Process one live frame; returns the text spoken (if any)."""
        spoken = None
        if self._last_lap is None:
            self._last_lap, self._lap_start_t = f.lap, f.t

        # lap completion -> debrief (the straight is the latency-free zone)
        if f.lap != self._last_lap:
            lap_time = f.t - self._lap_start_t
            if self._last_lap >= 1 and lap_time > 30:
                text = self.rules.debrief(self._last_lap, lap_time, self._best_lap_time)
                if self._best_lap_time is None or lap_time < self._best_lap_time:
                    self._best_lap_time = lap_time
                if self.tts.speak(text, kind="debrief"):
                    spoken = text
            self._last_lap, self._lap_start_t = f.lap, f.t

        for turn in self.turns:
            if not self._crossed.get((f.lap, turn.number, "apex")) and f.pct >= turn.apex_pct:
                self._crossed[(f.lap, turn.number, "apex")] = True
                self.rules.observe_apex(turn, f.speed)

            key = (f.lap, turn.number, "cue")
            dist_pct = turn.entry_pct - f.pct
            if not self._crossed.get(key) and 0.0 < dist_pct < 0.12:
                time_to_entry = (dist_pct * self.track_length_m) / max(f.speed, 10.0)
                text = self.rules.peek_cue(turn, f.lap)
                if text is None:
                    if time_to_entry < 1.0:
                        self._crossed[key] = True
                    continue
                needed = speech_seconds(text) + SAFETY_MARGIN_S + 0.5
                if time_to_entry > needed + 1.5:
                    continue  # too early — keep approaching
                self._crossed[key] = True
                if not self.tts.speak(text, kind="corner"):
                    continue  # cooldown/mute — skip, don't retry late
                self.rules.mark_cued(turn, f.lap)
                spoken = text
        return spoken
