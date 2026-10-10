"""Fetch pinned research data only; never execute upstream repository code."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent


def download(url):
    req=urllib.request.Request(url,headers={'User-Agent':'codegen-verify-research'})
    with urllib.request.urlopen(req,timeout=90) as response:
        return response.read()


def fetch(name):
    tree=json.loads((ROOT/(name+'-tree.json')).read_text(encoding='utf-8'))
    assert not tree.get('truncated')
    records={x['path']:x for x in tree['tree'] if x['type']=='blob'}
    if name=='algoveri':
        wanted={p for p in records if p.startswith('algoveri_data/') or p in {'README.md','LICENSE','VERIFIER_README.md'}}
    elif name=='dafnybench':
        wanted={p for p in records if p.startswith('DafnyBench/') or p in {'README.md','LICENSE'}}
    else:
        wanted={'README.md','LICENSE','jsonl/dafny_tasks.jsonl','jsonl/dafny_issues.jsonl',
                'vericoding_benchmark_v1.csv','inspection/README.md','inspection/ANALYSIS.md',
                'inspection/MISTRANSLATED.md','inspection/WEAK.md'} & set(records)
        wanted |= {p for p in records if p.startswith('vericoded/') and p.endswith('.dfy')}
    out=(ROOT/name).resolve()
    out.mkdir(exist_ok=True)
    received={}
    # One pinned archive avoids thousands of raw-content requests. Every selected
    # member is still checked against its independently retrieved Git tree blob.
    url=f"https://codeload.github.com/{tree['repository']}/zip/{tree['commit']}"
    blob=download(url)
    archive=zipfile.ZipFile(io.BytesIO(blob))
    for member in archive.infolist():
        if member.is_dir(): continue
        relative=member.filename.split('/',1)[-1]
        if relative in wanted:
            received[relative]=archive.read(member)
    assert set(received)==wanted
    manifest=[]
    for relative,blob in sorted(received.items()):
        target=(out/relative).resolve()
        assert target.is_relative_to(out)
        git_blob=hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()
        assert git_blob==records[relative]['sha'],relative
        assert len(blob)==records[relative]['size']
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists(): assert target.read_bytes()==blob
        else: target.write_bytes(blob)
        manifest.append({'path':relative,'bytes':len(blob),'git_blob_sha1':git_blob,
                         'sha256':hashlib.sha256(blob).hexdigest()})
    result={'dataset':name,'repository':tree['repository'],'commit':tree['commit'],
            'retrieved_at':datetime.now(timezone.utc).isoformat(),'files':manifest,
            'upstream_code_executed':False,'git_blob_checks_passed':True}
    dest=ROOT/(name+'-snapshot.json')
    assert not dest.exists(),'Snapshot already finalized'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'dataset':name,'files':len(manifest),'bytes':sum(x['bytes'] for x in manifest),'commit':tree['commit']}


if __name__=='__main__':
    import sys
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(fetch,sys.argv[1:] or ['algoveri','dafnybench','vericoding']):
            print(json.dumps(result),flush=True)
