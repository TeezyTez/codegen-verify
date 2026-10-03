"""Frozen hand-written rules for this *synthetic* profile, not a general compiler.

Does not read task.reference/mutants/tests. Covers all current rule IDs rather
than deliberately weakening the non-LLM baseline. Preparation effort is not free.
"""
import json


RESERVE = '  ok := used + req <= cap;\n  next := if ok then used + req else used;'
RELEASE = '  ok := req <= used;\n  next := if ok then used - req else used;'
RULES = {
    'remaining': {'Remaining':'  r := cap - used;'},
    'scale': {'Scale':'  r := units * rate;'},
    'snapshot': {'Snapshot':'  a := left; b := right;'},
    'clamp': {'Clamp':'  grant := if req <= cap then req else cap;'},
    'reserve': {'Reserve':RESERVE},
    'release': {'Release':RELEASE},
    'partial': {'Partial':'  grant := if req <= cap - used then req else cap - used;\n  next := used + grant;'},
    'transfer': {'Transfer':'  ok := req <= a && b + req <= cap;\n  na := if ok then a - req else a;\n  nb := if ok then b + req else b;'},
    'refill': {'Refill':'  next := if used + steps <= cap then used + steps else cap;'},
    'reserve_twice': {'Reserve':RESERVE,
        'ReserveTwice':'  ok1 := used + q1 <= cap;\n  var mid := if ok1 then used + q1 else used;\n  ok2 := mid + q2 <= cap;\n  next := if ok2 then mid + q2 else mid;'},
    'release_twice': {'Release':RELEASE,
        'ReleaseTwice':'  ok1 := q1 <= used;\n  var mid := if ok1 then used - q1 else used;\n  ok2 := q2 <= mid;\n  next := if ok2 then mid - q2 else mid;'},
    'reserve_release': {'Reserve':RESERVE,'Release':RELEASE,'ReserveRelease':'  next := used;'},
}


class Template:
    kind = 'deterministic_template'
    def __init__(self, task):
        self.task = task

    def identity(self):
        return {'kind':self.kind,'version':1,'supported_rules':sorted(RULES),
                'uses_reference':False,'preparation_minutes':None,
                'scope':'hand-authored rules for synthetic diagnostic profile, no external generality claim'}

    def generate(self, prompt, max_tokens, timeout):
        rule = self.task.meta['rule']
        if rule.get('version') != 1 or rule.get('name') not in RULES:
            action = {'action':'unsupported'}
        else:
            action = {'action':'generate','source':self.task.assemble(RULES[rule['name']])}
        return {'text':json.dumps(action),'input_tokens':0,'output_tokens':0,'cost_usd':0,
                'usage_source':'not_applicable_template'}
