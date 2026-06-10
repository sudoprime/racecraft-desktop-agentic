"""iRacing telemetry parser"""

import msgpack
from typing import Optional
from datetime import datetime

from racecraft.interfaces import ITelemetryParser
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
                engine_max_rpm=data.get('EngineWarnings', 0),

                # Driver inputs (iRacing already 0.0-1.0 normalized)
                throttle=max(0.0, min(1.0, data.get('Throttle', 0.0))),
                brake=max(0.0, min(1.0, data.get('Brake', 0.0))),
                clutch=max(0.0, min(1.0, data.get('Clutch', 0.0))),
                steering=self._normalize_steering(data),

                # Position (iRacing provides world coordinates in meters)
                position=Vector3(
                    x=data.get('CarIdxX', 0.0) if isinstance(data.get('CarIdxX'), (int, float)) else 0.0,
                    y=data.get('CarIdxY', 0.0) if isinstance(data.get('CarIdxY'), (int, float)) else 0.0,
                    z=data.get('CarIdxZ', 0.0) if isinstance(data.get('CarIdxZ'), (int, float)) else 0.0,
                ),
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
                fuel_capacity=data.get('FuelLevelPct'),
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
            # Log error, return None to skip invalid frame
            print(f"Error parsing iRacing telemetry: {e}")
            return None

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
        except:
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
        except:
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
        except:
            pass
        return 0.0
