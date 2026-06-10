# CLAUDE.md - RaceCraft Desktop Implementation Guide

## Project Vision

RaceCraft Desktop is a cross-platform racing simulator telemetry collection application with initial focus on iRacing, architected for extensibility to support F1 games, Assetto Corsa Competizione, Gran Turismo 7, and Forza Motorsport. The system provides a unified telemetry API abstracting game-specific protocols (UDP and shared memory) into normalized data structures for consumption by dashboards, analytics tools, and hardware integrations.

The application runs from the system tray as a single integrated process, automatically collecting telemetry during racing sessions and uploading normalized data to a remote server for analysis and storage. Background telemetry collection runs as async tasks within the main application process—there is no separate daemon or service component.

## Architecture Overview

### Architectural Decision: Single Process Design

**RaceCraft Desktop uses a unified single-process architecture**, integrating UI and telemetry collection into one executable. This design choice provides significant advantages over traditional daemon/service architectures:

**Benefits**:
- ✅ Simpler deployment: One executable, one process
- ✅ No IPC complexity: All components share memory
- ✅ Direct UI updates: Background tasks signal UI changes immediately
- ✅ Easier debugging: Single process to attach debugger
- ✅ User session context: Runs in logged-in user's context (required for game access)
- ✅ Natural lifecycle: Starts with user login, exits cleanly

**Implementation**: PyQt6 main thread + asyncio background tasks bridged via `qasync.QEventLoop`

### Core Principles

1. **Single Process Architecture**: UI and background tasks in one integrated application
2. **Protocol Abstraction**: Hide UDP vs shared memory implementation details behind common interfaces
3. **Normalized Data Model**: SI units (m/s, Celsius, meters) with game-specific raw data preserved
4. **Extensible Parsers**: Plugin-based game support without modifying core code
5. **Performance First**: Handle 60-360Hz update rates with minimal latency and memory overhead
6. **Configuration-Driven**: Add games via JSON profiles without code changes
7. **Resilient Operation**: Offline mode, graceful error handling, never crash on bad telemetry

### Technology Stack

**Python 3.11+** chosen for:
- Cross-platform support (Windows primary, macOS/Linux future)
- Mature async/await for high-frequency I/O
- Rich ecosystem (pyirsdk for iRacing, existing F1 parsers)
- Rapid iteration for protocol implementation

**Key Dependencies**:
- `pyirsdk` - iRacing shared memory SDK wrapper
- `asyncio` - Core event loop for concurrent collection
- `pydantic` - Data validation and normalized models
- `msgpack` - Efficient binary serialization
- `fastapi` - HTTP API for telemetry streaming/queries
- `websockets` - Real-time push to connected clients
- `httpx` - Async HTTP client for remote API communication
- `PyQt6` or `tkinter` - System tray UI and settings window
- `pystray` - Cross-platform system tray icon support

### System Components

**IMPORTANT ARCHITECTURAL DECISION**: RaceCraft Desktop uses a **single integrated process** architecture, not a separate daemon. The application runs from the system tray and manages all telemetry collection as background async tasks within the same process. This simplifies deployment, debugging, and state management compared to multi-process architectures.

```
┌─────────────────────────────────────────────────────────────────┐
│              RaceCraft Desktop (Single Process)                  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              UI Layer (Main Thread)                     │    │
│  │  ┌──────────────────────────────────────────────────┐  │    │
│  │  │  System Tray Icon (PyQt6)                        │  │    │
│  │  │    - Shows connection status                     │  │    │
│  │  │    - Menu: Show Window, Settings, Exit          │  │    │
│  │  │    - Notifications for session events           │  │    │
│  │  └──────────────────────────────────────────────────┘  │    │
│  │  ┌──────────────────────────────────────────────────┐  │    │
│  │  │  Main Window (PyQt6)                             │  │    │
│  │  │    - Authentication status (user_id, license)   │  │    │
│  │  │    - Current session info (game, laps, duration)│  │    │
│  │  │    - Upload status (pending, uploading)         │  │    │
│  │  │    - Settings panel (future)                    │  │    │
│  │  └──────────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │         Async Background Tasks (qasync bridge)          │    │
│  │                                                          │    │
│  │  ┌─────────────────────────────────────────────────┐   │    │
│  │  │ Game Detection Task (async, 2s poll)            │   │    │
│  │  │   - Monitor running processes                   │   │    │
│  │  │   - Load game profiles from JSON               │   │    │
│  │  │   - Auto-start/stop telemetry collection       │   │    │
│  │  └─────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌─────────────────────────────────────────────────┐   │    │
│  │  │ Telemetry Collection Task                       │   │    │
│  │  │   - Runs when game detected                     │   │    │
│  │  │   - Reads from SharedMemory or UDP              │   │    │
│  │  │   - Parses game-specific formats               │   │    │
│  │  │   - Normalizes to SI units                     │   │    │
│  │  │   - Queues frames for session manager          │   │    │
│  │  └─────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌─────────────────────────────────────────────────┐   │    │
│  │  │ Session Management Task                         │   │    │
│  │  │   - Detects session start/end                   │   │    │
│  │  │   - Buffers telemetry frames in memory         │   │    │
│  │  │   - Triggers uploads on session end            │   │    │
│  │  │   - Updates UI with session stats              │   │    │
│  │  └─────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌─────────────────────────────────────────────────┐   │    │
│  │  │ Upload Retry Task                               │   │    │
│  │  │   - Polls failed upload queue (5 min)          │   │    │
│  │  │   - Exponential backoff retry logic            │   │    │
│  │  │   - Updates UI with upload status              │   │    │
│  │  └─────────────────────────────────────────────────┘   │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Services (Shared State)                     │    │
│  │                                                          │    │
│  │  - AuthenticationService (httpx async client)           │    │
│  │  - GameDetector (process monitoring)                    │    │
│  │  - TelemetryReader (SharedMemory/UDP - current game)    │    │
│  │  - TelemetryParser (game-specific normalization)        │    │
│  │  - SessionManager (buffering, lifecycle)                │    │
│  │  - UploadService (SQLite queue, retry logic)            │    │
│  │                                                          │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │            Local Storage (Optional Future)               │    │
│  │  - SQLite: Failed upload queue, settings cache          │    │
│  │  - msgpack: Session recordings for replay               │    │
│  │  - Local FastAPI (optional): WebSocket streaming        │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘

Key Architectural Points:
• Single process, single event loop (qasync bridges Qt + asyncio)
• No IPC required - all components share memory
• Background tasks coordinate via asyncio.Queue
• UI updates via Qt signals (thread-safe)
• Simpler deployment: one executable, one system tray process
```

## Data Model Specification

### NormalizedTelemetry (Core Schema)

```python
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional

class Vector3(BaseModel):
    x: float
    y: float
    z: float

class WheelPosition(str, Enum):
    FRONT_LEFT = "FL"
    FRONT_RIGHT = "FR"
    REAR_LEFT = "RL"
    REAR_RIGHT = "RR"

class WheelData(BaseModel):
    position: WheelPosition

    # Temperatures (Celsius)
    tire_surface_temp: Optional[float] = None
    tire_inner_temp: Optional[float] = None
    tire_middle_temp: Optional[float] = None
    tire_outer_temp: Optional[float] = None
    brake_temp: Optional[float] = None

    # Pressures (bar)
    tire_pressure: Optional[float] = None

    # Dynamics
    suspension_travel: Optional[float] = None  # meters
    wheel_speed: Optional[float] = None  # rad/s
    slip_ratio: Optional[float] = None  # percentage
    slip_angle: Optional[float] = None  # radians

    # Wear
    tire_wear: Optional[float] = None  # 0.0-1.0 (0=new, 1=worn)
    brake_wear: Optional[float] = None  # 0.0-1.0

class NormalizedTelemetry(BaseModel):
    # Metadata
    game_name: str
    session_id: str
    timestamp: datetime
    frame_number: int

    # Vehicle dynamics (SI units)
    speed: float  # m/s
    gear: int  # -1=reverse, 0=neutral, 1+=forward
    engine_rpm: float
    engine_max_rpm: Optional[float] = None

    # Driver inputs (normalized 0.0-1.0)
    throttle: float = Field(ge=0.0, le=1.0)
    brake: float = Field(ge=0.0, le=1.0)
    clutch: float = Field(ge=0.0, le=1.0)
    steering: float = Field(ge=-1.0, le=1.0)  # -1.0=full left, 1.0=full right

    # Position and orientation
    position: Vector3  # meters (world coordinates)
    velocity: Vector3  # m/s
    acceleration: Vector3  # m/s²

    # Rotation
    yaw: float  # radians
    pitch: float  # radians
    roll: float  # radians
    yaw_rate: float  # rad/s
    pitch_rate: float  # rad/s
    roll_rate: float  # rad/s

    # G-forces
    g_force_lateral: float  # G
    g_force_longitudinal: float  # G
    g_force_vertical: float  # G

    # Wheels (always FL, FR, RL, RR order)
    wheels: list[WheelData] = Field(min_length=4, max_length=4)

    # Fuel and damage
    fuel_remaining: Optional[float] = None  # liters
    fuel_capacity: Optional[float] = None  # liters
    fuel_laps_remaining: Optional[float] = None

    # Session info
    lap_number: Optional[int] = None
    lap_distance: Optional[float] = None  # meters
    track_length: Optional[float] = None  # meters
    lap_time_current: Optional[float] = None  # seconds
    lap_time_last: Optional[float] = None  # seconds
    lap_time_best: Optional[float] = None  # seconds

    # Flags and status
    in_pit: bool = False
    is_racing: bool = True

    # Game-specific raw data (preserved for advanced use)
    raw_data: Optional[dict] = None

class TelemetryMetadata(BaseModel):
    """Static session information"""
    game_name: str
    track_name: str
    car_name: str
    session_type: str  # "Practice", "Qualifying", "Race", etc.
    session_start_time: datetime
    player_name: Optional[str] = None
    track_length: float  # meters
    track_config: Optional[str] = None
```

