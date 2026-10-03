"""Explicit configuration, no credentials in JSON and no model-specific guesses."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from . import REPRESENTATIONS, STRATEGIES


@dataclass(frozen=True)
class Budget:
    model_calls: int = 3
    verifier_calls: int = 4
    output_tokens: int = 2048
    total_tokens: int | None = 48000
    cost_usd: float | None = None
    verification_seconds: float = 15
    model_seconds: float = 60
    task_seconds: float = 120

    def __post_init__(self):
        for key in ('model_calls','verifier_calls','output_tokens'):
            if type(getattr(self,key)) is not int or getattr(self,key) <= 0:
                raise ValueError(f'{key} must be a positive integer')
        if self.total_tokens is not None and (type(self.total_tokens) is not int or self.total_tokens <= 0):
            raise ValueError('total_tokens must be null or a positive integer')
        for key in ('verification_seconds','model_seconds','task_seconds','cost_usd'):
            value = getattr(self,key)
            if value is None and key == 'cost_usd':
                continue
            if type(value) not in {int,float} or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')


DEFAULT_MODEL = {'kind':'mock','name':None,'base_url':None,'api_key_env':'OPENAI_API_KEY',
                 'sampling':{},'send_seed':False,'output_token_parameter':'max_completion_tokens',
                 'input_usd_per_million':None,'output_usd_per_million':None,'price_source':None}


def validate_config(config):
    allowed = {'version','strategies','representations','replicates','seed','budget','model'}
    if set(config) != allowed or config['version'] != 1:
        raise ValueError('invalid config schema')
    for key, values in (('strategies',STRATEGIES),('representations',REPRESENTATIONS)):
        items = config[key]
        if not isinstance(items,list) or not items or len(items) != len(set(items)) or not set(items) <= set(values):
            raise ValueError(f'invalid {key}')
    if type(config['replicates']) is not int or config['replicates'] <= 0 or type(config['seed']) is not int:
        raise ValueError('invalid replicates/seed')
    budget = Budget(**config['budget'])
    model = config['model']
    if (not set(DEFAULT_MODEL) <= set(model) or not set(model) <= set(DEFAULT_MODEL)|{'thinking'}
            or model['kind'] not in {'mock','openai','deepseek'}):
        raise ValueError('invalid model config')
    if model['kind'] != 'mock':
        if not isinstance(model['name'],str) or not model['name']:
            raise ValueError('live model name required')
        url = urlsplit(model['base_url'] or '')
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('endpoint must be HTTPS without embedded credentials/query')
        if not isinstance(model['api_key_env'],str) or not model['api_key_env'].isidentifier():
            raise ValueError('credential config must name an environment variable')
    if model['kind'] == 'deepseek':
        if model.get('thinking') not in {'enabled','disabled'}:
            raise ValueError('DeepSeek thinking mode must be explicit')
        if model['send_seed'] or model['output_token_parameter'] != 'max_tokens':
            raise ValueError('DeepSeek profile uses max_tokens and no unsupported seed parameter')
    elif 'thinking' in model:
        raise ValueError('thinking option belongs to the DeepSeek adapter')
    if type(model['send_seed']) is not bool or model['output_token_parameter'] not in {'max_tokens','max_completion_tokens'}:
        raise ValueError('invalid optional API parameters')
    sampling = model['sampling']
    if not isinstance(sampling,dict) or not set(sampling) <= {'temperature','top_p'}:
        raise ValueError('unsupported sampling parameters; omit unsupported model options')
    for key,value in sampling.items():
        if type(value) not in {int,float} or not math.isfinite(value) or not 0 <= value <= (2 if key == 'temperature' else 1):
            raise ValueError('invalid sampling value')
    prices = [model['input_usd_per_million'], model['output_usd_per_million']]
    if any(p is not None for p in prices):
        if any(type(p) not in {int,float} or not math.isfinite(p) or p < 0 for p in prices) or not model['price_source']:
            raise ValueError('both prices and their source are required')
    if budget.cost_usd is not None and model['kind'] != 'mock' and any(p is None for p in prices):
        raise ValueError('cost budget needs known prices; refusing unbounded cost accounting')
    return budget


def load_config(path):
    config = json.loads(Path(path).read_text())
    validate_config(config)
    return config


def default_config():
    return {'version':1,'strategies':['single_shot','iterative_repair'],
            'representations':list(REPRESENTATIONS),'replicates':1,'seed':17,
            'budget':asdict(Budget()),'model':dict(DEFAULT_MODEL)}
