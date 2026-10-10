"""Reference challenge evidence uses exact saved input bytes and real Dafny."""
import hashlib
import importlib


def module():
    return importlib.import_module("generation.public_benchmark.reference_challenge")


def test_archive_preserves_raw_reference_and_admission_newline_normalization(tmp_path):
    reference = tmp_path / "original.dfy"
    raw = b'// \xcf\x80\r\nmethod M()\r ensures true\n{}\r\n'
    reference.write_bytes(raw)
    source, receipt = module().archive_reference(reference, tmp_path / "audit")
    assert source == reference.read_text(encoding="utf-8")
    assert (tmp_path / "audit/original-reference.dfy").read_bytes() == raw
    expected = source.encode("utf-8")
    assert (tmp_path / "audit/normalized-reference.dfy").read_bytes() == expected
    assert receipt["original_raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["actual_input_sha256"] == hashlib.sha256(expected).hexdigest()


def test_real_reference_verification_binds_saved_input_hash(tmp_path):
    source = tmp_path / "normalized-reference.dfy"
    source.write_bytes(b"method M() ensures true {}\n")
    primary = {"id": "M", "name": "M", "kind": "method", "verifier_names": ["M"]}
    evidence = module().verify_saved_reference(source, primary)
    assert evidence["status"] == "verified", evidence
    assert evidence["executed"] and evidence["real_verifier"]
    assert evidence["actual_input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert evidence["saved_input_path"] == str(source.resolve())
    assert evidence["verifier_identity"]["source_newline_translation"] is False
    assert evidence["command"][evidence["command"].index("--cores") + 1] == "1"
    assert evidence["primary_batches"] == {"M (correctness)": "passed"}
