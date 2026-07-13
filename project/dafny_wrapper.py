"""
Dafny 验证器封装 + 结构化反馈解析。

解析器兼容 Dafny 4.11 的诊断块格式：每个 ``Error``/``Related
location`` 头后面可以跟一段带行号的源码。下游旧代码仍可继续使用
``ErrorInfo.error_type``、``message``、``location_*`` 和 ``related_spec``；
更精确的信息通过 ``subtype``、``source`` 和 ``related_source`` 暴露。
"""
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import config


_DIAGNOSTIC_HEADER_RE = re.compile(
    r"^\s*(?P<path>.*?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<kind>Error|Related location):\s*(?P<detail>.*)$",
    re.IGNORECASE,
)
_SOURCE_LINE_RE = re.compile(r"^\s*\d+\s*\|\s?(?P<source>.*)$")
_VERIFIER_SUMMARY_RE = re.compile(
    r"Dafny program verifier finished with\s+(?P<verified>\d+)\s+verified,\s*"
    r"(?P<errors>\d+)\s+errors?",
    re.IGNORECASE,
)
_PARSE_ERROR_SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+(?:parse\s+)?errors?\s+detected",
    re.IGNORECASE,
)
_RESOLUTION_ERROR_SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+resolution(?:/type|\s+or\s+type|.*?)?\s+errors?\s+detected",
    re.IGNORECASE,
)


@dataclass
class ErrorInfo:
    """结构化的 Dafny 诊断。

    前五个字段保持原顺序，避免破坏可能使用位置参数构造 ``ErrorInfo`` 的
    现有调用方。
    """

    error_type: str = ""       # 兼容分类：invariant / postcondition / syntax / ...
    message: str = ""          # 原始 Error 头
    location_line: int = 0     # Error 主位置行号
    location_col: int = 0      # Error 主位置列号
    related_spec: str = ""     # 兼容字段：优先保存 related source
    subtype: str = ""          # 更精确分类，如 invariant_entry
    source: str = ""           # Error 诊断块中的源码（可多行）
    related_source: str = ""   # Related location 诊断块中的源码（可多行）
    related_location_line: int = 0
    related_location_col: int = 0


@dataclass
class VerificationResult:
    """验证结果。"""

    passed: bool = False
    errors: list[ErrorInfo] = field(default_factory=list)
    verified_count: int = 0
    error_count: int = 0
    raw_output: str = ""


@dataclass(frozen=True)
class _DiagnosticBlock:
    """一个 Dafny Error 或 Related location 诊断块。"""

    kind: str
    header: str
    detail: str
    line: int
    col: int
    source: str


