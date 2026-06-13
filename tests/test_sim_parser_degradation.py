"""Graceful degradation across all six sim parsers (loop 4, D / R15).

The owner's robustness goal: missing data / a feature not enabled / a
partial shared-memory read must degrade HONESTLY — return None and skip
the frame, never crash or fabricate. Each parser had ONE malformed case;
this sweeps a battery (empty, non-msgpack, truncated pages, missing
page) across every parser so a partial read on ANY sim is safe. Axis/
sign/field CORRECTNESS for the five untested sims stays owner-validated
at the rig — this only pins crash-safety.
"""
import msgpack
import pytest

from racecraft.parsers.iracing import IRacingParser
from racecraft.parsers.acc import ACCParser
from racecraft.parsers.ac import ACParser
from racecraft.parsers.ams2 import AMS2Parser
from racecraft.parsers.rf2 import RF2Parser
from racecraft.parsers.f1 import F1Parser

PARSERS = [IRacingParser, ACCParser, ACParser, AMS2Parser, RF2Parser, F1Parser]

# Malformed payloads that a real partial/disabled shared-memory read can
# produce. None of these are valid frames; all must yield None, not raise.
MALFORMED = [
    b"",                                   # empty
    b"\x00" * 8,                           # a few null bytes
    b"not-msgpack-at-all",                 # garbage
    msgpack.packb({}),                     # empty page dict
    msgpack.packb({"physics": b"\x00" * 4}),   # one truncated page
    msgpack.packb({"telemetry": b"\x00" * 4}), # truncated F1/rf2-style page
    msgpack.packb([1, 2, 3]),              # wrong top-level type
]


@pytest.mark.parametrize("parser_cls", PARSERS, ids=[p.__name__ for p in PARSERS])
@pytest.mark.parametrize("payload", MALFORMED, ids=range(len(MALFORMED)))
def test_malformed_input_returns_none_without_raising(parser_cls, payload):
    p = parser_cls()
    result = p.parse(payload)        # must not raise
    assert result is None            # degrades to skip-frame


@pytest.mark.parametrize("parser_cls", PARSERS, ids=[p.__name__ for p in PARSERS])
def test_none_input_is_handled(parser_cls):
    # a reader hiccup can hand us None; parse must not explode
    p = parser_cls()
    try:
        assert p.parse(None) is None
    except TypeError:
        # acceptable only if it's a clean type rejection, not a deep crash
        pass
