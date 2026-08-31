import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from budget import BudgetExceeded, BudgetLedger, BudgetLimits, BudgetedVerifier, budget_scope


class FakeVerifier:
    def verify(self, code):
        return code

    def resolve(self, code):
        return code


def test_budget_ledger_enforces_each_hard_boundary():
    ledger = BudgetLedger(BudgetLimits(max_model_calls=1, max_verifier_calls=1, max_candidates=1))
    ledger.before_model_call()
    ledger.record_model_call(total_tokens=4)
    with pytest.raises(BudgetExceeded, match="max_model_calls"):
        ledger.before_model_call()

    ledger.record_candidate()
    with pytest.raises(BudgetExceeded, match="max_candidates"):
        ledger.record_candidate()


def test_budgeted_verifier_is_transparent_and_counted():
    ledger = BudgetLedger(BudgetLimits(max_verifier_calls=1))
    verifier = BudgetedVerifier(FakeVerifier())
    with budget_scope(ledger):
        assert verifier.verify("program") == "program"
        with pytest.raises(BudgetExceeded, match="max_verifier_calls"):
            verifier.resolve("program")
    assert ledger.snapshot()["verifier_calls"] == 1

