"""Game detection via process monitoring"""

import asyncio
from typing import Optional, Dict, Callable
import psutil


class GameDetector:
    """Detect running racing games and provide their configurations"""

    # Game configurations
    GAME_CONFIGS = {
        "iRacingSim64DX11.exe": {
            "name": "iRacing",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.iracing",
            "reader_class": "IRacingReader",
            "parser_module": "racecraft.parsers.iracing",
            "parser_class": "IRacingParser",
            "update_rate": 60,
        },
        "iRacingSimDX11.exe": {  # Older 32-bit version
            "name": "iRacing",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.iracing",
            "reader_class": "IRacingReader",
            "parser_module": "racecraft.parsers.iracing",
            "parser_class": "IRacingParser",
            "update_rate": 60,
        },
        "AC2-Win64-Shipping.exe": {  # Assetto Corsa Competizione
            "name": "ACC",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.acc",
            "reader_class": "ACCReader",
            "parser_module": "racecraft.parsers.acc",
            "parser_class": "ACCParser",
            "update_rate": 60,
            # implemented to spec, pending manual on-rig validation —
            # see racecraft-agentic/docs/COMPATIBILITY.md
            "validation_status": "implemented-untested",
        },
        "F1_24.exe": {
            "name": "F1 24",
            "protocol": "udp",
            "reader_module": "racecraft.readers.f1",
            "reader_class": "F1Reader",
            "parser_module": "racecraft.parsers.f1",
            "parser_class": "F1Parser",
            "update_rate": 60,
            "validation_status": "implemented-untested",
        },
        "F1_25.exe": {  # same packet format family
            "name": "F1 25",
            "protocol": "udp",
            "reader_module": "racecraft.readers.f1",
            "reader_class": "F1Reader",
            "parser_module": "racecraft.parsers.f1",
            "parser_class": "F1Parser",
            "update_rate": 60,
            "validation_status": "implemented-untested",
        },
        "acs.exe": {  # Assetto Corsa (original) — sim process
            "name": "Assetto Corsa",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.ac",
            "reader_class": "ACReader",
            "parser_module": "racecraft.parsers.ac",
            "parser_class": "ACParser",
            "update_rate": 60,
            "validation_status": "implemented-untested",
        },
        "AMS2AVX.exe": {  # Automobilista 2 (AVX build, the common one)
            "name": "Automobilista 2",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.ams2",
            "reader_class": "AMS2Reader",
            "parser_module": "racecraft.parsers.ams2",
            "parser_class": "AMS2Parser",
            "update_rate": 60,
            # requires Options -> System -> Shared Memory = PCARS2
            "validation_status": "implemented-untested",
        },
        "AMS2.exe": {  # non-AVX build
            "name": "Automobilista 2",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.ams2",
            "reader_class": "AMS2Reader",
            "parser_module": "racecraft.parsers.ams2",
            "parser_class": "AMS2Parser",
            "update_rate": 60,
            "validation_status": "implemented-untested",
        },
        "rFactor2.exe": {
            "name": "rFactor 2",
            "protocol": "shared_memory",
            "reader_module": "racecraft.readers.rf2",
            "reader_class": "RF2Reader",
            "parser_module": "racecraft.parsers.rf2",
            "parser_class": "RF2Parser",
            "update_rate": 60,
            # requires rF2SharedMemoryMapPlugin (CrewChief/SimHub install it)
            "validation_status": "implemented-untested",
        },
        # Future games will be added here
    }

    def __init__(self):
        self._current_game: Optional[str] = None
        self._current_config: Optional[Dict] = None

    async def detect_active_game(self) -> Optional[Dict]:
        """
        Poll running processes to find active racing game.
        Returns config dict if found, None otherwise.
        """
        # Run in thread pool to avoid blocking
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._scan_processes)
        except RuntimeError:
            # No event loop, run synchronously
            return self._scan_processes()

    def _scan_processes(self) -> Optional[Dict]:
        """Scan running processes (blocking operation)"""
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name']
                    if proc_name in self.GAME_CONFIGS:
                        config = self.GAME_CONFIGS[proc_name].copy()
                        config['process_name'] = proc_name
                        self._current_game = proc_name
                        self._current_config = config
                        return config
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f"Error scanning processes: {e}")

        # No game found
        if self._current_game is not None:
            # Game was running, now stopped
            self._current_game = None
            self._current_config = None

        return None

    async def monitor_games(
        self,
        on_game_started: Callable[[Dict], None],
        on_game_stopped: Callable[[], None],
        poll_interval: float = 2.0
    ):
        """
        Continuously monitor for game starts/stops.
        Calls callbacks when state changes.
        """
        last_detected = None

        while True:
            current = await self.detect_active_game()

            # State changed
            if current != last_detected:
                if current:
                    # Game started
                    await on_game_started(current)
                else:
                    # Game stopped
                    await on_game_stopped()

                last_detected = current

            await asyncio.sleep(poll_interval)

    @property
    def current_game(self) -> Optional[Dict]:
        """Get current game configuration"""
        return self._current_config
