import pytest


def test_development_schedule_is_complete_and_reproducible():
    from generation.obligations.file_campaign import schedule, TASK_IDS
    jobs=schedule(TASK_IDS,3,20261008)
    assert jobs==schedule(TASK_IDS,3,20261008)
    assert len(jobs)==96
    assert len({j['directory'] for j in jobs})==96
    assert len({(j['task_id'],j['strategy'],j['replicate']) for j in jobs})==96
    for offset in range(0,96,4):
        block=jobs[offset:offset+4]
        assert len({(j['task_id'],j['replicate']) for j in block})==1
        assert {j['strategy'] for j in block}=={'baseline','state','guided','independent_sampling'}
    with pytest.raises(ValueError):schedule(TASK_IDS[:-1],3,20261008)


def test_halt_is_persistent_and_three_consecutive_transport_errors_stop(tmp_path):
    from generation.obligations.file_campaign import record_transport,check_not_halted
    record_transport(tmp_path,'a','error')
    record_transport(tmp_path,'b','error')
    record_transport(tmp_path,'c','ok')
    record_transport(tmp_path,'d','error')
    record_transport(tmp_path,'e','error')
    check_not_halted(tmp_path)
    record_transport(tmp_path,'f','error')
    with pytest.raises(ValueError,match='halted'):check_not_halted(tmp_path)


def test_model_success_does_not_reset_verifier_infrastructure_failures(tmp_path):
    from generation.obligations.file_campaign import record_transport,check_not_halted
    for i in range(3):
        record_transport(tmp_path,str(i),'error',channel='verifier')
        record_transport(tmp_path,str(i),'ok')
    with pytest.raises(ValueError,match='halted'):check_not_halted(tmp_path)
