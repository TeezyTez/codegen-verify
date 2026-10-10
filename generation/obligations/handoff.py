"""Verified file delivery and raw session collection for exploratory solvers.

One allowed loader tool call replaces manual prompt transcription. This is not
an OS isolation boundary; session auditing must reject additional tool calls.
"""
import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from generation.representation.task import canonical
from repair.task import digest
from .exploration import QueueModel, atomic_json

PROTOCOL = 'verified_file_repair_exploratory_v2'
ROOT = Path(__file__).resolve().parents[2]


def dispatch(messages):
    if len(messages)!=2 or [m['role'] for m in messages]!=['system','user']:
        raise ValueError('expected system and user messages')
    return 'SYSTEM:\n'+messages[0]['content']+'\nUSER:\n'+messages[1]['content']


def load_request(path, request_id, expected_hash):
    path=Path(path)
    raw=path.read_bytes()
    request=json.loads(raw.decode('utf-8'))
    if (request['request_id']!=request_id or request['dispatch_sha256']!=expected_hash
        or digest(request['dispatch'])!=expected_hash
        or digest(canonical(request['messages']))!=request['messages_sha256']
        or dispatch(request['messages'])!=request['dispatch']):
        raise ValueError('request identity/content mismatch')
    if len(request['dispatch'].encode('utf-8'))>32000:
        raise ValueError('loader input exceeds audited output size')
    if (path.parent/'expired.json').exists() or (path.parent/'response.json').exists():
        raise ValueError('request no longer active')
    receipt={'request_id':request_id,'dispatch_sha256':expected_hash,
             'request_file_sha256':hashlib.sha256(raw).hexdigest(),
             'loader_sha256':digest(Path(__file__).read_text(encoding='utf-8'))}
    with (path.parent/'loaded.json').open('x',encoding='utf-8') as out:
        json.dump(receipt,out,sort_keys=True)
    return request['dispatch']


def loader_command(folder, request):
    # All paths are trusted controller paths. Never interpolate task content.
    def quote(value): return "'"+str(value).replace("'","''")+"'"
    return ('& '+quote(ROOT/'.venv/Scripts/python.exe')+' -X utf8 -m generation.obligations.handoff load '
            +'--request '+quote(Path(folder).resolve()/'request.json')+' --request-id '
            +quote(request['request_id'])+' --sha256 '+quote(request['dispatch_sha256']))


def bootstrap(folder, request):
    args={'cmd':loader_command(folder,request),'workdir':str(ROOT),'max_output_tokens':12000}
    code='text(await tools.exec_command('+json.dumps(args,ensure_ascii=False)+'));'
    return ('You are an isolated Dafny solver in a file-delivery experiment. Your only permitted tool call is '
            'the following functions.exec invocation, exactly once, to load your complete input. '
            'Do not inspect any other files, browse, delegate, run a verifier, or use other tools. '
            'After the loader returns, follow the SYSTEM and USER text in its stdout and return only '
            'the requested JSON object as your final answer. If loading fails or output is truncated, '
            'return {"loader_error":true}; do not retry. No commentary.\n'+code)


class FileQueue(QueueModel):
    def __init__(self,root,batch_root=None):
        super().__init__(root)
        self.batch_root=Path(batch_root) if batch_root is not None else None

    def dispatch(self,messages): return dispatch(messages)

    def check_active(self):
        if self.batch_root is None:raise ValueError('audited campaign required')
        from .file_campaign import check_active
        check_active(self.batch_root,toolchain=False)

    def accept_response(self,folder,request,response):
        batch=json.loads((self.batch_root/'batch.json').read_text(encoding='utf-8'))
        validate_response(folder,request,response,batch['expected_backend'])

    def generate(self,messages,max_tokens,timeout,seed):
        from .file_campaign import halt,record_transport
        try:
            result=super().generate(messages,max_tokens,timeout,seed)
        except Exception as exc:
            if self.batch_root is not None:halt(self.batch_root,'queue_audit_failure',str(exc))
            return {'text':'','error':'protocol_halted','retryable':False,
                    'input_tokens':None,'output_tokens':None,'cost_usd':None}
        record_transport(self.batch_root,str(self.root.name)+'_'+str(self.index),
                         'error' if result.get('error') else 'ok')
        return result

    def identity(self):
        return {**super().identity(),'adapter':'verified_file_queue_v2','protocol':PROTOCOL,
                'tools':'exactly one fixed loader call permitted; subsequent tools prohibited by instruction',
                'input_delivery':'request identity/hash checked before tool stdout; receipt audited',
                'wrapper_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
                'token_usage_known':True,
                'model_request_accounting':'one solver context includes loader-selection and post-tool answer inference'}


