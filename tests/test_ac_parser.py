"""
Assetto Corsa (original) parser conformance tests (platform loop 2, C7).

Builds shared-memory pages from the SAME ctypes structs the parser reads
(spec-internal consistency; on-rig manual validation confirms the spec
itself) and asserts the normalized output: units, AC-specific I/M/O tyre
temps, player coordinates from graphics, gear/lap mapping, metadata.
"""
import ctypes
import sys
from pathlib import Path

import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.parsers.ac import (
    ACGraphicsPage, ACParser, ACPhysicsPage, ACStaticPage, PSI_TO_BAR,
)


def _wset(field, text: str):
    units = list(text.encode("utf-16-le"))
    for i in range(len(field)):
        lo = units[2 * i] if 2 * i < len(units) else 0
        hi = units[2 * i + 1] if 2 * i + 1 < len(units) else 0
        field[i] = lo | (hi << 8)


def make_frame(**overrides):
    phys = ACPhysicsPage()
    phys.packetId = 7
    phys.gas, phys.brake, phys.clutch = 0.6, 0.2, 0.0
    phys.gear = 3            # 0=R 1=N 2=1st -> 3 = 2nd
    phys.rpms = 5400
    phys.steerAngle = 0.3
    phys.speedKmh = 144.0    # 40 m/s
    phys.accG[0], phys.accG[1], phys.accG[2] = -0.9, 0.05, 0.6
    for i in range(4):
        phys.wheelsPressure[i] = 26.0           # psi
        phys.tyreCoreTemperature[i] = 80.0
        phys.tyreTempI[i] = 85.0                # AC populates I/M/O
        phys.tyreTempM[i] = 82.0
        phys.tyreTempO[i] = 79.0
        phys.brakeTemp[i] = 250.0
        phys.suspensionTravel[i] = 0.03
        phys.wheelSlip[i] = 0.02
    phys.fuel = 30.0

    gfx = ACGraphicsPage()
    gfx.packetId = 7
    gfx.status = 2           # AC_LIVE
    gfx.session = 0          # practice
    gfx.completedLaps = 4
    gfx.normalizedCarPosition = 0.62
    gfx.carCoordinates[0] = 101.5   # player world position, AC layout
    gfx.carCoordinates[1] = 3.0
    gfx.carCoordinates[2] = -77.25
    gfx.iCurrentTime = 45500
    gfx.iLastTime = 92500
    gfx.iBestTime = 91250
    gfx.isInPit = 0
    gfx.isInPitLane = 0

    static = ACStaticPage()
    static.maxRpm = 7800
    static.maxFuel = 60.0
    static.trackSPlineLength = 4500.0
    _wset(static.track, "magione")
    _wset(static.carModel, "ks_mazda_mx5_cup")
    _wset(static.playerName, "Test")
    _wset(static.playerSurname, "Driver")

    for k, v in overrides.items():
        for page in (phys, gfx, static):
            if hasattr(page, k):
                setattr(page, k, v)

    return msgpack.packb({
        "physics": bytes(phys),
        "graphics": bytes(gfx),
        "static": bytes(static),
    })


def test_parse_normalizes_units_and_mappings():
    t = ACParser().parse(make_frame())
    assert t is not None
    assert t.game_name == "assetto_corsa"
    assert abs(t.speed - 40.0) < 0.01                       # km/h -> m/s
    assert t.gear == 2                                       # 3 -> 2nd
    assert abs(t.throttle - 0.6) < 1e-6 and abs(t.brake - 0.2) < 1e-6
    assert t.lap_number == 5                                 # completed+1
    assert abs(t.lap_distance - 0.62) < 1e-6                 # 0..1 fraction
    assert abs(t.position.x - 101.5) < 1e-4                  # player coords
    assert abs(t.position.z - -77.25) < 1e-4
    assert t.is_racing is True
    assert abs(t.lap_time_best - 91.25) < 1e-6               # ms -> s


def test_ac_populates_imo_tyre_temps():
    t = ACParser().parse(make_frame())
    w = t.wheels[0]
    assert w.tire_inner_temp == 85.0
    assert w.tire_middle_temp == 82.0
    assert w.tire_outer_temp == 79.0
    assert abs(w.tire_pressure - 26.0 * PSI_TO_BAR) < 1e-6   # psi -> bar


def test_wheel_order_is_fl_fr_rl_rr():
    raw = make_frame()
    # mark FR (index 1) with a distinct temp
    pages = msgpack.unpackb(raw)
    phys = ACPhysicsPage.from_buffer_copy(pages["physics"])
    phys.tyreTempM[1] = 99.0
    pages["physics"] = bytes(phys)
    t = ACParser().parse(msgpack.packb(pages))
    assert t.wheels[1].position.name == "FRONT_RIGHT"
    assert t.wheels[1].tire_middle_temp == 99.0


def test_pit_and_session_status():
    t = ACParser().parse(make_frame(isInPitLane=1))
    assert t.in_pit is True
    t2 = ACParser().parse(make_frame(status=1))  # AC_REPLAY
    assert t2.is_racing is False


def test_metadata_strings_decode():
    md = ACParser().parse_metadata(make_frame())
    assert md.game_name == "assetto_corsa"
    assert md.track_name == "magione"
    assert md.car_name == "ks_mazda_mx5_cup"
    assert md.player_name == "Test Driver"
    assert md.session_type == "Practice"
    assert md.track_length == 4500.0


def test_garbage_and_short_buffers_return_none():
    p = ACParser()
    assert p.parse(b"not msgpack") is None
    assert p.parse(msgpack.packb({"physics": b"\x00" * 8})) is None
    assert p.parse_metadata(msgpack.packb({"static": b"\x01" * 4})) is None


def test_validate_data_rejects_nonsense():
    p = ACParser()
    t = p.parse(make_frame())
    assert p.validate_data(t) is True
    t.speed = 400.0  # 1440 km/h
    assert p.validate_data(t) is False


def test_detection_registry_classes_importable():
    """Every GAME_CONFIGS entry must point at a real reader/parser class."""
    import importlib
    from racecraft.detection import GameDetector
    for exe, cfg in GameDetector.GAME_CONFIGS.items():
        reader_mod = importlib.import_module(cfg["reader_module"])
        parser_mod = importlib.import_module(cfg["parser_module"])
        assert hasattr(reader_mod, cfg["reader_class"]), exe
        assert hasattr(parser_mod, cfg["parser_class"]), exe
