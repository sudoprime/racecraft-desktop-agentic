"""cx_Freeze setup script for RaceCraft Desktop"""

import sys
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but some modules need help
build_exe_options = {
    "packages": [
        "asyncio",
        "PyQt6",
        "qasync",
        "pydantic",
        "httpx",
        "keyring",
    ],
    "include_files": [
        ("assets", "assets"),
        ("config", "config"),
    ],
    "excludes": [
        "tkinter",  # Exclude unused modules to reduce size
        "unittest",
        "email",
        "http.server",
    ],
}

# Base for Windows GUI applications (no console)
base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(
    name="RaceCraft",
    version="0.1.0",
    description="Racing simulator telemetry collection daemon",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "racecraft/app.py",
            base=base,
            target_name="RaceCraft.exe",
            icon="assets/icon.ico",
            shortcut_name="RaceCraft Desktop",
            shortcut_dir="DesktopFolder",
        )
    ],
)
