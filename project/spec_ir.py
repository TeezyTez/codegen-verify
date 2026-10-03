"""Typed, language-neutral specification IR and deterministic Dafny rendering.

The model is allowed to choose semantic operators, but it never writes Dafny.
Every expression is parsed into this small AST, type checked against the frozen
public interface, and rendered by trusted code.  This module is deliberately
independent from model providers and experiment orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping, Sequence


class SpecIRValidationError(ValueError):
    """A deterministic error in the structure or typing of a specification."""


@dataclass(frozen=True)
class TypeRef:
    name: str
    arguments: tuple["TypeRef", ...] = ()

    def render(self) -> str:
        if not self.arguments:
            return self.name
        return f"{self.name}<" + ", ".join(item.render() for item in self.arguments) + ">"

    @property
    def is_numeric(self) -> bool:
        return self.name in {"int", "real"} and not self.arguments


@dataclass(frozen=True)
class Binding:
    name: str
    type: TypeRef

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type.render()}


@dataclass(frozen=True)
class Expression:
    op: str
    args: tuple["Expression", ...] = ()
    value: Any = None
    name: str = ""
    bindings: tuple[Binding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"op": self.op}
        if self.name:
            result["name"] = self.name
        if self.value is not None:
            result["value"] = self.value
        if self.args:
            result["args"] = [item.to_dict() for item in self.args]
        if self.bindings:
            result["vars"] = [item.to_dict() for item in self.bindings]
        return result


@dataclass(frozen=True)
class Clause:
    id: str
    expression: Expression
    requirement_ids: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "expression": self.expression.to_dict(),
            "requirement_ids": list(self.requirement_ids),
            "description": self.description,
        }


@dataclass(frozen=True)
class FunctionDefinition:
    name: str
    parameters: tuple[Binding, ...]
    return_type: TypeRef
    body: Expression
    decreases: tuple[Expression, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": [item.to_dict() for item in self.parameters],
            "return_type": self.return_type.render(),
            "body": self.body.to_dict(),
            "decreases": [item.to_dict() for item in self.decreases],
        }


@dataclass(frozen=True)
class SpecIR:
    schema_version: int
    task_id: str
    entry_point: str
    parameters: tuple[Binding, ...]
    result: Binding
    result_expression: Expression
    preconditions: tuple[Clause, ...] = ()
    postconditions: tuple[Clause, ...] = ()
    definitions: tuple[FunctionDefinition, ...] = ()
    required_declarations: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "entry_point": self.entry_point,
            "interface": {
                "parameters": [item.to_dict() for item in self.parameters],
                "result": self.result.to_dict(),
            },
            "result": self.result_expression.to_dict(),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "postconditions": [item.to_dict() for item in self.postconditions],
            "definitions": [item.to_dict() for item in self.definitions],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_model_output(
        cls,
        payload: Mapping[str, Any],
        *,
        task_id: str,
        entry_point: str,
        task_ir: Mapping[str, Any],
    ) -> "SpecIR":
        """Parse model semantics while deriving the public interface from trusted TaskIR."""

        if int(payload.get("schema_version", 1)) != 1:
            raise SpecIRValidationError("schema_version must be 1")
        declared_entry = str(payload.get("entry_point") or entry_point)
        if declared_entry != entry_point:
            raise SpecIRValidationError(
                f"entry_point is frozen as {entry_point!r}, got {declared_entry!r}"
            )

        parameters, result, declarations = interface_from_task_ir(task_ir)
        if "result" not in payload:
            raise SpecIRValidationError("result expression is required")
        result_expression = parse_expression(payload["result"], path="result")
        definitions = _parse_definitions(payload.get("definitions", []))
        preconditions = _parse_clauses(payload.get("preconditions", []), "PRE")
        postconditions = _parse_clauses(payload.get("postconditions", []), "POST")

        spec = cls(
            schema_version=1,
            task_id=task_id,
            entry_point=entry_point,
            parameters=parameters,
            result=result,
            result_expression=result_expression,
            preconditions=preconditions,
            postconditions=postconditions,
            definitions=definitions,
            required_declarations=declarations,
            metadata=dict(payload.get("metadata") or {}),
        )
        validate_spec_ir(spec)
        return spec


_TYPE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_RESERVED = {
    "assert", "assume", "bool", "break", "case", "class", "datatype", "else",
    "ensures", "exists", "false", "forall", "function", "ghost", "if", "in",
    "int", "lemma", "match", "method", "modifies", "new", "null", "old",
    "predicate", "reads", "real", "requires", "return", "returns", "seq", "set",
    "then", "true", "var", "while",
}


def parse_type(text: str) -> TypeRef:
    """Parse the small Dafny type surface supported by the IR."""

    source = re.sub(r"\s+", "", str(text or ""))
    if not source:
        raise SpecIRValidationError("type must be non-empty")
    index = 0

    def parse_one() -> TypeRef:
        nonlocal index
        match = _TYPE_TOKEN.match(source, index)
        if match is None:
            raise SpecIRValidationError(f"invalid type near {source[index:]!r}")
        name = match.group(0)
        index = match.end()
        arguments: list[TypeRef] = []
        if index < len(source) and source[index] == "<":
            index += 1
            while True:
                arguments.append(parse_one())
                if index < len(source) and source[index] == ",":
                    index += 1
                    continue
                if index >= len(source) or source[index] != ">":
                    raise SpecIRValidationError(f"unclosed type arguments in {source!r}")
                index += 1
                break
        return TypeRef(name, tuple(arguments))

    result = parse_one()
    if index != len(source):
        raise SpecIRValidationError(f"unexpected type suffix {source[index:]!r}")
    if result.name in {"seq", "set", "multiset", "Option"} and len(result.arguments) != 1:
        raise SpecIRValidationError(f"{result.name} requires exactly one type argument")
    return result


def interface_from_task_ir(
    task_ir: Mapping[str, Any],
) -> tuple[tuple[Binding, ...], Binding, tuple[str, ...]]:
    raw_parameters = task_ir.get("parameters")
    raw_return = task_ir.get("return_type")
    if not isinstance(raw_parameters, (list, tuple)) or not isinstance(raw_return, Mapping):
        raise SpecIRValidationError("TaskIR must contain typed parameters and return_type")

    parameters: list[Binding] = []
    declarations: list[str] = []
    for index, raw in enumerate(raw_parameters):
        if not isinstance(raw, Mapping):
            raise SpecIRValidationError(f"TaskIR parameter {index} is invalid")
        name = _checked_identifier(str(raw.get("name") or ""), f"parameter {index}")
        type_payload = raw.get("dafny_type")
        if not isinstance(type_payload, Mapping) or not type_payload.get("supported"):
            raise SpecIRValidationError(f"TaskIR parameter {name} has no supported Dafny type")
        parameters.append(Binding(name, parse_type(str(type_payload.get("dafny") or ""))))
        declarations.extend(str(item) for item in type_payload.get("required_declarations", []))

    if not raw_return.get("supported"):
        raise SpecIRValidationError("TaskIR return value has no supported Dafny type")
    result = Binding("result", parse_type(str(raw_return.get("dafny") or "")))
    declarations.extend(str(item) for item in raw_return.get("required_declarations", []))
    return tuple(parameters), result, tuple(dict.fromkeys(item for item in declarations if item))


def parse_expression(value: Any, *, path: str = "expression") -> Expression:
    if not isinstance(value, Mapping):
        raise SpecIRValidationError(f"{path} must be an expression object")
    op = str(value.get("op") or "").strip().lower()
    if not op:
        raise SpecIRValidationError(f"{path}.op is required")
    raw_args = value.get("args", [])
    if not isinstance(raw_args, list):
        raise SpecIRValidationError(f"{path}.args must be a list")
    args = tuple(
        parse_expression(item, path=f"{path}.args[{index}]")
        for index, item in enumerate(raw_args)
    )
    name = str(value.get("name") or "").strip()
    bindings: list[Binding] = []
    raw_bindings = value.get("vars", [])
    if not isinstance(raw_bindings, list):
        raise SpecIRValidationError(f"{path}.vars must be a list")
    for index, item in enumerate(raw_bindings):
        if not isinstance(item, Mapping):
            raise SpecIRValidationError(f"{path}.vars[{index}] must be an object")
        binding_name = _checked_identifier(
            str(item.get("name") or ""), f"{path}.vars[{index}]"
        )
        bindings.append(Binding(binding_name, parse_type(str(item.get("type") or ""))))
    return Expression(
        op=op,
        args=args,
        value=value.get("value"),
        name=name,
        bindings=tuple(bindings),
    )


def _parse_definitions(value: Any) -> tuple[FunctionDefinition, ...]:
    if not isinstance(value, list):
        raise SpecIRValidationError("definitions must be a list")
    definitions: list[FunctionDefinition] = []
    for index, raw in enumerate(value):
        path = f"definitions[{index}]"
        if not isinstance(raw, Mapping):
            raise SpecIRValidationError(f"{path} must be an object")
        name = _checked_identifier(str(raw.get("name") or ""), path)
        raw_parameters = raw.get("parameters", [])
        if not isinstance(raw_parameters, list):
            raise SpecIRValidationError(f"{path}.parameters must be a list")
        parameters = tuple(
            Binding(
                _checked_identifier(str(item.get("name") or ""), f"{path}.parameters"),
                parse_type(str(item.get("type") or "")),
            )
            for item in raw_parameters
            if isinstance(item, Mapping)
        )
        if len(parameters) != len(raw_parameters):
            raise SpecIRValidationError(f"{path}.parameters contains an invalid entry")
        body = parse_expression(raw.get("body"), path=f"{path}.body")
        raw_decreases = raw.get("decreases", [])
        if not isinstance(raw_decreases, list):
            raise SpecIRValidationError(f"{path}.decreases must be a list")
        definitions.append(FunctionDefinition(
            name=name,
            parameters=parameters,
            return_type=parse_type(str(raw.get("return_type") or "")),
            body=body,
            decreases=tuple(
                parse_expression(item, path=f"{path}.decreases[{item_index}]")
                for item_index, item in enumerate(raw_decreases)
            ),
        ))
    return tuple(definitions)


def _parse_clauses(value: Any, prefix: str) -> tuple[Clause, ...]:
    if not isinstance(value, list):
        raise SpecIRValidationError(f"{prefix.lower()}conditions must be a list")
    clauses: list[Clause] = []
    for index, raw in enumerate(value, start=1):
        path = f"{prefix.lower()}conditions[{index - 1}]"
        expression_payload = raw
        clause_id = f"{prefix}-{index:03d}"
        requirements: tuple[str, ...] = ()
        description = ""
        if isinstance(raw, Mapping) and "expression" in raw:
            expression_payload = raw["expression"]
            clause_id = str(raw.get("id") or clause_id)
            raw_requirements = raw.get("requirement_ids", [])
            if not isinstance(raw_requirements, list):
                raise SpecIRValidationError(f"{path}.requirement_ids must be a list")
            requirements = tuple(str(item) for item in raw_requirements if str(item))
            description = str(raw.get("description") or "")
        clauses.append(Clause(
            id=_checked_identifier(clause_id.replace("-", "_"), path).replace("_", "-"),
            expression=parse_expression(expression_payload, path=f"{path}.expression"),
            requirement_ids=requirements,
            description=description,
        ))
    return tuple(clauses)


def validate_spec_ir(spec: SpecIR) -> None:
    _checked_identifier(spec.entry_point, "entry_point")
    names = [item.name for item in spec.parameters]
    if spec.result.name in names:
        raise SpecIRValidationError("public parameters cannot shadow the result binding")
    if len(names) != len(set(names)):
        raise SpecIRValidationError("public parameter names must be unique")
    function_names = [item.name for item in spec.definitions]
    if len(function_names) != len(set(function_names)):
        raise SpecIRValidationError("function definition names must be unique")
    if spec.entry_point in function_names:
        raise SpecIRValidationError("a helper function cannot shadow the public method")

    functions = {item.name: item for item in spec.definitions}
    public_env = {item.name: item.type for item in spec.parameters}

    for definition in spec.definitions:
        parameter_names = [item.name for item in definition.parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise SpecIRValidationError(f"function {definition.name} has duplicate parameters")
        env = {item.name: item.type for item in definition.parameters}
        body_type = infer_expression_type(definition.body, env, functions, path=definition.name)
        _require_same_type(body_type, definition.return_type, f"function {definition.name} body")
        for index, decreases in enumerate(definition.decreases):
            decrease_type = infer_expression_type(
                decreases, env, functions, path=f"{definition.name}.decreases[{index}]"
            )
            if decrease_type.name not in {"int", "nat"} or decrease_type.arguments:
                raise SpecIRValidationError(
                    f"{definition.name}.decreases[{index}] must be int or nat"
                )

    result_type = infer_expression_type(
        spec.result_expression, public_env, functions, path="result"
    )
    _require_same_type(result_type, spec.result.type, "result expression")
    for clause in spec.preconditions:
        clause_type = infer_expression_type(
            clause.expression, public_env, functions, path=clause.id
        )
        _require_same_type(clause_type, TypeRef("bool"), clause.id)
    post_env = {**public_env, spec.result.name: spec.result.type}
    for clause in spec.postconditions:
        clause_type = infer_expression_type(clause.expression, post_env, functions, path=clause.id)
        _require_same_type(clause_type, TypeRef("bool"), clause.id)


def infer_expression_type(
    expression: Expression,
    env: Mapping[str, TypeRef],
    functions: Mapping[str, FunctionDefinition],
    *,
    path: str = "expression",
) -> TypeRef:
    op = expression.op
    args = expression.args

    if op == "var":
        if not expression.name or expression.name not in env:
            raise SpecIRValidationError(f"{path}: unknown variable {expression.name!r}")
        return env[expression.name]
    if op == "literal":
        return _literal_type(expression.value, path)
    if op in {"and", "or"}:
        _require_arity(op, args, path, minimum=2)
        for index, arg in enumerate(args):
            _require_same_type(
                infer_expression_type(arg, env, functions, path=f"{path}.args[{index}]"),
                TypeRef("bool"),
                path,
            )
        return TypeRef("bool")
    if op in {"not"}:
        _require_arity(op, args, path, exact=1)
        _require_same_type(
            infer_expression_type(args[0], env, functions, path=f"{path}.args[0]"),
            TypeRef("bool"), path,
        )
        return TypeRef("bool")
    if op in {"implies", "iff"}:
        _require_arity(op, args, path, exact=2)
        for index, arg in enumerate(args):
            _require_same_type(
                infer_expression_type(arg, env, functions, path=f"{path}.args[{index}]"),
                TypeRef("bool"), path,
            )
        return TypeRef("bool")
    if op in {"eq", "ne"}:
        _require_arity(op, args, path, exact=2)
        left = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        right = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        _require_same_type(left, right, path)
        return TypeRef("bool")
    if op in {"lt", "le", "gt", "ge"}:
        _require_arity(op, args, path, exact=2)
        left = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        right = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        _require_same_type(left, right, path)
        if not left.is_numeric:
            raise SpecIRValidationError(f"{path}: {op} requires numeric operands")
        return TypeRef("bool")
    if op in {"add", "sub", "mul", "div", "mod", "min", "max"}:
        _require_arity(op, args, path, exact=2)
        left = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        right = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        _require_same_type(left, right, path)
        if not left.is_numeric:
            raise SpecIRValidationError(f"{path}: {op} requires numeric operands")
        if op == "mod" and left.name != "int":
            raise SpecIRValidationError(f"{path}: mod requires int operands")
        return left
    if op in {"neg", "abs"}:
        _require_arity(op, args, path, exact=1)
        result = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        if not result.is_numeric:
            raise SpecIRValidationError(f"{path}: {op} requires a numeric operand")
        return result
    if op == "to_real":
        _require_arity(op, args, path, exact=1)
        source = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        _require_same_type(source, TypeRef("int"), path)
        return TypeRef("real")
    if op == "if":
        _require_arity(op, args, path, exact=3)
        condition = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        _require_same_type(condition, TypeRef("bool"), path)
        left = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        right = infer_expression_type(args[2], env, functions, path=f"{path}.args[2]")
        _require_same_type(left, right, path)
        return left
    if op == "len":
        _require_arity(op, args, path, exact=1)
        source = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        if source.name not in {"seq", "set", "multiset", "string"}:
            raise SpecIRValidationError(f"{path}: len requires a sequence, set, multiset, or string")
        return TypeRef("int")
    if op == "index":
        _require_arity(op, args, path, exact=2)
        source = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        index = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        _require_same_type(index, TypeRef("int"), path)
        if source.name == "string":
            return TypeRef("char")
        if source.name != "seq" or len(source.arguments) != 1:
            raise SpecIRValidationError(f"{path}: index requires a sequence or string")
        return source.arguments[0]
    if op == "slice":
        if len(args) not in {2, 3}:
            raise SpecIRValidationError(f"{path}: slice requires sequence, start, and optional end")
        source = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        if source.name not in {"seq", "string"}:
            raise SpecIRValidationError(f"{path}: slice requires a sequence or string")
        for index, arg in enumerate(args[1:], start=1):
            _require_same_type(
                infer_expression_type(arg, env, functions, path=f"{path}.args[{index}]"),
                TypeRef("int"), path,
            )
        return source
    if op == "concat":
        _require_arity(op, args, path, exact=2)
        left = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        right = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        _require_same_type(left, right, path)
        if left.name not in {"seq", "string"}:
            raise SpecIRValidationError(f"{path}: concat requires sequences or strings")
        return left
    if op in {"seq", "set"}:
        if not args:
            type_text = str(expression.value or "")
            if not type_text:
                raise SpecIRValidationError(f"{path}: empty {op} requires element type in value")
            return TypeRef(op, (parse_type(type_text),))
        item_types = [
            infer_expression_type(arg, env, functions, path=f"{path}.args[{index}]")
            for index, arg in enumerate(args)
        ]
        for item in item_types[1:]:
            _require_same_type(item_types[0], item, path)
        return TypeRef(op, (item_types[0],))
    if op == "contains":
        _require_arity(op, args, path, exact=2)
        item = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        container = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        if container.name == "string":
            _require_same_type(item, TypeRef("char"), path)
        elif container.name not in {"seq", "set", "multiset"} or len(container.arguments) != 1:
            raise SpecIRValidationError(f"{path}: contains requires a sequence, set, or multiset")
        else:
            _require_same_type(item, container.arguments[0], path)
        return TypeRef("bool")
    if op in {"set_of", "multiset_of"}:
        _require_arity(op, args, path, exact=1)
        source = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        if source.name != "seq" or len(source.arguments) != 1:
            raise SpecIRValidationError(f"{path}: {op} requires a sequence")
        return TypeRef("set" if op == "set_of" else "multiset", source.arguments)
    if op in {"union", "intersection", "difference"}:
        _require_arity(op, args, path, exact=2)
        left = infer_expression_type(args[0], env, functions, path=f"{path}.args[0]")
        right = infer_expression_type(args[1], env, functions, path=f"{path}.args[1]")
        _require_same_type(left, right, path)
        if left.name not in {"set", "multiset"}:
            raise SpecIRValidationError(f"{path}: {op} requires set or multiset operands")
        return left
    if op == "call":
        if expression.name not in functions:
            raise SpecIRValidationError(f"{path}: unknown pure function {expression.name!r}")
        definition = functions[expression.name]
        _require_arity(op, args, path, exact=len(definition.parameters))
        for index, (arg, parameter) in enumerate(zip(args, definition.parameters)):
            actual = infer_expression_type(arg, env, functions, path=f"{path}.args[{index}]")
            _require_same_type(actual, parameter.type, f"{path} argument {parameter.name}")
        return definition.return_type
    if op in {"forall", "exists"}:
        if not expression.bindings:
            raise SpecIRValidationError(f"{path}: {op} requires at least one bound variable")
        if len(args) not in {1, 2}:
            raise SpecIRValidationError(f"{path}: {op} requires body, with optional range")
        nested = dict(env)
        for binding in expression.bindings:
            if binding.name in nested:
                raise SpecIRValidationError(f"{path}: bound variable {binding.name!r} shadows a name")
            nested[binding.name] = binding.type
        for index, arg in enumerate(args):
            actual = infer_expression_type(arg, nested, functions, path=f"{path}.args[{index}]")
            _require_same_type(actual, TypeRef("bool"), path)
        return TypeRef("bool")
    raise SpecIRValidationError(f"{path}: unsupported operator {op!r}")


def render_dafny(spec: SpecIR) -> str:
    """Render validated IR. No model-produced source text crosses this boundary."""

    validate_spec_ir(spec)
    blocks: list[str] = [*spec.required_declarations]
    for definition in spec.definitions:
        signature = ", ".join(
            f"{item.name}: {item.type.render()}" for item in definition.parameters
        )
        lines = [f"function {definition.name}({signature}): {definition.return_type.render()}"]
        if definition.decreases:
            lines.append("  decreases " + ", ".join(render_expression(item) for item in definition.decreases))
        lines.extend(["{", f"  {render_expression(definition.body)}", "}"])
        blocks.append("\n".join(lines))

    params = ", ".join(f"{item.name}: {item.type.render()}" for item in spec.parameters)
    lines = [
        f"method {spec.entry_point}({params}) returns ({spec.result.name}: {spec.result.type.render()})"
    ]
    lines.extend(f"  requires {render_expression(item.expression)}" for item in spec.preconditions)
    lines.append(
        f"  ensures {spec.result.name} == {render_expression(spec.result_expression)}"
    )
    lines.extend(f"  ensures {render_expression(item.expression)}" for item in spec.postconditions)
    blocks.append("\n".join(lines))
    return "\n\n".join(block for block in blocks if block.strip()).strip()


def render_expression(expression: Expression) -> str:
    op = expression.op
    args = expression.args
    if op == "var":
        return expression.name
    if op == "literal":
        return _render_literal(expression.value)
    binary = {
        "implies": "==>", "iff": "<==>", "eq": "==", "ne": "!=",
        "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "add": "+",
        "sub": "-", "mul": "*", "div": "/", "mod": "%", "concat": "+",
        "union": "+", "intersection": "*", "difference": "-",
    }
    if op in binary:
        return f"({render_expression(args[0])} {binary[op]} {render_expression(args[1])})"
    if op in {"and", "or"}:
        symbol = "&&" if op == "and" else "||"
        return "(" + f" {symbol} ".join(render_expression(item) for item in args) + ")"
    if op == "not":
        return f"(!{render_expression(args[0])})"
    if op == "neg":
        return f"(-{render_expression(args[0])})"
    if op == "abs":
        value = render_expression(args[0])
        return f"(if {value} < 0 then -{value} else {value})"
    if op in {"min", "max"}:
        left, right = render_expression(args[0]), render_expression(args[1])
        comparison = "<=" if op == "min" else ">="
        return f"(if {left} {comparison} {right} then {left} else {right})"
    if op == "to_real":
        return f"({render_expression(args[0])} as real)"
    if op == "if":
        return (
            f"(if {render_expression(args[0])} then {render_expression(args[1])} "
            f"else {render_expression(args[2])})"
        )
    if op == "len":
        return f"|{render_expression(args[0])}|"
    if op == "index":
        return f"{render_expression(args[0])}[{render_expression(args[1])}]"
    if op == "slice":
        end = render_expression(args[2]) if len(args) == 3 else ""
        return f"{render_expression(args[0])}[{render_expression(args[1])}..{end}]"
    if op in {"seq", "set"}:
        opening, closing = ("[", "]") if op == "seq" else ("{", "}")
        return opening + ", ".join(render_expression(item) for item in args) + closing
    if op == "contains":
        return f"({render_expression(args[0])} in {render_expression(args[1])})"
    if op == "set_of":
        return f"set {render_expression(args[0])}"
    if op == "multiset_of":
        return f"multiset({render_expression(args[0])})"
    if op == "call":
        return f"{expression.name}(" + ", ".join(render_expression(item) for item in args) + ")"
    if op in {"forall", "exists"}:
        bindings = ", ".join(
            f"{item.name}: {item.type.render()}" for item in expression.bindings
        )
        if len(args) == 1:
            body = render_expression(args[0])
        else:
            connector = "==>" if op == "forall" else "&&"
            body = f"{render_expression(args[0])} {connector} {render_expression(args[1])}"
        return f"({op} {bindings} :: {body})"
    raise SpecIRValidationError(f"cannot render unsupported operator {op!r}")


def model_schema() -> dict[str, Any]:
    """Compact schema description used in prompts and serialized manifests."""

    return {
        "schema_version": 1,
        "entry_point": "must match the frozen interface",
        "result": {"op": "expression operator", "args": ["recursive expressions"]},
        "preconditions": [
            {"id": "PRE-001", "expression": {"op": "..."}, "requirement_ids": []}
        ],
        "postconditions": [
            {"id": "POST-001", "expression": {"op": "..."}, "requirement_ids": []}
        ],
        "definitions": [
            {
                "name": "Reference",
                "parameters": [{"name": "x", "type": "int"}],
                "return_type": "int",
                "body": {"op": "var", "name": "x"},
                "decreases": [],
            }
        ],
        "operators": sorted({
            "var", "literal", "and", "or", "not", "implies", "iff", "eq", "ne",
            "lt", "le", "gt", "ge", "add", "sub", "mul", "div", "mod", "neg",
            "abs", "min", "max", "to_real", "if", "len", "index", "slice", "concat",
            "seq", "set", "contains", "set_of", "multiset_of", "union", "intersection",
            "difference", "call", "forall", "exists",
        }),
    }


def _checked_identifier(value: str, path: str) -> str:
    if not _IDENTIFIER.fullmatch(value) or value in _RESERVED:
        raise SpecIRValidationError(f"{path}: invalid identifier {value!r}")
    return value


def _literal_type(value: Any, path: str) -> TypeRef:
    if isinstance(value, bool):
        return TypeRef("bool")
    if isinstance(value, int):
        return TypeRef("int")
    if isinstance(value, float):
        return TypeRef("real")
    if isinstance(value, str):
        return TypeRef("string")
    raise SpecIRValidationError(f"{path}: unsupported literal {value!r}")


def _render_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = format(value, ".15g")
        return text if "." in text else text + ".0"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    raise SpecIRValidationError(f"unsupported literal {value!r}")


def _require_arity(
    op: str,
    args: Sequence[Expression],
    path: str,
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    if exact is not None and len(args) != exact:
        raise SpecIRValidationError(f"{path}: {op} requires exactly {exact} arguments")
    if minimum is not None and len(args) < minimum:
        raise SpecIRValidationError(f"{path}: {op} requires at least {minimum} arguments")


def _require_same_type(actual: TypeRef, expected: TypeRef, path: str) -> None:
    if actual != expected:
        raise SpecIRValidationError(
            f"{path}: expected {expected.render()}, got {actual.render()}"
        )
