"""Headless test-mode runner: simulated telemetry → real upload path.

Drives the full client pipeline without Qt: authenticate (password →
PKCE desktop JWT), generate a simulated session, stream chunks through
the real /api/streaming contract, end the session, submit for analysis,
and optionally wait for the coaching report.

This is what runs in automated E2E environments (the KubeVirt Windows
VM, CI) and it works on Linux too — PyQt is never imported.

Usage:
    python -m racecraft.headless --api-url http://host:30080 \
        --email dev@racecraft.local --password DevPassword123! \
        --laps 4 --time-scale 10 --wait
"""

import argparse
import asyncio
import os
import sys

from racecraft.auth import AuthenticationService
from racecraft.parsers.iracing import IRacingParser
from racecraft.readers.simulated import SimulatedReader
from racecraft.streaming import StreamingClient


async def run_test_session(api_url: str, email: str, password: str,
                           laps: int = 4, hz: int = 60, time_scale: float = 1.0,
                           wait: bool = False, notes: str = "simulated test session") -> int:
    auth = AuthenticationService(api_url)
    print(f"Authenticating against {api_url} as {email} ...")
    creds = await auth.login_with_password(email, password)
    if not creds:
        print("FAIL: authentication")
        return 1

    reader = SimulatedReader(update_rate=hz, laps=laps, time_scale=time_scale)
    parser = IRacingParser()
    streaming = StreamingClient(api_url, auth)

    await reader.connect()
    session_id = await streaming.start_session(
        game="iracing",
        track_name=reader.track_name,
        car_name=reader.car_name,
        session_type="practice",
        metadata={"source": "simulated", "laps": laps, "hz": hz},
    )
    print(f"Session started: {session_id} (analysis {streaming.analysis_id})")
    print(f"Generating {laps} laps at {hz}Hz (time scale {time_scale}x) ...")

    frames = 0
    async for raw in reader.read_telemetry():
        telemetry = parser.parse(raw)
        if telemetry and parser.validate_data(telemetry):
            await streaming.add_frame(telemetry, track_length=reader.track_length)
            frames += 1
            if frames % (hz * 30) == 0:
                print(f"  {frames} frames, lap {telemetry.lap_number}, "
                      f"{streaming.chunks_uploaded} chunks uploaded")

    await reader.disconnect()
    await streaming.end_session()
    print(f"Session ended: {frames} frames in {streaming.chunks_uploaded} chunks")

    analysis_id = await streaming.submit_for_analysis(notes)
    print(f"Submitted for analysis: {analysis_id}")

    if wait:
        print("Waiting for analysis to complete (LLM coaching step) ...")
        status = await streaming.wait_for_completion()
        print(f"Final status: {status}")
        if status.get("status") not in ("complete", "completed"):
            print("FAIL: analysis did not complete")
            return 1
        print("E2E TEST SESSION PASSED")

    return 0


def main() -> None:
    # Line-buffer stdout so progress is visible when redirected to a file
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="RaceCraft headless test session")
    ap.add_argument("--api-url", default=os.environ.get("RACECRAFT_API_URL",
                                                        "http://localhost:30080"))
    ap.add_argument("--email", default=os.environ.get("RACECRAFT_EMAIL",
                                                      "dev@racecraft.local"))
    ap.add_argument("--password", default=os.environ.get("RACECRAFT_PASSWORD",
                                                         "DevPassword123!"))
    ap.add_argument("--laps", type=int, default=int(os.environ.get("RACECRAFT_TEST_LAPS", "4")))
    ap.add_argument("--hz", type=int, default=60)
    ap.add_argument("--time-scale", type=float,
                    default=float(os.environ.get("RACECRAFT_TEST_TIMESCALE", "1.0")))
    ap.add_argument("--wait", action="store_true",
                    help="block until the analysis reaches a terminal state")
    ap.add_argument("--notes", default="simulated test session")
    args = ap.parse_args()

    rc = asyncio.run(run_test_session(
        args.api_url, args.email, args.password,
        laps=args.laps, hz=args.hz, time_scale=args.time_scale,
        wait=args.wait, notes=args.notes,
    ))
    sys.exit(rc)


if __name__ == "__main__":
    main()
