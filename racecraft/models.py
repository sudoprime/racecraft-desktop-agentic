"""Pydantic data models for RaceCraft telemetry"""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional


class Vector3(BaseModel):
    """3D vector for position, velocity, acceleration"""
    x: float
    y: float
    z: float


class WheelPosition(str, Enum):
    """Wheel position identifier"""
    FRONT_LEFT = "FL"
    FRONT_RIGHT = "FR"
    REAR_LEFT = "RL"
    REAR_RIGHT = "RR"


class WheelData(BaseModel):
    """Telemetry data for a single wheel"""
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
    """Normalized telemetry data across all games (SI units)"""

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


class AuthCredentials(BaseModel):
    """Authentication credentials from remote server"""
    user_id: str
    api_key: str
    license_tier: str
