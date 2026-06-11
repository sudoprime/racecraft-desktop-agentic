"""
F1 24/25 UDP reader.

Listens on the game's broadcast port (default 20777), keeps the latest
Motion / Session / LapData / CarTelemetry packets, and yields a combined
msgpack frame whenever a fresh CarTelemetry packet arrives (the highest-
rate packet — effectively the game's tick).

STATUS: implemented to the published spec, pending manual validation.
The socket is the test seam: tests inject packets via `_handle_packet`.
"""
import asyncio
import socket
from typing import AsyncIterator, Dict, Optional

import msgpack

from racecraft.interfaces import ITelemetryReader
from racecraft.parsers.f1 import (
    F1_UDP_PORT, HEADER_SIZE, PACKET_LAP, PACKET_MOTION, PACKET_SESSION,
    PACKET_TELEMETRY, PacketHeader,
)

_KEY_BY_ID = {
    PACKET_MOTION: "motion",
    PACKET_SESSION: "session",
    PACKET_LAP: "lap",
    PACKET_TELEMETRY: "telemetry",
}


class F1Reader(ITelemetryReader):
    def __init__(self, update_rate: int = 60, port: int = F1_UDP_PORT):
        self._update_rate = update_rate
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._latest: Dict[str, bytes] = {}
        self._fresh_telemetry = False
        self._stop_event = asyncio.Event()

    def _handle_packet(self, packet: bytes) -> Optional[bytes]:
        """Route one UDP packet; returns a combined frame when the tick
        (CarTelemetry) arrives and we have something to say."""
        if len(packet) < HEADER_SIZE:
            return None
        hdr = PacketHeader.from_buffer_copy(packet[:HEADER_SIZE])
        key = _KEY_BY_ID.get(int(hdr.m_packetId))
        if key is None:
            return None
        self._latest[key] = packet
        if key == "telemetry":
            return msgpack.packb(dict(self._latest))
        return None

    async def connect(self) -> bool:
        self._stop_event.clear()
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", self._port))
            self._sock.setblocking(False)
            return True
        except OSError:
            self._sock = None
            return False

    async def disconnect(self) -> None:
        self._stop_event.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    async def read_telemetry(self) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            if self._sock is None:
                await asyncio.sleep(1.0)
                continue
            try:
                packet = await asyncio.wait_for(
                    loop.sock_recv(self._sock, 4096), timeout=1.0)
            except (asyncio.TimeoutError, OSError):
                continue
            try:
                frame = self._handle_packet(packet)
                if frame is not None:
                    yield frame
            except Exception:
                pass  # one malformed packet must not kill the stream

    def is_connected(self) -> bool:
        return self._sock is not None

    @property
    def update_rate(self) -> int:
        return self._update_rate
