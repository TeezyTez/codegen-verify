"""A small, explicit Dafny profile. No inferred or model-written target specs."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from repair.task import BoundaryError, digest, validate_region

CONDITIONS = ('G00', 'G01', 'G10', 'G11')
HEADER_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|[0-9]+|<==>|==>|<==|<=|>=|==|!=|&&|\|\||::|[^\s]')


def header_pattern(header):
    tokens = HEADER_TOKEN.findall(header)
    return r'\s*'.join(re.escape(token)+(r'(?![A-Za-z0-9_])' if re.fullmatch(r'[A-Za-z0-9_]+',token) else '')
                       for token in tokens)


def body_check(body):
    validate_region(body, 'implementation')
    # No I/O, allocation, module/reflection escape, or trusted runtime assertions.
    if re.search(r'\b(?:print|new|modify|reveal|halt|Main|VerificationHarness)\b', body):
        raise BoundaryError('outside pure integer/sequence generation profile')


@dataclass
class Task:
    path: Path
    meta: dict

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        meta = json.loads(path.read_text())
        required = {'id','source_project','family','split','origin','description','methods',
                    'reference','mutants','tests','rule','trusted_assumptions','profile'}
        if not required <= meta.keys() or meta['profile'] != 'pure_dafny_methods_v1':
            raise ValueError('invalid generation task/profile')
        if meta['split'] not in {'dev','test'} or meta['trusted_assumptions'] != []:
            raise ValueError('invalid split or extra trusted assumptions')
        if not meta['methods'] or not meta['mutants'] or not meta['tests']:
            raise ValueError('task needs methods, negative controls and runtime witnesses')
        names = []
        for method in meta['methods']:
            name, header = method['name'], method['header']
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) or name in {'Main','VerificationHarness'}:
                raise ValueError('invalid or reserved method name')
            if not header.startswith(f'method {name}(') or '\n  ensures ' not in header:
                raise ValueError('each method needs an explicit frozen contract')
            if re.search(r'[{}#/\\"\x00]|\b(?:assume|axiom|extern|include|import|decreases|ghost|method)\b', header[len('method '):]):
                raise ValueError('unsupported trusted header')
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError('duplicate method')
        if set(meta['reference']) != set(names):
            raise ValueError('reference must implement every method')
        if len({m['id'] for m in meta['mutants']}) != len(meta['mutants']):
            raise ValueError('duplicate mutant ID')
        task = cls(path, meta)
        task.assemble(meta['reference'])
        for mutant in meta['mutants']:
            task.assemble(mutant['bodies'])
            if not mutant.get('violation'):
                raise ValueError('mutant requires a semantic violation explanation')
        task.harness()  # validate independently supplied finite witnesses
        return task

    @property
    def names(self):
        return [m['name'] for m in self.meta['methods']]

    def public(self):
        return {k: self.meta[k] for k in ('id','description','methods','rule','profile')}

    def skeleton(self):
        return '\n\n'.join(m['header'].rstrip() + '\n{\n  <generate body: ' + m['name'] + '>\n}'
                           for m in self.meta['methods']) + '\n'

    def assemble(self, bodies):
        if not isinstance(bodies, dict) or set(bodies) != set(self.names):
            raise BoundaryError('generate every declared method, no additional method')
        for text in bodies.values():
            if not isinstance(text, str):
                raise BoundaryError('body must be text')
            body_check(text)
        return '\n\n'.join(m['header'].rstrip() + '\n{\n' + bodies[m['name']].strip('\n') + '\n}'
                           for m in self.meta['methods']) + '\n'

    def extract(self, source):
        if not isinstance(source, str) or not source.isascii() or len(source) > 64000:
            raise BoundaryError('candidate exceeds source profile')
        rest, bodies = source, {}
        for method in self.meta['methods']:
            rest = rest.lstrip()
            # Preserve header tokens, allowing harmless whitespace differences.
            # This is a restricted declaration matcher, not a general Dafny AST.
            header = method['header'].rstrip()
            match = re.match(header_pattern(header)+r'\s*(?=\{)',rest)
            if not match:
                raise BoundaryError('fixed interface/contract changed or declaration reordered')
            rest = rest[match.end():]
            if not rest.startswith('{'):
                raise BoundaryError('expected method body')
            depth, end = 0, None
            for i, char in enumerate(rest):
                depth += (char == '{') - (char == '}')
                if depth == 0:
                    end = i
                    break
            if end is None:
                raise BoundaryError('unclosed method body')
            body = rest[1:end]
            body_check(body)
            bodies[method['name']] = body
            rest = rest[end+1:]
        if rest.strip():
            raise BoundaryError('extra declarations or trailing source')
        return bodies

    def candidate(self, action, condition):
        if action.get('action') != 'generate':
            raise BoundaryError('expected generate action')
        if condition in {'G10','G11'}:
            if set(action) != {'action','bodies'}:
                raise BoundaryError('skeleton condition requires bodies only')
            return self.assemble(action['bodies'])
        if set(action) != {'action','source'}:
            raise BoundaryError('full-source condition requires source only')
        self.extract(action['source'])
        return action['source']  # verify precisely the supplied artifact

    def harness(self):
        def literal(value):
            if type(value) is bool:
                return str(value).lower()
            if type(value) is int:
                return str(value)
            if isinstance(value, list) and all(type(x) is int for x in value):
                return '[' + ', '.join(map(str, value)) + ']'
            raise ValueError('runtime witnesses support int, bool, seq<int> only')
        lines = ['method Main() {']
        for i, case in enumerate(self.meta['tests']):
            if case['method'] not in self.names or not case['outputs']:
                raise ValueError('invalid witness method or outputs')
            names = [f'v{i}_{j}' for j in range(len(case['outputs']))]
            lines.append('  var ' + ', '.join(names) + ' := ' + case['method'] + '(' +
                         ', '.join(literal(v) for v in case['inputs']) + ');')
            lines.extend(f'  expect {name} == {literal(value)};' for name,value in zip(names,case['outputs']))
        lines += ['  print "GENERATION_WITNESSES_PASSED\\n";', '}']
        return '\n'.join(lines) + '\n'


def load_tasks(root):
    tasks = [Task.load(p) for p in sorted(Path(root).rglob('task.json'))]
    if not tasks or len({t.meta['id'] for t in tasks}) != len(tasks):
        raise ValueError('empty or duplicate task list')
    projects, templates = {}, {}
    for task in tasks:
        split, source = task.meta['split'], task.meta['source_project']
        if source in projects and projects[source] != split:
            raise ValueError('source project crosses splits')
        projects[source] = split
        norm = re.sub(r'\b(?:[A-Za-z_]\w*|\d+)\b', 'ID', task.skeleton())
        fingerprint = digest(re.sub(r'\s+', '', norm))
        if fingerprint in templates and templates[fingerprint] != split:
            raise ValueError('normalized template crosses splits')
        templates[fingerprint] = split
    return tasks
