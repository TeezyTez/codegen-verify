import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PACKAGE_DIR = PROJECT_ROOT / "project"
if str(PROJECT_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_PACKAGE_DIR))

import humaneval_tester as tester


def test_complete_check_catches_assertion_omitted_by_diagnostic_pattern():
    test_code = """
def check(candidate):
    assert candidate(1) == 1
    assert 2 + 2 == 5
"""

    # 不含 candidate 的第二条断言使逐条诊断不再被视为完整。
    assert tester._run_asserts_with_diagnostics(test_code, lambda value: value) is None

    passed, detail = tester._execute_test_code(test_code, lambda value: value)

    assert passed is False
    assert detail["test_passed"] is False
    assert "断言失败" in detail["error"]


def test_complete_check_executes_loop_after_supported_top_level_assert():
    calls = []
    test_code = """
def check(candidate):
    assert candidate(0) == 0
    for value in (1, 2):
        assert candidate(value) == value
"""

    def candidate(value):
        calls.append(value)
        return -1 if value == 2 else value

    assert tester._run_asserts_with_diagnostics(test_code, candidate) is None

    passed, detail = tester._execute_test_code(test_code, candidate)

    assert passed is False
    assert calls == [0, 1, 2]
    assert "断言失败" in detail["error"]


def test_abs_and_comparison_assertions_produce_counterexample():
    test_code = """
def check(candidate):
    assert abs(candidate(1) - 1.0) < 1e-6
    assert candidate(2) < 5
"""

    def candidate(value):
        return 10 if value == 2 else float(value)

    passed, detail = tester._execute_test_code(test_code, candidate)

    assert passed is False
    assert detail["failing_input"] == [2]
    assert detail["expected"] == 5
    assert detail["actual"] == 10
    assert detail["assertions_total"] == 2
    assert detail["assertions_passed"] == 1


def test_abs_comparison_passes_through_full_check():
    test_code = """
def check(candidate):
    assert abs(candidate(3) - 0.3) < 1e-6
    assert candidate(4) <= 0.4
"""

    passed, detail = tester._execute_test_code(
        test_code,
        lambda value: value / 10,
    )

    assert passed is True
    assert detail["test_passed"] is True
    assert detail["error"] is None


def test_candidate_exception_is_reported_with_failing_input():
    test_code = """
def check(candidate):
    assert candidate(3) == 9
"""

    def candidate(value):
        raise ValueError(f"bad input: {value}")

    passed, detail = tester._execute_test_code(test_code, candidate)

    assert passed is False
    assert detail["failing_input"] == [3]
    assert detail["expected"] == 9
    assert detail["actual"] is None
    assert "ValueError: bad input: 3" in detail["error"]


def test_test_module_globals_are_visible_to_check():
    test_code = """
OFFSET = 7

def expected(value):
    return value + OFFSET

def check(candidate):
    assert candidate(5) == expected(5)
"""

    passed, detail = tester._execute_test_code(test_code, lambda value: value + 7)

    assert passed is True
    assert detail["test_passed"] is True


def test_prompt_helpers_are_loaded_before_official_check():
    support_code = """
def reference_transform(value):
    return value * value + 1

def target(value):
    \"\"\"Placeholder target from the HumanEval prompt.\"\"\"
"""
    test_code = """
def check(candidate):
    assert candidate(4) == reference_transform(4)
"""

    passed, detail = tester._execute_test_code(
        test_code,
        lambda value: value * value + 1,
        support_code,
        "target",
    )

    assert passed is True
    assert detail["test_passed"] is True


def _write_fake_generated_modules(directory: Path, method_body: str) -> None:
    (directory / "_dafny.py").write_text(
        """
class Seq:
    def __init__(self, value):
        self.Elements = tuple(value)
""",
        encoding="utf-8",
    )
    (directory / "HumanevalModule.py").write_text(
        "class default__:\n"
        "    @staticmethod\n"
        f"    {method_body}\n",
        encoding="utf-8",
    )


