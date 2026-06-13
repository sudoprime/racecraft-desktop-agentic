"""
rFactor 2 telemetry parser — rF2SharedMemoryMapPlugin pages.

Requires TheIronWolfModding's rF2SharedMemoryMapPlugin (the de-facto
standard; CrewChief/SimHub install it) which maps:
  $rFactor2SMMP_Telemetry$  -> rF2MappedBufferVersionBlock + rF2Telemetry
  $rFactor2SMMP_Scoring$    -> rF2MappedBufferVersionBlock + rF2Scoring

Struct layouts are transcribed from the plugin's published rF2State.h
(#pragma pack(4); Windows `long` = int32; rF2Vec3 = 3 doubles). The player
vehicle is found via scoring.mIsPlayer, then matched to its telemetry slot
by mID.

rF2 local frame: +x left, +y up, +z BACKWARD (forward speed = -mLocalVel.z).

STATUS: implemented to spec, pending manual validation on real hardware —
see docs/COMPATIBILITY.md in the platform repo.
"""
import ctypes
import math
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

MAX_MAPPED_VEHICLES = 128
KELVIN = 273.15
KPA_TO_BAR = 0.01
G = 9.80665

_WHEEL_ORDER = (
    WheelPosition.FRONT_LEFT,
    WheelPosition.FRONT_RIGHT,
    WheelPosition.REAR_LEFT,
    WheelPosition.REAR_RIGHT,
)


class rF2Vec3(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double)]


class rF2Wheel(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("mSuspensionDeflection", ctypes.c_double),
        ("mRideHeight", ctypes.c_double),
        ("mSuspForce", ctypes.c_double),
        ("mBrakeTemp", ctypes.c_double),
        ("mBrakePressure", ctypes.c_double),
        ("mRotation", ctypes.c_double),
        ("mLateralPatchVel", ctypes.c_double),
        ("mLongitudinalPatchVel", ctypes.c_double),
        ("mLateralGroundVel", ctypes.c_double),
        ("mLongitudinalGroundVel", ctypes.c_double),
        ("mCamber", ctypes.c_double),
        ("mLateralForce", ctypes.c_double),
        ("mLongitudinalForce", ctypes.c_double),
        ("mTireLoad", ctypes.c_double),
        ("mGripFract", ctypes.c_double),
        ("mPressure", ctypes.c_double),
        ("mTemperature", ctypes.c_double * 3),
        ("mWear", ctypes.c_double),
        ("mTerrainName", ctypes.c_char * 16),
        ("mSurfaceType", ctypes.c_uint8),
        ("mFlat", ctypes.c_bool),
        ("mDetached", ctypes.c_bool),
        ("mStaticUndeflectedRadius", ctypes.c_uint8),
        ("mVerticalTireDeflection", ctypes.c_double),
        ("mWheelYLocation", ctypes.c_double),
        ("mToe", ctypes.c_double),
        ("mTireCarcassTemperature", ctypes.c_double),
        ("mTireInnerLayerTemperature", ctypes.c_double * 3),
        ("mExpansion", ctypes.c_uint8 * 24),
    ]


