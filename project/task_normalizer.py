"""Normalize HumanEval records into a lossless, structured task IR.

The benchmark runner used to recover a function description with line-based
string operations.  That is fragile when a prompt contains helper functions,
multi-line signatures, or a long docstring.  This module deliberately uses the
Python AST for identity and typing, and :mod:`doctest` for public examples.

No source text is truncated.  The original prompt and the exact target
signature spelling are retained in :class:`TaskIR` alongside normalized fields
that downstream prompt builders can consume safely.
"""

from __future__ import annotations

import ast
import doctest
import io
import tokenize
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence


class TaskNormalizationError(ValueError):
    """Raised when a HumanEval record cannot be normalized unambiguously."""


@dataclass(frozen=True)
class DafnyTypeIR:
    """A Python annotation and its explicit Dafny representation.

    ``dafny`` is ``None`` when the annotation cannot be represented safely.
    Unsupported types are never silently coerced to a convenient Dafny type.
    This is particularly important for ``Any`` and mappings, whose semantics
    cannot be recovered from a Python annotation alone.
    """

    annotation: str
    kind: str
    dafny: Optional[str]
    supported: bool
    arguments: tuple["DafnyTypeIR", ...] = field(default_factory=tuple)
    reason: Optional[str] = None
    required_declarations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParameterIR:
    name: str
    kind: str
    annotation: Optional[str]
    dafny_type: DafnyTypeIR
    has_default: bool = False
    default_source: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExampleIR:
    """One public doctest example from the target function's docstring."""

    source: str
    expected_text: str
    line_number: int
    call_name: Optional[str]
    positional_args: tuple[Any, ...] = field(default_factory=tuple)
    keyword_args: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    arguments_are_literal: bool = False
    expected_value: Any = None
    expected_is_literal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskIR:
    """Structured, lossless representation of one HumanEval problem."""

    task_id: str
    entry_point: str
    prompt: str
    function_line: int
    signature: str
    signature_source: str
    raw_docstring: str
    docstring: str
    parameters: tuple[ParameterIR, ...]
    return_annotation: Optional[str]
    return_type: DafnyTypeIR
    examples: tuple[ExampleIR, ...]

    @property
    def supported(self) -> bool:
        return self.return_type.supported and all(
            parameter.dafny_type.supported for parameter in self.parameters
        )

    @property
    def unsupported_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for parameter in self.parameters:
            if not parameter.dafny_type.supported:
                reason = parameter.dafny_type.reason or "unsupported annotation"
                reasons.append(f"parameter {parameter.name}: {reason}")
        if not self.return_type.supported:
            reason = self.return_type.reason or "unsupported annotation"
            reasons.append(f"return value: {reason}")
        return tuple(reasons)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["supported"] = self.supported
        result["unsupported_reasons"] = list(self.unsupported_reasons)
        return result


_OPTION_DECLARATION = "datatype Option<T> = None | Some(value: T)"
_SEQUENCE_NAMES = {"List", "list", "Sequence", "typing.List", "typing.Sequence"}
_TUPLE_NAMES = {"Tuple", "tuple", "typing.Tuple"}
_OPTIONAL_NAMES = {"Optional", "typing.Optional"}
_UNION_NAMES = {"Union", "typing.Union"}
_MAPPING_NAMES = {
    "dict",
    "Dict",
    "Mapping",
    "MutableMapping",
    "typing.Dict",
    "typing.Mapping",
    "typing.MutableMapping",
}


