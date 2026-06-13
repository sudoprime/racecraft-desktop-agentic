"""Remote log + crash reporting for the desktop app (platform loop 4, M).

Ships WARNING+ log records and uncaught-exception crash reports to the
BACKEND (POST /api/desktop/logs, /api/desktop/crash) — never to Loki
directly (no infra creds in a distributed binary; the backend relays).

Hard requirements:
- **Never block the telemetry loop.** `emit()` only enqueues onto a
  BOUNDED queue (drops oldest when full — a logging path must never
  grow memory or stall). A daemon worker thread does all HTTP.
- **Never raise into the app.** Every network/serialization error is
  swallowed; remote logging failing is invisible to the user.
- **Crashes are delivered synchronously** (short timeout) because the
  process may be about to exit — they're rare and high-value.
- **Auth-optional.** A token-getter supplies the current desktop bearer
  when available; pre-login and crash-at-startup reports go anonymously
  (the backend labels them so we still see them — the whole point).
"""
import atexit
import logging
import os
import platform
import queue
import sys
import threading
import time
import traceback as _tb
from typing import Callable, List, Optional

import httpx

from racecraft import __version__

logger = logging.getLogger(__name__)

_OS = platform.platform()
_token_getter: Callable[[], Optional[str]] = lambda: None


def set_token_getter(fn: Callable[[], Optional[str]]) -> None:
    """Wire the current-bearer accessor once auth exists (so logs/crashes
    after login carry the user; before login they go anonymous)."""
    global _token_getter
    _token_getter = fn


def _headers() -> dict:
    tok = None
    try:
        tok = _token_getter()
    except Exception:
        tok = None
    return {"Authorization": f"Bearer {tok}"} if tok else {}


class RemoteLogHandler(logging.Handler):
    """Batches records and POSTs them from a daemon worker thread."""

    def __init__(self, api_base_url: str, level=logging.WARNING,
                 batch_size: int = 50, flush_interval: float = 5.0,
                 max_queue: int = 1000):
        super().__init__(level=level)
        self.url = api_base_url.rstrip("/") + "/api/desktop/logs"
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._q: "queue.Queue[dict]" = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._client = httpx.Client(timeout=5.0)
        self._worker = threading.Thread(target=self._run, name="remote-log",
                                        daemon=True)
        self._worker.start()
        atexit.register(self.close)

    def emit(self, record: logging.LogRecord) -> None:
        # Cheap and non-blocking: format + enqueue, drop-oldest if full.
        try:
            entry = {
                "level": record.levelname.lower(),
                "message": self.format(record),
                "logger": record.name,
                "timestamp": record.created,
            }
            try:
                self._q.put_nowait(entry)
            except queue.Full:
                try:
                    self._q.get_nowait()      # drop oldest
                    self._q.put_nowait(entry)
                except queue.Empty:
                    pass
        except Exception:
            pass  # logging must never raise

    def _drain_batch(self) -> List[dict]:
        batch: List[dict] = []
        deadline = time.monotonic() + self.flush_interval
        while len(batch) < self.batch_size:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                batch.append(self._q.get(timeout=timeout))
            except queue.Empty:
                break
        return batch

    def _post(self, entries: List[dict]) -> None:
        if not entries:
            return
        try:
            self._client.post(self.url, headers=_headers(), json={
                "app_version": __version__, "os": _OS, "entries": entries,
            })
        except Exception:
            pass  # best-effort; the local file/console handlers still have it

    def _run(self) -> None:
        while not self._stop.is_set():
            self._post(self._drain_batch())
        # final drain on shutdown
        rest: List[dict] = []
        try:
            while True:
                rest.append(self._q.get_nowait())
        except queue.Empty:
            pass
        self._post(rest)

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._worker.join(timeout=3.0)
            self._client.close()
        except Exception:
            pass
        super().close()


def report_crash(exc_type, exc_value, exc_tb, api_base_url: str,
                 context: Optional[dict] = None) -> None:
    """POST one crash report synchronously (best-effort, short timeout)."""
    try:
        tb_text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        payload = {
            "app_version": __version__,
            "os": _OS,
            "exc_type": getattr(exc_type, "__name__", str(exc_type)),
            "message": str(exc_value)[:4000],
            "traceback": tb_text[:20000],
            "timestamp": time.time(),
            "context": context or {},
        }
        with httpx.Client(timeout=4.0) as client:
            client.post(api_base_url.rstrip("/") + "/api/desktop/crash",
                        headers=_headers(), json=payload)
    except Exception:
        pass  # a crash reporter that crashes helps no one


def install_remote_logging(api_base_url: str, *, enabled: Optional[bool] = None,
                           level=logging.WARNING) -> Optional[RemoteLogHandler]:
    """Install crash hooks (sys/threading/asyncio) and, when enabled,
    attach the RemoteLogHandler to the root logger. Crash hooks are ALWAYS
    installed — a crash we never see is the problem we're solving.

    Returns the handler (or None if the log stream is disabled). Gate the
    higher-volume log stream with RACECRAFT_REMOTE_LOG (default on).
    """
    if enabled is None:
        enabled = os.getenv("RACECRAFT_REMOTE_LOG", "1") == "1"

    # --- crash hooks (always) ---
    prev_excepthook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        report_crash(exc_type, exc_value, exc_tb, api_base_url)
        prev_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

    if hasattr(threading, "excepthook"):
        def _thread_hook(args):
            report_crash(args.exc_type, args.exc_value, args.exc_traceback,
                         api_base_url, context={"thread": args.thread.name
                                                if args.thread else "?"})
        threading.excepthook = _thread_hook

    handler = None
    if enabled:
        handler = RemoteLogHandler(api_base_url, level=level)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logger.info("Remote logging enabled (WARNING+ -> backend)")
    return handler


def install_asyncio_crash_hook(loop, api_base_url: str) -> None:
    """Route unhandled asyncio exceptions to the crash reporter too. Call
    once the event loop exists (the Qt/qasync loop or asyncio.run loop)."""
    def _handler(_loop, ctx):
        exc = ctx.get("exception")
        if exc is not None:
            report_crash(type(exc), exc, exc.__traceback__, api_base_url,
                         context={"asyncio": ctx.get("message", "")})
        else:
            logger.error(f"asyncio error: {ctx.get('message')}")
    try:
        loop.set_exception_handler(_handler)
    except Exception:
        pass
