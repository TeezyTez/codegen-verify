"""Same budget/provider rules; separate experimental condition space."""
import copy
import json
from pathlib import Path

from generation.representation.config import default_config as legacy_default, validate_config as validate
from . import REPRESENTATIONS, STRATEGIES


def default_config():
    config = copy.deepcopy(legacy_default())
    config.update(strategies=list(STRATEGIES), representations=list(REPRESENTATIONS))
    config['budget'].update(model_calls=4, verifier_calls=5, output_tokens=4096, task_seconds=180)
    return config


def validate_config(config):
    return validate(config, strategies=STRATEGIES, representations=REPRESENTATIONS)


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    validate_config(config)
    return config
