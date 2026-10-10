from generation.public_benchmark.structure import inspect_source
from generation.public_benchmark.runner import _diagnostics
from generation.representation.verifier import Dafny


def test_actual_unicode_verifier_diagnostic_maps_to_correct_declaration():
    source='// π🙂\nmethod A() ensures true {}\n// 中文\nmethod B() ensures false {}\n// '+('padding '*20)
    structure=inspect_source(source)
    assert structure['status']=='ok'
    report=Dafny(timeout=30).verify(source,names=('A','B')).to_dict()
    assert report['status']=='verification_failed'
    mapped=_diagnostics(report,source,structure,'A')
    assert mapped and any(d['target']=='B' for d in mapped)
    assert all(d['target']=='B' for d in mapped)
