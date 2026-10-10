from generation.public_benchmark.results import declaration_outcomes, paired_summary


def test_partial_batches_do_not_prove_missing_declarations():
    structure={'declarations':[{'id':'A','name':'A'},{'id':'B','name':'B'}]}
    result={'status':'verification_failed','executed':True,'real_verifier':True,
            'obligations':{'A (correctness)':'passed','B (correctness)':'failed'}}
    assert declaration_outcomes(structure,result)=={'A':'passed','B':'failed'}
    result['obligations']={'A (correctness)':'passed'}
    assert declaration_outcomes(structure,result)=={'A':'passed','B':'unknown'}
    result['real_verifier']=False
    assert declaration_outcomes(structure,result)=={'A':'unknown','B':'unknown'}


def test_paired_summary_weights_families_not_replicates_and_reports_incomplete():
    rows=[]
    for family, repetitions in [('f1',3),('f2',1)]:
        for r in range(repetitions):
            for arm in 'ABCD':
                rows.append({'family_id':family,'task_id':family,'replicate':r,'arm':arm,
                    'success':arm=='D' and family=='f1','model':'m','complete':True,
                    'research_eligible':True})
    out=paired_summary(rows,expected_sessions=len(rows)+1,bootstrap=100)
    assert out['complete_matrix'] is False
    assert out['models']['m']['arm_rates']['D']==0.5
    assert out['models']['m']['contrasts']['D-C']['difference']==0.5
    assert out['models']['m']['families']==2


def test_replay_is_not_included_as_model_efficacy():
    row={'family_id':'f','task_id':'f','replicate':0,'arm':'D','success':True,
         'model':'mock','complete':True,'research_eligible':False}
    out=paired_summary([row],expected_sessions=1,bootstrap=10)
    assert out['models']=={}
    assert not out['complete_matrix']


def test_counts_do_not_prove_complete_paired_roster():
    rows=[dict(family_id='f',task_id='t',model='m',replicate=r,arm=a,
               success=True,complete=True,research_eligible=True)
          for a,r in [('A',0),('A',1),('B',0),('C',0)]]
    assert not paired_summary(rows,expected_sessions=4,bootstrap=10)['complete_matrix']


def test_constant_tiny_sample_does_not_claim_exact_equivalence():
    rows=[dict(family_id='f',task_id='t',model='m',replicate=0,arm=a,
               success=True,complete=True,research_eligible=True) for a in 'ABCD']
    result=paired_summary(rows,expected_sessions=4,bootstrap=10)
    lo,hi=result['models']['m']['contrasts']['D-C']['interval']
    assert lo < 0 < hi
    assert abs(hi-0.975)<1e-10
