import pytest
from research.public_scope_20261012 import expression_ok,assemble,strip_comments,extract_task


@pytest.mark.parametrize('e',['multiset(a[..]) == multiset(old(a[..]))','m == multiset{}','forall k :: 0 <= k < i ==> a[k] <= x','if i == 0 then true else a[i-1] <= x'])
def test_balanced_expressions(e):
    assert expression_ok(e)


@pytest.mark.parametrize('e',['true); return; assert (true','true) {} (true','true // x','true\nreturn','true {:axiom}','assume false','a := b'])
def test_expression_cannot_escape_inserted_context(e):
    assert not expression_ok(e)


def test_proof_arm_cannot_change_base_source():
    t={'initial':'method M() {}\n'}
    with pytest.raises(ValueError):assemble(t,{'base_source':'method M() {return;}','annotations':[]},'P')


def test_literal_text_survives_comment_removal():
    assert '"//hi"' in strip_comments('print "//hi"; // bye\n/*a*/')


def test_reference_reconstruction_preserves_body():
    t=extract_task('method M(n:nat) returns (x:nat)\nensures x == n\n{\nx := 0;\nwhile x < n\ninvariant x <= n\n{\nx := x+1;\n}\n}\n')
    assert 'invariant' not in t['initial']
    assert 'invariant (x <= n)' in assemble(t,t['reference'],'P')


def test_pure_predicate_needs_no_correctness_batch():
    from research.public_scope_20261012 import inspect_source,evaluate
    source='predicate P(x:int) { x >= 0 }\nmethod M(x:int) returns (y:int)\nrequires P(x)\nensures y == x\n{ y := x; }\n'
    t={'initial':source,'frozen':inspect_source(source),'editable':['M']}
    result=evaluate(t,{'base_source':None,'annotations':[]},'P')
    assert result['verification']['status']=='verified'


def test_character_literals_cannot_confuse_expression_parentheses():
    assert not expression_ok("'(' != 'a') {} if (')' != 'a'")
    assert expression_ok("m' == multiset{}")
