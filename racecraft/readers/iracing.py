"""iRacing telemetry reader using shared memory"""

import asyncio
from typing import AsyncIterator
import msgpack

try:
    import irsdk
    IRSDK_AVAILABLE = True
except ImportError:
    IRSDK_AVAILABLE = False
    print("WARNING: pyirsdk not installed. iRacing support disabled.")
    print("Install with: pip install pyirsdk")

from racecraft.interfaces import ITelemetryReader


class IRacingReader(ITelemetryReader):
    """Shared memory reader for iRacing using pyirsdk"""

    def __init__(self, update_rate: int = 60):
        if not IRSDK_AVAILABLE:
            raise ImportError("pyirsdk not available. Install with: pip install pyirsdk")

        self._ir = irsdk.IRSDK()
        self._connected = False
        self._update_rate = update_rate
        self._poll_interval = 1.0 / update_rate
        self._stop_event = asyncio.Event()

    async def connect(self) -> bool:
        """Connect to iRacing shared memory"""
        # Run blocking startup in thread pool
        loop = asyncio.get_running_loop()
        connected = await loop.run_in_executor(None, self._ir.startup)
        self._connected = connected
        return connected

    async def disconnect(self) -> None:
        """Shutdown iRacing connection"""
        self._stop_event.set()
        if self._connected:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._ir.shutdown)
        self._connected = False

    async def read_telemetry(self) -> AsyncIterator[bytes]:
        """
        Continuously read iRacing telemetry at configured rate.
        Yields serialized dict of all telemetry variables.
        """
        loop = asyncio.get_running_loop()

        while not self._stop_event.is_set():
            # Check if iRacing is still running
            is_init = await loop.run_in_executor(None, lambda: self._ir.is_initialized)
            if not is_init:
                await asyncio.sleep(1.0)  # Wait for iRacing to start
                continue

            # Get telemetry data (blocking call, run in thread)
            try:
                # Freeze the data to get a consistent snapshot
                await loop.run_in_executor(None, self._ir.freeze_var_buffer_latest)

                # Build telemetry dict from available variables
                data = {}
                if self._ir.var_headers_names:
                    for key in self._ir.var_headers_names:
                        try:
                            data[key] = self._ir[key]
                        except:
                            pass

                if data:
                    # Serialize to bytes for interface compliance
                    yield msgpack.packb(data)
            except Exception as e:
                print(f"Error reading iRacing telemetry: {e}")
                # Don't crash, just skip this frame
                pass

            await asyncio.sleep(self._poll_interval)

    def is_connected(self) -> bool:
        """Check if currently connected"""
        try:
            return self._ir.is_initialized if self._ir else False
        except:
            return False

    @property
    def update_rate(self) -> int:
        """Expected Hz rate"""
        return self._update_rate
