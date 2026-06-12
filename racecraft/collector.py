"""Telemetry collection coordinator"""

import asyncio
import logging
import os
from typing import Optional
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import importlib

from racecraft.detection import GameDetector
from racecraft.interfaces import ITelemetryReader, ITelemetryParser
from racecraft.session_core import SessionCore

logger = logging.getLogger(__name__)


class TelemetryStats(QObject):
    """Real-time telemetry statistics with Qt signals for UI updates"""

    # Signals for UI updates
    stats_updated = pyqtSignal(dict)  # Emits stats dict
    game_connected = pyqtSignal(str)  # Emits game name
    game_disconnected = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.game_name: Optional[str] = None
        self.frames_collected = 0
        self.frames_per_second = 0.0
        self.session_start_time: Optional[datetime] = None
        self.last_speed = 0.0
        self.last_rpm = 0.0
        self.last_gear = 0
        self.current_lap = 0
        self.last_raw_data: Optional[dict] = None

        # For FPS calculation
        self._frame_count_window = 0
        self._last_fps_update = datetime.now()

    def reset(self):
        """Reset statistics for new session"""
        self.frames_collected = 0
        self.frames_per_second = 0.0
        self.session_start_time = datetime.now()
        self._frame_count_window = 0
        self._last_fps_update = datetime.now()

    def record_frame(self, telemetry):
        """Record a telemetry frame and update stats"""
        self.frames_collected += 1
        self._frame_count_window += 1

        # Update from telemetry
        self.last_speed = telemetry.speed
        self.last_rpm = telemetry.engine_rpm
        self.last_gear = telemetry.gear
        self.current_lap = telemetry.lap_number or 0
        self.last_raw_data = telemetry.raw_data

        # Calculate FPS every second
        now = datetime.now()
        elapsed = (now - self._last_fps_update).total_seconds()
        if elapsed >= 1.0:
            self.frames_per_second = self._frame_count_window / elapsed
            self._frame_count_window = 0
            self._last_fps_update = now

            # Emit stats update
            self._emit_stats()

    def _emit_stats(self):
        """Emit current stats to UI"""
        session_duration = 0
        if self.session_start_time:
            session_duration = (datetime.now() - self.session_start_time).total_seconds()

        stats = {
            'game_name': self.game_name,
            'frames_collected': self.frames_collected,
            'frames_per_second': round(self.frames_per_second, 1),
            'session_duration': int(session_duration),
            'last_speed': round(self.last_speed * 2.237, 1),  # m/s to mph
            'last_rpm': int(self.last_rpm),
            'last_gear': self.last_gear,
            'current_lap': self.current_lap,
            'raw_telemetry': self.last_raw_data or {},
        }

        self.stats_updated.emit(stats)


# Test-mode game config: the SimulatedReader generates synthetic laps
# without a sim attached (see racecraft/readers/simulated.py)
SIMULATED_GAME_CONFIG = {
    "name": "Simulated",
    "protocol": "simulated",
    "reader_module": "racecraft.readers.simulated",
    "reader_class": "SimulatedReader",
    "parser_module": "racecraft.parsers.iracing",
    "parser_class": "IRacingParser",
    "update_rate": 60,
    "process_name": "simulated",
}

# Map collector game names to the backend's Game enum values
from racecraft.game_mapping import GAME_ENUM


