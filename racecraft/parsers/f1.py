"""
F1 24/25 UDP telemetry parser (EA official "UDP Specification").

Parses the packed little-endian packets the game broadcasts on UDP 20777
(packet format 2024/2025 — the per-car structs used here are identical
across both). The reader assembles the latest Motion / LapData / Session /
CarTelemetry packets into one msgpack frame; this parser combines them
into NormalizedTelemetry for the player's car (header.m_playerCarIndex).

STATUS: implemented to the published spec, pending manual validation on
real hardware — see docs/COMPATIBILITY.md in the platform repo.

Spec details that matter (and are pinned by tests):
- All structs are PACKED (#pragma pack(1)); header is 29 bytes.
- CarTelemetry wheel arrays are ordered RL, RR, FL, FR — our model wants
  FL, FR, RL, RR, so wheels are REORDERED here.
- m_speed is uint16 km/h; m_steer is already -1..1; m_clutch is 0-100.
- LapData times are uint32 milliseconds; m_lapDistance is METERS and can
  be NEGATIVE before crossing the line on an out-lap (clamped to 0).
- Motion carries world position/velocity and g-forces directly.
"""
import ctypes
from datetime import datetime, timezone
from typing import Optional

import msgpack

from racecraft.interfaces import ITelemetryParser
from racecraft.models import (
    NormalizedTelemetry,
    TelemetryMetadata,
    Vector3,
    WheelData,
    WheelPosition,
)

F1_UDP_PORT = 20777
PACKET_MOTION = 0
PACKET_SESSION = 1
PACKET_LAP = 2
PACKET_TELEMETRY = 6
MAX_CARS = 22

# spec wheel order: 0=RL, 1=RR, 2=FL, 3=FR -> model order FL, FR, RL, RR
_SPEC_TO_MODEL = (2, 3, 0, 1)
_MODEL_ORDER = (WheelPosition.FRONT_LEFT, WheelPosition.FRONT_RIGHT,
                WheelPosition.REAR_LEFT, WheelPosition.REAR_RIGHT)

# m_trackId -> display name (F1 24 appendix)
TRACK_NAMES = {
    0: "Melbourne", 1: "Paul Ricard", 2: "Shanghai", 3: "Sakhir (Bahrain)",
    4: "Catalunya", 5: "Monaco", 6: "Montreal", 7: "Silverstone",
    8: "Hockenheim", 9: "Hungaroring", 10: "Spa", 11: "Monza",
    12: "Singapore", 13: "Suzuka", 14: "Abu Dhabi", 15: "Texas",
    16: "Brazil", 17: "Austria", 18: "Sochi", 19: "Mexico",
    20: "Baku", 21: "Sakhir Short", 22: "Silverstone Short",
    23: "Texas Short", 24: "Suzuka Short", 25: "Hanoi", 26: "Zandvoort",
    27: "Imola", 28: "Portimao", 29: "Jeddah", 30: "Miami",
    31: "Las Vegas", 32: "Losail",
}

SESSION_TYPES = {0: "Practice", 1: "Practice", 2: "Practice", 3: "Practice",
                 4: "Practice", 5: "Qualifying", 6: "Qualifying",
                 7: "Qualifying", 8: "Qualifying", 9: "Qualifying",
                 10: "Race", 11: "Race", 12: "Hotlap", 13: "Race",
                 15: "Qualifying", 18: "Hotlap"}


class PacketHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("m_packetFormat", ctypes.c_uint16),
        ("m_gameYear", ctypes.c_uint8),
        ("m_gameMajorVersion", ctypes.c_uint8),
        ("m_gameMinorVersion", ctypes.c_uint8),
        ("m_packetVersion", ctypes.c_uint8),
        ("m_packetId", ctypes.c_uint8),
        ("m_sessionUID", ctypes.c_uint64),
        ("m_sessionTime", ctypes.c_float),
        ("m_frameIdentifier", ctypes.c_uint32),
        ("m_overallFrameIdentifier", ctypes.c_uint32),
        ("m_playerCarIndex", ctypes.c_uint8),
        ("m_secondaryPlayerCarIndex", ctypes.c_uint8),
    ]


