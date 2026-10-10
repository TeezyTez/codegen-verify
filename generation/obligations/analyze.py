"""Reject foreign protocols and unverifiable state artifacts before aggregation."""
import json

from repair.task import digest
from generation.representation.task import canonical
from generation.representation import analyze as shared
from . import PROTOCOL


def check_row(folder, row, manifest):
    state = json.loads((folder/'state.json').read_text(encoding='utf-8'))
    if digest(canonical(state)) != row['state_sha256'] or state['metrics'] != row['evidence_metrics']:
        raise ValueError('state artifact mismatch')
    for observation in state['observations']:
        label = observation['label']
        evidence = json.loads((folder/(label+'.verification.json')).read_text(encoding='utf-8'))
        source = (folder/(label+'.dfy')).read_text(encoding='utf-8')
        identity = observation['identity']
        if (digest(canonical(evidence)) != observation['evidence_sha256'] or
                digest(source) != identity['candidate_sha256'] or
                identity['spec_sha256'] != manifest['asset_hashes']['spec'] or
                identity['task_sha256'] != manifest['task_sha256'] or
                identity['toolchain_sha256'] != digest(canonical(manifest['toolchain']))):
            raise ValueError('state evidence identity mismatch')


class CohortAudit:
    """One summary may compare strategies, but never changed tasks or toolchains."""
    def __init__(self):
        self.toolchain = None
        self.tasks = {}

    def __call__(self, folder, row, manifest):
        check_row(folder, row, manifest)
        toolchain = canonical(manifest['toolchain'])
        if self.toolchain is not None and self.toolchain != toolchain:
            raise ValueError('mixed toolchain identities; use separate summaries')
        self.toolchain = toolchain
        task = canonical({'task_sha256': manifest['task_sha256'], 'assets': manifest['asset_hashes']})
        previous = self.tasks.setdefault(row['task_id'], task)
        if previous != task:
            raise ValueError('mixed task identities for the same task ID; use separate summaries')


def summarize(root):
    return shared.summarize(root, protocol=PROTOCOL, check_row=CohortAudit())


def write_summary(root):
    return shared.write_summary(root, protocol=PROTOCOL, check_row=CohortAudit())
