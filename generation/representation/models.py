"""One explicit SDK adapter and deterministic offline fixtures; neither owns a session."""
import copy
import importlib.metadata
import json
import os
import math
from email.utils import parsedate_to_datetime
import time

from .task import canonical
from repair.task import digest

SYSTEM = '''Implement the supplied requirements in Dafny 4.11. Return exactly one JSON
object: {"bodies":{"MethodName":"complete implementation body"}}.
Return only the bodies of all supplied method signatures, never declarations or
contracts. The trusted framework assembles and verifies the fixed acceptance file.
Allowed: initialized local variables, assignments, if/else with explicit blocks,
while with an explicit body, loop invariants/decreases, assert, return, integer and
boolean expressions and sequence indexing/length, forall/exists in expressions.
No comments, strings, attributes, imports, I/O, allocation, declarations, assume,
axioms, havoc, body-less loops or verification bypass. No host commands or tools.
Do not add requirements. No reference solution is supplied in these messages.'''


def retry_delay(exc):
    """Only a numeric/date delay crosses the error boundary, never raw headers."""
    response = getattr(exc,'response',None)
    value = response.headers.get('retry-after') if response is not None else None
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError,ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp()-time.time()
        except (TypeError,ValueError,OverflowError):
            return None
    return max(0.0,seconds) if math.isfinite(seconds) else None


class Mock:
    kind = 'mock'

    def __init__(self, task):
        # This test fixture, not a research model, deliberately has answers.
        self.sequence = copy.deepcopy([task.meta['mutants'][0]['bodies'],task.meta['reference']])
        self.index = 0

    def identity(self):
        return {'kind':'mock','name':'wrong_then_reference_v1','uses_reference':True,
                'sequence_sha256':digest(canonical(self.sequence)),'sampling':{},'seed_supported':False,
                'price_source':'offline fixture; no API call','research_eligible':False}

    def generate(self, messages, max_tokens, timeout, seed):
        bodies = self.sequence[min(self.index,len(self.sequence)-1)]
        self.index += 1
        return {'text':json.dumps({'bodies':bodies}),'input_tokens':None,'output_tokens':None,
                'cost_usd':0.0,'error':None,'usage_source':'not_applicable_mock',
                'request_parameters':{'max_output_tokens':max_tokens,'seed_sent':None}}


class OpenAIModel:
    kind = 'live'

    def __init__(self, config, *, authorized=False, client=None):
        if not authorized:
            raise ValueError('real API calls require explicit --allow-paid')
        self.config = copy.deepcopy(config)
        if client is None:
            from openai import OpenAI
            env_name = config['api_key_env']
            if env_name not in os.environ:
                raise ValueError('configured credential environment variable is absent')
            # The credential is read by SDK on an authorized request, never
            # inspected, printed, put in config manifests, or passed to Dafny.
            client = OpenAI(api_key=lambda:os.environ[env_name],base_url=config['base_url'],max_retries=0)
        self.client = client

    def identity(self):
        return {'kind':'live','provider':self.config['kind'],'name':self.config['name'],
                'base_url':self.config['base_url'],'sdk_version':importlib.metadata.version('openai'),
                'sampling_requested':self.config['sampling'],
                'seed_requested':self.config['send_seed'],
                'parameter_support':'only confirmed by successful API response; unsupported options are not silently dropped',
                'output_token_parameter':self.config['output_token_parameter'],
                'prices_usd_per_million':{k:self.config[k+'_usd_per_million'] for k in ('input','output')},
                'price_source':self.config['price_source'],'sdk_max_retries':0}

    def generate(self, messages, max_tokens, timeout, seed):
        params = {'model':self.config['name'],'messages':messages,
                  self.config['output_token_parameter']:max_tokens,**self.config['sampling']}
        if self.config['kind'] == 'deepseek':
            params['extra_body'] = {'thinking':{'type':self.config['thinking']}}
        else:
            params['store'] = False
        if self.config['send_seed']:
            params['seed'] = seed
        request = {k:v for k,v in params.items() if k != 'messages'}
        try:
            response = self.client.with_options(timeout=timeout,max_retries=0).chat.completions.create(**params)
        except Exception as exc:
            import openai
            category = ('rate_limit' if isinstance(exc,openai.RateLimitError) else
                        'timeout' if isinstance(exc,openai.APITimeoutError) else
                        'authentication' if isinstance(exc,openai.AuthenticationError) else
                        'permission' if isinstance(exc,openai.PermissionDeniedError) else
                        'invalid_request' if isinstance(exc,(openai.BadRequestError,openai.NotFoundError)) else
                        'server_error' if isinstance(exc,openai.InternalServerError) else
                        'connection' if isinstance(exc,openai.APIConnectionError) else 'provider_error')
            # Do not serialize exception text: it may include headers/URLs.
            return {'text':'','error':category,'error_type':type(exc).__name__,
                    'input_tokens':None,'output_tokens':None,'cost_usd':None,
                    'retryable':category in {'rate_limit','timeout','connection','server_error'},
                    'retry_after_seconds':retry_delay(exc),
                    'request_parameters':request,'usage_source':'unknown'}
        usage = getattr(response,'usage',None)
        inp,out = getattr(usage,'prompt_tokens',None),getattr(usage,'completion_tokens',None)
        known = type(inp) is int and type(out) is int and inp >= 0 and out >= 0
        prices = self.config['input_usd_per_million'],self.config['output_usd_per_million']
        cost = (inp*prices[0]+out*prices[1])/1e6 if known and all(x is not None for x in prices) else None
        choices = getattr(response,'choices',[])
        text = (getattr(choices[0].message,'content',None) if choices else None) or ''
        finish_reason = getattr(choices[0],'finish_reason',None) if choices else None
        error = ('output_truncated' if finish_reason == 'length' else
                 'model_refusal' if finish_reason == 'content_filter' else
                 None if text.strip() else 'empty_output')
        return {'text':text,'error':error,'retryable':error in {'output_truncated','empty_output'},
                'input_tokens':inp if known else None,'output_tokens':out if known else None,
                'cost_usd':cost,'usage_source':'provider_reported' if known else 'unknown',
                'request_parameters':request,'parameters_accepted':True,
                'response_model':getattr(response,'model',None),
                'prompt_cache_hit_tokens':getattr(usage,'prompt_cache_hit_tokens',None),
                'prompt_cache_miss_tokens':getattr(usage,'prompt_cache_miss_tokens',None),
                'cost_basis':'configured per-token price estimate, not provider billing receipt',
                'system_fingerprint':getattr(response,'system_fingerprint',None),
                'finish_reason':finish_reason}
