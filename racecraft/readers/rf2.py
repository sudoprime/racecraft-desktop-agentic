"""
rFactor 2 shared-memory reader — rF2SharedMemoryMapPlugin pages.

PREREQUISITE: the rF2SharedMemoryMapPlugin DLL must be installed in the
game (CrewChief/SimHub install it automatically). Maps
$rFactor2SMMP_Telemetry$ and $rFactor2SMMP_Scoring$; each page is an
rF2MappedBufferVersionBlock followed by the buffer struct. A frame is
yielded only when both version words match (mVersionUpdateBegin ==
mVersionUpdateEnd, i.e. not mid-write) and the telemetry version advanced.

Windows-only at runtime; `_open_maps()` is the test seam.

STATUS: implemented to spec, pending manual validation on real hardware.
"""
import asyncio
import ctypes
import mmap
import sys
from typing import AsyncIterator, Optional

import msgpack

from racecraft.interfaces import ITelemetryReader
from racecraft.parsers.rf2 import (
    MAX_MAPPED_VEHICLES,
    SCORING_VEHICLES_OFFSET,
    TELEMETRY_VEHICLES_OFFSET,
    VEH_SCORING_SIZE,
    VEH_TELEMETRY_SIZE,
    VERSION_BLOCK_SIZE,
)

_TEL_TAG = "$rFactor2SMMP_Telemetry$"
_SCO_TAG = "$rFactor2SMMP_Scoring$"
_TEL_SIZE = TELEMETRY_VEHICLES_OFFSET + MAX_MAPPED_VEHICLES * VEH_TELEMETRY_SIZE
_SCO_SIZE = SCORING_VEHICLES_OFFSET + MAX_MAPPED_VEHICLES * VEH_SCORING_SIZE


def _versions(raw: bytes):
    begin = int.from_bytes(raw[0:4], "little")
    end = int.from_bytes(raw[4:8], "little")
    return begin, end


def _num_vehicles(raw: bytes, offset: int) -> int:
    n = int.from_bytes(raw[offset:offset + 4], "little", signed=True)
    return max(0, min(n, MAX_MAPPED_VEHICLES))


class RF2Reader(ITelemetryReader):
    def __init__(self, update_rate: int = 60):
        self._update_rate = update_rate
        self._poll_interval = 1.0 / update_rate
        self._maps: Optional[dict] = None
        self._stop_event = asyncio.Event()

    # --- test seam ---------------------------------------------------------
    def _open_maps(self) -> Optional[dict]:
        if sys.platform != "win32":
            return None
        try:
            return {
                "telemetry": mmap.mmap(-1, _TEL_SIZE, tagname=_TEL_TAG),
                "scoring": mmap.mmap(-1, _SCO_SIZE, tagname=_SCO_TAG),
            }
        except OSError:
            return None

    @staticmethod
    def _read_raw(m, size: int) -> bytes:
        if isinstance(m, (bytes, bytearray)):
            return bytes(m[:size])
        m.seek(0)
        return m.read(size)

    def _read_page(self, m, size: int, vehicles_offset: int, veh_size: int,
                   num_off: int) -> Optional[bytes]:
        """Read header first, then only the active vehicles — and verify the
        version block was stable across the read (not torn)."""
        head = self._read_raw(m, vehicles_offset)
        begin, end = _versions(head)
        if begin != end:
            return None  # mid-write
        n = _num_vehicles(head, num_off)
        raw = self._read_raw(m, vehicles_offset + n * veh_size)
        if _versions(raw) != (begin, end):
            return None  # torn during the copy
        return raw

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
        from racecraft.parsers.rf2 import rF2ScoringInfo
        sco_num_off = VERSION_BLOCK_SIZE + 4 + rF2ScoringInfo.mNumVehicles.offset
        last_version = -1
        while not self._stop_event.is_set():
            if not self._maps:
                await asyncio.sleep(1.0)
                continue
            try:
                tel = self._read_page(self._maps["telemetry"], _TEL_SIZE,
                                      TELEMETRY_VEHICLES_OFFSET,
                                      VEH_TELEMETRY_SIZE, VERSION_BLOCK_SIZE + 4)
                sco = self._read_page(self._maps["scoring"], _SCO_SIZE,
                                      SCORING_VEHICLES_OFFSET,
                                      VEH_SCORING_SIZE, sco_num_off)
                if tel is not None and sco is not None:
                    version = _versions(tel)[0]
                    if version != last_version:
                        last_version = version
                        yield msgpack.packb({"telemetry": tel, "scoring": sco})
            except Exception:
                pass
            await asyncio.sleep(self._poll_interval)

    def is_connected(self) -> bool:
        return self._maps is not None

    @property
    def update_rate(self) -> int:
        return self._update_rate
