"""Golden raw-iRacing telemetry frames (loop 4, R15 / D sprint).

These reproduce the REAL iRacing SDK field SHAPES that the simulated
reader does not — most importantly CarIdxX/Y/Z as 64-element per-car
ARRAYS (not the player's scalar), EngineWarnings as a status BITFIELD,
and FuelLevelPct as a 0-1 FRACTION. The all-zeros position bug (R12) and
the wrong rpm/fuel fields (R13) were invisible precisely because the sim
reader injects scalar/clean values; these fixtures pin the real shapes
so the bugs cannot silently return.
"""
import msgpack

# A plausible "moving forward, flat, level" frame. Velocities are in the
# CAR frame: X=forward, Y=left, Z=up (m/s).
_BASE = {
    "SessionUniqueID": 12345,
    "SessionTick": 1000,
    "SessionTime": 10.0,
    "Speed": 45.0,                 # m/s (~100 mph)
    "RPM": 7200.0,
    "EngineWarnings": 4,           # BITFIELD (e.g. a warning bit) — NOT a redline
    "Gear": 4,
    "Throttle": 0.85,
    "Brake": 0.0,
    "Clutch": 1.0,
    "SteeringWheelAngle": 0.1,
    "SteeringWheelAngleMax": 9.0,
    # Per-car ARRAYS (64 cars) — the player isn't a scalar here:
    "CarIdxX": [0.0] * 64,
    "CarIdxY": [0.0] * 64,
    "CarIdxZ": [0.0] * 64,
    "VelocityX": 45.0,             # forward
    "VelocityY": 0.0,
    "VelocityZ": 0.0,
    "Yaw": 0.0,
    "Pitch": 0.0, "Roll": 0.0,
    "YawRate": 0.0, "PitchRate": 0.0, "RollRate": 0.0,
    "LatAccel": 0.2, "VertAccel": 9.8, "LongAccel": 1.5,
    "FuelLevel": 32.5,             # liters remaining (correct)
    "FuelLevelPct": 0.65,          # 0-1 fraction — NOT capacity
    "Lap": 3,
    "LapDist": 1234.5,
    "LapCurrentLapTime": 42.1,
    "LapLastLapTime": 91.2,
    "LapBestLapTime": 90.8,
    "OnPitRoad": False,
    "IsOnTrack": True,
    # a couple of tire channels so wheels build
    "LFtempCL": 80.0, "LFtempCM": 82.0, "LFtempCR": 81.0, "LFpressure": 165.0,
}


def make_iracing_frame(**overrides) -> bytes:
    """Pack a raw iRacing-shaped frame (with overrides) to msgpack bytes,
    exactly as the reader feeds the parser."""
    frame = dict(_BASE)
    frame.update(overrides)
    return msgpack.packb(frame)
