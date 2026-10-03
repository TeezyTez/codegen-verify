"""Explicitly authorized live adapter; replay is always diagnostic, never research."""
import json
import time

SYSTEM = '''Generate implementations under externally frozen Dafny contracts.
Return JSON only. For full-source mode: {"action":"generate","source":"entire file"}.
For skeleton mode: {"action":"generate","bodies":{"methodName":"complete body"}}.
Other tools: {"action":"read"}, {"action":"verify"}, {"action":"stop"}.
Preserve the listed header tokens and method order (whitespace may vary). Implement every method. No
extra declarations, comments, strings, imports, attributes, assumptions, I/O,
allocation, or verification bypass. Loop invariants and assert are permitted.
The external task, formal contracts and runtime acceptance cannot be changed.
Tool feedback is available only as declared. No reference solution is available.'''


class Replay:
    kind = 'scripted_replay'
    def __init__(self, task, condition):
        self.task, self.condition, self.index = task, condition, 0
        # Same intentional illegal/incorrect/correct candidates across conditions.
        self.sequence = [{name:'  assume false;' for name in task.names},
                         task.meta['mutants'][0]['bodies'], task.meta['reference']]

    def identity(self):
        from repair.task import digest
        return {'kind':self.kind,'sequence_sha256':digest(json.dumps(self.sequence,sort_keys=True)),
                'uses_reference':True,'research_eligible':False}

    def generate(self, prompt, max_tokens, timeout):
        if self.index >= len(self.sequence):
            action = {'action':'stop'}
        else:
            bodies = self.sequence[self.index]
            if self.condition in {'G10','G11'}:
                action = {'action':'generate','bodies':bodies}
            else:
                # Deliberately bypass assemble's policy for the first negative
                # candidate, so the *runner* has to reject it.
                source = '\n\n'.join(m['header'].rstrip()+'\n{\n'+bodies[m['name']]+'\n}'
                                      for m in self.task.meta['methods'])+'\n'
                action = {'action':'generate','source':source}
        self.index += 1
        return {'text':json.dumps(action),'input_tokens':None,'output_tokens':None,
                'cost_usd':0.0,'usage_source':'not_applicable_replay'}


class Provider:
    kind = 'live_model'
    def __init__(self, input_price=None, output_price=None):
        from repair.verifier import config
        from llm_client import LLMClient
        self.client = LLMClient(config.CODE_PROVIDER,config.CODE_MODEL,role='fixed_spec_generation')
        self.input_price,self.output_price = input_price,output_price
        self.thinking = config.DEEPSEEK_THINKING
        self.reasoning_effort = config.DEEPSEEK_REASONING_EFFORT

    def identity(self):
        return {'kind':self.kind,'provider':self.client.provider,'model':self.client.model,
                'temperature':0.2,'thinking':self.thinking if self.client.provider=='deepseek' else None,
                'reasoning_effort':self.reasoning_effort if self.client.provider=='deepseek' else None,
                'prices_usd_per_million':{'input':self.input_price,'output':self.output_price}}

    def generate(self, prompt, max_tokens, timeout):
        started = time.monotonic()
        options = dict(model=self.client.model,messages=[{'role':'system','content':SYSTEM},
                       {'role':'user','content':prompt}],temperature=0.2,max_tokens=max_tokens)
        if self.client.provider == 'deepseek':
            options['extra_body'] = {'thinking':{'type':self.thinking}}
            if self.thinking == 'enabled':
                options['reasoning_effort'] = self.reasoning_effort
        response = self.client.client.with_options(timeout=timeout,max_retries=0).chat.completions.create(**options)
        usage = getattr(response,'usage',None)
        inp,out = getattr(usage,'prompt_tokens',None),getattr(usage,'completion_tokens',None)
        known = type(inp) is int and inp > 0 and type(out) is int and out >= 0
        cost = None
        if known and self.input_price is not None and self.output_price is not None:
            cost = (inp*self.input_price + out*self.output_price)/1e6
        return {'text':response.choices[0].message.content or '',
                'input_tokens':inp if known else None,'output_tokens':out if known else None,
                'cost_usd':cost,'usage_source':'provider_reported' if known else 'unknown',
                'seconds':time.monotonic()-started,'response_model':getattr(response,'model',None),
                'finish_reason':response.choices[0].finish_reason}
