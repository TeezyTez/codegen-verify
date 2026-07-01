"""
Lightweight specification adequacy checker.

The checker is intentionally conservative: it does not prove that a Dafny
specification captures the natural-language task. Instead, it reports evidence,
risks, and missing obligations that are useful for research analysis.
"""
import re
from typing import Any


def check_spec_adequacy(
    spec: str,
    problem_desc: str = "",
    entry_point: str = "",
    dafny_verified: bool | None = None,
    humaneval_passed: bool | None = None,
) -> dict[str, Any]:
    spec = spec or ""
    problem_desc = problem_desc or ""
    signature = _parse_method_signature(spec)
    clauses = _extract_clauses(spec)
    desc_features = _problem_features(problem_desc)

    flags: list[str] = []
    missing: list[str] = []
    evidence: dict[str, Any] = {
        "signature": signature,
        "requires": clauses["requires"],
        "ensures": clauses["ensures"],
        "desc_features": desc_features,
    }

    score = 100

    if not signature:
        flags.append("missing_method_signature")
        missing.append("Provide a Dafny method signature matching the target function.")
        score -= 35
    elif entry_point and signature["name"] != entry_point:
        flags.append("entry_point_mismatch")
        missing.append(f"Expected method `{entry_point}` but spec declares `{signature['name']}`.")
        score -= 25

    if not clauses["ensures"]:
        flags.append("no_postcondition")
        missing.append("Add postconditions that constrain the returned value.")
        score -= 45
    elif not any("result" in clause for clause in clauses["ensures"]):
        flags.append("postcondition_does_not_constrain_result")
        missing.append("Mention `result` in ensures clauses.")
        score -= 30

    trivial = _trivial_ensures(clauses["ensures"])
    if trivial:
        flags.append("trivial_or_shape_only_postcondition")
        missing.append("Replace trivial/type/shape-only ensures with semantic obligations.")
        evidence["trivial_ensures"] = trivial
        score -= 25

    mentioned_params = _mentioned_params(signature, spec) if signature else []
    if signature and signature["params"] and len(mentioned_params) == 0 and clauses["ensures"]:
        flags.append("postcondition_ignores_inputs")
        missing.append("Relate `result` to at least one input parameter.")
        score -= 30
    evidence["mentioned_params"] = mentioned_params

    semantic_score = _semantic_signal_score(spec)
    evidence["semantic_signal_score"] = semantic_score
    if semantic_score < 2 and clauses["ensures"]:
        flags.append("low_semantic_signal")
        missing.append("Add semantic operators such as quantifiers, equality, ordering, length, or helper predicates.")
        score -= 15

    feature_result = _check_feature_obligations(spec, desc_features)
    flags.extend(feature_result["flags"])
    missing.extend(feature_result["missing"])
    score -= feature_result["penalty"]

    if dafny_verified is True and humaneval_passed is False:
        flags.append("verified_but_behavior_failed")
        missing.append("Dafny verified the code, but HumanEval failed; inspect spec adequacy or Python-Dafny semantic mapping.")
        score -= 30
    elif dafny_verified is True and flags:
        flags.append("verified_with_spec_risk")
    elif dafny_verified is False and "no_postcondition" in flags:
        flags.append("verification_failure_with_weak_spec")

    score = max(0, min(100, score))
    level = _score_level(score, flags)

    return {
        "score": score,
        "level": level,
        "flags": sorted(set(flags)),
        "missing_obligations": _dedupe(missing),
        "evidence": evidence,
        "recommendations": _recommendations(flags, desc_features),
    }


def _parse_method_signature(spec: str) -> dict[str, Any] | None:
    match = re.search(
        r"method\s+(\w+)\s*\((.*?)\)\s*(?:returns\s*\((.*?)\))?",
        spec,
        flags=re.DOTALL,
    )
    if not match:
        return None
    return {
        "name": match.group(1),
        "params": _parse_params(match.group(2) or ""),
        "returns": _parse_params(match.group(3) or ""),
    }


def _parse_params(text: str) -> list[dict[str, str]]:
    result = []
    current = ""
    depth = 0
    for ch in text:
        if ch in "<({[":
            depth += 1
        elif ch in ">)}]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            _append_param(result, current)
            current = ""
        else:
            current += ch
    _append_param(result, current)
    return result


def _append_param(result: list[dict[str, str]], text: str) -> None:
    text = text.strip()
    if not text or ":" not in text:
        return
    name, typ = text.split(":", 1)
    result.append({"name": name.strip(), "type": typ.strip()})


def _extract_clauses(spec: str) -> dict[str, list[str]]:
    requires = []
    ensures = []
    for line in spec.splitlines():
        stripped = line.strip()
        if stripped.startswith("requires"):
            requires.append(stripped)
        elif stripped.startswith("ensures"):
            ensures.append(stripped)
    return {"requires": requires, "ensures": ensures}


def _problem_features(problem_desc: str) -> dict[str, bool]:
    text = _semantic_problem_text(problem_desc)
    signature_text = _signature_text(problem_desc)

    def has_word(*words: str) -> bool:
        return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)

    return {
        "bool_result": "-> bool" in signature_text or has_word("true", "false", "boolean"),
        "sequence_task": "list[" in signature_text or has_word("list", "seq", "array", "sequence"),
        "string_task": "str" in signature_text or has_word("string"),
        "ordering": has_word("sorted", "increasing", "decreasing", "maximum", "minimum", "largest", "smallest"),
        "existential": any(phrase in text for phrase in ["exists", "there is", "there are", "at least one"]),
        "universal": has_word("all", "every", "each") or "for any" in text,
        "length_or_size": has_word("length", "size", "empty", "non-empty", "nonempty"),
        "threshold_or_distance": has_word("threshold", "close", "distance", "difference", "absolute"),
        "sum_or_prefix": has_word("sum", "prefix", "balance", "total"),
        "examples_present": ">>>" in problem_desc,
    }


