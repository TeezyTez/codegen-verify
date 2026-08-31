"""Bounded, deduplicated search state for generated Dafny candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from artifacts import VerificationEvidence


@dataclass
class CandidateState:
    id: str
    code: str
    depth: int
    parent_id: str = ""
    repair_kind: str = "generation"
    evidence: VerificationEvidence | None = None


class CandidatePool:
    def __init__(self, *, max_candidates: int = 0):
        self._max_candidates = max(0, max_candidates)
        self._items: dict[str, CandidateState] = {}

    def offer(
        self,
        code: str,
        *,
        depth: int,
        parent_id: str = "",
        repair_kind: str = "generation",
    ) -> CandidateState | None:
        candidate_id = hashlib.sha256((code or "").encode("utf-8")).hexdigest()[:16]
        if candidate_id in self._items:
            return None
        if self._max_candidates and len(self._items) >= self._max_candidates:
            return None
        item = CandidateState(candidate_id, code, depth, parent_id, repair_kind)
        self._items[candidate_id] = item
        return item

    def record(self, candidate_id: str, evidence: VerificationEvidence) -> None:
        self._items[candidate_id].evidence = evidence

    def best(self) -> CandidateState | None:
        measured = [item for item in self._items.values() if item.evidence is not None]
        return max(measured, key=lambda item: item.evidence.quality) if measured else None

    def snapshot(self) -> list[dict]:
        return [
            {
                "candidate_id": item.id,
                "parent_id": item.parent_id,
                "depth": item.depth,
                "repair_kind": item.repair_kind,
                "quality": list(item.evidence.quality) if item.evidence else [],
                "passed": bool(item.evidence and item.evidence.passed),
            }
            for item in self._items.values()
        ]

