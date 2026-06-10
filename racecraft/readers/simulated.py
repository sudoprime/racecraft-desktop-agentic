"""Simulated telemetry reader — generates synthetic laps without a sim.

Used by --test mode. Emits iRacing-style raw dicts (msgpack) so the
existing IRacingParser normalizes them through the exact same code path
real telemetry takes. The driving model is the same 8-corner synthetic
profile as the platform's mock generators (deploy/helm/racecraft/files/),
but integrated through a simple accel/brake speed controller so braking
points, corner minimums and exits look like real driving to the
analysis pipeline.
"""

import asyncio
import math
import os
from datetime import datetime, timezone
from typing import AsyncIterator

import msgpack

from racecraft.interfaces import ITelemetryReader

TRACK_LENGTH_M = 4500.0
TRACK_NAME = "Simulation Ring"
CAR_NAME = "Simulated MX-5"
NUM_CORNERS = 8

MAX_ACCEL = 7.5    # m/s^2 — full-throttle acceleration
MAX_BRAKE = 18.0   # m/s^2 — threshold braking


class SimulatedReader(ITelemetryReader):
    """Generate synthetic telemetry for a fixed number of laps.

    The async iterator ends after ``laps`` complete laps, which the
    collector treats like the sim exiting — triggering session end.

    time_scale > 1 emits frames faster than real time while keeping the
    *virtual* clock (SessionTime / timestamps) honest, so a 6-minute
    session can be generated in seconds for tests.
    """

    def __init__(self, update_rate: int = 60, laps: int = None, time_scale: float = None):
        # Env fallbacks let GUI test mode (which only passes update_rate)
        # still be configured
        if laps is None:
            laps = int(os.environ.get("RACECRAFT_TEST_LAPS", "4"))
        if time_scale is None:
            time_scale = float(os.environ.get("RACECRAFT_TEST_TIMESCALE", "1.0"))
        self._update_rate = update_rate
        self._laps = laps
        self._time_scale = max(0.1, time_scale)
        self._connected = False
        self._stop_event = asyncio.Event()

        # Simulation state
        self._session_start = datetime.now(timezone.utc)
        self._session_time = 0.0     # virtual seconds since session start
        self._tick = 0
        self._lap = 1
        self._lap_dist = 0.0         # meters into current lap
        self._speed = 30.0           # m/s, rolling start
        self._lap_time = 0.0
        self._last_lap_time = 0.0
        self._best_lap_time = 0.0
        self._fuel = 45.0            # liters

    # -- ITelemetryReader --------------------------------------------------

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._stop_event.set()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    @property
    def update_rate(self) -> int:
        return self._update_rate

    @property
    def track_name(self) -> str:
        return TRACK_NAME

    @property
    def car_name(self) -> str:
        return CAR_NAME

    @property
    def track_length(self) -> float:
        return TRACK_LENGTH_M

    async def read_telemetry(self) -> AsyncIterator[bytes]:
        dt = 1.0 / self._update_rate
        sleep_for = dt / self._time_scale

        while not self._stop_event.is_set():
            frame = self._step(dt)
            if frame is None:  # all laps complete
                break
            yield msgpack.packb(frame)
            await asyncio.sleep(sleep_for)

    # -- driving model -----------------------------------------------------

    def _target_speed(self, pct: float, lap: int) -> float:
        """Corner-modulated target speed; laps vary slightly in pace."""
        corner = math.sin(2 * math.pi * NUM_CORNERS * pct)
        # Per-lap variation: ±2% pace, deterministic
        pace = 1.0 + 0.02 * math.sin(lap * 2.4)
        return (52.0 - 18.0 * max(0.0, corner) ** 2) * pace

    def _step(self, dt: float):
        pct = self._lap_dist / TRACK_LENGTH_M
        target = self._target_speed(pct, self._lap)

        # Speed controller: accelerate/brake toward target → realistic
        # braking points and corner-exit ramps rather than profile steps.
        # Look ahead ~2.5s so braking starts before the corner.
        ahead_pct = (self._lap_dist + self._speed * 2.5) / TRACK_LENGTH_M % 1.0
        target = min(target, self._target_speed(ahead_pct, self._lap))

        dv = target - self._speed
        if dv >= 0:
            accel = min(dv / dt, MAX_ACCEL)
        else:
            accel = max(dv / dt, -MAX_BRAKE)
        self._speed = max(5.0, self._speed + accel * dt)

        # Inputs from the controller state
        throttle = max(0.0, min(1.0, accel / MAX_ACCEL)) if accel >= 0 else 0.0
        brake = max(0.0, min(1.0, -accel / MAX_BRAKE)) if accel < 0 else 0.0
        corner = math.sin(2 * math.pi * NUM_CORNERS * pct + 0.5)
        steer = 0.35 * corner

        # Geometry: circular track, angle = lap fraction
        angle = 2 * math.pi * pct
        radius = TRACK_LENGTH_M / (2 * math.pi)
        heading = angle + math.pi / 2

        gear = max(1, 3 + int(self._speed / 15) % 4)
        rpm = 2200.0 + (self._speed / 55.0) * 4800.0 + brake * 300.0

        g_lat = steer * self._speed * 0.04
        g_long = accel / 9.81

        # Tire temps rise with lateral load, per-side
        t_base = 78.0 + 6.0 * abs(g_lat)
        left_bias = 4.0 if g_lat > 0 else -4.0

        frame = {
            "SessionTick": self._tick,
            "SessionTime": self._session_time,
            "SessionUniqueID": 1,
            "Speed": self._speed,
            "Gear": gear,
            "RPM": rpm,
            "Throttle": throttle,
            "Brake": brake,
            "Clutch": 0.0,
            "SteeringWheelAngle": steer,
            "SteeringWheelAngleMax": 1.0,
            "CarIdxX": radius * math.sin(angle),
            "CarIdxY": radius * math.cos(angle),
            "CarIdxZ": 30.0,
            "VelocityX": self._speed * math.cos(heading),
            "VelocityY": self._speed * math.sin(heading),
            "VelocityZ": 0.0,
            "LatAccel": g_lat,
            "LongAccel": g_long,
            "VertAccel": 1.0,
            "Yaw": heading,
            "YawRate": (self._speed / radius) if radius else 0.0,
            "Pitch": 0.0,
            "Roll": -0.02 * g_lat,
            "PitchRate": 0.0,
            "RollRate": 0.0,
            "Lap": self._lap,
            "LapDist": self._lap_dist,
            "LapDistPct": pct,
            "LapCurrentLapTime": self._lap_time,
            "LapLastLapTime": self._last_lap_time,
            "LapBestLapTime": self._best_lap_time,
            "FuelLevel": self._fuel,
            "OnPitRoad": False,
            "IsOnTrack": True,
            # Tire temps/pressures (L/M/R per wheel, iRacing naming)
            **{
                f"{w}temp{p}": t_base + (left_bias if w[0] == "L" else -left_bias)
                for w in ("LF", "RF", "LR", "RR")
                for p in ("CL", "CM", "CR")
            },
            **{f"{w}pressure": 1.82 for w in ("LF", "RF", "LR", "RR")},
        }

        # Advance state
        self._tick += 1
        self._session_time += dt
        self._lap_time += dt
        self._fuel = max(0.0, self._fuel - 0.0006)
        self._lap_dist += self._speed * dt

        if self._lap_dist >= TRACK_LENGTH_M:
            self._lap_dist -= TRACK_LENGTH_M
            self._last_lap_time = self._lap_time
            if self._best_lap_time == 0.0 or self._lap_time < self._best_lap_time:
                self._best_lap_time = self._lap_time
            self._lap_time = 0.0
            self._lap += 1
            if self._lap > self._laps:
                return None

        return frame