def test_sequence_inputs_use_dafny_runtime_sequence(monkeypatch):
    class Seq:
        def __init__(self, value):
            self.elems = tuple(value)

    monkeypatch.setitem(sys.modules, "_dafny", SimpleNamespace(Seq=Seq))
    converted = tester._to_dafny_val([1, 2, 3], "seq<int>")
    assert isinstance(converted, Seq)
    assert converted.elems == (1, 2, 3)


def test_nested_sequence_inputs_are_wrapped_recursively(monkeypatch):
    class Seq:
        def __init__(self, value):
            self.elems = tuple(value)

    monkeypatch.setitem(sys.modules, "_dafny", SimpleNamespace(Seq=Seq))
    converted = tester._to_dafny_val([[1], [2, 3]], "seq<seq<int>>")
    assert isinstance(converted, Seq)
    assert all(isinstance(item, Seq) for item in converted.elems)


def test_generated_module_loader_restores_path_and_module_cache():
    with tempfile.TemporaryDirectory(prefix="humaneval-loader-test-") as temp_dir:
        generated_dir = Path(temp_dir)
        _write_fake_generated_modules(
            generated_dir,
            "def identity(value):\n        return value",
        )
        original_path = list(sys.path)
        previous_module = sys.modules.get("HumanevalModule")
        previous_runtime = sys.modules.get("_dafny")

        with tester._loaded_generated_candidate(
            str(generated_dir),
            "identity",
            [("value", "int")],
            [("result", "int")],
        ) as candidate:
            assert candidate(11) == 11
            assert sys.path[0] == str(generated_dir.resolve())
            assert "HumanevalModule" in sys.modules
            assert "_dafny" in sys.modules

        assert sys.path == original_path
        assert sys.modules.get("HumanevalModule") is previous_module
        assert sys.modules.get("_dafny") is previous_runtime


def test_isolated_runner_times_out_nonterminating_candidate():
    test_code = """
def check(candidate):
    assert candidate(1) == 1
"""
    with tempfile.TemporaryDirectory(prefix="humaneval-timeout-test-") as temp_dir:
        generated_dir = Path(temp_dir)
        _write_fake_generated_modules(
            generated_dir,
            "def spin(value):\n        while True:\n            pass",
        )

        started = time.monotonic()
        passed, detail = tester._run_test_in_subprocess(
            str(generated_dir),
            "spin",
            [("value", "int")],
            [("result", "int")],
            test_code,
            timeout_seconds=0.5,
        )
        elapsed = time.monotonic() - started

        assert passed is False
        assert "超时" in detail["error"]
        assert elapsed < 5
        assert str(generated_dir.resolve()) not in sys.path
        assert "HumanevalModule" not in sys.modules


def test_run_humaneval_test_cleans_translation_directory(monkeypatch):
    generated_roots = []

    def fake_compile(command, **kwargs):
        assert command[:3] == ["fake-dafny", "translate", "py"]
        output_base = Path(command[command.index("--output") + 1])
        generated_roots.append(output_base.parent)
        Path(f"{output_base}-py").mkdir()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tester.subprocess, "run", fake_compile)
    monkeypatch.setattr(
        tester,
        "_run_test_in_subprocess",
        lambda *args, **kwargs: (
            True,
            {
                "test_passed": True,
                "error": None,
                "assertions_total": "N/A",
                "assertions_passed": "N/A",
            },
        ),
    )

    passed, detail = tester.run_humaneval_test(
        "method identity(value: int) returns (result: int) { result := value; }",
        {
            "task_id": "HumanEval/test",
            "entry_point": "identity",
            "test": "def check(candidate):\n    assert candidate(1) == 1\n",
        },
        dafny_path="fake-dafny",
    )

    assert passed is True
    assert detail["test_passed"] is True
    assert len(generated_roots) == 1
    assert not generated_roots[0].exists()
def test_from_dafny_option_maps_none_and_some(monkeypatch):
    class FakeRuntime:
        class Seq:  # pragma: no cover - only needed for isinstance lookup
            pass

    class Option_None:
        is_None = True

    class Option_Some:
        is_None = False

        def __init__(self, value):
            self.value = value

    monkeypatch.setitem(sys.modules, "_dafny", FakeRuntime)
    assert tester._from_dafny_val(Option_None(), "Option<string>") is None
    assert tester._from_dafny_val(Option_Some("x"), "Option<string>") == "x"