HEADER_SIZE = ctypes.sizeof(PacketHeader)  # 29 per spec


class CarMotionData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("m_worldPositionX", ctypes.c_float),
        ("m_worldPositionY", ctypes.c_float),
        ("m_worldPositionZ", ctypes.c_float),
        ("m_worldVelocityX", ctypes.c_float),
        ("m_worldVelocityY", ctypes.c_float),
        ("m_worldVelocityZ", ctypes.c_float),
        ("m_worldForwardDirX", ctypes.c_int16),
        ("m_worldForwardDirY", ctypes.c_int16),
        ("m_worldForwardDirZ", ctypes.c_int16),
        ("m_worldRightDirX", ctypes.c_int16),
        ("m_worldRightDirY", ctypes.c_int16),
        ("m_worldRightDirZ", ctypes.c_int16),
        ("m_gForceLateral", ctypes.c_float),
        ("m_gForceLongitudinal", ctypes.c_float),
        ("m_gForceVertical", ctypes.c_float),
        ("m_yaw", ctypes.c_float),
        ("m_pitch", ctypes.c_float),
        ("m_roll", ctypes.c_float),
    ]


class LapData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("m_lastLapTimeInMS", ctypes.c_uint32),
        ("m_currentLapTimeInMS", ctypes.c_uint32),
        ("m_sector1TimeMSPart", ctypes.c_uint16),
        ("m_sector1TimeMinutesPart", ctypes.c_uint8),
        ("m_sector2TimeMSPart", ctypes.c_uint16),
        ("m_sector2TimeMinutesPart", ctypes.c_uint8),
        ("m_deltaToCarInFrontMSPart", ctypes.c_uint16),
        ("m_deltaToCarInFrontMinutesPart", ctypes.c_uint8),
        ("m_deltaToRaceLeaderMSPart", ctypes.c_uint16),
        ("m_deltaToRaceLeaderMinutesPart", ctypes.c_uint8),
        ("m_lapDistance", ctypes.c_float),
        ("m_totalDistance", ctypes.c_float),
        ("m_safetyCarDelta", ctypes.c_float),
        ("m_carPosition", ctypes.c_uint8),
        ("m_currentLapNum", ctypes.c_uint8),
        ("m_pitStatus", ctypes.c_uint8),
        ("m_numPitStops", ctypes.c_uint8),
        ("m_sector", ctypes.c_uint8),
        ("m_currentLapInvalid", ctypes.c_uint8),
        ("m_penalties", ctypes.c_uint8),
        ("m_totalWarnings", ctypes.c_uint8),
        ("m_cornerCuttingWarnings", ctypes.c_uint8),
        ("m_numUnservedDriveThroughPens", ctypes.c_uint8),
        ("m_numUnservedStopGoPens", ctypes.c_uint8),
        ("m_gridPosition", ctypes.c_uint8),
        ("m_driverStatus", ctypes.c_uint8),
        ("m_resultStatus", ctypes.c_uint8),
        ("m_pitLaneTimerActive", ctypes.c_uint8),
        ("m_pitLaneTimeInLaneInMS", ctypes.c_uint16),
        ("m_pitStopTimerInMS", ctypes.c_uint16),
        ("m_pitStopShouldServePen", ctypes.c_uint8),
        ("m_speedTrapFastestSpeed", ctypes.c_float),
        ("m_speedTrapFastestLap", ctypes.c_uint8),
    ]