class rF2VehicleTelemetry(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("mID", ctypes.c_int32),
        ("mDeltaTime", ctypes.c_double),
        ("mElapsedTime", ctypes.c_double),
        ("mLapNumber", ctypes.c_int32),
        ("mLapStartET", ctypes.c_double),
        ("mVehicleName", ctypes.c_char * 64),
        ("mTrackName", ctypes.c_char * 64),
        ("mPos", rF2Vec3),
        ("mLocalVel", rF2Vec3),
        ("mLocalAccel", rF2Vec3),
        ("mOri", rF2Vec3 * 3),
        ("mLocalRot", rF2Vec3),
        ("mLocalRotAccel", rF2Vec3),
        ("mGear", ctypes.c_int32),
        ("mEngineRPM", ctypes.c_double),
        ("mEngineWaterTemp", ctypes.c_double),
        ("mEngineOilTemp", ctypes.c_double),
        ("mClutchRPM", ctypes.c_double),
        ("mUnfilteredThrottle", ctypes.c_double),
        ("mUnfilteredBrake", ctypes.c_double),
        ("mUnfilteredSteering", ctypes.c_double),
        ("mUnfilteredClutch", ctypes.c_double),
        ("mFilteredThrottle", ctypes.c_double),
        ("mFilteredBrake", ctypes.c_double),
        ("mFilteredSteering", ctypes.c_double),
        ("mFilteredClutch", ctypes.c_double),
        ("mSteeringShaftTorque", ctypes.c_double),
        ("mFront3rdDeflection", ctypes.c_double),
        ("mRear3rdDeflection", ctypes.c_double),
        ("mFrontWingHeight", ctypes.c_double),
        ("mFrontRideHeight", ctypes.c_double),
        ("mRearRideHeight", ctypes.c_double),
        ("mDrag", ctypes.c_double),
        ("mFrontDownforce", ctypes.c_double),
        ("mRearDownforce", ctypes.c_double),
        ("mFuel", ctypes.c_double),
        ("mEngineMaxRPM", ctypes.c_double),
        ("mScheduledStops", ctypes.c_uint8),
        ("mOverheating", ctypes.c_bool),
        ("mDetached", ctypes.c_bool),
        ("mHeadlights", ctypes.c_bool),
        ("mDentSeverity", ctypes.c_uint8 * 8),
        ("mLastImpactET", ctypes.c_double),
        ("mLastImpactMagnitude", ctypes.c_double),
        ("mLastImpactPos", rF2Vec3),
        ("mEngineTorque", ctypes.c_double),
        ("mCurrentSector", ctypes.c_int32),
        ("mSpeedLimiter", ctypes.c_uint8),
        ("mMaxGears", ctypes.c_uint8),
        ("mFrontTireCompoundIndex", ctypes.c_uint8),
        ("mRearTireCompoundIndex", ctypes.c_uint8),
        ("mFuelCapacity", ctypes.c_double),
        ("mFrontFlapActivated", ctypes.c_uint8),
        ("mRearFlapActivated", ctypes.c_uint8),
        ("mRearFlapLegalStatus", ctypes.c_uint8),
        ("mIgnitionStarter", ctypes.c_uint8),
        ("mFrontTireCompoundName", ctypes.c_char * 18),
        ("mRearTireCompoundName", ctypes.c_char * 18),
        ("mSpeedLimiterAvailable", ctypes.c_uint8),
        ("mAntiStallActivated", ctypes.c_uint8),
        ("mUnused", ctypes.c_uint8 * 2),
        ("mVisualSteeringWheelRange", ctypes.c_float),
        ("mRearBrakeBias", ctypes.c_double),
        ("mTurboBoostPressure", ctypes.c_double),
        ("mPhysicsToGraphicsOffset", ctypes.c_float * 3),
        ("mPhysicalSteeringWheelRange", ctypes.c_float),
        ("mBatteryChargeFraction", ctypes.c_double),
        ("mElectricBoostMotorTorque", ctypes.c_double),
        ("mElectricBoostMotorRPM", ctypes.c_double),
        ("mElectricBoostMotorTemperature", ctypes.c_double),
        ("mElectricBoostWaterTemperature", ctypes.c_double),
        ("mElectricBoostMotorState", ctypes.c_uint8),
        ("mExpansion", ctypes.c_uint8 * 111),
        ("mWheels", rF2Wheel * 4),
    ]


class rF2VehicleScoring(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("mID", ctypes.c_int32),
        ("mDriverName", ctypes.c_char * 32),
        ("mVehicleName", ctypes.c_char * 64),
        ("mTotalLaps", ctypes.c_int16),
        ("mSector", ctypes.c_int8),
        ("mFinishStatus", ctypes.c_int8),
        ("mLapDist", ctypes.c_double),
        ("mPathLateral", ctypes.c_double),
        ("mTrackEdge", ctypes.c_double),
        ("mBestSector1", ctypes.c_double),
        ("mBestSector2", ctypes.c_double),
        ("mBestLapTime", ctypes.c_double),
        ("mLastSector1", ctypes.c_double),
        ("mLastSector2", ctypes.c_double),
        ("mLastLapTime", ctypes.c_double),
        ("mCurSector1", ctypes.c_double),
        ("mCurSector2", ctypes.c_double),
        ("mNumPitstops", ctypes.c_int16),
        ("mNumPenalties", ctypes.c_int16),
        ("mIsPlayer", ctypes.c_bool),
        ("mControl", ctypes.c_int8),
        ("mInPits", ctypes.c_bool),
        ("mPlace", ctypes.c_uint8),
        ("mVehicleClass", ctypes.c_char * 32),
        ("mTimeBehindNext", ctypes.c_double),
        ("mLapsBehindNext", ctypes.c_int32),
        ("mTimeBehindLeader", ctypes.c_double),
        ("mLapsBehindLeader", ctypes.c_int32),
        ("mLapStartET", ctypes.c_double),
        ("mPos", rF2Vec3),
        ("mLocalVel", rF2Vec3),
        ("mLocalAccel", rF2Vec3),
        ("mOri", rF2Vec3 * 3),
        ("mLocalRot", rF2Vec3),
        ("mLocalRotAccel", rF2Vec3),
        ("mHeadlights", ctypes.c_uint8),
        ("mPitState", ctypes.c_uint8),
        ("mServerScored", ctypes.c_uint8),
        ("mIndividualPhase", ctypes.c_uint8),
        ("mQualification", ctypes.c_int32),
        ("mTimeIntoLap", ctypes.c_double),
        ("mEstimatedLapTime", ctypes.c_double),
        ("mPitGroup", ctypes.c_char * 24),
        ("mFlag", ctypes.c_uint8),
        ("mUnderYellow", ctypes.c_bool),
        ("mCountLapFlag", ctypes.c_uint8),
        ("mInGarageStall", ctypes.c_bool),
        ("mUpgradePack", ctypes.c_uint8 * 16),
        ("mPitLapDist", ctypes.c_float),
        ("mBestLapSector1", ctypes.c_float),
        ("mBestLapSector2", ctypes.c_float),
        ("mExpansion", ctypes.c_uint8 * 48),
    ]