## Interface Specifications

### ITelemetryReader (Protocol Abstract Base)

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
import asyncio

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
```

### ITelemetryParser (Game-Specific Parsing)

```python
from abc import ABC, abstractmethod
from typing import Optional

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
```

## iRacing Implementation (PRIORITY)

### Overview

iRacing provides the most sophisticated telemetry system via shared memory mapped file `Local\IRSDKMemMapFileName`. The pyirsdk library handles low-level access, providing 300+ telemetry variables at 60Hz (configurable to 360Hz).

### IRacingReader Implementation

```python
import asyncio
import irsdk
from typing import AsyncIterator, Optional
import time

class IRacingReader(ITelemetryReader):
    """Shared memory reader for iRacing using pyirsdk"""

    def __init__(self, update_rate: int = 60):
        self._ir = irsdk.IRSDK()
        self._connected = False
        self._update_rate = update_rate
        self._poll_interval = 1.0 / update_rate
        self._stop_event = asyncio.Event()

    async def connect(self) -> bool:
        """Connect to iRacing shared memory"""
        return await asyncio.to_thread(self._ir.startup)

    async def disconnect(self) -> None:
        """Shutdown iRacing connection"""
        self._stop_event.set()
        await asyncio.to_thread(self._ir.shutdown)
        self._connected = False

    async def read_telemetry(self) -> AsyncIterator[bytes]:
        """
        Continuously read iRacing telemetry at configured rate.
        Yields serialized dict of all telemetry variables.
        """
        while not self._stop_event.is_set():
            if not self._ir.is_initialized:
                await asyncio.sleep(1.0)  # Wait for iRacing to start
                continue

            # pyirsdk returns dict, serialize to bytes for interface compliance
            data = await asyncio.to_thread(self._ir.get)
            if data:
                yield msgpack.packb(data)

            await asyncio.sleep(self._poll_interval)

    def is_connected(self) -> bool:
        return self._ir.is_initialized

    @property
    def update_rate(self) -> int:
        return self._update_rate
```

### IRacingParser Implementation

```python
import msgpack
from typing import Optional

class IRacingParser(ITelemetryParser):
    """Parse iRacing telemetry into normalized format"""

    def __init__(self):
        self._session_info: Optional[dict] = None

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        """Convert iRacing dict to NormalizedTelemetry"""
        try:
            data = msgpack.unpackb(raw_data)

            # iRacing wheel order: [LF, RF, LR, RR]
            # Normalize to: [FL, FR, RL, RR]
            wheels = [
                WheelData(
                    position=WheelPosition.FRONT_LEFT,
                    tire_surface_temp=data.get('LFtempCL'),  # Left front center temp
                    tire_inner_temp=data.get('LFtempCL'),
                    tire_middle_temp=data.get('LFtempCM'),
                    tire_outer_temp=data.get('LFtempCR'),
                    tire_pressure=data.get('LFpressure'),
                    tire_wear=data.get('LFwearL'),  # Average wear
                    wheel_speed=data.get('LFrpm', 0) * 0.10472,  # RPM to rad/s
                ),
                WheelData(
                    position=WheelPosition.FRONT_RIGHT,
                    tire_surface_temp=data.get('RFtempCL'),
                    tire_inner_temp=data.get('RFtempCL'),
                    tire_middle_temp=data.get('RFtempCM'),
                    tire_outer_temp=data.get('RFtempCR'),
                    tire_pressure=data.get('RFpressure'),
                    tire_wear=data.get('RFwearL'),
                    wheel_speed=data.get('RFrpm', 0) * 0.10472,
                ),
                WheelData(
                    position=WheelPosition.REAR_LEFT,
                    tire_surface_temp=data.get('LRtempCL'),
                    tire_inner_temp=data.get('LRtempCL'),
                    tire_middle_temp=data.get('LRtempCM'),
                    tire_outer_temp=data.get('LRtempCR'),
                    tire_pressure=data.get('LRpressure'),
                    tire_wear=data.get('LRwearL'),
                    wheel_speed=data.get('LRrpm', 0) * 0.10472,
                ),
                WheelData(
                    position=WheelPosition.REAR_RIGHT,
                    tire_surface_temp=data.get('RRtempCL'),
                    tire_inner_temp=data.get('RRtempCL'),
                    tire_middle_temp=data.get('RRtempCM'),
                    tire_outer_temp=data.get('RRtempCR'),
                    tire_pressure=data.get('RRpressure'),
                    tire_wear=data.get('RRwearL'),
                    wheel_speed=data.get('RRrpm', 0) * 0.10472,
                ),
            ]

            return NormalizedTelemetry(
                game_name="iRacing",
                session_id=str(data.get('SessionUniqueID', 0)),
                timestamp=datetime.utcnow(),
                frame_number=data.get('SessionTick', 0),

                # Vehicle dynamics (iRacing uses m/s for speed already)
                speed=data.get('Speed', 0.0),
                gear=data.get('Gear', 0),
                engine_rpm=data.get('RPM', 0.0),
                engine_max_rpm=data.get('EngineWarnings', {}).get('RPMWarnLevel'),

                # Driver inputs (iRacing already 0.0-1.0 normalized)
                throttle=data.get('Throttle', 0.0),
                brake=data.get('Brake', 0.0),
                clutch=data.get('Clutch', 0.0),
                steering=data.get('SteeringWheelAngle', 0.0) / data.get('SteeringWheelAngleMax', 1.0),

                # Position (iRacing provides world coordinates)
                position=Vector3(
                    x=data.get('PosX', 0.0),
                    y=data.get('PosY', 0.0),
                    z=data.get('PosZ', 0.0)
                ),
                velocity=Vector3(
                    x=data.get('VelocityX', 0.0),
                    y=data.get('VelocityY', 0.0),
                    z=data.get('VelocityZ', 0.0)
                ),
                acceleration=Vector3(
                    x=data.get('AccelX', 0.0),
                    y=data.get('AccelY', 0.0),
                    z=data.get('AccelZ', 0.0)
                ),

                # Rotation
                yaw=data.get('Yaw', 0.0),
                pitch=data.get('Pitch', 0.0),
                roll=data.get('Roll', 0.0),
                yaw_rate=data.get('YawRate', 0.0),
                pitch_rate=data.get('PitchRate', 0.0),
                roll_rate=data.get('RollRate', 0.0),

                # G-forces (iRacing provides in G units)
                g_force_lateral=data.get('LatAccel', 0.0),
                g_force_longitudinal=data.get('LongAccel', 0.0),
                g_force_vertical=data.get('VertAccel', 0.0),

                wheels=wheels,

                # Fuel
                fuel_remaining=data.get('FuelLevel', 0.0),
                fuel_capacity=data.get('FuelCapacity'),
                fuel_laps_remaining=data.get('FuelLapsRemaining'),

                # Session
                lap_number=data.get('Lap', 0),
                lap_distance=data.get('LapDist', 0.0),
                lap_time_current=data.get('LapCurrentLapTime', 0.0),
                lap_time_last=data.get('LapLastLapTime'),
                lap_time_best=data.get('LapBestLapTime'),

                in_pit=data.get('OnPitRoad', False),
                is_racing=data.get('IsOnTrack', False),

                raw_data=data  # Preserve full iRacing data
            )
        except Exception as e:
            # Log error, return None to skip invalid frame
            return None

    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        """Extract iRacing session info from YAML"""
        # In real implementation, parse YAML from ir['SessionInfo']
        # This is called once at session start
        return None  # Simplified for example

    @property
    def game_name(self) -> str:
        return "iRacing"

    def validate_data(self, data: NormalizedTelemetry) -> bool:
        """Sanity check iRacing data"""
        # Speed check (500 m/s = ~1100 mph, impossible for cars)
        if data.speed > 500.0 or data.speed < 0:
            return False

        # RPM check
        if data.engine_rpm < 0 or data.engine_rpm > 20000:
            return False

        # Input validation (should be normalized)
        if not (0.0 <= data.throttle <= 1.0):
            return False

        return True
```

### Game Detection

```python
import psutil
import asyncio
from typing import Optional

class GameDetector:
    """Detect running racing games and instantiate appropriate readers"""

    GAME_CONFIGS = {
        "iRacingSim64DX11.exe": {
            "name": "iRacing",
            "reader_class": IRacingReader,
            "parser_class": IRacingParser,
            "protocol": "shared_memory"
        },
        # Future games added here
    }

    def __init__(self):
        self._current_game: Optional[str] = None

    async def detect_active_game(self) -> Optional[dict]:
        """
        Poll running processes to find active racing game.
        Returns config dict if found, None otherwise.
        """
        for proc in psutil.process_iter(['name']):
            try:
                proc_name = proc.info['name']
                if proc_name in self.GAME_CONFIGS:
                    self._current_game = proc_name
                    return self.GAME_CONFIGS[proc_name]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        self._current_game = None
        return None

    async def monitor_games(self, callback, poll_interval: float = 2.0):
        """
        Continuously monitor for game starts/stops.
        Calls callback(game_config) when game detected.
        Calls callback(None) when game exits.
        """
        last_detected = None

        while True:
            current = await self.detect_active_game()

            if current != last_detected:
                await callback(current)
                last_detected = current

            await asyncio.sleep(poll_interval)
```

### Core Daemon

```python
import asyncio
from typing import Optional

