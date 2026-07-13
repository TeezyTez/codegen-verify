"""Utilities for keeping generated Dafny code bound to a frozen contract.

The pipeline stores a specification separately from the generated program.  A
repair is only meaningful when the program that is sent to Dafny still carries
the same public method signature and contract.  This module performs a small,
purpose-built parse of the public method contract and compares contracts modulo
parameter renaming and insignificant whitespace.

It intentionally does not try to parse all of Dafny.  The supported surface is
the one emitted by this project: a ``method`` declaration followed by zero or
more ``requires``/``ensures`` clauses and, for implementations, a method body.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_DECLARATION_RE = re.compile(
    r"^\s*(?:ghost\s+)?(?:method|function|predicate|lemma|class|datatype|module)\b"
)


@dataclass(frozen=True)
class DafnyParam:
    name: str
    typ: str


@dataclass(frozen=True)
class MethodContract:
    name: str
    params: tuple[DafnyParam, ...]
    returns: tuple[DafnyParam, ...]
    requires: tuple[str, ...]
    ensures: tuple[str, ...]

    @property
    def signature_types(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return (
            tuple(_normalize_type(param.typ) for param in self.params),
            tuple(_normalize_type(param.typ) for param in self.returns),
        )


@dataclass(frozen=True)
class ContractFidelity:
    ok: bool
    issues: tuple[str, ...]
    expected: MethodContract | None = None
    candidate: MethodContract | None = None


def parse_method_contract(source: str, method_name: str = "") -> MethodContract | None:
    """Extract one public method signature and its requires/ensures clauses."""
    source = source or ""
    method_match = _find_method(source, method_name)
    if method_match is None:
        return None

    name = method_match.group(1)
    open_paren = source.find("(", method_match.start())
    close_paren = _matching_delimiter(source, open_paren, "(", ")")
    if open_paren < 0 or close_paren < 0:
        return None

    params = tuple(_parse_params(source[open_paren + 1 : close_paren]))
    cursor = close_paren + 1
    returns: tuple[DafnyParam, ...] = ()
    returns_match = re.match(r"\s*returns\s*", source[cursor:])
    if returns_match:
        returns_open = source.find("(", cursor + returns_match.end())
        returns_close = _matching_delimiter(source, returns_open, "(", ")")
        if returns_open < 0 or returns_close < 0:
            return None
        returns = tuple(_parse_params(source[returns_open + 1 : returns_close]))
        cursor = returns_close + 1

    contract_text = _contract_tail(source, cursor)
    requires, ensures = _parse_clauses(contract_text)
    return MethodContract(
        name=name,
        params=params,
        returns=returns,
        requires=tuple(requires),
        ensures=tuple(ensures),
    )


def check_contract_fidelity(
    expected_source: str,
    candidate_source: str,
    method_name: str = "",
) -> ContractFidelity:
    """Require the candidate to carry exactly the frozen public contract.

    Parameter and return variable names may be alpha-renamed.  ``requires
    true`` is ignored because it is semantically identical to no precondition.
    Other added preconditions are rejected: they silently shrink the source
    program's input domain.  Added postconditions are also rejected so the
    state specification and the verified program cannot drift apart.
    """
    expected = parse_method_contract(expected_source, method_name)
    candidate_name = method_name or (expected.name if expected else "")
    candidate = parse_method_contract(candidate_source, candidate_name)
    issues: list[str] = []

    if expected is None:
        return ContractFidelity(False, ("unable to parse frozen method contract",), None, candidate)
    if candidate is None:
        return ContractFidelity(False, (f"candidate is missing method `{expected.name}`",), expected, None)

    if candidate.name != expected.name:
        issues.append(f"method name changed: {expected.name} -> {candidate.name}")
    if candidate.signature_types != expected.signature_types:
        issues.append(
            "method parameter/return types changed: "
            f"{expected.signature_types!r} -> {candidate.signature_types!r}"
        )

    expected_names = [param.name for param in (*expected.params, *expected.returns)]
    candidate_names = [param.name for param in (*candidate.params, *candidate.returns)]
    rename = {
        candidate_name: expected_name
        for candidate_name, expected_name in zip(candidate_names, expected_names)
    }

    expected_requires = _canonical_clause_set(expected.requires, {})
    candidate_requires = _canonical_clause_set(candidate.requires, rename)
    expected_ensures = _canonical_clause_set(expected.ensures, {})
    candidate_ensures = _canonical_clause_set(candidate.ensures, rename)

    missing_requires = sorted(expected_requires - candidate_requires)
    extra_requires = sorted(candidate_requires - expected_requires)
    missing_ensures = sorted(expected_ensures - candidate_ensures)
    extra_ensures = sorted(candidate_ensures - expected_ensures)

    if missing_requires:
        issues.append("missing requires: " + " | ".join(missing_requires))
    if extra_requires:
        issues.append("added/changed requires: " + " | ".join(extra_requires))
    if missing_ensures:
        issues.append("missing ensures: " + " | ".join(missing_ensures))
    if extra_ensures:
        issues.append("added/changed ensures: " + " | ".join(extra_ensures))

    return ContractFidelity(not issues, tuple(issues), expected, candidate)


def contract_fidelity_issues(
    expected_source: str,
    candidate_source: str,
    method_name: str = "",
) -> list[str]:
    return list(check_contract_fidelity(expected_source, candidate_source, method_name).issues)


def _find_method(source: str, method_name: str) -> re.Match[str] | None:
    if method_name:
        pattern = re.compile(rf"\bmethod\s+({re.escape(method_name)})\s*\(")
        return pattern.search(source)
    return re.search(r"\bmethod\s+(\w+)\s*\(", source)


def _matching_delimiter(text: str, start: int, opening: str, closing: str) -> int:
    if start < 0 or start >= len(text) or text[start] != opening:
        return -1
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _parse_params(text: str) -> Iterable[DafnyParam]:
    for part in _split_top_level(text, ","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        names, typ = part.split(":", 1)
        for name in names.split(","):
            clean_name = name.strip()
            if clean_name:
                yield DafnyParam(clean_name, typ.strip())


def _split_top_level(text: str, separator: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    matching = {")": "(", "]": "[", "}": "{", ">": "<"}
    for char in text:
        if char in depths:
            depths[char] += 1
        elif char in matching:
            opening = matching[char]
            depths[opening] = max(0, depths[opening] - 1)
        if char == separator and not any(depths.values()):
            result.append("".join(current))
            current = []
        else:
            current.append(char)
    result.append("".join(current))
    return result


def _contract_tail(source: str, cursor: int) -> str:
    lines = source[cursor:].splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = _strip_comment(line).strip()
        if not stripped:
            if kept:
                kept.append("")
            continue
        if stripped == "{" or stripped.startswith("{:verify"):
            break
        if kept and _DECLARATION_RE.match(stripped):
            break
        kept.append(line)
    return "\n".join(kept)


def _parse_clauses(text: str) -> tuple[list[str], list[str]]:
    requires: list[str] = []
    ensures: list[str] = []
    current_kind = ""
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_kind, current_parts
        if not current_kind:
            return
        clause = " ".join(part for part in current_parts if part).strip()
        if clause:
            (requires if current_kind == "requires" else ensures).append(clause)
        current_kind = ""
        current_parts = []

    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        match = re.match(r"^(requires|ensures)\b(.*)$", line)
        if match:
            flush()
            current_kind = match.group(1)
            current_parts = [match.group(2).strip()]
        elif current_kind:
            if _DECLARATION_RE.match(line) or line == "{":
                flush()
                break
            current_parts.append(line)
    flush()
    return requires, ensures


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0]


def _canonical_clause_set(clauses: Iterable[str], rename: dict[str, str]) -> set[str]:
    result = set()
    for clause in clauses:
        canonical = _canonical_clause(clause, rename)
        if canonical in {"", "true", "(true)"}:
            continue
        result.add(canonical)
    return result


def _canonical_clause(clause: str, rename: dict[str, str]) -> str:
    canonical = _strip_comment(clause)
    for old_name, new_name in sorted(rename.items(), key=lambda item: -len(item[0])):
        canonical = re.sub(rf"\b{re.escape(old_name)}\b", new_name, canonical)
    canonical = re.sub(r"\s+", "", canonical)
    while canonical.endswith(";"):
        canonical = canonical[:-1]
    return canonical


def _normalize_type(typ: str) -> str:
    return re.sub(r"\s+", "", typ)
