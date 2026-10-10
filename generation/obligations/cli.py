"""Public-contract obligation experiments; mock by default, live requires --allow-paid."""
from pathlib import Path
import sys

from generation.representation import cli as shared
from generation.representation.preflight import inspect_run as inspect_shared
from . import PROTOCOL, REPRESENTATIONS, STRATEGIES
from .analyze import write_summary
from .config import load_config, validate_config
from .policy import Policy
from .runner import run, source_hashes

TASKS = Path(__file__).resolve().parents[1]/'representation'/'tasks'
CONFIG = Path(__file__).resolve().parent/'configs'/'demo.json'
DEFAULT_STRATEGY = 'guided'
DEFAULT_REPRESENTATION = 'contract'


def inspect_run(task, config, verifier, **kwargs):
    report = inspect_shared(task, config, verifier, **kwargs, config_validator=validate_config,
                            messages_factory=Policy(task, verifier.identity()).messages)
    report['protocol'] = PROTOCOL
    return report


def admit(tasks, verifier, output):
    return shared.admit(tasks, verifier, output, protocol=PROTOCOL, hashes=source_hashes)


def main(argv=None):
    return shared.main(argv, profile=sys.modules[__name__])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f'Configuration/artifact error ({type(exc).__name__}): check inputs and output paths.', file=sys.stderr)
        raise SystemExit(2)