class RaceCraftDaemon:
    """Main daemon coordinating telemetry collection"""

    def __init__(self):
        self.detector = GameDetector()
        self.reader: Optional[ITelemetryReader] = None
        self.parser: Optional[ITelemetryParser] = None
        self.telemetry_queue = asyncio.Queue(maxsize=1000)
        self._running = False

    async def start(self):
        """Start the daemon"""
        self._running = True

        # Start game detection
        asyncio.create_task(self.detector.monitor_games(self._on_game_changed))

        # Start processing pipeline
        asyncio.create_task(self._process_telemetry())

        print("RaceCraft Daemon started. Waiting for racing games...")

    async def _on_game_changed(self, game_config: Optional[dict]):
        """Called when game starts or stops"""
        # Stop existing reader
        if self.reader:
            await self.reader.disconnect()
            self.reader = None
            self.parser = None
            print("Game disconnected")

        # Start new reader
        if game_config:
            self.reader = game_config['reader_class']()
            self.parser = game_config['parser_class']()

            if await self.reader.connect():
                print(f"Connected to {game_config['name']}")
                asyncio.create_task(self._collect_telemetry())
            else:
                print(f"Failed to connect to {game_config['name']}")

    async def _collect_telemetry(self):
        """Read raw telemetry and parse into queue"""
        async for raw_data in self.reader.read_telemetry():
            telemetry = self.parser.parse(raw_data)

            if telemetry and self.parser.validate_data(telemetry):
                try:
                    self.telemetry_queue.put_nowait(telemetry)
                except asyncio.QueueFull:
                    # Drop frame if queue full (backpressure)
                    pass

    async def _process_telemetry(self):
        """Consume telemetry queue and distribute to outputs"""
        while self._running:
            telemetry = await self.telemetry_queue.get()

            # TODO: Forward to WebSocket clients
            # TODO: Write to storage if recording
            # TODO: Export to other formats

            # For now, just log
            print(f"Frame {telemetry.frame_number}: {telemetry.speed:.1f} m/s, "
                  f"Gear {telemetry.gear}, RPM {telemetry.engine_rpm:.0f}")
```

### FastAPI Integration

```python
from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
import json

app = FastAPI(title="RaceCraft API")
daemon = RaceCraftDaemon()

@app.on_event("startup")
async def startup():
    await daemon.start()

@app.get("/api/status")
async def get_status():
    """Get current daemon status"""
    return {
        "running": daemon._running,
        "game_connected": daemon.reader is not None,
        "game_name": daemon.parser.game_name if daemon.parser else None,
        "queue_size": daemon.telemetry_queue.qsize()
    }

@app.get("/api/telemetry/current")
async def get_current_telemetry():
    """Get most recent telemetry frame"""
    if daemon.telemetry_queue.empty():
        return {"error": "No telemetry available"}

    # Peek most recent without blocking
    telemetry = daemon.telemetry_queue._queue[-1]
    return telemetry.model_dump()

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """Stream telemetry via WebSocket"""
    await websocket.accept()

    # Subscribe to telemetry updates
    queue = asyncio.Queue()

    try:
        while True:
            telemetry = await daemon.telemetry_queue.get()
            await websocket.send_json(telemetry.model_dump())
    except Exception as e:
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## UI Architecture

### Overview

RaceCraft Desktop provides a minimal, non-intrusive UI that runs in the system tray. The application shows a main window on first startup for authentication, then minimizes to the tray for ongoing background operation. Users can restore the window at any time via the tray icon.

### Technology Choice: PyQt6

**Recommendation**: Use PyQt6 for the UI framework due to:
- Native Windows appearance and performance
- Excellent system tray support
- Built-in threading for async integration
- Rich widget library for settings panels
- Cross-platform (future macOS/Linux support)

**Alternative**: `tkinter` is lighter weight but has limited tray support and dated appearance.

### System Tray Icon

```python
# racecraft/ui/tray.py
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject, pyqtSignal

class RaceCraftTray(QObject):
    """System tray icon with menu"""

    show_window_signal = pyqtSignal()
    exit_signal = pyqtSignal()

    def __init__(self, icon_path: str):
        super().__init__()
        self.tray = QSystemTrayIcon(QIcon(icon_path))

        # Create menu
        menu = QMenu()

        show_action = QAction("Show RaceCraft", menu)
        show_action.triggered.connect(self.show_window_signal.emit)
        menu.addAction(show_action)

        menu.addSeparator()

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(self.exit_signal.emit)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    def show(self):
        """Show tray icon"""
        self.tray.show()

    def update_status(self, status: str):
        """Update tooltip with current status"""
        self.tray.setToolTip(f"RaceCraft - {status}")

    def show_notification(self, title: str, message: str):
        """Show system notification"""
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def _on_tray_activated(self, reason):
        """Handle tray icon click"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window_signal.emit()

    def _open_settings(self):
        # TODO: Open settings dialog
        pass
```

### Main UI Window

```python
# racecraft/ui/main_window.py
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QGroupBox, QStatusBar)
from PyQt6.QtCore import Qt, pyqtSlot
from datetime import datetime

class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RaceCraft Desktop")
        self.setMinimumSize(500, 400)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Authentication section
        auth_group = self._create_auth_section()
        layout.addWidget(auth_group)

        # Current session section
        session_group = self._create_session_section()
        layout.addWidget(session_group)

        # Upload status section
        upload_group = self._create_upload_section()
        layout.addWidget(upload_group)

        # Stretch to push sections to top
        layout.addStretch()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _create_auth_section(self) -> QGroupBox:
        """Create authentication status section"""
        group = QGroupBox("Authentication")
        layout = QVBoxLayout()

        self.user_id_label = QLabel("User ID: Not authenticated")
        self.license_label = QLabel("License: None")
        self.auth_status_label = QLabel("Status: Checking...")

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self._on_login_clicked)

        layout.addWidget(self.user_id_label)
        layout.addWidget(self.license_label)
        layout.addWidget(self.auth_status_label)
        layout.addWidget(self.login_button)

        group.setLayout(layout)
        return group

    def _create_session_section(self) -> QGroupBox:
        """Create current session info section"""
        group = QGroupBox("Current Session")
        layout = QVBoxLayout()

        self.game_label = QLabel("Game: None")
        self.track_label = QLabel("Track: None")
        self.lap_label = QLabel("Laps: 0")
        self.duration_label = QLabel("Duration: 00:00:00")
        self.frames_label = QLabel("Frames collected: 0")

        layout.addWidget(self.game_label)
        layout.addWidget(self.track_label)
        layout.addWidget(self.lap_label)
        layout.addWidget(self.duration_label)
        layout.addWidget(self.frames_label)

        group.setLayout(layout)
        return group

    def _create_upload_section(self) -> QGroupBox:
        """Create upload status section"""
        group = QGroupBox("Upload Status")
        layout = QVBoxLayout()

        self.upload_status_label = QLabel("Status: No sessions pending")
        self.last_upload_label = QLabel("Last upload: Never")
        self.pending_count_label = QLabel("Pending sessions: 0")

        layout.addWidget(self.upload_status_label)
        layout.addWidget(self.last_upload_label)
        layout.addWidget(self.pending_count_label)

        group.setLayout(layout)
        return group

    @pyqtSlot(dict)
    def update_auth_status(self, auth_data: dict):
        """Update authentication UI"""
        self.user_id_label.setText(f"User ID: {auth_data.get('user_id', 'Unknown')}")
        self.license_label.setText(f"License: {auth_data.get('license_tier', 'Free')}")

        if auth_data.get('authorized'):
            self.auth_status_label.setText("Status: ✓ Authenticated")
            self.auth_status_label.setStyleSheet("color: green;")
            self.login_button.setEnabled(False)
        else:
            self.auth_status_label.setText("Status: ✗ Not authenticated")
            self.auth_status_label.setStyleSheet("color: red;")
            self.login_button.setEnabled(True)

    @pyqtSlot(dict)
    def update_session_info(self, session_data: dict):
        """Update current session UI"""
        self.game_label.setText(f"Game: {session_data.get('game_name', 'None')}")
        self.track_label.setText(f"Track: {session_data.get('track_name', 'None')}")
        self.lap_label.setText(f"Laps: {session_data.get('lap_count', 0)}")

        duration = session_data.get('duration_seconds', 0)
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.duration_label.setText(f"Duration: {int(hours):02}:{int(minutes):02}:{int(seconds):02}")

        self.frames_label.setText(f"Frames collected: {session_data.get('frame_count', 0):,}")

    @pyqtSlot(dict)
    def update_upload_status(self, upload_data: dict):
        """Update upload status UI"""
        status = upload_data.get('status', 'idle')

        if status == 'uploading':
            self.upload_status_label.setText("Status: ⏳ Uploading session...")
            self.upload_status_label.setStyleSheet("color: orange;")
        elif status == 'complete':
            self.upload_status_label.setText("Status: ✓ Upload complete")
            self.upload_status_label.setStyleSheet("color: green;")
        elif status == 'failed':
            self.upload_status_label.setText("Status: ✗ Upload failed (retrying)")
            self.upload_status_label.setStyleSheet("color: red;")
        else:
            self.upload_status_label.setText("Status: No sessions pending")
            self.upload_status_label.setStyleSheet("")

        if upload_data.get('last_upload_time'):
            self.last_upload_label.setText(f"Last upload: {upload_data['last_upload_time']}")

        self.pending_count_label.setText(f"Pending sessions: {upload_data.get('pending_count', 0)}")

    def closeEvent(self, event):
        """Override close to minimize to tray instead of exit"""
        event.ignore()
        self.hide()

    def _on_login_clicked(self):
        # TODO: Open login dialog or browser
        pass
```

### Authentication Flow

