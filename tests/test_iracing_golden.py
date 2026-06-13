"""iRacing parser correctness against REAL field shapes (loop 4, R12/R13).

The simulated reader masks these by feeding scalar CarIdxX and clean
values; here we feed the genuine array/bitfield/fraction shapes.
"""
import math

import pytest

from racecraft.parsers.iracing import IRacingParser
from tests.fixtures.iracing_frames import make_iracing_frame


def test_position_is_not_all_zeros_after_motion():
    p = IRacingParser()
    # frame 0 anchors at origin (no prior dt)
    t0 = p.parse(make_iracing_frame(SessionTime=10.0))
    assert (t0.position.x, t0.position.y, t0.position.z) == (0.0, 0.0, 0.0)
    # frame 1, +0.1s at 45 m/s forward, yaw 0 -> advances +x by ~4.5m
    t1 = p.parse(make_iracing_frame(SessionTime=10.1))
    assert t1.position.x == pytest.approx(4.5, abs=1e-6)
    assert t1.position.y == pytest.approx(0.0, abs=1e-9)
    # NOT the all-zeros bug
    assert (t1.position.x, t1.position.y) != (0.0, 0.0)


def test_yaw_rotates_velocity_into_world():
    p = IRacingParser()
    p.parse(make_iracing_frame(SessionTime=0.0, Yaw=math.pi / 2))
    # heading +90deg (left): forward velocity should advance world +y
    t = p.parse(make_iracing_frame(SessionTime=0.1, Yaw=math.pi / 2,
                                   VelocityX=45.0, VelocityY=0.0))
    assert t.position.y == pytest.approx(4.5, abs=1e-6)
    assert t.position.x == pytest.approx(0.0, abs=1e-6)


def test_caridx_arrays_do_not_crash_or_leak():
    p = IRacingParser()
    # explicit non-zero garbage in the arrays must not reach position
    t = p.parse(make_iracing_frame(
        SessionTime=5.0, CarIdxX=[999.0] * 64, CarIdxY=[999.0] * 64))
    assert t is not None
    assert t.position.x == 0.0 and t.position.y == 0.0  # integration, not array[0]


def test_engine_max_rpm_is_not_the_bitfield():
    p = IRacingParser()
    t = p.parse(make_iracing_frame(EngineWarnings=4))
    assert t.engine_max_rpm is None        # honest unknown, not 4
    assert t.engine_rpm == 7200.0


def test_fuel_capacity_is_not_the_fraction():
    p = IRacingParser()
    t = p.parse(make_iracing_frame(FuelLevel=32.5, FuelLevelPct=0.65))
    assert t.fuel_capacity is None         # not 0.65
    assert t.fuel_remaining == 32.5        # liters, correct


def test_new_session_resets_the_path():
    p = IRacingParser()
    p.parse(make_iracing_frame(SessionUniqueID=1, SessionTime=0.0))
    moved = p.parse(make_iracing_frame(SessionUniqueID=1, SessionTime=0.5))
    assert moved.position.x > 0
    # different session -> path resets to origin
    fresh = p.parse(make_iracing_frame(SessionUniqueID=2, SessionTime=100.0))
    assert (fresh.position.x, fresh.position.y, fresh.position.z) == (0, 0, 0)


def test_dt_clamp_ignores_teleport_jumps():
    p = IRacingParser()
    p.parse(make_iracing_frame(SessionTime=0.0))
    # a 60s jump (pause / garage) must not integrate 60s of velocity
    t = p.parse(make_iracing_frame(SessionTime=60.0, VelocityX=45.0))
    assert t.position.x == 0.0     # clamped out


def test_parser_validate_still_passes_golden_frame():
    p = IRacingParser()
    t = p.parse(make_iracing_frame())
    assert p.validate_data(t) is True


def test_sim_convention_integrates_to_a_circle():
    """The simulated reader emits car-frame velocity + yaw=heading; the
    parser must integrate that into a roughly circular path (a closed lap),
    not a double-rotated figure. Validates the sim<->parser convention
    match that keeps the headless e2e track map correct."""
    import math as _m
    from racecraft.parsers.iracing import IRacingParser
    from tests.fixtures.iracing_frames import make_iracing_frame
    p = IRacingParser()
    speed, radius = 40.0, 200.0
    dt = 0.05
    yaw_rate = speed / radius
    xs, ys, t = [], [], 0.0
    heading = 0.0
    for i in range(int((2 * _m.pi / yaw_rate) / dt) + 1):
        tt = p.parse(make_iracing_frame(
            SessionUniqueID=77, SessionTime=t,
            VelocityX=speed, VelocityY=0.0, Yaw=heading))
        xs.append(tt.position.x); ys.append(tt.position.y)
        t += dt; heading += yaw_rate * dt
    # the path should span ~2*radius in each axis and return near start
    assert max(xs) - min(xs) == pytest.approx(2 * radius, rel=0.15)
    assert max(ys) - min(ys) == pytest.approx(2 * radius, rel=0.15)
    # closes the loop (last point near the first)
    assert abs(xs[-1] - xs[0]) < radius * 0.2


def test_offtrack_flag_parsed():
    from racecraft.parsers.iracing import IRacingParser
    from tests.fixtures.iracing_frames import make_iracing_frame
    p = IRacingParser()
    on = p.parse(make_iracing_frame(IsOnTrack=True))
    off = p.parse(make_iracing_frame(IsOnTrack=False))
    assert on.is_racing is True
    assert off.is_racing is False


def test_v_depth_channels_populate():
    """V depth (loop 4): iRacing realtime vehicle channels reach the model.
    iRacing exposes no per-wheel camber/load/force/ride-height in realtime
    telemetry (setup-only) -> those stay None (honest absence). dcBrakeBias
    normalises to a 0-1 front fraction. Derivation only; real-world
    correctness is rig-deferred (owner rule 10)."""
    p = IRacingParser()
    t = p.parse(make_iracing_frame(
        WaterTemp=95.0, OilTemp=110.0, OilPress=3.5, FuelPress=4.1,
        SteeringWheelTorque=18.0, dcBrakeBias=54.0, DRS_Status=1,
        AirTemp=21.0, TrackTempCrew=33.0))
    assert t.engine_water_temp == 95.0
    assert t.engine_oil_temp == 110.0
    assert t.engine_oil_pressure == 3.5
    assert t.fuel_pressure == 4.1
    assert t.steering_torque == 18.0
    assert t.brake_bias == 0.54           # 54.0% -> 0.54 front fraction
    assert t.drs_state == 1
    assert t.air_temp == 21.0
    assert t.track_temp == 33.0
    # iRacing has no realtime per-wheel camber/load -> honest None
    assert t.wheels[0].camber is None
    assert t.wheels[0].wheel_load is None


def test_brake_bias_passthrough_when_already_fraction():
    p = IRacingParser()
    t = p.parse(make_iracing_frame(dcBrakeBias=0.52))
    assert t.brake_bias == 0.52           # already a fraction -> unchanged
