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


def restore_public_contract(
    expected_source: str,
    candidate_source: str,
    method_name: str = "",
) -> str:
    """Replace only the candidate's public declaration with the frozen one.

    LLMs frequently rewrite a postcondition into a logically equivalent helper
    expression. The harness must keep one stable contract for attribution and
    reproducibility, so generated implementations are normalized back to the
    parsed frozen signature/clauses before deterministic checks. Method bodies
    and helper declarations are left untouched.
    """
    expected = parse_method_contract(expected_source, method_name)
    if expected is None:
        return candidate_source

    method_match = _find_method(candidate_source, expected.name)
    if method_match is None:
        return candidate_source

    remainder = candidate_source[method_match.start():]
    body_match = re.search(r"(?m)^[ \t]*\{", remainder)
    if body_match is None:
        return candidate_source

    body_start = method_match.start() + body_match.start()
    declaration = _render_method_contract(expected)
    return candidate_source[:method_match.start()] + declaration + "\n" + candidate_source[body_start:]


def build_direct_reference_program(
    frozen_spec: str,
    method_name: str = "",
) -> str | None:
    """Build the trivial implementation when the spec defines the result.

    For a clause such as ``ensures result == Reference(xs)``, reimplementing
    ``Reference`` with a loop creates avoidable proof obligations and permits
    helper semantic drift. This constructor uses the frozen helper definitions
    themselves and gives the public method the single assignment required by
    the contract. Additional ensures remain in place and are still verified.
    """
    contract = parse_method_contract(frozen_spec, method_name)
    if contract is None or not contract.returns:
        return None

    assignments: list[tuple[str, str]] = []
    bodyless = bodyless_callable_names(frozen_spec)
    for return_param in contract.returns:
        reference_call = ""
        helper_name = ""
        for clause in contract.ensures:
            match = re.fullmatch(
                rf"\s*{re.escape(return_param.name)}\s*(?:==|<==>)\s*"
                r"([A-Za-z_]\w*)\s*(\(.*\))\s*",
                clause,
                flags=re.DOTALL,
            )
            if match:
                helper_name = match.group(1)
                reference_call = helper_name + match.group(2)
                break
        if not reference_call:
            return None
        helper_pattern = re.compile(
            rf"\b(?:function|predicate)\s+{re.escape(helper_name)}\s*\("
        )
        if not helper_pattern.search(frozen_spec) or helper_name in bodyless:
            return None
        assignments.append((return_param.name, reference_call))

    lines = frozen_spec.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(rf"\bmethod\s+{re.escape(contract.name)}\s*\(", line)
        ),
        None,
    )
    if start is None:
        return None

    end = start + 1
    while end < len(lines):
        stripped = _strip_comment(lines[end]).strip()
        if stripped and _DECLARATION_RE.match(stripped):
            break
        if stripped.startswith("{"):
            return None
        end += 1

    implementation = [
        *_render_method_contract(contract).splitlines(),
        "{",
        *(f"    {name} := {call};" for name, call in assignments),
        "}",
    ]
    rebuilt = [*lines[:start], *implementation, *lines[end:]]
    return "\n".join(rebuilt).strip()


def bodyless_callable_names(source: str) -> set[str]:
    """Return function/predicate declarations that have no executable body."""
    lines = (source or "").splitlines()
    declarations: list[tuple[int, str, str]] = []
    pattern = re.compile(r"^\s*(?:ghost\s+)?(function|predicate)\s+(\w+)\b")
    for index, line in enumerate(lines):
        match = pattern.match(_strip_comment(line))
        if match:
            declarations.append((index, match.group(1), match.group(2)))

    result: set[str] = set()
    for position, (start, _kind, name) in enumerate(declarations):
        end = len(lines)
        for index in range(start + 1, len(lines)):
            stripped = _strip_comment(lines[index]).strip()
            if stripped and _DECLARATION_RE.match(stripped):
                end = index
                break
        block = "\n".join(lines[start:end])
        if "{" not in block:
            result.add(name)
    return result


def _render_method_contract(contract: MethodContract) -> str:
    params = ", ".join(f"{param.name}: {param.typ}" for param in contract.params)
    declaration = f"method {contract.name}({params})"
    if contract.returns:
        returns = ", ".join(
            f"{param.name}: {param.typ}" for param in contract.returns
        )
        declaration += f" returns ({returns})"
    lines = [declaration]
    lines.extend(f"    requires {clause}" for clause in contract.requires)
    lines.extend(f"    ensures {clause}" for clause in contract.ensures)
    return "\n".join(lines)


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
    pending_names: list[str] = []
    for part in _split_top_level(text, ","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            # Dafny permits grouped declarations such as ``x, y: int``.
            # Keep names until the group-ending type annotation is seen.
            pending_names.append(part)
            continue
        names, typ = part.split(":", 1)
        grouped_names = [*pending_names, *names.split(",")]
        pending_names = []
        for name in grouped_names:
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
        # A compact implementation may open its body and contain statements on
        # the same line (``{ result := x; }``).  None of that text belongs to
        # the final requires/ensures clause.
        if stripped.startswith("{"):
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
            if _DECLARATION_RE.match(line) or line.startswith("{"):
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
    canonical = _alpha_normalize_quantifiers(canonical)
    canonical = re.sub(r"\s+", "", canonical)
    while canonical.endswith(";"):
        canonical = canonical[:-1]
    return canonical


def _alpha_normalize_quantifiers(clause: str) -> str:
    """Canonicalize locally bound ``forall``/``exists`` variable names.

    Renaming a bound variable is not contract drift. Dafny also permits an
    inferred binder type to be written explicitly; binder annotations are
    omitted here, while the resolver remains responsible for type soundness.
    """
    result = clause
    search_from = 0
    next_id = 0
    pattern = re.compile(r"\b(forall|exists)\s+(.*?)::", re.DOTALL)
    while True:
        match = pattern.search(result, search_from)
        if not match:
            return result

        binders = match.group(2).strip()
        declarations, separator, range_expr = binders.partition("|")
        names = re.findall(r"(?:^|,)\s*([A-Za-z_]\w*)", declarations)
        if not names:
            search_from = match.end()
            continue

        replacements: dict[str, str] = {}
        placeholders: list[str] = []
        for name in names:
            placeholder = f"__bound_{next_id}"
            next_id += 1
            replacements[name] = placeholder
            placeholders.append(placeholder)

        suffix = result[match.end():]
        normalized_range = range_expr
        for old_name, new_name in replacements.items():
            suffix = re.sub(rf"\b{re.escape(old_name)}\b", new_name, suffix)
            if separator:
                normalized_range = re.sub(
                    rf"\b{re.escape(old_name)}\b", new_name, normalized_range
                )

        canonical_binders = ",".join(placeholders)
        if separator:
            canonical_binders += " | " + normalized_range.strip()
        marker = f"{match.group(1)} {canonical_binders} ::"
        result = result[:match.start()] + marker + suffix
        search_from = match.start() + len(marker)


def _normalize_type(typ: str) -> str:
    return re.sub(r"\s+", "", typ)
