"""Experimental input policies; no authority over acceptance or budgets."""
from copy import deepcopy

from generation.representation.models import SYSTEM
from generation.representation.task import canonical
from generation.representation.verifier import feedback
from . import PROTOCOL, REPRESENTATIONS, STRATEGIES
from .config import validate_config
from .state import EvidenceState


class Policy:
    protocol = PROTOCOL
    system = SYSTEM
    feedback_policy = 'public_contract_evidence_v1'
    validate_config = staticmethod(validate_config)
    diagnostic = staticmethod(feedback)

    @staticmethod
    def source_hashes():
        from .runner import source_hashes
        return source_hashes()

    def __init__(self, task, toolchain):
        self.state = EvidenceState(task, toolchain)
        self.history = []
        self.rejection = None

    def messages(self, task, representation, strategy, current=None, diagnostic=None):
        if strategy not in STRATEGIES or representation not in REPRESENTATIONS:
            raise ValueError('unknown experimental condition')
        public = {'task_id': task.meta['id'], 'methods': deepcopy(task.meta['methods']),
                  'shared_definitions': task.meta['shared_definitions'],
                  'requirements': [{'id': r['requirement_id'], 'text': r['natural_quote'],
                                    'acceptance': deepcopy(r['acceptance'])} for r in task.meta['requirements']]}
        content = {'task': public, 'feedback_policy': self.feedback_policy}
        if strategy != 'independent_sampling':
            content.update(current_bodies=deepcopy(current), history=deepcopy(self.history))
            if strategy in {'state', 'guided'}:
                state = self.state.snapshot()
                # Every group receives the underlying observations in history.
                content['evidence_state'] = {k: v for k, v in state.items() if k != 'observations'}
            if strategy == 'guided':
                content['target'] = deepcopy(self.rejection) or self.state.select_target()
                content['repair_instruction'] = (
                    'Produce complete bodies addressing the selected target first. Preserve all fixed '
                    'contracts and repair implementation/invariants as needed. Treat UNKNOWN or STALE '
                    'as missing current proof, not a counterexample. Model claims cannot discharge obligations.')
        return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': canonical(content)}]

    def observe(self, source, evidence, label):
        diagnostic = self.state.observe(source, evidence, label)
        self.history.append(deepcopy(self.state.observations[-1]))
        self.rejection = None
        return diagnostic

    def begin_candidate(self, source, label):
        self.state.begin_candidate(source, label)

    def reject(self, diagnostic):
        self.history.append({'diagnostic': deepcopy(diagnostic), 'candidate_accepted': False})
        self.rejection = {'kind': 'diagnostic', 'category': diagnostic['category'], 'status': 'UNKNOWN'}

    def snapshot(self):
        return {**self.state.snapshot(), 'history': deepcopy(self.history)}