def _source_segment(source: str, node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    segment = ast.get_source_segment(source, node)
    return segment if segment is not None else ast.unparse(node)


def _annotation_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _annotation_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _is_none_annotation(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and node.value is None
        or isinstance(node, ast.Name)
        and node.id in {"None", "NoneType"}
    )


def _unsupported(annotation: str, kind: str, reason: str) -> DafnyTypeIR:
    return DafnyTypeIR(
        annotation=annotation,
        kind=kind,
        dafny=None,
        supported=False,
        reason=reason,
    )


def _make_optional(annotation: str, child: DafnyTypeIR) -> DafnyTypeIR:
    if not child.supported or child.dafny is None:
        return DafnyTypeIR(
            annotation=annotation,
            kind="optional",
            dafny=None,
            supported=False,
            arguments=(child,),
            reason=f"optional member is unsupported: {child.reason or child.annotation}",
        )
    declarations = tuple(dict.fromkeys((*child.required_declarations, _OPTION_DECLARATION)))
    return DafnyTypeIR(
        annotation=annotation,
        kind="optional",
        dafny=f"Option<{child.dafny}>",
        supported=True,
        arguments=(child,),
        required_declarations=declarations,
    )


def _flatten_pep604_union(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_flatten_pep604_union(node.left), *_flatten_pep604_union(node.right)]
    return [node]


def python_annotation_to_dafny(
    annotation: Optional[ast.AST | str],
    *,
    source: Optional[str] = None,
) -> DafnyTypeIR:
    """Translate a Python type annotation into an explicit Dafny type IR.

    ``annotation`` may be an AST node or annotation text.  The function is
    intentionally conservative: missing annotations, ``Any``, dictionaries,
    and arbitrary unions are marked unsupported instead of guessed.
    """

    if annotation is None:
        return _unsupported("<missing>", "missing", "Python annotation is missing")

    if isinstance(annotation, str):
        text = annotation.strip()
        if not text:
            return _unsupported("<missing>", "missing", "Python annotation is missing")
        try:
            node = ast.parse(text, mode="eval").body
        except SyntaxError:
            return _unsupported(text, "unknown", "annotation is not valid Python syntax")
        annotation_text = text
    else:
        node = annotation
        annotation_text = _source_segment(source or "", node) if source else ast.unparse(node)
        annotation_text = annotation_text or ast.unparse(node)

    # Resolve a quoted forward annotation such as ``"Optional[int]"``.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        forwarded = python_annotation_to_dafny(node.value)
        return DafnyTypeIR(
            annotation=annotation_text,
            kind=forwarded.kind,
            dafny=forwarded.dafny,
            supported=forwarded.supported,
            arguments=forwarded.arguments,
            reason=forwarded.reason,
            required_declarations=forwarded.required_declarations,
        )

    simple_name = _annotation_name(node)
    simple_types = {
        "int": ("integer", "int"),
        "float": ("real", "real"),
        "bool": ("boolean", "bool"),
        "str": ("string", "string"),
        "None": ("unit", "()"),
        "NoneType": ("unit", "()"),
    }
    if simple_name in simple_types:
        kind, dafny = simple_types[simple_name]
        return DafnyTypeIR(annotation_text, kind, dafny, True)
    if _is_none_annotation(node):
        return DafnyTypeIR(annotation_text, "unit", "()", True)
    if simple_name in {"Any", "typing.Any"}:
        return _unsupported(annotation_text, "any", "Any has no sound concrete Dafny representation")
    if simple_name in _MAPPING_NAMES:
        return _unsupported(
            annotation_text,
            "mapping",
            "dictionary key/value and mutation semantics require an explicit encoding",
        )
    if simple_name in _SEQUENCE_NAMES:
        return _unsupported(
            annotation_text,
            "sequence",
            "sequence annotation is missing its element type",
        )
    if simple_name in _TUPLE_NAMES:
        return _unsupported(
            annotation_text,
            "tuple",
            "tuple annotation is missing its element types",
        )

    # PEP 604 spelling: ``T | None``.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = _flatten_pep604_union(node)
        non_none = [member for member in members if not _is_none_annotation(member)]
        if len(members) == 2 and len(non_none) == 1:
            return _make_optional(
                annotation_text,
                python_annotation_to_dafny(non_none[0], source=source),
            )
        return _unsupported(
            annotation_text,
            "union",
            "only Optional[T] / T | None unions have a sound built-in encoding",
        )

    if isinstance(node, ast.Subscript):
        container_name = _annotation_name(node.value)
        slice_node = node.slice
        members = list(slice_node.elts) if isinstance(slice_node, ast.Tuple) else [slice_node]

        if container_name in _MAPPING_NAMES:
            return _unsupported(
                annotation_text,
                "mapping",
                "dictionary key/value and mutation semantics require an explicit encoding",
            )

        if container_name in _SEQUENCE_NAMES:
            if len(members) != 1:
                return _unsupported(annotation_text, "sequence", "sequence requires one element type")
            child = python_annotation_to_dafny(members[0], source=source)
            if not child.supported or child.dafny is None:
                return DafnyTypeIR(
                    annotation_text,
                    "sequence",
                    None,
                    False,
                    (child,),
                    f"sequence element is unsupported: {child.reason or child.annotation}",
                )
            return DafnyTypeIR(
                annotation_text,
                "sequence",
                f"seq<{child.dafny}>",
                True,
                (child,),
                required_declarations=child.required_declarations,
            )

        if container_name in _TUPLE_NAMES:
            # ``Tuple[T, ...]`` is the homogeneous, immutable-sequence form.
            if len(members) == 2 and isinstance(members[1], ast.Constant) and members[1].value is Ellipsis:
                child = python_annotation_to_dafny(members[0], source=source)
                if not child.supported or child.dafny is None:
                    return DafnyTypeIR(
                        annotation_text,
                        "variadic_tuple",
                        None,
                        False,
                        (child,),
                        f"tuple element is unsupported: {child.reason or child.annotation}",
                    )
                return DafnyTypeIR(
                    annotation_text,
                    "variadic_tuple",
                    f"seq<{child.dafny}>",
                    True,
                    (child,),
                    required_declarations=child.required_declarations,
                )

            children = tuple(python_annotation_to_dafny(member, source=source) for member in members)
            if not children or any(not child.supported or child.dafny is None for child in children):
                return DafnyTypeIR(
                    annotation_text,
                    "tuple",
                    None,
                    False,
                    children,
                    "one or more tuple members are unsupported",
                )
            declarations = tuple(
                dict.fromkeys(
                    declaration
                    for child in children
                    for declaration in child.required_declarations
                )
            )
            return DafnyTypeIR(
                annotation_text,
                "tuple",
                f"({', '.join(child.dafny or '' for child in children)})",
                True,
                children,
                required_declarations=declarations,
            )

        if container_name in _OPTIONAL_NAMES:
            if len(members) != 1:
                return _unsupported(annotation_text, "optional", "Optional requires one member type")
            return _make_optional(
                annotation_text,
                python_annotation_to_dafny(members[0], source=source),
            )

        if container_name in _UNION_NAMES:
            non_none = [member for member in members if not _is_none_annotation(member)]
            if len(members) == 2 and len(non_none) == 1:
                return _make_optional(
                    annotation_text,
                    python_annotation_to_dafny(non_none[0], source=source),
                )
            return _unsupported(
                annotation_text,
                "union",
                "only Optional[T] / Union[T, None] has a sound built-in encoding",
            )

    return _unsupported(
        annotation_text,
        "unknown",
        f"no configured Dafny representation for {annotation_text}",
    )


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _absolute_offset(offsets: Sequence[int], position: tuple[int, int]) -> int:
    line, column = position
    return offsets[line - 1] + column


def _extract_signature_source(source: str, function: ast.FunctionDef) -> str:
    """Return the exact source spelling from ``def`` through its header colon."""

    offsets = _line_offsets(source)
    start = (function.lineno, function.col_offset)
    depth = 0
    saw_def = False
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.start < start:
                continue
            if not saw_def:
                if token.type == tokenize.NAME and token.string == "def" and token.start == start:
                    saw_def = True
                else:
                    continue
            if token.type == tokenize.OP:
                if token.string in "([{":
                    depth += 1
                elif token.string in ")]}":
                    depth -= 1
                elif token.string == ":" and depth == 0:
                    begin = _absolute_offset(offsets, start)
                    end = _absolute_offset(offsets, token.end)
                    return source[begin:end]
    except (IndentationError, tokenize.TokenError):
        pass

    # The module has already parsed successfully, so this path is only a guard
    # against unexpected tokenizer behaviour.
    return _render_normalized_signature(function)


def _render_normalized_signature(function: ast.FunctionDef) -> str:
    arguments = ast.unparse(function.args)
    returns = f" -> {ast.unparse(function.returns)}" if function.returns is not None else ""
    return f"def {function.name}({arguments}){returns}:"


def _parameter_records(source: str, function: ast.FunctionDef) -> tuple[ParameterIR, ...]:
    args = function.args
    records: list[ParameterIR] = []
    positional = [*args.posonlyargs, *args.args]
    positional_defaults: list[Optional[ast.expr]] = [None] * (
        len(positional) - len(args.defaults)
    ) + list(args.defaults)
    positional_only_count = len(args.posonlyargs)

    for index, (argument, default) in enumerate(zip(positional, positional_defaults)):
        kind = "positional_only" if index < positional_only_count else "positional_or_keyword"
        annotation = _source_segment(source, argument.annotation)
        records.append(
            ParameterIR(
                name=argument.arg,
                kind=kind,
                annotation=annotation,
                dafny_type=python_annotation_to_dafny(argument.annotation, source=source),
                has_default=default is not None,
                default_source=_source_segment(source, default),
            )
        )

    if args.vararg is not None:
        annotation = _source_segment(source, args.vararg.annotation)
        records.append(
            ParameterIR(
                name=args.vararg.arg,
                kind="var_positional",
                annotation=annotation,
                dafny_type=python_annotation_to_dafny(args.vararg.annotation, source=source),
            )
        )

    for argument, default in zip(args.kwonlyargs, args.kw_defaults):
        annotation = _source_segment(source, argument.annotation)
        records.append(
            ParameterIR(
                name=argument.arg,
                kind="keyword_only",
                annotation=annotation,
                dafny_type=python_annotation_to_dafny(argument.annotation, source=source),
                has_default=default is not None,
                default_source=_source_segment(source, default),
            )
        )

    if args.kwarg is not None:
        annotation = _source_segment(source, args.kwarg.annotation)
        records.append(
            ParameterIR(
                name=args.kwarg.arg,
                kind="var_keyword",
                annotation=annotation,
                dafny_type=python_annotation_to_dafny(args.kwarg.annotation, source=source),
            )
        )

    return tuple(records)


def _literal(node: ast.AST) -> tuple[bool, Any]:
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _parse_call(source: str) -> tuple[Optional[str], tuple[Any, ...], tuple[tuple[str, Any], ...], bool]:
    try:
        expression = ast.parse(source, mode="eval").body
    except SyntaxError:
        return None, (), (), False
    if not isinstance(expression, ast.Call):
        return None, (), (), False

    call_name = ast.unparse(expression.func)
    positional: list[Any] = []
    keywords: list[tuple[str, Any]] = []
    all_literal = True

    for argument in expression.args:
        ok, value = _literal(argument)
        all_literal = all_literal and ok
        positional.append(value if ok else ast.unparse(argument))
    for keyword in expression.keywords:
        if keyword.arg is None:
            ok, value = _literal(keyword.value)
            all_literal = all_literal and ok
            keywords.append(("**", value if ok else ast.unparse(keyword.value)))
        else:
            ok, value = _literal(keyword.value)
            all_literal = all_literal and ok
            keywords.append((keyword.arg, value if ok else ast.unparse(keyword.value)))

    return call_name, tuple(positional), tuple(keywords), all_literal


def _parse_expected(expected_text: str) -> tuple[bool, Any]:
    # In doctest, no printed representation means the expression returned None.
    if not expected_text.strip():
        return True, None
    try:
        return True, ast.literal_eval(expected_text.strip())
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        # Some HumanEval docstrings contain an actual newline inside the
        # displayed representation of a quoted string (HumanEval/51 is the
        # canonical example).  It is invalid doctest layout but the intended
        # Python literal is unambiguous once that line break is escaped.
        if "\n" in expected_text:
            try:
                return True, ast.literal_eval(expected_text.strip().replace("\n", "\\n"))
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                pass
        return False, None


def _python_expression_is_complete(source: str) -> bool:
    try:
        ast.parse(source, mode="eval")
        return True
    except SyntaxError:
        return False


def _has_unterminated_string(source: str) -> bool:
    try:
        ast.parse(source, mode="eval")
    except SyntaxError as error:
        message = error.msg.lower()
        return "unterminated string" in message or "eol while scanning string" in message
    return False


def _fallback_doctest_examples(docstring: str) -> tuple[tuple[str, str, int], ...]:
    """Recover examples from docstrings rejected by the stdlib parser.

    HumanEval/51 embeds real newlines in a quoted argument and expected string.
    The standard doctest grammar correctly rejects that layout.  Dropping the
    examples would nevertheless lose benchmark semantics, so this conservative
    scanner repairs only line breaks needed to finish an unterminated quoted
    expression and leaves every expected-output line available as text.
    """

    lines = docstring.splitlines()
    recovered: list[tuple[str, str, int]] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        if not stripped.startswith(">>>"):
            index += 1
            continue

        line_number = index + 1
        source = stripped[3:].lstrip()
        index += 1
        while index < len(lines):
            next_stripped = lines[index].lstrip()
            explicit_continuation = next_stripped.startswith("...")
            if _python_expression_is_complete(source) and not explicit_continuation:
                break
            if next_stripped.startswith(">>>"):
                break
            continuation = next_stripped[3:].lstrip() if explicit_continuation else lines[index].strip()
            separator = "\\n" if _has_unterminated_string(source) else "\n"
            source += separator + continuation
            index += 1

        expected_lines: list[str] = []
        while index < len(lines) and not lines[index].lstrip().startswith(">>>"):
            expected_lines.append(lines[index].strip())
            index += 1
        while expected_lines and not expected_lines[0]:
            expected_lines.pop(0)
        while expected_lines and not expected_lines[-1]:
            expected_lines.pop()
        recovered.append((source.rstrip(), "\n".join(expected_lines), line_number))

    return tuple(recovered)


def _parse_examples(docstring: str) -> tuple[ExampleIR, ...]:
    if not docstring:
        return ()
    try:
        parsed_examples = doctest.DocTestParser().get_examples(docstring)
    except ValueError:
        parsed_examples = None

    results: list[ExampleIR] = []
    if parsed_examples is None:
        raw_examples = _fallback_doctest_examples(docstring)
    else:
        raw_examples = tuple(
            (example.source.rstrip(), example.want.rstrip("\n"), example.lineno + 1)
            for example in parsed_examples
        )

    for source, expected_text, line_number in raw_examples:
        call_name, positional, keywords, arguments_are_literal = _parse_call(source)
        expected_is_literal, expected_value = _parse_expected(expected_text)
        results.append(
            ExampleIR(
                source=source,
                expected_text=expected_text,
                line_number=line_number,
                call_name=call_name,
                positional_args=positional,
                keyword_args=keywords,
                arguments_are_literal=arguments_are_literal,
                expected_value=expected_value,
                expected_is_literal=expected_is_literal,
            )
        )
    return tuple(results)


def normalize_humaneval_problem(problem: Mapping[str, Any]) -> TaskIR:
    """Normalize a HumanEval JSON record without discarding source semantics."""

    prompt = problem.get("prompt")
    entry_point = problem.get("entry_point")
    task_id = problem.get("task_id", "")
    if not isinstance(prompt, str):
        raise TaskNormalizationError("problem['prompt'] must be a string")
    if not isinstance(entry_point, str) or not entry_point:
        raise TaskNormalizationError("problem['entry_point'] must be a non-empty string")
    if not isinstance(task_id, str):
        task_id = str(task_id)

    try:
        module = ast.parse(prompt, filename=task_id or "<humaneval-prompt>")
    except SyntaxError as error:
        raise TaskNormalizationError(
            f"cannot parse prompt for {task_id or entry_point}: {error.msg} at line {error.lineno}"
        ) from error

    targets = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == entry_point
    ]
    if not targets:
        nested_matches = [
            node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == entry_point
        ]
        placement = " (only nested definitions were found)" if nested_matches else ""
        raise TaskNormalizationError(
            f"top-level FunctionDef {entry_point!r} was not found{placement}"
        )
    if len(targets) != 1:
        raise TaskNormalizationError(
            f"expected exactly one top-level FunctionDef {entry_point!r}, found {len(targets)}"
        )

    function = targets[0]
    raw_docstring = ast.get_docstring(function, clean=False) or ""
    clean_docstring = ast.get_docstring(function, clean=True) or ""
    return_annotation = _source_segment(prompt, function.returns)

    return TaskIR(
        task_id=task_id,
        entry_point=entry_point,
        prompt=prompt,
        function_line=function.lineno,
        signature=_render_normalized_signature(function),
        signature_source=_extract_signature_source(prompt, function),
        raw_docstring=raw_docstring,
        docstring=clean_docstring,
        parameters=_parameter_records(prompt, function),
        return_annotation=return_annotation,
        return_type=python_annotation_to_dafny(function.returns, source=prompt),
        examples=_parse_examples(clean_docstring),
    )


