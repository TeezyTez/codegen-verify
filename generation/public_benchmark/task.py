"""Public BAF record views with externally assembled, immutable spec fields."""
from copy import deepcopy
import hashlib
import json
import re


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class PublicTask:
    def __init__(self, record, *, family_id):
        self.record = deepcopy(record)
        self.id = record['id']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_\-]{0,100}',self.id):
            raise ValueError('unsafe task ID')
        self.family_id = family_id
        self.record_sha256 = digest(canonical(record))
        self.fields = {k:record[k] for k in ['vc-preamble','vc-helpers','vc-spec','vc-postamble']}
        if any(not isinstance(v,str) for v in self.fields.values()): raise ValueError('invalid frozen field')
        self.spec_sha256 = digest(canonical(self.fields))
        # This identifies the intended editable header only. Actual boundaries,
        # symbol resolution and candidate acceptance use the compiler AST.
        names = re.findall(r'\b(?:method|function|predicate|lemma)\s+([A-Za-z_][A-Za-z0-9_\']*)\s*\(',record['vc-spec'])
        if len(names) != 1: raise ValueError('public_v1 requires one explicit target declaration')
        self.target_name = names[0]
        self.skeleton = self.assemble({'implementation':'{}','helpers':''})

    def assemble(self, candidate):
        if not isinstance(candidate,dict) or set(candidate) != {'implementation','helpers'}:
            raise ValueError('exact implementation/helpers object required')
        if any(not isinstance(v,str) for v in candidate.values()): raise ValueError('regions must be strings')
        if not candidate['implementation'].strip(): raise ValueError('implementation body required')
        return '\n\n'.join([self.fields['vc-preamble'],self.fields['vc-helpers'],
            candidate['helpers'],self.fields['vc-spec']+'\n'+candidate['implementation'],
            self.fields['vc-postamble']])+'\n'

    def public(self):
        return {'id':self.id,'description':self.record['vc-description'],
            'frozen_source':self.skeleton,'editable_regions':['implementation','helpers']}

    def manifest(self):
        return {'id':self.id,'family_id':self.family_id,'source':self.record['source'],
            'source_id':self.record['source-id'],'record_sha256':self.record_sha256,
            'spec_sha256':self.spec_sha256,'target_name':self.target_name,
            'skeleton_sha256':digest(self.skeleton)}
