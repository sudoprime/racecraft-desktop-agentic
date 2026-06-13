"""
Automobilista 2 (AMS2) telemetry parser — Project CARS 2 shared-memory API.

AMS2 exposes the PC2 SharedMemory struct (header SHARED_MEMORY_VERSION = 14)
via the "$pcars2$" memory-mapped file when the player enables Shared Memory
(PCARS2 mode) in Options. The struct below is transcribed field-for-field
from the published SharedMemory.h (CREST2-AMS2 mirror of the official
header); types/order must not be reordered. Strings are 8-bit char arrays
(not wchar), TYRE order is FL, FR, RL, RR — same as our model.

Consistency: the header documents mSequenceNumber as odd while the game is
mid-write; the reader skips odd-sequence frames.

STATUS: implemented to spec, pending manual validation on real hardware —
see docs/COMPATIBILITY.md in the platform repo.
"""
import ctypes
from datetime import datetime, timezone
from typing import Optional

from racecraft.interfaces import ITelemetryParser
from racecraft.models import (
    NormalizedTelemetry,
    TelemetryMetadata,
    Vector3,
    WheelData,
    WheelPosition,
)

SHARED_MEMORY_VERSION = 14
STRING_LENGTH_MAX = 64
STORED_PARTICIPANTS_MAX = 64
TYRE_MAX = 4
VEC_MAX = 3
TYRE_COMPOUND_NAME_LENGTH_MAX = 40
PSI_TO_BAR = 0.0689476
G = 9.80665

# GameState enum: 0 exited, 1 front end, 2 in-game playing, 3 paused
GAME_INGAME_PLAYING = 2
# SessionState enum: 0 invalid, 1 practice, 2 test, 3 qualify,
# 4 formation lap, 5 race, 6 time attack
_SESSION_NAMES = {1: "Practice", 2: "Test", 3: "Qualifying",
                  4: "Formation", 5: "Race", 6: "Hotlap"}

_WHEEL_ORDER = (
    WheelPosition.FRONT_LEFT,
    WheelPosition.FRONT_RIGHT,
    WheelPosition.REAR_LEFT,
    WheelPosition.REAR_RIGHT,
)


class ParticipantInfo(ctypes.LittleEndianStructure):
    _fields_ = [
        ("mIsActive", ctypes.c_bool),
        ("mName", ctypes.c_char * STRING_LENGTH_MAX),
        ("mWorldPosition", ctypes.c_float * VEC_MAX),
        ("mCurrentLapDistance", ctypes.c_float),
        ("mRacePosition", ctypes.c_uint32),
        ("mLapsCompleted", ctypes.c_uint32),
        ("mCurrentLap", ctypes.c_uint32),
        ("mCurrentSector", ctypes.c_int32),
    ]


