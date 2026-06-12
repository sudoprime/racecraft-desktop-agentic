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
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

import httpx

from racecraft.models import NormalizedTelemetry

logger = logging.getLogger(__name__)


class StreamingClient:
    """Manages one streaming session against the RaceCraft backend."""

    def __init__(self, api_base_url: str, auth, samples_per_chunk: int = 600,
                 spool_dir: Optional[str] = None, upload_attempts: int = 2):
        self.api_base_url = api_base_url.rstrip("/")
        self.auth = auth  # AuthenticationService — provides bearer_token
        self.samples_per_chunk = samples_per_chunk
        self.client = httpx.AsyncClient(timeout=30.0)
        # Failed chunk uploads land here instead of vanishing (platform
        # loop 3, T3): retried on later flushes and at session end.
        self.spool_dir = Path(spool_dir or os.path.join(
            os.path.expanduser("~"), ".racecraft", "spool"))
        self.upload_attempts = max(1, upload_attempts)

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
        resp = await self._authed_post(
            f"{self.api_base_url}/api/streaming/session/start",
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
        async with self._upload_lock:
            remaining = await self._drain_spool()  # full drain at session end
            if remaining:
                logger.info(f"StreamingClient: drained {remaining} spooled chunk(s)")
            spool = self.spool_dir / str(self.session_id)
            leftover = list(spool.glob("chunk_*.json.gz")) if spool.is_dir() else []
            if leftover:
                logger.warning(
                    f"StreamingClient: {len(leftover)} chunk(s) remain spooled at "
                    f"{spool} — the platform's gap-tolerant parser will analyze "
                    f"around them; the files are kept on disk")
        resp = await self._authed_post(
            f"{self.api_base_url}/api/streaming/session/end",
            json={"session_id": self.session_id},
        )
        resp.raise_for_status()

    async def submit_for_analysis(self, notes: str = "") -> Optional[str]:
        """Submit the ended session for AI analysis. Returns analysis_id."""
        if not self.analysis_id:
            return None
        resp = await self._authed_post(
            f"{self.api_base_url}/api/streaming/session/analyze",
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

    async def _authed_post(self, url: str, **kw) -> httpx.Response:
        """POST with the bearer token; on a 401, refresh once and retry
        (platform loop 3, T3 — access tokens are 7 days and refresh
        tokens rotate, so a long-lived desktop session WILL cross an
        expiry eventually; before this the first 401 ended uploads for
        the rest of the session)."""
        resp = await self.client.post(url, headers=self._headers(), **kw)
        if resp.status_code == 401 and hasattr(self.auth, "refresh"):
            logger.info("StreamingClient: 401 — refreshing token and retrying")
            if await self.auth.refresh():
                resp = await self.client.post(url, headers=self._headers(), **kw)
        return resp

    def _spool_path(self, chunk_number: int) -> Path:
        return (self.spool_dir / str(self.session_id)
                / f"chunk_{chunk_number:06d}.json.gz")

    async def _upload_chunk_payload(self, chunk_number: int, payload: bytes) -> None:
        """One chunk upload with bounded retries; raises on final failure."""
        checksum = hashlib.md5(payload).hexdigest()
        last_exc = None
        for attempt in range(self.upload_attempts):
            try:
                resp = await self._authed_post(
                    f"{self.api_base_url}/api/streaming/chunk/upload",
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
                return
            except Exception as e:
                last_exc = e
                if attempt + 1 < self.upload_attempts:
                    await asyncio.sleep(0.5 * (2 ** attempt))
        raise last_exc

    async def _flush(self) -> None:
        async with self._upload_lock:
            if self._buffer:
                chunk, self._buffer = self._buffer, []
                chunk_number = self._chunk_number
                self._chunk_number += 1

                payload = gzip.compress(json.dumps(chunk).encode())
                try:
                    await self._upload_chunk_payload(chunk_number, payload)
                except Exception as e:
                    # The buffer used to be popped-then-uploaded: one failed
                    # POST silently lost ~10s of telemetry forever (platform
                    # loop 3, T3). Spool to disk instead; retried on later
                    # flushes and at session end, and it survives a crash.
                    path = self._spool_path(chunk_number)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
                    logger.warning(
                        f"StreamingClient: chunk {chunk_number} upload failed "
                        f"({e}); spooled to {path}")

            await self._drain_spool(max_files=2)

    async def _drain_spool(self, max_files: Optional[int] = None) -> int:
        """Re-attempt spooled chunks (oldest first). max_files bounds how
        many we try per call so the live collection loop is never stalled
        behind a long backlog; session end drains fully. Returns the
        number successfully uploaded."""
        if not self.session_id:
            return 0
        spool = self.spool_dir / str(self.session_id)
        if not spool.is_dir():
            return 0
        uploaded = 0
        files = sorted(spool.glob("chunk_*.json.gz"))
        if max_files is not None:
            files = files[:max_files]
        for path in files:
            chunk_number = int(path.stem.split("_")[1].split(".")[0])
            try:
                await self._upload_chunk_payload(chunk_number, path.read_bytes())
            except Exception as e:
                logger.warning(f"StreamingClient: spooled chunk {chunk_number} "
                               f"still failing ({e}); will retry later")
                break  # keep ordering; try again next drain
            path.unlink()
            uploaded += 1
        return uploaded
