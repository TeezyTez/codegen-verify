import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import pipeline
import config
from task_normalizer import normalize_humaneval_problem
from spec_critic import (
    _empty_argument_is_explicit,
    _explicit_task_domain_error,
    _validate_reconciliation_report,
    confirm_probe_expectation_with_llm,
    critic_feedback_obligations,
    execute_approved_boundary_checks,
    generate_task_probes_with_llm,
    public_example_probes,
    normalize_critic_report,
    review_spec_with_llm,
)


class FakeLLM:
    provider = "deepseek"
    model = "deepseek-chat"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _report(decision="approve", **updates):
    report = {
        "decision": decision,
        "confidence": 0.8,
        "summary": "audit complete",
        "issues": [],
        "counterexamples": [],
        "boundary_checks": [
            {
                "case": "zero",
                "input": 0,
                "arguments": [0],
                "expected": 0,
                "expected_value": 0,
                "spec_behavior": 0,
                "matches": True,
                "within_task_domain": True,
                "expected_source": "task_text",
            },
            {
                "case": "one",
                "input": 1,
                "arguments": [1],
                "expected": 1,
                "expected_value": 1,
                "spec_behavior": 1,
                "matches": True,
                "within_task_domain": True,
                "expected_source": "task_text",
            },
        ],
    }
    report.update(updates)
    return report


def _approval_report_for(*cases):
    return _report(
        "approve",
        boundary_checks=[
            {
                "case": f"typed-{index}",
                "input": repr(arguments),
                "arguments": arguments,
                "expected": repr(expected),
                "expected_value": expected,
                "spec_behavior": repr(expected),
                "matches": True,
                "within_task_domain": True,
                "expected_source": "task_text",
            }
            for index, (arguments, expected) in enumerate(cases, start=1)
        ],
    )


