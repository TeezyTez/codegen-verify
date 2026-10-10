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


def _stop_and_drain(process, initial_stdout=None, initial_stderr=None):
    """Terminate only this invocation's process tree, then drain for at most 5s.

    A failed tree kill must not turn a verifier deadline into an unbounded pipe
    wait. Cleanup can add at most 5s for taskkill plus 5s for communicate.
    """
    incomplete = False
    try:
        if os.name == 'posix':
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif os.name == 'nt':
            killed = subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                                    capture_output=True,timeout=5)
            if killed.returncode:
                raise OSError('process tree termination failed')
        else:
            process.kill()
    except (OSError,subprocess.TimeoutExpired):
        incomplete = True
        try:
            process.kill()
        except OSError:
            pass
    def text(value):
        return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
    try:
        stdout,stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired as exc:
        incomplete = True
        stdout,stderr = text(exc.output or initial_stdout),text(exc.stderr or initial_stderr)
    except (OSError,UnicodeError):
        incomplete = True
        stdout,stderr = text(initial_stdout),text(initial_stderr)
    if incomplete:
        stderr += '\nverifier_cleanup_incomplete: process tree termination or bounded output drain failed'
    return stdout,stderr


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
        return {**super().identity(),'adapter':'representation_formal_only_v3',
                'source_encoding':'utf-8','source_newline_translation':False,
                'process_group_timeout':os.name in {'posix','nt'},'real_verifier':True,
                'timeout_cleanup_limit_seconds':10 if os.name=='nt' else 5,
                'timeout_cleanup_method':'taskkill_process_tree' if os.name=='nt' else 'process_group'}

    def verify(self, source, *, names=(), timeout=None):
        started = time.monotonic()
        limit = min(self.timeout, self.timeout if timeout is None else timeout)
        if limit <= 0:
            return Verification('timeout')
        with tempfile.TemporaryDirectory(prefix='representation-verify-',ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            program, report = root/'program.dfy', root/'results.csv'
            program.write_bytes(source.encode('utf-8'))
            command = [self.path,'verify',str(program),'--cores','1',
                       '--verification-time-limit',str(max(1,math.ceil(limit))),
                       '--log-format',f'csv;LogFileName={report}']
            if self.solver:
                command += ['--solver-path', self.solver]
            result = Verification('tool_error',command=command)
            # .NET uses the Windows profile for its command-line sentinel/cache.
            # Keep the allowlist: model API credentials must not reach generated-code tools.
            env = {k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT','DOTNET_ROOT',
                   'USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP') if k in os.environ}
            try:
                process = subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',start_new_session=os.name=='posix')
                result.executed = result.real_verifier = True
                try:
                    result.stdout,result.stderr = process.communicate(timeout=limit)
                except subprocess.TimeoutExpired as exc:
                    result.status = 'timeout'
                    result.stdout,result.stderr = _stop_and_drain(process,exc.output,exc.stderr)
                except BaseException:
                    _stop_and_drain(process)
                    raise
                result.returncode = process.returncode
                if report.exists():
                    result.csv_log = report.read_text(encoding='utf-8-sig')
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
                if result.status != 'timeout':
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
