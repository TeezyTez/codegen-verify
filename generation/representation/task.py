"""Hand-authored views with audited mappings; never translate natural text to contracts."""
import copy
import json
from pathlib import Path
import re

from generation.task import Task as FrozenTask
from repair.task import BoundaryError, digest
from . import REPRESENTATIONS
from .guard import validate_body


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def asset_hashes(meta):
    return {**{r:digest(canonical(meta['representations'][r])) for r in REPRESENTATIONS},
            'spec':digest(canonical(meta['methods'])), 'template':digest(meta['template']),
            'shared_definitions':digest(meta['shared_definitions']),
            'mapping':digest(canonical(meta['requirements']))}


class Task:
    def __init__(self, core):
        self.core = core
        self.path, self.meta = core.path, core.meta
        self.file_hash = digest(self.path.read_text(encoding='utf-8'))
        self.snapshot = canonical(self.meta)

    @classmethod
    def load(cls, path):
        core = FrozenTask.load(path)
        m = core.meta
        required = {'task_id','task_family','license','source','representations','requirements',
                    'equivalence_audit','asset_hashes','template','shared_definitions','version'}
        if not required <= m.keys() or m['task_id'] != m['id'] or m['task_family'] != m['family']:
            raise ValueError('missing representation metadata')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', m['id']):
            raise ValueError('unsafe task ID')
        if not all(isinstance(m[k], str) and m[k] for k in ('license','source','version')):
            raise ValueError('source/license/version required')
        if m['shared_definitions'] != '' or m['template'] != core.skeleton():
            raise ValueError('v1 supports fixed method headers and no shared declarations')
        for method in m['methods']:
            if method.get('signature') != method['header'].splitlines()[0]:
                raise ValueError('public signature must match the frozen header')
        reps = m['representations']
        if set(reps) != set(REPRESENTATIONS) or not isinstance(reps['natural'], str):
            raise ValueError('exactly three representations required')
        if not isinstance(reps['checklist'], list) or not isinstance(reps['structured'], dict):
            raise ValueError('invalid representation type')
        if set(reps['structured']) != {'schema_version','constraints'} or reps['structured']['schema_version'] != 'constraints_v1':
            raise ValueError('unknown structured schema')
        items = reps['structured']['constraints']
        if not isinstance(items, list) or not m['requirements']:
            raise ValueError('constraints and mappings required')
        ids = [r['requirement_id'] for r in m['requirements']]
        if len(set(ids)) != len(ids) or any(not re.fullmatch(r'R[1-9][0-9]*', i) for i in ids):
            raise ValueError('invalid requirement IDs')
        if len(items) != len(ids) or len(reps['checklist']) != len(ids):
            raise ValueError('unmapped representation entries')
        covered = set()
        for i, req in enumerate(m['requirements']):
            rid = req['requirement_id']
            checklist, structured = reps['checklist'][i], items[i]
            if set(checklist) != {'requirement_id','text'} or not isinstance(checklist['text'], str):
                raise ValueError('invalid checklist entry')
            if set(structured) != {'requirement_id','kind','subject','relation','value'}:
                raise ValueError('invalid structured constraint')
            if structured['kind'] not in {'precondition','postcondition'} or any(not isinstance(v,str) or not v for v in structured.values()):
                raise ValueError('invalid structured values')
            if checklist['requirement_id'] != rid or structured['requirement_id'] != rid:
                raise ValueError('requirement ID mismatch')
            if req['checklist_index'] != i or req['structured_index'] != i or not req['natural_quote']:
                raise ValueError('invalid view mapping')
            if req['natural_quote'] not in reps['natural'] or f'[{rid}]' not in req['natural_quote']:
                raise ValueError('missing natural requirement anchor')
            acceptance = req['acceptance']
            method = next((x for x in m['methods'] if x['name'] == acceptance['method']), None)
            line = acceptance['header_line']
            if method is None or type(line) is not int or not 2 <= line <= len(method['header'].splitlines()):
                raise ValueError('invalid acceptance location')
            clause = method['header'].splitlines()[line-1].strip()
            if not clause.startswith(('requires ', 'ensures ')):
                raise ValueError('mapping must refer to a contract clause')
            if structured['kind'] != ('precondition' if clause.startswith('requires ') else 'postcondition'):
                raise ValueError('structured clause kind differs from mapping')
            covered.add((method['name'],line))
        clauses = {(method['name'],i+1) for method in m['methods'] for i,line in enumerate(method['header'].splitlines())
                   if line.strip().startswith(('requires ', 'ensures '))}
        if clauses != covered:
            raise ValueError('unmapped hidden contract clauses')
        audit = m['equivalence_audit']
        if audit.get('status') not in {'pending','human_reviewed'}:
            raise ValueError('invalid equivalence audit status')
        if audit['status'] == 'human_reviewed' and not all(audit.get(k) for k in ('reviewer','date','evidence')):
            raise ValueError('human review requires provenance')
        if m['asset_hashes'] != asset_hashes(m):
            raise ValueError('frozen asset hash mismatch')
        task = cls(core)
        task.assemble(m['reference'])
        for mutant in m['mutants']:
            task.assemble(mutant['bodies'])
        return task

    @property
    def names(self):
        return self.core.names

    def check_frozen(self):
        if digest(self.path.read_text(encoding='utf-8')) != self.file_hash or canonical(self.meta) != self.snapshot:
            raise BoundaryError('frozen_assets_changed')
        if self.meta['asset_hashes'] != asset_hashes(self.meta):
            raise BoundaryError('frozen_assets_changed')

    def public(self, representation):
        if representation not in REPRESENTATIONS:
            raise ValueError('unknown representation')
        # Only this allowlist crosses the model boundary. No task hash, hidden
        # header, template, reference, witness, other view, or private mapping.
        return copy.deepcopy({'task_id':self.meta['id'],
                              'signatures':[m['signature'] for m in self.meta['methods']],
                              'shared_definitions':'',
                              'requirements':self.meta['representations'][representation]})

    def assemble(self, bodies):
        if not isinstance(bodies, dict) or set(bodies) != set(self.names):
            raise BoundaryError('expected exactly the declared method bodies')
        for body in bodies.values():
            if not isinstance(body, str):
                raise BoundaryError('implementation must be text')
            validate_body(body)
        return self.core.assemble(bodies)

    def layout(self, source):
        bodies = self.core.extract(source)
        if source != self.assemble(bodies):
            raise BoundaryError('assembled file does not match frozen template')
        locations, mapping, offset = {}, {}, 0
        for method in self.meta['methods']:
            header_lines = len(method['header'].rstrip().splitlines())
            for req in self.meta['requirements']:
                a = req['acceptance']
                if a['method'] == method['name']:
                    mapping.setdefault(offset+a['header_line'], []).append(req['requirement_id'])
            count = len(bodies[method['name']].strip('\n').splitlines())
            for j in range(count):
                locations[offset+header_lines+2+j] = {'method':method['name'],'line':j+1}
            offset += header_lines+count+3
        return locations, mapping


def load_tasks(root):
    paths = sorted(Path(root).rglob('task.json'))
    tasks = [Task.load(p) for p in paths]
    if not tasks or len({t.meta['id'] for t in tasks}) != len(tasks):
        raise ValueError('empty or duplicate task set')
    return tasks
