import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from spec_repair import _reference_pattern_hint, validate_spec


def test_validate_spec_rejects_bodyless_reference_function():
    spec = """method f(x: int) returns (result: int)
    ensures result == Reference(x)

function Reference(x: int): int
"""
    valid, error = validate_spec(spec)
    assert valid is False
    assert "missing a body" in error


def test_validate_spec_allows_bodyless_ghost_only_helper():
    spec = """predicate GhostProperty(x: int)

function Reference(x: int): int { x }

method f(x: int) returns (result: int)
    ensures GhostProperty(x)
    ensures result == Reference(x)
"""
    valid, error = validate_spec(spec)
    assert valid is True, error


def test_parenthesis_grouping_gets_state_threaded_reference_hint():
    hint = _reference_pattern_hint(
        "Separate groups of balanced parentheses from a string.",
        {"flags": ["proof_friendly_reference_missing"]},
    )
    assert "depth" in hint
    assert "completed groups" in hint
    assert "无 body" in hint