class DafnyVerifier:
    """封装 Dafny CLI 调用。"""

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
    def _classify_subtype(text: str) -> str:
        """返回比旧 ``error_type`` 更精确且稳定的诊断子类型。"""

        lower = (text or "").lower()
        if "invariant" in lower:
            if "on entry" in lower:
                return "invariant_entry"
            if "maintained" in lower or "maintenance" in lower:
                return "invariant_maintenance"
            return "invariant"
        if "postcondition" in lower:
            return "postcondition"
        if "precondition" in lower:
            return "precondition"
        if "out of range" in lower or "index out of bounds" in lower:
            return "out_of_range"
        if (
            "cannot prove termination" in lower
            or "could not prove termination" in lower
            or "decreases expression might not decrease" in lower
            or "decreases clause" in lower
            or "termination measure" in lower
        ):
            return "termination"
        if "timed out" in lower or "timeout" in lower:
            return "timeout"
        if (
            "syntax" in lower
            or "parse error" in lower
            or "parse errors" in lower
            or "invalid rhs" in lower
            or "invalid unaryexpression" in lower
            or "invalid unary expression" in lower
            or "invalid statement" in lower
            or "rbrace expected" in lower
            or re.search(r"\b(?:closeparen|openparen|semicolon|expression) expected\b", lower)
        ):
            return "syntax"
        if (
            "type mismatch" in lower
            or "resolution/type" in lower
            or "not assignable" in lower
            or "cannot be converted" in lower
            or "of type" in lower
            or re.search(r"\btype\b", lower)
        ):
            return "type"
        if "assignment" in lower or "can be assigned only in compiled contexts" in lower:
            return "assignment"
        if "not defined" in lower or "not found" in lower or "undeclared" in lower:
            return "undefined"
        return "other"

    @staticmethod
    def _error_type_for_subtype(subtype: str) -> str:
        """映射到旧调用方使用的粗粒度 ``error_type``。"""

        if subtype.startswith("invariant_"):
            return "invariant"
        return subtype

    @classmethod
    def _classify_error(cls, line: str) -> str:
        """兼容旧 API：只返回粗粒度错误类型。"""

        return cls._error_type_for_subtype(cls._classify_subtype(line))

    @staticmethod
    def _combined_output(completed: subprocess.CompletedProcess) -> str:
        """合并 stdout/stderr，避免两个非空流被粘在同一行。"""

        parts = [part.rstrip("\r\n") for part in (completed.stdout, completed.stderr) if part]
        return "\n".join(parts)

    def verify(self, code: str) -> VerificationResult:
        """验证 Dafny 代码（先 resolve 快速检查语法，再 verify）。"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".dfy", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        try:
            resolve_result = subprocess.run(
                self._cmd("resolve", tmp_path),
                capture_output=True,
                text=True,
                timeout=15,
            )
            resolve_output = self._combined_output(resolve_result)

            if resolve_result.returncode != 0 or "error" in resolve_output.lower():
                parse_errors = self._parse_resolve(resolve_output, resolve_result.returncode)
                if parse_errors.error_count > 0:
                    return parse_errors

            verify_result = subprocess.run(
                self._cmd("verify", tmp_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return self._parse(self._combined_output(verify_result), verify_result.returncode)
        except subprocess.TimeoutExpired as exc:
            message = f"Dafny command timed out after {exc.timeout} seconds"
            return VerificationResult(
                passed=False,
                errors=[ErrorInfo(error_type="timeout", subtype="timeout", message=message)],
                error_count=1,
                raw_output=message,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def resolve(self, code: str, timeout: int = 15) -> VerificationResult:
        """Run only Dafny resolution/type checking for a generated candidate."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".dfy", delete=False, encoding="utf-8") as handle:
            handle.write(code)
            path = handle.name
        try:
            completed = subprocess.run(
                self._cmd("resolve", path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = self._combined_output(completed)
            parsed = self._parse_resolve(output, completed.returncode)
            if completed.returncode == 0 and parsed.error_count == 0:
                parsed.passed = True
            return parsed
        except subprocess.TimeoutExpired as exc:
            message = f"Dafny resolve timed out after {exc.timeout} seconds"
            return VerificationResult(
                passed=False,
                errors=[ErrorInfo(error_type="timeout", subtype="timeout", message=message)],
                error_count=1,
                raw_output=message,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _diagnostic_blocks(output: str) -> list[_DiagnosticBlock]:
        """把 Dafny 4.11 文本切成 Error/Related location 块。"""

        lines = (output or "").splitlines()
        headers: list[tuple[int, re.Match[str]]] = []
        for index, line in enumerate(lines):
            match = _DIAGNOSTIC_HEADER_RE.match(line)
            # 带行号的源码可能恰好包含 ``(...): Error:``；它不是诊断头。
            if match and "|" not in line[:match.start("kind")]:
                headers.append((index, match))

        blocks: list[_DiagnosticBlock] = []
        for position, (start, match) in enumerate(headers):
            end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
            source_lines = []
            for line in lines[start + 1:end]:
                source_match = _SOURCE_LINE_RE.match(line)
                if source_match:
                    source_lines.append(source_match.group("source").rstrip())
            blocks.append(_DiagnosticBlock(
                kind=match.group("kind").lower(),
                header=lines[start].strip(),
                detail=match.group("detail").strip(),
                line=int(match.group("line")),
                col=int(match.group("col")),
                source="\n".join(source_lines),
            ))
        return blocks

    @classmethod
    def _parse_diagnostics(cls, output: str) -> list[ErrorInfo]:
        """解析 Error 块，并把随后的 Related location 关联到它。"""

        errors: list[ErrorInfo] = []
        current: ErrorInfo | None = None
        for block in cls._diagnostic_blocks(output):
            if block.kind == "error":
                subtype = cls._classify_subtype(block.detail)
                current = ErrorInfo(
                    error_type=cls._error_type_for_subtype(subtype),
                    subtype=subtype,
                    message=block.header,
                    location_line=block.line,
                    location_col=block.col,
                    source=block.source,
                )
                errors.append(current)
                continue

            if current is None:
                continue

            if block.source:
                current.related_source = "\n".join(
                    part for part in (current.related_source, block.source) if part
                )
            current.related_location_line = block.line
            current.related_location_col = block.col
            # ``related_spec`` 是旧字段；现在让它真正承载关联规约源码。
            current.related_spec = current.related_source or block.detail

        return errors

    @staticmethod
    def _reported_counts(output: str) -> tuple[int, int]:
        """读取 verifier/resolve 汇总计数。"""

        verifier_summary = _VERIFIER_SUMMARY_RE.search(output or "")
        if verifier_summary:
            return (
                int(verifier_summary.group("verified")),
                int(verifier_summary.group("errors")),
            )

        parse_counts = [
            int(match.group("count"))
            for match in _PARSE_ERROR_SUMMARY_RE.finditer(output or "")
        ]
        resolution_counts = [
            int(match.group("count"))
            for match in _RESOLUTION_ERROR_SUMMARY_RE.finditer(output or "")
        ]
        return 0, sum(parse_counts) + sum(resolution_counts)

    def _parse_resolve(self, output: str, returncode: int = 0) -> VerificationResult:
        """解析 ``dafny resolve`` 的语法/类型诊断。"""

        errors = self._parse_diagnostics(output)
        _, reported_error_count = self._reported_counts(output)

        # 某些 resolve 消息的 Error 头本身不含足够分类信息；汇总行可以补足。
        lower = (output or "").lower()
        fallback_subtype = ""
        if "parse error" in lower:
            fallback_subtype = "syntax"
        elif "resolution/type error" in lower or "resolution error" in lower:
            fallback_subtype = "type"
        if fallback_subtype:
            for error in errors:
                if error.subtype == "other":
                    error.subtype = fallback_subtype
                    error.error_type = fallback_subtype

        error_count = max(reported_error_count, len(errors))
        if returncode != 0 and error_count == 0:
            error_count = 1
            errors.append(ErrorInfo(
                error_type="other",
                subtype="process_error",
                message=f"Dafny resolve exited with status {returncode} without a diagnostic",
            ))
        return VerificationResult(
            passed=False,
            errors=errors,
            error_count=error_count,
            raw_output=output,
        )

    def _parse(self, output: str, returncode: int) -> VerificationResult:
        """解析 ``dafny verify`` 输出。"""

        errors = self._parse_diagnostics(output)
        verified_count, reported_error_count = self._reported_counts(output)
        error_count = max(reported_error_count, len(errors))

        if returncode != 0 and error_count == 0:
            errors.append(ErrorInfo(
                error_type="other",
                subtype="process_error",
                message=f"Dafny verify exited with status {returncode} without a diagnostic",
            ))
            error_count = 1

        return VerificationResult(
            passed=returncode == 0 and error_count == 0 and verified_count > 0,
            errors=errors,
            verified_count=verified_count,
            error_count=error_count,
            raw_output=output,
        )


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    verifier = DafnyVerifier()

    ok = verifier.verify("""
method Max(x: int, y: int) returns (result: int)
    ensures result >= x && result >= y
    ensures result == x || result == y
{
    if x >= y { return x; }
    else { return y; }
}
""")
    print(f"[MAX] passed={ok.passed} verified={ok.verified_count} errors={ok.error_count}")

    bad = verifier.verify("""
method BadMax(x: int, y: int) returns (result: int)
    ensures result >= x && result >= y
{
    return x;
}
""")
    print(f"[BAD] passed={bad.passed} errors={bad.error_count}")
    for error in bad.errors:
        print(
            f"  -> [{error.error_type}/{error.subtype}] "
            f"L{error.location_line}:{error.location_col} | {error.message[:80]}"
        )
