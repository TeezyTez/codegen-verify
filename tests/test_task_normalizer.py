from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1] / "project"
sys.path.insert(0, str(PROJECT_DIR))

from task_normalizer import (  # noqa: E402
    TaskNormalizationError,
    normalize_humaneval_problem,
    python_annotation_to_dafny,
    render_problem_description,
    render_dafny_signature,
)


def _problem(prompt: str, entry_point: str = "target") -> dict[str, str]:
    return {
        "task_id": "HumanEval/test",
        "entry_point": entry_point,
        "prompt": prompt,
    }


def test_ast_selects_entry_point_instead_of_first_helper_and_keeps_full_docstring() -> None:
    tail = "TAIL_MARKER_" + "x" * 260
    problem = _problem(
        '''\
def helper(value: int) -> bool:
    """A helper, not the requested function."""
    return value > 0


def target(values: List[int], threshold: float = 0.5) -> bool:
    """Decide whether the values meet the threshold.
    >>> target([1, 2], threshold=0.5)
    True
    '''
        + tail
        + '''
    """
'''
    )

    task = normalize_humaneval_problem(problem)

    assert task.entry_point == "target"
    assert task.signature == "def target(values: List[int], threshold: float=0.5) -> bool:"
    assert task.signature_source.startswith("def target(")
    assert "helper" not in task.signature_source
    assert task.parameters[0].annotation == "List[int]"
    assert task.parameters[0].dafny_type.dafny == "seq<int>"
    assert task.parameters[1].default_source == "0.5"
    assert tail in task.docstring
    assert len(task.docstring) > 300


def test_multiline_signature_preserves_exact_source_and_parameter_kinds() -> None:
    task = normalize_humaneval_problem(
        _problem(
            '''\
def target(
    head: Tuple[int, str],
    /,
    *items: float,
    enabled: bool = True,
    **metadata: dict[str, int],
) -> Optional[str]:
    """Return a value or None."""
'''
        )
    )

    assert "\n" in task.signature_source
    assert task.signature_source.rstrip().endswith(":")
    assert [parameter.kind for parameter in task.parameters] == [
        "positional_only",
        "var_positional",
        "keyword_only",
        "var_keyword",
    ]
    assert task.parameters[0].dafny_type.dafny == "(int, string)"
    assert task.parameters[2].has_default
    assert task.parameters[2].default_source == "True"
    assert not task.parameters[3].dafny_type.supported
    assert task.return_type.dafny == "Option<string>"
    assert "datatype Option<T>" in task.return_type.required_declarations[0]


def test_doctest_examples_are_structured_and_literal_values_are_recovered() -> None:
    task = normalize_humaneval_problem(
        _problem(
            '''\
def target(items: List[int], scale: int = 1) -> Optional[List[int]]:
    """Transform items.
    >>> target([1, -2], scale=3)
    [3, -6]
    >>> target([], scale=2)
    """
'''
        )
    )

    assert len(task.examples) == 2
    first, second = task.examples
    assert first.call_name == "target"
    assert first.positional_args == ([1, -2],)
    assert first.keyword_args == (("scale", 3),)
    assert first.arguments_are_literal
    assert first.expected_is_literal
    assert first.expected_value == [3, -6]
    assert second.expected_is_literal
    assert second.expected_value is None


@pytest.mark.parametrize(
    ("annotation", "dafny", "kind"),
    [
        ("int", "int", "integer"),
        ("float", "real", "real"),
        ("bool", "bool", "boolean"),
        ("str", "string", "string"),
        ("List[int]", "seq<int>", "sequence"),
        ("list[Tuple[int, str]]", "seq<(int, string)>", "sequence"),
        ("Tuple[int, bool]", "(int, bool)", "tuple"),
        ("Tuple[float, ...]", "seq<real>", "variadic_tuple"),
        ("Optional[str]", "Option<string>", "optional"),
        ("int | None", "Option<int>", "optional"),
    ],
)
def test_python_to_dafny_type_representation(annotation: str, dafny: str, kind: str) -> None:
    result = python_annotation_to_dafny(annotation)
    assert result.supported
    assert result.dafny == dafny
    assert result.kind == kind


@pytest.mark.parametrize("annotation", ["Any", "List[Any]", "dict", "Dict[str, int]"])
def test_any_and_mapping_types_are_explicitly_unsupported(annotation: str) -> None:
    result = python_annotation_to_dafny(annotation)
    assert not result.supported
    assert result.dafny is None
    assert result.reason


def test_render_uses_complete_description_examples_and_type_warnings() -> None:
    unique_tail = "semantic ending that must not be truncated"
    task = normalize_humaneval_problem(
        _problem(
            f'''\
def target(payload: dict[str, int]) -> Optional[str]:
    """{"A" * 260}
    {unique_tail}
    >>> target({{"answer": 42}})
    'ok'
    """
'''
        )
    )

    rendered = render_problem_description(task)

    assert unique_tail in rendered
    assert task.signature_source in rendered
    assert 'target({"answer": 42})' in rendered
    assert "期望: 'ok'" in rendered
    assert "UNSUPPORTED" in rendered
    assert "datatype Option<T>" in rendered


def test_deterministic_dafny_signature_uses_multiple_returns_for_tuple() -> None:
    task = normalize_humaneval_problem(
        _problem(
            '''\
def target(values: List[int]) -> Tuple[int, int]:
    """Return sum and product."""
'''
        )
    )
    assert render_dafny_signature(task) == (
        "method target(values: seq<int>) returns (result0: int, result1: int)"
    )


def test_missing_or_nested_entry_point_is_rejected() -> None:
    with pytest.raises(TaskNormalizationError, match="top-level FunctionDef"):
        normalize_humaneval_problem(
            _problem(
                '''\
def wrapper():
    def target(value: int) -> int:
        return value
'''
            )
        )


def test_real_humaneval_records_normalize_without_selecting_helpers() -> None:
    data_path = Path(__file__).resolve().parents[1] / "data" / "HumanEval.jsonl"
    records = {
        record["task_id"]: record
        for record in (json.loads(line) for line in data_path.read_text(encoding="utf-8").splitlines())
        if record["task_id"] in {"HumanEval/10", "HumanEval/12", "HumanEval/17", "HumanEval/51"}
    }

    palindrome = normalize_humaneval_problem(records["HumanEval/10"])
    assert palindrome.entry_point == "make_palindrome"
    assert palindrome.signature.startswith("def make_palindrome(")
    assert "is_palindrome" not in palindrome.signature

    longest = normalize_humaneval_problem(records["HumanEval/12"])
    assert longest.return_type.dafny == "Option<string>"
    assert longest.examples[0].expected_value is None

    music = normalize_humaneval_problem(records["HumanEval/17"])
    assert "'o|' - half note, lasts two beats" in music.docstring
    assert music.examples[0].expected_value == [4, 2, 1, 2, 2, 1, 1, 1, 1, 4, 4]

    multiline_string = normalize_humaneval_problem(records["HumanEval/51"])
    assert len(multiline_string.examples) == 6
    assert multiline_string.examples[1].positional_args == ("abcdef\nghijklm",)
    assert multiline_string.examples[1].expected_value == "bcdf\nghjklm"
