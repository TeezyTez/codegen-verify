"""Protocol invariants and real Dafny end-to-end checks (when installed)."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repair.analyze import summarize
from repair.dependencies import build_graph, regressions, schedule
from repair.models import Replay
from repair.runner import CONDITIONS, Limits, run
from repair.task import BoundaryError, Task, validate_region, validate_splits
from repair.verifier import Dafny, Result, classify

ROOT = Path(__file__).resolve().parents[1]


def task(name='counter'):
    return Task.load(ROOT / 'repair' / 'tasks' / name / 'task.json')


@pytest.mark.parametrize('text', [
    'assume false;', 'assert true; r := 0;', 'invariant true\n r := 0;',
    'invariant true /*', 'invariant true //', 'invariant true\n}',
    'assert {:axiom} false;', 'assert true;\nassume false;',
])
def test_proof_regions_reject_implementation_and_bypasses(text):
    with pytest.raises(BoundaryError):
        validate_region(text, 'invariants')


@pytest.mark.parametrize('text', [
    'r := 0; } method F() {', 'assume false;', '{:verify false}',
    'while true decreases * {}', 'r := *;', 'var a :| true;',
    'import X', 'expect false;', '/* comment */',
])
def test_implementation_regions_reject_escapes(text):
    with pytest.raises(BoundaryError):
        validate_region(text, 'implementation')


def test_immutable_contract_and_scope():
    t = task()
    source = t.render(t.regions(t.original))
    with pytest.raises(BoundaryError):
        t.check_final(source.replace('ensures r == n', 'ensures true'))
    with pytest.raises(BoundaryError):
        t.apply(source, {'not_a_region': 'assert true;'})
    with pytest.raises(BoundaryError):
        t.apply(source, {'count_invariants': 'r := 0;'})


@pytest.mark.parametrize('output,code,batches,expected', [
    ('Dafny program verifier finished with 1 verified, 0 errors',0,{'F':'passed'},'passed'),
    ('Dafny program verifier finished with 0 verified, 0 errors',0,{},'unknown'),
    ('Dafny program verifier finished with 1 verified, 0 errors',0,{},'unknown'),
    ('Dafny program verifier finished with 1 verified, 1 error',4,{'F':'failed'},'verification_failed'),
    ('1 parse errors detected',2,{},'compile_error'),
    ('1 resolution/type error detected',2,{},'compile_error'),
    ('verification timed out',4,{},'timeout'),
    ('inconclusive',4,{},'unknown'),
    ('cannot start solver',1,{},'tool_error'),
])
def test_statuses(output,code,batches,expected):
    assert classify(output,code,batches) == expected


def test_graph_is_labeled_and_does_not_infer_failed_callers():
    t = task()
    graph = build_graph(t.original)
    assert any(e['from']=='Twice' and e['to']=='Count' for e in graph['edges'])
    assert graph['confirmed_logical_edges'] == []
    assert schedule(t, graph, {'Count (correctness)':'failed'})['region'] == 'count_invariants'
    delta = regressions({'Count':'failed','Client':'passed'}, {'Count':'passed','Client':'failed'})
    assert delta['confirmed'] == ['Client']
    assert regressions({'Client':'passed'}, {})['lost_observability'] == ['Client']


def test_graph_blank_lines_are_not_self_calls_and_locations_are_exact():
    source = 'method A() {}\n\nmethod B() { A(); }\n'
    graph = build_graph(source, [{'location_line': 3}])
    assert graph['nodes']['B']['start_line'] == 3
    assert graph['reported_failures'][0]['owners'] == ['B']
    assert [(e['from'],e['to']) for e in graph['edges']] == [('B','A')]
    recursive = build_graph('method R() { R(); }\n')
    assert recursive['edges'][0]['to'] == 'R'


def test_graph_rejects_ambiguous_names():
    with pytest.raises(ValueError, match='duplicate callable'):
        build_graph('method F() {}\nmethod F() {}\n')


def test_graph_contract_and_helper_edges_are_distinct():
    graph = build_graph('predicate P(x:int) { true }\nlemma L() {}\nmethod M(x:int)\n  requires P(x)\n{\n  L();\n}\n')
    assert {e['kind'] for e in graph['edges']} == {'contract_reference','proof_helper_reference'}


def test_project_split_leakage():
    a,b = task(), task('arithmetic')
    b.meta['split'] = 'test'
    with pytest.raises(ValueError, match='crosses splits'):
        validate_splits([a,b])


class FakeVerifier:
    def __init__(self, final='passed'):
        self.calls=0
        self.final=final
    def version(self):
        return 'fake-unit-test-only'
    def verify(self, source, timeout=None):
        self.calls += 1
        status = 'verification_failed' if self.calls == 1 else ('passed' if self.calls == 2 else self.final)
        return Result(status, obligations={'Count (correctness)':'passed' if status=='passed' else 'failed'})


def replay(t):
    return Replay([{'action':'patch','replacements':json.loads((t.path.parent/'reference.json').read_text())}])


def test_final_reverification_overrides_intermediate_success(tmp_path):
    t=task()
    v=FakeVerifier('timeout')
    result=run(t,replay(t),v,tmp_path/'run')
    assert v.calls==3
    assert not result['success']
    assert result['stop_reason']=='final_reverification_failed'


def test_budget_and_replay_separation(tmp_path):
    t=task()
    result=run(t,replay(t),FakeVerifier(),tmp_path/'budget',limits=Limits(verifier_calls=2))
    assert not result['success'] and result['usage']['model_calls']==0
    result=run(t,replay(t),FakeVerifier(),tmp_path/'normal')
    assert result['success'] and not result['research_eligible']
    summary=summarize(tmp_path/'normal')
    assert summary['research']==[] and summary['scripted_diagnostics']


def test_unknown_usage_is_not_free_and_token_budget_stops_before_model(tmp_path):
    result=run(task(),replay(task()),FakeVerifier(),tmp_path/'tiny',limits=Limits(total_tokens=1))
    assert result['usage']['model_calls']==0
    assert result['stop_reason']=='token_budget_exhausted'


@pytest.mark.parametrize('condition', CONDITIONS)
def test_condition_prompts_and_tool_permissions(tmp_path, condition):
    run(task(),replay(task()),FakeVerifier(),tmp_path/condition,condition=condition)
    prompt=json.loads((tmp_path/condition/'prompt_001.json').read_text())
    assert prompt['tools']==['read','patch','verify','stop']
    assert ('dependencies' in prompt)==(condition in {'dependency','no_schedule'})
    assert ('suggested_repair' in prompt)==(condition in {'dependency','no_dependencies'})
    assert 'reference.json' not in json.dumps(prompt)


def test_real_dafny_task_admission_and_repair(tmp_path):
    v=Dafny(timeout=15)
    if not v.version().startswith('4.11.'):
        pytest.skip('real Dafny 4.11 not installed')
    for t in [task('counter'),task('arithmetic'),task('clover_double'),task('clover_array')]:
        assert v.verify((t.path.parent/'original.dfy').read_text()).status=='passed'
        assert v.verify(t.original).status=='verification_failed'
        result=run(t,Replay(json.loads((t.path.parent/'replay.json').read_text())),v,tmp_path/t.meta['id'])
        assert result['success'], result
        assert result['usage']['verifier_calls']>=3
        if t.meta['id']=='arithmetic-implementation':
            assert result['regressions']>=1 and result['boundary_rejections']==1
        assert v.verify((tmp_path/t.meta['id']/'final.dfy').read_text()).status=='passed'


def test_tool_error_and_timeout(tmp_path, monkeypatch):
    assert Dafny('/definitely/missing/dafny').verify('method F() {}').status=='tool_error'
    def expire(*a, **k):
        raise subprocess.TimeoutExpired('dafny', 1)
    monkeypatch.setattr(subprocess, 'run', expire)
    assert Dafny('dafny').verify('method F() {}').status=='timeout'


def test_provider_failure_and_malformed_json_recover_with_budget(tmp_path):
    class FlakyReplay(Replay):
        def generate(self, *args):
            if self.index == 0:
                self.index += 1
                raise ConnectionError('unit-test only')
            if self.index == 1:
                self.index += 1
                return dict(text='not json', input_tokens=None, output_tokens=None, cost_usd=None)
            return super().generate(*args)
    t = task()
    reference = json.loads((t.path.parent/'reference.json').read_text())
    result = run(t, FlakyReplay([{}, {}, {'action':'patch','replacements':reference}]),
                 FakeVerifier(), tmp_path/'recovery')
    assert result['success'] and result['usage']['model_calls'] == 3
    assert result['usage']['cost_usd'] is None
    assert result['usage']['unknown_usage_calls'] == 3
    assert result['boundary_rejections'] == 1


def test_live_requires_explicit_authorization_before_provider(tmp_path):
    from repair.cli import main
    with pytest.raises(SystemExit) as exc:
        main(['run', '--model', 'live', '--output', str(tmp_path/'unauthorized')])
    assert exc.value.code == 2
    assert not (tmp_path/'unauthorized').exists()


def test_provider_missing_usage_is_unknown_without_network(monkeypatch):
    from types import SimpleNamespace
    from repair.models import Provider
    from repair.verifier import config
    import llm_client
    options = []
    class Transport:
        def with_options(self, **kwargs):
            options.append(kwargs)
            return self
    original = Transport()
    model = Provider.__new__(Provider)  # Do not construct an API client.
    model.client = SimpleNamespace(client=original, chat=lambda **kwargs: '{}')
    model.input_price = model.output_price = 1
    old_retries = config.LLM_RETRIES
    monkeypatch.setattr(llm_client, 'get_usage_metrics', lambda *args: dict(
        calls=1, successful_calls=1, prompt_tokens=0, completion_tokens=0))
    result = model.generate('unit-test request', 8, 2)
    assert result['input_tokens'] is None and result['cost_usd'] is None
    assert options == [{'timeout':2,'max_retries':0}]
    assert config.LLM_RETRIES == old_retries and model.client.client is original


def test_failed_admission_prevents_live_client_creation(tmp_path, monkeypatch):
    import repair.cli as cli
    monkeypatch.setattr(cli, 'Dafny', lambda *args: FakeVerifier())
    def forbidden_client(**kwargs):
        pytest.fail('must not construct a client after failed admission')
    monkeypatch.setattr(cli, 'Provider', forbidden_client)
    status = cli.main(['run','--task',str(task().path),'--model','live','--allow-paid',
                       '--output',str(tmp_path/'admission')])
    assert status == 1
