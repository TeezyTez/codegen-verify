"""Version-bound declaration evidence and controlled target-selection ablations.

This is a conservative declaration dependency ledger, not a solver VC graph.
Only the trusted runner supplies outcomes. Policy has no acceptance authority.
"""
from copy import deepcopy
import json


SYSTEM = '''Generate a complete implementation and necessary proofs under the frozen Dafny specification.
Use the full specification, source and verifier feedback to plan your work. You may repair implementation,
repair proofs, introduce permitted helpers, or regenerate the implementation. All groups have the same
actions and tools. Never change frozen declarations or contracts. Never use assumptions, axioms, missing
proof bodies, termination exemptions, imports, externs or verifier-option overrides. Only the external
verifier and contract guard decide acceptance. Unknown or stale evidence is not a counterexample.
Return the JSON object requested in the task, with implementation and helpers strings. No markdown.'''


def dependency_order(rows):
    """Stable dependency-first order, with declaration order inside each SCC."""
    index, low, stack, active, components = {}, {}, [], set(), []
    def key(name):
        return rows[name].get('order',0), name
    def visit(name):
        index[name] = low[name] = len(index)
        stack.append(name); active.add(name)
        for dep in sorted(set(rows[name]['depends_on']) & rows.keys(), key=key):
            if dep not in index:
                visit(dep); low[name] = min(low[name],low[dep])
            elif dep in active:
                low[name] = min(low[name],index[dep])
        if low[name] == index[name]:
            component = []
            while True:
                member = stack.pop(); active.remove(member); component.append(member)
                if member == name: break
            components.append(sorted(component,key=key))
    for name in sorted(rows,key=key):
        if name not in index: visit(name)
    return [name for component in components for name in component]


class EvidenceLedger:
    def __init__(self, declarations):
        self.rows = {}
        self.revision = None
        self.prior_closed = set()
        self.last_closed = set()
        self.diagnostics = []
        self.actions = []
        self.last_served = {}
        self.streak_target = None
        self.streak = 0
        self.service_streak = 0
        self.cooldowns = {}
        self.regressions = set()
        self.regression_events = set()
        self.metrics = {'proof_regressions':0, 'newly_closed':0}
        self.update_structure(declarations)

    def update_structure(self, declarations):
        new = {}
        for position, declaration in enumerate(declarations):
            row = deepcopy(declaration)
            ident = row['id']
            if ident in new: raise ValueError('duplicate declaration identity')
            row.setdefault('order',position)
            row['depends_on'] = sorted(set(row.get('depends_on',[])))
            row.update(status='unobserved', local_outcome='unknown', evidence_revision=None)
            if ident in self.rows:
                row.update({k:self.rows[ident][k] for k in ['status','local_outcome','evidence_revision']})
            new[ident] = row
        self.rows = new
        self.order = dependency_order(new)

    def begin(self, revision):
        if not isinstance(revision,str) or not revision: raise ValueError('candidate revision required')
        if revision != self.revision:
            self.prior_closed = set(self.last_closed)
            for row in self.rows.values():
                if row['status'] != 'unobserved': row['status'] = 'stale'
            self.revision = revision
            self.diagnostics = []
            self.regressions = set()

    def observe(self, revision, outcomes, diagnostics=()):
        if set(outcomes)-self.rows.keys(): raise ValueError('unknown declaration outcome')
        if set(outcomes.values())-{'passed','failed','unknown'}: raise ValueError('untrusted outcome status')
        self.begin(revision)
        self.diagnostics = deepcopy(list(diagnostics))
        passed = {key for key in self.rows if outcomes.get(key)=='passed'}
        closed = set(passed)
        # Greatest fixed point: a fully verified recursive SCC may close together.
        while True:
            remaining = {key for key in closed if set(self.rows[key]['depends_on']) <= closed}
            if remaining == closed: break
            closed = remaining
        for key, row in self.rows.items():
            local = outcomes.get(key,'unknown')
            row['local_outcome'] = local
            row['evidence_revision'] = revision
            row['status'] = ('closed' if key in closed else 'locally_passed' if key in passed
                             else 'failed' if local=='failed' else 'unknown')
            if key in self.prior_closed and local=='failed':
                self.regressions.add(key)
                self.regression_events.add((revision,key))
        progress = closed-self.prior_closed
        self.metrics['proof_regressions'] = len(self.regression_events)
        self.metrics['newly_closed'] += len(progress)
        self.last_closed.difference_update(k for k,v in outcomes.items() if v=='failed')
        self.last_closed.update(closed)
        self.prior_closed = set(self.last_closed)
        if self.streak_target:
            if progress:
                self.streak = 0
                self.cooldowns.pop(self.streak_target,None)
            elif self.streak >= 2:
                self.cooldowns.setdefault(self.streak_target,
                    {k for k,v in self.rows.items() if k != self.streak_target and v['status'] != 'closed' and v.get('editable',True)})

    def record_action(self, target):
        if target is not None and target not in self.rows: raise ValueError('unknown action target')
        self.actions.append(target)
        if target is None: return
        self.last_served[target] = len(self.actions)
        self.service_streak = self.service_streak+1 if target == self.streak_target else 1
        self.streak = self.streak+1 if target == self.streak_target else 1
        self.streak_target = target
        for pending in self.cooldowns.values(): pending.discard(target)

    def snapshot(self):
        return deepcopy({'candidate_revision':self.revision, 'declarations':self.rows,
            'diagnostics':self.diagnostics, 'actions':self.actions, 'metrics':self.metrics})


