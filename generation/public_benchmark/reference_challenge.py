"""Recheck short-timeout/unknown native references without rewriting old evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path

from .admission import DATA, ROOT, compatibility_one, save, structure_version
from .runner import _verification
from .task import canonical, digest
from generation.representation.verifier import Dafny

PURPOSE = "independent_reference_challenge_recheck_not_model_generation"


def raw_sha(value):
    return hashlib.sha256(value).hexdigest()


def archive_reference(original, output):
    """Match admission.read_text UTF-8/universal-newline semantics exactly."""
    original, output = Path(original), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    raw = original.read_bytes()
    normalized = original.read_text(encoding="utf-8")
    if original.read_bytes() != raw:
        raise ValueError("published reference changed while reading")
    payload = normalized.encode("utf-8")
    (output / "original-reference.dfy").write_bytes(raw)
    (output / "normalized-reference.dfy").write_bytes(payload)
    return normalized, {"original_path": str(original.resolve()),
        "original_raw_sha256": raw_sha(raw), "normalized_utf8_sha256": raw_sha(payload),
        "actual_input_sha256": raw_sha((output / "normalized-reference.dfy").read_bytes()),
        "normalization": "Path.read_text(encoding='utf-8') universal newlines, exactly as admission; UTF-8 bytes without output newline translation"}


def verify_saved_reference(path, primary):
    path = Path(path).resolve()
    payload = path.read_bytes()
    source = payload.decode("utf-8")
    verifier = Dafny(timeout=120)
    identity = verifier.identity()
    if identity.get("source_encoding") != "utf-8" or identity.get("source_newline_translation") is not False:
        raise ValueError("exact-byte verifier adapter required")
    evidence = _verification(verifier.verify(source, names=(), timeout=120), primary)
    evidence.update(saved_input_path=str(path), actual_input_sha256=raw_sha(payload),
        verifier_identity=identity,
        input_hash_provenance="Saved UTF-8 bytes passed verbatim to v3 adapter; its frozen implementation writes source.encode('utf-8') with write_bytes.",
        verifier_adapter_raw_sha256=raw_sha((ROOT / "generation/representation/verifier.py").read_bytes()))
    if path.read_bytes() != payload:
        evidence.update(status="tool_error", input_integrity_failure=True)
    return evidence


def recheck_one(record, family, prior_path, output):
    ident = record["id"]
    output, prior_path = Path(output), Path(prior_path)
    directory = output / "evidence" / ident
    task_path = output / "tasks" / (ident + ".json")
    prior_bytes = prior_path.read_bytes()
    prior = json.loads(prior_bytes)
    expected = {"prior_preflight_sha256": raw_sha(prior_bytes), "record_sha256": digest(canonical(record)),
        "structure_version": structure_version(), "script_sha256": raw_sha(Path(__file__).read_bytes())}
    if task_path.exists():
        previous = json.loads(task_path.read_text(encoding="utf-8"))
        if previous.get("challenge_complete"):
            if previous.get("challenge_manifest") != expected:
                raise ValueError("completed reference challenge identity changed")
            for relative, checksum in previous["challenge_artifact_sha256"].items():
                artifact = (output / relative).resolve()
                if output.resolve() not in artifact.parents or raw_sha(artifact.read_bytes()) != checksum:
                    raise ValueError("reference challenge evidence changed")
            return previous
    source_path = DATA / "vericoding/vericoded" / (ident + "_vericoded.dfy")
    reference, input_receipt = archive_reference(source_path, directory)
    (directory / "original-preflight.json").write_bytes(prior_bytes)
    save(directory / "input-receipt.json", input_receipt)
    # This reuses the actual admission parser/normalization and all contract gates.
    # A pending marker cannot make the task eligible before fresh verification.
    result = compatibility_one(record, family, {"status": "pending_120_second_recheck"}, output / "tasks")
    result.update(challenge_manifest=expected, challenge_purpose=PURPOSE,
        prior_preflight_status=prior["status"], prior_preflight_sha256=raw_sha(prior_bytes),
        reference_input_receipt=input_receipt, semantic_review="pending", model_calls=0)
    if "reference_sha256" in result and result["reference_sha256"] != digest(reference):
        raise ValueError("admission and actual normalized input differ")
    structural_reasons = [r for r in result["reasons"] if r != "reference_not_verified"]
    evidence = None
    result["reference_verification"] = "not_run_structural_rejection"
    if not structural_reasons:
        primary = next(d for d in result["reference_structure"]["declarations"]
                       if d["id"] in result.get("editable_ids", []) or d["name"] == result["task"]["target_name"])
        evidence = verify_saved_reference(directory / "normalized-reference.dfy", primary)
        save(directory / "verification.json", evidence)
        for name, key in [("verifier.stdout.txt", "stdout"), ("verifier.stderr.txt", "stderr"), ("verifier.csv", "csv_log")]:
            (directory / name).write_bytes(evidence.get(key, "").encode("utf-8"))
        result["reference_verification"] = "all_observed_batches_verified" if evidence["status"] == "verified" else evidence["status"]
        result["reference_verification_evidence"] = evidence
    result["reasons"] = structural_reasons
    if result["reference_verification"] != "all_observed_batches_verified":
        result["reasons"].append("reference_not_verified_at_120_seconds" if evidence is not None else "reference_recheck_blocked_by_structure")
    result["status"] = "not_qualified" if result["reasons"] else "structurally_eligible"
    if result["status"] == "structurally_eligible":
        result["editable_ids"] = [d["id"] for d in result["skeleton"]["declarations"] if d["name"] == result["task"]["target_name"]]
    result["challenge_complete"] = True
    result["challenge_artifact_sha256"] = {str(p.relative_to(output)): raw_sha(p.read_bytes()) for p in directory.iterdir() if p.is_file()}
    save(task_path, result)
    print(ident, prior["status"], "->", result["reference_verification"], result["status"], flush=True)
    return result


def run(output, *, workers=4):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    grouping = json.loads((DATA / "recruitment-groups.json").read_text(encoding="utf-8"))
    families = {ident: group["provisional_family_id"] for group in grouping["groups"] for ident in group["ids"]}
    records = [json.loads(line) for line in (DATA / "vericoding/jsonl/dafny_tasks.jsonl").read_text(encoding="utf-8").splitlines()]
    jobs = []
    for record in records:
        if record["source"] == "dafnybench":
            continue
        prior_path = DATA / "baf_preflight" / (record["id"] + ".json")
        if prior_path.exists() and json.loads(prior_path.read_text(encoding="utf-8"))["status"] in {"timeout", "unknown"}:
            jobs.append((record, families[record["id"]], prior_path))
    plan = {"purpose": PURPOSE, "ids": [record["id"] for record, _, _ in jobs], "workers": workers,
        "timeout_seconds": 120, "cores": 1, "model_calls": 0, "semantic_admitted": 0,
        "structure_version": structure_version(), "script_raw_sha256": raw_sha(Path(__file__).read_bytes()),
        "verifier_adapter_raw_sha256": raw_sha((ROOT / "generation/representation/verifier.py").read_bytes()),
        "prior_statuses": {record["id"]: json.loads(path.read_text(encoding="utf-8"))["status"] for record, _, path in jobs},
        "prior_sha256": {record["id"]: raw_sha(path.read_bytes()) for record, _, path in jobs},
        "selection": "All non-DafnyBench task records with prior 30-second timeout or unknown; no model outcome consulted."}
    plan_path = output / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text(encoding="utf-8")) != plan:
        raise ValueError("reference challenge plan changed; use a new output directory")
    save(plan_path, plan)
    print("Rechecking", len(jobs), "short-timeout/unknown references", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(recheck_one, *job, output) for job in jobs]
        for future in as_completed(futures):
            results.append(future.result())
            save(output / "progress.json", {"complete": len(results), "planned": len(jobs),
                "statuses": dict(Counter(r["status"] for r in results)),
                "verification_statuses": dict(Counter(r["reference_verification"] for r in results))})
    summary = {"purpose": PURPOSE, "tasks": len(results), "timeout_seconds": 120, "model_calls": 0,
        "statuses": dict(Counter(r["status"] for r in results)),
        "verification_statuses": dict(Counter(r["reference_verification"] for r in results)),
        "ready_for_semantic_review": sorted(r["id"] for r in results if r["status"] == "structurally_eligible"),
        "not_qualified": {r["id"]: r["reasons"] for r in results if r["status"] != "structurally_eligible"},
        "semantic_admitted": 0, "notes": "Newly recovered references still require independent semantic and nonempty-input witness review before final admission."}
    save(output / "compatibility.json", sorted(results, key=lambda r: r["id"]))
    save(output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "logs/public-codegen-20261009/reference-challenge-v2")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    run(args.output, workers=args.workers)
