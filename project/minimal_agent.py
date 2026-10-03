"""Single-spec, single-candidate experiment. No planner, critic, search or repair."""

from dataclasses import asdict
import json
import re

from budget import BudgetExceeded, BudgetLedger, BudgetLimits, BudgetedVerifier, budget_scope
from spec_compiler import PROFILE, UnsupportedTask, check_task, compile_spec, schema
from spec_ir import SpecIRValidationError
from task_normalizer import TaskIR, render_dafny_signature


DIRECT = "direct_minimal_v1"
SPEC_SYSTEM = """Translate the public task to the given typed specification JSON schema.
Return exactly one JSON object. Define the result for the full public input domain.
You may use only the listed operators. Never add preconditions or write source code."""
CODE_SYSTEM = """Implement the public task in Dafny. Return only the statements inside
the method body, without enclosing braces, markdown, comments or strings.
The supplied signature and contract are frozen and added by the runner.
Do not declare methods/functions, call helpers, add attributes, assume facts,
or disable termination checking. You may use local variables, branches, loops,
assertions and loop invariants. Produce one implementation only."""


def assemble_candidate(contract: str, body: str) -> str:
    """Enclose a restricted body in the *exact* trusted contract.

    This intentionally narrow lexical policy is not a general Dafny parser.
    Dafny checks syntax and semantics after this containment check.
    """
    if not isinstance(body, str) or not body.strip() or len(body) > 32000:
        raise ValueError("candidate body must contain 1..32000 characters")
    token = re.compile(r"\s+|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|:=|:|&&|\|\||==|!=|<=|>=|==>|[{}()\[\];,.+*<>!=|\-]")
    tokens = []
    pos = 0
    while pos < len(body):
        match = token.match(body, pos)
        if match is None:
            raise ValueError("candidate uses syntax outside the v0.1 body subset")
        item = match.group()
        if not item.isspace():
            tokens.append(item)
        pos = match.end()
    forbidden = {
        "assume", "expect", "method", "function", "lemma", "predicate", "class",
        "module", "import", "include", "datatype", "type", "newtype", "iterator",
        "ghost", "extern", "axiom", "requires", "ensures", "modifies", "reads",
    }
    if forbidden.intersection(tokens):
        raise ValueError("candidate contains a forbidden declaration or proof escape")
    depth = 0
    for index, item in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if (item, following) in {("{", ":"), ("decreases", "*"), (":", "|"), (":=", "*")}:
            raise ValueError("attributes, unchecked termination and nondeterminism are excluded")
        if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", item) and following == "(":
            if item not in {"if", "while", "assert", "return"}:
                raise ValueError("method/function calls are excluded in v0.1 candidates")
        depth += (item == "{") - (item == "}")
        if depth < 0:
            raise ValueError("candidate escapes the frozen method body")
    if depth:
        raise ValueError("candidate has unbalanced braces")
    return contract.rstrip() + "\n{\n" + body.strip() + "\n}\n"


class MinimalAgent:
    def __init__(self, *, spec_model, code_model, verifier, condition=PROFILE):
        if condition not in {PROFILE, DIRECT}:
            raise ValueError(f"unknown minimal condition: {condition}")
        self.spec_model = spec_model
        self.code_model = code_model
        self.verifier = BudgetedVerifier(verifier)
        self.condition = condition

    def run(self, task: TaskIR) -> dict:
        # TaskIR has no official tests/canonical solution or holdout callback.
        ledger = BudgetLedger(BudgetLimits(
            max_model_calls=2, max_verifier_calls=3, max_candidates=1,
            max_total_tokens=16000, max_wall_seconds=180,
        ))
        result = {
            "protocol": PROFILE, "condition_id": self.condition, "task_id": task.task_id,
            "status": "not_started", "dafny_verified": False,
            "semantic_correctness": "unknown", "holdout": {"status": "not_run"},
            "task_ir": task.to_dict(), "evidence": {}, "artifacts": {},
        }
        stage = "task"
        with budget_scope(ledger):
            try:
                check_task(task)
                if self.condition == PROFILE:
                    stage = "spec_generation"
                    prompt = {
                        "public_task": task.prompt,
                        "interface": render_dafny_signature(task), "schema": schema(),
                    }
                    raw = self._chat(self.spec_model, SPEC_SYSTEM, json.dumps(prompt), ledger)
                    result["artifacts"]["spec_response"] = raw
                    stage = "spec_compile"
                    spec = compile_spec(json.loads(raw), task)
                    result["evidence"]["typed_ir"] = {"status": "passed"}
                    result["artifacts"].update({
                        "spec_ir": spec.ir.to_dict(), "contract": spec.contract,
                        "reference_program": spec.reference_program,
                        "examples_program": spec.examples_program,
                    })
                    stage = "reference_verify"
                    reference = self.verifier.verify(spec.reference_program)
                    result["evidence"]["reference_totality"] = asdict(reference)
                    if not reference.passed:
                        result["status"] = "reference_rejected"
                        return result
                    stage = "public_examples"
                    example_evidence = {
                        "checked": spec.examples_checked, "skipped": spec.examples_skipped,
                        "status": "not_run",
                    }
                    result["evidence"]["public_examples"] = example_evidence
                    if not spec.examples_checked or spec.examples_skipped:
                        result["status"] = "insufficient_public_evidence"
                        return result
                    checked = self.verifier.verify(spec.examples_program)
                    example_evidence.update({
                        "status": "passed" if checked.passed else "failed",
                        "verification": asdict(checked),
                    })
                    if not checked.passed:
                        result["status"] = "public_examples_rejected"
                        return result
                    contract = spec.contract
                else:
                    contract = render_dafny_signature(task)
                    result["artifacts"]["contract"] = contract
                stage = "code_generation"
                body = self._chat(
                    self.code_model, CODE_SYSTEM,
                    json.dumps({"public_task": task.prompt, "frozen_contract": contract}), ledger,
                )
                result["artifacts"]["code_response"] = body
                stage = "candidate_policy"
                code = assemble_candidate(contract, body)
                ledger.record_candidate()
                result["artifacts"]["code"] = code
                stage = "candidate_verify"
                checked = self.verifier.verify(code)
                result["evidence"]["candidate"] = asdict(checked)
                result["dafny_verified"] = checked.passed
                result["status"] = "verified" if checked.passed else "candidate_rejected"
            except UnsupportedTask as exc:
                result.update(status="unsupported", error=str(exc))
            except BudgetExceeded as exc:
                result.update(status="budget_exhausted", error=exc.reason)
            except (SpecIRValidationError, ValueError, TypeError, RecursionError) as exc:
                result.update(status=f"{stage}_rejected", error=str(exc))
            except Exception as exc:
                # Provider exceptions may embed request/credential details.
                result.update(status=f"{stage}_error", error=type(exc).__name__)
            finally:
                result["last_stage"] = stage
                result["budget"] = ledger.snapshot()
        return result

    @staticmethod
    def _chat(model, system, user, ledger):
        ledger.before_model_call()
        before = ledger.model_calls
        try:
            return model.chat(system=system, user=user, temperature=0.0, max_tokens=4096)
        finally:
            # LLMClient accounts for real API calls; replay/fakes account here.
            if ledger.model_calls == before:
                ledger.record_model_call()
