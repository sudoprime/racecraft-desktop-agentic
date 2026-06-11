"""
ACC parser conformance tests (platform loop 2, C2).

Builds shared-memory pages from the SAME ctypes structs the parser reads
(spec-internal consistency; on-rig manual validation confirms the spec
itself) and asserts the normalized output: units, wheel order, lap
mapping, pit flags, metadata strings.
"""
import ctypes
import sys
from pathlib import Path

import msgpack
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.parsers.acc import (
    ACCParser, GraphicsPage, PhysicsPage, StaticPage, PSI_TO_BAR,
)


def _wset(field, text: str):
    raw = text.encode("utf-16-le")
    for i, b in enumerate(raw[: len(field) * 2 - 2]):
        pass
    units = list(memoryview(raw).cast("H")) if len(raw) % 2 == 0 else []
    for i in range(len(field)):
        field[i] = units[i] if i < len(units) else 0


def make_frame(**overrides):
    phys = PhysicsPage()
    phys.packetId = 42
    phys.gas, phys.brake, phys.clutch = 0.75, 0.10, 0.0
    phys.gear = 4            # ACC: 0=R 1=N 2=1st -> 4 = 3rd
    phys.rpms = 6200
    phys.steerAngle = -0.25
    phys.speedKmh = 180.0
    phys.accG[0], phys.accG[1], phys.accG[2] = 1.2, 0.1, -0.4
    for i in range(4):
        phys.wheelsPressure[i] = 27.5          # psi
        phys.tyreCoreTemperature[i] = 82.0 + i
        phys.brakeTemp[i] = 300.0 + 10 * i
        phys.suspensionTravel[i] = 0.02
        phys.wheelSlip[i] = 0.05
    phys.fuel = 41.5
    phys.heading, phys.pitch, phys.roll = 1.1, 0.01, -0.02

    gfx = GraphicsPage()
    gfx.packetId = 42
    gfx.status = 2           # AC_LIVE
    gfx.session = 0          # practice
    gfx.completedLaps = 2    # -> lap_number 3
    gfx.normalizedCarPosition = 0.435
    gfx.iCurrentTime, gfx.iLastTime, gfx.iBestTime = 45_120, 91_300, 89_700
    gfx.isInPit, gfx.isInPitLane = 0, 0
    gfx.activeCars = 2
    gfx.playerCarID = 7
    gfx.carID[0], gfx.carID[1] = 3, 7
    gfx.carCoordinates[1][0] = 101.5
    gfx.carCoordinates[1][1] = 2.0
    gfx.carCoordinates[1][2] = -340.25

    static = StaticPage()
    static.maxRpm = 7200
    static.maxFuel = 110.0
    static.trackSPlineLength = 5200.0
    _wset(static.track, "monza")
    _wset(static.carModel, "ferrari_296_gt3")
    _wset(static.playerName, "Max")
    _wset(static.playerSurname, "Mustermann")

    for obj, kv in overrides.items():
        target = {"phys": phys, "gfx": gfx, "static": static}[obj]
        for k, v in kv.items():
            setattr(target, k, v)

    return msgpack.packb({
        "physics": bytes(phys), "graphics": bytes(gfx), "static": bytes(static),
    })


class TestACCParserConformance:
    def test_core_normalization(self):
        t = ACCParser().parse(make_frame())
        assert t is not None
        assert t.game_name == "acc"
        assert t.speed == pytest.approx(50.0)          # 180 km/h -> m/s
        assert t.gear == 3                              # ACC 4 -> model 3rd
        assert t.throttle == 0.75 and t.brake == pytest.approx(0.10)
        assert t.steering == pytest.approx(-0.25)
        assert t.g_force_lateral == pytest.approx(1.2)
        assert t.g_force_longitudinal == pytest.approx(-0.4)

    def test_lap_mapping_and_track(self):
        t = ACCParser().parse(make_frame())
        assert t.lap_number == 3                        # completedLaps 2 + 1
        assert t.lap_distance == pytest.approx(0.435)   # normalized 0..1
        assert t.track_length == pytest.approx(5200.0)
        assert t.lap_time_last == pytest.approx(91.3)
        assert t.lap_time_best == pytest.approx(89.7)

    def test_wheels_order_and_units(self):
        t = ACCParser().parse(make_frame())
        assert [w.position.value for w in t.wheels] == ["FL", "FR", "RL", "RR"]
        assert t.wheels[0].tire_pressure == pytest.approx(27.5 * PSI_TO_BAR)
        assert t.wheels[2].tire_middle_temp == pytest.approx(84.0)
        assert t.wheels[3].brake_temp == pytest.approx(330.0)
        # ACC doesn't populate legacy I/O temps — must be None, not 0
        assert t.wheels[0].tire_inner_temp is None
        assert t.wheels[0].tire_outer_temp is None

    def test_player_position_via_car_id_table(self):
        t = ACCParser().parse(make_frame())
        assert t.position.x == pytest.approx(101.5)
        assert t.position.z == pytest.approx(-340.25)

    def test_pit_flags(self):
        t = ACCParser().parse(make_frame(gfx={"isInPitLane": 1}))
        assert t.in_pit is True
        t2 = ACCParser().parse(make_frame(gfx={"status": 1}))  # replay
        assert t2.is_racing is False

    def test_metadata(self):
        md = ACCParser().parse_metadata(make_frame())
        assert md.track_name == "monza"
        assert md.car_name == "ferrari_296_gt3"
        assert md.player_name == "Max Mustermann"
        assert md.track_length == pytest.approx(5200.0)
        assert md.session_type == "Practice"

    def test_garbage_returns_none(self):
        p = ACCParser()
        assert p.parse(b"not msgpack") is None
        assert p.parse(msgpack.packb({"physics": b"\x00" * 8})) is None
        assert p.parse_metadata(msgpack.packb({"static": b"short"})) is None


class TestACCReaderSeam:
    def test_reader_yields_frames_from_fake_maps(self):
        import asyncio
        from racecraft.readers.acc import ACCReader, _PAGES

        frame_bytes = make_frame()
        pages = msgpack.unpackb(frame_bytes)

        r = ACCReader(update_rate=200)
        r._open_maps = lambda: {
            name: pages[name.encode()] if name.encode() in pages else pages[name]
            for name in _PAGES
        }

        async def grab_one():
            assert await r.connect() is True
            async for raw in r.read_telemetry():
                await r.disconnect()
                return raw

        raw = asyncio.run(grab_one())
        t = ACCParser().parse(raw)
        assert t is not None and t.speed == pytest.approx(50.0)
