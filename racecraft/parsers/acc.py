"""
ACC (Assetto Corsa Competizione) telemetry parser.

Parses the Kunos shared-memory pages (acpmf_physics / acpmf_graphics /
acpmf_static) into NormalizedTelemetry. The struct layouts follow the
published Kunos shared-memory spec (ACC keeps the original AC layout with
ACC-specific semantics); strings are declared as uint16 arrays and decoded
as UTF-16LE so the byte layout matches the game's MSVC wchar_t layout on
every platform (ctypes' c_wchar is 4 bytes on Linux, which would corrupt
offsets in tests).

STATUS: implemented to spec, pending manual validation on real hardware —
see docs/COMPATIBILITY.md in the platform repo. ACC notes:
- physics.steerAngle is the normalized steering input in [-1, 1].
- physics.accG is [lateral, vertical, longitudinal] in G.
- wheelsPressure is PSI (normalized model wants bar).
- tyreCoreTemperature is the live tyre temp; the legacy tyreTempI/M/O
  arrays are not populated by ACC (left None rather than fabricated).
- graphics.normalizedCarPosition is the 0..1 lap fraction (the platform's
  chunk schema wants exactly this in lap_distance... see parse()).
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

PSI_TO_BAR = 0.0689476
ACC_STATUS_LIVE = 2  # AC_LIVE in the status enum

# wheel array order in the shared memory: FL, FR, RL, RR (matches our model)
_WHEEL_ORDER = (
    WheelPosition.FRONT_LEFT,
    WheelPosition.FRONT_RIGHT,
    WheelPosition.REAR_LEFT,
    WheelPosition.REAR_RIGHT,
)


def _wstr(field) -> str:
    """Decode a uint16-array field as UTF-16LE up to the first NUL."""
    raw = bytes(field)
    text = raw.decode("utf-16-le", errors="ignore")
    return text.split("\x00", 1)[0]


def _acc_damage(phys) -> Optional[dict]:
    """ACC carDamage[5] = [front, rear, left, right, centre] (loop 4, V
    depth). Returns a labelled dict, or None when undamaged."""
    d = [float(x) for x in phys.carDamage]
    if not any(d):
        return None
    return {"front": d[0], "rear": d[1], "left": d[2], "right": d[3],
            "centre": d[4]}


class PhysicsPage(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32),
        ("gas", ctypes.c_float),
        ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float),
        ("gear", ctypes.c_int32),
        ("rpms", ctypes.c_int32),
        ("steerAngle", ctypes.c_float),
        ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3),
        ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4),
        ("wheelLoad", ctypes.c_float * 4),
        ("wheelsPressure", ctypes.c_float * 4),
        ("wheelAngularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4),
        ("tyreDirtyLevel", ctypes.c_float * 4),
        ("tyreCoreTemperature", ctypes.c_float * 4),
        ("camberRAD", ctypes.c_float * 4),
        ("suspensionTravel", ctypes.c_float * 4),
        ("drs", ctypes.c_float),
        ("tc", ctypes.c_float),
        ("heading", ctypes.c_float),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("cgHeight", ctypes.c_float),
        ("carDamage", ctypes.c_float * 5),
        ("numberOfTyresOut", ctypes.c_int32),
        ("pitLimiterOn", ctypes.c_int32),
        ("abs", ctypes.c_float),
        ("kersCharge", ctypes.c_float),
        ("kersInput", ctypes.c_float),
        ("autoShifterOn", ctypes.c_int32),
        ("rideHeight", ctypes.c_float * 2),
        ("turboBoost", ctypes.c_float),
        ("ballast", ctypes.c_float),
        ("airDensity", ctypes.c_float),
        ("airTemp", ctypes.c_float),
        ("roadTemp", ctypes.c_float),
        ("localAngularVel", ctypes.c_float * 3),
        ("finalFF", ctypes.c_float),
        ("performanceMeter", ctypes.c_float),
        ("engineBrake", ctypes.c_int32),
        ("ersRecoveryLevel", ctypes.c_int32),
        ("ersPowerLevel", ctypes.c_int32),
        ("ersHeatCharging", ctypes.c_int32),
        ("ersIsCharging", ctypes.c_int32),
        ("kersCurrentKJ", ctypes.c_float),
        ("drsAvailable", ctypes.c_int32),
        ("drsEnabled", ctypes.c_int32),
        ("brakeTemp", ctypes.c_float * 4),
        ("clutch", ctypes.c_float),
        # legacy AC inner/middle/outer temps — ACC leaves these at 0
        ("tyreTempI", ctypes.c_float * 4),
        ("tyreTempM", ctypes.c_float * 4),
        ("tyreTempO", ctypes.c_float * 4),
    ]


class GraphicsPage(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32),
        ("status", ctypes.c_int32),
        ("session", ctypes.c_int32),
        ("currentTime", ctypes.c_uint16 * 15),
        ("lastTime", ctypes.c_uint16 * 15),
        ("bestTime", ctypes.c_uint16 * 15),
        ("split", ctypes.c_uint16 * 15),
        ("completedLaps", ctypes.c_int32),
        ("position", ctypes.c_int32),
        ("iCurrentTime", ctypes.c_int32),
        ("iLastTime", ctypes.c_int32),
        ("iBestTime", ctypes.c_int32),
        ("sessionTimeLeft", ctypes.c_float),
        ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int32),
        ("currentSectorIndex", ctypes.c_int32),
        ("lastSectorTime", ctypes.c_int32),
        ("numberOfLaps", ctypes.c_int32),
        ("tyreCompound", ctypes.c_uint16 * 33),
        ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float),
        ("activeCars", ctypes.c_int32),
        ("carCoordinates", (ctypes.c_float * 3) * 60),
        ("carID", ctypes.c_int32 * 60),
        ("playerCarID", ctypes.c_int32),
        ("penaltyTime", ctypes.c_float),
        ("flag", ctypes.c_int32),
        ("penalty", ctypes.c_int32),
        ("idealLineOn", ctypes.c_int32),
        ("isInPitLane", ctypes.c_int32),
        ("surfaceGrip", ctypes.c_float),
        ("mandatoryPitDone", ctypes.c_int32),
        ("windSpeed", ctypes.c_float),
        ("windDirection", ctypes.c_float),
    ]


class StaticPage(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", ctypes.c_uint16 * 15),
        ("acVersion", ctypes.c_uint16 * 15),
        ("numberOfSessions", ctypes.c_int32),
        ("numCars", ctypes.c_int32),
        ("carModel", ctypes.c_uint16 * 33),
        ("track", ctypes.c_uint16 * 33),
        ("playerName", ctypes.c_uint16 * 33),
        ("playerSurname", ctypes.c_uint16 * 33),
        ("playerNick", ctypes.c_uint16 * 33),
        ("sectorCount", ctypes.c_int32),
        ("maxTorque", ctypes.c_float),
        ("maxPower", ctypes.c_float),
        ("maxRpm", ctypes.c_int32),
        ("maxFuel", ctypes.c_float),
        ("suspensionMaxTravel", ctypes.c_float * 4),
        ("tyreRadius", ctypes.c_float * 4),
        ("maxTurboBoost", ctypes.c_float),
        ("deprecated_1", ctypes.c_float),
        ("deprecated_2", ctypes.c_float),
        ("penaltiesEnabled", ctypes.c_int32),
        ("aidFuelRate", ctypes.c_float),
        ("aidTireRate", ctypes.c_float),
        ("aidMechanicalDamage", ctypes.c_float),
        ("allowTyreBlankets", ctypes.c_int32),
        ("aidStability", ctypes.c_float),
        ("aidAutoClutch", ctypes.c_int32),
        ("aidAutoBlip", ctypes.c_int32),
        ("hasDRS", ctypes.c_int32),
        ("hasERS", ctypes.c_int32),
        ("hasKERS", ctypes.c_int32),
        ("kersMaxJ", ctypes.c_float),
        ("engineBrakeSettingsCount", ctypes.c_int32),
        ("ersPowerControllerCount", ctypes.c_int32),
        ("trackSPlineLength", ctypes.c_float),
        ("trackConfiguration", ctypes.c_uint16 * 33),
    ]


def _from_buffer(cls, raw: bytes):
    if raw is None or len(raw) < ctypes.sizeof(cls):
        return None
    return cls.from_buffer_copy(raw[: ctypes.sizeof(cls)])


class ACCParser(ITelemetryParser):
    """Parses msgpack frames of {'physics','graphics','static'} raw pages."""

    def __init__(self):
        self._frame = 0

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        try:
            pages = msgpack.unpackb(raw_data)
            phys = _from_buffer(PhysicsPage, pages.get(b"physics") or pages.get("physics"))
            gfx = _from_buffer(GraphicsPage, pages.get(b"graphics") or pages.get("graphics"))
            static = _from_buffer(StaticPage, pages.get(b"static") or pages.get("static"))
            if phys is None or gfx is None:
                return None

            # player position: locate playerCarID in the carID table
            coords = (0.0, 0.0, 0.0)
            try:
                ids = list(gfx.carID)
                idx = ids.index(gfx.playerCarID) if gfx.playerCarID in ids else 0
                c = gfx.carCoordinates[idx]
                coords = (float(c[0]), float(c[1]), float(c[2]))
            except (ValueError, IndexError):
                pass

            compound = _wstr(gfx.tyreCompound) or None
            wheels = []
            for i, pos in enumerate(_WHEEL_ORDER):
                core = float(phys.tyreCoreTemperature[i]) or None
                wheels.append(WheelData(
                    position=pos,
                    tire_surface_temp=core,
                    tire_middle_temp=core,
                    # ACC does not populate the legacy I/M/O arrays — leave
                    # inner/outer None instead of fabricating zeros
                    brake_temp=float(phys.brakeTemp[i]) or None,
                    tire_pressure=float(phys.wheelsPressure[i]) * PSI_TO_BAR or None,
                    suspension_travel=float(phys.suspensionTravel[i]),
                    wheel_speed=float(phys.wheelAngularSpeed[i]),
                    slip_ratio=float(phys.wheelSlip[i]),
                    tire_wear=float(phys.tyreWear[i]),
                    # V depth (loop 4): ACC physics page exposes these.
                    # rideHeight is [front, rear] -> i<2 is front.
                    camber=float(phys.camberRAD[i]),  # radians
                    wheel_load=float(phys.wheelLoad[i]),  # N
                    ride_height=float(phys.rideHeight[0 if i < 2 else 1]),  # m
                    tire_compound=compound,
                ))

            self._frame += 1
            track_len = float(static.trackSPlineLength) if static else None
            return NormalizedTelemetry(
                game_name="acc",
                session_id="",
                timestamp=datetime.now(timezone.utc),
                frame_number=self._frame,
                speed=max(0.0, float(phys.speedKmh) / 3.6),
                gear=int(phys.gear) - 1,  # ACC: 0=R, 1=N, 2=1st -> model: -1/0/1+
                engine_rpm=float(phys.rpms),
                engine_max_rpm=float(static.maxRpm) if static and static.maxRpm > 0 else None,
                throttle=min(1.0, max(0.0, float(phys.gas))),
                brake=min(1.0, max(0.0, float(phys.brake))),
                clutch=min(1.0, max(0.0, float(phys.clutch))),
                steering=min(1.0, max(-1.0, float(phys.steerAngle))),
                position=Vector3(x=coords[0], y=coords[1], z=coords[2]),
                velocity=Vector3(x=float(phys.velocity[0]),
                                 y=float(phys.velocity[1]),
                                 z=float(phys.velocity[2])),
                acceleration=Vector3(x=0.0, y=0.0, z=0.0),
                yaw=float(phys.heading),
                pitch=float(phys.pitch),
                roll=float(phys.roll),
                yaw_rate=float(phys.localAngularVel[1]),
                pitch_rate=float(phys.localAngularVel[0]),
                roll_rate=float(phys.localAngularVel[2]),
                # accG order per spec: [lateral, vertical, longitudinal]
                g_force_lateral=float(phys.accG[0]),
                g_force_vertical=float(phys.accG[1]),
                g_force_longitudinal=float(phys.accG[2]),
                wheels=wheels,
                fuel_remaining=float(phys.fuel),
                fuel_capacity=float(static.maxFuel) if static and static.maxFuel > 0 else None,
                lap_number=int(gfx.completedLaps) + 1,
                # the platform chunk schema wants the 0..1 lap fraction here
                lap_distance=max(0.0, min(1.0, float(gfx.normalizedCarPosition))),
                track_length=track_len,
                lap_time_current=float(gfx.iCurrentTime) / 1000.0 if gfx.iCurrentTime > 0 else None,
                lap_time_last=float(gfx.iLastTime) / 1000.0 if gfx.iLastTime > 0 else None,
                lap_time_best=float(gfx.iBestTime) / 1000.0 if gfx.iBestTime > 0 else None,
                in_pit=bool(gfx.isInPit or gfx.isInPitLane),
                is_racing=int(gfx.status) == ACC_STATUS_LIVE,
                # V depth (loop 4): ACC vehicle-level channels (all from the
                # physics page; no engine water/oil temp or brakeBias in the
                # ACC shared-memory struct -> honest absence).
                drs_state=int(phys.drs),  # 0/1 (GT3 has no DRS; stays 0)
                ers_pct=float(phys.kersCharge),  # 0..1
                tc_active=bool(phys.tc > 0.0),  # tc = realtime cut amount
                abs_active=bool(phys.abs > 0.0),  # abs = realtime cut amount
                damage=_acc_damage(phys),
                air_temp=float(phys.airTemp) or None,
                track_temp=float(phys.roadTemp) or None,
            )
        except Exception:
            return None

    @property
    def game_name(self) -> str:
        return "acc"

    def validate_data(self, data: NormalizedTelemetry) -> bool:
        """Sanity-check ACC data before it enters the stream."""
        if data.speed > 150.0 or data.speed < 0:  # >540 km/h is not a GT3
            return False
        if data.engine_rpm < 0 or data.engine_rpm > 12000:
            return False
        if data.lap_distance is not None and not 0.0 <= data.lap_distance <= 1.0:
            return False
        return True

    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        try:
            pages = msgpack.unpackb(raw_data)
            static = _from_buffer(StaticPage, pages.get(b"static") or pages.get("static"))
            if static is None:
                return None
            name = " ".join(p for p in (_wstr(static.playerName),
                                        _wstr(static.playerSurname)) if p)
            gfx = _from_buffer(GraphicsPage, pages.get(b"graphics") or pages.get("graphics"))
            session_type = "Practice"
            if gfx is not None:
                # graphics.session: 0 unknown? practice=0..  spec enum:
                # AC_PRACTICE=0, AC_QUALIFY=1, AC_RACE=2, AC_HOTLAP=3, ...
                session_type = {0: "Practice", 1: "Qualifying", 2: "Race",
                                3: "Hotlap"}.get(int(gfx.session), "Practice")
            return TelemetryMetadata(
                game_name="acc",
                track_name=_wstr(static.track) or "Unknown Track",
                car_name=_wstr(static.carModel) or "Unknown Car",
                session_type=session_type,
                session_start_time=datetime.now(timezone.utc),
                player_name=name or _wstr(static.playerNick) or None,
                track_length=float(static.trackSPlineLength) or 0.0,
                track_config=_wstr(static.trackConfiguration) or None,
            )
        except Exception:
            return None
