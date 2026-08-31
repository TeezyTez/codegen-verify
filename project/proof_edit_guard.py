"""Reject proof-only repairs that silently change executable behavior."""

from __future__ import annotations

from difflib import SequenceMatcher
import re


_PROOF_LINE = re.compile(
    r"^(?:invariant\b|decreases\b|assert\b|assume\b|reveal\b|calc\b|ghost\b|lemma\b|\{|\})"
)


def proof_edit_issues(before: str, after: str) -> tuple[str, ...]:
    """Allow only annotation/ghost-line edits; executable edits are fail-closed."""

    old = (before or "").splitlines()
    new = (after or "").splitlines()
    issues: list[str] = []
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed = [*old[i1:i2], *new[j1:j2]]
        unsafe = [line.strip() for line in changed if line.strip() and not _PROOF_LINE.match(line.strip())]
        if unsafe:
            issues.append("proof repair changed executable text: " + " | ".join(unsafe[:3]))
    return tuple(issues)

