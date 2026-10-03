"""Dafny CLI adapter. Full-file validation and observed per-callable batches."""
from dataclasses import asdict, dataclass, field
import csv
import hashlib
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import shutil

# Reuse the existing tested diagnostic parser and local Dafny configuration.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
import config
from dafny_wrapper import DafnyVerifier as LegacyParser


@dataclass
class Result:
    status: str
    diagnostics: list = field(default_factory=list)
    obligations: dict = field(default_factory=dict)
    raw: str = ""
    returncode: int | None = None
    seconds: float = 0
    command: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def classify(output, returncode, obligations):
    lower = output.lower()
    if "timed out" in lower or "timeout" in lower:
        return "timeout"
    if re.search(r"(?:parse|resolution(?:/type)?) errors? detected", lower):
        return "compile_error"
    if any(x in lower for x in ("inconclusive", "unknown", "out of resource")):
        return "unknown"
    summary = re.search(r"finished with\s+(\d+)\s+verified,\s*(\d+)\s+errors?", output)
    if summary and int(summary[2]):
        return "verification_failed"
    if (returncode == 0 and summary and int(summary[1]) > 0 and obligations
            and all(x == "passed" for x in obligations.values())):
        return "passed"
    if returncode not in {0, 4}:
        return "tool_error"
    # Includes empty files / missing structured logs / unexpected verifier output.
    return "unknown"


class Dafny:
    def __init__(self, path=None, timeout=20):
        self.path = path or config.DAFNY_PATH
        self.timeout = timeout
        self.solver = config.DAFNY_SOLVER_PATH

    def version(self):
        try:
            return subprocess.run([self.path, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return type(exc).__name__

    def identity(self):
        def file_hash(path):
            if not path or not Path(path).is_file():
                return None
            h = hashlib.sha256()
            with Path(path).open('rb') as handle:
                for block in iter(lambda: handle.read(1048576), b''):
                    h.update(block)
            return h.hexdigest()
        binary = str(Path(shutil.which(self.path) or self.path).resolve())
        distribution = Path(binary).parent
        return {"version": self.version(), "executable": binary, "sha256": file_hash(binary),
                "solver_path": self.solver or "bundled", "solver_sha256": file_hash(self.solver),
                "driver_sha256": file_hash(distribution / 'DafnyDriver.dll'),
                "bundled_solver_candidates": {p.name: file_hash(p) for p in sorted((distribution / 'z3' / 'bin').glob('z3*')) if p.is_file()},
                "solver_selection": "explicit" if self.solver else "Dafny default; candidates fingerprinted, selected version not independently observed",
                "python": platform.python_version(), "platform": platform.platform(),
                "timeout_seconds": self.timeout, "cores": 1}

    def verify(self, source, *, timeout=None):
        started = time.monotonic()
        limit = max(1, min(self.timeout, timeout or self.timeout))
        with tempfile.TemporaryDirectory(prefix="contract-repair-") as directory:
            root = Path(directory)
            program, report = root / "program.dfy", root / "results.csv"
            program.write_text(source)
            command = [self.path, "verify", str(program), "--allow-warnings", "--cores", "1",
                       "--verification-time-limit", str(int(limit)),
                       "--log-format", f"csv;LogFileName={report}"]
            if self.solver:
                command += ["--solver-path", self.solver]
            try:
                completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=limit)
                raw = completed.stdout + completed.stderr
                obligations = {}
                if report.exists():
                    with report.open() as handle:
                        for row in csv.DictReader(handle):
                            name = row.get("TestResult.DisplayName", "")
                            outcome = row.get("TestResult.Outcome", "").lower()
                            if name:
                                if name in obligations:
                                    obligations[name] = "unknown"  # ambiguous batch identity
                                else:
                                    obligations[name] = outcome
                parser = LegacyParser(self.path)
                errors = [asdict(x) for x in parser._parse_diagnostics(raw)]
                status = classify(raw, completed.returncode, obligations)
                return Result(status, errors, obligations, raw, completed.returncode,
                              time.monotonic() - started, command)
            except subprocess.TimeoutExpired:
                return Result("timeout", raw="whole verifier process exceeded timeout",
                              seconds=time.monotonic() - started, command=command)
            except OSError as exc:
                return Result("tool_error", raw=f"{type(exc).__name__}: {exc}",
                              seconds=time.monotonic() - started, command=command)
