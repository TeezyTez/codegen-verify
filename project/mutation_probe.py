"""
Reusable mutation-based specification adequacy probe.

The probe asks a focused question: can a simple, obviously suspicious
implementation still satisfy the current spec? It is intentionally lightweight
so the main pipeline can use it as a repair signal.
"""
import re
from dataclasses import dataclass
from typing import Any

from dafny_wrapper import DafnyVerifier


@dataclass(frozen=True)
class Param:
    name: str
    typ: str


@dataclass(frozen=True)
class Signature:
    name: str
    params: list[Param]
    returns: list[Param]


@dataclass(frozen=True)
class Mutant:
    name: str
    code: str
    rationale: str


def parse_signature(spec: str) -> Signature | None:
    match = re.search(
        r"method\s+(\w+)\s*\((.*?)\)\s*(?:returns\s*\((.*?)\))?",
        spec or "",
        flags=re.DOTALL,
    )
    if not match:
        return None
    return Signature(
        name=match.group(1),
        params=_parse_params(match.group(2) or ""),
        returns=_parse_params(match.group(3) or ""),
    )


def generate_mutants(spec: str) -> list[Mutant]:
    signature = parse_signature(spec)
    if not signature or not signature.returns:
        return []

    mutants: list[Mutant] = []
    default_assignments = _default_assignments(signature.returns)
    if default_assignments:
        mutants.append(_build_mutant(
            spec,
            "default_return",
            default_assignments,
            "Assign default values to all return variables.",
        ))

    alternate_assignments = _alternate_assignments(signature.returns)
    if alternate_assignments:
        mutants.append(_build_mutant(
            spec,
            "alternate_default_return",
            alternate_assignments,
            "Assign an alternate constant/default value.",
        ))

    for ret in signature.returns:
        for param in signature.params:
            if _normalize_type(ret.typ) == _normalize_type(param.typ):
                mutants.append(_build_mutant(
                    spec,
                    f"return_param_{param.name}",
                    [f"{ret.name} := {param.name};"],
                    f"Return input parameter `{param.name}` directly.",
                ))
                break

    return _dedupe_mutants(mutants)


def probe_spec_mutants(spec: str, verifier: DafnyVerifier | None = None) -> dict[str, Any]:
    verifier = verifier or DafnyVerifier()
    mutants = generate_mutants(spec)
    results = []

    for mutant in mutants:
        verification = verifier.verify(mutant.code)
        results.append({
            "name": mutant.name,
            "rationale": mutant.rationale,
            "dafny_verified": verification.passed,
            "dafny_error_count": verification.error_count,
        })

    verified_count = sum(1 for item in results if item["dafny_verified"])
    return {
        "mutants_total": len(results),
        "mutants_verified": verified_count,
        "mutation_adequacy_risk": _risk_level(verified_count, len(results)),
        "mutants": results,
    }


def _parse_params(text: str) -> list[Param]:
    params = []
    current = ""
    depth = 0
    for ch in text:
        if ch in "<({[":
            depth += 1
        elif ch in ">)}]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            _append_param(params, current)
            current = ""
        else:
            current += ch
    _append_param(params, current)
    return params


def _append_param(params: list[Param], text: str) -> None:
    text = text.strip()
    if not text or ":" not in text:
        return
    name, typ = text.split(":", 1)
    params.append(Param(name.strip(), typ.strip()))


def _default_assignments(returns: list[Param]) -> list[str]:
    assignments = []
    for ret in returns:
        value = _default_value(ret.typ)
        if value is None:
            return []
        assignments.append(f"{ret.name} := {value};")
    return assignments


def _alternate_assignments(returns: list[Param]) -> list[str]:
    assignments = []
    for ret in returns:
        value = _alternate_value(ret.typ)
        if value is None:
            return []
        assignments.append(f"{ret.name} := {value};")
    return assignments


def _default_value(typ: str) -> str | None:
    typ = typ.strip()
    if typ == "bool":
        return "false"
    if typ == "int":
        return "0"
    if typ == "real":
        return "0.0"
    if typ == "string":
        return '""'
    if typ.startswith("seq<"):
        return "[]"
    return None


def _alternate_value(typ: str) -> str | None:
    typ = typ.strip()
    if typ == "bool":
        return "true"
    if typ == "int":
        return "1"
    if typ == "real":
        return "1.0"
    if typ == "string":
        return '"x"'
    if typ.startswith("seq<"):
        return "[]"
    return None


def _build_mutant(spec: str, name: str, assignments: list[str], rationale: str) -> Mutant:
    body = "\n".join(f"    {line}" for line in assignments)
    code = f"{spec.rstrip()}\n{{\n{body}\n}}"
    return Mutant(name=name, code=code, rationale=rationale)


def _dedupe_mutants(mutants: list[Mutant]) -> list[Mutant]:
    seen = set()
    result = []
    for mutant in mutants:
        if mutant.code in seen:
            continue
        seen.add(mutant.code)
        result.append(mutant)
    return result


def _normalize_type(typ: str) -> str:
    return re.sub(r"\s+", "", typ)


def _risk_level(verified_count: int, total: int) -> str:
    if total == 0:
        return "not_applicable"
    if verified_count > 0:
        return "medium"
    return "low"
