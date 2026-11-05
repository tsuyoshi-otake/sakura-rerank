"""Fixed comparison policy and authenticated raw pools; no training execution."""
import gzip
import json
from pathlib import Path
import subprocess
import sys

from sakura_rerank.data.consumed_numeric import verify_chain
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from reserve_plan import ROOT,HERE,sha,read,save

sys.path.insert(0,'research/issue-33-consumed-numeric')
try:
    import numeric_common as prior
finally:
    sys.path.pop(0)

PLAN=HERE/'plan-v1.json'
PLAN_COMMIT='55d26ed181bbac424a772a179a0749303457ad31'
DICTIONARY=Path('data/generated/system-dictionary-index.jsonl')
DICTIONARY_SHA='4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072'


def authenticate():
    plan=json.loads(prior.boundary.committed(PLAN,PLAN_COMMIT))
    prior.boundary.committed(HERE/'policy-v1.md',PLAN_COMMIT)
    for path,digest in plan['inputs'].items():
        if sha(path)!=digest: raise ValueError('comparison_frozen_input_changed')
    evaluation=plan['evaluation']
    if sha(evaluation['selection_path'])!=evaluation['selection_sha256']:
        raise ValueError('comparison_reservation_changed')
    return plan


def rows(path):
    if Path(path).stat().st_size>512*1024*1024: raise ValueError('comparison_artifact_bound')
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rb') as stream:
        count=0;size=0
        while raw:=stream.readline(256*1024+1):
            count+=1;size+=len(raw)
            if len(raw)>256*1024 or count>1000000 or size>512*1024*1024:
                raise ValueError('comparison_decoded_artifact_bound')
            yield json.loads(raw)


def write_rows(path,values):
    count=0;size=0
    with Path(path).open('xb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as stream:
        for row in values:
            encoded=canonical_json_bytes(row)+b'\n';count+=1;size+=len(encoded)
            if size>512*1024*1024 or len(encoded)>256*1024 or count>1000000:
                raise ValueError('comparison_output_artifact_bound')
            stream.write(encoded)
    return dict(path=Path(path).name,sha256=sha(path),rows=count,decoded_bytes=size)


def source_pools():
    plan=authenticate()
    old=list(rows(plan['source']['dictionary_pool']))
    if (len(old)!=162502 or len({r['stable_id'] for r in old})!=len(old)
            or any(r['population']!='train' or r['corpus'] not in ('jawiki','aozora') for r in old)):
        raise ValueError('comparison_dictionary_pool_changed')
    _,all_annotations,_,receipts,units=prior.origin.scope()
    manifest=read(prior.ROOT/'cache/manifest.json')
    verified=read('reports/issue-33-consumed-numeric-verification-v1.json')
    if (verified['status']!='passed' or verified['report_sha256']!=sha('reports/issue-33-consumed-numeric-v1.json')
            or verified['cache_manifest_sha256']!=sha(prior.ROOT/'cache/manifest.json')
            or verified['script_sha256']!=sha('research/issue-33-consumed-numeric/verify_cache.py')):
        raise ValueError('comparison_annotation_numeric_verification_changed')
    for filename,digest in manifest['artifacts'].items():
        if sha(prior.ROOT/'cache'/filename)!=digest: raise ValueError('comparison_annotation_cache_changed')
    chain=verify_chain((prior.ROOT/'cache/row-receipts.jsonl').read_bytes(),manifest['rows'],manifest['row_chain_head'])
    origins={r['origin']['stable_id']:r['origin'] for r in chain}
    annotations=sorted((r for r in all_annotations if r['stable_id'] in origins),key=lambda r:r['stable_id'])
    if len(annotations)!=35592 or len(origins)!=35592:
        raise ValueError('comparison_annotation_pool_count')
    for row in annotations:
        origin=origins[row['stable_id']]
        if (origin['original_row_sha256']!=canonical_json_hash(row)
                or origin['consumption_sha256']!=canonical_json_hash(receipts[row['stable_id']])):
            raise ValueError('comparison_annotation_source_changed')
    return plan,old,annotations,receipts,units


def dictionary_readings():
    if sha(DICTIONARY)!=DICTIONARY_SHA: raise ValueError('comparison_dictionary_changed')
    result={}
    for row in rows(DICTIONARY):
        if len(row['readings'])==1:
            result[row['surface']]=row['readings'][0]
    return result


def implementation(paths):
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True,timeout=15).strip()
    for path in paths: prior.boundary.committed(path,head)
    return head,{str(path).replace('\\','/'):sha(path) for path in paths}