def audit_context(rows):
    """Allow platform-marked environment refreshes, never additional solver input.

    Platform metadata is evidence from the original session, not a marker in a
    user-supplied prompt. Refreshes may repeat initial fields or advance the
    calendar by one day; filesystem, workspace, shell and timezone must stay put.
    """
    items=[r['payload'] for r in rows if r['type']=='response_item']
    tasks=[p for p in items if p['type']=='agent_message']
    users=[p for p in items if p.get('role')=='user']
    if len(tasks)!=1 or tasks[0].get('author')!='/root' or not users:
        raise ValueError('solver contains additional task or missing environment context')
    initial=None; previous=None; dates=[]; hashes=[]
    allowed={'cwd','shell','current_date','timezone','filesystem'}
    for message in users:
        metadata=message.get('internal_chat_message_metadata_passthrough',{})
        content=message.get('content',[])
        if (metadata.get('content_item_kinds')!=['environments.environment_context'] or
            len(content)!=1 or content[0].get('type')!='input_text'):
            raise ValueError('untrusted additional user context')
        text=content[0].get('text','')
        if '<!' in text or '<?' in text:raise ValueError('unexpected environment markup')
        try: node=ET.fromstring(text)
        except ET.ParseError as exc:raise ValueError('invalid environment context') from exc
        if node.tag!='environment_context' or node.attrib or (node.text or '').strip():
            raise ValueError('unexpected environment context')
        fields={}
        for child in node:
            if child.tag not in allowed or child.tag in fields or (child.tail or '').strip():
                raise ValueError('unexpected environment field or content')
            if child.tag=='filesystem':
                # Compare the full platform permission payload, excluding XML indentation.
                child.tail=None
                fields[child.tag]=ET.tostring(child,encoding='unicode')
            else:
                if child.attrib or len(child):raise ValueError('unexpected environment field structure')
                fields[child.tag]=(child.text or '').strip()
        if initial is None:
            if (set(fields)!=allowed or fields['cwd']!=str(ROOT.parent) or
                fields['shell']!='powershell' or fields['timezone']!='Asia/Shanghai'):
                raise ValueError('initial environment context differs from runner')
            initial=fields
        elif any(value!=initial[key] for key,value in fields.items() if key!='current_date'):
            raise ValueError('environment context changed beyond calendar update')
        try: current=date.fromisoformat(fields['current_date'])
        except (KeyError,ValueError) as exc:raise ValueError('missing or invalid environment date') from exc
        if previous is not None and current not in {previous,previous+timedelta(days=1)}:
            raise ValueError('unexpected environment date change')
        previous=current; dates.append(current.isoformat()); hashes.append(digest(text))
    return {'environment_messages':len(users),'dates':dates,'environment_sha256':hashes}


def extract_session(rows):
    contexts=[r['payload'] for r in rows if r['type']=='turn_context']
    if not contexts or len({(c.get('model'),c.get('effort')) for c in contexts})!=1:
        raise ValueError('model identity changed or missing')
    items=[r['payload'] for r in rows if r['type']=='response_item']
    calls=[p for p in items if p['type'].endswith('_call')]
    if len(calls)!=1 or calls[0].get('name')!='exec':
        raise ValueError('unexpected solver tool calls')
    finals=[p for p in items if p.get('role')=='assistant' and p.get('phase')=='final_answer']
    if len(finals)!=1:
        raise ValueError('missing or duplicate final answer')
    text=''.join(c.get('text','') for c in finals[0]['content'])
    counts=[r['payload']['info']['total_token_usage'] for r in rows if r['type']=='event_msg'
            and r['payload'].get('type')=='token_count' and r['payload'].get('info')]
    if not counts: raise ValueError('missing usage')
    return {'text':text,'model':contexts[0]['model'],'effort':contexts[0]['effort'],
            'usage':counts[-1],'tool_calls':len(calls),'model_turn_contexts':len(contexts)}


def audit_delivery(rows,folder,request,receipt):
    items=[r['payload'] for r in rows if r['type']=='response_item']
    calls=[p for p in items if p['type'].endswith('_call')]
    expected=bootstrap(folder,request).split('No commentary.\n',1)[1]
    if len(calls)!=1 or calls[0].get('name')!='exec' or calls[0].get('input','').strip()!=expected.strip():
        raise ValueError('actual loader command mismatch')
    outputs=[p for p in items if p['type']=='custom_tool_call_output' and p.get('call_id')==calls[0]['call_id']]
    if len(outputs)!=1:raise ValueError('missing loader output')
    values=[]
    for block in outputs[0]['output']:
        text=block.get('text','')
        try:value=json.loads(text)
        except ValueError:
            if not text.startswith('Script completed\n'):raise ValueError('unexpected loader output block')
        else:values.append(value)
    expected_stdout='HANDOFF_RECEIPT '+canonical(receipt)+'\n'+request['dispatch']
    if (len(values)!=1 or values[0].get('exit_code')!=0 or
        values[0].get('output','').replace('\r\n','\n')!=expected_stdout):
        raise ValueError('actual loader stdout mismatch or truncation')


