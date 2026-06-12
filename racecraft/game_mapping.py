"""
Maps detection display names -> the platform's Game enum values
(backend/app/models/streaming.py in racecraft-agentic — keep in sync;
tests/test_game_enum_conformance.py enforces it). Lives outside
collector.py so headless tests don't need PyQt.
"""

GAME_ENUM = {
    "iRacing": "iracing",
    "Simulated": "iracing",
    "ACC": "acc",
    "Assetto Corsa": "assetto_corsa",
    "F1 24": "f1",
    "F1 25": "f1",
    "rFactor 2": "rf2",
    "Automobilista 2": "ams2",
}