class SharedMemory(ctypes.LittleEndianStructure):
    # The header has no pack pragma — natural alignment (all scalars are
    # 4-byte except bool; identical layout under MSVC and ctypes default).
    _fields_ = [
        ("mVersion", ctypes.c_uint32),
        ("mBuildVersionNumber", ctypes.c_uint32),
        ("mGameState", ctypes.c_uint32),
        ("mSessionState", ctypes.c_uint32),
        ("mRaceState", ctypes.c_uint32),
        ("mViewedParticipantIndex", ctypes.c_int32),
        ("mNumParticipants", ctypes.c_int32),
        ("mParticipantInfo", ParticipantInfo * STORED_PARTICIPANTS_MAX),
        ("mUnfilteredThrottle", ctypes.c_float),
        ("mUnfilteredBrake", ctypes.c_float),
        ("mUnfilteredSteering", ctypes.c_float),
        ("mUnfilteredClutch", ctypes.c_float),
        ("mCarName", ctypes.c_char * STRING_LENGTH_MAX),
        ("mCarClassName", ctypes.c_char * STRING_LENGTH_MAX),
        ("mLapsInEvent", ctypes.c_uint32),
        ("mTrackLocation", ctypes.c_char * STRING_LENGTH_MAX),
        ("mTrackVariation", ctypes.c_char * STRING_LENGTH_MAX),
        ("mTrackLength", ctypes.c_float),
        ("mNumSectors", ctypes.c_int32),
        ("mLapInvalidated", ctypes.c_bool),
        ("mBestLapTime", ctypes.c_float),
        ("mLastLapTime", ctypes.c_float),
        ("mCurrentTime", ctypes.c_float),
        ("mSplitTimeAhead", ctypes.c_float),
        ("mSplitTimeBehind", ctypes.c_float),
        ("mSplitTime", ctypes.c_float),
        ("mEventTimeRemaining", ctypes.c_float),
        ("mPersonalFastestLapTime", ctypes.c_float),
        ("mWorldFastestLapTime", ctypes.c_float),
        ("mCurrentSector1Time", ctypes.c_float),
        ("mCurrentSector2Time", ctypes.c_float),
        ("mCurrentSector3Time", ctypes.c_float),
        ("mFastestSector1Time", ctypes.c_float),
        ("mFastestSector2Time", ctypes.c_float),
        ("mFastestSector3Time", ctypes.c_float),
        ("mPersonalFastestSector1Time", ctypes.c_float),
        ("mPersonalFastestSector2Time", ctypes.c_float),
        ("mPersonalFastestSector3Time", ctypes.c_float),
        ("mWorldFastestSector1Time", ctypes.c_float),
        ("mWorldFastestSector2Time", ctypes.c_float),
        ("mWorldFastestSector3Time", ctypes.c_float),
        ("mHighestFlagColour", ctypes.c_uint32),
        ("mHighestFlagReason", ctypes.c_uint32),
        ("mPitMode", ctypes.c_uint32),
        ("mPitSchedule", ctypes.c_uint32),
        ("mCarFlags", ctypes.c_uint32),
        ("mOilTempCelsius", ctypes.c_float),
        ("mOilPressureKPa", ctypes.c_float),
        ("mWaterTempCelsius", ctypes.c_float),
        ("mWaterPressureKPa", ctypes.c_float),
        ("mFuelPressureKPa", ctypes.c_float),
        ("mFuelLevel", ctypes.c_float),
        ("mFuelCapacity", ctypes.c_float),
        ("mSpeed", ctypes.c_float),
        ("mRpm", ctypes.c_float),
        ("mMaxRPM", ctypes.c_float),
        ("mBrake", ctypes.c_float),
        ("mThrottle", ctypes.c_float),
        ("mClutch", ctypes.c_float),
        ("mSteering", ctypes.c_float),
        ("mGear", ctypes.c_int32),
        ("mNumGears", ctypes.c_int32),
        ("mOdometerKM", ctypes.c_float),
        ("mAntiLockActive", ctypes.c_bool),
        ("mLastOpponentCollisionIndex", ctypes.c_int32),
        ("mLastOpponentCollisionMagnitude", ctypes.c_float),
        ("mBoostActive", ctypes.c_bool),
        ("mBoostAmount", ctypes.c_float),
        ("mOrientation", ctypes.c_float * VEC_MAX),
        ("mLocalVelocity", ctypes.c_float * VEC_MAX),
        ("mWorldVelocity", ctypes.c_float * VEC_MAX),
        ("mAngularVelocity", ctypes.c_float * VEC_MAX),
        ("mLocalAcceleration", ctypes.c_float * VEC_MAX),
        ("mWorldAcceleration", ctypes.c_float * VEC_MAX),
        ("mExtentsCentre", ctypes.c_float * VEC_MAX),
        ("mTyreFlags", ctypes.c_uint32 * TYRE_MAX),
        ("mTerrain", ctypes.c_uint32 * TYRE_MAX),
        ("mTyreY", ctypes.c_float * TYRE_MAX),
        ("mTyreRPS", ctypes.c_float * TYRE_MAX),
        ("mTyreSlipSpeed", ctypes.c_float * TYRE_MAX),  # OBSOLETE
        ("mTyreTemp", ctypes.c_float * TYRE_MAX),
        ("mTyreGrip", ctypes.c_float * TYRE_MAX),  # OBSOLETE
        ("mTyreHeightAboveGround", ctypes.c_float * TYRE_MAX),
        ("mTyreLateralStiffness", ctypes.c_float * TYRE_MAX),  # OBSOLETE
        ("mTyreWear", ctypes.c_float * TYRE_MAX),
        ("mBrakeDamage", ctypes.c_float * TYRE_MAX),
        ("mSuspensionDamage", ctypes.c_float * TYRE_MAX),
        ("mBrakeTempCelsius", ctypes.c_float * TYRE_MAX),
        ("mTyreTreadTemp", ctypes.c_float * TYRE_MAX),
        ("mTyreLayerTemp", ctypes.c_float * TYRE_MAX),
        ("mTyreCarcassTemp", ctypes.c_float * TYRE_MAX),
        ("mTyreRimTemp", ctypes.c_float * TYRE_MAX),
        ("mTyreInternalAirTemp", ctypes.c_float * TYRE_MAX),
        ("mCrashState", ctypes.c_uint32),
        ("mAeroDamage", ctypes.c_float),
        ("mEngineDamage", ctypes.c_float),
        ("mAmbientTemperature", ctypes.c_float),
        ("mTrackTemperature", ctypes.c_float),
        ("mRainDensity", ctypes.c_float),
        ("mWindSpeed", ctypes.c_float),
        ("mWindDirectionX", ctypes.c_float),
        ("mWindDirectionY", ctypes.c_float),
        ("mCloudBrightness", ctypes.c_float),
        # --- PC2/AMS2 API v9+ additions ---
        ("mSequenceNumber", ctypes.c_uint32),
        ("mWheelLocalPositionY", ctypes.c_float * TYRE_MAX),
        ("mSuspensionTravel", ctypes.c_float * TYRE_MAX),
        ("mSuspensionVelocity", ctypes.c_float * TYRE_MAX),
        ("mAirPressure", ctypes.c_float * TYRE_MAX),  # PSI
        ("mEngineSpeed", ctypes.c_float),
        ("mEngineTorque", ctypes.c_float),
        ("mWings", ctypes.c_float * 2),
        ("mHandBrake", ctypes.c_float),
        ("mCurrentSector1Times", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mCurrentSector2Times", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mCurrentSector3Times", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mFastestSector1Times", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mFastestSector2Times", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mFastestSector3Times", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mFastestLapTimes", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mLastLapTimes", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mLapsInvalidated", ctypes.c_bool * STORED_PARTICIPANTS_MAX),
        ("mRaceStates", ctypes.c_uint32 * STORED_PARTICIPANTS_MAX),
        ("mPitModes", ctypes.c_uint32 * STORED_PARTICIPANTS_MAX),
        ("mOrientations", (ctypes.c_float * VEC_MAX) * STORED_PARTICIPANTS_MAX),
        ("mSpeeds", ctypes.c_float * STORED_PARTICIPANTS_MAX),
        ("mCarNames", (ctypes.c_char * STRING_LENGTH_MAX) * STORED_PARTICIPANTS_MAX),
        ("mCarClassNames", (ctypes.c_char * STRING_LENGTH_MAX) * STORED_PARTICIPANTS_MAX),
        ("mEnforcedPitStopLap", ctypes.c_int32),
        ("mTranslatedTrackLocation", ctypes.c_char * STRING_LENGTH_MAX),
        ("mTranslatedTrackVariation", ctypes.c_char * STRING_LENGTH_MAX),
        ("mBrakeBias", ctypes.c_float),
        ("mTurboBoostPressure", ctypes.c_float),
        ("mTyreCompound", (ctypes.c_char * TYRE_COMPOUND_NAME_LENGTH_MAX) * TYRE_MAX),
        ("mPitSchedules", ctypes.c_uint32 * STORED_PARTICIPANTS_MAX),
        ("mHighestFlagColours", ctypes.c_uint32 * STORED_PARTICIPANTS_MAX),
        ("mHighestFlagReasons", ctypes.c_uint32 * STORED_PARTICIPANTS_MAX),
        ("mNationalities", ctypes.c_uint32 * STORED_PARTICIPANTS_MAX),
        ("mSnowDensity", ctypes.c_float),
        ("mSessionDuration", ctypes.c_float),
        ("mSessionAdditionalLaps", ctypes.c_int32),
        ("mTyreTempLeft", ctypes.c_float * TYRE_MAX),
        ("mTyreTempCenter", ctypes.c_float * TYRE_MAX),
        ("mTyreTempRight", ctypes.c_float * TYRE_MAX),
        ("mDrsState", ctypes.c_uint32),
        ("mRideHeight", ctypes.c_float * TYRE_MAX),
        ("mJoyPad0", ctypes.c_uint32),
        ("mDPad", ctypes.c_uint32),
        ("mAntiLockSetting", ctypes.c_int32),
        ("mTractionControlSetting", ctypes.c_int32),
        ("mErsDeploymentMode", ctypes.c_int32),
        ("mErsAutoModeEnabled", ctypes.c_bool),
        ("mClutchTemp", ctypes.c_float),
        ("mClutchWear", ctypes.c_float),
        ("mClutchOverheated", ctypes.c_bool),
        ("mClutchSlipping", ctypes.c_bool),
        ("mYellowFlagState", ctypes.c_int32),
        ("mSessionIsPrivate", ctypes.c_bool),
        ("mLaunchStage", ctypes.c_int32),
    ]


