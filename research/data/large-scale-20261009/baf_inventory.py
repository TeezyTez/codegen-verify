"""Pinned BAF inventory and reference preflight, not benchmark admission."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from generation.representation.verifier import Dafny
from repair.verifier import classify

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'baf_preflight'
FIELDS = ['vc-preamble', 'vc-helpers', 'vc-spec', 'vc-postamble']


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def screen(code):
    # Only conservative warning flags. A candidate acceptance parser is still required.
    clean = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"', ' ', code)
    patterns = {'assume': r'\bassume\b', 'axiom': r'\baxiom\b',
                'extern': r'\bextern\b', 'include': r'\binclude\b',
                'import': r'\bimport\b', 'termination_opt_out': r'\bdecreases\s*\*',
                'verification_attributes': r'\{:\s*(?:verify|options|vcs|timeLimit|resource_limit)\b'}
    return [k for k, v in patterns.items() if re.search(v, clean)]


def prepare():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'plan.json').exists()
    base = ROOT/'vericoding'
    rows = []
    for group in ['tasks', 'issues']:
        rows += [(group, json.loads(line)) for line in (base/'jsonl'/f'dafny_{group}.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    inventory = []
    for group, row in rows:
        ident = row['id']
        path = base/'vericoded'/f'{ident}_vericoded.dfy'
        reference = path.read_text(encoding='utf-8') if path.exists() else None
        item = {'id': ident, 'upstream_partition': group, 'source': row['source'],
                'source_id': row['source-id'], 'near_duplicate_group': row['qa-near-duplicate-group'],
                'qa_score': row['qa-score'], 'qa_issue_type': row['qa-issue-type'],
                'record_sha256': sha(json.dumps(row, sort_keys=True, ensure_ascii=False)),
                'frozen_fields_sha256': sha(json.dumps({k: row[k] for k in FIELDS}, sort_keys=True, ensure_ascii=False)),
                'reference_path': str(path.relative_to(ROOT)) if reference is not None else None,
                'reference_sha256': sha(reference) if reference is not None else None,
                'reference_lexical_warnings': screen(reference) if reference is not None else [],
                'frozen_fields_lexical_warnings': screen('\n'.join(row[k] for k in FIELDS)),
                'has_ensures_in_vc_spec': bool(re.search(r'\bensures\b', row['vc-spec'])),
                'admission_status': 'unaudited', 'reference_contract_match': 'not_yet_checked'}
        inventory.append(item)
    jobs = [r for r in inventory if r['reference_path']]
    save(OUT/'inventory.json', inventory)
    save(OUT/'inventory_summary.json', {
        'records': len(inventory), 'upstream_partitions': dict(Counter(r['upstream_partition'] for r in inventory)),
        'references': len(jobs), 'reference_sources': dict(Counter(r['source'] for r in jobs)),
        'non_dafnybench_references': sum(r['source'] != 'dafnybench' for r in jobs),
        'warning_free_references': sum(not r['reference_lexical_warnings'] for r in jobs),
        'reference_warning_counts': dict(Counter(f for r in jobs for f in r['reference_lexical_warnings'])),
        'formal_codegen_admitted': 0, 'interpretation': 'Upstream task partition and published reference do not establish correctness or adequate specifications.'})
    save(OUT/'plan.json', {'protocol': 'baf_reference_compatibility_preflight_v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'workers': 4, 'timeout_seconds': 30,
        'script_sha256': sha(Path(__file__).read_text(encoding='utf-8')),
        'toolchain': Dafny(timeout=30).identity(), 'jobs': jobs, 'model_calls': 0,
        'reference_only': True, 'external_includes': 'skip',
        'interpretation': 'Reference compatibility screening only. No expected target names or contract-match assertion. Never use as candidate acceptance.'})
    print('Frozen', len(inventory), 'records and', len(jobs), 'reference jobs', flush=True)


def run():
    plan = json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    assert plan['script_sha256'] == sha(Path(__file__).read_text(encoding='utf-8'))
    assert plan['toolchain'] == Dafny(timeout=30).identity()

    def one(job):
        dest = OUT/(job['id']+'.json')
        if dest.exists():
            return json.loads(dest.read_text(encoding='utf-8'))
        source = (ROOT/job['reference_path']).read_text(encoding='utf-8')
        assert sha(source) == job['reference_sha256']
        if 'include' in job['reference_lexical_warnings']:
            result = {'id': job['id'], 'source': job['source'], 'status': 'skipped_external_dependency', 'evidence': None}
        else:
            evidence = Dafny(timeout=30).verify(source, names=())
            status = evidence.status
            if status == 'unknown' and evidence.executed and evidence.real_verifier:
                if classify(evidence.stdout+evidence.stderr, evidence.returncode, evidence.obligations) == 'passed':
                    status = 'all_observed_batches_verified'
            result = {'id': job['id'], 'source': job['source'], 'status': status, 'evidence': evidence.to_dict()}
        save(dest, result)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=plan['workers']) as pool:
        futures = [pool.submit(one, j) for j in plan['jobs']]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results)%100 == 0 or len(results) == len(futures):
                print(len(results), dict(Counter(r['status'] for r in results)), flush=True)
    save(OUT/'results.json', sorted(results, key=lambda r:r['id']))
    save(OUT/'summary.json', {'references': len(results), 'model_calls': 0,
        'actual_verifier_calls': sum(r['evidence'] is not None for r in results),
        'statuses': dict(Counter(r['status'] for r in results)),
        'by_source': {s: dict(Counter(r['status'] for r in results if r['source'] == s)) for s in sorted({r['source'] for r in results})},
        'admitted_codegen_tasks': 0,
        'interpretation': 'Compatibility only; contract identity, non-vacuity, semantic adequacy, dependence and source license checks remain.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run'])
    args = parser.parse_args()
    prepare() if args.mode == 'prepare' else run()
