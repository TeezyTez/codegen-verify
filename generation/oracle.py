"""Frozen contract verification plus independent finite runtime witnesses."""
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from repair.task import BoundaryError
from repair.verifier import Dafny


@dataclass
class Evidence:
    status: str
    structure: str = 'not_run'
    formal: str = 'not_run'
    behavioral: str = 'not_run'
    verifier_calls: int = 0
    runtime_calls: int = 0
    details: dict = field(default_factory=dict)
    seconds: float = 0

    def to_dict(self):
        return asdict(self)


class Oracle:
    def __init__(self, verifier=None):
        self.verifier = verifier or Dafny()

    def identity(self):
        return {'verifier':self.verifier.identity(), 'runtime_target':'py',
                'runtime_python':sys.executable, 'runtime_witnesses':'trusted expect statements',
                'note':'runtime compilation uses --no-verify only after a separate formal check; never proof evidence'}

    def runtime(self, source, task, timeout):
        started = time.monotonic()
        if timeout <= 0:
            return {'status':'timeout','seconds':0,'command':[],'raw':'deadline exhausted','executed':False}
        with tempfile.TemporaryDirectory(prefix='generation-witness-') as directory:
            root = Path(directory)
            path = root / 'program.dfy'
            path.write_text(source + '\n' + task.harness())
            command = [self.verifier.path,'run','--no-verify','--target','py','--allow-warnings',str(path)]
            # Pure Dafny profile, no FFI/imports/I/O/allocation. Do not provide
            # model API keys or the surrounding repository to generated code.
            env = {k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT') if k in os.environ}
            env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH','')
            try:
                # Kill the compiler/runtime process group on POSIX, not just
                # the Dafny parent (generated programs can contain slow loops).
                process = subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,text=True,start_new_session=os.name=='posix')
                try:
                    stdout,stderr = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':
                        try:
                            os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    process.communicate()
                    raise
                raw = stdout + stderr
                if process.returncode == 0 and 'GENERATION_WITNESSES_PASSED' in stdout:
                    status = 'passed'
                elif 'expectation violation' in raw.lower() or 'expectation failed' in raw.lower():
                    status = 'behavior_failed'
                else:
                    status = 'runtime_error'
                return {'status':status,'returncode':process.returncode,'raw':raw,'command':command,
                        'seconds':time.monotonic()-started,'executed':True}
            except subprocess.TimeoutExpired:
                return {'status':'timeout','command':command,'raw':'runtime deadline exceeded',
                        'seconds':time.monotonic()-started,'executed':True}
            except OSError as exc:
                return {'status':'tool_error','command':command,'raw':type(exc).__name__,
                        'seconds':time.monotonic()-started,'executed':True}

    def check(self, task, source, *, timeout=30, test_failed=False):
        started = time.monotonic()
        result = Evidence('not_run')
        try:
            task.extract(source)
        except (BoundaryError, ValueError) as exc:
            return Evidence('boundary_rejected',structure='failed',details={'reason':str(exc)})
        result.structure = 'passed'
        if timeout <= 0:
            result.status = 'timeout'
            return result
        result.verifier_calls = 1
        formal = self.verifier.verify(source,timeout=timeout)
        result.details['formal'] = formal.to_dict()
        result.formal = formal.status
        result.status = formal.status
        expected = {name + ' (correctness)' for name in task.names}
        if formal.status == 'passed' and not expected <= set(formal.obligations):
            result.formal = result.status = 'unknown'
            result.details['missing_batches'] = sorted(expected-set(formal.obligations))
        remaining = timeout - (time.monotonic()-started)
        if result.formal == 'passed' or (test_failed and result.formal == 'verification_failed'):
            runtime = self.runtime(source,task,remaining)
            result.runtime_calls = int(runtime['executed'])
            result.behavioral = runtime['status']
            result.details['runtime'] = runtime
            if result.formal == 'passed':
                result.status = runtime['status']
        result.seconds = time.monotonic()-started
        if result.seconds > timeout:
            result.status = 'timeout'
        return result
