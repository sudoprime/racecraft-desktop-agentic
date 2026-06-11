"""
Assetto Corsa (original, 1.x) telemetry parser.

Parses the Kunos shared-memory pages (acpmf_physics / acpmf_graphics /
acpmf_static — same page names ACC later reused) into NormalizedTelemetry.
Struct layouts follow the published AC 1.16 shared-memory spec; strings are
uint16 arrays decoded UTF-16LE (see parsers/acc.py for why).

Differences from ACC that matter here:
- physics.tyreTempI/M/O (inner/middle/outer) ARE populated in AC.
- graphics.carCoordinates is the PLAYER's world position directly
  (a single float[3] — ACC widened it to a 60-car table).
- physics ends with isAIControlled, tyreContactPoint/Normal/Heading,
  brakeBias and localVelocity (AC additions over the shared prefix).

STATUS: implemented to spec, pending manual validation on real hardware —
see docs/COMPATIBILITY.md in the platform repo.
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
from racecraft.parsers.acc import _wstr

PSI_TO_BAR = 0.0689476
AC_STATUS_LIVE = 2  # AC_LIVE

_WHEEL_ORDER = (
    WheelPosition.FRONT_LEFT,
    WheelPosition.FRONT_RIGHT,
    WheelPosition.REAR_LEFT,
    WheelPosition.REAR_RIGHT,
)


class ACPhysicsPage(ctypes.LittleEndianStructure):
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
        ("tyreTempI", ctypes.c_float * 4),
        ("tyreTempM", ctypes.c_float * 4),
        ("tyreTempO", ctypes.c_float * 4),
        # AC additions past the ACC-shared prefix
        ("isAIControlled", ctypes.c_int32),
        ("tyreContactPoint", (ctypes.c_float * 3) * 4),
        ("tyreContactNormal", (ctypes.c_float * 3) * 4),
        ("tyreContactHeading", (ctypes.c_float * 3) * 4),
        ("brakeBias", ctypes.c_float),
        ("localVelocity", ctypes.c_float * 3),
    ]


class ACGraphicsPage(ctypes.LittleEndianStructure):
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
        ("carCoordinates", ctypes.c_float * 3),  # player position (AC layout)
        ("penaltyTime", ctypes.c_float),
        ("flag", ctypes.c_int32),
        ("idealLineOn", ctypes.c_int32),
        ("isInPitLane", ctypes.c_int32),
        ("surfaceGrip", ctypes.c_float),
    ]


# AC's static page matches the prefix ACC kept; reuse the field list from
# the ACC StaticPage (it stops at trackConfiguration, which AC 1.5+ has).
from racecraft.parsers.acc import StaticPage as ACStaticPage  # noqa: E402


def _from_buffer(cls, raw: bytes):
    if raw is None or len(raw) < ctypes.sizeof(cls):
        return None
    return cls.from_buffer_copy(raw[: ctypes.sizeof(cls)])


class ACParser(ITelemetryParser):
    """Parses msgpack frames of {'physics','graphics','static'} raw pages."""

    def __init__(self):
        self._frame = 0

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        try:
            pages = msgpack.unpackb(raw_data)
            phys = _from_buffer(ACPhysicsPage, pages.get(b"physics") or pages.get("physics"))
            gfx = _from_buffer(ACGraphicsPage, pages.get(b"graphics") or pages.get("graphics"))
            static = _from_buffer(ACStaticPage, pages.get(b"static") or pages.get("static"))
            if phys is None or gfx is None:
                return None

            wheels = []
            for i, pos in enumerate(_WHEEL_ORDER):
                wheels.append(WheelData(
                    position=pos,
                    tire_surface_temp=float(phys.tyreCoreTemperature[i]) or None,
                    tire_inner_temp=float(phys.tyreTempI[i]) or None,
                    tire_middle_temp=float(phys.tyreTempM[i]) or None,
                    tire_outer_temp=float(phys.tyreTempO[i]) or None,
                    brake_temp=float(phys.brakeTemp[i]) or None,
                    tire_pressure=float(phys.wheelsPressure[i]) * PSI_TO_BAR or None,
                    suspension_travel=float(phys.suspensionTravel[i]),
                    wheel_speed=float(phys.wheelAngularSpeed[i]),
                    slip_ratio=float(phys.wheelSlip[i]),
                    tire_wear=float(phys.tyreWear[i]),
                ))

            self._frame += 1
            track_len = float(static.trackSPlineLength) if static else None
            return NormalizedTelemetry(
                game_name="assetto_corsa",
                session_id="",
                timestamp=datetime.now(timezone.utc),
                frame_number=self._frame,
                speed=max(0.0, float(phys.speedKmh) / 3.6),
                gear=int(phys.gear) - 1,  # 0=R, 1=N, 2=1st -> model: -1/0/1+
                engine_rpm=float(phys.rpms),
                engine_max_rpm=float(static.maxRpm) if static and static.maxRpm > 0 else None,
                throttle=min(1.0, max(0.0, float(phys.gas))),
                brake=min(1.0, max(0.0, float(phys.brake))),
                clutch=min(1.0, max(0.0, float(phys.clutch))),
                steering=min(1.0, max(-1.0, float(phys.steerAngle))),
                position=Vector3(x=float(gfx.carCoordinates[0]),
                                 y=float(gfx.carCoordinates[1]),
                                 z=float(gfx.carCoordinates[2])),
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
                # platform chunk schema wants the 0..1 lap fraction here
                lap_distance=max(0.0, min(1.0, float(gfx.normalizedCarPosition))),
                track_length=track_len,
                lap_time_current=float(gfx.iCurrentTime) / 1000.0 if gfx.iCurrentTime > 0 else None,
                lap_time_last=float(gfx.iLastTime) / 1000.0 if gfx.iLastTime > 0 else None,
                lap_time_best=float(gfx.iBestTime) / 1000.0 if gfx.iBestTime > 0 else None,
                in_pit=bool(gfx.isInPit or gfx.isInPitLane),
                is_racing=int(gfx.status) == AC_STATUS_LIVE,
            )
        except Exception:
            return None

    @property
    def game_name(self) -> str:
        return "assetto_corsa"

    def validate_data(self, data: NormalizedTelemetry) -> bool:
        if data.speed > 150.0 or data.speed < 0:
            return False
        if data.engine_rpm < 0 or data.engine_rpm > 22000:  # AC has F1 content
            return False
        if data.lap_distance is not None and not 0.0 <= data.lap_distance <= 1.0:
            return False
        return True

    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        try:
            pages = msgpack.unpackb(raw_data)
            static = _from_buffer(ACStaticPage, pages.get(b"static") or pages.get("static"))
            if static is None:
                return None
            gfx = _from_buffer(ACGraphicsPage, pages.get(b"graphics") or pages.get("graphics"))
            session_type = "Practice"
            if gfx is not None:
                # AC_SESSION_TYPE: 0 practice, 1 qualify, 2 race, 3 hotlap,
                # 4 time attack, 5 drift, 6 drag
                session_type = {0: "Practice", 1: "Qualifying", 2: "Race",
                                3: "Hotlap", 4: "Time Attack", 5: "Drift",
                                6: "Drag"}.get(int(gfx.session), "Practice")
            name = " ".join(p for p in (_wstr(static.playerName),
                                        _wstr(static.playerSurname)) if p)
            return TelemetryMetadata(
                game_name="assetto_corsa",
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
