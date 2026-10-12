import copy
import pytest

from research.edit_scope_20261012 import assemble, validate_candidate, make_tasks, model_feedback, infrastructure_failure


def test_proof_arm_rejects_executable_change_but_joint_allows_it():
    task=make_tasks()[0]
    proposal=copy.deepcopy(task['initial'])
    proposal['step']+=' s := s + 1;'
    assert 'executable_edit' in validate_candidate(task,proposal,'P')
    assert validate_candidate(task,proposal,'J')==[]


def test_proof_arm_can_change_invariants_without_changing_body():
    task=make_tasks()[0]
    proposal=copy.deepcopy(task['reference'])
    assert validate_candidate(task,proposal,'P')==[]
    assert 'ensures' in assemble(task,proposal)


@pytest.mark.parametrize('payload',['true; s := 0; assert true','true } method Hack() {','true // comment','true /* comment */','true {:axiom}'])
def test_annotation_slots_reject_statement_or_attribute_injection(payload):
    task=make_tasks()[0]
    proposal=copy.deepcopy(task['initial'])
    proposal['invariants']=[payload]
    assert validate_candidate(task,proposal,'P')


def test_joint_cannot_add_loop_or_use_assumptions():
    task=make_tasks()[0]
    for code in ['assume false;','while false {}','for k := 0 to 1 {}']:
        proposal=copy.deepcopy(task['initial']);proposal['step']=code
        assert validate_candidate(task,proposal,'J')


def test_wrong_shape_and_unknown_fields_are_rejected():
    task=make_tasks()[0]
    proposal=copy.deepcopy(task['initial']);proposal['spec']='ensures true'
    assert validate_candidate(task,proposal,'J')
    assert validate_candidate(task,[], 'P')


def test_labels_and_references_not_needed_to_assemble():
    task=make_tasks()[0]
    public={k:v for k,v in task.items() if k not in ('reference','cohort','witness')}
    assert assemble(public,task['initial'])==assemble(task,task['initial'])


def test_model_feedback_excludes_local_paths_commands_and_raw_streams():
    e={'findings':[], 'verification':{'status':'verification_failed','command':['secret/local/path'],
       'stdout':'local/path','stderr':'local/path','diagnostics':[{'message':'failed','location_line':4}],
       'obligations':{'Solve (correctness)':'failed'}}}
    f=model_feedback(e)
    assert f['verification']['diagnostics'][0]['message']=='failed'
    assert 'local/path' not in str(f)
    assert 'command' not in f['verification']


@pytest.mark.parametrize('e',[{'structure':{'status':'tool_error'},'verification':None},
    {'structure':None,'verification':{'status':'tool_error'}},
    {'structure':None,'verification':{'status':'unknown'}}])
def test_verifier_infrastructure_failure_terminates(e):
    assert infrastructure_failure(e)