def _cstr(field) -> str:
    return bytes(field).split(b"\x00", 1)[0].decode("utf-8", errors="ignore")


def _ams2_damage(shm) -> Optional[dict]:
    """AMS2 aero/engine damage (0-1 floats) + crash flag (loop 4, V depth).
    None when there's no damage at all."""
    aero = float(shm.mAeroDamage)
    engine = float(shm.mEngineDamage)
    crash = int(shm.mCrashState)
    if not (aero or engine or crash):
        return None
    return {"aero": aero, "engine": engine, "crash_state": crash}


def _shm(raw: bytes) -> Optional[SharedMemory]:
    if raw is None or len(raw) < ctypes.sizeof(SharedMemory):
        return None
    return SharedMemory.from_buffer_copy(raw[: ctypes.sizeof(SharedMemory)])


class AMS2Parser(ITelemetryParser):
    """Parses raw $pcars2$ SharedMemory snapshots (one page per frame)."""

    def __init__(self):
        self._frame = 0

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        try:
            shm = _shm(raw_data)
            if shm is None or shm.mVersion != SHARED_MEMORY_VERSION:
                return None
            if shm.mSequenceNumber % 2 == 1:
                return None  # game mid-write; reader normally filters these

            idx = shm.mViewedParticipantIndex
            player = (shm.mParticipantInfo[idx]
                      if 0 <= idx < STORED_PARTICIPANTS_MAX else None)

            wheels = []
            for i, pos in enumerate(_WHEEL_ORDER):
                wheels.append(WheelData(
                    position=pos,
                    tire_surface_temp=float(shm.mTyreTemp[i]) or None,
                    tire_inner_temp=float(shm.mTyreTempLeft[i]) or None,
                    tire_middle_temp=float(shm.mTyreTempCenter[i]) or None,
                    tire_outer_temp=float(shm.mTyreTempRight[i]) or None,
                    brake_temp=float(shm.mBrakeTempCelsius[i]) or None,
                    tire_pressure=float(shm.mAirPressure[i]) * PSI_TO_BAR or None,
                    suspension_travel=float(shm.mSuspensionTravel[i]),
                    wheel_speed=float(shm.mTyreRPS[i]),
                    tire_wear=float(shm.mTyreWear[i]),
                    # V depth (loop 4): AMS2 exposes per-wheel ride height +
                    # compound (no per-wheel camber/forces in PC2 shm).
                    ride_height=float(shm.mRideHeight[i]),  # m
                    tire_compound=_cstr(shm.mTyreCompound[i]) or None,
                ))

            lap_fraction = None
            position = Vector3(x=0.0, y=0.0, z=0.0)
            lap_number = 1
            if player is not None:
                if shm.mTrackLength > 0:
                    lap_fraction = max(0.0, min(
                        1.0, float(player.mCurrentLapDistance) / float(shm.mTrackLength)))
                position = Vector3(x=float(player.mWorldPosition[0]),
                                   y=float(player.mWorldPosition[1]),
                                   z=float(player.mWorldPosition[2]))
                lap_number = max(1, int(player.mCurrentLap))

            self._frame += 1
            return NormalizedTelemetry(
                game_name="ams2",
                session_id="",
                timestamp=datetime.now(timezone.utc),
                frame_number=self._frame,
                speed=max(0.0, float(shm.mSpeed)),  # already m/s
                gear=int(shm.mGear),  # -1/0/1+ matches the model directly
                engine_rpm=float(shm.mRpm),
                engine_max_rpm=float(shm.mMaxRPM) if shm.mMaxRPM > 0 else None,
                throttle=min(1.0, max(0.0, float(shm.mThrottle))),
                brake=min(1.0, max(0.0, float(shm.mBrake))),
                clutch=min(1.0, max(0.0, float(shm.mClutch))),
                steering=min(1.0, max(-1.0, float(shm.mSteering))),
                position=position,
                velocity=Vector3(x=float(shm.mWorldVelocity[0]),
                                 y=float(shm.mWorldVelocity[1]),
                                 z=float(shm.mWorldVelocity[2])),
                acceleration=Vector3(x=float(shm.mLocalAcceleration[0]),
                                     y=float(shm.mLocalAcceleration[1]),
                                     z=float(shm.mLocalAcceleration[2])),
                # mOrientation is Euler [x, y, z]; PC2 local space is
                # X right, Y up, Z forward
                yaw=float(shm.mOrientation[1]),
                pitch=float(shm.mOrientation[0]),
                roll=float(shm.mOrientation[2]),
                yaw_rate=float(shm.mAngularVelocity[1]),
                pitch_rate=float(shm.mAngularVelocity[0]),
                roll_rate=float(shm.mAngularVelocity[2]),
                # local acceleration m/s^2 -> G; X lateral, Y vertical,
                # Z longitudinal in PC2 local space
                g_force_lateral=float(shm.mLocalAcceleration[0]) / G,
                g_force_vertical=float(shm.mLocalAcceleration[1]) / G,
                g_force_longitudinal=float(shm.mLocalAcceleration[2]) / G,
                wheels=wheels,
                # mFuelLevel is a 0..1 fraction of capacity
                fuel_remaining=float(shm.mFuelLevel) * float(shm.mFuelCapacity)
                if shm.mFuelCapacity > 0 else float(shm.mFuelLevel),
                fuel_capacity=float(shm.mFuelCapacity) if shm.mFuelCapacity > 0 else None,
                lap_number=lap_number,
                # platform chunk schema wants the 0..1 lap fraction here
                lap_distance=lap_fraction,
                track_length=float(shm.mTrackLength) if shm.mTrackLength > 0 else None,
                lap_time_current=float(shm.mCurrentTime) if shm.mCurrentTime > 0 else None,
                lap_time_last=float(shm.mLastLapTime) if shm.mLastLapTime > 0 else None,
                lap_time_best=float(shm.mBestLapTime) if shm.mBestLapTime > 0 else None,
                in_pit=int(shm.mPitMode) != 0,
                is_racing=int(shm.mGameState) == GAME_INGAME_PLAYING,
                # V depth (loop 4): PC2/AMS2 vehicle-level channels. Native
                # units; magnitudes rig-deferred (owner rule 10). turbo_boost
                # is AMS2-native (pressure units cross-sim-unverified).
                engine_water_temp=float(shm.mWaterTempCelsius) or None,  # C
                engine_oil_temp=float(shm.mOilTempCelsius) or None,  # C
                engine_oil_pressure=float(shm.mOilPressureKPa) or None,  # kPa
                fuel_pressure=float(shm.mFuelPressureKPa) or None,  # kPa
                turbo_boost=float(shm.mTurboBoostPressure) or None,
                brake_bias=(float(shm.mBrakeBias)
                            if 0.0 < shm.mBrakeBias <= 1.0 else None),  # front frac
                drs_state=int(shm.mDrsState),
                ers_deploy_mode=int(shm.mErsDeploymentMode),
                abs_active=bool(shm.mAntiLockActive),
                abs_level=int(shm.mAntiLockSetting),
                tc_level=int(shm.mTractionControlSetting),
                damage=_ams2_damage(shm),
                air_temp=float(shm.mAmbientTemperature) or None,
                track_temp=float(shm.mTrackTemperature) or None,
            )
        except Exception:
            return None

    @property
    def game_name(self) -> str:
        return "ams2"

    def validate_data(self, data: NormalizedTelemetry) -> bool:
        if data.speed > 150.0 or data.speed < 0:
            return False
        if data.engine_rpm < 0 or data.engine_rpm > 22000:
            return False
        if data.lap_distance is not None and not 0.0 <= data.lap_distance <= 1.0:
            return False
        return True

    def parse_metadata(self, raw_data: bytes) -> Optional[TelemetryMetadata]:
        try:
            shm = _shm(raw_data)
            if shm is None or shm.mVersion != SHARED_MEMORY_VERSION:
                return None
            idx = shm.mViewedParticipantIndex
            player_name = None
            if 0 <= idx < STORED_PARTICIPANTS_MAX:
                player_name = _cstr(shm.mParticipantInfo[idx].mName) or None
            variation = _cstr(shm.mTrackVariation)
            return TelemetryMetadata(
                game_name="ams2",
                track_name=_cstr(shm.mTrackLocation) or "Unknown Track",
                car_name=_cstr(shm.mCarName) or "Unknown Car",
                session_type=_SESSION_NAMES.get(int(shm.mSessionState), "Practice"),
                session_start_time=datetime.now(timezone.utc),
                player_name=player_name,
                track_length=float(shm.mTrackLength) or 0.0,
                track_config=variation or None,
            )
        except Exception:
            return None
