"""Failure-path process fixtures; no generated program or real PID is killed."""
import os
import subprocess
from types import SimpleNamespace

import pytest

from generation.representation import verifier


@pytest.fixture
def windows_process(monkeypatch):
    state={'communicate_timeouts':[],'kill_calls':0,'taskkill':[],'drain_hangs':False,'initial_interrupt':False}
    class Process:
        pid=543210
        returncode=None
        def __init__(self,*args,**kwargs): pass
        def kill(self): state['kill_calls']+=1
        def communicate(self,*,timeout=None):
            state['communicate_timeouts'].append(timeout)
            if len(state['communicate_timeouts'])==1:
                if state['initial_interrupt']: raise KeyboardInterrupt()
                raise subprocess.TimeoutExpired('dafny',timeout,output=b'initial stdout',stderr=b'initial stderr')
            assert timeout is not None and timeout>0, 'cleanup drain must have a deadline'
            if state['drain_hangs']:
                raise subprocess.TimeoutExpired('dafny',timeout,output=b'latest stdout',stderr=b'latest stderr')
            self.returncode=-9
            return 'collected stdout','collected stderr'
    def taskkill(command,**kwargs):
        state['taskkill'].append((command,kwargs))
        if state.get('kill_error'):
            raise state['kill_error']
        return SimpleNamespace(returncode=state.get('kill_returncode',0))
    monkeypatch.setattr(verifier,'os',SimpleNamespace(name='nt',environ=os.environ))
    monkeypatch.setattr(verifier.subprocess,'Popen',Process)
    monkeypatch.setattr(verifier.subprocess,'run',taskkill)
    return state


def test_windows_timeout_kills_owned_process_tree_and_bounds_drain(windows_process):
    result=verifier.Dafny(path='synthetic-dafny',timeout=.01).verify('method M() {}')
    assert result.status=='timeout' and result.executed and result.real_verifier
    command,options=windows_process['taskkill'][0]
    assert command==['taskkill','/PID','543210','/T','/F']
    assert 0<options['timeout']<=5
    assert windows_process['communicate_timeouts']==[.01,5]
    assert result.stdout=='collected stdout'


@pytest.mark.parametrize('kill_error',[OSError('synthetic denied'),subprocess.TimeoutExpired('taskkill',5)])
def test_failed_tree_kill_and_stuck_pipe_return_timeout_with_partial_output(windows_process,kill_error):
    windows_process.update(kill_error=kill_error,drain_hangs=True)
    result=verifier.Dafny(path='synthetic-dafny',timeout=.01).verify('method M() {}')
    assert result.status=='timeout'
    assert windows_process['kill_calls']==1
    assert result.stdout=='latest stdout'
    assert 'latest stderr' in result.stderr and 'cleanup_incomplete' in result.stderr
    assert len(windows_process['communicate_timeouts'])==2


def test_nonzero_taskkill_falls_back_without_losing_timeout(windows_process):
    windows_process['kill_returncode']=1
    result=verifier.Dafny(path='synthetic-dafny',timeout=.01).verify('method M() {}')
    assert result.status=='timeout'
    assert windows_process['kill_calls']==1


def test_interruption_cleans_tree_with_deadline_and_preserves_interrupt(windows_process):
    windows_process.update(initial_interrupt=True,drain_hangs=True)
    with pytest.raises(KeyboardInterrupt):
        verifier.Dafny(path='synthetic-dafny',timeout=.01).verify('method M() {}')
    assert windows_process['taskkill']
    assert windows_process['communicate_timeouts']==[.01,5]
