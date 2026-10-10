from generation.public_benchmark.policy import EvidenceLedger, choose_target, build_messages


def decl(name, deps=(), order=0):
    return {'id':name, 'name':name, 'depends_on':list(deps), 'order':order, 'kind':'method'}


def test_local_pass_does_not_close_caller_with_failed_callee():
    ledger = EvidenceLedger([decl('Caller', ['Leaf']), decl('Leaf')])
    ledger.observe('v1', {'Caller':'passed', 'Leaf':'failed'})
    assert ledger.rows['Caller']['status'] == 'locally_passed'
    assert ledger.rows['Leaf']['status'] == 'failed'
    assert choose_target(ledger, 'D')['id'] == 'Leaf'


def test_complete_mutual_recursion_closes_as_group_and_missing_dependency_does_not():
    ledger = EvidenceLedger([decl('A',['B']), decl('B',['A']), decl('C',['Missing'])])
    ledger.observe('v1', {'A':'passed', 'B':'passed', 'C':'passed'})
    assert ledger.rows['A']['status'] == ledger.rows['B']['status'] == 'closed'
    assert ledger.rows['C']['status'] == 'locally_passed'


def test_new_revision_invalidates_evidence_and_parse_failure_is_not_regression():
    ledger = EvidenceLedger([decl('A')])
    ledger.observe('v1', {'A':'passed'})
    ledger.begin('v2')
    assert ledger.rows['A']['status'] == 'stale'
    ledger.observe('v2', {}, [{'target':'A','category':'parse_error'}])
    assert ledger.rows['A']['status'] == 'unknown'
    assert ledger.metrics['proof_regressions'] == 0
    assert choose_target(ledger, 'D')['reason'] == 'parse_or_type_blocker'
    assert choose_target(ledger, 'C')['reason'] == 'parse_or_type_blocker'


def test_explicit_regression_records_once_per_candidate():
    ledger = EvidenceLedger([decl('A')])
    ledger.observe('v1', {'A':'passed'})
    ledger.observe('v2', {'A':'failed'})
    ledger.observe('v2', {'A':'failed'})
    assert ledger.metrics['proof_regressions'] == 1


def test_adaptive_priority_differs_from_fixed_order_without_different_information():
    ledger = EvidenceLedger([decl('Early',order=0), decl('Late',order=1)])
    ledger.observe('v1', {'Early':'unknown','Late':'failed'})
    assert choose_target(ledger,'C')['id'] == 'Early'
    assert choose_target(ledger,'D')['id'] == 'Late'
    ledger.record_action('Late')
    ledger.observe('v2', {'Early':'unknown','Late':'failed'})
    ledger.record_action('Late')
    ledger.observe('v3', {'Early':'unknown','Late':'failed'})
    assert choose_target(ledger,'D')['id'] == 'Early'


def test_fixed_order_visits_dependency_before_caller():
    ledger = EvidenceLedger([decl('Caller',['Leaf'],0),decl('Leaf',order=1)])
    assert choose_target(ledger,'C')['id'] == 'Leaf'


def test_all_arms_share_raw_inputs_and_acceptance_no_reference_leaks():
    task={'id':'t', 'description':'task', 'frozen_source':'method F() ensures true',
          'editable_regions':['implementation','helpers'], 'reference':'SECRET_REFERENCE'}
    ledger=EvidenceLedger([decl('F')])
    history=[{'stdout':'FULL_RAW_DIAGNOSTIC'}]
    import json
    contents={arm:json.loads(build_messages(task,'candidate',history,ledger,arm)[1]['content'])
              for arm in 'ABCD'}
    for value in contents.values():
        assert value['history'] == history
        assert value['current_source'] == 'candidate'
        assert 'reference' not in value['task']
    assert 'evidence_state' not in contents['A']
    assert contents['B']['evidence_state'] == contents['C']['evidence_state'] == contents['D']['evidence_state']
    assert 'target' not in contents['B']


def test_unknown_arm_and_untrusted_status_fail_closed():
    import pytest
    ledger=EvidenceLedger([decl('F')])
    with pytest.raises(ValueError): choose_target(ledger,'legacy_guided')
    with pytest.raises(ValueError): ledger.observe('v1',{'F':'model_says_correct'})


def test_fixed_public_definitions_remain_evidence_but_are_not_generation_targets():
    frozen={**decl('Fixed',order=0),'editable':False}
    target={**decl('Solve',['Fixed'],1),'editable':True}
    ledger=EvidenceLedger([frozen,target])
    for arm in ['C','D']:
        assert choose_target(ledger,arm)['id']=='Solve'
    assert 'Fixed' in ledger.snapshot()['declarations']


def test_regression_survives_invalid_and_unknown_intermediate_revisions():
    ledger=EvidenceLedger([decl('A')])
    ledger.observe('v1',{'A':'passed'})
    ledger.begin('invalid')
    ledger.observe('unknown',{})
    ledger.observe('v4',{'A':'failed'})
    assert ledger.metrics['proof_regressions']==1


def test_c_rotation_does_not_reset_when_other_proofs_progress():
    ledger=EvidenceLedger([decl('A'),decl('B',order=1)])
    ledger.record_action('A'); ledger.observe('v1',{'A':'failed','B':'passed'})
    ledger.record_action('A'); ledger.observe('v2',{'A':'failed','B':'unknown'})
    assert choose_target(ledger,'C')['id']=='B'


def test_same_target_and_state_produce_identical_c_d_prompts():
    task={'id':'t','description':'task','frozen_source':'method F()','editable_regions':[]}
    ledger=EvidenceLedger([decl('F')])
    assert build_messages(task,'',[],ledger,'C')==build_messages(task,'',[],ledger,'D')
