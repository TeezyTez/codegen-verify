"""Independent post-hoc compilation audit; never executes generated programs.

This is a secondary measurement, never candidate acceptance or agent feedback.
--no-verify is permitted only after independently checking archived successful
verification and exact v3 source-byte provenance. Legacy newline-translating
verifier records are unknown rather than reconstructed or repaired.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from .analyze import _trial
from .task import canonical, digest
from generation.representation.verifier import _stop_and_drain
from repair.verifier import classify

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_DAFNY=ROOT/'.tools/dafny/4.11.0/Dafny.exe'


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _identity(row):
    return row['model'],row['task_id'],row['replicate'],row['arm']


def _inside(root,relative):
    path=(root/relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError('artifact path escapes read-only trial')
    return path


def _roster(root):
    """Read the frozen roster; individual trial corruption is handled per row."""
    if not (root/'jobs.json').exists():
        row=_read(root/'result.json')
        return [(root,row)],'single_trial'
    manifest=_read(root/'manifest.json');jobs=_read(root/'jobs.json');tasks=_read(root/'tasks.json')
    saved=_read(root/'results.json')
    if (digest(canonical(jobs))!=manifest['jobs_sha256']
            or digest(canonical(tasks))!=manifest['tasks_sha256']
            or len(jobs)!=manifest['expected_sessions']):
        raise ValueError('campaign roster or task digest differs')
    model=manifest['model'].get('model',manifest['model'].get('name','unknown'))
    expected=[(model,j['task_id'],j['replicate'],j['arm']) for j in jobs]
    actual=[_identity(row) for row in saved]
    directories=[j['directory'] for j in jobs]
    if (not jobs or len(set(expected))!=len(expected) or len(set(actual))!=len(actual)
            or len(set(directories))!=len(directories) or set(expected)!=set(actual)
            or len(jobs)!=len(saved)):
        raise ValueError('campaign results do not exactly match frozen roster')
    indexed={_identity(row):row for row in saved}
    return [(_inside(root/'runs',job['directory']),indexed[key])
            for job,key in zip(jobs,expected)],manifest.get('phase','unspecified')


def _verified_source(root,saved):
    row,manifest=_trial(root)
    if row!=saved or row.get('success') is not True or row.get('stop_reason')!='verified':
        raise ValueError('successful trial differs from saved result')
    original_verifier=manifest.get('verifier',{})
    if (original_verifier.get('adapter')!='representation_formal_only_v3'
            or original_verifier.get('source_encoding')!='utf-8'
            or original_verifier.get('source_newline_translation') is not False):
        raise ValueError('unsupported_provenance: original verifier did not preserve exact UTF-8 source bytes')
    action=row['successful_action'];round_=row['rounds'][action-1]
    prefix=f'round-{action:02d}'
    required={f'{prefix}/{name}' for name in ('candidate.dfy','structure.json','verification.json',
                                              'round.json','verifier.stdout.txt','verifier.stderr.txt','verifier.csv')}
    recorded={Path(name).as_posix() for name in row.get('artifact_sha256',{})}
    if not required<=recorded:
        raise ValueError('required successful-round artifact hash missing')
    if _read(root/prefix/'round.json')!=round_:
        raise ValueError('successful round artifact differs')
    source=(root/prefix/'candidate.dfy').read_bytes()
    source.decode('utf-8')  # Strict validation only; never rewrite or normalize bytes.
    source_hash=_sha(source)
    if source_hash!=row.get('accepted_candidate_sha256') or source_hash!=round_.get('candidate_sha256'):
        raise ValueError('candidate UTF-8 byte SHA differs from accepted source SHA')
    structure=_read(root/prefix/'structure.json')
    if (structure.get('source_sha256')!=source_hash or structure.get('status')!='ok'
            or structure.get('trusted_ast') is not True or structure.get('findings')
            or round_.get('guard_findings')!=[]):
        raise ValueError('successful candidate AST or guard evidence differs')
    target=manifest['task']['target_name']
    primary=[d for d in structure.get('declarations',[]) if d.get('name')==target]
    if len(primary)!=1 or primary[0]['id'] not in manifest['editable_ids']:
        raise ValueError('primary declaration is absent from successful AST')
    verification=_read(root/prefix/'verification.json')
    if verification!=round_.get('verification'):
        raise ValueError('verification artifact differs from successful round')
    if (verification.get('status')!='verified' or verification.get('executed') is not True
            or verification.get('real_verifier') is not True or verification.get('returncode')!=0):
        raise ValueError('success lacks original real successful Dafny verification')
    for name,key in [('verifier.stdout.txt','stdout'),('verifier.stderr.txt','stderr'),('verifier.csv','csv_log')]:
        if (root/prefix/name).read_text(encoding='utf-8')!=verification.get(key,''):
            raise ValueError('verifier stream differs from recorded verification')
    command=verification.get('command',[])
    # v3 emits this exact full-verification command shape. Reject filters and
    # unrecognized switches even if a forged record reports all shown batches passed.
    if (not isinstance(command,list) or not all(isinstance(v,str) for v in command)
            or len(command) not in {9,11} or command[1]!='verify'
            or command[3:6]!=['--cores','1','--verification-time-limit']
            or not command[6].isdigit() or int(command[6])<1
            or command[7]!='--log-format' or not command[8].startswith('csv;LogFileName=')
            or (len(command)==11 and command[9]!='--solver-path')):
        raise ValueError('original evidence was not an unfiltered v3 Dafny verification command')
    observations={}
    for batch in csv.DictReader(verification.get('csv_log','').splitlines()):
        name=batch.get('TestResult.DisplayName')
        if not name or name in observations:
            raise ValueError('ambiguous original verifier CSV')
        observations[name]=batch.get('TestResult.Outcome','').lower()
    if (not observations or observations!=verification.get('obligations')
            or any(status!='passed' for status in observations.values())
            or classify(verification['stdout']+verification['stderr'],0,observations)!='passed'):
        raise ValueError('original full verification is not uniformly successful')
    declaration=primary[0]
    bases=set(declaration.get('verifier_names',[]))|{declaration['id'],declaration['name']}
    suffixes={'correctness'} if declaration['kind'] in {'method','lemma'} else {'correctness','well-formedness'}
    primary_batches={name:value for name,value in observations.items()
                     if any(name==base+' ('+suffix+')' for base in bases for suffix in suffixes)}
    if not primary_batches or primary_batches!=verification.get('primary_batches'):
        raise ValueError('primary verification coverage is not established')
    provenance={'candidate_path':str(root/prefix/'candidate.dfy'),'candidate_byte_sha256':source_hash,
                'accepted_candidate_sha256':row['accepted_candidate_sha256'],
                'result_sha256':digest(canonical(row)),'manifest_sha256':digest(canonical(manifest)),
                'structure_sha256':digest(canonical(structure)),
                'verification_sha256':digest(canonical(verification)),
                'original_verifier':original_verifier,'successful_action':action,
                'original_model_research_eligible':row.get('research_eligible',False),
                'no_verify_authorization':'Exact accepted UTF-8 bytes and original full successful Dafny verification independently checked; skip repeat proof only for this secondary translation.'}
    return source,provenance


def _run_process(command,cwd,timeout):
    """One bounded child process; timeout cleanup kills only its process tree."""
    started=time.monotonic()
    result={'command':[str(x) for x in command],'timeout_seconds':timeout,'executed':False,
            'returncode':None,'stdout':'','stderr':'','status':'unknown'}
    env={k:os.environ[k] for k in ('PATH','SYSTEMROOT','DOTNET_ROOT','USERPROFILE','LOCALAPPDATA',
         'APPDATA','TEMP','TMP','TMPDIR') if k in os.environ}
    try:
        process=subprocess.Popen(result['command'],cwd=cwd,env=env,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',start_new_session=os.name=='posix')
        result['executed']=True
        try:
            result['stdout'],result['stderr']=process.communicate(timeout=timeout)
            result['status']='completed'
        except subprocess.TimeoutExpired as error:
            result['status']='timeout'
            result['stdout'],result['stderr']=_stop_and_drain(process,error.output,error.stderr)
        except BaseException:
            _stop_and_drain(process)
            raise
        result['returncode']=process.returncode
    except (OSError,UnicodeError) as error:
        result.update(status='unknown',error_type=type(error).__name__)
    result['seconds']=time.monotonic()-started
    result['cleanup_incomplete']='verifier_cleanup_incomplete' in result['stderr']
    return result


def _compiler_identity(dafny,output):
    version=_run_process([str(dafny),'--version'],output,10)
    help_=_run_process([str(dafny),'translate','py','--help'],output,10)
    usable=(version['status']=='completed' and version['returncode']==0
            and version['stdout'].strip().startswith('4.11.0')
            and help_['status']=='completed' and help_['returncode']==0
            and '--no-verify' in help_['stdout'] and '--output' in help_['stdout'])
    files=[dafny,dafny.parent/'DafnyDriver.dll',dafny.parent/'DafnyCore.dll']
    return {'usable':usable,'version':version,'translate_py_help':help_,
            'file_sha256':{str(p):_sha(p.read_bytes()) for p in files if p.is_file()},
            'python_executable':sys.executable,'python_version':sys.version,
            'python_executable_sha256':_sha(Path(sys.executable).read_bytes()),
            'audit_source_sha256':_sha(Path(__file__).read_bytes()),
            'generated_program_execution':False,'per_source_timeout_limit_seconds':120,
            'timeout_cleanup_limit_seconds':10 if os.name=='nt' else 5}


def _translate(source,directory,dafny,timeout):
    """Called only after _verified_source. Writes solely within the audit output."""
    directory.mkdir(parents=True,exist_ok=False)
    candidate=directory/'accepted.dfy';candidate.write_bytes(source)
    generated=directory/'generated';generated.mkdir()
    started=time.monotonic()
    translation=_run_process([str(dafny),'translate','py',str(candidate),'--no-verify',
                              '--include-runtime','--output',str(generated/'program.py')],directory,timeout)
    result={'source_byte_sha256':_sha(source),'translation':translation,'syntax':None,
            'translate_succeeded':False,'python_syntax_ok':False,'status':'unknown',
            'generated_file_sha256':{},'executed_generated_program':False}
    if translation['status']=='completed' and translation['returncode']!=0:
        result['status']='failed'
    elif translation['status']=='completed' and translation['returncode']==0:
        result['translate_succeeded']=True
        python_files=sorted(generated.rglob('*.py'))
        if not python_files:
            result['reason']='translation emitted no Python source'
        else:
            remaining=timeout-(time.monotonic()-started)
            if remaining<=0:
                result['reason']='source audit deadline reached before Python syntax compilation'
            else:
                syntax=_run_process([sys.executable,'-I','-S','-m','py_compile',*[str(p) for p in python_files]],
                                    directory,remaining)
                result['syntax']=syntax
                if syntax['status']=='completed':
                    result['python_syntax_ok']=syntax['returncode']==0
                    result['status']='python_syntax_ok' if result['python_syntax_ok'] else 'failed'
    for path in sorted(generated.rglob('*')):
        if path.is_file():
            if generated.resolve() not in path.resolve().parents:
                raise ValueError('generated artifact escaped translation directory')
            result['generated_file_sha256'][str(path.relative_to(directory))]=_sha(path.read_bytes())
    for stage in ['translation','syntax']:
        if result[stage] is not None:
            for stream in ['stdout','stderr']:
                (directory/f'{stage}.{stream}.txt').write_bytes(result[stage][stream].encode('utf-8'))
    result['seconds']=time.monotonic()-started
    _write(directory/'result.json',result)
    return result


def audit_campaign(directory,output_dir,*,dafny_path=DEFAULT_DAFNY,timeout=120,workers=1):
    """Audit every recorded successful trial independently, then cache compilation."""
    root=Path(directory).resolve();output=Path(output_dir).resolve();dafny=Path(dafny_path).resolve()
    if output==root or root in output.parents:
        raise ValueError('compile audit output must be outside the read-only source directory')
    if output.exists(): raise FileExistsError('compile audit output already exists')
    if type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0<timeout<=120:
        raise ValueError('compile audit timeout must be positive and at most 120 seconds')
    if type(workers) is not int or not 1<=workers<=8:
        raise ValueError('compile audit workers must be an integer from 1 to 8')
    roster,phase=_roster(root)
    if any(row.get('complete') is not True or type(row.get('success')) is not bool for _,row in roster):
        raise ValueError('compile audit requires an entirely completed explicit-result roster')
    output.mkdir(parents=True,exist_ok=False)
    compiler=None;cache={};rows=[];cache_hits=0;sources={}
    # Finish provenance checks for every trial before any compiler process starts.
    for trial,saved in roster:
        if saved['success'] is not True:continue
        row={'identity':list(_identity(saved)),'trial_directory':str(trial),'primary_success':True,
             'provenance_verified':False,'translate_succeeded':False,'python_syntax_ok':False,
             'status':'unknown','cache_hit':False}
        rows.append(row)
        try:
            source,provenance=_verified_source(trial,saved)
        except (OSError,UnicodeError,ValueError,KeyError,TypeError,IndexError) as error:
            row['reason']='unsupported_provenance' if 'unsupported_provenance' in str(error) else 'invalid_provenance'
            row['detail']=str(error)
            continue
        row.update(provenance_verified=True,provenance=provenance)
        source_hash=provenance['candidate_byte_sha256']
        if source_hash in sources:
            cache_hits+=1;row['cache_hit']=True
        else:
            sources[source_hash]=source
    if sources:
        compiler=_compiler_identity(dafny,output);_write(output/'compiler.json',compiler)
    if compiler and compiler['usable']:
        def compile_one(item):
            source_hash,source=item
            try:
                return source_hash,_translate(source,output/'sources'/source_hash,dafny,timeout)
            except (OSError,UnicodeError,ValueError) as error:
                # Cache infrastructure failures too: each SHA gets at most one attempt.
                return source_hash,{'infrastructure_error':str(error)}
        if workers==1:
            cache=dict(map(compile_one,sources.items()))
        else:
            with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='compile-audit') as executor:
                cache=dict(executor.map(compile_one,sources.items()))
    # Merge in roster order, independent of worker completion order.
    for row in rows:
        if not row['provenance_verified']:continue
        source_hash=row['provenance']['candidate_byte_sha256']
        if not compiler['usable']:
            row['reason']='compiler_unavailable_or_unexpected_version'
            row['cache_hit']=False
            continue
        compiled=cache[source_hash]
        if 'infrastructure_error' in compiled:
            row['reason']='compile_audit_infrastructure_failure';row['detail']=compiled['infrastructure_error']
            continue
        row.update({key:compiled[key] for key in ('translate_succeeded','python_syntax_ok','status')})
        row.update(compile_result=f'sources/{source_hash}/result.json',
                   compile_result_sha256=digest(canonical(compiled)))
    counts={'translate_succeeded':sum(r['translate_succeeded'] for r in rows),
            'python_syntax_ok':sum(r['python_syntax_ok'] for r in rows),
            'failed':sum(r['status']=='failed' for r in rows),'unknown':sum(r['status']=='unknown' for r in rows)}
    summary={'schema_version':1,'source_directory':str(root),'phase':phase,'primary_successes':len(rows),
             'primary_failures_not_audited':len(roster)-len(rows),'primary_acceptance_changed':False,
             'counts':counts,'unique_compiled_sources':len(cache),
             'cache_hits':cache_hits if cache else 0,'workers':workers,'rows':rows,
             'compiler':compiler,'no_agent_feedback':True,'executed_generated_programs':False,
             'interpretation':'Independent secondary translation and Python syntax measurement. --no-verify only avoids repeating an already evidenced proof; it never accepts candidates. Syntax compilation does not establish runtime correctness. Old newline-translating provenance is unsupported, never reconstructed.'}
    _write(output/'summary.json',summary)
    (output/'rows.jsonl').write_bytes(('\n'.join(canonical(r) for r in rows)+'\n').encode('utf-8'))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dafny',type=Path,default=DEFAULT_DAFNY)
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--workers',type=int,default=1,help='Concurrent unique-source audits (1 to 8; default 1)')
    args=parser.parse_args()
    result=audit_campaign(args.directory,args.output,dafny_path=args.dafny,timeout=args.timeout,workers=args.workers)
    print(json.dumps({'primary_successes':result['primary_successes'],'counts':result['counts'],
                      'primary_acceptance_changed':False},ensure_ascii=False))