class CarTelemetryData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("m_speed", ctypes.c_uint16),
        ("m_throttle", ctypes.c_float),
        ("m_steer", ctypes.c_float),
        ("m_brake", ctypes.c_float),
        ("m_clutch", ctypes.c_uint8),
        ("m_gear", ctypes.c_int8),
        ("m_engineRPM", ctypes.c_uint16),
        ("m_drs", ctypes.c_uint8),
        ("m_revLightsPercent", ctypes.c_uint8),
        ("m_revLightsBitValue", ctypes.c_uint16),
        ("m_brakesTemperature", ctypes.c_uint16 * 4),
        ("m_tyresSurfaceTemperature", ctypes.c_uint8 * 4),
        ("m_tyresInnerTemperature", ctypes.c_uint8 * 4),
        ("m_engineTemperature", ctypes.c_uint16),
        ("m_tyresPressure", ctypes.c_float * 4),
        ("m_surfaceType", ctypes.c_uint8 * 4),
    ]


class SessionPrefix(ctypes.LittleEndianStructure):
    """The leading fields of PacketSessionData (all we need)."""
    _pack_ = 1
    _fields_ = [
        ("m_weather", ctypes.c_uint8),
        ("m_trackTemperature", ctypes.c_int8),
        ("m_airTemperature", ctypes.c_int8),
        ("m_totalLaps", ctypes.c_uint8),
        ("m_trackLength", ctypes.c_uint16),
        ("m_sessionType", ctypes.c_uint8),
        ("m_trackId", ctypes.c_int8),
        ("m_formula", ctypes.c_uint8),
    ]


def _player_struct(packet: bytes, cls, header: PacketHeader):
    """Extract the player's per-car struct from a car-array packet."""
    size = ctypes.sizeof(cls)
    idx = min(int(header.m_playerCarIndex), MAX_CARS - 1)
    off = HEADER_SIZE + idx * size
    if len(packet) < off + size:
        return None
    return cls.from_buffer_copy(packet[off:off + size])


def _header(packet: bytes) -> Optional[PacketHeader]:
    if packet is None or len(packet) < HEADER_SIZE:
        return None
    return PacketHeader.from_buffer_copy(packet[:HEADER_SIZE])


def _get(pages: dict, key: str) -> Optional[bytes]:
    return pages.get(key.encode()) if pages.get(key.encode()) is not None else pages.get(key)


