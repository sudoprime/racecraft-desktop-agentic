"""
TTS queue for the live coach (D3, mode A — racecraft-agentic
docs/REALTIME_COACH.md). Owner decisions 2026-06-11: premium feature,
one bundled default voice at launch.

Safety rules enforced HERE, not in callers:
- never overlap utterances (a cue speaks to completion first)
- global cooldown between utterance starts (GLOBAL_COOLDOWN_S)
- mute switch and verbosity ('off' | 'key' | 'all'); debriefs count as
  'key', corner cues only at 'all'... inverted: corner cues are the
  product — 'key' = corner cues only, 'all' = cues + debriefs.

Backends are pluggable; the default picks Piper when a model/binary is
configured (RACECRAFT_PIPER_BIN / RACECRAFT_PIPER_MODEL), else a log-only
backend (also what headless tests use).
"""
import os
import shutil
import subprocess
import time
from typing import Callable, List, Optional, Tuple

from racecraft.coach.ghost import GLOBAL_COOLDOWN_S, speech_seconds


class LogBackend:
    """Records utterances instead of speaking — headless/test default."""

    def __init__(self):
        self.spoken: List[Tuple[float, str]] = []

    def speak(self, text: str) -> None:
        self.spoken.append((time.monotonic(), text))


class PiperBackend:
    """Local neural TTS via the piper binary (bundled voice).

    Blocking call by design: the queue serializes utterances anyway, and
    piper latency is ~100-300ms (REALTIME_COACH.md).
    """

    def __init__(self, binary: str, model: str):
        self.binary = binary
        self.model = model

    @classmethod
    def from_env(cls) -> Optional["PiperBackend"]:
        binary = os.getenv("RACECRAFT_PIPER_BIN", "piper")
        model = os.getenv("RACECRAFT_PIPER_MODEL", "")
        if model and shutil.which(binary):
            return cls(binary, model)
        return None

    def speak(self, text: str) -> None:
        try:
            piper = subprocess.Popen(
                [self.binary, "--model", self.model, "--output-raw"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
            aplay = subprocess.Popen(
                ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"],
                stdin=piper.stdout, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            piper.stdin.write(text.encode())
            piper.stdin.close()
            aplay.wait(timeout=30)
        except Exception:
            pass  # a missed cue is better than a crashed coach


class TTSQueue:
    """Serializes coach speech and enforces the safety rules.

    `clock` is injectable for deterministic tests (defaults to
    time.monotonic). speak() returns True when the utterance was accepted.
    """

    def __init__(self, backend=None, clock: Callable[[], float] = None):
        self.backend = backend or PiperBackend.from_env() or LogBackend()
        self.clock = clock or time.monotonic
        self.muted = False
        self.verbosity = "key"   # 'off' | 'key' (corner cues) | 'all' (+debriefs)
        self._speaking_until = -1e9
        self._last_start = -1e9

    def can_speak(self, kind: str = "corner") -> bool:
        if self.muted or self.verbosity == "off":
            return False
        if kind == "debrief" and self.verbosity != "all":
            return False
        now = self.clock()
        if now < self._speaking_until:
            return False
        if now - self._last_start < GLOBAL_COOLDOWN_S:
            return False
        return True

    def speak(self, text: str, kind: str = "corner") -> bool:
        if not text or not self.can_speak(kind):
            return False
        now = self.clock()
        self._last_start = now
        self._speaking_until = now + speech_seconds(text)
        self.backend.speak(text)
        return True
