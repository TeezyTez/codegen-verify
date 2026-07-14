"""Offline parser tests using Dafny 4.11 diagnostic output samples."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1] / "project"
sys.path.insert(0, str(PROJECT_DIR))

from dafny_wrapper import DafnyVerifier, ErrorInfo  # noqa: E402


INVARIANT_ENTRY_OUTPUT = """C:/tmp/entry.dfy(8,16): Error: this loop invariant could not be proved on entry
 Related message: loop invariant violation
  |
8 |     invariant 1 <= i <= n
  |                 ^^


Dafny program verifier finished with 0 verified, 1 error
"""


INVARIANT_MAINTENANCE_OUTPUT = """C:/tmp/maintenance.dfy(8,16): Error: this invariant could not be proved to be maintained by the loop
 Related message: loop invariant violation
  |
8 |     invariant r == i
  |                 ^^


Dafny program verifier finished with 0 verified, 1 error
"""


POSTCONDITION_OUTPUT = """C:/tmp/post.dfy(3,0): Error: a postcondition could not be proved on this return path
  |
3 | {
  | ^

C:/tmp/post.dfy(2,12): Related location: this is the postcondition that could not be proved
  |
2 |   ensures r > x
  |             ^


Dafny program verifier finished with 0 verified, 1 error
"""


PRECONDITION_OUTPUT = """C:/tmp/pre.dfy(5,8): Error: a precondition for this call could not be proved
  |
5 | { r := F(0); }
  |         ^

C:/tmp/pre.dfy(2,13): Related location: this is the precondition that could not be proved
  |
2 |   requires x > 0
  |              ^


Dafny program verifier finished with 1 verified, 1 error
"""


OUT_OF_RANGE_OUTPUT = """C:/tmp/range.dfy(3,8): Error: index out of range
  |
3 |   r := s[|s|];
  |         ^


Dafny program verifier finished with 0 verified, 1 error
"""


TERMINATION_OUTPUT = """C:/tmp/termination.dfy(3,25): Error: cannot prove termination; try supplying a decreases clause
  |
3 |   if n == 0 then 0 else F(n + 1)
  |                          ^


Dafny program verifier finished with 0 verified, 1 error
"""


SYNTAX_OUTPUT = """C:/tmp/syntax.dfy(3,6): Error: invalid Rhs
  |
3 |  r := ;
  |       ^

1 parse errors detected in syntax.dfy
"""


TYPE_OUTPUT = """C:/tmp/type.dfy(3,3): Error: RHS (of type bool) not assignable to LHS (of type int)
  |
3 |  r := true;
  |    ^^

1 resolution/type errors detected in type.dfy
"""


def test_invariant_entry_has_compatible_type_and_precise_subtype():
    result = DafnyVerifier()._parse(INVARIANT_ENTRY_OUTPUT, returncode=1)

    assert result.passed is False
    assert result.error_count == 1
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.error_type == "invariant"
    assert error.subtype == "invariant_entry"
    assert (error.location_line, error.location_col) == (8, 16)
    assert error.source == "    invariant 1 <= i <= n"


def test_invariant_maintenance_is_distinguished_from_entry():
    result = DafnyVerifier()._parse(INVARIANT_MAINTENANCE_OUTPUT, returncode=1)

    assert result.errors[0].error_type == "invariant"
    assert result.errors[0].subtype == "invariant_maintenance"
    assert result.errors[0].source == "    invariant r == i"


def test_postcondition_block_attaches_related_location_and_source():
    result = DafnyVerifier()._parse(POSTCONDITION_OUTPUT, returncode=1)

    assert result.error_count == 1
    assert len(result.errors) == 1  # Related location is not a second error.
    error = result.errors[0]
    assert error.error_type == "postcondition"
    assert error.subtype == "postcondition"
    assert error.source == "{"
    assert error.related_source == "  ensures r > x"
    assert error.related_spec == error.related_source
    assert (error.related_location_line, error.related_location_col) == (2, 12)


def test_precondition_block_preserves_verified_count_and_related_source():
    result = DafnyVerifier()._parse(PRECONDITION_OUTPUT, returncode=1)

    assert result.verified_count == 1
    assert result.error_count == 1
    error = result.errors[0]
    assert error.error_type == "precondition"
    assert error.subtype == "precondition"
    assert error.source == "{ r := F(0); }"
    assert error.related_source == "  requires x > 0"


def test_actual_411_outputs_cover_range_termination_syntax_and_type():
    cases = [
        (OUT_OF_RANGE_OUTPUT, "out_of_range"),
        (TERMINATION_OUTPUT, "termination"),
        (SYNTAX_OUTPUT, "syntax"),
        (TYPE_OUTPUT, "type"),
    ]

    for output, expected in cases:
        parser = DafnyVerifier()._parse_resolve if expected in {"syntax", "type"} else DafnyVerifier()._parse
        result = parser(output, returncode=1)
        assert result.passed is False
        assert result.error_count == 1
        assert result.errors[0].error_type == expected
        assert result.errors[0].subtype == expected
        assert result.errors[0].source


def test_source_block_can_capture_multiple_numbered_lines():
    output = """C:/tmp/multiline.dfy(7,15): Error: this invariant could not be proved to be maintained by the loop
  |
7 |     invariant 0 <= i &&
8 |               i <= n
  |                ^

Dafny program verifier finished with 0 verified, 1 error
"""

    error = DafnyVerifier()._parse(output, returncode=1).errors[0]
    assert error.source == "    invariant 0 <= i &&\n              i <= n"


def test_success_requires_zero_returncode_even_when_summary_has_no_errors():
    output = "Dafny program verifier finished with 1 verified, 0 errors\n"

    assert DafnyVerifier()._parse(output, returncode=0).passed is True
    failed_process = DafnyVerifier()._parse(output, returncode=7)
    assert failed_process.passed is False
    assert failed_process.error_count == 1
    assert failed_process.errors[0].subtype == "process_error"


def test_timeout_is_structured_and_keeps_errorinfo_compatibility():
    verifier = DafnyVerifier(dafny_path="dafny")
    timeout = subprocess.TimeoutExpired(cmd=["dafny", "resolve"], timeout=15)

    with patch("dafny_wrapper.subprocess.run", side_effect=timeout):
        result = verifier.verify("method M() {}")

    assert result.passed is False
    assert result.error_count == 1
    assert result.errors[0].error_type == "timeout"
    assert result.errors[0].subtype == "timeout"
    assert "15" in result.errors[0].message

    # Existing positional construction remains valid; new fields are optional.
    legacy = ErrorInfo("syntax", "old", 3, 4, "requires true")
    assert legacy.error_type == "syntax"
    assert legacy.related_spec == "requires true"
    assert legacy.subtype == ""


def test_commands_allow_non_fatal_dafny_warnings():
    verifier = DafnyVerifier("dafny")
    assert verifier._cmd("resolve", "sample.dfy") == [
        "dafny", "resolve", "--allow-warnings", "sample.dfy"
    ]
    verify_command = verifier._cmd("verify", "sample.dfy")
    assert verify_command[:3] == ["dafny", "verify", "--allow-warnings"]


def test_process_error_keeps_warning_output_for_diagnosis():
    parsed = DafnyVerifier()._parse_resolve(
        "Compilation failed because warnings were found", returncode=2
    )
    assert parsed.errors[0].subtype == "process_error"
    assert "warnings were found" in parsed.errors[0].message
