"""Conservative outcome mapping and paired problem-family analysis."""
from collections import defaultdict
import math
import random


def declaration_outcomes(structure, evidence):
    rows = structure['declarations']
    if not evidence.get('executed') or not evidence.get('real_verifier'):
        return {r['id']:'unknown' for r in rows}
    if evidence['status'] == 'verified':
        return {r['id']:'passed' for r in rows}
    result = {}
    for row in rows:
        prefixes = {row['name'],row['id'],row['id'].removeprefix('_default.')}
        outcomes = [value for name,value in evidence.get('obligations',{}).items()
                    if name.rsplit(' (',1)[0] in prefixes]
        result[row['id']] = ('failed' if 'failed' in outcomes else 'passed' if outcomes and
                            all(v=='passed' for v in outcomes) and evidence['status']=='verification_failed'
                            else 'unknown')
    return result


def paired_summary(rows, *, expected_sessions, expected_identities=None, bootstrap=10000, seed=20261009):
    eligible = [r for r in rows if r.get('research_eligible') and r.get('complete')]
    identities = [(r['model'],r['task_id'],r['replicate'],r['arm']) for r in eligible]
    if len(set(identities)) != len(identities): raise ValueError('duplicate experiment identity')
    blocks = defaultdict(set)
    for model,task,replicate,arm in identities:
        blocks[(model,task,replicate)].add(arm)
    matched = all(arms==set('ABCD') for arms in blocks.values())
    if expected_identities is not None:
        matched = matched and set(identities)=={tuple(x) for x in expected_identities}
    grouped = defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:defaultdict(list))))
    for row in eligible:
        grouped[row['model']][row['family_id']][row['arm']][row['task_id']].append(float(row['success']))
    rng = random.Random(seed)
    models = {}
    for model, families in grouped.items():
        rates = {}
        for family, arms in families.items():
            if set(arms) != set('ABCD'): continue
            rates[family] = {arm:sum(sum(values)/len(values) for values in tasks.values())/len(tasks)
                             for arm,tasks in arms.items()}
        if not rates: continue
        keys = sorted(rates)
        contrasts = {}
        for left,right in [('D','C'),('D','A'),('B','A'),('C','B')]:
            delta = [rates[k][left]-rates[k][right] for k in keys]
            draws = sorted(sum(rng.choice(delta) for _ in delta)/len(delta) for _ in range(bootstrap))
            # Two main contrasts use Bonferroni simultaneous family coverage.
            tail = .0125 if left=='D' else .025
            contrasts[left+'-'+right] = {'difference':sum(delta)/len(delta),
                'interval':[draws[int(tail*(bootstrap-1))],draws[int((1-tail)*(bootstrap-1))]],
                'interval_coverage':1-2*tail,'method':'paired_family_percentile_bootstrap',
                'bootstrap_replicates':bootstrap}
            if len(set(delta))==1:
                # A constant empirical sample cannot establish population equivalence.
                # Distribution-free Hoeffding bound for paired differences in [-1,1].
                c=delta[0]; radius=math.sqrt(2*math.log(1/tail)/len(delta))
                contrasts[left+'-'+right].update(
                    interval=[max(-1,c-radius),min(1,c+radius)],
                    method='constant_sample_hoeffding_bound')
                if c==0:
                    # |E(delta)| <= P(delta != 0). With zero nonzero family
                    # differences, the exact one-sided binomial upper bound
                    # on that probability is 1 - alpha**(1/N).
                    bound=1-(2*tail)**(1/len(delta))
                    contrasts[left+'-'+right].update(interval=[-bound,bound],
                        method='zero_family_difference_exact_binomial_bound')
        models[model] = {'families':len(keys),'incomplete_families_excluded_from_paired_description':len(families)-len(keys),
            'arm_rates':{arm:sum(rates[k][arm] for k in keys)/len(keys) for arm in 'ABCD'},
            'contrasts':contrasts}
    return {'recorded_sessions':len(rows),'eligible_completed_sessions':len(eligible),
        'expected_sessions':expected_sessions,
        'complete_matrix':matched and len(eligible)==expected_sessions and len(rows)==expected_sessions,
        'models':models,
        'interpretation':'Partial matrices are descriptive only. Bootstrap precision at small family counts is limited. Development cohorts are not confirmatory tests.'}
