"""Reproducible benchmark run directories and manifests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
from typing import Any

import config


def create_run_directory(label: str = "humaneval") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in label)
    path = config.RUNS_DIR / f"{stamp}_{safe_label}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def build_manifest(
    *,
    mode: str,
    start: int,
    limit: int,
    task_ids: list[str],
    data_path: Path,
) -> dict[str, Any]:
    git_sha = _command(["git", "rev-parse", "HEAD"])
    git_status = _command(["git", "status", "--short"])
    prompt_files = [
        config.PROJECT_DIR / "project" / name
        for name in (
            "pipeline.py",
            "proof_repair.py",
            "spec_repair.py",
            "spec_code_alignment.py",
            "proof_patterns.py",
        )
    ]
    return {
        "schema_version": 1,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": mode,
        "official_test_feedback_allowed": False,
        "template_fallback": bool(config.USE_TEMPLATE_FALLBACK),
        "git": {
            "sha": git_sha.strip(),
            "dirty": bool(git_status.strip()),
            "status": git_status.splitlines(),
            "working_tree_hash": _working_tree_hash(git_status),
        },
        "models": {
            "spec": config.SPEC_MODEL,
            "code": config.CODE_MODEL,
            "repair": config.REPAIR_MODEL,
            "temperature": config.LLM_TEMPERATURE,
            "max_tokens": config.LLM_MAX_TOKENS or None,
            "retries": config.LLM_RETRIES,
        },
        "pipeline": {
            "max_repair_rounds": config.MAX_REPAIR_ROUNDS,
            "enable_spec_repair": config.ENABLE_SPEC_REPAIR,
            "enable_proof_repair": config.ENABLE_PROOF_REPAIR,
            "enable_behavior_repair_loop": config.ENABLE_BEHAVIOR_REPAIR_LOOP,
            "enable_inloop_mutation": config.ENABLE_INLOOP_MUTATION_ADEQUACY,
            "enable_mutation_strengthening": config.ENABLE_MUTATION_SPEC_STRENGTHENING,
        },
        "selection": {
            "start": start,
            "limit": limit,
            "task_ids": task_ids,
        },
        "artifacts": {
            "data_path": str(data_path.resolve()),
            "data_sha256": _sha256_file(data_path),
            "prompt_source_sha256": _combined_hash(prompt_files),
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "dafny_path": config.DAFNY_PATH,
            "dafny_version": _command([config.DAFNY_PATH, "--version"]).strip(),
            "dependencies": {
                package: _package_version(package)
                for package in ("openai", "langgraph")
            },
        },
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=config.PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"
    output = (result.stdout or result.stderr or "").strip()
    return output if result.returncode == 0 else f"rc={result.returncode}: {output}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if not path.exists():
            continue
        digest.update(str(path.relative_to(config.PROJECT_DIR)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _working_tree_hash(status: str) -> str:
    digest = hashlib.sha256(status.encode("utf-8"))
    diff = _command(["git", "diff", "--binary"])
    digest.update(diff.encode("utf-8"))
    return digest.hexdigest()


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"
