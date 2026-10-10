"""Isolated scratch caches: production receipt and bridge are never modified."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parents[1]


@pytest.fixture
def cache(tmp_path):
    for name in ("structure_bridge.cs", "structure_bridge.ps1", "build_structure_bridge.ps1"):
        shutil.copyfile(HERE / name, tmp_path / name)
    command = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File",
        str(tmp_path / "build_structure_bridge.ps1"), "-DafnyHome", str(ROOT / ".tools/dafny/4.11.0"),
        "-CacheRoot", str(tmp_path / "cache")]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert completed.returncode == 0, completed.stderr
    spec = importlib.util.spec_from_file_location("cache_proposal", HERE / "structure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BRIDGE = tmp_path / "structure_bridge.ps1"
    module.BUILD_MANIFEST = tmp_path / "cache/build.json"
    return module, tmp_path, command


def test_prebuilt_inspection_records_actual_binary_and_receipt_hash(cache):
    import hashlib
    module, _, _ = cache
    result = module.inspect_source("method M() ensures true {}")
    assert result["status"] == "ok", result
    receipt = json.loads(module.BUILD_MANIFEST.read_text())
    evidence = result["toolchain"]["precompiled_bridge"]
    assert evidence["key"] == receipt["key"]
    assert evidence["dll_sha256"] == hashlib.sha256(Path(receipt["dll_path"]).read_bytes()).hexdigest()
    assert evidence["receipt_sha256"] == hashlib.sha256(module.BUILD_MANIFEST.read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["dll", "cs", "wrapper", "builder", "runtime", "dafny"])
def test_damaged_or_stale_cache_is_rejected_without_rebuilding(cache, change):
    module, root, _ = cache
    receipt = json.loads(module.BUILD_MANIFEST.read_text())
    receipt_before = module.BUILD_MANIFEST.read_bytes()
    if change == "dll":
        dll = Path(receipt["dll_path"])
        dll.write_bytes(b"damaged" + dll.read_bytes()[7:])
    elif change in {"cs", "wrapper", "builder"}:
        name = {"cs": "structure_bridge.cs", "wrapper": "structure_bridge.ps1", "builder": "build_structure_bridge.ps1"}[change]
        path = root / name
        path.write_bytes(path.read_bytes() + (b"\n// stale" if change == "cs" else b"\n# stale"))
    else:
        field = "powershell" if change == "runtime" else "dafny_core_sha256"
        receipt["identity"][field] = "invalid"
        module.BUILD_MANIFEST.write_text(json.dumps(receipt), encoding="utf8")
        receipt_before = module.BUILD_MANIFEST.read_bytes()
    result = module.inspect_source("method M() {}")
    assert result["status"] == "tool_error", result
    assert result["trusted_ast"] is False
    assert module.BUILD_MANIFEST.read_bytes() == receipt_before


def test_explicit_builder_refuses_to_overwrite_frozen_receipt(cache):
    module, root, command = cache
    before = module.BUILD_MANIFEST.read_bytes()
    source = root / "structure_bridge.cs"
    source.write_bytes(source.read_bytes() + b"\n// new version")
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert completed.returncode != 0
    assert "refusing overwrite" in completed.stderr
    assert module.BUILD_MANIFEST.read_bytes() == before
