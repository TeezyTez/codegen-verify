"""Build auditable recruitment groups and a non-runnable research design."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def save(name, value):
    (ROOT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    inventory = json.loads((ROOT/'baf_preflight/inventory.json').read_text(encoding='utf-8'))
    candidates = [r for r in inventory if r['upstream_partition'] == 'tasks' and r['source'] != 'dafnybench']
    ids = {r['id'] for r in candidates}
    assert len(ids) == len(candidates) == 1891
    parent = {ident:ident for ident in ids}

    def find(ident):
        while parent[ident] != ident:
            parent[ident] = parent[parent[ident]]
            ident = parent[ident]
        return ident

    def union(left, right):
        left, right = find(left), find(right)
        parent[max(left, right)] = min(left, right)

    by_key = defaultdict(list)
    for row in candidates:
        keys = [('frozen_exact', row['frozen_fields_sha256'])]
        if row['source_id']:
            keys.append(('origin', row['source'], row['source_id']))
        if row['near_duplicate_group']:
            keys.append(('upstream_duplicate_group', row['near_duplicate_group']))
        for key in keys:
            by_key[key].append(row['id'])
    for members in by_key.values():
        for ident in members[1:]:
            union(members[0], ident)
    groups = defaultdict(list)
    for row in candidates:
        groups[find(row['id'])].append(row)
    ordered = []
    for members in groups.values():
        names = sorted(r['id'] for r in members)
        ordered.append({'provisional_family_id':'baf-'+hashlib.sha256('|'.join(names).encode()).hexdigest()[:16],
            'ids':names, 'sources':sorted({r['source'] for r in members}),
            'published_references':sum(r['reference_path'] is not None for r in members),
            'semantic_deduplication':'pending', 'admission':'pending', 'split':None})
    ordered.sort(key=lambda row:row['provisional_family_id'])
    save('recruitment-groups.json', {'candidate_rows':len(candidates),
        'provisional_groups':len(ordered), 'admitted_families':0,
        'interpretation':'Known origin/duplicate/exact-field unions only. Unmerged groups are not established independent problems. No final split or jobs.',
        'source_counts':dict(Counter(r['source'] for r in candidates)), 'groups':ordered})
    save('campaign-design.json', {'protocol':'spec_evidence_codegen_large_scale_v1_design',
        'status':'design_not_implemented', 'run_enabled':False, 'model_calls_started':0,
        'task_type':'from_scratch_fixed_spec_implementation_and_proof_generation',
        'main_dataset':'audited_BAF_native_problem_families', 'target_test_families':1000,
        'final_test_families':None, 'development_families':64,
        'arms':['A_autonomous','B_evidence_state','C_fixed_scheduler','D_evidence_scheduler_v1'],
        'replicates':3, 'model_roles':['user_requested_current_Codex_channel','independent_replication_model'],
        'resolved_model_identities':[], 'matrix_sessions_per_test_family':24,
        'planned_sessions_if_1000_families_and_two_models':24000,
        'budgets':{'model_actions':12,'candidate_verifications':12,'verifier_seconds':120,
                   'verifier_cores':1,'output_tokens_per_action':16384,'total_session_tokens':240000,
                   'model_request_seconds':900,'session_seconds':10800},
        'budget_curve_actions':[1,2,4,8,12],
        'primary_contrast':'D-C', 'key_practical_contrast':'D-A',
        'secondary_contrasts':['B-A','C-B'], 'minimum_practical_gain_percentage_points':5,
        'analysis_unit':'audited_problem_family', 'cluster_bootstrap_replicates':10000,
        'randomization_seed':20261009, 'final_job_roster_created':False,
        'launch_gates':['audited_contracts_and_references','semantic_family_deduplication_and_split',
                        'full_Dafny_AST_guard_and_coverage','implemented_frozen_controller_v1',
                        'isolated_batch_model_workers_and_identity','64_development_session_protocol_audit',
                        'frozen_prompts_toolchain_power_analysis_and_roster'],
        'never_count_as_model_experiment':['reference_preflight','lexical_screening','scripted_replay']})
    census = json.loads((ROOT/'reference_census/results.json').read_text(encoding='utf-8'))
    reasons = Counter()
    annotations = []
    for row in census:
        e = row['evidence'] or {}
        raw = e.get('stdout','')+e.get('stderr','')
        reason = 'other'
        if row['reference_status'] == 'tool_error':
            if 'Compilation failed because warnings were found and --allow-warnings is false' in raw:
                reason = 'warning_policy_rejection'
            elif 'parse errors detected' in raw or 'resolution/type errors detected' in raw:
                reason = 'parse_or_resolution_reported'
            elif not e.get('executed'):
                reason = 'not_executed'
            reasons[reason] += 1
            annotations.append({'id':row['job']['id'],'original_status':'tool_error','raw_output_reason':reason})
    save('reference_census/tool-error-annotations.json', {'original_results_modified':False,
        'interpretation':'Post-hoc explanation of existing raw outputs, not a rerun or success reclassification.',
        'reason_counts':dict(reasons),'rows':annotations})
    print(json.dumps({'candidate_rows':len(candidates),'provisional_groups':len(ordered),
                      'admitted_families':0,'tool_error_reasons':dict(reasons)}))


if __name__ == '__main__':
    main()