class SpecCriticTests(unittest.TestCase):
    @staticmethod
    def _graph_state():
        return {
            "problem_id": "test",
            "problem_desc": "Return x.",
            "spec": "",
            "code": "",
            "entry_point": "f",
            "round": 1,
            "max_rounds": 1,
            "behavior_problem": {},
            "research_trace": [],
            "mutation_adequacy": {},
            "mutation_strengthening_attempts": 0,
            "critic_repair_rounds": 0,
        }

    def test_fenced_json_is_parsed_with_model_identity(self):
        llm = FakeLLM([
            "```json\n"
            '{"decision":"approve","confidence":0.8,"summary":"ok",'
            '"issues":[],"counterexamples":[],"boundary_checks":['
            '{"case":"zero","input":0,"arguments":[0],"expected":0,"expected_value":0,'
            '"spec_behavior":0,"matches":true,'
            '"within_task_domain":true,"expected_source":"task_text"},'
            '{"case":"one","input":1,"arguments":[1],"expected":1,"expected_value":1,'
            '"spec_behavior":1,"matches":true,'
            '"within_task_domain":true,"expected_source":"task_text"}]}'
            "\n```"
        ])
        report = review_spec_with_llm(
            llm,
            problem_desc="Return x.",
            spec="method f(x: int) returns (result: int) ensures result == x",
            entry_point="f",
            review_passes=1,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "approve")
        self.assertEqual(report["critic_provider"], "deepseek")
        self.assertEqual(report["critic_model"], "deepseek-chat")
        self.assertEqual(llm.calls[0]["temperature"], 0.0)
        self.assertGreater(llm.calls[0]["max_tokens"], 0)

    def test_taskir_signature_gate_rejects_type_drift_before_llm_call(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "test/0",
            "entry_point": "f",
            "prompt": (
                "def f(x: int) -> int:\n"
                "    \"\"\"Return x.\"\"\"\n"
            ),
        }).to_dict()
        llm = FakeLLM([])

        report = review_spec_with_llm(
            llm,
            problem_desc="Return x.",
            spec="method f(x: bool) returns (result: int) ensures result == 0",
            entry_point="f",
            task_ir=task_ir,
        )

        self.assertEqual(report["decision"], "reject")
        self.assertEqual(report["signature_gate"]["status"], "failed")
        self.assertIn("types differ", report["signature_gate"]["issues"][0])
        self.assertEqual(llm.calls, [])

    def test_unexplained_public_precondition_forces_abstention(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "test/domain",
            "entry_point": "f",
            "prompt": (
                "def f(x: int) -> int:\n"
                "    \"\"\"Return x.\"\"\"\n"
            ),
        }).to_dict()

        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([1], 1), ([2], 2)))]),
            problem_desc="Return x.",
            spec=(
                "method f(x: int) returns (result: int)\n"
                "  requires x >= 0\n"
                "  ensures result == x"
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "abstain")
        self.assertEqual(report["unreviewed_public_requires"], ["x >= 0"])

    def test_explicit_positive_domain_justifies_public_precondition(self):
        problem = {
            "task_id": "test/positive",
            "entry_point": "f",
            "prompt": (
                "def f(x: int) -> int:\n"
                "    \"\"\"Given a positive integer, return it.\"\"\"\n"
            ),
        }
        task_ir = normalize_humaneval_problem(problem).to_dict()

        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([1], 1), ([2], 2)))]),
            problem_desc="Given a positive integer, return it.",
            spec=(
                "method f(x: int) returns (result: int)\n"
                "  requires x > 0\n"
                "  ensures result == x"
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "approve")
        self.assertEqual(report["public_precondition_review"]["status"], "passed")

    def test_mean_definedness_justifies_nonempty_sequence_precondition(self):
        problem = {
            "task_id": "test/mean",
            "entry_point": "mean",
            "prompt": (
                "from typing import List\n"
                "def mean(xs: List[float]) -> float:\n"
                "    \"\"\"Return the average (mean) of the dataset.\"\"\"\n"
            ),
        }
        task_ir = normalize_humaneval_problem(problem).to_dict()

        report = review_spec_with_llm(
            FakeLLM([
                json.dumps(_approval_report_for(([[1.0]], 1.0), ([[2.0, 4.0]], 3.0)))
            ]),
            problem_desc="Return the average (mean) of the dataset.",
            spec=(
                "method mean(xs: seq<real>) returns (result: real)\n"
                "  requires |xs| > 0\n"
                "  ensures result == 0.0"
            ),
            entry_point="mean",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "approve")
        assessment = report["public_precondition_review"]["assessments"][0]
        self.assertEqual(
            assessment["atoms"][0]["evidence"]["kind"],
            "mathematical_definedness",
        )

    def test_zero_to_n_range_justifies_nonnegative_n(self):
        problem = {
            "task_id": "test/range",
            "entry_point": "f",
            "prompt": (
                "def f(n: int) -> str:\n"
                "    \"\"\"Return numbers starting from 0 upto n inclusive.\"\"\"\n"
            ),
        }
        task_ir = normalize_humaneval_problem(problem).to_dict()
        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([0], "0"), ([1], "0 1")))]),
            problem_desc="Return numbers starting from 0 upto n inclusive.",
            spec=(
                "method f(n: int) returns (result: string)\n"
                "  requires n >= 0\n"
                "  ensures result == \"\""
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "approve")
        assessment = report["public_precondition_review"]["assessments"][0]
        self.assertEqual(
            assessment["atoms"][0]["evidence"]["kind"],
            "range_definedness",
        )

    def test_precondition_evidence_is_bound_to_each_parameter_and_conjunct(self):
        problem = {
            "task_id": "test/two-params",
            "entry_point": "f",
            "prompt": (
                "def f(x: int, y: int) -> int:\n"
                "    \"\"\"x is positive; return x plus y.\"\"\"\n"
            ),
        }
        task_ir = normalize_humaneval_problem(problem).to_dict()
        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([1, 0], 1), ([2, -1], 1)))]),
            problem_desc="x is positive; return x plus y.",
            spec=(
                "method f(x: int, y: int) returns (result: int)\n"
                "  requires x > 0 && y > 0\n"
                "  ensures result == x + y"
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "abstain")
        assessment = report["public_precondition_review"]["assessments"][0]
        self.assertEqual(
            [atom["status"] for atom in assessment["atoms"]],
            ["justified", "unresolved"],
        )

    def test_implication_cannot_hide_an_extra_public_domain_restriction(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "test/implication",
            "entry_point": "f",
            "prompt": (
                "def f(x: int, y: int) -> int:\n"
                "    \"\"\"x is positive; y is any integer; return x plus y.\"\"\"\n"
            ),
        }).to_dict()
        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([1, 0], 1), ([2, -1], 1)))]),
            problem_desc="x is positive; y is any integer; return x plus y.",
            spec=(
                "method f(x: int, y: int) returns (result: int)\n"
                "  requires x > 0 ==> y > 0\n"
                "  ensures result == x + y"
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "abstain")
        self.assertEqual(
            report["public_precondition_review"]["unresolved_clauses"],
            ["x > 0 ==> y > 0"],
        )

    def test_positive_output_language_does_not_justify_positive_input_precondition(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "test/positive-output",
            "entry_point": "f",
            "prompt": (
                "def f(x: int) -> int:\n"
                "    \"\"\"Return the positive integer 1 for any integer input.\"\"\"\n"
            ),
        }).to_dict()
        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([-1], 1), ([0], 1)))]),
            problem_desc="Return the positive integer 1 for any integer input.",
            spec=(
                "method f(x: int) returns (result: int)\n"
                "  requires x > 0\n"
                "  ensures result == 1"
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "abstain")
        self.assertEqual(report["public_precondition_review"]["status"], "unresolved")

    def test_equal_length_evidence_is_bound_to_the_exact_parameter_pair(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "test/length-pair",
            "entry_point": "f",
            "prompt": (
                "from typing import List\n"
                "def f(xs: List[int], ys: List[int], zs: List[int]) -> int:\n"
                "    \"\"\"xs and ys have the same length; return 0.\"\"\"\n"
            ),
        }).to_dict()
        report = review_spec_with_llm(
            FakeLLM([json.dumps(_approval_report_for(([[1], [2], [3]], 0)))]),
            problem_desc="xs and ys have the same length; return 0.",
            spec=(
                "method f(xs: seq<int>, ys: seq<int>, zs: seq<int>) "
                "returns (result: int)\n"
                "  requires |xs| == |zs|\n"
                "  ensures result == 0"
            ),
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "abstain")
        self.assertEqual(
            report["public_precondition_review"]["unresolved_clauses"],
            ["|xs| == |zs|"],
        )

    def test_critic_evidence_is_retried_when_taskir_types_do_not_match(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "test/evidence-types",
            "entry_point": "f",
            "prompt": "def f(x: int) -> int:\n    \"\"\"Return x.\"\"\"\n",
        }).to_dict()
        invalid = _approval_report_for((["not-an-int"], 1))
        corrected = _approval_report_for(([0], 0), ([1], 1))
        llm = FakeLLM([json.dumps(invalid), json.dumps(corrected)])

        report = review_spec_with_llm(
            llm,
            problem_desc="Return x.",
            spec="method f(x: int) returns (result: int) ensures result == x",
            entry_point="f",
            task_ir=task_ir,
            execute_boundary_checks=False,
            review_passes=1,
            max_parse_retries=1,
        )

        self.assertEqual(report["decision"], "approve")
        self.assertEqual(report["parse_attempts"], 2)
        self.assertIn("does not match task type", llm.calls[1]["user"])

    def test_reconciliation_retries_a_dafny_validity_only_rejection(self):
        validity_reject = _report(
            "reject",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "critical",
                "material": True,
                "requirement": "the helper must be a valid Dafny expression",
                "spec_location": "Reference",
                "explanation": "number.Floor is allegedly not a built-in Dafny expression",
            }],
            counterexamples=[{
                "input": "3.5",
                "arguments": [3.5],
                "expected": 0.5,
                "expected_value": 0.5,
                "spec_behavior": "undefined because Dafny cannot compile it",
                "rationale": "claimed language invalidity",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            }],
        )

        with self.assertRaisesRegex(ValueError, "already resolved and verified"):
            _validate_reconciliation_report(validity_reject, {})

    def test_reconciliation_approval_must_reuse_executed_evidence_exactly(self):
        conflicting = _approval_report_for(([2], 99))
        with self.assertRaisesRegex(ValueError, "contradicts already executed"):
            _validate_reconciliation_report(
                conflicting,
                {},
                passed_evidence=[{"arguments": [2], "expected_value": 2}],
            )

        novel = _approval_report_for(([3], 3))
        with self.assertRaisesRegex(ValueError, "was not executed"):
            _validate_reconciliation_report(
                novel,
                {},
                passed_evidence=[{"arguments": [2], "expected_value": 2}],
            )

        accepted = _approval_report_for(([2], 2))
        _validate_reconciliation_report(
            accepted,
            {},
            passed_evidence=[{"arguments": [2], "expected_value": 2}],
        )

    def test_empty_and_example_domain_evidence_is_entrypoint_and_parameter_bound(self):
        task_ir = {
            "entry_point": "f",
            "parameters": [
                {"name": "haystack", "dafny_type": {"kind": "string", "arguments": []}},
                {"name": "needle", "dafny_type": {"kind": "string", "arguments": []}},
            ],
            "return_type": {"kind": "integer", "arguments": []},
            "raw_docstring": (
                "Needle is a nonempty pattern. When haystack is empty, compare needle carefully."
            ),
            "examples": [],
        }
        self.assertTrue(_empty_argument_is_explicit(0, task_ir))
        self.assertFalse(_empty_argument_is_explicit(1, task_ir))

        numeric_task = {
            "entry_point": "f",
            "parameters": [{
                "name": "x",
                "dafny_type": {"kind": "integer", "arguments": []},
            }],
            "return_type": {"kind": "integer", "arguments": []},
            "raw_docstring": "Given a positive integer x, return x.",
            "examples": [{
                "call_name": "helper",
                "positional_args": (-1,),
                "arguments_are_literal": True,
            }],
        }
        self.assertIn("explicitly positive", _explicit_task_domain_error([-1], numeric_task))

    def test_inconsistent_approval_with_counterexample_fails_closed(self):
        report = normalize_critic_report(_report(
            "approve",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "high",
                "material": True,
                "requirement": "include final prefix",
                "spec_location": "Reference",
                "explanation": "final value is omitted",
            }],
            counterexamples=[{
                "input": "[1, 2, -4]",
                "arguments": [[1, 2, -4]],
                "expected": True,
                "expected_value": True,
                "spec_behavior": False,
                "rationale": "off by one",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            }],
            boundary_checks=[{
                "case": "negative at final position",
                "input": "[1, 2, -4]",
                "arguments": [[1, 2, -4]],
                "expected": True,
                "expected_value": True,
                "spec_behavior": False,
                "matches": False,
                "within_task_domain": True,
                "expected_source": "task_text",
            }],
        ))
        self.assertEqual(report["decision"], "reject")

    def test_approval_with_mismatching_grounded_boundary_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "approval contains"):
            normalize_critic_report(_report(
                "approve",
                boundary_checks=[{
                    "case": "contradictory trace",
                    "input": 1,
                    "arguments": [1],
                    "expected": 1,
                    "expected_value": 1,
                    "spec_behavior": 0,
                    "matches": False,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                }],
            ))

    def test_unparseable_output_abstains_after_retry(self):
        llm = FakeLLM(["not json", "still not json"])
        report = review_spec_with_llm(
            llm,
            problem_desc="Return x.",
            spec="method f(x: int) returns (result: int) ensures result == x",
            max_parse_retries=1,
            review_passes=1,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "abstain")
        self.assertEqual(report["parse_attempts"], 2)
        self.assertIn("previous response was invalid", llm.calls[1]["user"])

    def test_second_pass_can_overturn_a_false_approval(self):
        first = _report("approve")
        second = _report(
            "reject",
            summary="singleton witness violates the quantifier bound",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "high",
                "material": True,
                "requirement": "observe a negative final operation",
                "spec_location": "exists i :: i < |operations|",
                "explanation": "i=1 is not eligible for a singleton input",
            }],
            counterexamples=[{
                "input": "[-1]",
                "arguments": [[-1]],
                "expected": True,
                "expected_value": True,
                "spec_behavior": False,
                "rationale": "only i=0 is quantified and SumPrefix(xs, 0)=0",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            }],
            boundary_checks=[
                {
                    "case": "empty",
                    "input": "[]",
                    "arguments": [[]],
                    "expected": False,
                    "expected_value": False,
                    "spec_behavior": False,
                    "matches": True,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                },
                {
                    "case": "negative singleton",
                    "input": "[-1]",
                    "arguments": [[-1]],
                    "expected": True,
                    "expected_value": True,
                    "spec_behavior": False,
                    "matches": False,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                },
            ],
        )
        llm = FakeLLM([json.dumps(first), json.dumps(second)])
        report = review_spec_with_llm(
            llm,
            problem_desc="Return true if any prefix balance is negative.",
            spec="method below_zero(operations: seq<int>) returns (result: bool)",
            review_passes=2,
            max_parse_retries=0,
            execute_boundary_checks=False,
        )

        self.assertEqual(report["decision"], "reject")
        self.assertEqual(report["review_passes"], 2)
        self.assertIn("Untrusted previous audit", llm.calls[1]["user"])

    def test_structured_findings_become_repair_obligations(self):
        obligations = critic_feedback_obligations(_report(
            "reject",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "high",
                "material": True,
                "requirement": "include the current prefix element",
                "spec_location": "SumPrefix",
                "explanation": "index i is excluded",
            }],
        ))
        self.assertIn("include the current prefix element", obligations[0])
        self.assertIn("SumPrefix", obligations[0])

    def test_reject_narrative_that_says_spec_is_correct_is_retried(self):
        contradictory = _report(
            "reject",
            summary="The specification is actually correct and should approve.",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "high",
                "material": True,
                "requirement": "preserve duplicates",
                "spec_location": "Reference",
                "explanation": "previous audit incorrectly ignored exact equality",
            }],
            counterexamples=[{
                "input": "['a', 'a']",
                "arguments": [["a", "a"]],
                "expected": "['a', 'a']",
                "expected_value": ["a", "a"],
                "spec_behavior": "['a']",
                "rationale": "claimed mismatch",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            }],
            boundary_checks=[{
                "case": "duplicates",
                "input": "['a', 'a']",
                "arguments": [["a", "a"]],
                "expected": "['a', 'a']",
                "expected_value": ["a", "a"],
                "spec_behavior": "['a']",
                "matches": False,
                "within_task_domain": True,
                "expected_source": "task_text",
            }],
        )
        llm = FakeLLM([json.dumps(contradictory), json.dumps(_report("approve"))])
        report = review_spec_with_llm(
            llm,
            problem_desc="Preserve matching strings.",
            spec="method f() returns (result: int)",
            review_passes=1,
            max_parse_retries=1,
            execute_boundary_checks=False,
        )
        self.assertEqual(report["decision"], "approve")
        self.assertIn("self-contradictory", llm.calls[1]["user"])

    def test_raw_control_character_inside_json_string_is_tolerated(self):
        raw = json.dumps(_report("approve")).replace("audit complete", "audit\x01complete")
        llm = FakeLLM([raw])
        report = review_spec_with_llm(
            llm,
            problem_desc="Return x.",
            spec="method f(x: int) returns (result: int)",
            review_passes=1,
            max_parse_retries=0,
            execute_boundary_checks=False,
        )
        self.assertEqual(report["decision"], "approve")

    def test_probe_generator_returns_distinct_json_native_probes(self):
        probes = {
            "probes": [
                {
                    "case": "negative singleton",
                    "requirement": "detect any negative prefix",
                    "arguments": [[-1]],
                    "expected_value": True,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "first and final operation is decisive",
                    "coverage_tags": ["minimal_valid", "singleton"],
                    "contrast_group": "",
                },
                {
                    "case": "all positive",
                    "requirement": "return false if no prefix is negative",
                    "arguments": [[2]],
                    "expected_value": False,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "negative condition never occurs",
                    "coverage_tags": ["minimal_valid", "decisive_last"],
                    "contrast_group": "final_negative",
                },
                {
                    "case": "negative only at end",
                    "requirement": "include the final operation",
                    "arguments": [[2, -3]],
                    "expected_value": True,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "detect exclusive endpoint errors",
                    "coverage_tags": ["decisive_last", "endpoint"],
                    "contrast_group": "final_negative",
                },
            ]
        }
        llm = FakeLLM([json.dumps(probes)])
        suite = generate_task_probes_with_llm(
            llm,
            problem_desc="Return true if any prefix balance is negative.",
            entry_point="below_zero",
            max_parse_retries=0,
        )
        self.assertEqual(suite["status"], "generated")
        self.assertEqual(len(suite["probes"]), 3)
        self.assertEqual(suite["probes"][0]["arguments"], [[-1]])

    def test_probe_generator_retries_explanation_with_self_revision(self):
        def probe(case, argument, *, rationale="consistent result"):
            return {
                "case": case,
                "requirement": "return the input",
                "arguments": [argument],
                "expected_value": argument,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": rationale,
                "coverage_tags": ["minimal_valid"],
                "contrast_group": "",
            }

        invalid = {
            "probes": [
                probe("zero", 0, rationale="Wait, correct expected: 0."),
                probe("one", 1),
                probe("two", 2),
            ]
        }
        corrected = {
            "probes": [probe("zero", 0), probe("one", 1), probe("two", 2)]
        }
        llm = FakeLLM([json.dumps(invalid), json.dumps(corrected)])

        suite = generate_task_probes_with_llm(
            llm,
            problem_desc="Return x.",
            entry_point="f",
            max_parse_retries=1,
        )

        self.assertEqual(suite["status"], "generated")
        self.assertEqual(suite["attempts"], 2)
        self.assertIn("self-revision", llm.calls[1]["user"])

    def test_probe_generator_uses_semantic_projection_and_retries_unspecified_empty(self):
        def probe(case, values, expected):
            return {
                "case": case,
                "requirement": "sum the input list",
                "arguments": [values],
                "expected_value": expected,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "direct sum",
                "coverage_tags": ["minimal_valid", "singleton"],
                "contrast_group": "",
            }

        invalid = {"probes": [
            probe("invented empty", [], 0),
            probe("one", [1], 1),
            probe("two", [2], 2),
        ]}
        corrected = {"probes": [
            probe("one", [1], 1),
            probe("two", [2], 2),
            probe("three", [3], 3),
        ]}
        task_ir = {
            "signature": "def f(xs: List[int]) -> int:",
            "raw_docstring": "Return the sum of the supplied numbers.",
            "parameters": [{
                "name": "xs",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
            }],
            "return_type": {"kind": "integer", "arguments": []},
            "examples": [],
        }
        llm = FakeLLM([json.dumps(invalid), json.dumps(corrected)])

        suite = generate_task_probes_with_llm(
            llm,
            problem_desc="Dafny-only instruction that must stay out of blind probes.",
            entry_point="f",
            max_parse_retries=1,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "generated")
        self.assertEqual(suite["attempts"], 2)
        self.assertNotIn("Dafny-only instruction", llm.calls[0]["user"])
        self.assertIn("Return the sum", llm.calls[0]["user"])
        self.assertIn("too few distinct", llm.calls[1]["user"])

    def test_unspecified_empty_probe_is_dropped_if_suite_remains_complete(self):
        def probe(case, value, expected, tags, group=""):
            return {
                "case": case,
                "requirement": "return every non-empty prefix",
                "arguments": [value],
                "expected_value": expected,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "prefix construction",
                "coverage_tags": tags,
                "contrast_group": group,
            }

        payload = {"probes": [
            probe("speculative empty", "", [], ["minimal_valid"]),
            probe("one", "a", ["a"], []),
            probe("two", "ab", ["a", "ab"], ["ordering"]),
            probe("three", "abc", ["a", "ab", "abc"], ["ordering"]),
        ]}
        task_ir = {
            "signature": "def all_prefixes(s: str) -> List[str]:",
            "raw_docstring": "Return all prefixes from shortest to longest.",
            "parameters": [{
                "name": "s",
                "dafny_type": {"kind": "string", "arguments": []},
            }],
            "return_type": {
                "kind": "sequence",
                "arguments": [{"kind": "string", "arguments": []}],
            },
            "examples": [],
        }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps(payload)]),
            problem_desc="full generation prompt",
            entry_point="all_prefixes",
            max_parse_retries=0,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "generated")
        self.assertEqual(suite["attempts"], 1)
        self.assertEqual([probe["arguments"] for probe in suite["probes"]], [
            ["a"], ["ab"], ["abc"],
        ])
        self.assertIn("minimal_valid", suite["probes"][0]["coverage_tags"])
        self.assertIn("singleton", suite["probes"][0]["coverage_tags"])

    def test_model_declared_singleton_tag_cannot_fake_structural_coverage(self):
        probes = {
            "probes": [
                {
                    "case": f"length-{length}",
                    "requirement": "return the sequence length",
                    "arguments": [list(range(length))],
                    "expected_value": length,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "direct length",
                    "coverage_tags": ["minimal_valid", "singleton"],
                    "contrast_group": "",
                }
                for length in (2, 3, 4)
            ]
        }
        task_ir = {
            "signature": "def f(xs: List[int]) -> int:",
            "raw_docstring": "Return the length of the input list.",
            "parameters": [{
                "name": "xs",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
            }],
            "return_type": {"kind": "integer", "arguments": []},
            "examples": [],
        }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps(probes)]),
            problem_desc="full generation prompt",
            entry_point="f",
            max_parse_retries=0,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("singleton", suite["error"])

    def test_model_declared_multiplicity_tag_requires_actual_repetition(self):
        def probe(value):
            return {
                "case": f"value-{value}",
                "requirement": "count every occurrence, including duplicates",
                "arguments": [[value], value],
                "expected_value": 1,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "the singleton contains the target once",
                "coverage_tags": ["minimal_valid", "singleton", "multiplicity"],
                "contrast_group": "",
            }

        task_ir = {
            "signature": "def count_occurrences(values: List[int], target: int) -> int:",
            "raw_docstring": (
                "Count how many times target occurs in the list, preserving duplicate "
                "occurrences."
            ),
            "parameters": [
                {
                    "name": "values",
                    "dafny_type": {
                        "kind": "sequence",
                        "arguments": [{"kind": "integer", "arguments": []}],
                    },
                },
                {"name": "target", "dafny_type": {"kind": "integer", "arguments": []}},
            ],
            "return_type": {"kind": "integer", "arguments": []},
            "examples": [],
        }
        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [probe(1), probe(2), probe(3)]})]),
            problem_desc="full generation prompt",
            entry_point="count_occurrences",
            max_parse_retries=0,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("multiplicity", suite["error"])

    def test_model_declared_tie_tag_requires_an_actual_tie_case(self):
        def probe(value):
            return {
                "case": value,
                "requirement": "choose the longest string with lexical tie-breaking",
                "arguments": [[value]],
                "expected_value": value,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "a singleton has only one possible result",
                "coverage_tags": ["minimal_valid", "singleton", "tie"],
                "contrast_group": "",
            }

        task_ir = {
            "signature": "def choose(values: List[str]) -> str:",
            "raw_docstring": (
                "Return the longest string. If multiple strings have the same length, "
                "return the lexicographically first one."
            ),
            "parameters": [{
                "name": "values",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "string", "arguments": []}],
                },
            }],
            "return_type": {"kind": "string", "arguments": []},
            "examples": [],
        }
        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({
                "probes": [probe("a"), probe("bb"), probe("ccc")],
            })]),
            problem_desc="full generation prompt",
            entry_point="choose",
            max_parse_retries=0,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("tie", suite["error"])

    def test_decisive_last_requires_a_named_adjacent_contrast_pair(self):
        probes = {
            "probes": [
                {
                    "case": "negative singleton",
                    "requirement": "detect a negative balance",
                    "arguments": [[-1]],
                    "expected_value": True,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "the first balance is negative",
                    "coverage_tags": ["minimal_valid", "singleton"],
                    "contrast_group": "",
                },
                {
                    "case": "safe prefix",
                    "requirement": "include the final operation",
                    "arguments": [[2]],
                    "expected_value": False,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "the balance remains nonnegative",
                    "coverage_tags": ["decisive_last"],
                    "contrast_group": "",
                },
                {
                    "case": "failure only at end",
                    "requirement": "include the final operation",
                    "arguments": [[2, -3]],
                    "expected_value": True,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "only the appended operation makes the balance negative",
                    "coverage_tags": ["decisive_last"],
                    "contrast_group": "",
                },
            ]
        }
        task_ir = {
            "signature": "def below_zero(operations: List[int]) -> bool:",
            "raw_docstring": "Return true if at any point a prefix balance is below zero.",
            "parameters": [{
                "name": "operations",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
            }],
            "return_type": {"kind": "boolean", "arguments": []},
            "examples": [],
        }
        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps(probes)]),
            problem_desc="full generation prompt",
            entry_point="below_zero",
            max_parse_retries=0,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("decisive_last", suite["error"])

    def test_explicit_empty_input_can_supply_minimal_valid_coverage(self):
        def probe(values):
            return {
                "case": repr(values),
                "requirement": "return the list length",
                "arguments": [values],
                "expected_value": len(values),
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "direct length",
                "coverage_tags": ["minimal_valid", "singleton"],
                "contrast_group": "",
            }

        task_ir = {
            "signature": "def length(values: List[int]) -> int:",
            "raw_docstring": "Return the input list length; values may be empty.",
            "parameters": [{
                "name": "values",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
            }],
            "return_type": {"kind": "integer", "arguments": []},
            "examples": [],
        }
        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({
                "probes": [probe([]), probe([1]), probe([2])],
            })]),
            problem_desc="full generation prompt",
            entry_point="length",
            max_parse_retries=0,
            task_ir=task_ir,
        )

        self.assertEqual(suite["status"], "generated")
        self.assertIn("minimal_valid", suite["probes"][0]["coverage_tags"])

    def test_generated_probe_cannot_claim_public_example_provenance(self):
        task_ir = {
            "parameters": [{
                "name": "x",
                "dafny_type": {"kind": "integer", "arguments": []},
            }],
            "return_type": {"kind": "integer", "arguments": []},
            "raw_docstring": "Return x.",
            "examples": [],
        }
        probes = {
            "probes": [
                {
                    "case": str(value),
                    "requirement": "return x",
                    "arguments": [value],
                    "expected_value": value,
                    "within_task_domain": True,
                    "expected_source": "public_example",
                    "rationale": "identity",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                }
                for value in (0, 1, -1)
            ]
        }
        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps(probes)]),
            problem_desc="Return x.",
            entry_point="f",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("reserved for deterministic TaskIR extraction", suite["error"])

    def test_empty_output_or_invalid_empty_input_does_not_authorize_empty_probe(self):
        def probe(values):
            return {
                "case": repr(values),
                "requirement": "filter values",
                "arguments": [values],
                "expected_value": [],
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "no values match",
                "coverage_tags": ["minimal_valid", "singleton"],
                "contrast_group": "",
            }

        for docstring in (
            "Return an empty list if no items match.",
            "Empty inputs are invalid.",
        ):
            task_ir = {
                "parameters": [{
                    "name": "values",
                    "dafny_type": {
                        "kind": "sequence",
                        "arguments": [{"kind": "integer", "arguments": []}],
                    },
                }],
                "return_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
                "raw_docstring": docstring,
                "examples": [],
            }
            suite = generate_task_probes_with_llm(
                FakeLLM([json.dumps({
                    "probes": [probe([]), probe([1]), probe([2])],
                })]),
                problem_desc=docstring,
                entry_point="f",
                task_ir=task_ir,
                max_parse_retries=0,
            )
            with self.subTest(docstring=docstring):
                self.assertEqual(suite["status"], "unavailable")
                self.assertIn("too few distinct", suite["error"])

    def test_decisive_last_cannot_be_faked_by_changing_a_scalar_threshold(self):
        task_ir = {
            "parameters": [
                {
                    "name": "operations",
                    "dafny_type": {
                        "kind": "sequence",
                        "arguments": [{"kind": "integer", "arguments": []}],
                    },
                },
                {"name": "threshold", "dafny_type": {"kind": "integer", "arguments": []}},
            ],
            "return_type": {"kind": "boolean", "arguments": []},
            "raw_docstring": "Return true if at any point a prefix balance is below threshold.",
            "examples": [],
        }

        def probe(case, operations, threshold, expected, group=""):
            return {
                "case": case,
                "requirement": "detect the decisive final operation",
                "arguments": [operations, threshold],
                "expected_value": expected,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "boundary comparison",
                "coverage_tags": ["minimal_valid", "singleton", "decisive_last"],
                "contrast_group": group,
            }

        payload = {"probes": [
            probe("negative", [-1], 0, True),
            probe("baseline", [1], 0, False, "fake-last"),
            probe("threshold-only", [1], 1, True, "fake-last"),
        ]}
        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps(payload)]),
            problem_desc="full prompt",
            entry_point="below_threshold",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("decisive_last", suite["error"])

    def test_overlap_coverage_requires_an_actual_overlapping_match(self):
        task_ir = {
            "parameters": [
                {"name": "string", "dafny_type": {"kind": "string", "arguments": []}},
                {"name": "substring", "dafny_type": {"kind": "string", "arguments": []}},
            ],
            "return_type": {"kind": "integer", "arguments": []},
            "raw_docstring": "Count overlapping occurrences of substring in string.",
            "examples": [],
        }

        def probe(case, haystack, needle):
            return {
                "case": case,
                "requirement": "count overlapping occurrences",
                "arguments": [haystack, needle],
                "expected_value": 0,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "the needle is absent",
                "coverage_tags": ["minimal_valid", "singleton", "multiplicity"],
                "contrast_group": "",
            }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [
                probe("repeated but absent", "banana", "zz"),
                probe("minimal one", "a", "b"),
                probe("minimal two", "c", "d"),
            ]})]),
            problem_desc="full prompt",
            entry_point="count_overlap",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("multiplicity", suite["error"])

    def test_large_scalar_values_do_not_fake_minimal_boundary_coverage(self):
        task_ir = {
            "parameters": [{
                "name": "x",
                "dafny_type": {"kind": "integer", "arguments": []},
            }],
            "return_type": {"kind": "integer", "arguments": []},
            "raw_docstring": "Return x.",
            "examples": [],
        }

        def probe(value):
            return {
                "case": str(value),
                "requirement": "return x",
                "arguments": [value],
                "expected_value": value,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "identity",
                "coverage_tags": ["minimal_valid"],
                "contrast_group": "",
            }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [probe(100), probe(101), probe(102)]})]),
            problem_desc="Return x.",
            entry_point="f",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("minimal_valid", suite["error"])

    def test_string_return_type_does_not_create_a_fake_singleton_input_requirement(self):
        task_ir = {
            "parameters": [{
                "name": "n",
                "dafny_type": {"kind": "integer", "arguments": []},
            }],
            "return_type": {"kind": "string", "arguments": []},
            "raw_docstring": (
                "Return a string containing space-delimited numbers from 0 up to n inclusive."
            ),
            "examples": [],
        }

        def probe(value, expected, group=""):
            return {
                "case": str(value),
                "requirement": "include n in the numeric string",
                "arguments": [value],
                "expected_value": expected,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "enumerate zero through n",
                "coverage_tags": ["minimal_valid", "representation", "endpoint"],
                "contrast_group": group,
            }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [
                probe(0, "0"),
                probe(9, "0 1 2 3 4 5 6 7 8 9", "inclusive"),
                probe(10, "0 1 2 3 4 5 6 7 8 9 10", "inclusive"),
            ]})]),
            problem_desc="full prompt",
            entry_point="string_sequence",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "generated")
        covered = {tag for probe in suite["probes"] for tag in probe["coverage_tags"]}
        self.assertNotIn("singleton", covered)
        self.assertIn("endpoint", covered)

    def test_ordering_requirement_needs_a_multi_element_order_sensitive_case(self):
        task_ir = {
            "parameters": [{
                "name": "values",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
            }],
            "return_type": {
                "kind": "sequence",
                "arguments": [{"kind": "integer", "arguments": []}],
            },
            "raw_docstring": "Return the values sorted in ascending order.",
            "examples": [],
        }

        def probe(value):
            return {
                "case": str(value),
                "requirement": "sort ascending",
                "arguments": [[value]],
                "expected_value": [value],
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "a singleton is already sorted",
                "coverage_tags": ["minimal_valid", "singleton", "ordering"],
                "contrast_group": "",
            }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [probe(1), probe(2), probe(3)]})]),
            problem_desc="full prompt",
            entry_point="sort_values",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("ordering", suite["error"])

    def test_already_sorted_inputs_do_not_discriminate_identity_from_sorting(self):
        task_ir = {
            "parameters": [{
                "name": "values",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "integer", "arguments": []}],
                },
            }],
            "return_type": {
                "kind": "sequence",
                "arguments": [{"kind": "integer", "arguments": []}],
            },
            "raw_docstring": "Return values sorted in ascending order.",
            "examples": [],
        }

        def probe(values):
            return {
                "case": repr(values),
                "requirement": "sort ascending",
                "arguments": [values],
                "expected_value": values,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "the supplied case is already sorted",
                "coverage_tags": ["minimal_valid", "singleton", "ordering"],
                "contrast_group": "",
            }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [
                probe([0]), probe([1, 2]), probe([2, 3]),
            ]})]),
            problem_desc="full prompt",
            entry_point="sort_values",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("ordering", suite["error"])

    def test_identical_candidates_do_not_fake_tie_breaking_coverage(self):
        task_ir = {
            "parameters": [{
                "name": "values",
                "dafny_type": {
                    "kind": "sequence",
                    "arguments": [{"kind": "string", "arguments": []}],
                },
            }],
            "return_type": {"kind": "string", "arguments": []},
            "raw_docstring": (
                "Return the longest string; if multiple strings tie at the same length, "
                "return the lexicographically first."
            ),
            "examples": [],
        }

        def probe(case, values, expected):
            return {
                "case": case,
                "requirement": "apply lexical tie-breaking",
                "arguments": [values],
                "expected_value": expected,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "choose the only distinct candidate",
                "coverage_tags": ["minimal_valid", "singleton", "tie"],
                "contrast_group": "",
            }

        suite = generate_task_probes_with_llm(
            FakeLLM([json.dumps({"probes": [
                probe("one", ["a"], "a"),
                probe("identical", ["a", "a"], "a"),
                probe("three", ["bbb"], "bbb"),
            ]})]),
            problem_desc="full prompt",
            entry_point="choose",
            task_ir=task_ir,
            max_parse_retries=0,
        )

        self.assertEqual(suite["status"], "unavailable")
        self.assertIn("tie", suite["error"])

    def test_invalid_cached_probe_suite_is_regenerated(self):
        problem = {
            "task_id": "test/cache",
            "entry_point": "f",
            "prompt": (
                "from typing import List\n"
                "def f(xs: List[int]) -> int:\n"
                "    \"\"\"Return the input list length.\"\"\"\n"
            ),
        }
        task_ir = normalize_humaneval_problem(problem).to_dict()

        def probe(length):
            return {
                "case": f"length-{length}",
                "requirement": "return length",
                "arguments": [list(range(length))],
                "expected_value": length,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "direct length",
                "coverage_tags": ["minimal_valid", "singleton"],
                "contrast_group": "",
            }

        invalid_cache = {
            "status": "generated",
            "attempts": 1,
            "probes": [probe(2), probe(3), probe(4)],
        }
        fresh_probe_llm = FakeLLM([json.dumps({
            "probes": [probe(1), probe(2), probe(3)],
        })])
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(True, {"error": None}),
        ):
            report = review_spec_with_llm(
                FakeLLM([
                    json.dumps(_approval_report_for(([[1]], 1), ([[1, 2]], 2)))
                ]),
                problem_desc="Return the input list length.",
                spec=(
                    "method f(xs: seq<int>) returns (result: int)\n"
                    "  ensures result == |xs|"
                ),
                entry_point="f",
                task_ir=task_ir,
                probe_llm=fresh_probe_llm,
                probe_suite=invalid_cache,
            )

        self.assertEqual(report["decision"], "approve")
        self.assertEqual(len(fresh_probe_llm.calls), 1)
        self.assertEqual(report["generated_probes"][0]["arguments"], [[0]])

    def test_confirmation_label_cannot_contradict_its_rationale(self):
        llm = FakeLLM([json.dumps({
            "decision": "confirm",
            "expected_value": 1.5555555555555556,
            "confidence": 1.0,
            "rationale": (
                "The proposed value 1.5556 is incorrect; the result is 4/3, "
                "so dispute."
            ),
        })])

        confirmation = confirm_probe_expectation_with_llm(
            llm,
            problem_desc="Return mean absolute deviation.",
            entry_point="mean_absolute_deviation",
            arguments=[[1.0, 3.0, 5.0]],
            expected_value=1.5555555555555556,
        )

        self.assertEqual(confirmation["decision"], "abstain")

    def test_confirmation_guard_does_not_invert_explicit_negation(self):
        llm = FakeLLM([json.dumps({
            "decision": "confirm",
            "expected_value": 3,
            "confidence": 0.9,
            "rationale": (
                "The proposed value is not incorrect; there is no reason to "
                "dispute it."
            ),
        })])

        confirmation = confirm_probe_expectation_with_llm(
            llm,
            problem_desc="Return three.",
            entry_point="f",
            arguments=[],
            expected_value=3,
        )

        self.assertEqual(confirmation["decision"], "abstain")

    def test_confirmation_recomputes_without_showing_the_proposed_value(self):
        llm = FakeLLM([json.dumps({
            "decision": "computed",
            "expected_value": 4 / 3,
            "confidence": 1.0,
            "rationale": "The four units of total deviation are averaged over three values.",
        })])

        confirmation = confirm_probe_expectation_with_llm(
            llm,
            problem_desc="Return mean absolute deviation.",
            entry_point="mean_absolute_deviation",
            arguments=[[1.0, 3.0, 5.0]],
            expected_value=1.5555555555555556,
        )

        self.assertEqual(confirmation["decision"], "dispute")
        self.assertNotIn("1.555555", llm.calls[0]["user"])
        self.assertNotIn("Proposed", llm.calls[0]["user"])

    def test_incomplete_computed_confirmation_abstains_instead_of_disputing(self):
        confirmation = confirm_probe_expectation_with_llm(
            FakeLLM([json.dumps({"decision": "computed"})]),
            problem_desc="Return x.",
            entry_point="f",
            arguments=[1],
            expected_value=1,
        )

        self.assertEqual(confirmation["decision"], "abstain")

    def test_protocol_failure_with_public_requires_cannot_use_probe_only_approval(self):
        probes = {
            "probes": [
                {
                    "case": f"case-{value}",
                    "requirement": "return the string length",
                    "arguments": ["x" * value],
                    "expected_value": value,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "direct character count",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                }
                for value in (1, 2, 3)
            ]
        }
        report = review_spec_with_llm(
            FakeLLM(["not json"]),
            problem_desc="Return the length of the input.",
            spec=(
                "method f(s: string) returns (result: int)\n"
                "  requires |s| > 0\n"
                "  ensures result == |s|"
            ),
            entry_point="f",
            max_parse_retries=0,
            probe_llm=FakeLLM([json.dumps(probes)]),
        )

        self.assertEqual(report["decision"], "abstain")
        self.assertTrue(report["audit_protocol_failure"])
        self.assertNotIn("probe_only_gate", report)

    def test_protocol_failure_without_requires_still_abstains(self):
        probes = {
            "probes": [
                {
                    "case": f"case-{value}",
                    "requirement": "return the input",
                    "arguments": [value],
                    "expected_value": value,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "identity behavior",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                }
                for value in (0, 1, 2)
            ]
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(True, {"error": None}),
        ) as execute:
            report = review_spec_with_llm(
                FakeLLM(["not json"]),
                problem_desc="Return x.",
                spec=(
                    "method f(x: int) returns (result: int)\n"
                    "  ensures result == x"
                ),
                entry_point="f",
                max_parse_retries=0,
                probe_llm=FakeLLM([json.dumps(probes)]),
            )

        self.assertEqual(report["decision"], "abstain")
        self.assertNotIn("probe_only_gate", report)
        execute.assert_not_called()

    def test_two_disputed_bad_probes_are_removed_before_approval(self):
        audit_llm = FakeLLM([json.dumps(_report("approve"))])
        probe_llm = FakeLLM([
            json.dumps({
                "decision": "computed",
                "expected_value": 1,
                "confidence": 1.0,
                "rationale": "The identity function returns one for input one.",
            }),
            json.dumps({
                "decision": "computed",
                "expected_value": 2,
                "confidence": 1.0,
                "rationale": "The identity function returns two for input two.",
            }),
        ])
        probe_suite = {
            "status": "generated",
            "attempts": 1,
            "probes": [
                {
                    "case": "bad-one",
                    "requirement": "identity",
                    "arguments": [1],
                    "expected_value": 2,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "bad arithmetic",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                },
                {
                    "case": "bad-two",
                    "requirement": "identity",
                    "arguments": [2],
                    "expected_value": 3,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "bad arithmetic",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                },
                {
                    "case": "good",
                    "requirement": "identity",
                    "arguments": [3],
                    "expected_value": 3,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "correct identity result",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                },
            ],
        }
        executions = [
            (False, {
                "error": "mismatch",
                "failing_input": [1],
                "actual": 1,
                "assertions_passed": 0,
            }),
            (False, {
                "error": "mismatch",
                "failing_input": [2],
                "actual": 2,
                "assertions_passed": 0,
            }),
            (True, {"error": None}),
        ]
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test", side_effect=executions
        ) as execute:
            report = review_spec_with_llm(
                audit_llm,
                problem_desc="Return x.",
                spec=(
                    "method f(x: int) returns (result: int)\n"
                    "  ensures result == x"
                ),
                entry_point="f",
                max_parse_retries=0,
                probe_llm=probe_llm,
                probe_suite=probe_suite,
            )

        self.assertEqual(report["decision"], "approve")
        self.assertEqual(len(report["discarded_probe_conflicts"]), 2)
        self.assertEqual(execute.call_count, 3)

    def test_confirmed_probe_mismatch_becomes_structured_repair_evidence(self):
        probe_suite = {
            "status": "generated",
            "attempts": 1,
            "probes": [
                {
                    "case": f"case-{value}",
                    "requirement": "return twice the input",
                    "arguments": [value],
                    "expected_value": value * 2,
                    "within_task_domain": True,
                    "expected_source": "task_text",
                    "rationale": "doubling",
                    "coverage_tags": ["minimal_valid"],
                    "contrast_group": "",
                }
                for value in (1, 2, 3)
            ],
        }
        confirmation_llm = FakeLLM([json.dumps({
            "decision": "computed",
            "expected_value": 2,
            "confidence": 1.0,
            "rationale": "Twice one is two.",
        })])
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(False, {
                "error": "mismatch",
                "failing_input": [1],
                "actual": 1,
                "assertions_passed": 0,
            }),
        ):
            report = review_spec_with_llm(
                FakeLLM([json.dumps(_report("approve"))]),
                problem_desc="Return twice x.",
                spec="method f(x: int) returns (result: int) ensures result == x",
                entry_point="f",
                max_parse_retries=0,
                probe_llm=confirmation_llm,
                probe_suite=probe_suite,
            )

        self.assertEqual(report["decision"], "reject")
        self.assertEqual(report["issues"][-1]["severity"], "critical")
        self.assertEqual(report["counterexamples"][-1]["arguments"], [1])
        self.assertEqual(report["counterexamples"][-1]["expected_value"], 2)

    def test_executed_probe_overturns_false_approval(self):
        report = _report("approve")
        probe = {
            "case": "negative singleton",
            "arguments": [[-1]],
            "expected_value": True,
            "within_task_domain": True,
            "expected_source": "public_example",
            "probe_origin": "public_example",
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(
                False,
                {
                    "error": "mismatch",
                    "failing_input": [[-1]],
                    "expected": True,
                    "actual": False,
                },
            ),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="below_zero",
                additional_checks=[probe],
            )
        self.assertEqual(checked["decision"], "reject")
        self.assertEqual(checked["executable_boundary_checks"]["status"], "failed")
        self.assertIn("executing", checked["counterexamples"][-1]["rationale"])

    def test_executable_comparator_does_not_treat_bool_as_int(self):
        report = _report("approve", boundary_checks=[])
        probe = {
            "case": "integer one",
            "arguments": [0],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "public_example",
            "probe_origin": "public_example",
        }

        def execute_generated_test(_code, problem):
            namespace = {}
            exec(problem["test"], namespace)
            try:
                namespace["check"](lambda _value: True)
            except AssertionError:
                return False, {
                    "error": "mismatch",
                    "failing_input": [0],
                    "expected": 1,
                    "actual": True,
                    "assertions_passed": 0,
                }
            return True, {"error": None}

        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            side_effect=execute_generated_test,
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[probe],
            )

        self.assertEqual(checked["decision"], "reject")
        self.assertEqual(checked["executable_boundary_checks"]["status"], "failed")

    def test_approving_audit_boundaries_are_not_treated_as_independent_probes(self):
        report = _report("approve", boundary_checks=[{
            "case": "mis-serialized critic trace",
            "arguments": ['"abc"'],
            "expected_value": ["a", "ab", "abc"],
            "within_task_domain": True,
            "expected_source": "task_text",
        }])
        public_probe = {
            "case": "public",
            "arguments": ["abc"],
            "expected_value": ["a", "ab", "abc"],
            "within_task_domain": True,
            "expected_source": "public_example",
            "probe_origin": "public_example",
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(True, {"error": None}),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="all_prefixes",
                additional_checks=[public_probe],
            )

        self.assertEqual(checked["decision"], "approve")
        self.assertEqual(checked["executable_boundary_checks"]["checks_run"], 1)

    def test_public_examples_are_injected_deterministically(self):
        task_ir = {
            "examples": [{
                "call_name": "f",
                "positional_args": ([1, 2],),
                "keyword_args": (),
                "arguments_are_literal": True,
                "expected_value": (1, 2),
                "expected_is_literal": True,
            }]
        }
        probes = public_example_probes(task_ir, entry_point="f")
        self.assertEqual(probes[0]["arguments"], [[1, 2]])
        self.assertEqual(probes[0]["expected_value"], [1, 2])
        self.assertEqual(probes[0]["expected_source"], "public_example")

    def test_infrastructure_failure_abstains_instead_of_semantic_reject(self):
        report = _report("approve")
        probe = {
            "case": "timeout",
            "arguments": [1],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "task_text",
            "probe_origin": "nl_generated",
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(False, {"error": "执行超时", "failing_input": None}),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[probe],
            )
        self.assertEqual(checked["decision"], "abstain")
        self.assertEqual(checked["executable_boundary_checks"]["status"], "execution_error")

    def test_unstructured_execution_exception_and_nonnumeric_progress_abstain(self):
        report = _report("approve")
        public_probe = {
            "case": "public identity",
            "arguments": [1],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "public_example",
            "probe_origin": "public_example",
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(False, {
                "error": "测试执行异常: OSError",
                "assertions_passed": "N/A",
            }),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[public_probe],
            )

        self.assertEqual(checked["decision"], "abstain")
        self.assertEqual(checked["executable_boundary_checks"]["status"], "execution_error")

    def test_deterministically_invalid_executable_spec_routes_to_repair(self):
        report = _report("approve")
        probe = {
            "case": "identity",
            "arguments": [1],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "task_text",
            "probe_origin": "nl_generated",
        }
        syntax_error = SimpleNamespace(
            error_type="syntax",
            subtype="syntax",
            message="invalid statement in function body",
            location_line=4,
        )
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(
                passed=False,
                error_count=1,
                errors=[syntax_error],
            ),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[probe],
            )

        self.assertEqual(checked["decision"], "reject")
        self.assertEqual(checked["executable_boundary_checks"]["status"], "not_executable")
        self.assertEqual(checked["issues"][-1]["category"], "dafny_validity")
        self.assertIn("invalid statement", checked["issues"][-1]["explanation"])

    def test_dafny_timeout_while_preparing_spec_remains_abstain(self):
        report = _report("approve")
        probe = {
            "case": "identity",
            "arguments": [1],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "task_text",
            "probe_origin": "nl_generated",
        }
        timeout = SimpleNamespace(
            error_type="timeout",
            subtype="timeout",
            message="Dafny command timed out",
            location_line=0,
        )
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(
                passed=False,
                error_count=1,
                errors=[timeout],
            ),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[probe],
            )

        self.assertEqual(checked["decision"], "abstain")
        self.assertEqual(checked["executable_boundary_checks"]["status"], "execution_error")

    def test_single_nl_probe_mismatch_requires_confirmation(self):
        report = _report("approve")
        probe = {
            "case": "generated",
            "arguments": [1],
            "expected_value": 2,
            "within_task_domain": True,
            "expected_source": "task_text",
            "probe_origin": "nl_generated",
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(False, {
                "error": "mismatch",
                "failing_input": [1],
                "expected": None,
                "actual": 1,
                "assertions_passed": 0,
            }),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[probe],
            )
        self.assertEqual(checked["decision"], "abstain")
        self.assertEqual(checked["pending_probe_conflict"]["expected"], 2)

    def test_deduplicated_counterexample_still_counts_as_replayed(self):
        counterexample = {
            "input": "[1]",
            "arguments": [[1]],
            "expected": 1,
            "expected_value": 1,
            "spec_behavior": 0,
            "rationale": "claimed mismatch",
            "within_task_domain": True,
            "expected_source": "task_text",
            "matches_spec": False,
        }
        report = _report(
            "reject",
            counterexamples=[counterexample],
            probe_generation={"status": "generated"},
        )
        public_copy = {
            "case": "public",
            "arguments": [[1]],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "public_example",
            "probe_origin": "public_example",
        }
        critic_copy = {
            "case": "critic_counterexample",
            "arguments": [[1]],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "task_text",
            "probe_origin": "critic_counterexample",
        }
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(True, {"error": None}),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[public_copy, critic_copy],
            )

        self.assertEqual(checked["decision"], "abstain")
        self.assertTrue(checked["provisional_audit_rejection_overturned"])
        self.assertTrue(checked["needs_reconciliation_audit"])

    def test_required_reject_evidence_is_batched_without_truncation(self):
        counterexample = {
            "input": "1",
            "arguments": [1],
            "expected": 1,
            "expected_value": 1,
            "spec_behavior": 0,
            "rationale": "first claimed mismatch",
            "within_task_domain": True,
            "expected_source": "task_text",
            "matches_spec": False,
        }
        report = _report(
            "reject",
            counterexamples=[counterexample],
            boundary_checks=[{
                "case": "second claimed mismatch",
                "arguments": [2],
                "expected_value": 2,
                "matches": False,
                "within_task_domain": True,
                "expected_source": "task_text",
            }],
            probe_generation={"status": "generated"},
        )
        counterexample_check = {
            "case": "critic counterexample",
            "arguments": [1],
            "expected_value": 1,
            "within_task_domain": True,
            "expected_source": "task_text",
            "probe_origin": "critic_counterexample",
        }
        with patch.object(config, "MAX_EXECUTED_CRITIC_PROBES", 1), patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(True, {"error": None}),
        ):
            checked = execute_approved_boundary_checks(
                report,
                spec="spec",
                entry_point="f",
                additional_checks=[counterexample_check],
            )

        self.assertEqual(checked["decision"], "abstain")
        self.assertEqual(
            checked["executable_boundary_checks"]["required_reject_evidence_missing"],
            0,
        )
        self.assertEqual(checked["executable_boundary_checks"]["batches_run"], 2)
        self.assertNotIn("provisional_audit_rejection_overturned", checked)

    def test_disputed_reject_evidence_does_not_displace_the_next_required_case(self):
        counterexamples = [
            {
                "input": "1",
                "arguments": [1],
                "expected": 10,
                "expected_value": 10,
                "spec_behavior": 1,
                "rationale": "the audit incorrectly claims a tenfold result",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            },
            {
                "input": "2",
                "arguments": [2],
                "expected": 2,
                "expected_value": 2,
                "spec_behavior": 0,
                "rationale": "the audit also claims the identity case fails",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            },
        ]
        rejected = _report(
            "reject",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "high",
                "material": True,
                "requirement": "return the input",
                "spec_location": "Reference",
                "explanation": "the audit claims two concrete identity failures",
            }],
            counterexamples=counterexamples,
        )

        def generated_probe(value):
            return {
                "case": f"identity-{value}",
                "requirement": "return the input",
                "arguments": [value],
                "expected_value": value,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "the function is the identity",
                "coverage_tags": ["minimal_valid"],
                "contrast_group": "",
            }

        probe_payload = {
            "probes": [generated_probe(3), generated_probe(4), generated_probe(5)]
        }
        confirmation = {
            "decision": "computed",
            "expected_value": 1,
            "confidence": 0.99,
            "rationale": "The task returns its input, so argument 1 produces 1.",
        }
        probe_llm = FakeLLM([json.dumps(probe_payload), json.dumps(confirmation)])
        executed_tests = []

        def run_probe(_code, problem):
            executed_tests.append(problem["test"])
            if len(executed_tests) == 1:
                return False, {
                    "error": "mismatch",
                    "failing_input": [1],
                    "expected": 10,
                    "actual": 1,
                    "assertions_passed": 0,
                }
            return True, {"error": None}

        critic_llm = FakeLLM([
            json.dumps(rejected),
            json.dumps(_approval_report_for(([3], 3))),
        ])
        with patch.object(config, "MAX_EXECUTED_CRITIC_PROBES", 1), patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test", side_effect=run_probe
        ):
            report = review_spec_with_llm(
                critic_llm,
                problem_desc="Return x.",
                spec="method f(x: int) returns (result: int) ensures result == x",
                entry_point="f",
                probe_llm=probe_llm,
                review_passes=1,
                max_parse_retries=0,
            )

        self.assertEqual(report["decision"], "approve")
        self.assertTrue(report["audit_rejection_overturned"])
        self.assertEqual(len(executed_tests), 5)
        self.assertIn("candidate(1), 10", executed_tests[0])
        self.assertIn("candidate(2), 2", executed_tests[1])
        self.assertNotIn("candidate(1), 10", executed_tests[1])
        self.assertTrue(any("candidate(3), 3" in code for code in executed_tests[2:]))
        self.assertEqual(
            report["executable_boundary_checks"]["required_reject_evidence_missing"],
            0,
        )

    def test_disproving_one_reject_case_does_not_replace_fresh_positive_audit(self):
        initial_reject = _report(
            "reject",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "high",
                "material": True,
                "requirement": "return x for every integer",
                "spec_location": "Reference",
                "explanation": "the helper is allegedly wrong on a concrete input",
            }],
            counterexamples=[{
                "input": "1",
                "arguments": [1],
                "expected": 1,
                "expected_value": 1,
                "spec_behavior": 0,
                "rationale": "claimed mismatch at one",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            }],
        )
        fresh_reject = _report(
            "reject",
            issues=[{
                "category": "semantic_mismatch",
                "severity": "critical",
                "material": True,
                "requirement": "return x for every integer",
                "spec_location": "Reference base case",
                "explanation": "a distinct zero-input defect remains",
            }],
            counterexamples=[{
                "input": "0",
                "arguments": [0],
                "expected": 0,
                "expected_value": 0,
                "spec_behavior": 1,
                "rationale": "zero is mapped to one",
                "within_task_domain": True,
                "expected_source": "task_text",
                "matches_spec": False,
            }],
        )

        def probe(value):
            return {
                "case": str(value),
                "requirement": "return x",
                "arguments": [value],
                "expected_value": value,
                "within_task_domain": True,
                "expected_source": "task_text",
                "rationale": "identity",
                "coverage_tags": ["minimal_valid"],
                "contrast_group": "",
            }

        critic_llm = FakeLLM([
            json.dumps(initial_reject),
            json.dumps(fresh_reject),
        ])
        probe_llm = FakeLLM([json.dumps({
            "probes": [probe(1), probe(2), probe(3)],
        })])
        with patch(
            "contract_utils.build_direct_reference_program", return_value="candidate"
        ), patch(
            "dafny_wrapper.DafnyVerifier.verify",
            return_value=SimpleNamespace(passed=True, error_count=0),
        ), patch(
            "humaneval_tester.run_humaneval_test",
            return_value=(True, {"error": None}),
        ):
            report = review_spec_with_llm(
                critic_llm,
                problem_desc="Return x.",
                spec="method f(x: int) returns (result: int) ensures result == x",
                entry_point="f",
                probe_llm=probe_llm,
                review_passes=1,
                max_parse_retries=0,
            )

        self.assertEqual(report["decision"], "abstain")
        self.assertEqual(report["reconciliation_audit"]["decision"], "reject")
        self.assertNotIn("audit_rejection_overturned", report)

    def test_pipeline_gate_repairs_rejection_then_abstains_at_budget(self):
        state = {"spec_critic": _report("reject"), "critic_repair_rounds": 0}
        with patch.object(pipeline.config, "ENABLE_SPEC_CRITIC", True), patch.object(
            pipeline.config, "MAX_CRITIC_REPAIR_ROUNDS", 1
        ):
            self.assertEqual(pipeline.decide_after_critic(state), "repair")
            state["critic_repair_rounds"] = 1
            self.assertEqual(pipeline.decide_after_critic(state), "end")
            state["spec_critic"] = _report("abstain")
            self.assertEqual(pipeline.decide_after_critic(state), "end")

    def test_mutation_strengthening_has_a_bounded_retry(self):
        state = {
            "mutation_adequacy": {"mutants_verified": 1},
            "mutation_strengthening_attempts": 0,
        }
        with patch.object(pipeline.config, "ENABLE_MUTATION_SPEC_STRENGTHENING", True), patch.object(
            pipeline.config, "MAX_MUTATION_STRENGTHENING_ROUNDS", 1
        ):
            self.assertEqual(pipeline.decide_after_mutation(state), "strengthen_spec")
            state["mutation_strengthening_attempts"] = 1
            self.assertEqual(pipeline.decide_after_mutation(state), "critic")

    def test_compiled_graph_rejection_stops_before_code_generation(self):
        rejected = _report("reject")
        calls = []

        def node(name, update):
            def run(_state):
                calls.append(name)
                return update
            return run

        with patch.object(pipeline.config, "ENABLE_SPEC_CRITIC", True), patch.object(
            pipeline.config, "MAX_CRITIC_REPAIR_ROUNDS", 0
        ), patch.object(
            pipeline, "spec_agent", node("spec", {"spec": "candidate"})
        ), patch.object(
            pipeline, "spec_repair_agent", node("spec_repair", {})
        ), patch.object(
            pipeline,
            "mutation_adequacy_node",
            node("mutation", {"mutation_adequacy": {"mutants_verified": 0}}),
        ), patch.object(
            pipeline,
            "spec_critic_agent",
            node("critic", {"spec_critic": rejected, "critic_gate_status": "rejected"}),
        ), patch.object(
            pipeline, "code_agent", node("code", {"code": "must not run"})
        ):
            final = pipeline.build_pipeline().invoke(self._graph_state())

        self.assertEqual(calls, ["spec", "spec_repair", "mutation", "critic"])
        self.assertEqual(final["critic_gate_status"], "rejected")
        self.assertEqual(final["code"], "")


if __name__ == "__main__":
    unittest.main()