def choose_target(ledger, arm):
    if arm not in {'A','B','C','D'}: raise ValueError('unknown experimental arm')
    if arm in {'A','B'}: return None
    candidates = [key for key in ledger.order if ledger.rows[key]['status'] != 'closed' and ledger.rows[key].get('editable',True)]
    if not candidates: return None
    blockers = {'parse_error','type_error','undefined_name','assignment'}
    for item in ledger.diagnostics:
        if item.get('category') in blockers:
            ident = item.get('target')
            if ident not in candidates: ident = candidates[0]
            return {'id':ident,'reason':'parse_or_type_blocker'}
    if arm == 'C':
        start = 0
        if ledger.streak_target in ledger.order:
            start = ledger.order.index(ledger.streak_target) + int(ledger.service_streak>=2)
        rotated = ledger.order[start:]+ledger.order[:start]
        ident = next(k for k in rotated if k in candidates)
        return {'id':ident,'reason':'fixed_dependency_declaration_order'}
    available = [k for k in candidates if not (ledger.cooldowns.get(k,set()) & set(candidates))]
    if not available: available = candidates
    provisional_users = {key for key,row in ledger.rows.items() if row['status']=='locally_passed'}
    def descendants_using(target):
        result, frontier = set(), [target]
        while frontier:
            current = frontier.pop()
            for key,row in ledger.rows.items():
                if current in row['depends_on'] and key not in result and key != target:
                    result.add(key); frontier.append(key)
        return result
    def priority(key):
        affected = descendants_using(key)
        tier = (0 if affected & provisional_users else 1 if key in ledger.regressions
                else 2 if ledger.rows[key]['status']=='failed' else 3)
        return tier, -len(affected), ledger.last_served.get(key,0), ledger.rows[key]['order'], key
    ident = min(available,key=priority)
    reason = ['unclosed_dependency','observed_regression','current_failure','unobserved_or_unknown'][priority(ident)[0]]
    return {'id':ident,'reason':reason}


def build_messages(task, current, history, ledger, arm):
    if arm not in {'A','B','C','D'}: raise ValueError('unknown experimental arm')
    public = {key:deepcopy(task[key]) for key in ['id','description','frozen_source','editable_regions']}
    content = {'task':public,'current_source':current,'history':deepcopy(history),
        'output_schema':{'implementation':'complete target body including braces',
                         'helpers':'complete additional declarations, or empty string'}}
    if arm != 'A': content['evidence_state'] = ledger.snapshot()
    if arm in {'C','D'}:
        selected = choose_target(ledger,arm)
        content['target'] = {'id':selected['id']} if selected else None
        content['instruction'] = 'Address the selected target first; other necessary edits in allowed regions are permitted.'
    return [{'role':'system','content':SYSTEM},
            {'role':'user','content':json.dumps(content,sort_keys=True,ensure_ascii=False)}]
