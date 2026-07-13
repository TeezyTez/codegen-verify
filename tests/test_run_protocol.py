import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import run_humaneval


PROBLEM = {
    "task_id": "HumanEval/test",
    "entry_point": "identity",
    "prompt": '''def identity(x: int) -> int:
    """Return x.
    >>> identity(2)
    2
    """
''',
    "test": "def check(candidate):\n    assert candidate(2) == 2\n",
}
SPEC = "method identity(x: int) returns (result: int)\n    ensures result == x"
CODE = SPEC + "\n{ result := x; }"


class RunProtocolTests(unittest.TestCase):
    def _final(self, **updates):
        result = {
            "dafny_verified": True,
            "passed": True,
            "code": CODE,
            "spec": SPEC,
            "round": 1,
            "behavior_executed": False,
            "behavior_passed": False,
            "research_trace": [],
        }
        result.update(updates)
        return result

    def test_strict_mode_never_places_official_test_inside_pipeline(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            run_humaneval, "run_pipeline", return_value=self._final()
        ) as pipeline, patch.object(
            run_humaneval, "run_humaneval_test", return_value=(True, {"error": None})
        ) as holdout:
            results = run_humaneval.run_benchmark(
                [PROBLEM], limit=1, evaluation_mode="strict", output_dir=Path(directory)
            )

        self.assertIsNone(pipeline.call_args.kwargs["behavior_problem"])
        holdout.assert_called_once()
        self.assertTrue(results[0]["passed"])
        self.assertTrue(results[0]["official_test_executed"])

    def test_assisted_mode_uses_only_separate_dev_test_and_still_runs_holdout(self):
        dev = {"test": "def check(candidate):\n    assert candidate(1) == 1\n"}
        with tempfile.TemporaryDirectory() as directory, patch.object(
            run_humaneval,
            "run_pipeline",
            return_value=self._final(behavior_executed=True, behavior_passed=True),
        ) as pipeline, patch.object(
            run_humaneval, "run_humaneval_test", return_value=(True, {"error": None})
        ) as holdout:
            results = run_humaneval.run_benchmark(
                [PROBLEM],
                limit=1,
                evaluation_mode="assisted",
                repair_tests={PROBLEM["task_id"]: dev},
                output_dir=Path(directory),
            )

        inloop = pipeline.call_args.kwargs["behavior_problem"]
        self.assertEqual(inloop["test"], dev["test"])
        self.assertNotEqual(inloop["test"], PROBLEM["test"])
        holdout.assert_called_once()
        self.assertTrue(results[0]["passed"])


if __name__ == "__main__":
    unittest.main()
