"""Trusted task templates and a deliberately restricted edit language."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class BoundaryError(ValueError):
    pass


MARKER = re.compile(r"^// repair-begin (\w+)\n(.*?)^// repair-end \1$", re.M | re.S)
BYPASS = re.compile(r"\b(?:assume|admit|sorry|axiom|extern|include|import|module|trait|class|datatype|newtype|method|function|predicate|lemma|requires|ensures|modifies|reads|expect|yield)\b|\{\s*:|\bdecreases\s*\*|:=\s*\*|:\|", re.S)


def validate_region(text: str, kind: str) -> None:
    if len(text) > 16000 or not text.isascii():
        raise BoundaryError("region too large or outside ASCII source subset")
    if any(x in text for x in ('//', '/*', '*/', '"', "'", '`', '#', '\\')):
        raise BoundaryError("comments, directives and string/character literals are excluded")
    if BYPASS.search(text):
        raise BoundaryError("target contract/declaration change or proof bypass")
    if kind in {"invariants", "assertions"}:
        prefix = "invariant " if kind == "invariants" else "assert "
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith(prefix):
                raise BoundaryError(f"{kind} region accepts only {prefix.strip()}")
            expr = line[len(prefix):]
            if kind == "assertions":
                if not expr.endswith(';'):
                    raise BoundaryError("assertion must end with semicolon")
                expr = expr[:-1]
            if not expr.strip() or any(x in expr for x in (';', '{', '}', ':=')):
                raise BoundaryError("proof region cannot contain executable statements/blocks")
    elif kind == "implementation":
        depth = 0
        for char in text:
            depth += (char == '{') - (char == '}')
            if depth < 0:
                raise BoundaryError("region escapes its enclosing body")
        if depth:
            raise BoundaryError("unbalanced region")
    else:
        raise BoundaryError(f"unsupported edit region kind: {kind}")


@dataclass
class Task:
    path: Path
    meta: dict
    original: str

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        meta = json.loads(path.read_text())
        required = {"id", "mode", "source_project", "split", "failure_type", "origin", "regions"}
        if not required <= meta.keys() or meta["mode"] not in {"proof", "implementation"}:
            raise ValueError("invalid task manifest")
        if meta["split"] not in {"dev", "test"}:
            raise ValueError("invalid source split")
        original = (path.parent / "program.dfy").read_text()
        trusted = re.sub(r"//[^\n]*", "", original)
        if meta.get("trusted_assumptions") != [] or re.search(
            r"\b(?:assume|admit|sorry|axiom|extern|include|import)\b|\{\s*:|\bdecreases\s*\*", trusted
        ):
            raise BoundaryError("v1 task profile allows no extra axioms, imports or verification attributes")
        matches = list(MARKER.finditer(original))
        ids = [m[1] for m in matches]
        if len(ids) != len(set(ids)) or set(ids) != set(meta["regions"]):
            raise BoundaryError("regions must exactly match unique template markers")
        if original.count('// repair-begin ') != len(matches):
            raise BoundaryError("malformed/nested region markers")
        if meta["mode"] == "proof" and any(r["kind"] == "implementation" for r in meta["regions"].values()):
            raise BoundaryError("proof repair cannot edit implementation")
        task = cls(path, meta, original)
        task.render(task.regions(original))
        from .dependencies import build_graph
        nodes = build_graph(original)["nodes"]
        if any(r.get("owner") not in nodes for r in meta["regions"].values()):
            raise BoundaryError("region owner is not a recognized top-level callable")
        return task

    def regions(self, source):
        return {m[1]: m[2] for m in MARKER.finditer(source)}

    def render(self, replacements):
        if set(replacements) != set(self.meta["regions"]):
            raise BoundaryError("region set differs from trusted manifest")
        for name, text in replacements.items():
            if not isinstance(text, str):
                raise BoundaryError("replacement must be text")
            validate_region(text, self.meta["regions"][name]["kind"])
        def replace(match):
            text = replacements[match[1]]
            return f"// repair-begin {match[1]}\n{text.rstrip()}\n// repair-end {match[1]}"
        return MARKER.sub(replace, self.original)

    def apply(self, current, patch):
        if not isinstance(patch, dict) or not patch or not set(patch) <= set(self.meta["regions"]):
            raise BoundaryError("patch must map permitted region IDs to replacement text")
        # Reconstruct exclusively from the immutable original scaffold.
        return self.render({**self.regions(current), **patch})

    def check_final(self, candidate):
        if candidate != self.render(self.regions(candidate)):
            raise BoundaryError("final artifact changed immutable bytes")

    def public(self):
        return {k: self.meta[k] for k in ("id", "mode", "regions")}


def validate_splits(tasks):
    projects, fingerprints = {}, {}
    for task in tasks:
        split = task.meta["split"]
        project = task.meta["source_project"]
        if project in projects and projects[project] != split:
            raise ValueError(f"source project crosses splits: {project}")
        projects[project] = split
        # Identifier-normalized template catches renamed clones. This is only
        # a conservative first filter, not a complete semantic duplicate test.
        normalized = re.sub(r"\b[A-Za-z_]\w*\b", "ID", re.sub(r"//[^\n]*", "", task.original))
        fingerprint = digest(re.sub(r"\s+", "", normalized))
        if fingerprint in fingerprints and fingerprints[fingerprint] != split:
            raise ValueError("near-identical templates cross splits")
        fingerprints[fingerprint] = split
