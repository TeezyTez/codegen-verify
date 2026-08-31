import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from proof_edit_guard import proof_edit_issues


def test_proof_edit_guard_accepts_annotation_only_change():
    before = """method f(x: int) returns (r: int)
{
  r := x;
}"""
    after = """method f(x: int) returns (r: int)
{
  assert x == x;
  r := x;
}"""

    assert proof_edit_issues(before, after) == ()


def test_proof_edit_guard_rejects_executable_change():
    before = "method f(x: int) returns (r: int)\n{\n  r := x;\n}"
    after = "method f(x: int) returns (r: int)\n{\n  r := x + 1;\n}"

    assert "changed executable text" in proof_edit_issues(before, after)[0]

