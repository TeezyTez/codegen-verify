"""Real file bytes at the Popen seam; no verifier, solver, or model is launched."""
from pathlib import Path

import pytest

from generation.representation import verifier


@pytest.mark.parametrize('source',[
    'method M() {\n  assert true;\n}\n',
    'method M() {\r\n  assert true;\r\n}\r\n',
    '// 中文说明 café 😀\nmethod M() {\n  print "αβ";\n}\n',
    '// 中文说明 café 😀\r\nmethod M() {\r\n  print "αβ";\r\n}\r\n',
],ids=['lf','crlf','unicode-lf','unicode-crlf'])
def test_verifier_process_receives_exact_source_bytes(monkeypatch,source):
    captured=[]
    class Process:
        returncode=0
        def __init__(self,command,**kwargs):
            # Read the actual file at the production Popen seam, not a mocked writer.
            assert command[1]=='verify'
            captured.append(Path(command[2]).read_bytes())
        def communicate(self,**kwargs):
            return '', ''
    monkeypatch.setattr(verifier.subprocess,'Popen',Process)
    result=verifier.Dafny(path='synthetic-process-seam',timeout=1).verify(source)
    assert result.executed
    assert captured==[source.encode('utf-8')]
