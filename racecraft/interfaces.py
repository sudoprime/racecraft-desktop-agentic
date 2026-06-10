"""Abstract base classes for telemetry readers and parsers"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from racecraft.models import NormalizedTelemetry, TelemetryMetadata


class ITelemetryReader(ABC):
    """Abstract base for all telemetry collection methods"""

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to telemetry source.
        Returns True if successful, False otherwise.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up resources and close connections"""
        pass

    @abstractmethod
    async def read_telemetry(self) -> AsyncIterator[bytes]:
        """
        Async generator yielding raw telemetry data as bytes.
        Continues until disconnect() called or source unavailable.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected to telemetry source"""
        pass

    @property
    @abstractmethod
    def update_rate(self) -> int:
        """Expected Hz rate of telemetry updates"""
        pass


class ITelemetryParser(ABC):
    """Abstract base for game-specific telemetry parsing"""

    @abstractmethod
    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        """
        Parse raw game telemetry into normalized format.
        Returns None if data invalid/unparseable.
        """
        pass

    @abstractmethod
    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        """
        Extract session metadata (called once per session).
        Returns None if metadata not available yet.
        """
        pass

    @property
    @abstractmethod
    def game_name(self) -> str:
        """Identifier for this game (e.g., "iRacing", "F1_24")"""
        pass

    @abstractmethod
    def validate_data(self, data: NormalizedTelemetry) -> bool:
        """
        Sanity check normalized data (e.g., speed < 500 m/s).
        Returns True if data appears valid.
        """
        pass
