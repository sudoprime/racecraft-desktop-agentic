"""
Cross-repo contract (loop 2 iteration 37): every detectable game must map
to a value the platform's Game enum accepts — otherwise its streaming
sessions are silently tagged 'unknown' (the bug this test was written to
catch: only iRacing was mapped while five sims had capture implemented).

PLATFORM_GAME_ENUM mirrors backend/app/models/streaming.py::Game in the
racecraft-agentic repo; update BOTH when a sim is added.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from racecraft.game_mapping import GAME_ENUM
from racecraft.detection import GameDetector

PLATFORM_GAME_ENUM = {
    "iracing", "acc", "assetto_corsa", "rf2", "ams2", "f1", "unknown",
}


def test_every_detectable_game_maps_to_a_platform_enum_value():
    for exe, cfg in GameDetector.GAME_CONFIGS.items():
        name = cfg["name"]
        assert name in GAME_ENUM, (
            f"{name} ({exe}) is detectable but unmapped - its sessions "
            f"would stream as game='unknown'")
        assert GAME_ENUM[name] in PLATFORM_GAME_ENUM, (
            f"{name} maps to {GAME_ENUM[name]!r}, not a platform enum value")


def test_mapped_values_are_real_enum_values():
    for name, value in GAME_ENUM.items():
        assert value in PLATFORM_GAME_ENUM, (name, value)


def test_parser_game_names_match_platform_enum():
    """The NormalizedTelemetry.game_name each parser stamps must also be a
    platform value (lowercased), so chunk metadata agrees with the session."""
    from racecraft.parsers.acc import ACCParser
    from racecraft.parsers.ac import ACParser
    from racecraft.parsers.ams2 import AMS2Parser
    from racecraft.parsers.rf2 import RF2Parser
    from racecraft.parsers.f1 import F1Parser
    for parser in (ACCParser(), ACParser(), AMS2Parser(), RF2Parser(), F1Parser()):
        assert parser.game_name.lower() in PLATFORM_GAME_ENUM, parser.game_name