def _coerce_task_ir(task_ir: TaskIR | Mapping[str, Any]) -> TaskIR:
    if isinstance(task_ir, TaskIR):
        return task_ir
    # Keeping this convenience at the rendering boundary makes integration with
    # JSON-loaded benchmark records straightforward and unambiguous.
    if "prompt" in task_ir and "entry_point" in task_ir:
        return normalize_humaneval_problem(task_ir)
    raise TypeError("render_problem_description expects TaskIR or a HumanEval problem mapping")


def render_problem_description(task_ir: TaskIR | Mapping[str, Any]) -> str:
    """Render a complete Dafny-generation prompt from structured task data."""

    task = _coerce_task_ir(task_ir)
    type_lines: list[str] = []
    for parameter in task.parameters:
        py_type = parameter.annotation or "<missing>"
        dafny_type = parameter.dafny_type.dafny or "UNSUPPORTED"
        type_lines.append(f"- 参数 {parameter.name}: Python {py_type} -> Dafny {dafny_type}")
    return_python = task.return_annotation or "<missing>"
    return_dafny = task.return_type.dafny or "UNSUPPORTED"
    type_lines.append(f"- 返回值: Python {return_python} -> Dafny {return_dafny}")

    declarations = tuple(
        dict.fromkeys(
            declaration
            for type_ir in (
                *(parameter.dafny_type for parameter in task.parameters),
                task.return_type,
            )
            for declaration in type_ir.required_declarations
        )
    )

    example_lines: list[str] = []
    for index, example in enumerate(task.examples, start=1):
        expectation = example.expected_text
        if example.expected_is_literal:
            expectation = repr(example.expected_value)
        elif not expectation:
            expectation = "<doctest 无输出>"
        example_lines.extend(
            (
                f"{index}. 调用: {example.source}",
                f"   期望: {expectation}",
            )
        )

    sections = [
        "请用 Dafny 语言实现以下 Python 任务，并给出能表达完整功能语义的规约。",
        f"任务标识：{task.task_id or '<unknown>'}",
        f"目标方法名：{task.entry_point}",
        "固定 Dafny 签名（必须逐字保留）：",
        render_dafny_signature(task),
        "",
        "Python 原始签名：",
        task.signature_source,
        "",
        "完整函数说明：",
        task.docstring or "<无文档字符串>",
        "",
        "类型映射：",
        *type_lines,
    ]
    if declarations:
        sections.extend(("", "需要的 Dafny 类型声明：", *declarations))
    if task.unsupported_reasons:
        sections.extend(("", "不支持/待显式建模的类型：", *(f"- {r}" for r in task.unsupported_reasons)))
    if example_lines:
        sections.extend(("", "公开 doctest 示例：", *example_lines))
    sections.extend(
        (
            "",
            "实现约束：",
            "1. 使用目标方法名，不得改用 prompt 中其他 helper 的签名。",
            "2. requires/ensures 必须与完整函数说明及所有公开示例一致。",
            "3. 不得通过加强 requires 排除题目要求处理的合法输入。",
            "4. 对标记为 UNSUPPORTED 的 Python 类型，必须先给出显式、语义等价的 Dafny 编码。",
            "5. 返回可由 Dafny 验证的完整代码。",
        )
    )
    return "\n".join(sections)


def render_dafny_signature(task_ir: TaskIR | Mapping[str, Any]) -> str:
    """Render the deterministic public Dafny signature for a normalized task."""
    task = _coerce_task_ir(task_ir)
    if not task.supported:
        return f"method {task.entry_point}(UNSUPPORTED)"
    params = ", ".join(
        f"{parameter.name}: {parameter.dafny_type.dafny}"
        for parameter in task.parameters
    )
    if task.return_type.kind == "tuple":
        returns = ", ".join(
            f"result{index}: {child.dafny}"
            for index, child in enumerate(task.return_type.arguments)
        )
    elif task.return_type.kind == "unit":
        returns = ""
    else:
        returns = f"result: {task.return_type.dafny}"
    suffix = f" returns ({returns})" if returns else ""
    return f"method {task.entry_point}({params}){suffix}"


__all__ = [
    "DafnyTypeIR",
    "ExampleIR",
    "ParameterIR",
    "TaskIR",
    "TaskNormalizationError",
    "normalize_humaneval_problem",
    "python_annotation_to_dafny",
    "render_dafny_signature",
    "render_problem_description",
]