class rF2ScoringInfo(ctypes.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [
        ("mTrackName", ctypes.c_char * 64),
        ("mSession", ctypes.c_int32),
        ("mCurrentET", ctypes.c_double),
        ("mEndET", ctypes.c_double),
        ("mMaxLaps", ctypes.c_int32),
        ("mLapDist", ctypes.c_double),  # track length, meters
        ("pointer1", ctypes.c_uint8 * 8),  # x64 build of the game/plugin
        ("mNumVehicles", ctypes.c_int32),
        ("mGamePhase", ctypes.c_uint8),
        ("mYellowFlagState", ctypes.c_int8),
        ("mSectorFlag", ctypes.c_int8 * 3),
        ("mStartLight", ctypes.c_uint8),
        ("mNumRedLights", ctypes.c_uint8),
        ("mInRealtime", ctypes.c_bool),
        ("mPlayerName", ctypes.c_char * 32),
        ("mPlrFileName", ctypes.c_char * 64),
        ("mDarkCloud", ctypes.c_double),
        ("mRaining", ctypes.c_double),
        ("mAmbientTemp", ctypes.c_double),
        ("mTrackTemp", ctypes.c_double),
        ("mWind", rF2Vec3),
        ("mMinPathWetness", ctypes.c_double),
        ("mMaxPathWetness", ctypes.c_double),
        ("mGameMode", ctypes.c_uint8),
        ("mIsPasswordProtected", ctypes.c_bool),
        ("mMaxPlayers", ctypes.c_int32),
        ("mServerName", ctypes.c_char * 32),
        ("mStartET", ctypes.c_float),
        ("mAvgPathWetness", ctypes.c_double),
        ("mExpansion", ctypes.c_uint8 * 200),
        ("pointer2", ctypes.c_uint8 * 8),
    ]


# Each mapped file starts with the version block, then the buffer struct
# (rF2MappedBufferHeaderWithSize adds mBytesUpdatedHint).
VERSION_BLOCK_SIZE = 8  # two unsigned longs (Windows long = 4 bytes)
TELEMETRY_VEHICLES_OFFSET = VERSION_BLOCK_SIZE + 4 + 4  # hint + mNumVehicles
SCORING_VEHICLES_OFFSET = (VERSION_BLOCK_SIZE + 4
                           + ctypes.sizeof(rF2ScoringInfo))
VEH_TELEMETRY_SIZE = ctypes.sizeof(rF2VehicleTelemetry)
VEH_SCORING_SIZE = ctypes.sizeof(rF2VehicleScoring)


def _num_vehicles(raw: bytes, offset: int) -> int:
    if len(raw) < offset + 4:
        return 0
    n = int.from_bytes(raw[offset:offset + 4], "little", signed=True)
    return max(0, min(n, MAX_MAPPED_VEHICLES))


def _telemetry_vehicles(raw: bytes):
    n = _num_vehicles(raw, VERSION_BLOCK_SIZE + 4)
    for i in range(n):
        start = TELEMETRY_VEHICLES_OFFSET + i * VEH_TELEMETRY_SIZE
        if len(raw) < start + VEH_TELEMETRY_SIZE:
            return
        yield rF2VehicleTelemetry.from_buffer_copy(raw[start:start + VEH_TELEMETRY_SIZE])


def _scoring_vehicles(raw: bytes):
    info_off = VERSION_BLOCK_SIZE + 4
    # mNumVehicles lives inside rF2ScoringInfo
    n_off = info_off + rF2ScoringInfo.mNumVehicles.offset
    n = _num_vehicles(raw, n_off)
    for i in range(n):
        start = SCORING_VEHICLES_OFFSET + i * VEH_SCORING_SIZE
        if len(raw) < start + VEH_SCORING_SIZE:
            return
        yield rF2VehicleScoring.from_buffer_copy(raw[start:start + VEH_SCORING_SIZE])


def _scoring_info(raw: bytes) -> Optional[rF2ScoringInfo]:
    off = VERSION_BLOCK_SIZE + 4
    if len(raw) < off + ctypes.sizeof(rF2ScoringInfo):
        return None
    return rF2ScoringInfo.from_buffer_copy(raw[off:off + ctypes.sizeof(rF2ScoringInfo)])


def _cstr(field) -> str:
    return bytes(field).split(b"\x00", 1)[0].decode("utf-8", errors="ignore")


def _rf2_damage(tel) -> Optional[dict]:
    """rF2 body damage from mDentSeverity[8] (0/1/2 per panel). Normalised
    to the schema's 0-1 scale: per-panel list + an overall max (loop 4, V
    depth). None when there's no dent data at all."""
    dents = [int(d) for d in tel.mDentSeverity]
    if not any(dents):
        return None
    return {"dent_severity": dents, "overall": max(dents) / 2.0}


class RF2Parser(ITelemetryParser):
    """Parses msgpack frames of {'telemetry','scoring'} raw page bytes."""

    def __init__(self):
        self._frame = 0

    def _player(self, pages):
        tel_raw = pages.get(b"telemetry") or pages.get("telemetry")
        sco_raw = pages.get(b"scoring") or pages.get("scoring")
        if not tel_raw or not sco_raw:
            return None, None, None
        player_sco = next((v for v in _scoring_vehicles(sco_raw) if v.mIsPlayer), None)
        if player_sco is None:
            return None, None, _scoring_info(sco_raw)
        player_tel = next((v for v in _telemetry_vehicles(tel_raw)
                           if v.mID == player_sco.mID), None)
        return player_tel, player_sco, _scoring_info(sco_raw)

    def parse(self, raw_data: bytes) -> Optional[NormalizedTelemetry]:
        try:
            pages = msgpack.unpackb(raw_data)
            tel, sco, info = self._player(pages)
            if tel is None or sco is None:
                return None

            # Compound names: front pair share mFrontTireCompoundName, rears
            # the rear name (loop 4, V depth).
            front_compound = _cstr(tel.mFrontTireCompoundName) or None
            rear_compound = _cstr(tel.mRearTireCompoundName) or None

            wheels = []
            for i, pos in enumerate(_WHEEL_ORDER):
                w = tel.mWheels[i]
                temps = [float(t) - KELVIN for t in w.mTemperature]
                wheels.append(WheelData(
                    position=pos,
                    # mTemperature is left/center/right in Kelvin
                    tire_inner_temp=temps[0],
                    tire_middle_temp=temps[1],
                    tire_outer_temp=temps[2],
                    tire_surface_temp=temps[1],
                    brake_temp=float(w.mBrakeTemp) or None,
                    tire_pressure=float(w.mPressure) * KPA_TO_BAR or None,
                    suspension_travel=float(w.mSuspensionDeflection),
                    wheel_speed=float(w.mRotation),
                    tire_wear=1.0 - float(w.mWear),  # mWear: 1.0 = fresh
                    # V depth (loop 4): contact-patch + geometry, all rF2-native
                    # units. Axis/sign correctness is rig-deferred (owner rule 10).
                    camber=float(w.mCamber),  # radians
                    toe=float(w.mToe),  # radians
                    wheel_load=float(w.mTireLoad) or None,  # N
                    lateral_force=float(w.mLateralForce),  # N
                    longitudinal_force=float(w.mLongitudinalForce),  # N
                    ride_height=float(w.mRideHeight),  # m
                    tire_compound=(front_compound if i < 2 else rear_compound),
                ))

            speed = math.sqrt(tel.mLocalVel.x ** 2 + tel.mLocalVel.y ** 2
                              + tel.mLocalVel.z ** 2)
            track_len = float(info.mLapDist) if info and info.mLapDist > 0 else None
            lap_fraction = None
            if track_len:
                lap_fraction = max(0.0, min(1.0, float(sco.mLapDist) / track_len))

            self._frame += 1
            return NormalizedTelemetry(
                game_name="rf2",
                session_id="",
                timestamp=datetime.now(timezone.utc),
                frame_number=self._frame,
                speed=float(speed),
                gear=int(tel.mGear),  # -1/0/1+ matches the model directly
                engine_rpm=float(tel.mEngineRPM),
                engine_max_rpm=float(tel.mEngineMaxRPM) if tel.mEngineMaxRPM > 0 else None,
                throttle=min(1.0, max(0.0, float(tel.mUnfilteredThrottle))),
                brake=min(1.0, max(0.0, float(tel.mUnfilteredBrake))),
                clutch=min(1.0, max(0.0, float(tel.mUnfilteredClutch))),
                steering=min(1.0, max(-1.0, float(tel.mUnfilteredSteering))),
                position=Vector3(x=float(tel.mPos.x), y=float(tel.mPos.y),
                                 z=float(tel.mPos.z)),
                velocity=Vector3(x=float(tel.mLocalVel.x), y=float(tel.mLocalVel.y),
                                 z=float(tel.mLocalVel.z)),
                acceleration=Vector3(x=float(tel.mLocalAccel.x),
                                     y=float(tel.mLocalAccel.y),
                                     z=float(tel.mLocalAccel.z)),
                yaw=0.0, pitch=0.0, roll=0.0,  # orientation matrix not decomposed
                yaw_rate=float(tel.mLocalRot.y),
                pitch_rate=float(tel.mLocalRot.x),
                roll_rate=float(tel.mLocalRot.z),
                # rF2 local frame: +x left, +y up, +z backward
                g_force_lateral=float(tel.mLocalAccel.x) / G,
                g_force_vertical=float(tel.mLocalAccel.y) / G,
                g_force_longitudinal=-float(tel.mLocalAccel.z) / G,
                wheels=wheels,
                fuel_remaining=float(tel.mFuel),
                fuel_capacity=float(tel.mFuelCapacity) if tel.mFuelCapacity > 0 else None,
                lap_number=max(1, int(tel.mLapNumber)),
                # platform chunk schema wants the 0..1 lap fraction here
                lap_distance=lap_fraction,
                track_length=track_len,
                lap_time_current=float(sco.mTimeIntoLap) if sco.mTimeIntoLap > 0 else None,
                lap_time_last=float(sco.mLastLapTime) if sco.mLastLapTime > 0 else None,
                lap_time_best=float(sco.mBestLapTime) if sco.mBestLapTime > 0 else None,
                in_pit=bool(sco.mInPits),
                is_racing=bool(info.mInRealtime) if info else True,
                # V depth (loop 4): vehicle-level channels rF2 exposes but
                # we never forwarded. rF2-native units; magnitudes/signs are
                # rig-deferred (owner rule 10) — these tests assert derivation,
                # not real-world correctness.
                engine_water_temp=float(tel.mEngineWaterTemp) or None,  # C
                engine_oil_temp=float(tel.mEngineOilTemp) or None,  # C
                steering_torque=float(tel.mSteeringShaftTorque),  # Nm
                # rF2 reports the REAR bias fraction; the schema wants FRONT.
                brake_bias=(1.0 - float(tel.mRearBrakeBias)
                            if 0.0 < tel.mRearBrakeBias < 1.0 else None),
                turbo_boost=(float(tel.mTurboBoostPressure) / 1000.0
                             if tel.mTurboBoostPressure else None),  # Pa->kPa
                drs_state=int(tel.mRearFlapActivated),  # 0=off, 1=active
                ers_pct=(float(tel.mBatteryChargeFraction)
                         if tel.mBatteryChargeFraction else None),  # 0..1
                ers_deploy_mode=int(tel.mElectricBoostMotorState),
                damage=_rf2_damage(tel),
            )
        except Exception:
            return None

    @property
    def game_name(self) -> str:
        return "rf2"

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
            pages = msgpack.unpackb(raw_data)
            tel, sco, info = self._player(pages)
            if info is None:
                return None
            # mSession: 0=testday 1-4=practice 5-8=qual 9=warmup 10-13=race
            s = int(info.mSession)
            session_type = ("Test" if s == 0 else
                            "Practice" if 1 <= s <= 4 else
                            "Qualifying" if 5 <= s <= 8 else
                            "Warmup" if s == 9 else "Race")
            return TelemetryMetadata(
                game_name="rf2",
                track_name=_cstr(info.mTrackName) or "Unknown Track",
                car_name=(_cstr(tel.mVehicleName) if tel else
                          _cstr(sco.mVehicleName) if sco else "Unknown Car")
                or "Unknown Car",
                session_type=session_type,
                session_start_time=datetime.now(timezone.utc),
                player_name=_cstr(info.mPlayerName) or None,
                track_length=float(info.mLapDist) or 0.0,
                track_config=None,
            )
        except Exception:
            return None