```python
# racecraft/auth.py
import httpx
from typing import Optional
from pydantic import BaseModel
import keyring
import uuid

class AuthCredentials(BaseModel):
    user_id: str
    api_key: str
    license_tier: str

class AuthenticationService:
    """Handle authentication with remote server"""

    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url
        self.client = httpx.AsyncClient(timeout=10.0)
        self._credentials: Optional[AuthCredentials] = None

    async def validate_on_startup(self) -> Optional[AuthCredentials]:
        """
        Called on app startup to validate stored credentials.
        If no credentials exist, prompt user to login.
        """
        # Try to load stored credentials
        stored_key = keyring.get_password("racecraft", "api_key")

        if not stored_key:
            # First run - need to authenticate
            return await self._initial_authentication()

        # Validate existing credentials
        try:
            response = await self.client.get(
                f"{self.api_base_url}/api/auth/validate",
                headers={"X-API-Key": stored_key}
            )

            if response.status_code == 200:
                data = response.json()
                self._credentials = AuthCredentials(
                    user_id=data['user_id'],
                    api_key=stored_key,
                    license_tier=data['license_tier']
                )
                return self._credentials
            else:
                # Invalid credentials - need to re-authenticate
                keyring.delete_password("racecraft", "api_key")
                return await self._initial_authentication()

        except Exception as e:
            print(f"Validation error: {e}")
            return None

    async def _initial_authentication(self) -> Optional[AuthCredentials]:
        """
        First-time authentication flow.
        Generate device_id, request API key from server.
        """
        device_id = self._get_or_create_device_id()

        try:
            # Request authentication
            response = await self.client.post(
                f"{self.api_base_url}/api/auth/device/register",
                json={"device_id": device_id}
            )

            if response.status_code == 200:
                data = response.json()

                # Store API key securely
                keyring.set_password("racecraft", "api_key", data['api_key'])

                self._credentials = AuthCredentials(
                    user_id=data['user_id'],
                    api_key=data['api_key'],
                    license_tier=data.get('license_tier', 'free')
                )

                return self._credentials
            elif response.status_code == 403:
                # Device/user not authorized
                print("Authorization required. Visit dashboard to enable this device.")
                return None
            else:
                print(f"Authentication failed: {response.status_code}")
                return None

        except Exception as e:
            print(f"Authentication error: {e}")
            return None

    def _get_or_create_device_id(self) -> str:
        """Get or create unique device ID"""
        device_id = keyring.get_password("racecraft", "device_id")

        if not device_id:
            device_id = str(uuid.uuid4())
            keyring.set_password("racecraft", "device_id", device_id)

        return device_id

    @property
    def user_id(self) -> Optional[str]:
        return self._credentials.user_id if self._credentials else None

    @property
    def is_authenticated(self) -> bool:
        return self._credentials is not None
```

### Session Upload Service

```python
# racecraft/upload.py
import httpx
import asyncio
from typing import List
from datetime import datetime
import sqlite3
from pathlib import Path

class UploadService:
    """Handle uploading completed sessions to remote server"""

    def __init__(self, api_base_url: str, auth_service: AuthenticationService):
        self.api_base_url = api_base_url
        self.auth = auth_service
        self.client = httpx.AsyncClient(timeout=30.0)
        self.upload_queue = asyncio.Queue()
        self._init_failed_upload_db()

    def _init_failed_upload_db(self):
        """Initialize SQLite DB for failed uploads"""
        db_path = Path.home() / ".racecraft" / "upload_queue.db"
        db_path.parent.mkdir(exist_ok=True)

        self.db_conn = sqlite3.connect(str(db_path))
        self.db_conn.execute("""
            CREATE TABLE IF NOT EXISTS upload_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE,
                session_data BLOB,
                created_at TIMESTAMP,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT
            )
        """)
        self.db_conn.commit()

    async def upload_session(self, session_id: str, telemetry_frames: List[dict]):
        """
        Upload a completed session to remote server.
        Automatically retries with exponential backoff on failure.
        """
        if not self.auth.is_authenticated:
            print("Cannot upload - not authenticated")
            return False

        payload = {
            "session_id": session_id,
            "user_id": self.auth.user_id,
            "frames": telemetry_frames,
            "uploaded_at": datetime.utcnow().isoformat()
        }

        try:
            response = await self.client.post(
                f"{self.api_base_url}/api/sessions/upload",
                headers={"X-API-Key": self.auth._credentials.api_key},
                json=payload
            )

            if response.status_code == 200:
                print(f"Session {session_id} uploaded successfully")
                self._remove_from_queue(session_id)
                return True
            else:
                print(f"Upload failed: {response.status_code} - {response.text}")
                self._queue_for_retry(session_id, payload, str(response.text))
                return False

        except Exception as e:
            print(f"Upload error: {e}")
            self._queue_for_retry(session_id, payload, str(e))
            return False

    def _queue_for_retry(self, session_id: str, payload: dict, error: str):
        """Add failed upload to retry queue"""
        import msgpack

        self.db_conn.execute(
            """INSERT OR REPLACE INTO upload_queue
               (session_id, session_data, created_at, retry_count, last_error)
               VALUES (?, ?, ?, COALESCE((SELECT retry_count FROM upload_queue WHERE session_id = ?) + 1, 0), ?)""",
            (session_id, msgpack.packb(payload), datetime.utcnow(), session_id, error)
        )
        self.db_conn.commit()

    def _remove_from_queue(self, session_id: str):
        """Remove successful upload from queue"""
        self.db_conn.execute("DELETE FROM upload_queue WHERE session_id = ?", (session_id,))
        self.db_conn.commit()

    async def retry_failed_uploads(self):
        """Background task to retry failed uploads"""
        while True:
            cursor = self.db_conn.execute(
                "SELECT session_id, session_data, retry_count FROM upload_queue ORDER BY created_at LIMIT 5"
            )

            for row in cursor.fetchall():
                session_id, data_blob, retry_count = row

                # Exponential backoff: wait 2^retry_count minutes (max 60 min)
                wait_minutes = min(2 ** retry_count, 60)
                print(f"Retrying upload for {session_id} (attempt {retry_count + 1})")

                import msgpack
                payload = msgpack.unpackb(data_blob)

                success = await self.upload_session(session_id, payload['frames'])

                if not success and retry_count > 10:
                    # Give up after 10 retries
                    print(f"Giving up on session {session_id} after 10 retries")
                    self._remove_from_queue(session_id)

            # Check for failed uploads every 5 minutes
            await asyncio.sleep(300)

    def get_pending_count(self) -> int:
        """Get count of pending uploads"""
        cursor = self.db_conn.execute("SELECT COUNT(*) FROM upload_queue")
        return cursor.fetchone()[0]
```

### Session Manager Integration

```python
# racecraft/session_manager.py
from typing import Optional, List
from datetime import datetime
import asyncio

class SessionManager:
    """Manage racing sessions and trigger uploads"""

    def __init__(self, upload_service: UploadService):
        self.upload_service = upload_service
        self.current_session: Optional[dict] = None
        self.telemetry_buffer: List[dict] = []

    def start_session(self, metadata: TelemetryMetadata):
        """Called when new session detected"""
        self.current_session = {
            "session_id": f"{metadata.game_name}_{int(datetime.utcnow().timestamp())}",
            "game_name": metadata.game_name,
            "track_name": metadata.track_name,
            "start_time": datetime.utcnow(),
            "metadata": metadata.model_dump()
        }
        self.telemetry_buffer = []
        print(f"Session started: {self.current_session['session_id']}")

    def add_telemetry_frame(self, telemetry: NormalizedTelemetry):
        """Add telemetry frame to current session buffer"""
        if self.current_session:
            # Convert to dict and store (sampling can happen here)
            self.telemetry_buffer.append(telemetry.model_dump())

    async def end_session(self):
        """Called when session ends - trigger upload"""
        if not self.current_session or not self.telemetry_buffer:
            return

        print(f"Session ended. Collected {len(self.telemetry_buffer)} frames")

        # Upload in background (non-blocking)
        asyncio.create_task(
            self.upload_service.upload_session(
                self.current_session['session_id'],
                self.telemetry_buffer
            )
        )

        # Clear current session
        self.current_session = None
        self.telemetry_buffer = []

    def detect_session_end(self, telemetry: NormalizedTelemetry) -> bool:
        """
        Heuristic to detect session end.
        Returns True if session should end.
        """
        # Session ends when:
        # - Game disconnects (handled elsewhere)
        # - Player returns to pit/menu (is_racing=False for >30 seconds)
        # - Long period of inactivity

        if not telemetry.is_racing:
            # TODO: Implement timeout logic
            return False

        return False
```

### UI Integration with Daemon

```python
# racecraft/app.py
import sys
import asyncio
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal
from qasync import QEventLoop  # Bridge between asyncio and Qt

class DaemonThread(QThread):
    """Run daemon in separate thread"""

    auth_updated = pyqtSignal(dict)
    session_updated = pyqtSignal(dict)
    upload_updated = pyqtSignal(dict)

    def __init__(self, daemon: RaceCraftDaemon):
        super().__init__()
        self.daemon = daemon

    def run(self):
        """Run daemon event loop"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.daemon.start())

class RaceCraftApp:
    """Main application coordinator"""

    def __init__(self):
        self.qt_app = QApplication(sys.argv)

        # Use qasync for asyncio/Qt integration
        self.loop = QEventLoop(self.qt_app)
        asyncio.set_event_loop(self.loop)

        # Create services
        self.auth = AuthenticationService("https://api.racecraft.example.com")
        self.upload = UploadService("https://api.racecraft.example.com", self.auth)
        self.daemon = RaceCraftDaemon()
        self.session_manager = SessionManager(self.upload)

        # Create UI
        self.main_window = MainWindow()
        self.tray = RaceCraftTray("assets/icon.png")

        # Connect signals
        self.tray.show_window_signal.connect(self.main_window.show)
        self.tray.exit_signal.connect(self._on_exit)

    async def start(self):
        """Start the application"""
        # Authenticate on startup
        credentials = await self.auth.validate_on_startup()

        if credentials:
            self.main_window.update_auth_status({
                "user_id": credentials.user_id,
                "license_tier": credentials.license_tier,
                "authorized": True
            })
            self.tray.update_status("Authenticated")
        else:
            self.main_window.update_auth_status({"authorized": False})
            self.tray.update_status("Not authenticated")
            # Show window to prompt login
            self.main_window.show()

        # Start daemon
        await self.daemon.start()

        # Start background services
        asyncio.create_task(self.upload.retry_failed_uploads())

        # Show tray icon
        self.tray.show()

        # Start with window hidden if authenticated
        if credentials:
            self.main_window.hide()
        else:
            self.main_window.show()

    def _on_exit(self):
        """Clean shutdown"""
        self.qt_app.quit()

def main():
    app = RaceCraftApp()

    with app.loop:
        app.loop.run_until_complete(app.start())
        app.loop.run_forever()

if __name__ == "__main__":
    main()
```

