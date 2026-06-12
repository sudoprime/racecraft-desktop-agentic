"""
Cloud per-lap debrief for the live coach (D4, mode B — premium per the
owner's packaging decision). The desktop computes the same template
summary mode A speaks; mode B mails it to the platform for a 1-2 sentence
radio call from the production-class model and speaks THAT instead.
Fallback contract: ANY failure (non-200, timeout, network) speaks the
local template — the coach never goes silent because the cloud blinked.
"""
import asyncio
from typing import Callable, Optional

DEBRIEF_TIMEOUT_S = 6.0   # spoken on the straight; stale debriefs are noise


async def fetch_debrief(client, api_base_url: str, bearer_token: str,
                        summary: dict) -> Optional[str]:
    """POST the lap summary; text on success, None on ANY failure."""
    try:
        resp = await asyncio.wait_for(
            client.post(
                f"{api_base_url}/api/streaming/coach/debrief",
                json={"summary": summary},
                headers={"Authorization": f"Bearer {bearer_token}"},
            ),
            timeout=DEBRIEF_TIMEOUT_S,
        )
        if resp.status_code != 200:
            return None
        text = (resp.json() or {}).get("text") or ""
        return text.strip() or None
    except Exception:
        return None


def make_cloud_debrief_hook(tts, client, api_base_url: str,
                            bearer_token_fn: Callable[[], str]):
    """Build a LiveCoach debrief_hook that tries the cloud, then falls back.

    The hook schedules an async task (the collector loop is async) and
    returns immediately — the lap-complete frame must not block on a
    network call. `bearer_token_fn` is called at request time so token
    refreshes are picked up.
    """

    def hook(summary: dict, fallback_text: str) -> None:
        async def run():
            text = await fetch_debrief(client, api_base_url,
                                       bearer_token_fn(), summary)
            tts.speak(text or fallback_text, kind="debrief")
        try:
            asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            # no running loop (sync/test context): speak the fallback now
            tts.speak(fallback_text, kind="debrief")

    return hook