def _semantic_problem_text(problem_desc: str) -> str:
    text = problem_desc.lower()
    for marker in ["原函数签名", "实现要求", "测试示例"]:
        if marker.lower() in text:
            text = text.split(marker.lower(), 1)[0]
    if "函数说明：" in text:
        text = text.split("函数说明：", 1)[1]
    return text


def _signature_text(problem_desc: str) -> str:
    match = re.search(r"原函数签名（python）：(.*)", problem_desc.lower())
    return match.group(1) if match else ""


def _trivial_ensures(ensures: list[str]) -> list[str]:
    patterns = [
        r"ensures\s+true\b",
        r"ensures\s+result\s*==\s*result\b",
        r"ensures\s+0\s*<=\s*\|?result\|?$",
        r"ensures\s+\|result\|\s*>=\s*0\b",
        r"ensures\s+result\s*!=\s*null\b",
    ]
    return [clause for clause in ensures if any(re.search(p, clause) for p in patterns)]


def _mentioned_params(signature: dict[str, Any], spec: str) -> list[str]:
    ensures_text = "\n".join(_extract_clauses(spec)["ensures"])
    mentioned = []
    for param in signature.get("params", []):
        if re.search(rf"\b{re.escape(param['name'])}\b", ensures_text):
            mentioned.append(param["name"])
    return mentioned


def _semantic_signal_score(spec: str) -> int:
    signals = [
        "forall", "exists", "==>", "&&", "||", "|", "[", "]",
        "<=", ">=", "==", "!=", "<", ">", "old(", "Abs", "Sum",
    ]
    return sum(1 for signal in signals if signal in spec)


def _check_feature_obligations(spec: str, features: dict[str, bool]) -> dict[str, Any]:
    flags = []
    missing = []
    penalty = 0

    def absent_any(tokens: list[str]) -> bool:
        return not any(token in spec for token in tokens)

    if features["bool_result"] and absent_any(["result == true", "result == false", "result <==>", "exists", "forall", "==>"]):
        flags.append("bool_task_without_logical_condition")
        missing.append("Boolean tasks should connect result to a logical condition.")
        penalty += 12

    if features["sequence_task"] and absent_any(["|result|", "forall", "exists", "result[", " in "]):
        flags.append("sequence_task_without_element_or_length_condition")
        missing.append("Sequence/list tasks usually need length, element, membership, or ordering constraints.")
        penalty += 12

    if features["string_task"] and absent_any(["|result|", "result[", "substring", "+", "forall"]):
        flags.append("string_task_without_string_semantics")
        missing.append("String tasks usually need length, character, substring, or concatenation semantics.")
        penalty += 10

    if features["ordering"] and absent_any(["forall", "<=", ">=", "<", ">"]):
        flags.append("ordering_task_without_order_constraint")
        missing.append("Ordering/min/max tasks should include comparison or universal constraints.")
        penalty += 12

    if features["existential"] and "exists" not in spec and "result" in spec:
        flags.append("existential_task_without_exists")
        missing.append("Existential tasks often need an `exists` postcondition or equivalent boolean condition.")
        penalty += 8

    if features["universal"] and "forall" not in spec:
        flags.append("universal_task_without_forall")
        missing.append("Universal tasks often need a `forall` postcondition.")
        penalty += 8

    if features["threshold_or_distance"] and absent_any(["threshold", "Abs", "-", "<", "<=", ">"]):
        flags.append("threshold_task_without_distance_condition")
        missing.append("Threshold/distance tasks should constrain differences against the threshold.")
        penalty += 12

    if features["sum_or_prefix"] and absent_any(["Sum", "sum", "prefix", "+", "forall", "exists"]):
        flags.append("sum_task_without_accumulation_condition")
        missing.append("Sum/prefix tasks should expose accumulation semantics or a helper function.")
        penalty += 10

    return {"flags": flags, "missing": missing, "penalty": penalty}


def _score_level(score: int, flags: list[str]) -> str:
    if "no_postcondition" in flags or "missing_method_signature" in flags:
        return "inadequate"
    if score < 45:
        return "weak"
    if score < 70:
        return "partial"
    if score < 85:
        return "plausible"
    return "strong_static"


def _recommendations(flags: list[str], features: dict[str, bool]) -> list[str]:
    recs = []
    if "no_postcondition" in flags:
        recs.append("Add at least one semantic `ensures` clause.")
    if "postcondition_ignores_inputs" in flags:
        recs.append("Relate `result` to input parameters in postconditions.")
    if features["sequence_task"]:
        recs.append("For seq/list tasks, consider `|result|`, element preservation, membership, or ordering clauses.")
    if features["bool_result"]:
        recs.append("For bool tasks, specify both true and false cases when possible.")
    if features["threshold_or_distance"]:
        recs.append("For threshold tasks, express the distance predicate explicitly.")
    if "verified_but_behavior_failed" in flags:
        recs.append("Treat this as a spec adequacy warning: verified code did not satisfy behavioral tests.")
    return _dedupe(recs)


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