## Configuration System

### Game Profiles (JSON)

```json
{
  "games": [
    {
      "id": "iracing",
      "name": "iRacing",
      "enabled": true,
      "process_names": ["iRacingSim64DX11.exe", "iRacingSimDX11.exe"],
      "protocol": "shared_memory",
      "memory_map_name": "Local\\IRSDKMemMapFileName",
      "update_rate": 60,
      "reader_class": "IRacingReader",
      "parser_class": "IRacingParser"
    },
    {
      "id": "f1_24",
      "name": "F1 24",
      "enabled": false,
      "process_names": ["F1_24.exe"],
      "protocol": "udp",
      "port": 20777,
      "update_rate": 60,
      "reader_class": "UDPReader",
      "parser_class": "F1_24_Parser"
    }
  ],
  "daemon": {
    "detection_interval": 2.0,
    "queue_max_size": 1000,
    "api_port": 8000,
    "recording_enabled": false,
    "recording_path": "./recordings"
  }
}
```

## Future Game Implementations

### F1 24 (UDP Protocol)

**Protocol**: UDP packets on port 20777, 15 packet types with common 29-byte header

**Key Implementation Notes**:
- Multi-packet system: Motion (ID 0), Telemetry (ID 6), Car Status (ID 7), Session (ID 1), Lap Data (ID 2)
- Packet correlation via `m_header.m_sessionUID` and `m_header.m_frameIdentifier`
- Little-endian binary parsing with packed structs (no padding)
- Wheel order: [RL, RR, FL, FR] - requires reordering for normalization
- Version detection via `m_header.m_packetFormat` field

**Parser Skeleton**:
```python
class F1_24_Parser(ITelemetryParser):
    def __init__(self):
        self.motion_packet = None
        self.telemetry_packet = None
        self.car_status_packet = None

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        # Read header (first 29 bytes)
        packet_id = struct.unpack('<B', raw_data[5:6])[0]

        # Route to packet-specific parser
        if packet_id == 0:
            self.motion_packet = self._parse_motion(raw_data)
        elif packet_id == 6:
            self.telemetry_packet = self._parse_telemetry(raw_data)
        elif packet_id == 7:
            self.car_status_packet = self._parse_car_status(raw_data)

        # Combine packets into normalized telemetry
        if all([self.motion_packet, self.telemetry_packet]):
            return self._merge_packets()

        return None
```

**Reader**: Use `UDPReader` base class binding to port 20777

**Challenges**:
- Packet loss detection via sequence gaps
- Correlating 15 packet types with frame identifiers
- Version compatibility (F1 23, F1 24, F1 25 have different formats)

**Libraries**:
- `f1-telemetry-client` (TypeScript) - reference for packet structures
- `f1-packets` (Python) - MIT licensed parser

---

### Assetto Corsa Competizione (Shared Memory)

**Protocol**: Three Windows memory-mapped files updated at different rates

**Memory Map Names**:
- `Local\acpmf_physics` - Physics data at ~333Hz
- `Local\acpmf_graphics` - Graphics/session data at ~60Hz
- `Local\acpmf_static` - Static configuration (read once)

**Key Implementation Notes**:
- Ultra-low latency (333Hz for physics)
- Windows-only (shared memory cannot cross network)
- No in-game configuration needed
- Struct-based binary data with C# memory layout

**Parser Skeleton**:
```python
class ACCParser(ITelemetryParser):
    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        # raw_data contains dict with 'physics', 'graphics', 'static' keys
        data = msgpack.unpackb(raw_data)

        physics = data['physics']
        graphics = data['graphics']

        # ACC wheel order: [FL, FR, RL, RR] (already correct)
        wheels = [
            WheelData(
                position=WheelPosition.FRONT_LEFT,
                tire_surface_temp=physics['tyreTempC'][0],
                tire_pressure=physics['wheelsPressure'][0],
                suspension_travel=physics['suspensionTravel'][0],
                brake_temp=physics['brakeTemp'][0]
            ),
            # ... FR, RL, RR
        ]

        return NormalizedTelemetry(...)
```

**Reader**: Extend `SharedMemoryReader` to open three separate memory maps

**Challenges**:
- Synchronizing three update rates (333Hz, 60Hz, static)
- Avoiding torn reads during concurrent writes (sequence number checking)
- Windows-only platform dependency

**Libraries**:
- `PyAccSharedMemory` (Python)
- `acc_shared_memory_rs` (Rust) - reference for struct layouts

---

### Gran Turismo 7 (Encrypted UDP)

**Protocol**: UDP on port 33740 with Salsa20 encryption, requires heartbeat

**Key Implementation Notes**:
- Heartbeat required: Send 'A'/'B'/'~' to console IP every ~1.6s
- Salsa20 decryption with key `"Simulator Interface Packet GT7 ver 0.0"`
- IV/nonce from packet XOR'd with 0xDEADBEAF magic constant
- 296/316/344-byte packets at 60Hz
- Console-only (PS4/PS5), no PC version

**Parser Skeleton**:
```python
from Crypto.Cipher import Salsa20

class GT7Parser(ITelemetryParser):
    DECRYPTION_KEY = b"Simulator Interface Packet GT7 ver 0.0"

    def _decrypt_packet(self, encrypted: bytes) -> bytes:
        magic = 0xDEADBEAF
        iv = struct.unpack('<I', encrypted[0x40:0x44])[0]
        nonce = (iv ^ magic).to_bytes(8, 'little')

        cipher = Salsa20.new(key=self.DECRYPTION_KEY, nonce=nonce)
        return cipher.decrypt(encrypted)

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        decrypted = self._decrypt_packet(raw_data)

        # Parse binary struct (positions documented by community)
        speed = struct.unpack('<f', decrypted[0x4C:0x50])[0]
        rpm = struct.unpack('<f', decrypted[0x3C:0x40])[0]
        # ... rest of parsing
```

**Reader**: `UDPReader` with heartbeat sender task

**Challenges**:
- Reverse-engineered protocol (no official docs)
- Encryption/decryption overhead
- Heartbeat timing critical (expires if missed)
- Console networking setup (static IP, port forwarding)

**Libraries**:
- `gt7dashboard` (Python)
- `gt7telemetry` (Python) - reference for packet structure

---

### Forza Motorsport (Unencrypted UDP)

**Protocol**: UDP on port 9999 (configurable), two formats (Dash/Sled)

**Key Implementation Notes**:
- Enable via HUD Options → Data Out in-game
- Dash format: 311 bytes, 60Hz, comprehensive telemetry
- Sled format: 232 bytes, motion platform focus
- Official documentation available at support.forzamotorsport.net
- Single listener limitation (port exclusivity)

**Parser Skeleton**:
```python
class ForzaParser(ITelemetryParser):
    DASH_FORMAT_SIZE = 311

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        if len(raw_data) != self.DASH_FORMAT_SIZE:
            return None

        # Official packet structure (little-endian)
        # Byte offsets documented by Forza
        speed = struct.unpack('<f', raw_data[244:248])[0]  # m/s
        rpm = struct.unpack('<f', raw_data[16:20])[0]
        gear = struct.unpack('<B', raw_data[307:308])[0]

        # Wheel data (4x floats for each metric)
        tire_slip_FL = struct.unpack('<f', raw_data[120:124])[0]
        # ... parse remaining wheel data
```

**Reader**: `UDPReader` binding to port 9999 (default)

**Challenges**:
- Port exclusivity (only one app can listen)
- Multiple Forza versions with slightly different formats
- Xbox console support requires network configuration

**Libraries**:
- `forza-data-tools` (Go) - reference implementation

---

### Implementation Priority Order

1. **iRacing** (PRIORITY) - Most sophisticated, best SDK, active community
2. **F1 24** - Excellent documentation, UDP simplicity, wide user base
3. **ACC** - High-performance shared memory, popular sim
4. **Forza Motorsport** - Official docs, console crossover appeal
5. **Gran Turismo 7** - Console exclusive, encryption complexity

## Testing Strategy

### Unit Testing

```python
# tests/test_parsers.py
import pytest
from racecraft.parsers import IRacingParser

def test_iracing_parser_valid_data():
    """Test parsing valid iRacing telemetry"""
    parser = IRacingParser()

    # Load recorded binary sample
    with open('tests/fixtures/iracing_frame.msgpack', 'rb') as f:
        raw_data = f.read()

    telemetry = parser.parse(raw_data)

    assert telemetry is not None
    assert telemetry.game_name == "iRacing"
    assert 0.0 <= telemetry.speed <= 150.0  # Reasonable range
    assert len(telemetry.wheels) == 4

def test_iracing_parser_validates_data():
    """Test data validation catches impossible values"""
    parser = IRacingParser()

    # Create invalid telemetry (speed > 500 m/s)
    bad_data = create_telemetry(speed=600.0)

    assert not parser.validate_data(bad_data)
```

### Recording Real Game Data

Create test fixtures by recording actual game UDP/shared memory streams:

