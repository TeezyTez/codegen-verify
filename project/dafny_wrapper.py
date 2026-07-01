"""
Dafny 验证器封装 + 结构化反馈解析
"""
import subprocess
import tempfile
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import config


@dataclass
class ErrorInfo:
    """结构化的验证错误"""
    error_type: str = ""       # postcondition / precondition / invariant / syntax / type
    message: str = ""          # 原始错误消息
    location_line: int = 0     # 行号
    location_col: int = 0      # 列号
    related_spec: str = ""     # 关联的规约片段


@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool = False
    errors: list[ErrorInfo] = field(default_factory=list)
    verified_count: int = 0
    error_count: int = 0
    raw_output: str = ""


class DafnyVerifier:
    """封装 Dafny CLI 调用"""

    def __init__(self, dafny_path: Optional[str] = None):
        self.dafny_path = dafny_path or config.DAFNY_PATH
        self.solver_path = getattr(config, "DAFNY_SOLVER_PATH", "")

    def _cmd(self, command: str, path: str) -> list[str]:
        cmd = [self.dafny_path, command]
        if command == "verify" and self.solver_path:
            cmd.extend(["--solver-path", self.solver_path])
        cmd.append(path)
        return cmd

    @staticmethod
    def _classify_error(line: str) -> str:
        lower = line.lower()
        if 'postcondition' in lower:
            return 'postcondition'
        if 'precondition' in lower:
            return 'precondition'
        if 'invariant' in lower:
            return 'invariant'
        if (
            'syntax' in lower
            or 'parse error' in lower
            or 'expected' in lower
            or 'invalid unaryexpression' in lower
            or 'invalid unary expression' in lower
            or 'invalid statement' in lower
            or 'rbrace expected' in lower
        ):
            return 'syntax'
        if 'type' in lower or 'type mismatch' in lower:
            return 'type'
        if 'assignment' in lower or 'can be assigned only in compiled contexts' in lower:
            return 'assignment'
        if 'out of range' in lower:
            return 'out_of_range'
        if 'not defined' in lower or 'not found' in lower or 'undeclared' in lower:
            return 'undefined'
        return 'other'

    def verify(self, code: str) -> VerificationResult:
        """验证 Dafny 代码（先 resolve 快速检查语法，再 verify）"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.dfy', delete=False, encoding='utf-8') as f:
            f.write(code)
            tmp_path = f.name

        try:
            # 第一步：快速 resolve 检查语法/类型错误
            resolve_result = subprocess.run(
                self._cmd("resolve", tmp_path),
                capture_output=True, text=True, timeout=15
            )
            resolve_output = resolve_result.stdout + resolve_result.stderr

            # 如果 resolve 就失败了，直接返回错误（不浪费 verify 时间）
            if resolve_result.returncode != 0 or 'error' in resolve_output.lower():
                parse_errors = self._parse_resolve(resolve_output)
                if parse_errors.error_count > 0:
                    os.unlink(tmp_path)
                    return parse_errors

            # 第二步：正式 verify
            result = subprocess.run(
                self._cmd("verify", tmp_path),
                capture_output=True, text=True, timeout=30
            )
            return self._parse(result.stdout + result.stderr, result.returncode)
        except subprocess.TimeoutExpired:
            return VerificationResult(passed=False, errors=[ErrorInfo(error_type="timeout", message="验证超时")])
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _parse_resolve(self, output: str) -> VerificationResult:
        """解析 dafny resolve 的输出（语法/类型错误）"""
        result = VerificationResult(raw_output=output, passed=False)
        lines = output.split('\n')

        for line in lines:
            if 'Error:' not in line:
                # 也检查 "parse errors detected" / "resolution/type errors detected"
                m = re.search(r'(\d+)\s*(?:parse\s*)?errors?\s*detected', line, re.IGNORECASE)
                if m:
                    result.error_count = int(m.group(1))
                m = re.search(r'(\d+)\s*resolution.*errors?\s*detected', line, re.IGNORECASE)
                if m:
                    result.error_count += int(m.group(1))
                continue

            err = ErrorInfo(message=line.strip())
            m_loc = re.search(r'\((\d+),(\d+)\)', line)
            if m_loc:
                err.location_line = int(m_loc.group(1))
                err.location_col = int(m_loc.group(2))

            # 识别具体错误类型
            err.error_type = self._classify_error(line)

            result.errors.append(err)

        if result.error_count == 0:
            result.error_count = len(result.errors)
        return result

    def _parse(self, output: str, returncode: int) -> VerificationResult:
        """解析 Dafny verify 输出"""
        result = VerificationResult(raw_output=output)

        # 解析 verified / errors 计数
        m = re.search(r'(\d+) verified', output)
        result.verified_count = int(m.group(1)) if m else 0
        m = re.search(r'(\d+) error', output)
        result.error_count = int(m.group(1)) if m else 0
        # 也检测 "parse errors detected" 和 "resolution/type errors detected"
        if result.error_count == 0:
            m = re.search(r'(\d+)\s*(?:parse\s*)?errors?\s*detected', output, re.IGNORECASE)
            if m:
                result.error_count = int(m.group(1))
            m = re.search(r'(\d+)\s*resolution.*errors?\s*detected', output, re.IGNORECASE)
            if m:
                result.error_count += int(m.group(1))
        result.passed = result.error_count == 0 and result.verified_count > 0

        # 解析每条错误
        lines = output.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            if 'Error:' not in line:
                i += 1
                continue

            err = ErrorInfo(message=line.strip())

            # 提取行号列号: 文件(line,col)
            m_loc = re.search(r'\((\d+),(\d+)\)', line)
            if m_loc:
                err.location_line = int(m_loc.group(1))
                err.location_col = int(m_loc.group(2))

            # 识别错误类型（按优先级）
            err.error_type = self._classify_error(line)

            # 查找关联的规约行（通常在 "Related location:" 后）
            if i + 1 < len(lines) and 'Related location' in lines[i + 1]:
                err.related_spec = lines[i + 1].strip()
                i += 1

            result.errors.append(err)
            i += 1

        return result


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    v = DafnyVerifier()

    # 测试 1
    r = v.verify("""
method Max(x: int, y: int) returns (result: int)
    ensures result >= x && result >= y
    ensures result == x || result == y
{
    if x >= y { return x; }
    else { return y; }
}
""")
    print(f"[MAX] passed={r.passed} verified={r.verified_count} errors={r.error_count}")

    # 测试 2
    r = v.verify("""
method BadMax(x: int, y: int) returns (result: int)
    ensures result >= x && result >= y
{
    return x;
}
""")
    print(f"[BAD] passed={r.passed} errors={r.error_count}")
    for e in r.errors:
        print(f"  -> [{e.error_type}] L{e.location_line}:{e.location_col} | {e.message[:80]}")
