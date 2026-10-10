"""Fail-closed Dafny 4.11 structure inspection using the real managed compiler.

PowerShell hosts the bundled DafnyCore assembly; it does not parse Dafny itself.
The accepted profile currently contains top-level functions, predicates, methods
and lemmas. Other declaration forms are reported as unsupported, never accepted
by a fallback grammar. Inspection is not verification or semantic admission.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DAFNY_HOME = ROOT / ".tools/dafny/4.11.0"
BRIDGE = Path(__file__).with_name("structure_bridge.ps1")
BUILD_MANIFEST = ROOT / ".tools/public-structure-bridge/build.json"
LIMITATIONS = [
    "Only default-module top-level functions, predicates, methods and lemmas are supported.",
    "All source attributes, imports, includes, higher-order calls and bodyless constructs are rejected.",
    "Dependencies are resolved declaration references, not SMT VC dependencies.",
    "Source regions use UTF-16 code units converted from Dafny UTF-8 token offsets.",
    "Parser acceptance does not establish verification, satisfiability or natural-language adequacy.",
]


def _tokens(source: str):
    """Deny-only preflight, preventing include I/O and option mutation before parsing.

    This lexer is never evidence for acceptance. Dafny must subsequently parse and
    resolve every accepted file, and its AST is independently checked.
    """
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end + 1
        elif source.startswith("/*", i):
            depth, i = 1, i + 2
            while i < len(source) and depth:
                if source.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif source.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
        elif source.startswith('@"', i):
            i += 2
            while i < len(source):
                if source.startswith('""', i):
                    i += 2
                elif source[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
        elif source[i] in "\"'":
            quote, i = source[i], i + 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                elif source[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
        elif source[i].isalpha() or source[i] == "_":
            start = i
            i += 1
            while i < len(source) and (source[i].isalnum() or source[i] in "_?'`"):
                i += 1
            yield source[start:i]
        elif source[i].isspace():
            i += 1
        else:
            yield source[i]
            i += 1


def _failure(status: str, code: str, message: str) -> dict:
    return {"schema_version": 1, "status": status, "trusted_ast": False,
            "declarations": [], "expected_verifier_targets": [],
            "findings": [{"code": code, "message": message}],
            "limitations": LIMITATIONS}


def inspect_source(source: str) -> dict:
    """Inspect a complete candidate. Only ``status == 'ok'`` is acceptable."""
    if not isinstance(source, str) or len(source.encode("utf-8")) > 2_000_000:
        return _failure("rejected", "source_limit", "Source must be text of at most 2 MB.")
    tokens = list(_tokens(source))
    if "include" in tokens or "import" in tokens:
        return _failure("rejected", "external_source", "Imports/includes are disallowed before parser file access.")
    if any(tokens[i:i+3] == ["{", ":", "options"] for i in range(len(tokens)-2)):
        return _failure("rejected", "attribute", "Source-controlled parser options are disallowed.")
    pwsh = shutil.which("pwsh")
    if not pwsh or not (DAFNY_HOME / "DafnyCore.dll").is_file():
        return _failure("tool_error", "bridge_unavailable", "PowerShell Core and bundled Dafny 4.11.0 are required.")
    if not BUILD_MANIFEST.is_file():
        return _failure("tool_error", "bridge_unavailable", "Explicit bridge prebuild is required before inspection.")
    try:
        with tempfile.TemporaryDirectory(prefix="dafny-structure-") as scratch:
            source_file = Path(scratch) / "candidate.dfy"
            source_file.write_bytes(source.encode("utf-8"))
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-NonInteractive", "-File", str(BRIDGE),
                 "-DafnyHome", str(DAFNY_HOME), "-SourceFile", str(source_file),
                 "-BuildManifest", str(BUILD_MANIFEST)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
            )
        if completed.returncode:
            return _failure("tool_error", "bridge_failed", (completed.stderr or completed.stdout)[-6000:])
        report = json.loads(completed.stdout)
        if report.get("schema_version") != 1 or report.get("status") not in {
            "ok", "rejected", "parse_error", "resolution_error", "tool_error"
        }:
            raise ValueError("Invalid compiler bridge response")
        report["limitations"] = LIMITATIONS
        report["source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        report["toolchain"] = {
            "compiler": "Dafny 4.11.0", "bridge": "managed-parser-and-resolver",
            "dafny_core_sha256": hashlib.sha256((DAFNY_HOME / "DafnyCore.dll").read_bytes()).hexdigest(),
            "bridge_sha256": hashlib.sha256(
                Path(__file__).read_bytes() + BRIDGE.read_bytes() + BRIDGE.with_suffix(".cs").read_bytes()
            ).hexdigest(),
            "host_runtime": report.pop("bridge_runtime", "unknown"),
            "precompiled_bridge": report.pop("bridge_cache", None),
        }
        return report
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return _failure("tool_error", "bridge_failed", str(error))


def compare_frozen(frozen: dict, candidate: dict, editable_ids=()) -> list[dict]:
    """Compare parser-derived tokens and resolved spec bindings, never raw regex.

    Only listed declaration bodies may change. New helper declarations may be
    added provided they pass the same guard and cannot change fixed spec binding.
    Frozen shared functions/definitions must have identical complete AST tokens.
    """
    if any(r.get("status") != "ok" or not r.get("trusted_ast") for r in (frozen, candidate)):
        return [{"code": "untrusted_structure", "message": "Both files require successful trusted inspection."}]
    old = {d["id"]: d for d in frozen["declarations"]}
    new = {d["id"]: d for d in candidate["declarations"]}
    editable = set(editable_ids)
    findings = []
    for key, declaration in old.items():
        replacement = new.get(key)
        if replacement is None:
            findings.append({"code": "missing_declaration", "declaration": key})
        elif declaration["header_tokens"] != replacement["header_tokens"] or declaration["contract_bindings"] != replacement["contract_bindings"]:
            findings.append({"code": "contract_changed", "declaration": key})
        elif key not in editable and declaration["tokens"] != replacement["tokens"]:
            findings.append({"code": "frozen_definition_changed", "declaration": key})
    return findings
