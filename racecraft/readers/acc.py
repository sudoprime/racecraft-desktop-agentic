"""
ACC (Assetto Corsa Competizione) shared-memory reader.

Reads the three Kunos memory-mapped pages (Local\\acpmf_physics,
Local\\acpmf_graphics, Local\\acpmf_static) and yields msgpack frames of
their raw bytes for ACCParser. Windows-only at runtime (named shared
memory via mmap tagname); `_open_maps()` is the test seam — tests replace
it with in-memory buffers.

STATUS: implemented to spec, pending manual validation on real hardware.
"""
import asyncio
import ctypes
import mmap
import sys
from typing import AsyncIterator, Optional

import msgpack

from racecraft.interfaces import ITelemetryReader
from racecraft.parsers.acc import GraphicsPage, PhysicsPage, StaticPage

_PAGES = {
    "physics": ("Local\\acpmf_physics", ctypes.sizeof(PhysicsPage)),
    "graphics": ("Local\\acpmf_graphics", ctypes.sizeof(GraphicsPage)),
    "static": ("Local\\acpmf_static", ctypes.sizeof(StaticPage)),
}


class ACCReader(ITelemetryReader):
    def __init__(self, update_rate: int = 60):
        self._update_rate = update_rate
        self._poll_interval = 1.0 / update_rate
        self._maps: Optional[dict] = None
        self._stop_event = asyncio.Event()

    # --- test seam ---------------------------------------------------------
    def _open_maps(self) -> Optional[dict]:
        """Open the three shared-memory pages; None when unavailable."""
        if sys.platform != "win32":
            return None
        try:
            return {name: mmap.mmap(-1, size, tagname=tag)
                    for name, (tag, size) in _PAGES.items()}
        except OSError:
            return None

    @staticmethod
    def _read_page(m, size: int) -> bytes:
        if isinstance(m, (bytes, bytearray)):
            return bytes(m[:size])
        m.seek(0)
        return m.read(size)

    # --- ITelemetryReader ---------------------------------------------------
    async def connect(self) -> bool:
        self._stop_event.clear()
        self._maps = self._open_maps()
        return self._maps is not None

    async def disconnect(self) -> None:
        self._stop_event.set()
        if self._maps:
            for m in self._maps.values():
                try:
                    if hasattr(m, "close"):
                        m.close()
                except Exception:
                    pass
        self._maps = None

    async def read_telemetry(self) -> AsyncIterator[bytes]:
        last_packet = -1
        while not self._stop_event.is_set():
            if not self._maps:
                await asyncio.sleep(1.0)
                continue
            try:
                frame = {name: self._read_page(self._maps[name], size)
                         for name, (_tag, size) in _PAGES.items()}
                phys = PhysicsPage.from_buffer_copy(frame["physics"])
                # only yield fresh frames (packetId advances while driving)
                if int(phys.packetId) != last_packet:
                    last_packet = int(phys.packetId)
                    yield msgpack.packb(frame)
            except Exception:
                pass  # never crash the collector on one bad frame
            await asyncio.sleep(self._poll_interval)

    def is_connected(self) -> bool:
        return self._maps is not None

    @property
    def update_rate(self) -> int:
        return self._update_rate
