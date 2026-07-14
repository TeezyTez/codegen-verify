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


MIN_MUTANTS_FOR_CONFIDENT_RISK = 4


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

    negative_assignments = _negative_assignments(signature.returns)
    if negative_assignments:
        mutants.append(_build_mutant(
            spec,
            "negative_constant_return",
            negative_assignments,
            "Assign a negative constant to every numeric return variable.",
        ))

    for return_index, ret in enumerate(signature.returns):
        for param in signature.params:
            for mutation_name, expression, rationale in _semantic_expressions(ret, param):
                assignments = _targeted_assignments(
                    signature.returns,
                    return_index,
                    expression,
                )
                if not assignments:
                    continue
                mutants.append(_build_mutant(
                    spec,
                    _semantic_mutant_name(signature, ret, mutation_name, param),
                    assignments,
                    rationale,
                ))

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
    total = len(results)
    return {
        "mutants_total": total,
        "mutants_verified": verified_count,
        "minimum_mutants_required": MIN_MUTANTS_FOR_CONFIDENT_RISK,
        "probe_strength": _probe_strength(total),
        "mutation_adequacy_risk": _risk_level(verified_count, total),
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


def _negative_assignments(returns: list[Param]) -> list[str]:
    assignments = []
    for ret in returns:
        value = _negative_value(ret.typ)
        if value is None:
            return []
        assignments.append(f"{ret.name} := {value};")
    return assignments


def _targeted_assignments(
    returns: list[Param],
    target_index: int,
    expression: str,
) -> list[str]:
    """Assign every out parameter so multi-return mutants remain compilable."""
    assignments = []
    for index, ret in enumerate(returns):
        value = expression if index == target_index else _default_value(ret.typ)
        if value is None:
            return []
        assignments.append(f"{ret.name} := {value};")
    return assignments


def _default_value(typ: str) -> str | None:
    typ = _normalize_type(typ)
    if typ == "bool":
        return "false"
    if typ in {"int", "nat"}:
        return "0"
    if typ == "real":
        return "0.0"
    if typ == "string":
        return '""'
    if typ.startswith("seq<"):
        return "[]"
    if typ.startswith("set<"):
        return "{}"
    if typ.startswith("Option<"):
        return "None"
    return None


def _alternate_value(typ: str) -> str | None:
    typ = _normalize_type(typ)
    if typ == "bool":
        return "true"
    if typ in {"int", "nat"}:
        return "1"
    if typ == "real":
        return "1.0"
    if typ == "string":
        return '"x"'
    if typ.startswith("seq<"):
        return "[]"
    if typ.startswith("set<"):
        return "{}"
    if typ.startswith("Option<"):
        return "None"
    return None


def _negative_value(typ: str) -> str | None:
    typ = _normalize_type(typ)
    if typ == "int":
        return "-1"
    if typ == "real":
        return "-1.0"
    return None


def _semantic_expressions(ret: Param, param: Param) -> list[tuple[str, str, str]]:
    """Return suspicious expressions that are well-typed for ``ret``.

    These are deliberately semantic rather than syntactic mutations.  They
    exercise common under-specification holes: identity implementations,
    off-by-one numeric results, and sequence implementations that drop,
    duplicate, or reverse their input.
    """
    result: list[tuple[str, str, str]] = []
    ret_type = _normalize_type(ret.typ)
    param_type = _normalize_type(param.typ)

    if _compatible_type(ret_type, param_type):
        result.append((
            "return_param",
            param.name,
            f"Return input parameter `{param.name}` directly.",
        ))

        if ret_type in {"int", "real"}:
            one = "1.0" if ret_type == "real" else "1"
            result.extend([
                (
                    "param_plus_one",
                    f"({param.name} + {one})",
                    f"Return `{param.name}` plus one (an off-by-one mutant).",
                ),
                (
                    "param_minus_one",
                    f"({param.name} - {one})",
                    f"Return `{param.name}` minus one (an off-by-one mutant).",
                ),
                (
                    "negate_param",
                    f"(-{param.name})",
                    f"Return the arithmetic negation of `{param.name}`.",
                ),
            ])
        elif ret_type == "nat":
            result.extend([
                (
                    "param_plus_one",
                    f"({param.name} + 1)",
                    f"Return `{param.name}` plus one (an off-by-one mutant).",
                ),
                (
                    "param_minus_one",
                    f"(if {param.name} == 0 then 0 else {param.name} - 1)",
                    f"Return a saturating `{param.name}` minus one mutant.",
                ),
            ])
        elif ret_type == "bool":
            result.append((
                "negate_param",
                f"(!{param.name})",
                f"Return the negation of boolean input `{param.name}`.",
            ))
        elif _is_sequence_like(ret_type):
            result.extend(_sequence_expressions(param))

    # Cross-type semantic projections catch specs that constrain only the
    # result's broad range but omit its relationship to an input collection.
    if ret_type == "int" and _is_sequence_like(param_type):
        result.extend([
            (
                "input_length",
                f"|{param.name}|",
                f"Return the length of input `{param.name}`.",
            ),
            (
                "input_length_plus_one",
                f"(|{param.name}| + 1)",
                f"Return the length of `{param.name}` plus one.",
            ),
            (
                "input_length_minus_one",
                f"(if |{param.name}| == 0 then 0 else |{param.name}| - 1)",
                f"Return a saturating length-minus-one value for `{param.name}`.",
            ),
        ])
    elif ret_type == "bool" and _is_sequence_like(param_type):
        result.extend([
            (
                "input_is_empty",
                f"|{param.name}| == 0",
                f"Return whether `{param.name}` is empty.",
            ),
            (
                "input_is_nonempty",
                f"|{param.name}| != 0",
                f"Return whether `{param.name}` is non-empty.",
            ),
        ])

    option_inner = _option_inner_type(ret_type)
    if option_inner is not None and _compatible_type(option_inner, param_type):
        result.append((
            "wrap_param_some",
            f"Some({param.name})",
            f"Always wrap input `{param.name}` in `Some`.",
        ))

    return result


def _sequence_expressions(param: Param) -> list[tuple[str, str, str]]:
    name = param.name
    return [
        (
            "drop_first",
            f"(if |{name}| == 0 then [] else {name}[1..])",
            f"Drop the first element of `{name}`.",
        ),
        (
            "drop_last",
            f"(if |{name}| == 0 then [] else {name}[..|{name}| - 1])",
            f"Drop the last element of `{name}`.",
        ),
        (
            "reverse_input",
            (
                f"seq(|{name}|, mutationIndex "
                f"requires 0 <= mutationIndex < |{name}| "
                f"=> {name}[|{name}| - 1 - mutationIndex])"
            ),
            f"Return `{name}` in reverse order.",
        ),
        (
            "duplicate_input",
            f"({name} + {name})",
            f"Duplicate the contents of `{name}`.",
        ),
    ]


def _semantic_mutant_name(
    signature: Signature,
    ret: Param,
    mutation_name: str,
    param: Param,
) -> str:
    prefix = f"{ret.name}_" if len(signature.returns) > 1 else ""
    if mutation_name == "return_param":
        return f"return_{prefix}param_{param.name}"
    return f"{prefix}{mutation_name}_{param.name}"


def _compatible_type(a: str, b: str) -> bool:
    a = _normalize_type(a)
    b = _normalize_type(b)
    if a == b:
        return True
    # Dafny's ``string`` is a sequence of characters.
    return {a, b} == {"string", "seq<char>"}


def _is_sequence_like(typ: str) -> bool:
    typ = _normalize_type(typ)
    return typ == "string" or typ.startswith("seq<")


def _option_inner_type(typ: str) -> str | None:
    match = re.fullmatch(r"Option<(.*)>", _normalize_type(typ))
    return match.group(1) if match else None


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
    if total < MIN_MUTANTS_FOR_CONFIDENT_RISK:
        return "insufficient"
    if verified_count > 0:
        return "medium"
    return "low"


def _probe_strength(total: int) -> str:
    if total == 0:
        return "not_applicable"
    if total < MIN_MUTANTS_FOR_CONFIDENT_RISK:
        return "insufficient"
    return "sufficient"
