"""Logging setup for the desktop app (platform loop 3, T3 part 2).

print() in a windowed (pythonw/PyInstaller --noconsole) build goes
nowhere — worse, writing to a missing stdout can raise. All runtime
diagnostics go through logging: console when attached, plus a file
under ~/.racecraft/logs/ when RACECRAFT_LOG_FILE=1 (default ON for
frozen/windowed builds where there is no console to see).
"""
import logging
import os
import sys
from pathlib import Path


def setup_logging(level=logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (tests, embedders)
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    frozen_windowed = getattr(sys, "frozen", False) or sys.stdout is None
    if os.getenv("RACECRAFT_LOG_FILE", "1" if frozen_windowed else "0") == "1":
        log_dir = Path.home() / ".racecraft" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            from logging.handlers import RotatingFileHandler
            fh = RotatingFileHandler(log_dir / "desktop.log",
                                     maxBytes=2_000_000, backupCount=3)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            pass  # no home dir / read-only: console-only
