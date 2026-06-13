"""iRacing telemetry parser"""

import logging
import math
import msgpack
from typing import Optional
from datetime import datetime

from racecraft.interfaces import ITelemetryParser

logger = logging.getLogger(__name__)
from racecraft.models import (
    NormalizedTelemetry,
    TelemetryMetadata,
    WheelData,
    WheelPosition,
    Vector3,
)


class IRacingParser(ITelemetryParser):
    """Parse iRacing telemetry into normalized format"""

    def __init__(self):
        self._session_info: Optional[dict] = None
        # World-position reconstruction state (loop 4, R12). iRacing gives
        # NO scalar world position in normal play — CarIdxX/Y/Z are
        # per-car ARRAYS (broadcast only). We integrate the car-frame
        # velocity (rotated into the world by yaw) over SessionTime, the
        # documented desktop technique. State is reset on a new session.
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._pos_z = 0.0
        self._last_session_time: Optional[float] = None
        self._integ_session_id: Optional[str] = None

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        """Convert iRacing dict to NormalizedTelemetry"""
        try:
            data = msgpack.unpackb(raw_data)

            # iRacing wheel data indices: LF=0, RF=1, LR=2, RR=3
            # Map to our standard: FL, FR, RL, RR
            wheels = [
                WheelData(
                    position=WheelPosition.FRONT_LEFT,
                    tire_surface_temp=self._get_tire_temp(data, 'LF'),
                    tire_inner_temp=data.get('LFtempCL'),
                    tire_middle_temp=data.get('LFtempCM'),
                    tire_outer_temp=data.get('LFtempCR'),
                    tire_pressure=data.get('LFpressure'),
                    tire_wear=self._get_avg_wear(data, 'LF'),
                    wheel_speed=self._rpm_to_rad_s(data.get('LFrpm', 0)),
                ),
                WheelData(
                    position=WheelPosition.FRONT_RIGHT,
                    tire_surface_temp=self._get_tire_temp(data, 'RF'),
                    tire_inner_temp=data.get('RFtempCL'),
                    tire_middle_temp=data.get('RFtempCM'),
                    tire_outer_temp=data.get('RFtempCR'),
                    tire_pressure=data.get('RFpressure'),
                    tire_wear=self._get_avg_wear(data, 'RF'),
                    wheel_speed=self._rpm_to_rad_s(data.get('RFrpm', 0)),
                ),
                WheelData(
                    position=WheelPosition.REAR_LEFT,
                    tire_surface_temp=self._get_tire_temp(data, 'LR'),
                    tire_inner_temp=data.get('LRtempCL'),
                    tire_middle_temp=data.get('LRtempCM'),
                    tire_outer_temp=data.get('LRtempCR'),
                    tire_pressure=data.get('LRpressure'),
                    tire_wear=self._get_avg_wear(data, 'LR'),
                    wheel_speed=self._rpm_to_rad_s(data.get('LRrpm', 0)),
                ),
                WheelData(
                    position=WheelPosition.REAR_RIGHT,
                    tire_surface_temp=self._get_tire_temp(data, 'RR'),
                    tire_inner_temp=data.get('RRtempCL'),
                    tire_middle_temp=data.get('RRtempCM'),
                    tire_outer_temp=data.get('RRtempCR'),
                    tire_pressure=data.get('RRpressure'),
                    tire_wear=self._get_avg_wear(data, 'RR'),
                    wheel_speed=self._rpm_to_rad_s(data.get('RRrpm', 0)),
                ),
            ]

            # Build normalized telemetry
            return NormalizedTelemetry(
                game_name="iRacing",
                session_id=str(data.get('SessionUniqueID', 0)),
                timestamp=datetime.utcnow(),
                frame_number=data.get('SessionTick', 0),

                # Vehicle dynamics (iRacing uses m/s for speed)
                speed=data.get('Speed', 0.0),
                gear=data.get('Gear', 0),
                engine_rpm=data.get('RPM', 0.0),
                # EngineWarnings is a status BITFIELD, not a redline (loop 4,
                # R13). iRacing has no realtime max-RPM channel -> honest None.
                engine_max_rpm=None,

                # Driver inputs (iRacing already 0.0-1.0 normalized)
                throttle=max(0.0, min(1.0, data.get('Throttle', 0.0))),
                brake=max(0.0, min(1.0, data.get('Brake', 0.0))),
                clutch=max(0.0, min(1.0, data.get('Clutch', 0.0))),
                steering=self._normalize_steering(data),

                # Position: reconstructed by velocity integration (R12) —
                # iRacing exposes no scalar world position in normal play.
                position=self._integrate_position(data),
                velocity=Vector3(
                    x=data.get('VelocityX', 0.0),
                    y=data.get('VelocityY', 0.0),
                    z=data.get('VelocityZ', 0.0),
                ),
                acceleration=Vector3(
                    x=data.get('LatAccel', 0.0),
                    y=data.get('VertAccel', 0.0),
                    z=data.get('LongAccel', 0.0),
                ),

                # Rotation (radians)
                yaw=data.get('Yaw', 0.0),
                pitch=data.get('Pitch', 0.0),
                roll=data.get('Roll', 0.0),
                yaw_rate=data.get('YawRate', 0.0),
                pitch_rate=data.get('PitchRate', 0.0),
                roll_rate=data.get('RollRate', 0.0),

                # G-forces
                g_force_lateral=data.get('LatAccel', 0.0),
                g_force_longitudinal=data.get('LongAccel', 0.0),
                g_force_vertical=data.get('VertAccel', 0.0),

                wheels=wheels,

                # Fuel
                fuel_remaining=data.get('FuelLevel', 0.0),
                # FuelLevelPct is a 0-1 FRACTION, not liters of capacity
                # (loop 4, R13). Capacity is session-info only -> honest None.
                fuel_capacity=None,
                fuel_laps_remaining=None,  # iRacing doesn't provide this directly

                # Session
                lap_number=data.get('Lap', 0),
                lap_distance=data.get('LapDist', 0.0),
                lap_time_current=data.get('LapCurrentLapTime', 0.0),
                lap_time_last=data.get('LapLastLapTime', 0.0),
                lap_time_best=data.get('LapBestLapTime', 0.0),

                in_pit=data.get('OnPitRoad', False),
                is_racing=data.get('IsOnTrack', True),

                raw_data=data  # Preserve full iRacing data
            )
        except Exception as e:
            logger.warning(f"Error parsing iRacing telemetry (frame skipped): {e}")
            return None

    def _integrate_position(self, data: dict) -> Vector3:
        """Reconstruct world position by integrating car-frame velocity,
        rotated into the world by yaw, over SessionTime (loop 4, R12).

        iRacing VelocityX/Y/Z are in the CAR's frame (X forward, Y left,
        Z up). Rotating the planar (X,Y) velocity by yaw and integrating
        gives a usable 2D track map — the thing curvature turn-detection
        and the track-map chart need, which the all-zeros bug had silently
        broken for the primary sim. First frame (and post-reset) anchors
        at the origin; dt comes from the SessionTime delta, clamped so a
        pause/teleport can't fling the path."""
        session_id = str(data.get('SessionUniqueID', 0))
        if session_id != self._integ_session_id:
            # new session -> reset the path to the origin
            self._integ_session_id = session_id
            self._pos_x = self._pos_y = self._pos_z = 0.0
            self._last_session_time = None

        st = data.get('SessionTime')
        if st is None:
            return Vector3(x=self._pos_x, y=self._pos_y, z=self._pos_z)

        if self._last_session_time is not None:
            dt = st - self._last_session_time
            # clamp: ignore non-monotonic jumps and long gaps (pauses,
            # garage exits) that would otherwise teleport the path
            if 0.0 < dt <= 1.0:
                vx = data.get('VelocityX', 0.0) or 0.0   # car-forward (m/s)
                vy = data.get('VelocityY', 0.0) or 0.0   # car-left (m/s)
                vz = data.get('VelocityZ', 0.0) or 0.0
                yaw = data.get('Yaw', 0.0) or 0.0
                cos_y, sin_y = math.cos(yaw), math.sin(yaw)
                world_vx = vx * cos_y - vy * sin_y
                world_vy = vx * sin_y + vy * cos_y
                self._pos_x += world_vx * dt
                self._pos_y += world_vy * dt
                self._pos_z += vz * dt
        self._last_session_time = st
        return Vector3(x=self._pos_x, y=self._pos_y, z=self._pos_z)

    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        """Extract iRacing session info from YAML"""
        # TODO: Parse SessionInfo YAML from iRacing
        # This would extract track name, car name, session type, etc.
        return None

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
        if not (0.0 <= data.brake <= 1.0):
            return False
        if not (0.0 <= data.clutch <= 1.0):
            return False

        return True

    def _get_tire_temp(self, data: dict, wheel: str) -> Optional[float]:
        """Get average tire temperature for a wheel"""
        try:
            # iRacing provides L, C, R temps - average them
            temp_l = data.get(f'{wheel}tempCL', 0.0)
            temp_c = data.get(f'{wheel}tempCM', 0.0)
            temp_r = data.get(f'{wheel}tempCR', 0.0)

            if temp_l or temp_c or temp_r:
                return (temp_l + temp_c + temp_r) / 3.0
        except (TypeError, ValueError):
            pass
        return None

    def _get_avg_wear(self, data: dict, wheel: str) -> Optional[float]:
        """Get average tire wear for a wheel"""
        try:
            # iRacing provides L, C, R wear - average them
            wear_l = data.get(f'{wheel}wearL', 0.0)
            wear_c = data.get(f'{wheel}wearM', 0.0)
            wear_r = data.get(f'{wheel}wearR', 0.0)

            if wear_l or wear_c or wear_r:
                return (wear_l + wear_c + wear_r) / 3.0
        except (TypeError, ValueError):
            pass
        return None

    def _rpm_to_rad_s(self, rpm: float) -> float:
        """Convert RPM to radians per second"""
        return rpm * 0.10472  # RPM * (2π / 60)

    def _normalize_steering(self, data: dict) -> float:
        """Normalize steering to -1.0 to 1.0 range"""
        try:
            angle = data.get('SteeringWheelAngle', 0.0)
            max_angle = data.get('SteeringWheelAngleMax', 1.0)
            if max_angle > 0:
                return max(-1.0, min(1.0, angle / max_angle))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        return 0.0
