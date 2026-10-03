"""The deliberately small v0.1 profile of SpecIR. No models or audit agents."""

from dataclasses import dataclass
from typing import Any

from spec_ir import (
    SpecIR, SpecIRValidationError, TypeRef, interface_from_task_ir,
    parse_expression, render_dafny, render_expression,
)
from task_normalizer import TaskIR


PROFILE = "typed_spec_minimal_v1"
TYPES = {"int", "bool", "seq<int>"}
# Division/real arithmetic, recursion, quantifiers, sets and mutable state are
# deliberately excluded until their semantics and coverage have separate tests.
OPERATORS = {
    "var", "literal", "add", "sub", "mul", "neg", "abs", "min", "max",
    "eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not", "if",
    "len", "index", "slice", "concat", "seq", "contains",
}
ARITIES = {
    "var": {0}, "literal": {0}, "neg": {1}, "abs": {1}, "not": {1},
    "len": {1}, "if": {3}, "slice": {2, 3},
}


class UnsupportedTask(ValueError):
    """The public interface is outside the frozen v0.1 scope."""


@dataclass(frozen=True)
class CompiledSpec:
    ir: SpecIR
    contract: str
    reference_program: str
    examples_program: str
    examples_checked: int
    examples_skipped: int


def check_task(task: TaskIR) -> None:
    if not task.supported:
        raise UnsupportedTask("; ".join(task.unsupported_reasons))
    parameters, result, declarations = interface_from_task_ir(task.to_dict())
    if declarations or any(p.type.render() not in TYPES for p in (*parameters, result)):
        raise UnsupportedTask("v0.1 supports only int, bool and seq<int>")
    if any(p.has_default or p.kind != "positional_or_keyword" for p in task.parameters):
        raise UnsupportedTask("v0.1 requires ordinary parameters without defaults")
    # Reserve the output and the generated public-example method namespace.
    if task.entry_point.startswith("Mvp") or any(p.name == "result" for p in parameters):
        raise UnsupportedTask("interface collides with a reserved v0.1 binding")


def schema() -> dict:
    return {
        "schema_version": 1,
        "result": {"op": "operator", "args": ["expressions"]},
        "operators": sorted(OPERATORS),
        "types": sorted(TYPES),
        "examples": {
            "variable": {"op": "var", "name": "x"},
            "constant": {"op": "literal", "value": 1},
            "empty_sequence": {"op": "seq", "value": "int"},
        },
        "rules": [
            "Only schema_version and result are allowed at the top level.",
            "Result may use input parameters, never the output variable result.",
            "if has [condition, then, else]; contains has [item, sequence].",
            "No preconditions, helper functions, extra postconditions or raw source.",
            "Index and slice must be defined for all inputs, including empty sequences.",
        ],
    }


def _check_expression(raw: Any, depth: int = 0) -> int:
    if depth > 32 or not isinstance(raw, dict):
        raise SpecIRValidationError("expression must be an object of depth <= 32")
    op = raw.get("op")
    if not isinstance(op, str) or op not in OPERATORS:
        raise SpecIRValidationError(f"operator outside v0.1: {op!r}")
    allowed = {"op", "args"}
    if op == "var":
        allowed.add("name")
    if op in {"literal", "seq"}:
        allowed.add("value")
    if set(raw) - allowed:
        raise SpecIRValidationError(f"unexpected fields for {op}: {sorted(set(raw) - allowed)}")
    args = raw.get("args", [])
    if not isinstance(args, list):
        raise SpecIRValidationError("args must be a list")
    arities = ARITIES.get(op, {2})
    if op not in {"seq", "and", "or"} and len(args) not in arities:
        raise SpecIRValidationError(f"invalid arity for {op}")
    if op in {"and", "or"} and len(args) < 2:
        raise SpecIRValidationError(f"{op} requires at least two arguments")
    if op == "literal" and type(raw.get("value")) not in {int, bool}:
        raise SpecIRValidationError("v0.1 literals must be int or bool")
    if op == "seq" and raw.get("value", "int") != "int":
        raise SpecIRValidationError("v0.1 sequences contain int only")
    count = 1
    for arg in args:
        count += _check_expression(arg, depth + 1)
        if count > 256:
            raise SpecIRValidationError("expression exceeds 256 nodes")
    return count


def compile_spec(payload: dict, task: TaskIR) -> CompiledSpec:
    """Compile a result definition, without claiming it expresses user intent."""
    check_task(task)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "result"}:
        raise SpecIRValidationError("expected exactly schema_version and result")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise SpecIRValidationError("schema_version must be integer 1")
    _check_expression(payload["result"])
    ir = SpecIR.from_model_output(
        payload, task_id=task.task_id, entry_point=task.entry_point, task_ir=task.to_dict(),
    )
    # Intermediate types are also constrained, not merely the public signature.
    def check_nodes(expr):
        from spec_ir import infer_expression_type
        typ = infer_expression_type(expr, {p.name: p.type for p in ir.parameters}, {})
        if typ.render() not in TYPES:
            raise SpecIRValidationError(f"intermediate type outside v0.1: {typ.render()}")
        for arg in expr.args:
            check_nodes(arg)
    check_nodes(ir.result_expression)
    contract = render_dafny(ir)
    reference = contract + "\n{\n  result := " + render_expression(ir.result_expression) + ";\n}\n"
    lines = ["method MvpPublicExamples()", "{"]
    checked = skipped = 0
    for example in task.examples:
        if not (example.arguments_are_literal and example.expected_is_literal
                and example.call_name == task.entry_point):
            skipped += 1
            continue
        values = dict(zip((p.name for p in ir.parameters), example.positional_args))
        if len(example.positional_args) > len(ir.parameters):
            raise SpecIRValidationError("public example has too many arguments")
        for name, value in example.keyword_args:
            if name in values:
                raise SpecIRValidationError("duplicate public-example argument")
            values[name] = value
        if set(values) != {p.name for p in ir.parameters}:
            raise SpecIRValidationError("public example does not match the frozen interface")
        args = ", ".join(_value_source(values[p.name], p.type) for p in ir.parameters)
        expected = _value_source(example.expected_value, ir.result.type)
        lines.extend([
            f"  var actual{checked} := {ir.entry_point}({args});",
            f"  assert actual{checked} == {expected};",
        ])
        checked += 1
    lines.append("}")
    return CompiledSpec(ir, contract, reference, reference + "\n" + "\n".join(lines), checked, skipped)


def _value_source(value: Any, typ: TypeRef) -> str:
    if typ.render() == "seq<int>" and type(value) is list:
        return "[" + ", ".join(_value_source(v, TypeRef("int")) for v in value) + "]"
    expected = {"int": int, "bool": bool}.get(typ.render())
    if expected is None or type(value) is not expected:
        raise SpecIRValidationError(f"public-example value does not match {typ.render()}")
    return render_expression(parse_expression({"op": "literal", "value": value}))
