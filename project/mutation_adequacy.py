"""
Mutation-based specification adequacy probe.

This script asks a focused question:

    Can an obviously wrong implementation still satisfy the generated spec?

If a mutant is Dafny-verified but fails the original HumanEval tests, the spec is
likely under-constrained. This is not a complete adequacy proof, but it gives
strong empirical evidence for paper analysis.
"""
import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config
from dafny_wrapper import DafnyVerifier
from humaneval_tester import run_humaneval_test
from run_humaneval import load_humaneval


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
        spec,
        flags=re.DOTALL,
    )
    if not match:
        return None
    return Signature(
        name=match.group(1),
        params=_parse_params(match.group(2) or ""),
        returns=_parse_params(match.group(3) or ""),
    )


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
            if _compatible_type(ret.typ, param.typ):
                mutants.append(_build_mutant(
                    spec,
                    f"return_param_{param.name}",
                    [f"{ret.name} := {param.name};"],
                    f"Return input parameter `{param.name}` directly.",
                ))
                break

    return _dedupe_mutants(mutants)


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


def _compatible_type(a: str, b: str) -> bool:
    return _normalize_type(a) == _normalize_type(b)


def _normalize_type(typ: str) -> str:
    return re.sub(r"\s+", "", typ)


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


def evaluate_mutants_for_result(
    result: dict[str, Any],
    problem: dict[str, Any] | None,
    run_tests: bool = True,
) -> dict[str, Any]:
    spec = result.get("spec", "")
    mutants = generate_mutants(spec)
    verifier = DafnyVerifier()
    mutant_results = []

    for mutant in mutants:
        verification = verifier.verify(mutant.code)
        test_passed = None
        test_error = None
        if verification.passed and run_tests and problem is not None:
            test_passed, detail = run_humaneval_test(mutant.code, problem)
            test_error = detail.get("error")

        mutant_results.append({
            "name": mutant.name,
            "rationale": mutant.rationale,
            "dafny_verified": verification.passed,
            "dafny_error_count": verification.error_count,
            "humaneval_passed": test_passed,
            "humaneval_error": test_error,
            "suspicious": bool(verification.passed and test_passed is False),
        })

    suspicious_count = sum(1 for item in mutant_results if item["suspicious"])
    verified_count = sum(1 for item in mutant_results if item["dafny_verified"])
    return {
        "task_id": result.get("task_id", ""),
        "entry_point": result.get("entry_point", ""),
        "mutants_total": len(mutant_results),
        "mutants_verified": verified_count,
        "suspicious_mutants": suspicious_count,
        "mutation_adequacy_risk": _risk_level(suspicious_count, verified_count, len(mutant_results)),
        "mutants": mutant_results,
    }


def _risk_level(suspicious_count: int, verified_count: int, total: int) -> str:
    if total == 0:
        return "not_applicable"
    if suspicious_count > 0:
        return "high"
    if verified_count > 0:
        return "medium"
    return "low"


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("results", data if isinstance(data, list) else [])


def load_problem_index() -> dict[str, dict[str, Any]]:
    try:
        return {problem["task_id"]: problem for problem in load_humaneval()}
    except Exception:
        return {}


def write_summary_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "task_id",
            "entry_point",
            "mutants_total",
            "mutants_verified",
            "suspicious_mutants",
            "mutation_adequacy_risk",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "task_id": row["task_id"],
                "entry_point": row["entry_point"],
                "mutants_total": row["mutants_total"],
                "mutants_verified": row["mutants_verified"],
                "suspicious_mutants": row["suspicious_mutants"],
                "mutation_adequacy_risk": row["mutation_adequacy_risk"],
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe spec adequacy with simple mutants")
    parser.add_argument("--input", type=Path, default=config.LOG_DIR / "benchmark_final.json")
    parser.add_argument("--output", type=Path, default=config.LOG_DIR / "mutation_adequacy.json")
    parser.add_argument("--csv", type=Path, default=config.LOG_DIR / "mutation_adequacy.csv")
    parser.add_argument("--no-tests", action="store_true", help="Only run Dafny verification for mutants")
    args = parser.parse_args()

    results = load_benchmark(args.input)
    problem_index = load_problem_index()
    reports = [
        evaluate_mutants_for_result(
            result,
            problem_index.get(result.get("task_id", "")),
            run_tests=not args.no_tests,
        )
        for result in results
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"total": len(reports), "results": reports}, f, indent=2, ensure_ascii=False)
    write_summary_csv(reports, args.csv)

    high_risk = sum(1 for row in reports if row["mutation_adequacy_risk"] == "high")
    verified_mutants = sum(row["mutants_verified"] for row in reports)
    suspicious = sum(row["suspicious_mutants"] for row in reports)
    print("\n=== Mutation Adequacy Probe ===")
    print(f"Tasks analyzed:        {len(reports)}")
    print(f"Verified mutants:      {verified_mutants}")
    print(f"Suspicious mutants:    {suspicious}")
    print(f"High-risk specs:       {high_risk}")
    print(f"JSON written to:       {args.output}")
    print(f"CSV written to:        {args.csv}")


if __name__ == "__main__":
    main()