class TelemetryCollector(QObject):
    """Coordinates game detection and telemetry collection"""

    # Signals
    stats_updated = pyqtSignal(dict)
    game_connected = pyqtSignal(str)
    game_disconnected = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, streaming=None, test_mode: bool = False, coach=None,
                 coach_enabled: bool = None):
        self.coach = coach  # LiveCoach (D3) or None
        # env-gated until the settings UI exposes a toggle (D3 remainder)
        self._coach_enabled = (coach_enabled if coach_enabled is not None
                               else os.getenv('RACECRAFT_LIVE_COACH', '0') == '1')
        super().__init__()

        self.detector = GameDetector()
        self.stats = TelemetryStats()

        # Streaming upload client (racecraft.streaming.StreamingClient);
        # None = collect locally only (unauthenticated / offline)
        self.streaming = streaming
        self.test_mode = test_mode
        self._test_session_done = False  # one simulated session per app start
        self._session_active = False

        # Current reader/parser
        self.reader: Optional[ITelemetryReader] = None
        self.parser: Optional[ITelemetryParser] = None
        self._collection_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_detected_game = None

        # Qt timer for game detection (more compatible with qasync)
        self._detection_timer = QTimer()
        self._detection_timer.timeout.connect(self._check_for_games)
        self._detection_timer.setInterval(2000)  # 2 seconds

        # Forward stats signals
        self.stats.stats_updated.connect(self.stats_updated.emit)
        self.stats.game_connected.connect(self.game_connected.emit)
        self.stats.game_disconnected.connect(self.game_disconnected.emit)

    async def start(self):
        """Start game detection and telemetry collection"""
        self._running = True
        logger.info("TelemetryCollector: Starting game detection...")

        # Start Qt timer for game monitoring
        self._detection_timer.start()

    def _check_for_games(self):
        """Called by Qt timer to check for running games"""
        # Run detection asynchronously
        asyncio.create_task(self._async_check_games())

    async def _async_check_games(self):
        """Async game detection check"""
        try:
            if self.test_mode:
                # Simulated game "runs" until its lap count completes
                current = None if self._test_session_done else SIMULATED_GAME_CONFIG
            else:
                current = await self.detector.detect_active_game()

            # State changed?
            if current != self._last_detected_game:
                if current:
                    # Game started
                    await self._on_game_started(current)
                else:
                    # Game stopped
                    await self._on_game_stopped()

                self._last_detected_game = current
        except Exception as e:
            logger.error(f"Exception in _async_check_games: {e}", exc_info=True)

    async def stop(self):
        """Stop telemetry collection"""
        self._running = False
        self._detection_timer.stop()
        await self._stop_collection()

    async def _on_game_started(self, game_config: dict):
        """Called when a racing game is detected"""
        logger.info(f"TelemetryCollector: Game detected - {game_config['name']}")

        # Stop existing collection
        await self._stop_collection()

        try:
            # Dynamically import reader and parser classes
            reader_module = importlib.import_module(game_config['reader_module'])
            reader_class = getattr(reader_module, game_config['reader_class'])

            parser_module = importlib.import_module(game_config['parser_module'])
            parser_class = getattr(parser_module, game_config['parser_class'])

            # Create instances
            self.reader = reader_class(update_rate=game_config.get('update_rate', 60))
            self.parser = parser_class()

            # Connect to game
            if await self.reader.connect():
                logger.info(f"TelemetryCollector: Connected to {game_config['name']}")
                self.stats.game_name = game_config['name']
                self.stats.reset()

                # Session lifecycle is owned by the Qt-free SessionCore
                # (platform loop 3, T3 part 2) — the same code headless
                # E2E drives.
                self.core = SessionCore(self.parser, self.streaming,
                                        coach=self.coach,
                                        on_frame=self.stats.record_frame)
                if self.streaming:
                    try:
                        await self.core.start(
                            game=GAME_ENUM.get(game_config['name'], 'unknown'),
                            track_name=getattr(self.reader, 'track_name', 'Unknown Track'),
                            car_name=getattr(self.reader, 'car_name', 'Unknown Car'),
                            session_type='practice',
                            metadata={'source': game_config.get('protocol', 'desktop')},
                        )
                        logger.info(f"TelemetryCollector: Streaming session {self.streaming.session_id}")

                        # Live coach (D3): build from the platform turn DB
                        # once we know the track; absent cache -> debriefs only
                        if self._coach_enabled and self.coach is None:
                            try:
                                from racecraft.coach.live import LiveCoach, fetch_turns
                                turns, length = await fetch_turns(
                                    self.streaming.client,
                                    self.streaming.api_base_url,
                                    self.streaming.auth.bearer_token,
                                    getattr(self.reader, 'track_name', 'Unknown Track'),
                                )
                                self.coach = LiveCoach(turns, track_length_m=length)
                                self.core.coach = self.coach
                                logger.info(f"LiveCoach: armed with {len(turns)} turns")
                            except Exception as e:
                                logger.warning(f"LiveCoach: unavailable ({e})")
                    except Exception as e:
                        logger.warning(f"TelemetryCollector: Streaming unavailable ({e}); collecting locally")

                # Emit signal
                self.game_connected.emit(game_config['name'])

                # Start collection task
                self._collection_task = asyncio.create_task(self._collect_telemetry())
            else:
                logger.info(f"TelemetryCollector: Failed to connect to {game_config['name']}")
                self.error_occurred.emit(f"Failed to connect to {game_config['name']}")

        except Exception as e:
            logger.info(f"TelemetryCollector: Error starting collection: {e}")
            self.error_occurred.emit(f"Error: {e}")

    async def _on_game_stopped(self):
        """Called when game exits"""
        logger.info("TelemetryCollector: Game stopped")
        await self._stop_collection()
        self.game_disconnected.emit()

    async def _collect_telemetry(self):
        """Main telemetry collection loop"""
        logger.info("TelemetryCollector: Starting telemetry collection...")

        try:
            track_length = getattr(self.reader, 'track_length', None)
            async for raw_data in self.reader.read_telemetry():
                if not self._running:
                    break
                # parse → validate → stats hook → coach → stream, all in
                # the shared SessionCore (headless drives the same path)
                await self.core.process_raw(raw_data, track_length=track_length)

            # Reader ended on its own (sim exited / simulated laps complete)
            await self._finish_session()
            if self.test_mode:
                self._test_session_done = True

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.info(f"TelemetryCollector: Collection error: {e}")
            self.error_occurred.emit(f"Collection error: {e}")

    async def _finish_session(self):
        """End the streaming session and submit it for analysis (once) —
        delegated to SessionCore's finish-once semantics."""
        core = getattr(self, 'core', None)
        if core is not None:
            await core.finish()

    async def _stop_collection(self):
        """Stop active telemetry collection"""
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
            self._collection_task = None

        # Game exited while a session was live (e.g. real sim closed)
        await self._finish_session()

        if self.reader:
            await self.reader.disconnect()
            self.reader = None

        self.parser = None
