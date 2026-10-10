import pytest
from generation.public_benchmark.task import PublicTask


def record():
    return {'id':'T1','source':'test','source-id':'origin1','vc-description':'Return x+1.',
        'vc-preamble':'function Inc(x:int): int { x+1 }','vc-helpers':'',
        'vc-spec':'method Solve(x:int) returns (y:int)\n ensures y == Inc(x)',
        'vc-code':'{ assume {:axiom} false; }','vc-postamble':''}


def test_assembly_only_takes_explicit_regions_and_never_publishes_reference():
    task=PublicTask(record(),family_id='family')
    source=task.assemble({'implementation':'{ y := x+1; }','helpers':''})
    assert source.startswith('function Inc')
    assert 'ensures y == Inc(x)' in source
    assert 'assume' not in source
    assert 'assume' not in task.public()['frozen_source']
    assert set(task.public()) == {'id','description','frozen_source','editable_regions'}
    with pytest.raises(ValueError):task.assemble({'implementation':'{}','helpers':'','spec':'ensures true'})


def test_bad_schema_and_placeholder_cannot_silently_become_candidate():
    task=PublicTask(record(),family_id='family')
    for candidate in [{'implementation':None,'helpers':''}, {'implementation':'{}'}, []]:
        with pytest.raises(ValueError):task.assemble(candidate)


def test_source_identity_changes_if_frozen_spec_changes():
    row=record();first=PublicTask(row,family_id='family')
    row['vc-spec']+='\n ensures y > x'
    second=PublicTask(row,family_id='family')
    assert first.spec_sha256 != second.spec_sha256
    assert first.record_sha256 != second.record_sha256