class F1Parser(ITelemetryParser):
    """Parses msgpack frames of {'motion','lap','session','telemetry'}."""

    def __init__(self):
        self._frame = 0

    @property
    def game_name(self) -> str:
        return "f1"

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        try:
            pages = msgpack.unpackb(raw_data)
            tel_raw = _get(pages, "telemetry")
            lap_raw = _get(pages, "lap")
            hdr = _header(tel_raw)
            if hdr is None:
                return None
            tel = _player_struct(tel_raw, CarTelemetryData, hdr)
            lap = None
            lap_hdr = _header(lap_raw)
            if lap_hdr is not None:
                lap = _player_struct(lap_raw, LapData, lap_hdr)
            motion = None
            motion_raw = _get(pages, "motion")
            motion_hdr = _header(motion_raw)
            if motion_hdr is not None:
                motion = _player_struct(motion_raw, CarMotionData, motion_hdr)
            session = None
            session_raw = _get(pages, "session")
            if session_raw is not None and len(session_raw) >= HEADER_SIZE + ctypes.sizeof(SessionPrefix):
                session = SessionPrefix.from_buffer_copy(
                    session_raw[HEADER_SIZE:HEADER_SIZE + ctypes.sizeof(SessionPrefix)])
            if tel is None:
                return None

            wheels = []
            for model_pos, spec_i in zip(_MODEL_ORDER, _SPEC_TO_MODEL):
                wheels.append(WheelData(
                    position=model_pos,
                    tire_surface_temp=float(tel.m_tyresSurfaceTemperature[spec_i]) or None,
                    tire_inner_temp=float(tel.m_tyresInnerTemperature[spec_i]) or None,
                    brake_temp=float(tel.m_brakesTemperature[spec_i]) or None,
                    tire_pressure=float(tel.m_tyresPressure[spec_i]) or None,
                ))

            track_len = float(session.m_trackLength) if session and session.m_trackLength > 0 else None
            lap_dist_m = max(0.0, float(lap.m_lapDistance)) if lap is not None else None
            lap_distance = None
            if lap_dist_m is not None and track_len:
                lap_distance = max(0.0, min(1.0, lap_dist_m / track_len))

            self._frame += 1
            return NormalizedTelemetry(
                game_name="f1",
                session_id=str(hdr.m_sessionUID),
                timestamp=datetime.now(timezone.utc),
                frame_number=int(hdr.m_overallFrameIdentifier) or self._frame,
                speed=float(tel.m_speed) / 3.6,
                gear=int(tel.m_gear),
                engine_rpm=float(tel.m_engineRPM),
                throttle=min(1.0, max(0.0, float(tel.m_throttle))),
                brake=min(1.0, max(0.0, float(tel.m_brake))),
                clutch=min(1.0, max(0.0, float(tel.m_clutch) / 100.0)),
                steering=min(1.0, max(-1.0, float(tel.m_steer))),
                position=Vector3(
                    x=float(motion.m_worldPositionX) if motion else 0.0,
                    y=float(motion.m_worldPositionY) if motion else 0.0,
                    z=float(motion.m_worldPositionZ) if motion else 0.0),
                velocity=Vector3(
                    x=float(motion.m_worldVelocityX) if motion else 0.0,
                    y=float(motion.m_worldVelocityY) if motion else 0.0,
                    z=float(motion.m_worldVelocityZ) if motion else 0.0),
                acceleration=Vector3(x=0.0, y=0.0, z=0.0),
                yaw=float(motion.m_yaw) if motion else 0.0,
                pitch=float(motion.m_pitch) if motion else 0.0,
                roll=float(motion.m_roll) if motion else 0.0,
                yaw_rate=0.0, pitch_rate=0.0, roll_rate=0.0,
                g_force_lateral=float(motion.m_gForceLateral) if motion else 0.0,
                g_force_longitudinal=float(motion.m_gForceLongitudinal) if motion else 0.0,
                g_force_vertical=float(motion.m_gForceVertical) if motion else 0.0,
                wheels=wheels,
                lap_number=int(lap.m_currentLapNum) if lap is not None else None,
                lap_distance=lap_distance,
                track_length=track_len,
                lap_time_current=float(lap.m_currentLapTimeInMS) / 1000.0
                    if lap is not None and lap.m_currentLapTimeInMS > 0 else None,
                lap_time_last=float(lap.m_lastLapTimeInMS) / 1000.0
                    if lap is not None and lap.m_lastLapTimeInMS > 0 else None,
                in_pit=bool(lap is not None and lap.m_pitStatus > 0),
                is_racing=bool(lap is None or lap.m_driverStatus in (1, 2, 3, 4)),
            )
        except Exception:
            return None

    def validate_data(self, data: NormalizedTelemetry) -> bool:
        if data.speed > 150.0 or data.speed < 0:  # 540 km/h cap
            return False
        if data.engine_rpm < 0 or data.engine_rpm > 16000:
            return False
        if data.lap_distance is not None and not 0.0 <= data.lap_distance <= 1.0:
            return False
        return True

    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        try:
            pages = msgpack.unpackb(raw_data)
            session_raw = _get(pages, "session")
            if session_raw is None or len(session_raw) < HEADER_SIZE + ctypes.sizeof(SessionPrefix):
                return None
            session = SessionPrefix.from_buffer_copy(
                session_raw[HEADER_SIZE:HEADER_SIZE + ctypes.sizeof(SessionPrefix)])
            return TelemetryMetadata(
                game_name="f1",
                track_name=TRACK_NAMES.get(int(session.m_trackId), "Unknown Track"),
                car_name="Formula 1" if session.m_formula == 0 else "Formula (other)",
                session_type=SESSION_TYPES.get(int(session.m_sessionType), "Practice"),
                session_start_time=datetime.now(timezone.utc),
                track_length=float(session.m_trackLength) or 0.0,
            )
        except Exception:
            return None
