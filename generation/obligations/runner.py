"""New protocol on the same executor used by representation experiments."""
from pathlib import Path

from generation.engine import run as execute
from generation.representation.runner import source_hashes as shared_hashes
from repair.task import digest
from .policy import Policy


def source_hashes():
    root = Path(__file__).resolve().parents[2]
    return {**shared_hashes(), **{str(p.relative_to(root)): digest(p.read_text(encoding='utf-8'))
                                 for p in sorted(Path(__file__).parent.glob('*.py'))}}


def run(task, model, verifier, output, *, config, strategy='guided', representation='contract',
        replicate=0, progress=None):
    policy = Policy(task, verifier.identity())
    return execute(task, model, verifier, output, config=config, strategy=strategy,
                   representation=representation, replicate=replicate, progress=progress, policy=policy)
