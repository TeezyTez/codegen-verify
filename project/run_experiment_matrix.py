"""Execute a generated experiment matrix with resumable per-job directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def load_matrix(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("matrix must contain a non-empty jobs list")
    identifiers = [str(job.get("job_id") or "") for job in jobs]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("matrix job_id values must be non-empty and unique")
    return jobs


def completed(job_dir: Path) -> bool:
    manifest_path = job_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("completed") is True
    except (OSError, ValueError):
        return False


def job_command(job: dict[str, Any], job_dir: Path) -> list[str]:
    command = list(job.get("command") or [])
    if len(command) < 2:
        raise ValueError(f"job {job.get('job_id')} has no executable command")
    command[0] = sys.executable
    return [*command, "--output-dir", str(job_dir)]


def credentials_available() -> bool:
    project_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_dir))
    import config

    providers = {
        config.CODE_PROVIDER,
        config.REPAIR_PROVIDER,
        config.REQUIREMENT_PROVIDER,
        config.SPEC_PROVIDER,
        config.PLANNER_PROVIDER,
        config.DIAGNOSIS_PROVIDER,
        config.CRITIC_PROVIDER,
        config.CRITIC_PROBE_PROVIDER,
    }
    return all(
        (provider == "openai" and bool(config.OPENAI_API_KEY))
        or (provider == "deepseek" and bool(config.DEEPSEEK_API_KEY))
        for provider in providers
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or validate a generated experiment matrix")
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("logs/experiments"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=0, help="Zero runs all remaining jobs")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    jobs = load_matrix(args.matrix)
    pending = []
    for job in jobs:
        job_dir = args.output_root / str(job["job_id"])
        if not completed(job_dir):
            pending.append((job, job_dir))
    if args.max_jobs > 0:
        pending = pending[: args.max_jobs]

    if args.dry_run:
        for job, job_dir in pending:
            print(json.dumps({
                "job_id": job["job_id"],
                "command": job_command(job, job_dir),
            }, ensure_ascii=False))
        print(f"dry-run validated {len(pending)} pending jobs; {len(jobs) - len(pending)} completed/skipped")
        return 0

    if not credentials_available():
        print(
            "refusing to start: one or more configured model providers lack local API credentials",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for index, (job, job_dir) in enumerate(pending, start=1):
        job_dir.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{len(pending)}] {job['job_id']}")
        completed_process = subprocess.run(job_command(job, job_dir), check=False)
        if completed_process.returncode != 0:
            failures += 1
            if not args.continue_on_error:
                break
    print(f"matrix execution finished: attempted={index if pending else 0}, failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

