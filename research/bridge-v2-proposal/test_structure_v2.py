"""Independent proposal tests; production bridge remains frozen during canary."""
import importlib.util
from pathlib import Path
import pytest


def bridge():
    path = Path(__file__).with_name("structure.py")
    spec = importlib.util.spec_from_file_location("structure_v2_proposal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BUILD_MANIFEST = Path(__file__).parent / "cache/build.json"
    return module


def slice_utf16(source, region):
    raw = source.encode("utf-16-le")
    return raw[region[0]*2:region[1]*2].decode("utf-16-le")


@pytest.mark.parametrize("prefix,suffix", [
    ("// pi\n", ""), ("// pi\r\n", ""),
    ("// π ∨ x₁\n", ""), ("// π\n", "\n// padding trailing chars"),
    ("// 😀\n", ""), ("\ufeff", ""),
])
def test_regions_match_original_source_and_preserve_newlines(prefix, suffix):
    source = prefix + "method M() ensures true {}" + suffix
    report = bridge().inspect_source(source)
    assert report["status"] == "ok", report
    declaration = report["declarations"][0]
    assert declaration["source_region"] == [len(prefix.encode("utf-16-le"))//2, len((prefix+"method M() ensures true {}").encode("utf-16-le"))//2]
    assert slice_utf16(source, declaration["source_region"]) == declaration["header"] + declaration["body"]
    assert slice_utf16(source, declaration["body_region"]) == "{}"
    assert declaration["header_tokens"] == ["method", "M", "(", ")", "ensures", "true"]


def test_unicode_literal_with_following_declaration_and_contract_freeze():
    module = bridge()
    original = 'method A() { print "π😀"; }\nmethod B() ensures true {}'
    altered = original.replace('print "π😀";', 'print "✓";')
    before, after = module.inspect_source(original), module.inspect_source(altered)
    assert before["status"] == after["status"] == "ok", (before, after)
    assert module.compare_frozen(before, after, {"A"}) == []
    for declaration in before["declarations"]:
        assert slice_utf16(original, declaration["source_region"]) == declaration["header"] + declaration["body"]


def test_non_ascii_identifier_is_compiler_error_not_region_failure():
    source = "function caf\u00e9(x: int): int { x }"
    report = bridge().inspect_source(source)
    assert report["status"] == "parse_error", report
    assert report["findings"][0]["code"] == "compiler_diagnostic"
