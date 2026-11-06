"""Bounded native-population replay and long-text tensor parity; no Test labels."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from sakura_rerank import current_tiny as current, native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_worker import Adapter, execute_model, runtime_identity

ROOT=Path(__file__).resolve().parents[2]
PARITY=ROOT/'research/issue-35-current-tiny-parity'
sys.path.insert(0,str(PARITY))
from current_tiny_reference_adapter import reference_factory

spec=importlib.util.spec_from_file_location('native_population_parity_support',PARITY/'parity.py')
support=importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save(path,value):
    with path.open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def vectors():
    # UTF-8 capacity boundaries, astral scalars and decomposed Unicode. No labels.
    texts=['A'*1536,'東'*512,'😀'*384,'か\u3099'*256,'A'*257,'東'*129]
    costs=[-(1<<63),-1,0,1,(1<<31)-1,(1<<63)-1]
    rows=[[dict(surface=texts[(i+j)%6],local_cost=costs[j]) for j in range(2+i%5)] for i in range(20)]
    return rows+[[],rows[0][:1],rows[4]+rows[0][:1]]


def harness(source):
    # Only the private diagnostic wire reader changes. The included production
    # scorer is untouched; native storage1536 remains below protocol3072 bytes.
    raw=support.harness(source)
    old=b'assert!(len <= 1024);'
    if raw.count(old)!=1:raise ValueError('diagnostic reader boundary differs')
    return raw.replace(old,b'assert!(len <= 1536);')


def replay(capture_root,plan_sha,result_sha):
    values=native.verify_capture((capture_root/'plan.json').read_bytes(),(capture_root/'result.json').read_bytes(),
        (capture_root/'capture.jsonl').read_bytes(),expected_plan_sha256=plan_sha,expected_result_sha256=result_sha)
    receipts=[]
    for item in values:
        if item['snapshot'] is None:continue
        snapshot=item['snapshot']
        receipts.append(native.bind_population_input(snapshot,native.population_input(snapshot),snapshot['product_state']))
    counts=[r['candidate_count'] for r in receipts]
    return dict(events=len(values),bound_snapshots=len(receipts),no_conversion_events=len(values)-len(receipts),
                candidate_records=sum(counts),maximum_candidates=max(counts),above_legacy32=sum(c>32 for c in counts),
                bindings_sha256=sha(canonical_json_bytes(receipts)))


def identity(source,capture_root):
    if support.command('git','-C',str(source),'status','--porcelain'):
        raise ValueError('native source must be clean')
    if support.command('git','-C',str(source),'rev-parse','HEAD')!=current.HEAD:
        raise ValueError('native source HEAD differs')
    paths=[Path(__file__),PARITY/'parity.py',PARITY/'native_harness.rs.in',PARITY/'current_tiny_reference_adapter.py']
    return dict(source_head=current.HEAD,sources=support.source_identity(source),compiler=support.compiler_identity(),
                implementation={str(p.relative_to(ROOT)).replace('\\','/'):sha(p.read_bytes()) for p in paths},
                runtime=runtime_identity(),captures={name:sha((capture_root/name).read_bytes())
                    for name in ('plan.json','result.json','capture.jsonl')})


def prepare(source,capture_root,work):
    if work.exists() or not work.is_relative_to(Path.home()/'tmp'):
        raise ValueError('fresh owned temporary root required')
    work.mkdir()
    value=identity(source,capture_root)
    value.update(kind='native_population_verification',version=1,harness_sha256=sha(harness(source)),
                 vectors_sha256=sha(support.projection_wire(vectors())),
                 source_capture_plan_sha256='f67b35f9ad7686e4e01ec39cb65a18846b9106e772136f163ce242d0fe9c4985',
                 source_capture_result_sha256='360085bf976e09f6c344654bc2fcc3c9aea82f9fbf5866589c56937f7e51d479')
    save(work/'plan.json',value)
    return dict(status='prepared',plan_sha256=sha((work/'plan.json').read_bytes()))


def compare(raw,rows):
    import numpy as np
    layout=[('context_ids',(1,64),'<i8'),('context_lengths',(1,),'<i8'),('reading_ids',(1,32),'<i8'),
            ('reading_lengths',(1,),'<i8'),('candidate_ids',(1,6,32),'<i8'),('candidate_lengths',(1,6),'<i8'),
            ('features',(1,6,6),'<f4'),('candidate_mask',(1,6),'?')]
    offset=elements=rejected=0
    feeds=[]
    for row in rows:
        accepted=raw[offset];offset+=1
        if not accepted:
            try:current.protocol_feed(row,full_population=True)
            except current.ProductContractError:rejected+=1
            else:raise ValueError('native rejection differs')
            continue
        expected=current.protocol_feed(row,full_population=True)
        feed={}
        for name,shape,dtype in layout:
            length=int(np.prod(shape))*np.dtype(dtype).itemsize
            array=np.frombuffer(raw[offset:offset+length],dtype=dtype).reshape(shape)
            if array.tobytes()!=expected[name].tobytes():raise ValueError('native tensor bytes differ')
            feed[name]=array.tolist();offset+=length;elements+=array.size
        feeds.append(feed)
    if offset!=len(raw) or len(feeds)!=20 or rejected!=3:raise ValueError('native denominator differs')
    return feeds,elements,rejected


def run(source,capture_root,work,expected):
    plan=json.loads((work/'plan.json').read_bytes())
    if sha((work/'plan.json').read_bytes())!=expected:raise ValueError('plan commitment differs')
    observed=identity(source,capture_root)
    if any(plan[k]!=v for k,v in observed.items()):raise ValueError('implementation/source commitment differs')
    if plan['harness_sha256']!=sha(harness(source)) or plan['vectors_sha256']!=sha(support.projection_wire(vectors())):
        raise ValueError('diagnostic input commitment differs')
    save(work/'started.json',dict(owner_pid=os.getpid(),plan_sha256=expected))
    result=dict(status='failed',plan_sha256=expected,real_test=False,gold_evidence=False,production_edits=False)
    started=time.monotonic()
    try:
        counts=replay(capture_root,plan['source_capture_plan_sha256'],plan['source_capture_result_sha256'])
        source_path,binary=work/'native.rs',work/'native.exe'
        source_path.write_bytes(harness(source))
        compiler=plan['compiler']
        env=dict(os.environ,LIB=';'.join(compiler['library_roots']),TEMP=str(work),TMP=str(work))
        _,compiled=support.owned_command([compiler['rustc'],'--edition=2021','-A','dead_code','-Copt-level=1',
            '-Clinker='+compiler['linker'],'-Clink-arg=/Brepro',str(source_path),'-o',str(binary)],work,'compile',env=env)
        raw,projected=support.owned_command([str(binary)],work,'projection',support.projection_wire(vectors()),env)
        feeds,elements,rejected=compare(raw,vectors())
        artifacts=dict(weights=(source/support.SOURCE_PATHS[7]).read_bytes(),tokenizer=canonical_json_bytes(current.TOKENIZER),
                       features=canonical_json_bytes(current.FEATURES),gate=b'{}')
        limits=dict(startup_seconds=15.,request_seconds=.4,model_seconds=60.,shutdown_seconds=2.)
        python=execute_model([dict(candidates=row) for row in vectors()[:20]],artifacts,
            Adapter(current.native_current_factory,current.validate_current),6,limits,deadline=time.monotonic()+90)
        reference=execute_model([dict(feed=feed) for feed in feeds],artifacts,
            Adapter(reference_factory,current.validate_current),6,limits,deadline=time.monotonic()+90)
        if not python['complete'] or not reference['complete'] or python['scores']!=reference['scores']:
            raise ValueError('CPU score parity failed')
        result.update(status='passed',capture_replay=counts,projection_cases=23,rejected_candidate_counts=rejected,
            tensor_scalar_elements=elements,tensor_byte_equal=True,model_sha256=current.MODEL_SHA256,
            actual_model_requests=40,output_scores_compared=120,cpu_score_equal=True,binary_sha256=sha(binary.read_bytes()),
            processes=[compiled,projected,python['process'],reference['process']],
            native_execution='extracted_native_projection_with_test_backend; no live native ONNX worker')
    finally:
        result['elapsed_seconds']=round(time.monotonic()-started,3)
        save(work/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=('prepare','run'))
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--capture-root',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--plan-sha256')
    args=parser.parse_args()
    source,capture,work=(p.resolve() for p in (args.source_root,args.capture_root,args.work_root))
    result=(prepare(source,capture,work) if args.stage=='prepare' else run(source,capture,work,args.plan_sha256))
    print(json.dumps({k:v for k,v in result.items() if k in {'status','plan_sha256','capture_replay','projection_cases','actual_model_requests'}}))


if __name__=='__main__':main()
