"""Conservative evidence ledger, not a recovered solver VC dependency graph."""
from copy import deepcopy

from repair.task import digest
from generation.representation.task import canonical
from generation.representation.verifier import feedback


class EvidenceState:
    def __init__(self, task, toolchain):
        self.task = task
        self.identity = {'spec_sha256': task.meta['asset_hashes']['spec'],
                         'task_sha256': task.file_hash,
                         'toolchain_sha256': digest(canonical(toolchain)),
                         'candidate_sha256': None}
        self.obligations = {}
        methods = {m['name']: m for m in task.meta['methods']}
        for item in task.meta['requirements']:
            mapping = item['acceptance']
            clause = methods[mapping['method']]['header'].splitlines()[mapping['header_line']-1].strip()
            self.obligations[item['requirement_id']] = {
                'kind': 'assumption' if clause.startswith('requires ') else 'postcondition',
                'method': mapping['method'], 'clause': clause, 'status': 'UNOBSERVED'}
        for name in task.names:
            self.obligations['M:'+name] = {'kind': 'method_batch', 'method': name, 'status': 'UNOBSERVED'}
        self.observations = []
        self.metrics = {'candidate_submissions': 0, 'repeated_candidates': 0,
                        'proof_regressions': 0, 'lost_observability': 0}
        self.seen = set()
        self.labels = set()
        self.prior_proved = set()

    def begin_candidate(self, source, label=None):
        candidate = digest(source)
        if self.identity['candidate_sha256'] != candidate:
            self.prior_proved = {key for key, row in self.obligations.items()
                                 if row['status'] == 'DISCHARGED'}
            for row in self.obligations.values():
                if row['status'] not in {'UNOBSERVED', 'STALE'}:
                    row['status'] = 'STALE'
            self.identity['candidate_sha256'] = candidate
        if label and label.startswith('round_') and label not in self.labels:
            self.metrics['candidate_submissions'] += 1
            self.metrics['repeated_candidates'] += int(candidate in self.seen)
            self.seen.add(candidate)
            self.labels.add(label)

    def observe(self, source, evidence, label):
        self.begin_candidate(source, label)
        diagnostic = feedback(self.task, source, evidence)
        # Historical diagnostics remain in immutable observations. Only diagnostics
        # from this verification belong to the current scheduling surface.
        self.obligations = {k:v for k,v in self.obligations.items() if v['kind'] != 'diagnostic'}
        trusted = evidence.real_verifier and evidence.executed
        proved = (trusted and evidence.status == 'verified' and
                  all(evidence.obligations.get(n+' (correctness)') == 'passed' for n in self.task.names))
        for row in self.obligations.values():
            if row['kind'] == 'method_batch':
                outcome = evidence.obligations.get(row['method']+' (correctness)')
                row['status'] = ({'passed': 'DISCHARGED', 'failed': 'UNPROVED'}.get(outcome, 'UNKNOWN')
                                 if trusted and evidence.status in {'verified', 'verification_failed'} else 'UNKNOWN')
            elif row['kind'] == 'postcondition':
                # Whole-program success proves postconditions under the frozen assumptions.
                # Failure or missing diagnostics never establishes clause satisfaction.
                if proved:
                    row['status'] = 'DISCHARGED'
                else:
                    row['status'] = 'UNKNOWN'
        for item in diagnostic['diagnostics']:
            key = 'D:'+digest(canonical(item))[:16]
            failed = (trusted and evidence.status in {'verification_failed', 'parse_error'}
                      and item['category'] not in {'timeout', 'unknown'})
            self.obligations[key] = {'kind': 'diagnostic', **deepcopy(item),
                                     'status': 'UNPROVED' if failed else 'UNKNOWN'}
            if failed and isinstance(item['requirement_ids'], list):
                for rid in item['requirement_ids']:
                    if self.obligations[rid]['kind'] != 'assumption':
                        self.obligations[rid]['status'] = 'UNPROVED'
        if self.prior_proved:
            for key in self.prior_proved:
                status = self.obligations[key]['status']
                self.metrics['proof_regressions'] += int(status == 'UNPROVED')
                self.metrics['lost_observability'] += int(status == 'UNKNOWN')
            self.prior_proved.clear()
        self.observations.append(deepcopy({'label': label, 'identity': self.identity,
            'status': evidence.status, 'executed': evidence.executed,
            'real_verifier': evidence.real_verifier, 'diagnostic': diagnostic,
            'method_batches': evidence.obligations,
            'evidence_sha256': digest(canonical(evidence.to_dict()))}))
        return diagnostic

    def snapshot(self):
        return deepcopy({'identity': self.identity, 'obligations': self.obligations,
                         'observations': self.observations, 'metrics': self.metrics})

    def select_target(self):
        candidates = []
        statuses = {'UNPROVED': 1, 'STALE': 2, 'UNOBSERVED': 2, 'UNKNOWN': 3}
        for key, row in self.obligations.items():
            if row['kind'] == 'assumption' or row['status'] == 'DISCHARGED':
                continue
            parse = row.get('category') in {'parse_error', 'type_error', 'undefined_name', 'assignment'}
            priority = 0 if parse and row['status'] != 'STALE' else statuses[row['status']]
            candidates.append((priority, 0 if row['kind'] == 'diagnostic' else 1, key, row))
        if not candidates:
            return None
        _, _, key, row = min(candidates, key=lambda item: item[:3])
        return deepcopy({'id': key, **row})
