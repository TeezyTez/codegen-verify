"""No-request readiness checks and exact first-message preview for a selected run."""
import os

from repair.task import digest
from .config import validate_config
from .runner import messages_for
from .task import canonical


def inspect_run(task, config, verifier, *, strategy, representation, replicate=0):
    budget = validate_config(config)
    if strategy not in config['strategies'] or representation not in config['representations']:
        raise ValueError('selected condition is absent from config')
    if not 0 <= replicate < config['replicates']:
        raise ValueError('replicate is absent from config')
    task.check_frozen()
    model = config['model']
    live = model['kind'] != 'mock'
    identity = verifier.identity()
    blockers, warnings = [], []
    if not identity.get('version','').startswith('4.11.'):
        blockers.append('Dafny 4.11 is not available or could not be detected')
    if live and (model['name'].upper().startswith(('SET_','YOUR_')) or model['name'].startswith('<')):
        blockers.append('replace the placeholder with your authorized model identifier')
    # Presence only, never read or serialize the credential value.
    credential_present = model['api_key_env'] in os.environ if live else None
    if live and not credential_present:
        blockers.append('configured credential environment variable is absent')
    if live and budget.cost_usd is None:
        warnings.append('no configured monetary ceiling; token/call/time ceilings still apply')
    if model['input_usd_per_million'] is None:
        warnings.append('pricing unknown; no dollar estimate is available')
    if task.meta['equivalence_audit']['status'] == 'pending':
        warnings.append('representation equivalence is pending; engineering smoke only')
    messages = messages_for(task,representation,strategy)
    reserve = len(canonical(messages).encode())+256+budget.output_tokens
    if budget.total_tokens is not None and reserve > budget.total_tokens:
        blockers.append('token budget cannot accommodate even the first request reservation')
    checks = 1 if strategy == 'single_shot' else 2
    if budget.verifier_calls < checks:
        blockers.append('verification budget cannot accommodate candidate and final acceptance')
    if budget.cost_usd is not None and live:
        first_cost = ((reserve-budget.output_tokens)*model['input_usd_per_million']+
                      budget.output_tokens*model['output_usd_per_million'])/1e6
        if first_cost > budget.cost_usd:
            blockers.append('cost ceiling cannot accommodate the first request reservation')
    calls = 1 if strategy == 'single_shot' else budget.model_calls
    return {'check':'single_run_preflight_v1','api_called':False,'task_id':task.meta['id'],
            'strategy':strategy,'representation':representation,'replicate':replicate,
            'model_kind':model['kind'],'model':model['name'],'endpoint':model['base_url'],
            'credential_env':model['api_key_env'] if live else None,'credential_present':credential_present,
            'ready_for_authorized_attempt':not blockers,'online_compatibility':'not_checked',
            'blockers':blockers,'warnings':warnings,'toolchain':identity,
            'budget':{'model_calls_max':calls,'verification_calls_max':budget.verifier_calls,
                      'output_tokens_per_call_max':budget.output_tokens,'accounted_token_ceiling':budget.total_tokens,
                      'task_seconds':budget.task_seconds,'cost_usd_ceiling':budget.cost_usd,
                      'price_source':model['price_source'],
                      'note':'Engineering reservations are not a guaranteed provider billing bound; admission is separate.'},
            'initial_messages':messages,'initial_messages_sha256':digest(canonical(messages)),
            'task_sha256':task.file_hash,'config_sha256':digest(canonical(config))}