```python
# tools/record_telemetry.py
async def record_game_telemetry(game: str, duration: int, output: str):
    """Record raw telemetry for testing"""
    detector = GameDetector()
    config = await detector.detect_active_game()

    if not config or config['name'] != game:
        print(f"Game {game} not running")
        return

    reader = config['reader_class']()
    await reader.connect()

    frames = []
    start_time = time.time()

    async for raw_data in reader.read_telemetry():
        frames.append(raw_data)

        if time.time() - start_time > duration:
            break

    # Save to msgpack file
    with open(output, 'wb') as f:
        msgpack.pack(frames, f)

    print(f"Recorded {len(frames)} frames to {output}")
```

### Performance Testing

```python
# tests/test_performance.py
import pytest
import time

@pytest.mark.benchmark
def test_parser_throughput():
    """Ensure parser can handle 360Hz sustained"""
    parser = IRacingParser()

    with open('tests/fixtures/iracing_1000_frames.msgpack', 'rb') as f:
        frames = msgpack.unpack(f)

    start = time.perf_counter()

    for frame in frames:
        telemetry = parser.parse(frame)
        assert telemetry is not None

    elapsed = time.perf_counter() - start
    fps = len(frames) / elapsed

    assert fps >= 360, f"Parser only managed {fps:.0f} FPS"
```

## Deployment

### Development Mode

```powershell
# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run application (UI + background telemetry collection)
python -m racecraft.app

# Application runs in system tray, minimize main window to hide
```

**Development Features**:
- Offline mode: Works without backend API (shows "dev-mode")
- Auto-generated tray icon if no icon file exists
- Hot reload: Restart app to see code changes
- Qt event loop + asyncio integrated via qasync

### Production (End User Distribution)

**Recommended Deployment**: Distribute as **packaged executable** (not Windows Service)

**Why not Windows Service?**
- RaceCraft is a **desktop application** that runs when user is logged in
- Needs access to user's running games (iRacing, F1, etc.)
- System tray interaction requires user session
- Windows Services run without GUI access

**Auto-Start Option** (via Inno Setup installer):
```ini
[Tasks]
Name: "startupicon"; Description: "Run at Windows startup"

[Icons]
Name: "{userstartup}\RaceCraft Desktop"; Filename: "{app}\RaceCraft.exe"; Tasks: startupicon
```

This places shortcut in `C:\Users\<user>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`, launching when user logs in.

### Distribution Methods

**1. Standalone EXE** (Development/Testing):
```powershell
.\build.ps1
# Output: dist\RaceCraft.exe
```

**2. Inno Setup Installer** (Recommended for Release):
```powershell
.\build.ps1 -Target installer
# Output: dist\RaceCraft-Setup-0.1.0.exe
```

**3. MSI Installer** (Enterprise):
```powershell
.\build.ps1 -Target msi
# Output: dist\RaceCraft-0.1.0-win64.msi
```

### Future: Optional Local API (Advanced Users)

If implementing local WebSocket API for third-party tools:

```python
# racecraft/api.py (optional future feature)
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/telemetry/current")
async def get_current_telemetry():
    # Return current telemetry frame
    pass

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    # Stream telemetry to connected clients
    pass

# Run embedded in main app (not separate process)
# uvicorn.run(app, host="127.0.0.1", port=8000) in background task
```

## Project Structure

```
racecraft-desktop/
├── racecraft/
│   ├── __init__.py
│   ├── app.py                 # Main application entry point (single process)
│   ├── models.py              # Pydantic data models
│   ├── interfaces.py          # ITelemetryReader, ITelemetryParser ABCs
│   ├── detection.py           # Game detection (async background task)
│   ├── auth.py                # Authentication service
│   ├── upload.py              # Session upload service
│   ├── session_manager.py     # Session lifecycle management
│   ├── collector.py           # Telemetry collection coordinator
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py    # Main PyQt6 window
│   │   ├── tray.py           # System tray icon
│   │   └── settings.py       # Settings dialog (FUTURE)
│   │
│   ├── readers/
│   │   ├── __init__.py
│   │   ├── base.py           # Base reader implementations
│   │   ├── shared_memory.py  # SharedMemoryReader (iRacing, ACC)
│   │   ├── udp.py            # UDPReader (F1, GT7, Forza)
│   │   └── iracing.py        # IRacingReader (PRIORITY)
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── iracing.py        # IRacingParser (PRIORITY)
│   │   ├── f1_24.py          # F1_24_Parser (FUTURE)
│   │   ├── acc.py            # ACCParser (FUTURE)
│   │   ├── gt7.py            # GT7Parser (FUTURE)
│   │   └── forza.py          # ForzaParser (FUTURE)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── validation.py     # Data validation helpers
│       ├── units.py          # Unit conversion utilities
│       └── recording.py      # Session recording/playback
│
├── assets/
│   ├── icon.png              # System tray icon (optional)
│   └── icon.ico              # Windows application icon (for installer)
│
├── config/
│   ├── games.json            # Game profiles
│   └── settings.json         # Application settings
│
├── tests/
│   ├── fixtures/             # Recorded telemetry samples
│   ├── test_parsers.py
│   ├── test_readers.py
│   ├── test_auth.py
│   ├── test_upload.py
│   └── test_performance.py
│
├── tools/
│   ├── record_telemetry.py   # CLI tool to record game data
│   └── validate_config.py    # Config file validator
│
├── installer/                # Packaging scripts
│   ├── setup.iss             # Inno Setup script
│   └── build_installer.md    # Build instructions
│
├── requirements.txt
├── setup.py
├── setup_cx_freeze.py        # cx_Freeze MSI builder
├── RaceCraft.spec            # PyInstaller spec
├── build.ps1                 # Automated build script
├── README.md
├── QUICKSTART.md
├── BUILDING.md
└── CLAUDE.md                 # This file
```

## Key Dependencies

```txt
# Core
python>=3.11
pydantic>=2.0
msgpack>=1.0

# iRacing (PRIORITY)
pyirsdk>=1.3

# Network/Async
httpx>=0.24            # Async HTTP client for remote API
asyncio-dgram>=2.1     # Async UDP
aiofiles>=23.0

# Local API
fastapi>=0.100
uvicorn[standard]>=0.23
websockets>=11.0

# UI
PyQt6>=6.5             # Main UI framework
qasync>=0.24           # Async/Qt integration

# Security & Storage
keyring>=24.0          # Secure credential storage
cryptography>=41.0     # Encryption utilities

# System
psutil>=5.9            # Process detection
pyyaml>=6.0            # Config parsing

# Future game libraries
# pycryptodome>=3.18   # GT7 Salsa20 decryption
# struct                # Binary parsing (stdlib)

# Development
pytest>=7.4
pytest-asyncio>=0.21
pytest-benchmark>=4.0
pytest-qt>=4.2         # PyQt testing
black>=23.0
ruff>=0.0.285
```

## Open Questions for Implementation

1. **Storage Backend**: Should recordings use:
   - Raw binary (msgpack) for perfect replay?
   - Time-series database (InfluxDB/TimescaleDB)?
   - Parquet files for analytics?

2. **API Authentication**: FastAPI endpoints open or require auth tokens?

3. **WebSocket Protocol**: JSON streaming or binary msgpack for efficiency?

4. **Multi-Client Support**: Single telemetry stream or per-client filtering/sampling?

5. **MoTeC Export**: Priority for i2 Pro format export? (Professional analysis tool)

6. **Cross-Platform**: Windows primary, but support macOS/Linux for iRacing via Wine/Proton?

## Success Criteria

### Phase 1: iRacing MVP with UI
- [ ] PyQt6 system tray UI functional
- [ ] Authentication on startup (device registration)
- [ ] SharedMemoryReader connects to iRacing
- [ ] IRacingParser produces valid NormalizedTelemetry
- [ ] Session detection (start/end)
- [ ] Session upload to remote server
- [ ] Failed upload retry queue (SQLite)
- [ ] UI shows authentication status
- [ ] UI shows current session info
- [ ] UI shows upload status
- [ ] Unit tests cover parser validation

### Phase 2: Multi-Game Foundation
- [ ] UDPReader base class implemented
- [ ] F1_24_Parser working with real game data
- [ ] Configuration system loads game profiles
- [ ] Recording/playback for offline testing
- [ ] Performance validated at 360Hz sustained
- [ ] Local FastAPI for third-party integrations

### Phase 3: Production Ready
- [ ] All 5 games supported (iRacing, F1, ACC, GT7, Forza)
- [ ] Windows installer (MSI or similar)
- [ ] Auto-start on Windows boot
- [ ] Health monitoring endpoints
- [ ] Settings dialog (game enable/disable, API config)
- [ ] MoTeC i2 export
- [ ] Comprehensive documentation

---

## Implementation Notes for LLM Agents

**ARCHITECTURE NOTE**: RaceCraft uses a **single-process integrated architecture**, not separate UI + daemon processes. All telemetry collection runs as async background tasks within the PyQt6 application using qasync to bridge Qt's event loop with asyncio.

**When implementing this specification**:

1. ✅ **COMPLETED**: `racecraft/models.py` - Pydantic models defined
2. ✅ **COMPLETED**: `racecraft/ui/main_window.py` and `racecraft/ui/tray.py` - UI components with fallback icon generation
3. ✅ **COMPLETED**: `racecraft/auth.py` - Authentication service with offline fallback
4. ✅ **COMPLETED**: `racecraft/app.py` - Main entry point with qasync integration
5. **NEXT**: Implement `racecraft/interfaces.py` - ABC definitions for readers/parsers
6. **NEXT**: Implement `racecraft/detection.py` - Game detection as async background task
7. **NEXT**: Implement `racecraft/readers/iracing.py` - iRacing shared memory reader
8. **NEXT**: Create `racecraft/parsers/iracing.py` - iRacing telemetry parser
9. **NEXT**: Build `racecraft/session_manager.py` - Session lifecycle and buffering
10. **NEXT**: Create `racecraft/upload.py` - Session upload with retry logic
11. **NEXT**: Create `racecraft/collector.py` - Telemetry collection coordinator integrating all components
12. **NEXT**: Wire background tasks into `racecraft/app.py` startup
13. **NEXT**: Write unit tests using recorded fixtures
14. **FUTURE**: Expand to other games (F1, ACC, GT7, Forza)