def check_backend(result,expected):
    if any(result.get(k)!=expected.get(k) for k in ['model','effort']):
        raise ValueError('backend identity differs from frozen model/effort')


def validate_response(folder,request,response,expected):
    required={'delivery_audit','session_path','session_sha256','session_id','loader_receipt',
              'reported_usage','recorded_effort','backend_identity','agent','context_audit'}
    if not required<=response.keys() or response['delivery_audit']!='passed':
        raise ValueError('audited session response required')
    folder=Path(folder);session=Path(response['session_path'])
    raw=session.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=response['session_sha256']:raise ValueError('session changed')
    rows=[json.loads(l) for l in raw.decode('utf-8').splitlines()]
    meta=rows[0]['payload'];spawn=meta.get('source',{}).get('subagent',{}).get('thread_spawn',{})
    if (meta['id']!=response['session_id'] or spawn.get('agent_path')!=response['agent'] or
        spawn.get('parent_thread_id')!=expected['parent_thread_id']):raise ValueError('session identity differs')
    if audit_context(rows)!=response['context_audit']:raise ValueError('session context audit differs')
    result=extract_session(rows);check_backend(result,expected)
    if result['text']!=response['text'] or digest(result['text'])!=response['text_sha256']:
        raise ValueError('raw final differs')
    if result['usage']!=response['reported_usage'] or any(response[k]!=result['usage'][k] for k in ['input_tokens','output_tokens']):
        raise ValueError('usage differs')
    receipt=json.loads((folder/'loaded.json').read_text(encoding='utf-8'))
    if receipt!=response['loader_receipt'] or receipt['request_id']!=request['request_id'] or receipt['dispatch_sha256']!=request['dispatch_sha256']:
        raise ValueError('load receipt differs')
    if receipt['request_file_sha256']!=hashlib.sha256((folder/'request.json').read_bytes()).hexdigest():
        raise ValueError('loaded request changed')
    audit_delivery(rows,folder,request,receipt)


def collect(folder, session, agent, parent,expected=None):
    folder=Path(folder); session=Path(session)
    rows=[json.loads(line) for line in session.read_text(encoding='utf-8').splitlines()]
    meta=rows[0]['payload']
    spawn=meta.get('source',{}).get('subagent',{}).get('thread_spawn',{})
    if spawn.get('agent_path')!=agent or spawn.get('parent_thread_id')!=parent:
        raise ValueError('solver session identity mismatch')
    context_audit=audit_context(rows)
    result=extract_session(rows)
    if expected is not None:check_backend(result,expected)
    request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    receipt=json.loads((folder/'loaded.json').read_text(encoding='utf-8'))
    if receipt['request_id']!=request['request_id'] or receipt['dispatch_sha256']!=digest(dispatch(request['messages'])):
        raise ValueError('load receipt mismatch')
    if receipt['request_file_sha256']!=hashlib.sha256((folder/'request.json').read_bytes()).hexdigest():
        raise ValueError('request changed after load')
    if receipt['loader_sha256']!=digest(Path(__file__).read_text(encoding='utf-8')):
        raise ValueError('loader changed after load')
    if (folder/'response.json').exists() or (folder/'expired.json').exists():
        raise ValueError('request already completed or expired')
    audit_delivery(rows,folder,request,receipt)
    response={'request_id':request['request_id'],'text':result['text'],'text_sha256':digest(result['text']),
              'agent':agent,'input_tokens':result['usage']['input_tokens'],
              'output_tokens':result['usage']['output_tokens'],'cost_usd':None,
              'backend_identity':result['model'],'tool_prohibition':'one_loader_then_no_tools',
              'session_id':meta['id'],'session_sha256':hashlib.sha256(session.read_bytes()).hexdigest(),
              'session_path':str(session.resolve()),
              'recorded_effort':result['effort'],'reported_usage':result['usage'],
              'model_turn_contexts':result['model_turn_contexts'],'delivery_audit':'passed',
              'loader_receipt':receipt,'context_audit':context_audit}
    atomic_json(folder/'response.json',response)
    return response


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    load=sub.add_parser('load')
    load.add_argument('--request',type=Path,required=True)
    load.add_argument('--request-id',required=True)
    load.add_argument('--sha256',required=True)
    args=parser.parse_args()
    text=load_request(args.request,args.request_id,args.sha256)
    receipt=json.loads((args.request.parent/'loaded.json').read_text(encoding='utf-8'))
    sys.stdout.write('HANDOFF_RECEIPT '+canonical(receipt)+'\n'+text)


if __name__=='__main__':main()
