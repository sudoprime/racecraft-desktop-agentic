"""
rFactor 2 (rF2SharedMemoryMapPlugin) parser conformance tests (loop 2, C7).

Builds telemetry + scoring pages from the SAME ctypes structs the parser
reads: version block + header + vehicle arrays. Asserts player matching by
mIsPlayer->mID, the rF2 local frame conventions (forward = -z), kPa->bar,
Kelvin->C left/center/right temps, lap fraction from scoring, and the
reader's torn-frame rejection.
"""
import ctypes
import sys
from pathlib import Path

import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.parsers.rf2 import (
    RF2Parser,
    SCORING_VEHICLES_OFFSET,
    TELEMETRY_VEHICLES_OFFSET,
    VEH_SCORING_SIZE,
    VEH_TELEMETRY_SIZE,
    VERSION_BLOCK_SIZE,
    rF2ScoringInfo,
    rF2VehicleScoring,
    rF2VehicleTelemetry,
    KELVIN,
)
from racecraft.readers.rf2 import RF2Reader, _versions


def _vehicle_telemetry(slot_id: int) -> rF2VehicleTelemetry:
    v = rF2VehicleTelemetry()
    v.mID = slot_id
    v.mLapNumber = 6
    v.mVehicleName = b"Formula Trainer"
    v.mTrackName = b"Sebring"
    v.mGear = 3
    v.mEngineRPM = 7200.0
    v.mEngineMaxRPM = 9500.0
    v.mUnfilteredThrottle = 0.9
    v.mUnfilteredBrake = 0.0
    v.mUnfilteredSteering = 0.15
    v.mPos.x, v.mPos.y, v.mPos.z = 420.0, 8.0, -1300.0
    # forward = -z in rF2 local space: 50 m/s forward
    v.mLocalVel.x, v.mLocalVel.y, v.mLocalVel.z = 0.0, 0.0, -50.0
    v.mLocalAccel.x, v.mLocalAccel.y, v.mLocalAccel.z = 9.8, 0.0, -19.6
    v.mFuel = 33.0
    v.mFuelCapacity = 70.0
    # V depth (loop 4) vehicle-level channels
    v.mEngineWaterTemp = 95.0
    v.mEngineOilTemp = 110.0
    v.mSteeringShaftTorque = 12.5
    v.mRearBrakeBias = 0.45           # -> front bias 0.55
    v.mTurboBoostPressure = 150000.0  # Pa -> 150 kPa
    v.mRearFlapActivated = 1          # DRS active
    v.mBatteryChargeFraction = 0.6
    v.mElectricBoostMotorState = 2
    v.mFrontTireCompoundName = b"Soft"
    v.mRearTireCompoundName = b"Medium"
    v.mDentSeverity[0] = 2            # one panel fully dented -> overall 1.0
    for i in range(4):
        w = v.mWheels[i]
        w.mBrakeTemp = 410.0
        w.mPressure = 170.0           # kPa
        w.mTemperature[0] = 90.0 + KELVIN
        w.mTemperature[1] = 88.0 + KELVIN
        w.mTemperature[2] = 86.0 + KELVIN
        w.mWear = 0.95                # 1.0 = fresh
        w.mSuspensionDeflection = 0.05
        # V depth contact-patch + geometry
        w.mCamber = -0.03
        w.mToe = 0.01
        w.mTireLoad = 3200.0
        w.mLateralForce = 1500.0
        w.mLongitudinalForce = -200.0
        w.mRideHeight = 0.06
    return v


def _vehicle_scoring(slot_id: int, is_player: bool) -> rF2VehicleScoring:
    s = rF2VehicleScoring()
    s.mID = slot_id
    s.mIsPlayer = is_player
    s.mLapDist = 1830.0
    s.mBestLapTime = 124.5
    s.mLastLapTime = 125.8
    s.mTimeIntoLap = 38.0
    s.mInPits = False
    s.mVehicleName = b"Formula Trainer"
    return s


def make_frame(player_slot=2, n=3, **info_overrides) -> bytes:
    info = rF2ScoringInfo()
    info.mTrackName = b"Sebring"
    info.mSession = 1             # practice
    info.mLapDist = 6100.0        # track length
    info.mNumVehicles = n
    info.mInRealtime = True
    info.mPlayerName = b"Test Driver"
    for k, v in info_overrides.items():
        setattr(info, k, v)

    tel = bytearray(TELEMETRY_VEHICLES_OFFSET + n * VEH_TELEMETRY_SIZE)
    tel[0:4] = (7).to_bytes(4, "little")     # versionUpdateBegin
    tel[4:8] = (7).to_bytes(4, "little")     # versionUpdateEnd
    tel[VERSION_BLOCK_SIZE + 4:VERSION_BLOCK_SIZE + 8] = n.to_bytes(4, "little")
    for i in range(n):
        start = TELEMETRY_VEHICLES_OFFSET + i * VEH_TELEMETRY_SIZE
        tel[start:start + VEH_TELEMETRY_SIZE] = bytes(_vehicle_telemetry(slot_id=i + 1))

    sco = bytearray(SCORING_VEHICLES_OFFSET + n * VEH_SCORING_SIZE)
    sco[0:4] = (9).to_bytes(4, "little")
    sco[4:8] = (9).to_bytes(4, "little")
    info_off = VERSION_BLOCK_SIZE + 4
    sco[info_off:info_off + ctypes.sizeof(rF2ScoringInfo)] = bytes(info)
    for i in range(n):
        start = SCORING_VEHICLES_OFFSET + i * VEH_SCORING_SIZE
        sco[start:start + VEH_SCORING_SIZE] = bytes(
            _vehicle_scoring(slot_id=i + 1, is_player=(i + 1 == player_slot)))

    return msgpack.packb({"telemetry": bytes(tel), "scoring": bytes(sco)})