**Critical implementation details**:

- **Single process architecture**: All async tasks run in the same process as the UI
- Always use `asyncio.to_thread()` for blocking SDK calls (pyirsdk)
- Use `qasync.QEventLoop` to bridge asyncio and PyQt6 event loops - **already implemented in app.py**
- Handle `asyncio.QueueFull` gracefully (drop frames, don't block)
- Validate telemetry before queueing (impossible values = corrupt data)
- Preserve raw game data in `NormalizedTelemetry.raw_data` field
- Log errors but never crash on bad telemetry frames - application should be resilient
- Use `typing.Optional` for fields not available in all games
- Store credentials securely with `keyring` (uses Windows Credential Manager on Windows)
- Session uploads happen in background (non-blocking, with retry)
- UI updates via Qt signals to ensure thread safety
- **Background tasks**: Start with `asyncio.create_task()` in `app.start()` method
- **Offline development mode**: Authentication failures don't prevent app startup (already implemented)

**Remote API Endpoints** (to be implemented on server):

```
POST /api/auth/device/register
  Body: { "device_id": "<uuid>" }
  Returns: { "user_id": "<id>", "api_key": "<key>", "license_tier": "free|pro" }

GET /api/auth/validate
  Headers: { "X-API-Key": "<key>" }
  Returns: { "user_id": "<id>", "authorized": true, "license_tier": "free|pro" }

POST /api/sessions/upload
  Headers: { "X-API-Key": "<key>" }
  Body: {
    "session_id": "<game>_<timestamp>",
    "user_id": "<id>",
    "frames": [<NormalizedTelemetry dicts>],
    "uploaded_at": "<ISO timestamp>"
  }
  Returns: { "status": "success", "session_id": "<id>" }
```

**UI/Daemon Communication**:

The UI and daemon run in the same process but different threads. Use PyQt signals for thread-safe communication:
- Daemon → UI: Emit signals when session starts/ends, auth status changes, upload completes
- UI → Daemon: Call thread-safe methods or use Qt signal/slot connections

**Testing without games**:

Record real telemetry once, then use fixtures:
```python
# Record once with game running
python tools/record_telemetry.py --game iracing --duration 30 --output tests/fixtures/iracing_30s.msgpack

# Test without game running
pytest tests/test_parsers.py  # Uses recorded fixtures
```

**Session End Detection**:

Sessions end when:
1. Game process terminates (detected by GameDetector)
2. Player exits to menu (`is_racing=False` for 30+ seconds)
3. New session starts (iRacing session ID changes)

Upload triggered immediately on session end, with background retry for failures.

This architecture provides a solid foundation for a multi-game telemetry system with iRacing as the proven reference implementation, cloud-connected telemetry storage, extensible interfaces for future games, and performance characteristics suitable for real-time dashboards and hardware integration.

---

## Windows Development Environment Setup

### Virtual Environment Creation

Python virtual environments isolate project dependencies from system Python. This is **critical** for avoiding version conflicts and ensuring reproducible builds.

**PowerShell Setup**:
```powershell
# Navigate to project directory
cd C:\Users\bryan\Documents\GitHub\racecraft-desktop

# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# If blocked by execution policy:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify activation (should see "(venv)" prefix in prompt)
# Install dependencies
pip install -r requirements.txt
```

**Command Prompt Alternative**:
```cmd
# Create venv
python -m venv venv

# Activate (no execution policy issues)
venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt
```

**Deactivation**:
```powershell
deactivate
```

**Common Virtual Environment Issues**:

1. **"Python not recognized"**: Add Python to PATH during installation or use `py -3.11 -m venv venv`
2. **Multiple Python versions**: Specify version explicitly: `py -3.11 -m venv venv`
3. **Permission errors**: Run PowerShell as administrator or change execution policy
4. **Git ignoring venv**: Add `venv/` to `.gitignore` (should already exist)

### IDE Configuration

**VS Code**:
1. Install Python extension
2. Open project folder
3. Press `Ctrl+Shift+P` → "Python: Select Interpreter"
4. Choose `.\venv\Scripts\python.exe`
5. Terminal will auto-activate venv

**PyCharm**:
1. File → Settings → Project → Python Interpreter
2. Add Interpreter → Existing Environment
3. Select `.\venv\Scripts\python.exe`

---

## Windows Packaging and Distribution

### Packaging Overview

Python applications require packaging for distribution to users without Python installed. For PyQt6 Windows applications, three primary approaches exist:

| Method | Output | Size | Pros | Cons | Best For |
|--------|--------|------|------|------|----------|
| **PyInstaller** | Single EXE | ~150MB | Simple, portable | Large, slow startup | Quick distribution, testing |
| **cx_Freeze** | Folder + MSI | ~150MB | Native MSI, faster startup | Multi-file | Enterprise deployment |
| **Inno Setup** | Installer EXE | ~80MB | Professional, small | Requires external tool | Public releases |

### PyInstaller (Recommended for Quick Builds)

**Installation**:
```powershell
pip install pyinstaller
```

**Basic Build**:
```powershell
# Single file executable (slower startup, larger)
pyinstaller --onefile --windowed --name RaceCraft racecraft/app.py

# Directory mode (faster startup, multiple files)
pyinstaller --windowed --name RaceCraft racecraft/app.py
```

**Advanced Build with Spec File** (recommended):

The `RaceCraft.spec` file provides fine-grained control over the build process:

```python
# RaceCraft.spec
# Build with: pyinstaller RaceCraft.spec

a = Analysis(
    ['racecraft\\app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),      # Include assets folder
        ('config', 'config'),      # Include config folder
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'qasync',
        'keyring.backends.Windows',  # Critical for Windows keyring
    ],
    hookspath=[],
    excludes=[
        'tkinter',        # Reduce size by excluding unused modules
        'matplotlib',
        'numpy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RaceCraft',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,              # UPX compression (reduces size ~30%)
    console=False,         # No console window for GUI app
    icon='assets\\icon.ico',
)
```

**Key PyInstaller Options**:
- `--onefile`: Bundle everything into single EXE (slower startup, easier distribution)
- `--windowed` / `--noconsole`: Hide console window (required for GUI apps)
- `--icon=path/to/icon.ico`: Set executable icon
- `--add-data "src;dst"`: Include non-Python files (assets, configs)
- `--hidden-import module`: Force include modules not auto-detected
- `--exclude-module module`: Remove unused modules to reduce size
- `--upx-dir path`: Specify UPX compressor location for size reduction

**Common PyInstaller Issues**:

1. **"Module not found" at runtime**:
   - Add to `hiddenimports` in spec file
   - PyInstaller can't detect dynamic imports

2. **Missing data files** (configs, assets):
   - Use `--add-data` or `datas=` in spec file
   - Access at runtime via `sys._MEIPASS` in frozen mode

3. **Large file size**:
   - Exclude unused modules with `excludes=`
   - Use UPX compression
   - Consider directory mode instead of `--onefile`

4. **Antivirus false positives**:
   - Code sign the executable (see below)
   - Submit to antivirus vendors
   - Use established PyInstaller version (avoid bleeding edge)

### cx_Freeze (For MSI Installers)

**Installation**:
```powershell
pip install cx_freeze
```

**Setup Script** (`setup_cx_freeze.py`):

```python
import sys
from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": [
        "asyncio", "PyQt6", "qasync", "pydantic", "httpx", "keyring",
    ],
    "include_files": [
        ("assets", "assets"),
        ("config", "config"),
    ],
    "excludes": [
        "tkinter", "unittest", "email", "http.server",
    ],
}

# GUI base for Windows (no console)
base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(
    name="RaceCraft",
    version="0.1.0",
    description="Racing simulator telemetry collection",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "racecraft/app.py",
            base=base,
            target_name="RaceCraft.exe",
            icon="assets/icon.ico",
            shortcut_name="RaceCraft Desktop",
            shortcut_dir="DesktopFolder",
        )
    ],
)
```

**Build Commands**:
```powershell
# Build executable directory
python setup_cx_freeze.py build

# Build MSI installer (recommended)
python setup_cx_freeze.py bdist_msi
```

**cx_Freeze vs PyInstaller**:
- **cx_Freeze**: Faster startup, native MSI, multiple files in folder
- **PyInstaller**: Single file option, simpler, better community support

### Inno Setup (Professional Installer)

**Prerequisites**:
1. Build EXE with PyInstaller first
2. Download Inno Setup: https://jrsoftware.org/isdl.php
3. Install to default location

**Inno Setup Script** (`installer/setup.iss`):

```ini
#define MyAppName "RaceCraft Desktop"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "RaceCraft Team"
#define MyAppURL "https://github.com/yourusername/racecraft-desktop"
#define MyAppExeName "RaceCraft.exe"

[Setup]
AppId={{YOUR-GUID-HERE}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=RaceCraft-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\dist\RaceCraft.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs
Source: "..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Tasks]
Name: "desktopicon"; Description: "Create desktop icon"; Flags: unchecked
Name: "startupicon"; Description: "Run at Windows startup"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch RaceCraft"; Flags: nowait postinstall skipifsilent
```

**Build Installer**:
```powershell
# Compile with Inno Setup
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss

# Output: dist\RaceCraft-Setup-0.1.0.exe (~80MB compressed)
```

**Inno Setup Benefits**:
- Professional installer wizard
- LZMA compression (much smaller than raw EXE)
- Start menu shortcuts
- Desktop icon option
- Auto-start capability
- Clean uninstaller
- Registry entries
- Widely trusted by users

### Automated Build Script

**PowerShell Build Script** (`build.ps1`):

```powershell
# Build script for RaceCraft Desktop
# Usage: .\build.ps1 [-Target exe|msi|installer|all]

param(
    [ValidateSet("exe", "msi", "installer", "all")]
    [string]$Target = "exe"
)

Write-Host "=== RaceCraft Build ===" -ForegroundColor Cyan

# Clean previous builds
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

# Ensure PyInstaller installed
pip install --upgrade pyinstaller

# Build EXE
if ($Target -eq "exe" -or $Target -eq "all") {
    Write-Host "Building EXE..." -ForegroundColor Green
    pyinstaller RaceCraft.spec

    if ($LASTEXITCODE -eq 0) {
        $size = (Get-Item "dist\RaceCraft.exe").Length / 1MB
        Write-Host "SUCCESS: dist\RaceCraft.exe ($([math]::Round($size, 2)) MB)" -ForegroundColor Green
    }
}

# Build MSI
if ($Target -eq "msi" -or $Target -eq "all") {
    Write-Host "Building MSI..." -ForegroundColor Green
    pip install --upgrade cx_freeze
    python setup_cx_freeze.py bdist_msi
}

# Build Inno Setup installer
if ($Target -eq "installer" -or $Target -eq "all") {
    Write-Host "Building Installer..." -ForegroundColor Green
    $innoPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

    if (Test-Path $innoPath) {
        if (-not (Test-Path "dist\RaceCraft.exe")) {
            pyinstaller RaceCraft.spec
        }
        & $innoPath "installer\setup.iss"
    } else {
        Write-Host "ERROR: Inno Setup not found" -ForegroundColor Red
    }
}

Write-Host "Build complete. Output in dist\" -ForegroundColor Cyan
```

**Usage**:
```powershell
# Build standalone EXE
.\build.ps1

# Build MSI installer
.\build.ps1 -Target msi

# Build Inno Setup installer
.\build.ps1 -Target installer

# Build everything
.\build.ps1 -Target all
```

---

## Code Signing (Removing SmartScreen Warnings)

Unsigned executables trigger Windows Defender SmartScreen warnings, reducing user trust. Code signing provides:
- **Verified publisher identity**
- **Tamper detection**
- **SmartScreen bypass** (after reputation built)
- **Professional appearance**

### Obtaining a Code Signing Certificate

**Commercial Certificates** ($200-300/year):
- **DigiCert** - Most trusted, used by Microsoft/Adobe
- **Sectigo (Comodo)** - Popular, good pricing
- **SSL.com** - Competitive pricing
- **GlobalSign** - Enterprise focus

**Free for Open Source**:
- **SignPath Foundation** (https://about.signpath.io/) - Free code signing for OSS projects
- Requires: Public GitHub repo, OSI-approved license, active development

**Certificate Types**:
- **Standard Code Signing** - Software-based, $200-300/year
- **EV Code Signing** - Hardware token (USB), immediate SmartScreen trust, $400-500/year

### Signing Process

**Prerequisites**:
1. Windows SDK installed (includes `signtool.exe`)
2. Code signing certificate (.pfx file + password)

**Signing Command**:
```powershell
# Sign executable with timestamp
signtool sign /f "certificate.pfx" /p "password" /tr "http://timestamp.digicert.com" /td sha256 /fd sha256 "dist\RaceCraft.exe"

# Verify signature
signtool verify /pa "dist\RaceCraft.exe"
```

**Timestamp Server Importance**:
- Without timestamp: Signature expires with certificate (1 year)
- With timestamp: Signature valid indefinitely
- Use trusted timestamp servers: DigiCert, Sectigo, GlobalSign

**Signing MSI Installers**:
```powershell
signtool sign /f "certificate.pfx" /p "password" /tr "http://timestamp.digicert.com" /td sha256 /fd sha256 "dist\RaceCraft-Setup-0.1.0.exe"
```

**Building Reputation**:
Even with code signing, new executables may trigger SmartScreen until reputation builds:
- **Downloads**: Requires thousands of unique downloads
- **Time**: 2-4 weeks minimum
- **EV Certificates**: Bypass this (instant trust)
- **Workaround**: Submit to Microsoft SmartScreen feedback

### Certificate Storage Best Practices

**Development**:
- Store .pfx in password manager (1Password, LastPass)
- Never commit to Git
- Add `*.pfx` to `.gitignore`

**CI/CD**:
- Store in GitHub Secrets / Azure Key Vault
- Use environment variables for passwords
- Automate signing in build pipeline

---

## Continuous Integration / Automated Builds

### GitHub Actions Workflow

**`.github/workflows/build.yml`**:

```yaml
name: Build Windows Executable

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pyinstaller

    - name: Build executable
      run: pyinstaller RaceCraft.spec

    - name: Sign executable (if certificate available)
      if: ${{ secrets.CERT_PASSWORD }}
      run: |
        echo "${{ secrets.CERT_BASE64 }}" | base64 -d > cert.pfx
        signtool sign /f cert.pfx /p "${{ secrets.CERT_PASSWORD }}" /tr "http://timestamp.digicert.com" /td sha256 /fd sha256 "dist\RaceCraft.exe"
        del cert.pfx

    - name: Upload artifact
      uses: actions/upload-artifact@v3
      with:
        name: RaceCraft-Windows
        path: dist/RaceCraft.exe

    - name: Create GitHub Release
      if: startsWith(github.ref, 'refs/tags/')
      uses: softprops/action-gh-release@v1
      with:
        files: dist/RaceCraft.exe
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**Setup**:
1. Add certificate to GitHub Secrets:
   - `CERT_BASE64`: Base64-encoded .pfx file
   - `CERT_PASSWORD`: Certificate password
2. Tag release: `git tag v0.1.0 && git push --tags`
3. GitHub Actions builds and publishes release automatically

---

## Distribution Checklist

Before releasing to users:

### Testing
- [ ] Test on clean Windows 10/11 VM (no Python installed)
- [ ] Verify all UI elements functional
- [ ] Test authentication flow
- [ ] Confirm system tray icon appears
- [ ] Test minimize/restore from tray
- [ ] Verify application exits cleanly
- [ ] Check memory usage over 30+ minutes
- [ ] Test without internet connection

### Security
- [ ] Code sign executable
- [ ] Scan with VirusTotal (https://www.virustotal.com/)
- [ ] Submit to Microsoft SmartScreen for review
- [ ] No hardcoded secrets/API keys
- [ ] HTTPS for all API communication

### Documentation
- [ ] README.md with installation instructions
- [ ] QUICKSTART.md for users
- [ ] CHANGELOG.md documenting changes
- [ ] LICENSE file (MIT recommended)
- [ ] Screenshot of application in README

### Packaging
- [ ] File size reasonable (<200MB for PyQt6 app)
- [ ] Icon displays correctly in Explorer
- [ ] Version number in executable properties
- [ ] Company/publisher name set
- [ ] Installer creates Start Menu shortcuts
- [ ] Uninstaller works completely
- [ ] No temp files left after uninstall

### Release
- [ ] GitHub release with binaries
- [ ] Release notes describing changes
- [ ] SHA256 checksums for downloads
- [ ] Installation instructions in release notes
- [ ] Link to documentation

---

## Troubleshooting Common Build Issues

### PyInstaller Build Failures

**Error**: `ModuleNotFoundError: No module named 'X'`
**Solution**: Add to `hiddenimports` in spec file

**Error**: `FileNotFoundError` for assets/config files
**Solution**: Add to `datas` in spec file: `('src_path', 'dst_path')`

**Error**: Executable crashes immediately on double-click
**Solution**: Run from command line to see error, check for missing DLLs

**Error**: "Failed to execute script" on startup
**Solution**: Run with `--debug all` flag to see detailed error

### Size Reduction

**Problem**: EXE is 300MB+
**Solutions**:
1. Exclude unused packages in spec `excludes=`
2. Use UPX compression (already in spec)
3. Consider directory mode instead of `--onefile`
4. Remove debug symbols: `strip=True`
5. Check for duplicate packages: `pip list` in venv

### Antivirus False Positives

**Problem**: Windows Defender flags executable as malware
**Solutions**:
1. Code sign the executable (most effective)
2. Submit to Microsoft Defender: https://www.microsoft.com/wdsi/filesubmission
3. Use established PyInstaller version (avoid dev builds)
4. Avoid obfuscators (trigger heuristics)
5. Build on clean machine (not one with malware history)

### Runtime Issues

**Problem**: Executable works on dev machine, crashes on clean Windows
**Solutions**:
1. Missing Visual C++ Redistributables - include with installer
2. Missing .NET Framework - check dependencies
3. 32-bit vs 64-bit mismatch - specify in spec file
4. Test on VM before release

**Problem**: Keyring access denied errors
**Solution**: Ensure `keyring.backends.Windows` in `hiddenimports`

**Problem**: PyQt6 import errors
**Solution**: Include all Qt modules explicitly in `hiddenimports`

---

## Development Workflow Summary

### Initial Setup (Once)
```powershell
# Clone repository
git clone https://github.com/yourusername/racecraft-desktop.git
cd racecraft-desktop

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Daily Development
```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# Run application
python -m racecraft.app

# Run tests
pytest

# Format code
black racecraft/

# Deactivate when done
deactivate
```

### Building for Distribution
```powershell
# Quick test build
.\build.ps1

# Full release build
.\build.ps1 -Target all

# Sign executable (if certificate available)
signtool sign /f cert.pfx /p "password" /tr "http://timestamp.digicert.com" /td sha256 /fd sha256 "dist\RaceCraft.exe"

# Test on clean VM before release
```

### Release Process
```bash
# Update version in code
# Update CHANGELOG.md
# Commit changes
git add .
git commit -m "Release v0.2.0"

# Tag release
git tag v0.2.0
git push origin main --tags

# GitHub Actions builds automatically
# Download from Actions, test, then create GitHub Release
```

This comprehensive setup and packaging guide ensures reproducible builds, professional distribution packages, and a smooth path from development to production deployment on Windows.
