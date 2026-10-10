import pytest
from generation.public_benchmark.families import validate_groups, combine, choose_representatives


def test_missing_reviewed_id_and_foreign_member_rejected():
    with pytest.raises(ValueError): validate_groups({'reviewed_ids':['a'],'duplicate_groups':[]},['a','b'])
    with pytest.raises(ValueError): validate_groups({'reviewed_ids':['a','b'],'duplicate_groups':[{'ids':['a','z'],'reason':'same'}]},['a','b'])


def test_conservative_union_propagates_dev_split_across_sources():
    rows=combine(['a','b','c','d'],[['a','b'],['b','c']],{'a'})
    assert rows['a']['family_id']==rows['c']['family_id']
    assert rows['c']['split']=='development'
    assert rows['d']['split']=='test'


def test_removed_development_task_still_protects_its_remaining_family():
    rows=combine(['test'],[['dev','intermediate'],['intermediate','test']],{'dev'})
    assert rows['test']['split']=='development'


def test_representatives_use_reference_structure_and_never_exposed_family():
    tasks={'dev':{'family_id':'f1','split':'development'},
           'simple':{'family_id':'f2','split':'test'},'rich':{'family_id':'f2','split':'test'}}
    metrics={i:{'extra_helpers':int(i=='rich'),'reference_tokens':10} for i in tasks}
    assert choose_representatives(tasks,metrics)==['rich']
    assert tasks['dev']['split']=='development'
