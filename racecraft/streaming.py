"""Streaming upload client — the desktop side of the platform's
/api/streaming contract (session/start → chunk/upload → session/end →
session/analyze).

Chunk format matches the pipeline consumer
(pipeline/app/services/telemetry_parser.py): gzipped JSON array of
sample dicts, uploaded as multipart with an MD5 checksum.
"""

import asyncio
import gzip
import hashlib
import json
from datetime import timedelta
from typing import Optional

import httpx

from racecraft.models import NormalizedTelemetry


class StreamingClient:
    """Manages one streaming session against the RaceCraft backend."""

    def __init__(self, api_base_url: str, auth, samples_per_chunk: int = 600):
        self.api_base_url = api_base_url.rstrip("/")
        self.auth = auth  # AuthenticationService — provides bearer_token
        self.samples_per_chunk = samples_per_chunk
        self.client = httpx.AsyncClient(timeout=30.0)

        self.session_id: Optional[str] = None
        self.analysis_id: Optional[str] = None
        self._buffer: list[dict] = []
        self._chunk_number = 0
        self._chunks_uploaded = 0
        self._session_start = None  # datetime of first frame (virtual clock base)
        self._upload_lock = asyncio.Lock()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.auth.bearer_token}"}

    # -- session lifecycle ---------------------------------------------------

    async def start_session(self, game: str, track_name: str, car_name: str,
                            session_type: str = "practice",
                            metadata: Optional[dict] = None) -> str:
        resp = await self.client.post(
            f"{self.api_base_url}/api/streaming/session/start",
            headers=self._headers(),
            json={
                "game": game,
                "track_name": track_name,
                "car_name": car_name,
                "session_type": session_type,
                "metadata": metadata or {},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self.session_id = data["session_id"]
        self.analysis_id = data.get("analysis_id")
        if not self.analysis_id:
            # Older backends omit analysis_id from session/start; discover it
            # the way the webapp dashboard does (newest streaming analysis)
            self.analysis_id = await self._discover_analysis_id()
        self._buffer = []
        self._chunk_number = 0
        self._chunks_uploaded = 0
        self._session_start = None
        return self.session_id

    async def add_frame(self, t: NormalizedTelemetry,
                        track_length: Optional[float] = None) -> None:
        """Buffer one normalized frame; flush a chunk when full."""
        if not self.session_id:
            return
        if self._session_start is None:
            self._session_start = t.timestamp

        self._buffer.append(self._to_sample(t, track_length))
        if len(self._buffer) >= self.samples_per_chunk:
            await self._flush()

    async def end_session(self) -> None:
        if not self.session_id:
            return
        await self._flush()  # remaining partial chunk
        resp = await self.client.post(
            f"{self.api_base_url}/api/streaming/session/end",
            headers=self._headers(),
            json={"session_id": self.session_id},
        )
        resp.raise_for_status()

    async def submit_for_analysis(self, notes: str = "") -> Optional[str]:
        """Submit the ended session for AI analysis. Returns analysis_id."""
        if not self.analysis_id:
            return None
        resp = await self.client.post(
            f"{self.api_base_url}/api/streaming/session/analyze",
            headers=self._headers(),
            json={"analysis_id": self.analysis_id, "notes": notes},
        )
        resp.raise_for_status()
        return self.analysis_id

    async def wait_for_completion(self, timeout_s: int = 3600,
                                  poll_s: int = 10) -> dict:
        """Poll analysis status until it reaches a terminal state."""
        elapsed = 0
        status: dict = {}
        while elapsed < timeout_s:
            try:
                resp = await self.client.get(
                    f"{self.api_base_url}/api/analysis/{self.analysis_id}/status",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    status = resp.json()
                    # status endpoint reports "complete"; DB enum is "completed"
                    if status.get("status") in ("complete", "completed", "failed"):
                        return status
            except httpx.HTTPError:
                pass  # transient poll failure must not abort the wait
            await asyncio.sleep(poll_s)
            elapsed += poll_s
        return status

    @property
    def chunks_uploaded(self) -> int:
        return self._chunks_uploaded

    async def _discover_analysis_id(self) -> Optional[str]:
        try:
            resp = await self.client.get(
                f"{self.api_base_url}/api/user/analyses", headers=self._headers())
            resp.raise_for_status()
            for a in resp.json().get("analyses", []):
                if a.get("file_name") == "streaming_session":
                    return a["id"]
        except httpx.HTTPError as e:
            print(f"StreamingClient: analysis_id discovery failed: {e}")
        return None

    # -- internals -------------------------------------------------------

    def _to_sample(self, t: NormalizedTelemetry, track_length: Optional[float]) -> dict:
        # lap_distance must be normalized 0-1 for the pipeline
        raw = t.raw_data or {}
        if "LapDistPct" in raw:
            lap_pct = float(raw["LapDistPct"])
        elif track_length and t.lap_distance is not None:
            lap_pct = (t.lap_distance / track_length) % 1.0
        elif t.lap_distance is not None and t.lap_distance <= 1.0:
            lap_pct = t.lap_distance
        else:
            lap_pct = 0.0

        # Prefer the source's virtual clock (honest under time_scale)
        if "SessionTime" in raw and self._session_start is not None:
            ts = self._session_start + timedelta(seconds=float(raw["SessionTime"]))
        else:
            ts = t.timestamp
        ts_str = ts.isoformat()
        if not ts_str.endswith("Z") and "+" not in ts_str:
            ts_str += "Z"

        return {
            "timestamp": ts_str,
            "lap_number": t.lap_number or 0,
            "lap_distance": lap_pct,
            "speed": t.speed,
            "throttle": t.throttle,
            "brake": t.brake,
            "steering": t.steering,
            "gear": t.gear,
            "g_force_lateral": t.g_force_lateral,
            "g_force_longitudinal": t.g_force_longitudinal,
            "position": {"x": t.position.x, "y": t.position.y, "z": t.position.z},
        }

    async def _flush(self) -> None:
        async with self._upload_lock:
            if not self._buffer:
                return
            chunk, self._buffer = self._buffer, []
            chunk_number = self._chunk_number
            self._chunk_number += 1

            payload = gzip.compress(json.dumps(chunk).encode())
            checksum = hashlib.md5(payload).hexdigest()

            resp = await self.client.post(
                f"{self.api_base_url}/api/streaming/chunk/upload",
                headers=self._headers(),
                data={
                    "session_id": self.session_id,
                    "chunk_number": str(chunk_number),
                    "checksum": checksum,
                },
                files={"file": (f"chunk_{chunk_number:06d}.json.gz", payload,
                                "application/gzip")},
            )
            resp.raise_for_status()
            self._chunks_uploaded += 1
