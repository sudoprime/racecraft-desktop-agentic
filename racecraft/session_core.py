"""Qt-free streaming-session lifecycle (platform loop 3, T3 part 2).

One session's frame path and finish-once semantics, extracted from the
Qt collector so that BOTH drivers — the system-tray app (TelemetryCollector
wraps this with Qt signals) and the headless runner — execute the SAME
code. Previously headless reimplemented the loop, so automated E2E
validated a parallel path rather than the product's.

Responsibilities:
- frame: parse → validate → (optional live coach) → stream
- finish: end session + submit for analysis, exactly once
The caller owns the reader (game detection / simulated), authentication,
and any UI.
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SessionCore:
    def __init__(self, parser, streaming, coach=None,
                 on_frame: Optional[Callable] = None,
                 coach_clock: Optional[Callable[[], float]] = None):
        """
        parser:    ITelemetryParser for the active game
        streaming: StreamingClient (None = collect locally only)
        coach:     LiveCoach or None; may also be attached later (.coach=)
        on_frame:  sync callback(telemetry) — stats/UI hook
        coach_clock: () -> float seconds for coach frame timestamps;
                   defaults to time.monotonic. Headless passes session
                   time so cue cadence is honest under --time-scale.
        """
        self.parser = parser
        self.streaming = streaming
        self.coach = coach
        self.on_frame = on_frame
        self._coach_clock = coach_clock
        self.session_active = False
        self.frames = 0

    async def start(self, game: str, track_name: str, car_name: str,
                    session_type: str = "practice",
                    metadata: Optional[dict] = None) -> Optional[str]:
        """Start the streaming session. Returns session_id, or None when
        there is no streaming client (local-only collection)."""
        if self.streaming is None:
            return None
        session_id = await self.streaming.start_session(
            game=game, track_name=track_name, car_name=car_name,
            session_type=session_type, metadata=metadata or {})
        self.session_active = True
        return session_id

    async def process_raw(self, raw, track_length: Optional[float] = None) -> Optional[str]:
        """One raw telemetry sample through parse → validate → coach →
        stream. Returns the coach's cue text when one was spoken (the
        headless runner logs it; the Qt app's TTS backend already spoke
        it). Invalid frames are skipped. Coach failures never break
        collection; upload failures are the StreamingClient's job to
        retry/spool and are logged here."""
        telemetry = self.parser.parse(raw)
        if not telemetry or not self.parser.validate_data(telemetry):
            return None

        self.frames += 1
        if self.on_frame is not None:
            try:
                self.on_frame(telemetry)
            except Exception:
                logger.exception("on_frame hook failed (continuing)")

        cue = None
        if self.coach is not None:
            try:
                from racecraft.coach.live import frame_from_telemetry
                if self._coach_clock is not None:
                    now = self._coach_clock()
                else:
                    import time as _time
                    now = _time.monotonic()
                cf = frame_from_telemetry(telemetry, now)
                if cf is not None:
                    cue = self.coach.on_frame(cf)
            except Exception:
                logger.exception("live coach frame failed (continuing)")

        if self.session_active:
            try:
                await self.streaming.add_frame(telemetry, track_length=track_length)
            except Exception as e:
                logger.warning(f"SessionCore: chunk upload failed: {e}")

        return cue

    async def finish(self, notes: str = "auto-submitted by desktop app") -> Optional[str]:
        """End the streaming session and submit it for analysis — exactly
        once. Returns the analysis_id (None when nothing was active or
        end/submit failed)."""
        if not self.session_active:
            return None
        self.session_active = False
        try:
            await self.streaming.end_session()
            analysis_id = await self.streaming.submit_for_analysis(notes)
            logger.info(f"SessionCore: session submitted for analysis ({analysis_id})")
            return analysis_id
        except Exception as e:
            logger.error(f"SessionCore: session end/submit failed: {e}")
            return None
