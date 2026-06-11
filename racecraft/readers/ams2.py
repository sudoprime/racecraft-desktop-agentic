"""
Automobilista 2 (AMS2) shared-memory reader — PC2 API "$pcars2$" page.

Requires the player to set Options -> System -> Shared Memory to PCARS2.
Reads the single SharedMemory page and yields its raw bytes when a frame
is consistent (mSequenceNumber even and unchanged across the read, per the
header's documented protocol). Windows-only at runtime; `_open_map()` is
the test seam.

STATUS: implemented to spec, pending manual validation on real hardware.
"""
import asyncio
import ctypes
import mmap
import sys
from typing import AsyncIterator, Optional

from racecraft.interfaces import ITelemetryReader
from racecraft.parsers.ams2 import SharedMemory

_TAG = "$pcars2$"
_SIZE = ctypes.sizeof(SharedMemory)
_SEQ_OFFSET = SharedMemory.mSequenceNumber.offset


class AMS2Reader(ITelemetryReader):
    def __init__(self, update_rate: int = 60):
        self._update_rate = update_rate
        self._poll_interval = 1.0 / update_rate
        self._map = None
        self._stop_event = asyncio.Event()

    # --- test seam ---------------------------------------------------------
    def _open_map(self):
        if sys.platform != "win32":
            return None
        try:
            return mmap.mmap(-1, _SIZE, tagname=_TAG)
        except OSError:
            return None

    @staticmethod
    def _read_raw(m) -> bytes:
        if isinstance(m, (bytes, bytearray)):
            return bytes(m[:_SIZE])
        m.seek(0)
        return m.read(_SIZE)

    @staticmethod
    def _sequence(raw: bytes) -> int:
        return int.from_bytes(raw[_SEQ_OFFSET:_SEQ_OFFSET + 4], "little")

    # --- ITelemetryReader ---------------------------------------------------
    async def connect(self) -> bool:
        self._stop_event.clear()
        self._map = self._open_map()
        return self._map is not None

    async def disconnect(self) -> None:
        self._stop_event.set()
        if self._map is not None and hasattr(self._map, "close"):
            try:
                self._map.close()
            except Exception:
                pass
        self._map = None

    async def read_telemetry(self) -> AsyncIterator[bytes]:
        last_seq = -1
        while not self._stop_event.is_set():
            if self._map is None:
                await asyncio.sleep(1.0)
                continue
            try:
                raw = self._read_raw(self._map)
                seq = self._sequence(raw)
                # odd sequence = game mid-write; verify it didn't change
                # while we copied (torn frame)
                if seq % 2 == 0 and seq != last_seq:
                    raw2 = self._read_raw(self._map)
                    if self._sequence(raw2) == seq:
                        last_seq = seq
                        yield raw
            except Exception:
                pass
            await asyncio.sleep(self._poll_interval)

    def is_connected(self) -> bool:
        return self._map is not None

    @property
    def update_rate(self) -> int:
        return self._update_rate
