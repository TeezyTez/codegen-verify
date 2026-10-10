"""Independent, real-verifier constant/empty-implementation admission audit.

This module never reads a reference .dfy file or uses vc-code. Surviving simple
implementations are manual-review signals, not proof that a contract is weak.
Failure to parse/typecheck is inapplicability, not a killed semantic mutant.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path

from .admission import DATA, ROOT, save
from .runner import _verification
from .structure import compare_frozen, inspect_source
from .task import PublicTask, canonical, digest
from generation.representation.verifier import Dafny

PURPOSE = "data_admission_mutation_audit_not_tested_generation_success"
LIMITATIONS = [
    "Finite constant/empty mutations do not establish contract completeness.",
    "A surviving constant can be correct for a constant-output task; independent manual review is required.",
    "Parse/type-inapplicable mutants, timeouts, and tool failures are not counted as killed.",
    "Only return-value constants and an empty body are tried; arbitrary algorithmic mutations are not covered.",
]


def _split(tokens, separator=","):
    groups, current, stack = [], [], []
    pairs = {"(": ")", "<": ">", "[": "]"}
    for token in tokens:
        if token in pairs:
            stack.append(pairs[token])
        elif stack and token == stack[-1]:
            stack.pop()
        if token == separator and not stack:
            groups.append(current)
            current = []
        else:
            current.append(token)
    if current:
        groups.append(current)
    return groups


def _outputs(declaration):
    """Read the compiler-provided header tokens for mutation construction only.

    This is deliberately not an acceptance parser. Every constructed source is
    parsed and resolved again by inspect_source before it reaches the verifier.
    """
    tokens = declaration["header_tokens"]
    if declaration["kind"] not in {"method", "lemma"}:
        raise ValueError("constant audit currently supports method/lemma targets")
    if "returns" not in tokens:
        return []
    index = tokens.index("returns") + 1
    if tokens[index] != "(":
        raise ValueError("unrecognized compiler return signature")
    depth, end = 1, index + 1
    while end < len(tokens) and depth:
        depth += (tokens[end] == "(") - (tokens[end] == ")")
        end += 1
    if depth:
        raise ValueError("unterminated compiler return signature")
    outputs = []
    for group in _split(tokens[index+1:end-1]):
        if group and group[0] == "ghost":
            group = group[1:]
        if len(group) < 3 or group[1] != ":":
            raise ValueError("unsupported return binding")
        outputs.append({"name": group[0], "type": "".join(group[2:]), "type_tokens": group[2:]})
    return outputs


def _values(output):
    tokens = output["type_tokens"]
    text = output["type"]
    if text in {"int", "nat", "real"}:
        return ["0", "1", "-1"]
    if text == "bool":
        return ["false", "true"]
    if text == "string" or tokens[0] == "seq":
        return ["[]"]
    if tokens[0] in {"set", "iset"}:
        return ["{}"]
    if tokens[0] == "multiset":
        return ["multiset{}"]
    if tokens[0] in {"map", "imap"}:
        return ["map[]"]
    if tokens[0] == "array" and len(tokens) >= 4 and tokens[1] == "<" and tokens[-1] == ">":
        return ["new " + "".join(tokens[2:-1]) + "[0]"]
    return []


def make_mutants(declaration, *, max_constants=64):
    if type(max_constants) is not int or max_constants < 1:
        raise ValueError("positive max_constants required")
    plan = {"outputs": [], "mutants": [{"id": "empty-body", "kind": "empty_body",
        "implementation": "{}", "helpers": "", "values": {}}], "skipped": [],
        "constant_combinations": 0, "truncated": False}
    try:
        plan["outputs"] = _outputs(declaration)
    except (ValueError, IndexError) as error:
        plan["skipped"].append({"code": "unsupported_target_signature", "message": str(error)})
        return plan
    choices = []
    for output in plan["outputs"]:
        values = _values(output)
        if not values:
            plan["skipped"].append({"code": "unsupported_output_type", "output": output["name"], "type": output["type"]})
        choices.append(values)
    if not choices or any(not values for values in choices):
        return plan
    plan["constant_combinations"] = math.prod(len(values) for values in choices)
    plan["truncated"] = plan["constant_combinations"] > max_constants
    for index, values in enumerate(itertools.islice(itertools.product(*choices), max_constants), 1):
        mapping = {output["name"]: value for output, value in zip(plan["outputs"], values)}
        body = "{ " + " ".join(name + " := " + value + ";" for name, value in mapping.items()) + " }"
        plan["mutants"].append({"id": f"constant-{index:03d}", "kind": "constant",
            "implementation": body, "helpers": "", "values": mapping})
    return plan


def classify_mutant(structure, verification=None, guard_findings=()):
    state = structure.get("status")
    if state == "parse_error":
        return "inapplicable_parse"
    if state == "resolution_error":
        return "inapplicable_type"
    if state == "tool_error":
        return "structure_tool_error"
    if state != "ok" or guard_findings:
        return "guard_rejected"
    if verification is None:
        return "unknown"
    status = verification.get("status")
    if status in {"parse_error", "resolution_error"}:
        raw = (verification.get("stdout", "") + verification.get("stderr", "")).lower()
        return "inapplicable_type" if "resolution" in raw or status == "resolution_error" else "inapplicable_parse"
    return {"verified": "survived", "verification_failed": "killed"}.get(status, status or "unknown")


def _write_result(directory, result):
    save(directory / "result.json", result)
    (directory / "result.sha256").write_text(digest(canonical(result)) + "\n", encoding="utf-8")


def _resume_result(directory, manifest):
    path = directory / "result.json"
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("manifest") != manifest:
        raise ValueError("mutation audit manifest changed: " + str(directory))
    if not (directory / "result.sha256").exists() or (directory / "result.sha256").read_text().strip() != digest(canonical(result)):
        raise ValueError("mutation audit result integrity failed: " + str(directory))
    for relative, expected in result.get("artifact_sha256", {}).items():
        artifact = (directory / relative).resolve()
        if directory.resolve() not in artifact.parents or not artifact.is_file() or digest(artifact.read_text(encoding="utf-8")) != expected:
            raise ValueError("mutation audit artifact integrity failed: " + str(artifact))
    return result


def evaluate_mutant(task, frozen, editable_ids, mutant, output, *, timeout=120):
    directory = Path(output)
    source = task.assemble({"implementation": mutant["implementation"], "helpers": mutant["helpers"]})
    manifest = {"purpose": PURPOSE, "task": task.manifest(), "mutant": mutant,
        "source_sha256": digest(source), "frozen_sha256": digest(canonical(frozen)),
        "editable_ids": sorted(editable_ids), "timeout_seconds": timeout}
    previous = _resume_result(directory, manifest)
    if previous is not None:
        return previous
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "manifest.json", manifest)
    (directory / "candidate.dfy").write_text(source, encoding="utf-8")
    structure = inspect_source(source)
    save(directory / "structure.json", structure)
    findings = compare_frozen(frozen, structure, editable_ids)
    evidence = None
    if structure.get("status") == "ok" and structure.get("trusted_ast") and not findings and not structure.get("findings"):
        primary = next(d for d in structure["declarations"] if d["name"] == task.target_name)
        evidence = _verification(Dafny(timeout=timeout).verify(source, names=(), timeout=timeout), primary)
        save(directory / "verification.json", evidence)
        for filename, key in [("verifier.stdout.txt", "stdout"), ("verifier.stderr.txt", "stderr"), ("verifier.csv", "csv_log")]:
            (directory / filename).write_text(evidence.get(key, ""), encoding="utf-8")
    status = classify_mutant(structure, evidence, findings)
    result = {"manifest": manifest, "id": mutant["id"], "status": status,
        "applicability": "applicable" if status in {"killed", "survived"} else "inapplicable" if status.startswith("inapplicable_") else "unknown",
        "structure_status": structure.get("status"), "guard_findings": findings + structure.get("findings", []),
        "verification": evidence, "manual_review_required": status == "survived",
        "artifact_sha256": {p.name: digest(p.read_text(encoding="utf-8")) for p in directory.iterdir()
            if p.is_file() and p.name not in {"result.json", "result.sha256"}}}
    _write_result(directory, result)
    return result


def fingerprints():
    names = ["generation/public_benchmark/" + name for name in ["mutations.py", "structure.py",
        "structure_bridge.cs", "structure_bridge.ps1", "task.py", "runner.py"]]
    names += ["generation/representation/verifier.py", "repair/verifier.py"]
    return {name: digest((ROOT / name).read_text(encoding="utf-8")) for name in names}


def audit_one(record, admission, semantic, output, *, timeout=120, source_hashes=None):
    if semantic.get("status") != "admitted" or admission.get("status") != "structurally_eligible":
        raise ValueError("task has not passed existing admission")
    task = PublicTask(record, family_id=admission["family_id"])
    if admission["record_sha256"] != task.record_sha256:
        raise ValueError("task record differs from admitted snapshot")
    directory = Path(output)
    manifest = {"schema_version": 1, "purpose": PURPOSE, "task": task.manifest(),
        "admission_sha256": digest(canonical(admission)), "semantic_sha256": digest(canonical(semantic)),
        "source_hashes": source_hashes or fingerprints(), "timeout_seconds": timeout}
    previous = _resume_result(directory, manifest)
    if previous is not None:
        return previous
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "manifest.json", manifest)
    frozen = inspect_source(task.skeleton)
    save(directory / "frozen_structure.json", frozen)
    differences = compare_frozen(admission["skeleton"], frozen, [])
    result = {"manifest": manifest, "id": task.id, "family_id": task.family_id,
        "status": "audit_incomplete", "model_calls": 0, "reference_used_for_mutation": False,
        "mutants": [], "survivors": [], "killed_mutants": [], "manual_review_required": False,
        "limitations": LIMITATIONS, "frozen_differences": differences}
    if frozen.get("status") == "ok" and frozen.get("trusted_ast") and not differences:
        target = next(d for d in frozen["declarations"] if d["name"] == task.target_name)
        plan = make_mutants(target)
        result["mutation_plan"] = plan
        save(directory / "mutation_plan.json", plan)
        for mutant in plan["mutants"]:
            row = evaluate_mutant(task, frozen, admission["editable_ids"], mutant, directory / "mutants" / mutant["id"], timeout=timeout)
            result["mutants"].append({"id": row["id"], "status": row["status"], "applicability": row["applicability"],
                "implementation": mutant["implementation"], "values": mutant["values"],
                "result_path": f"mutants/{mutant['id']}/result.json"})
            print(task.id, mutant["id"], row["status"], flush=True)
        result["survivors"] = [r["id"] for r in result["mutants"] if r["status"] == "survived"]
        result["killed_mutants"] = [r["id"] for r in result["mutants"] if r["status"] == "killed"]
        result["manual_review_required"] = bool(result["survivors"])
        result["status"] = "manual_review_required" if result["survivors"] else "audit_completed"
        if any(r["status"] in {"timeout", "tool_error", "structure_tool_error", "unknown"} for r in result["mutants"]):
            result["has_unresolved_checks"] = True
    result["counts"] = dict(Counter(row["status"] for row in result["mutants"]))
    result["artifact_sha256"] = {str(p.relative_to(directory)): digest(p.read_text(encoding="utf-8"))
        for p in directory.rglob("*") if p.is_file() and p not in {directory / "result.json", directory / "result.sha256"}}
    _write_result(directory, result)
    return result


def select_admitted(semantic_root, ids=None):
    semantics = {r["id"]: r for p in (Path(semantic_root) / "tasks").glob("*.json")
        if (r := json.loads(p.read_text(encoding="utf-8"))).get("status") == "admitted"}
    if ids is None:
        return semantics
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= semantics.keys():
        raise ValueError("explicit IDs must be unique, nonempty, and already admitted")
    return {ident: semantics[ident] for ident in sorted(ids)}


def run_available(admission_root, semantic_root, output, *, workers=4, timeout=120, ids=None):
    if type(workers) is not int or workers < 1 or timeout != 120:
        raise ValueError("positive workers and the fixed 120-second audit timeout are required")
    admission_root, semantic_root, output = Path(admission_root), Path(semantic_root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = {r["id"]: r for r in [json.loads(line) for line in (DATA / "vericoding/jsonl/dafny_tasks.jsonl").read_text(encoding="utf-8").splitlines()]}
    semantics = select_admitted(semantic_root, ids)
    source_hashes = fingerprints()
    plan = {"purpose": PURPOSE, "ids": sorted(semantics), "workers": workers, "timeout_seconds": timeout,
        "selection": "explicit_frozen_ids" if ids is not None else "all_currently_admitted",
        "source_hashes": source_hashes, "semantic_sha256": {key: digest(canonical(value)) for key, value in sorted(semantics.items())},
        "model_calls": 0, "limitations": LIMITATIONS}
    snapshot = digest(canonical(plan))[:20]
    save(output / "plans" / (snapshot + ".json"), plan)
    print("Auditing", len(semantics), "currently admitted tasks; snapshot", snapshot, flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for ident in sorted(semantics):
            admission = json.loads((admission_root / "tasks" / (ident + ".json")).read_text(encoding="utf-8"))
            future = pool.submit(audit_one, records[ident], admission, semantics[ident], output / "tasks" / ident,
                timeout=timeout, source_hashes=source_hashes)
            futures[future] = ident
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            save(output / "progress.json", {"snapshot": snapshot, "completed": len(results), "planned": len(semantics),
                "task_statuses": dict(Counter(r["status"] for r in results)),
                "mutant_statuses": dict(Counter(m["status"] for r in results for m in r["mutants"]))})
    summary = {"purpose": PURPOSE, "snapshot": snapshot, "completed_utc": datetime.now(timezone.utc).isoformat(),
        "tasks": len(results), "ids": sorted(semantics), "model_calls": 0,
        "task_statuses": dict(Counter(r["status"] for r in results)),
        "mutant_statuses": dict(Counter(m["status"] for r in results for m in r["mutants"])),
        "manual_review_required": [{"id": r["id"], "survivors": r["survivors"]} for r in results if r["survivors"]],
        "unresolved_tasks": [r["id"] for r in results if r["status"] == "audit_incomplete" or r.get("has_unresolved_checks")],
        "limitations": LIMITATIONS}
    save(output / "summaries" / (snapshot + ".json"), summary)
    save(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", type=Path, default=ROOT / "logs/public-codegen-20261009/admission")
    parser.add_argument("--semantic", type=Path, default=ROOT / "logs/public-codegen-20261009/semantic")
    parser.add_argument("--output", type=Path, default=ROOT / "logs/public-codegen-20261009/mutations")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ids", nargs="+", help="Exact frozen admitted IDs; omitted means all currently admitted tasks.")
    args = parser.parse_args()
    run_available(args.admission, args.semantic, args.output, workers=args.workers, ids=args.ids)
