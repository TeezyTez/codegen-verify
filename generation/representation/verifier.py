"""Formal-only adapter: reuse existing classification/parser/toolchain identity.

Adds separate streams, process-group deadlines and fail-closed expected batches;
never executes generated programs or uses the runtime --no-verify path.
"""
from dataclasses import asdict, dataclass, field
import csv
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from repair.verifier import Dafny as ExistingDafny, LegacyParser, classify


@dataclass
class Verification:
    status: str
    stdout: str = ''
    stderr: str = ''
    returncode: int | None = None
    seconds: float = 0
    command: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    obligations: dict = field(default_factory=dict)
    executed: bool = False
    real_verifier: bool = False
    csv_log: str = ''

    def to_dict(self):
        return asdict(self)


class Dafny(ExistingDafny):
    def identity(self):
        return {**super().identity(),'adapter':'representation_formal_only_v1',
                'process_group_timeout':os.name == 'posix','real_verifier':True}

    def verify(self, source, *, names=(), timeout=None):
        started = time.monotonic()
        limit = min(self.timeout, self.timeout if timeout is None else timeout)
        if limit <= 0:
            return Verification('timeout')
        with tempfile.TemporaryDirectory(prefix='representation-verify-') as directory:
            root = Path(directory)
            program, report = root/'program.dfy', root/'results.csv'
            program.write_text(source)
            command = [self.path,'verify',str(program),'--cores','1',
                       '--verification-time-limit',str(max(1,math.ceil(limit))),
                       '--log-format',f'csv;LogFileName={report}']
            if self.solver:
                command += ['--solver-path', self.solver]
            result = Verification('tool_error',command=command)
            env = {k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT','DOTNET_ROOT') if k in os.environ}
            try:
                process = subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,text=True,start_new_session=os.name=='posix')
                result.executed = result.real_verifier = True
                try:
                    result.stdout,result.stderr = process.communicate(timeout=limit)
                except subprocess.TimeoutExpired:
                    if os.name == 'posix':
                        try:
                            os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    result.stdout,result.stderr = process.communicate()
                    result.status = 'timeout'
                except BaseException:
                    if os.name == 'posix':
                        try:
                            os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    process.communicate()
                    raise
                result.returncode = process.returncode
                if report.exists():
                    result.csv_log = report.read_text()
                    for row in csv.DictReader(result.csv_log.splitlines()):
                        name = row.get('TestResult.DisplayName','')
                        if name:
                            result.obligations[name] = ('unknown' if name in result.obligations
                                                       else row.get('TestResult.Outcome','').lower())
                raw = result.stdout + result.stderr
                result.diagnostics = [asdict(e) for e in LegacyParser._parse_diagnostics(raw)]
                if result.status != 'timeout':
                    old = classify(raw,result.returncode,result.obligations)
                    result.status = {'passed':'verified','compile_error':'parse_error'}.get(old,old)
                    expected = {name+' (correctness)' for name in names}
                    if result.status == 'verified' and (not expected or not expected <= set(result.obligations)):
                        result.status = 'unknown'
            except (OSError,UnicodeError,csv.Error) as exc:
                result.status = 'tool_error'
                result.stderr += '\n'+type(exc).__name__
            result.seconds = time.monotonic()-started
            return result


CATEGORIES = {'postcondition':'postcondition','precondition':'precondition',
              'invariant_entry':'invariant','invariant_maintenance':'invariant','invariant':'invariant',
              'loop_invariant_entry':'invariant','loop_invariant_maintenance':'invariant',
              'loop_invariant':'invariant','assertion':'assertion',
              'termination':'termination','decreases':'termination',
              'bounds':'bounds','index_out_of_range':'bounds','out_of_range':'bounds',
              'syntax':'parse_error','type':'type_error','assignment':'assignment',
              'undefined':'undefined_name','timeout':'timeout'}


def feedback(task, source, result):
    """Never forward raw messages, snippets, paths, hidden line numbers or clauses."""
    body_locations, contract_locations = task.layout(source)
    diagnostics = []
    for item in result.diagnostics:
        location = body_locations.get(item.get('location_line'))
        ids = contract_locations.get(item.get('related_location_line'), [])
        if not ids:
            ids = contract_locations.get(item.get('location_line'), [])
        diagnostics.append({'category':CATEGORIES.get(item.get('subtype'),'unknown'),
                            'requirement_ids':ids if ids else 'unknown',
                            'candidate_location':location or 'unknown'})
    return {'status':result.status,'diagnostics':diagnostics,
            'property_satisfaction':'unknown','additional_spec_disclosure':False}
