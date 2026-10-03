"""Read-only consistency audit; NOT a replacement for final Dafny verification.

python scripts/check_repair_artifacts.py research/runs/2026-09-08-replay-r2
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repair.cli import load_tasks
from repair.task import digest


def audit(root, tasks_root='repair/tasks'):
    root = Path(root)
    if (root / 'SUPERSEDED.md').exists():
        raise ValueError('superseded run; inspect its notice instead of aggregating it')
    tasks = {t.meta['id']: t for t in load_tasks(tasks_root)}
    jobs = json.loads((root / 'jobs.json').read_text())
    source_versions = set()
    accepted = verifications = 0
    for job in jobs:
        folder = root / job['directory']
        result = json.loads((folder / 'result.json').read_text())
        manifest = json.loads((folder / 'manifest.json').read_text())
        task = tasks[job['task_id']]
        assert digest(task.path.read_text()) == manifest['task_manifest_sha256']
        assert digest((folder / 'initial.dfy').read_text()) == manifest['template_sha256']
        assert result['condition'] == job['condition'] and result['replicate'] == job['replicate']
        source_versions.add(json.dumps(manifest['source_hashes'], sort_keys=True))
        for name, expected in manifest['source_hashes'].items():
            assert digest((Path(__file__).parents[1] / 'repair' / name).read_text()) == expected
        events = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
        checks = [e for e in events if 'result' in e and 'source_sha256' in e]
        assert len(checks) == result['usage']['verifier_calls']
        verifications += len(checks)
        for name in ('model_calls', 'verifier_calls'):
            assert result['usage'][name] <= manifest['limits'][name]
        if result['success']:
            source = (folder / 'final.dfy').read_text()
            task.check_final(source)
            assert digest(source) == result['final_sha256']
            assert checks[-1]['stage'] == 'final_reverification'
            assert checks[-1]['source_sha256'] == result['final_sha256']
            assert checks[-1]['result'] == result['final']
            assert result['final']['status'] == 'passed'
            assert result['seconds'] < manifest['limits']['seconds']
            assert result['usage']['accounted_tokens'] <= manifest['limits']['total_tokens']
            accepted += 1
    assert len(source_versions) == 1, 'mixed framework versions in one suite'
    return dict(planned=len(jobs), audited=len(jobs), accepted=accepted,
                verification_events=verifications, framework_versions=len(source_versions),
                note='Artifact consistency only; successful runs already contain fresh full Dafny verification.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--tasks', default='repair/tasks')
    args = parser.parse_args()
    if not __debug__:
        raise SystemExit('Do not run this assertion-based audit with python -O')
    print(json.dumps(audit(args.root, args.tasks), indent=2))
