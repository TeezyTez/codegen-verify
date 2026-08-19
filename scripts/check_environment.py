"""Validate the reproducible local toolchain without exposing secrets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "toolchain.lock.json"
ENV_PATH = ROOT / ".env"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def main() -> int:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    warnings: list[str] = []

    expected_python = manifest["python"]["version"]
    actual_python = ".".join(map(str, sys.version_info[:3]))
    if actual_python != expected_python:
        failures.append(f"Python: expected {expected_python}, got {actual_python}")
    expected_python_hash = manifest["python"]["executable_sha256"]
    if sha256(Path(sys.executable)) != expected_python_hash:
        failures.append("Python executable hash does not match toolchain.lock.json")
    actual_pip = metadata.version("pip")
    expected_pip = manifest["python"]["pip_version"]
    if actual_pip != expected_pip:
        failures.append(f"pip: expected {expected_pip}, got {actual_pip}")

    requirements_path = ROOT / manifest["dependencies"]["file"]
    actual_lock_hash = sha256(requirements_path)
    if actual_lock_hash != manifest["dependencies"]["sha256"]:
        failures.append("requirements.lock hash does not match toolchain.lock.json")

    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#") or "==" not in requirement:
            continue
        name, expected = requirement.split("==", 1)
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            failures.append(f"Dependency missing: {name}=={expected}")
            continue
        if actual != expected:
            failures.append(f"Dependency mismatch: {name} expected {expected}, got {actual}")

    pip_check = run([sys.executable, "-m", "pip", "check"])
    if pip_check.returncode != 0:
        failures.append(f"pip check failed: {pip_check.stdout or pip_check.stderr}")

    dafny_path = ROOT / manifest["dafny"]["executable"]
    if not dafny_path.exists():
        failures.append(f"Dafny executable missing: {dafny_path}")
    else:
        dafny_version = run([str(dafny_path), "--version"])
        expected_dafny = manifest["dafny"]["version"]
        if dafny_version.returncode != 0:
            failures.append(f"Dafny failed to start: {dafny_version.stderr}")
        elif dafny_version.stdout.strip() != expected_dafny:
            failures.append(
                f"Dafny: expected {expected_dafny}, got {dafny_version.stdout.strip()}"
            )

    env = read_env(ENV_PATH)
    configured_dafny = env.get("DAFNY_PATH", "")
    if configured_dafny and Path(configured_dafny).resolve() != dafny_path.resolve():
        failures.append(".env DAFNY_PATH does not point to the locked executable")
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if not (os.getenv(key) or env.get(key)):
            warnings.append(f"{key} is empty; live model calls for that provider are disabled")

    print(f"Python {actual_python}")
    print(f"Dafny {manifest['dafny']['version']}")
    print(f"Locked dependencies: {len(metadata.packages_distributions())} import packages available")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for failure in failures:
        print(f"ERROR: {failure}")

    if failures:
        print("Environment check: FAILED")
        return 1
    print("Environment check: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
