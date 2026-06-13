"""
AMS2 (PC2 shared-memory API) parser conformance tests (platform loop 2, C7).

Builds a $pcars2$ SharedMemory page from the SAME ctypes struct the parser
reads and asserts the normalized output: m/s speed passthrough, direct gear
mapping, participant-derived lap fraction/position, PSI->bar, Kelvin-free
temp fields, sequence-number torn-frame rejection, metadata.
"""
import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.parsers.ams2 import (
    AMS2Parser, SharedMemory, SHARED_MEMORY_VERSION, PSI_TO_BAR, G,
)
from racecraft.readers.ams2 import AMS2Reader


def make_page(**overrides) -> bytes:
    shm = SharedMemory()
    shm.mVersion = SHARED_MEMORY_VERSION
    shm.mGameState = 2            # in-game playing
    shm.mSessionState = 1         # practice
    shm.mViewedParticipantIndex = 0
    shm.mNumParticipants = 1
    p = shm.mParticipantInfo[0]
    p.mIsActive = True
    p.mName = b"Test Driver"
    p.mWorldPosition[0], p.mWorldPosition[1], p.mWorldPosition[2] = 250.0, 12.0, -90.0
    p.mCurrentLapDistance = 1200.0
    p.mCurrentLap = 3
    shm.mCarName = b"MetalMoro AJR"
    shm.mTrackLocation = b"Interlagos"
    shm.mTrackVariation = b"GP"
    shm.mTrackLength = 4800.0
    shm.mBestLapTime = 92.5
    shm.mLastLapTime = 93.1
    shm.mCurrentTime = 41.2
    shm.mSpeed = 55.0             # m/s
    shm.mRpm = 6800.0
    shm.mMaxRPM = 9000.0
    shm.mThrottle, shm.mBrake, shm.mClutch = 0.8, 0.05, 0.0
    shm.mSteering = -0.4
    shm.mGear = 4
    shm.mFuelLevel = 0.5          # fraction
    shm.mFuelCapacity = 90.0
    shm.mLocalAcceleration[0] = 14.7  # ~1.5 g lateral
    shm.mLocalAcceleration[1] = 9.8
    shm.mLocalAcceleration[2] = -4.9
    for i in range(4):
        shm.mTyreTemp[i] = 78.0
        shm.mAirPressure[i] = 25.0       # PSI
        shm.mBrakeTempCelsius[i] = 320.0
        shm.mTyreWear[i] = 0.1
        shm.mSuspensionTravel[i] = 0.04
        shm.mTyreTempLeft[i] = 80.0
        shm.mTyreTempCenter[i] = 78.0
        shm.mTyreTempRight[i] = 76.0
        # V depth (loop 4): per-wheel ride height + compound
        shm.mRideHeight[i] = 0.055
        shm.mTyreCompound[i].value = b"Medium"   # 2D char array -> set .value
    # V depth vehicle-level channels
    shm.mWaterTempCelsius = 96.0
    shm.mOilTempCelsius = 112.0
    shm.mOilPressureKPa = 480.0
    shm.mFuelPressureKPa = 300.0
    shm.mTurboBoostPressure = 1.2
    shm.mBrakeBias = 0.58            # front fraction (PC2 native)
    shm.mDrsState = 1
    shm.mErsDeploymentMode = 3
    shm.mAntiLockActive = True
    shm.mAntiLockSetting = 4
    shm.mTractionControlSetting = 2
    shm.mAeroDamage = 0.25
    shm.mEngineDamage = 0.1
    shm.mAmbientTemperature = 24.0
    shm.mTrackTemperature = 31.0
    shm.mSequenceNumber = 12      # even = consistent
    shm.mPitMode = 0
    for k, v in overrides.items():
        setattr(shm, k, v)
    return bytes(shm)


def test_parse_normalizes_core_channels():
    t = AMS2Parser().parse(make_page())
    assert t is not None
    assert t.game_name == "ams2"
    assert t.speed == 55.0                                # m/s passthrough
    assert t.gear == 4                                    # direct mapping
    assert abs(t.throttle - 0.8) < 1e-6
    assert abs(t.steering - -0.4) < 1e-6
    assert t.lap_number == 3
    assert abs(t.lap_distance - 1200.0 / 4800.0) < 1e-6   # 0..1 fraction
    assert abs(t.position.x - 250.0) < 1e-4               # participant pos
    assert abs(t.g_force_lateral - 14.7 / G) < 1e-4
    assert abs(t.fuel_remaining - 45.0) < 1e-4            # fraction * capacity
    assert t.is_racing is True and t.in_pit is False


def test_v_depth_channels_populate():
    """V depth (loop 4): the newly-forwarded AMS2 channels reach the model.
    Pins plumbing/derivation (per-wheel ride height + compound, engine/brake/
    aids/weather/damage), NOT real-world axis/sign correctness — that's the
    post-loop on-rig session (owner rule 10)."""
    t = AMS2Parser().parse(make_page())
    # per-wheel
    assert all(abs(w.ride_height - 0.055) < 1e-6 for w in t.wheels)
    assert all(w.tire_compound == "Medium" for w in t.wheels)
    # vehicle-level
    assert t.engine_water_temp == 96.0
    assert t.engine_oil_temp == 112.0
    assert t.engine_oil_pressure == 480.0
    assert t.fuel_pressure == 300.0
    assert abs(t.brake_bias - 0.58) < 1e-6
    assert t.drs_state == 1
    assert t.ers_deploy_mode == 3
    assert t.abs_active is True and t.abs_level == 4
    assert t.tc_level == 2
    assert t.damage is not None
    assert abs(t.damage["aero"] - 0.25) < 1e-6
    assert abs(t.damage["engine"] - 0.1) < 1e-6
    assert t.damage["crash_state"] == 0
    assert t.air_temp == 24.0 and t.track_temp == 31.0


def test_wheels_psi_to_bar_and_temps():
    t = AMS2Parser().parse(make_page())
    w = t.wheels[0]
    assert abs(w.tire_pressure - 25.0 * PSI_TO_BAR) < 1e-6
    assert w.tire_inner_temp == 80.0      # left/center/right -> I/M/O
    assert w.tire_middle_temp == 78.0
    assert w.tire_outer_temp == 76.0
    assert w.brake_temp == 320.0


def test_wrong_version_and_odd_sequence_rejected():
    p = AMS2Parser()
    assert p.parse(make_page(mVersion=9)) is None
    assert p.parse(make_page(mSequenceNumber=13)) is None
    assert p.parse(b"\x00" * 64) is None


def test_metadata():
    md = AMS2Parser().parse_metadata(make_page())
    assert md.game_name == "ams2"
    assert md.track_name == "Interlagos"
    assert md.track_config == "GP"
    assert md.car_name == "MetalMoro AJR"
    assert md.player_name == "Test Driver"
    assert md.session_type == "Practice"
    assert md.track_length == 4800.0


def test_reader_sequence_filtering():
    r = AMS2Reader()
    even = make_page(mSequenceNumber=20)
    odd = make_page(mSequenceNumber=21)
    assert r._sequence(even) == 20
    assert r._sequence(odd) == 21


def test_struct_size_is_plausible():
    # participant block alone is 64 * ~96B; whole struct must exceed it and
    # stay well under 1 MB (sanity guard against silent field-order edits)
    size = ctypes.sizeof(SharedMemory)
    assert 10_000 < size < 1_000_000
