"""One controlled loop for baselines, dependency scheduling and ablations."""
from dataclasses import asdict, dataclass
from difflib import unified_diff
import json
from pathlib import Path
import time

from .dependencies import build_graph, regressions, schedule
from .models import SYSTEM
from .task import BoundaryError, digest


CONDITIONS = ("independent", "linear", "generic_agent", "dependency", "no_dependencies", "no_schedule")


@dataclass(frozen=True)
class Limits:
    model_calls: int = 6
    verifier_calls: int = 10
    total_tokens: int = 48000
    output_tokens: int = 2048
    seconds: int = 180

    def __post_init__(self):
        if any(v <= 0 for v in asdict(self).values()):
            raise ValueError("all limits must be positive")


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def run(task, model, verifier, output, *, condition="dependency", limits=None, replicate=0):
    if condition not in CONDITIONS:
        raise ValueError("unknown condition")
    limits = limits or Limits()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    usage = {"model_calls": 0, "verifier_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "accounted_tokens": 0, "unknown_usage_calls": 0, "cost_usd": 0.0}
    report = {"protocol": "fixed_contract_repair_v1", "task_id": task.meta["id"],
              "source_project": task.meta["source_project"], "split": task.meta["split"],
              "mode": task.meta["mode"], "failure_type": task.meta["failure_type"],
              "origin": task.meta["origin"], "condition": condition, "replicate": replicate,
              "model_kind": model.kind, "research_eligible": model.kind == "live_model",
              "success": False, "stop_reason": "not_started", "usage": usage,
              "regressions": 0, "lost_observability": 0, "boundary_rejections": 0}
    current = task.render(task.regions(task.original))
    original = current
    (output / "initial.dfy").write_text(original)
    manifest = {"protocol": report["protocol"], "task": task.meta,
                "template_sha256": digest(original), "limits": asdict(limits),
                "task_manifest_sha256": digest(task.path.read_text()),
                "replay_actions_sha256": digest(json.dumps(model.actions, sort_keys=True)) if hasattr(model, 'actions') else None,
                "condition": condition, "model_kind": model.kind, "replicate": replicate,
                "verifier_version": verifier.version(),
                "runtime": verifier.identity() if hasattr(verifier, 'identity') else {"kind": "test_double"},
                "model": getattr(getattr(model, "client", None), "model", "scripted"),
                "provider": getattr(getattr(model, "client", None), "provider", "none"),
                "system_prompt": SYSTEM,
                "temperature": 0.2 if model.kind == 'live_model' else None,
                "source_hashes": {str(p.relative_to(Path(__file__).parent)): digest(p.read_text())
                                  for p in sorted(Path(__file__).parent.glob('*.py'))},
                "legacy_adapter_hashes": {name: digest((Path(__file__).parents[1] / 'project' / name).read_text())
                                          for name in ('config.py', 'dafny_wrapper.py', 'llm_client.py')},
                "token_policy": "reserve UTF-8 prompt bytes + 256 overhead + output cap; use provider usage when known",
                "graph_policy": "lexical conservative references, no certified logical dependencies"}
    write_json(output / "manifest.json", manifest)
    history = []
    seen = {digest(original)}
    result = None

    def event(data):
        data = {"elapsed": round(time.monotonic() - started, 6), **data}
        with (output / "events.jsonl").open('a') as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + '\n')

    def remaining():
        return limits.seconds - (time.monotonic() - started)

    def verify(source, phase):
        if usage["verifier_calls"] >= limits.verifier_calls or remaining() <= 0:
            raise RuntimeError("verification_budget_exhausted")
        usage["verifier_calls"] += 1
        value = verifier.verify(source, timeout=remaining())
        event({"stage": phase, "source_sha256": digest(source), "result": value.to_dict()})
        return value

    try:
        result = verify(current, "initial_verification")
        report["initial"] = result.to_dict()
        if result.status == "passed":
            report["stop_reason"] = "invalid_task_initially_passed"
            return report
        if result.status in {"timeout", "tool_error", "unknown"}:
            report["stop_reason"] = "invalid_initial_evidence"
            return report
        initial_result = result
        report["stop_reason"] = "model_budget_exhausted"
        while usage["model_calls"] < limits.model_calls and remaining() > 0:
            if usage["verifier_calls"] >= limits.verifier_calls - 1:
                report["stop_reason"] = "reserved_final_verification_budget"
                break
            base = original if condition == "independent" else current
            feedback = initial_result if condition == "independent" else result
            graph = build_graph(base, feedback.diagnostics)
            prompt = {"task": task.public(), "source": base,
                      "tools": ["read", "patch", "verify", "stop"],
                      "budget_remaining": {"seconds": remaining(),
                          "model_calls": limits.model_calls - usage["model_calls"],
                          "verifier_calls": limits.verifier_calls - usage["verifier_calls"]}}
            if condition != "independent":
                prompt.update(verifier=feedback.to_dict(), recent_actions=history[-3:])
            if condition in {"dependency", "no_schedule"}:
                prompt["dependencies"] = graph
            if condition in {"dependency", "no_dependencies"}:
                prompt["suggested_repair"] = schedule(task, graph, feedback.obligations,
                                                      use_dependencies=condition == "dependency")
            if condition == "generic_agent":
                prompt["strategy"] = "Plan your own inspection, edits and verification using the available tools."
            else:
                prompt["strategy"] = "Propose the next repair candidate."
            text = json.dumps(prompt, ensure_ascii=False)
            reservation = len((SYSTEM + text).encode()) + 256 + limits.output_tokens
            if usage["accounted_tokens"] + reservation > limits.total_tokens:
                report["stop_reason"] = "token_budget_exhausted"
                break
            usage["model_calls"] += 1
            step = usage["model_calls"]
            write_json(output / f"prompt_{step:03d}.json", prompt)
            try:
                response = model.generate(text, limits.output_tokens, remaining())
            except Exception as exc:
                usage["accounted_tokens"] += reservation
                usage["unknown_usage_calls"] += 1
                usage["cost_usd"] = None
                history.append({"action": "provider_error", "error_type": type(exc).__name__})
                event({"stage": "model_error", "step": step, "error_type": type(exc).__name__})
                continue
            write_json(output / f"response_{step:03d}.json", response)
            measured = response["input_tokens"] is not None and response["output_tokens"] is not None
            if measured:
                usage["input_tokens"] += response["input_tokens"]
                usage["output_tokens"] += response["output_tokens"]
                usage["accounted_tokens"] += response["input_tokens"] + response["output_tokens"]
            else:
                usage["unknown_usage_calls"] += 1
                usage["accounted_tokens"] += reservation
            cost = response.get("cost_usd")
            usage["cost_usd"] = None if cost is None or usage["cost_usd"] is None else usage["cost_usd"] + cost
            if usage["accounted_tokens"] > limits.total_tokens or remaining() <= 0:
                report["stop_reason"] = "budget_exhausted_after_call"
                break
            try:
                action = json.loads(response["text"])
                if not isinstance(action, dict):
                    raise ValueError("expected action object")
                kind = action.get("action")
                if kind == "stop":
                    report["stop_reason"] = "model_stopped"
                    break
                if kind == "read":
                    node = graph["nodes"].get(action.get("symbol"))
                    history.append({"action": "read", "symbol": action.get("symbol"), "content": node})
                    event({"stage": "read", "step": step, "symbol": action.get("symbol")})
                    continue
                if kind == "verify":
                    # Tools have identical availability in every condition.
                    result = verify(base, "requested_verification")
                    history.append({"action": "verify", "status": result.status})
                    continue
                if kind != "patch":
                    raise ValueError("unknown tool action")
                candidate = task.apply(base, action.get("replacements"))
                task.check_final(candidate)
            except (BoundaryError, ValueError, TypeError) as exc:
                report["boundary_rejections"] += 1
                history.append({"action": "rejected", "reason": str(exc)})
                event({"stage": "patch_rejected", "step": step, "reason": str(exc)})
                continue
            fingerprint = digest(candidate)
            if fingerprint in seen:
                history.append({"action": "duplicate", "source_sha256": fingerprint})
                event({"stage": "duplicate", "step": step})
                continue
            seen.add(fingerprint)
            (output / f"candidate_{step:03d}.dfy").write_text(candidate)
            candidate_result = verify(candidate, "candidate_verification")
            delta = regressions(feedback.obligations, candidate_result.obligations)
            report["regressions"] += len(delta["confirmed"])
            report["lost_observability"] += len(delta["lost_observability"])
            record = {"action": "patch", "step": step, "regions": list(action["replacements"]),
                      "status": candidate_result.status, "regression": delta,
                      "diagnostics": candidate_result.diagnostics}
            history.append(record)
            event({"stage": "candidate_decision", **record})
            if candidate_result.status == "passed":
                # Re-read persisted final artifact; never accept a cached log.
                final_path = output / "final.dfy"
                final_path.write_text(candidate)
                final_source = final_path.read_text()
                task.check_final(final_source)
                final = verify(final_source, "final_reverification")
                report["final"] = final.to_dict()
                report["final_sha256"] = digest(final_source)
                report["success"] = (final.status == "passed" and remaining() > 0
                    and set(initial_result.obligations) <= set(final.obligations))
                report["stop_reason"] = "accepted" if report["success"] else "final_reverification_failed"
                current = candidate
                break
            # Same rollback rule for every condition, including ablations.
            if candidate_result.status == "verification_failed" and not delta["confirmed"] and not delta["lost_observability"]:
                current, result = candidate, candidate_result
        if remaining() <= 0:
            report["stop_reason"] = "wall_budget_exhausted"
    except (RuntimeError, BoundaryError) as exc:
        report["stop_reason"] = str(exc)
    finally:
        report["seconds"] = time.monotonic() - started
        changes = list(unified_diff(original.splitlines(), current.splitlines()))
        report["changed_lines"] = sum(x.startswith(('+', '-')) and not x.startswith(('+++', '---')) for x in changes)
        (output / "final.diff").write_text('\n'.join(changes) + '\n')
        write_json(output / "result.json", report)
    return report
