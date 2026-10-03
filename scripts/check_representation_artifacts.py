"""Read-only audit of planned jobs, exact model inputs and fixed final assets."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from generation.representation.analyze import summarize
from generation.representation.runner import messages_for
from generation.representation.task import Task, canonical
from repair.runner import write_json
from repair.task import digest


def audit(root):
    root = Path(root)
    summary = summarize(root)
    if not summary['complete_matrix']:
        raise ValueError('missing/incomplete runs: cannot certify a complete matrix')
    checked, prompts, verifications = 0, 0, 0
    for path in sorted(root.glob('*/result.json')):
        folder = path.parent
        row = json.loads(path.read_text())
        manifest = json.loads((folder/'manifest.json').read_text())
        task = Task.load(manifest['task_path'])
        if task.file_hash != manifest['task_sha256'] or task.meta['asset_hashes'] != manifest['asset_hashes']:
            raise ValueError('task assets no longer match the recorded run')
        if row['is_mock'] != (manifest['model']['kind'] == 'mock'):
            raise ValueError('mock/live identity mismatch')
        expected = messages_for(task,row['representation'],row['strategy'])
        for packet_path in sorted(folder.glob('round_*.messages.json')):
            packet = json.loads(packet_path.read_text())
            messages = packet['messages']
            actual = json.loads(messages[1]['content'])
            if actual['task'] != json.loads(expected[1]['content'])['task']:
                raise ValueError('public task allowlist mismatch')
            if row['strategy'] != 'iterative_repair' and messages != expected:
                raise ValueError('feedback/history leaked into an independent prompt')
            if row['strategy'] == 'iterative_repair':
                restored = messages_for(task,row['representation'],row['strategy'],
                                        actual.get('current_bodies'),actual.get('diagnostic'))
                if messages != restored:
                    raise ValueError('uncontrolled message fields')
                if actual.get('current_bodies') is not None:
                    task.assemble(actual['current_bodies'])
                diag = actual.get('diagnostic')
                if diag is not None:
                    if not set(diag) <= {'status','diagnostics','category','property_satisfaction','additional_spec_disclosure'} or diag.get('additional_spec_disclosure') is not False:
                        raise ValueError('uncontrolled diagnostic disclosure')
                    for item in diag.get('diagnostics',[]):
                        if set(item) != {'category','requirement_ids','candidate_location'}:
                            raise ValueError('raw diagnostic or source disclosure')
            if digest(canonical(messages)) != packet['sha256']:
                raise ValueError('prompt hash mismatch')
            prompts += 1
        events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
        checks = [e for e in events if e['stage'] == 'verification']
        if len(checks) != row['usage']['verifier_calls']:
            raise ValueError('verification ledger mismatch')
        for event in checks:
            label = event['label']
            source = (folder/(label+'.dfy')).read_text()
            task.layout(source)
            if digest(source) != event['source_sha256']:
                raise ValueError('verified source hash mismatch')
            evidence = json.loads((folder/(label+'.verification.json')).read_text())
            if evidence['status'] != event['status']:
                raise ValueError('verification status mismatch')
            command = evidence['command']
            if 'verify' not in command or any(x in command for x in ('--no-verify','--filter-symbol','--filter-position','--allow-axioms','--library')):
                raise ValueError('unexpected verifier command')
        verifications += len(checks)
        if len(list(folder.glob('round_*.messages.json'))) != row['usage']['model_calls']:
            raise ValueError('model call ledger mismatch')
        checked += 1
    return {'protocol':summary['protocol'],'runs_checked':checked,'prompts_checked':prompts,
            'verification_events_checked':verifications,'complete_matrix':True,
            'note':'Read-only artifact/input audit, not a fresh proof or a semantic equivalence review.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    if args.output:
        if args.output.exists():
            parser.error('output already exists')
        write_json(args.output,result)
    print(json.dumps(result,indent=2))
