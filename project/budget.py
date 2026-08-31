"""One hard, serializable resource boundary for every agent condition."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import time
from typing import Iterator


@dataclass(frozen=True)
class BudgetLimits:
    """Zero means unlimited; positive values are hard upper bounds."""

    max_model_calls: int = 0
    max_total_tokens: int = 0
    max_verifier_calls: int = 0
    max_wall_seconds: float = 0.0
    max_candidates: int = 0


class BudgetExceeded(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(f"experiment budget exhausted: {reason}")
        self.reason = reason


class BudgetLedger:
    """Account for expensive operations without exposing provider details upstream."""

    def __init__(self, limits: BudgetLimits | None = None):
        self.limits = limits or BudgetLimits()
        self.started = time.perf_counter()
        self.model_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.verifier_calls = 0
        self.candidates = 0
        self.stop_reason = ""

    def _fail(self, reason: str) -> None:
        self.stop_reason = reason
        raise BudgetExceeded(reason)

    def _check_wall_time(self) -> None:
        limit = self.limits.max_wall_seconds
        if limit > 0 and self.elapsed_seconds >= limit:
            self._fail("max_wall_seconds")

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.perf_counter() - self.started)

    def before_model_call(self) -> None:
        self._check_wall_time()
        if self.limits.max_model_calls > 0 and self.model_calls >= self.limits.max_model_calls:
            self._fail("max_model_calls")
        if self.limits.max_total_tokens > 0 and self.total_tokens >= self.limits.max_total_tokens:
            self._fail("max_total_tokens")

    def record_model_call(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        self.model_calls += 1
        self.prompt_tokens += max(0, int(prompt_tokens or 0))
        self.completion_tokens += max(0, int(completion_tokens or 0))
        measured = int(total_tokens or 0)
        self.total_tokens += max(0, measured or prompt_tokens + completion_tokens)

    def before_verifier_call(self) -> None:
        self._check_wall_time()
        if self.limits.max_verifier_calls > 0 and self.verifier_calls >= self.limits.max_verifier_calls:
            self._fail("max_verifier_calls")

    def record_verifier_call(self) -> None:
        self.verifier_calls += 1

    def record_candidate(self) -> None:
        self._check_wall_time()
        if self.limits.max_candidates > 0 and self.candidates >= self.limits.max_candidates:
            self._fail("max_candidates")
        self.candidates += 1

    def snapshot(self) -> dict:
        return {
            "limits": asdict(self.limits),
            "model_calls": self.model_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "verifier_calls": self.verifier_calls,
            "candidates": self.candidates,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "stop_reason": self.stop_reason,
        }


_ACTIVE_LEDGER: ContextVar[BudgetLedger | None] = ContextVar("active_budget_ledger", default=None)


def current_budget() -> BudgetLedger | None:
    return _ACTIVE_LEDGER.get()


@contextmanager
def budget_scope(ledger: BudgetLedger | None) -> Iterator[None]:
    token = _ACTIVE_LEDGER.set(ledger)
    try:
        yield
    finally:
        _ACTIVE_LEDGER.reset(token)


class BudgetedVerifier:
    """Transparent verifier adapter so all resolve/verify calls share one ledger."""

    def __init__(self, verifier):
        self._verifier = verifier

    def _call(self, method: str, *args, **kwargs):
        ledger = current_budget()
        if ledger:
            ledger.before_verifier_call()
        try:
            return getattr(self._verifier, method)(*args, **kwargs)
        finally:
            if ledger:
                ledger.record_verifier_call()

    def verify(self, *args, **kwargs):
        return self._call("verify", *args, **kwargs)

    def resolve(self, *args, **kwargs):
        return self._call("resolve", *args, **kwargs)

