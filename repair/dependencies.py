"""Lexical references, not a complete logical proof-dependency graph."""
import re


DECL = re.compile(r"^[ \t]*(?:opaque[ \t]+)?(method|function|lemma|predicate)[ \t]+(\w+)[ \t]*\(", re.M)


def build_graph(source, diagnostics=()):
    clean = re.sub(r"//[^\n]*", "", source)
    declarations = list(DECL.finditer(clean))
    nodes = {}
    for index, match in enumerate(declarations):
        if match[2] in nodes:
            raise ValueError('duplicate callable name outside v1 graph profile')
        end = declarations[index + 1].start() if index + 1 < len(declarations) else len(clean)
        nodes[match[2]] = {
            "kind": match[1], "start_line": clean.count('\n', 0, match.start()) + 1,
            "end_line": clean.count('\n', 0, end) + 1,
            "source": clean[match.start():end],
        }
    edges = []
    for name, node in nodes.items():
        # Exclude the declaration name, not its whole line: a one-line body
        # may contain real calls (including real recursion).
        for line in node["source"].split('(', 1)[1].splitlines():
            for callee in re.findall(r"\b(\w+)\s*\(", line):
                if callee not in nodes:
                    continue
                contract = line.strip().startswith(("requires", "ensures", "reads", "decreases"))
                kind = "contract_reference" if contract else (
                    "proof_helper_reference" if nodes[callee]["kind"] == "lemma" else "syntactic_call"
                )
                edge = {"from": name, "to": callee, "kind": kind,
                        "evidence": "conservative_lexical_approximation"}
                if edge not in edges:
                    edges.append(edge)
    failures = []
    for error in diagnostics:
        line = error.get("location_line", 0)
        owners = [name for name, n in nodes.items() if n["start_line"] <= line < n["end_line"]]
        failures.append({"line": line, "owners": owners, "type": error.get("subtype", "unknown")})
    return {"nodes": nodes, "edges": edges, "reported_failures": failures,
            "granularity": "callable verification batches", "confirmed_logical_edges": [],
            "limitations": "Top-level, unique unqualified names only; no alias/dynamic dispatch/SMT cores."}


def failed_owners(obligations):
    return {key.split(" (")[0] for key, status in obligations.items() if status != "passed"}


def schedule(task, graph, obligations, *, use_dependencies=True):
    failed = failed_owners(obligations)
    choices = []
    for name, region in task.meta["regions"].items():
        owner = region["owner"]
        outgoing = sum(e["from"] == owner and e["to"] in failed for e in graph["edges"])
        incoming = sum(e["to"] == owner for e in graph["edges"])
        priority = (owner not in failed, outgoing if use_dependencies else 0,
                    -incoming if use_dependencies else 0, name)
        choices.append((priority, name))
    choices.sort()
    return {"region": choices[0][1], "action": task.meta["regions"][choices[0][1]]["kind"],
            "ranking": [name for _, name in choices],
            "rule": "failed-first; unresolved referenced callees first; fan-in tie-break" if use_dependencies else "failed-first; stable ID tie-break"}


def regressions(before, after):
    return {
        "confirmed": sorted(k for k, s in before.items() if s == "passed" and after.get(k) == "failed"),
        "lost_observability": sorted(k for k, s in before.items() if s == "passed" and after.get(k) not in {"passed", "failed"}),
        "new_failures": sorted(k for k, s in after.items() if s == "failed" and before.get(k) != "failed"),
    }