def test_player_found_by_scoring_id_across_slots():
    t = RF2Parser().parse(make_frame(player_slot=2, n=3))
    assert t is not None
    assert t.game_name == "rf2"
    # all synthetic vehicles share telemetry, so matching is proven by
    # parse succeeding with the player NOT in slot 0
    assert t.lap_number == 6


def test_local_frame_conventions():
    t = RF2Parser().parse(make_frame())
    assert abs(t.speed - 50.0) < 1e-6                  # |localVel|
    assert abs(t.g_force_lateral - 1.0) < 1e-3         # 9.8/G
    assert abs(t.g_force_longitudinal - 19.6 / 9.80665) < 1e-3  # -(-19.6)/G
    assert t.gear == 3


def test_lap_fraction_and_times_from_scoring():
    t = RF2Parser().parse(make_frame())
    assert abs(t.lap_distance - 1830.0 / 6100.0) < 1e-6
    assert abs(t.lap_time_best - 124.5) < 1e-6
    assert t.track_length == 6100.0


def test_wheel_units():
    t = RF2Parser().parse(make_frame())
    w = t.wheels[0]
    assert abs(w.tire_pressure - 1.70) < 1e-6          # kPa -> bar
    assert abs(w.tire_inner_temp - 90.0) < 1e-6        # K -> C, left
    assert abs(w.tire_outer_temp - 86.0) < 1e-6
    assert abs(w.tire_wear - 0.05) < 1e-6              # inverted


def test_v_depth_channels_populate():
    """V depth (loop 4): the newly-forwarded rF2 channels reach the model
    with the right DERIVATION (unit conversion / front-vs-rear flip / damage
    normalisation). This pins plumbing+derivation, NOT real-world axis/sign
    correctness — that's the post-loop on-rig session (owner rule 10)."""
    t = RF2Parser().parse(make_frame())
    # per-wheel contact patch / geometry
    fl = t.wheels[0]
    assert fl.camber == -0.03
    assert fl.toe == 0.01
    assert fl.wheel_load == 3200.0
    assert fl.lateral_force == 1500.0
    assert fl.longitudinal_force == -200.0
    assert fl.ride_height == 0.06
    # compound: front pair "Soft", rears "Medium"
    assert [w.tire_compound for w in t.wheels] == ["Soft", "Soft", "Medium", "Medium"]
    # vehicle-level
    assert t.engine_water_temp == 95.0
    assert t.engine_oil_temp == 110.0
    assert t.steering_torque == 12.5
    assert abs(t.brake_bias - 0.55) < 1e-9          # 1 - rear 0.45
    assert abs(t.turbo_boost - 150.0) < 1e-9        # 150000 Pa -> 150 kPa
    assert t.drs_state == 1
    assert abs(t.ers_pct - 0.6) < 1e-9
    assert t.ers_deploy_mode == 2
    assert t.damage and t.damage["overall"] == 1.0


def test_no_player_returns_none():
    assert RF2Parser().parse(make_frame(player_slot=99)) is None
    assert RF2Parser().parse(b"garbage") is None


def test_metadata():
    md = RF2Parser().parse_metadata(make_frame())
    assert md.game_name == "rf2"
    assert md.track_name == "Sebring"
    assert md.car_name == "Formula Trainer"
    assert md.player_name == "Test Driver"
    assert md.session_type == "Practice"
    assert md.track_length == 6100.0


def test_reader_rejects_torn_version_block():
    raw = bytearray(make_frame())
    # craft a telemetry page whose begin != end
    pages = msgpack.unpackb(bytes(raw))
    tel = bytearray(pages["telemetry"])
    tel[0:4] = (8).to_bytes(4, "little")
    tel[4:8] = (7).to_bytes(4, "little")
    r = RF2Reader()
    page = r._read_page(bytes(tel), len(tel), TELEMETRY_VEHICLES_OFFSET,
                        VEH_TELEMETRY_SIZE, VERSION_BLOCK_SIZE + 4)
    assert page is None
    assert _versions(bytes(tel)) == (8, 7)
