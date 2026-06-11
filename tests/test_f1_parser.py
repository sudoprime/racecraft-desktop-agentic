"""
F1 24/25 UDP parser conformance tests (platform loop 2, C3).

Builds packets from the same ctypes structs (sizes pinned against the
published EA spec) and asserts normalization: km/h->m/s, the RL/RR/FL/FR
-> FL/FR/RL/RR wheel reorder, ms lap times, meter lap distance
normalized by track length (negatives clamped), pit/driver status, and
the reader's packet routing.
"""
import ctypes
import sys
from pathlib import Path

import msgpack
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.parsers.f1 import (
    HEADER_SIZE, MAX_CARS, PACKET_LAP, PACKET_MOTION, PACKET_SESSION,
    PACKET_TELEMETRY, CarMotionData, CarTelemetryData, F1Parser, LapData,
    PacketHeader, SessionPrefix,
)
from racecraft.readers.f1 import F1Reader

PLAYER = 3  # exercise non-zero player index


def make_header(packet_id: int) -> bytes:
    h = PacketHeader()
    h.m_packetFormat = 2024
    h.m_packetId = packet_id
    h.m_sessionUID = 777
    h.m_overallFrameIdentifier = 5000
    h.m_playerCarIndex = PLAYER
    return bytes(h)


def car_array_packet(packet_id: int, cls, player_struct) -> bytes:
    blank = bytes(ctypes.sizeof(cls))
    cars = [blank] * MAX_CARS
    cars[PLAYER] = bytes(player_struct)
    return make_header(packet_id) + b"".join(cars)


def make_frame(lap_distance=2600.0, pit_status=0, gear=5):
    tel = CarTelemetryData()
    tel.m_speed = 288            # km/h -> 80 m/s
    tel.m_throttle = 0.9
    tel.m_steer = -0.3
    tel.m_brake = 0.05
    tel.m_clutch = 50
    tel.m_gear = gear
    tel.m_engineRPM = 11000
    # spec order RL, RR, FL, FR — distinct values to verify the reorder
    for i, v in enumerate([95, 96, 91, 92]):
        tel.m_tyresSurfaceTemperature[i] = v
        tel.m_tyresInnerTemperature[i] = v + 5
        tel.m_brakesTemperature[i] = 400 + i
        tel.m_tyresPressure[i] = 22.0 + i

    lap = LapData()
    lap.m_lastLapTimeInMS = 91_300
    lap.m_currentLapTimeInMS = 45_120
    lap.m_lapDistance = lap_distance
    lap.m_currentLapNum = 7
    lap.m_pitStatus = pit_status
    lap.m_driverStatus = 1  # flying lap

    motion = CarMotionData()
    motion.m_worldPositionX = 120.5
    motion.m_worldPositionZ = -300.25
    motion.m_gForceLateral = 3.4
    motion.m_gForceLongitudinal = -4.1
    motion.m_yaw = 1.2

    session = SessionPrefix()
    session.m_trackLength = 5200
    session.m_trackId = 7        # Silverstone
    session.m_sessionType = 10   # Race
    session.m_formula = 0

    return msgpack.packb({
        "telemetry": car_array_packet(PACKET_TELEMETRY, CarTelemetryData, tel),
        "lap": car_array_packet(PACKET_LAP, LapData, lap),
        "motion": car_array_packet(PACKET_MOTION, CarMotionData, motion),
        "session": make_header(PACKET_SESSION) + bytes(session),
    })


class TestF1ParserConformance:
    def test_struct_sizes_match_published_spec(self):
        assert HEADER_SIZE == 29
        assert ctypes.sizeof(CarTelemetryData) == 60
        assert ctypes.sizeof(LapData) == 57
        assert ctypes.sizeof(CarMotionData) == 60

    def test_core_normalization(self):
        t = F1Parser().parse(make_frame())
        assert t is not None and t.game_name == "f1"
        assert t.speed == pytest.approx(80.0)       # 288 km/h
        assert t.gear == 5
        assert t.clutch == pytest.approx(0.5)       # 0-100 -> 0-1
        assert t.steering == pytest.approx(-0.3, abs=1e-6)
        assert t.g_force_lateral == pytest.approx(3.4)
        assert t.g_force_longitudinal == pytest.approx(-4.1)
        assert t.position.x == pytest.approx(120.5)

    def test_wheel_reorder_spec_to_model(self):
        t = F1Parser().parse(make_frame())
        assert [w.position.value for w in t.wheels] == ["FL", "FR", "RL", "RR"]
        # FL in the model must be spec index 2 (surface 91)
        assert t.wheels[0].tire_surface_temp == pytest.approx(91)
        assert t.wheels[1].tire_surface_temp == pytest.approx(92)
        assert t.wheels[2].tire_surface_temp == pytest.approx(95)  # RL = spec 0
        assert t.wheels[3].brake_temp == pytest.approx(401)        # RR = spec 1

    def test_lap_mapping(self):
        t = F1Parser().parse(make_frame())
        assert t.lap_number == 7
        assert t.lap_time_last == pytest.approx(91.3)
        assert t.lap_distance == pytest.approx(2600.0 / 5200.0)
        assert t.track_length == pytest.approx(5200.0)

    def test_negative_lap_distance_clamped(self):
        t = F1Parser().parse(make_frame(lap_distance=-120.0))
        assert t.lap_distance == 0.0

    def test_pit_status(self):
        assert F1Parser().parse(make_frame(pit_status=1)).in_pit is True
        assert F1Parser().parse(make_frame(pit_status=0)).in_pit is False

    def test_metadata_from_session(self):
        md = F1Parser().parse_metadata(make_frame())
        assert md.track_name == "Silverstone"
        assert md.session_type == "Race"
        assert md.track_length == pytest.approx(5200.0)

    def test_garbage_returns_none(self):
        p = F1Parser()
        assert p.parse(b"junk") is None
        assert p.parse(msgpack.packb({"telemetry": b"\x00" * 10})) is None
        assert p.parse_metadata(msgpack.packb({})) is None


class TestF1ReaderRouting:
    def test_combined_frame_emitted_on_telemetry_tick(self):
        r = F1Reader()
        pages = msgpack.unpackb(make_frame())
        get = lambda k: pages.get(k.encode()) or pages.get(k)
        assert r._handle_packet(get("session")) is None   # stored, no emit
        assert r._handle_packet(get("lap")) is None
        assert r._handle_packet(get("motion")) is None
        frame = r._handle_packet(get("telemetry"))         # tick -> emit
        assert frame is not None
        t = F1Parser().parse(frame)
        assert t is not None and t.speed == pytest.approx(80.0)
        assert t.lap_number == 7                            # lap data included

    def test_unknown_and_short_packets_ignored(self):
        r = F1Reader()
        assert r._handle_packet(b"x") is None
        assert r._handle_packet(make_header(99)) is None
