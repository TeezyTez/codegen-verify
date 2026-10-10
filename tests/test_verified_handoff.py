import json
import pytest

from generation.representation.task import canonical
from repair.task import digest


def request_file(tmp_path):
    messages=[{'role':'system','content':'Fixed contracts.'},{'role':'user','content':'{"task":"public"}'}]
    dispatch='SYSTEM:\nFixed contracts.\nUSER:\n{"task":"public"}'
    value={'request_id':'a'*32,'messages':messages,'messages_sha256':digest(canonical(messages)),
           'dispatch':dispatch,'dispatch_sha256':digest(dispatch)}
    path=tmp_path/'request.json'
    path.write_text(json.dumps(value),encoding='utf-8')
    return path,value


def test_loader_checks_bytes_before_disclosing_or_receipting(tmp_path):
    from generation.obligations.handoff import load_request
    path,r=request_file(tmp_path)
    text=load_request(path,r['request_id'],r['dispatch_sha256'])
    assert text==r['dispatch']
    receipt=json.loads((tmp_path/'loaded.json').read_text())
    assert receipt['dispatch_sha256']==digest(text)
    with pytest.raises(FileExistsError):
        load_request(path,r['request_id'],r['dispatch_sha256'])


@pytest.mark.parametrize('field,value',[('request_id','b'*32),('dispatch','missing clause'),('messages',[])])
def test_mismatches_fail_closed(tmp_path,field,value):
    from generation.obligations.handoff import load_request
    path,r=request_file(tmp_path)
    changed={**r,field:value};path.write_text(json.dumps(changed),encoding='utf-8')
    with pytest.raises(ValueError):load_request(path,r['request_id'],r['dispatch_sha256'])
    assert not (tmp_path/'loaded.json').exists()


def test_session_import_rejects_extra_tools_and_preserves_exact_final(tmp_path):
    from generation.obligations.handoff import extract_session
    rows=[{'type':'turn_context','payload':{'model':'test','effort':'high'}},
          {'type':'response_item','payload':{'type':'function_call','name':'exec','namespace':'functions','arguments':'approved loader'}},
          {'type':'response_item','payload':{'type':'function_call_output','output':'loaded'}},
          {'type':'response_item','payload':{'type':'message','role':'assistant','phase':'final_answer','content':[{'text':'  {"bodies":{}}\n'}]}},
          {'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':10,'output_tokens':5}}}}]
    result=extract_session(rows)
    assert result['text']=='  {"bodies":{}}\n' and result['model']=='test'
    rows.insert(1,{'type':'response_item','payload':{'type':'function_call','name':'exec','arguments':'read other file'}})
    with pytest.raises(ValueError,match='tool'):extract_session(rows)


def test_audit_checks_actual_command_and_complete_tool_output(tmp_path):
    from generation.obligations.handoff import audit_delivery, bootstrap
    path,r=request_file(tmp_path)
    receipt={'request_id':r['request_id'],'dispatch_sha256':r['dispatch_sha256']}
    code=bootstrap(tmp_path,r).split('No commentary.\n',1)[1]
    stdout='HANDOFF_RECEIPT '+canonical(receipt)+'\n'+r['dispatch']
    rows=[{'type':'response_item','payload':{'type':'custom_tool_call','name':'exec','call_id':'x','input':code}},
        {'type':'response_item','payload':{'type':'custom_tool_call_output','call_id':'x','output':[
            {'type':'input_text','text':json.dumps({'exit_code':0,'output':stdout})}]}}]
    audit_delivery(rows,tmp_path,r,receipt)
    rows[1]['payload']['output'][0]['text']=json.dumps({'exit_code':0,'output':stdout[:-1]})
    with pytest.raises(ValueError,match='stdout'):audit_delivery(rows,tmp_path,r,receipt)
    rows[0]['payload']['input']=code+' extra_command()'
    with pytest.raises(ValueError,match='command'):audit_delivery(rows,tmp_path,r,receipt)


def test_model_identity_must_match_frozen_backend():
    from generation.obligations.handoff import check_backend
    check_backend({'model':'expected','effort':'high'},{'model':'expected','effort':'high'})
    with pytest.raises(ValueError,match='backend'):
        check_backend({'model':'different','effort':'high'},{'model':'expected','effort':'high'})


def test_new_queue_refuses_legacy_manual_response(tmp_path):
    from generation.obligations.handoff import validate_response
    path,r=request_file(tmp_path)
    legacy={'request_id':r['request_id'],'text':'{}','text_sha256':digest('{}'),'agent':'manual'}
    with pytest.raises(ValueError,match='audited'):
        validate_response(tmp_path,r,legacy,{'model':'test','effort':'high'})


def test_legacy_submission_halts_live_queue_without_consumption(tmp_path):
    import threading,time
    from generation.obligations.handoff import FileQueue
    from generation.obligations.exploration import submit
    from generation.obligations.runner import source_hashes
    batch={'source_hashes':source_hashes(),'tasks':{},'expected_backend':{'model':'test','effort':'high'}}
    (tmp_path/'batch.json').write_text(json.dumps(batch),encoding='utf-8')
    (tmp_path/'freeze.json').write_text(json.dumps({'batch.json':digest((tmp_path/'batch.json').read_text())}),encoding='utf-8')
    queue=tmp_path/'queue'/'job';model=FileQueue(queue,tmp_path);results=[]
    thread=threading.Thread(target=lambda:results.append(model.generate(
        [{'role':'system','content':'test'},{'role':'user','content':'public'}],4096,3,1)))
    thread.start()
    folder=queue/'001'
    deadline=time.monotonic()+2
    while not (folder/'request.json').exists() and time.monotonic()<deadline:time.sleep(.01)
    request=json.loads((folder/'request.json').read_text())
    submit(folder,request['request_id'],'{}','legacy')
    thread.join(4)
    assert results[0]['error']=='protocol_halted' and results[0]['retryable'] is False
    assert (tmp_path/'halted.json').exists() and not (folder/'consumed.json').exists()
