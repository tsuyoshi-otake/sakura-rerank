"""Authenticate native paths and compare frozen v1/r2/#29 feeds and scores."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from sakura_rerank import native_paths as paths,native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_worker import Adapter,execute_model,gru_factory,runtime_identity,validate_gru
from sakura_rerank.native_path_inputs import encode_request,legacy_feature_candidates,native_gru_factory
from sakura_rerank.source_model_inputs import encode_snapshot,model_feed

ROOT=Path(__file__).resolve().parents[2]
NATIVE_PLAN='b06aa91e78dc4702cbf8be94fbd77a54c868eeb9ad20388c23af781bc12de5ee'
NATIVE_RESULT='16c152031ada945219cafad195b3a864d0ab7776a6f758f1477d37ab95991e4d'
OLD_CAPTURE='fecde9f3ecd05dca47bcf2f0139074ce31e25dccbb2717a002b55f2a6d5d9cb4'
MODELS=[dict(name='v1',width=6,path='data/generated/sakura-rerank-tiny-v1-research/sakura-rerank-tiny-v1-fp32.onnx',
             sha256='b3fe1e0aa7229edfd0760162d648f10328b0d75224a9cd49f2ba986b7db2ccbd'),
        dict(name='r2',width=7,path='data/generated/sakura-rerank-tiny-r2-research/sakura-rerank-tiny-v1-research-r2-fp32.onnx',
             sha256='96d7694cc3759465a95841aa8d4cd62757f302fc13388ca9c38751c2a9ae5c64'),
        dict(name='issue29',width=7,path='data/generated/issue-29-distill-gate/student-fp32.onnx',
             sha256='a58ebea1257cdc2507b02acb8b7e958181f05577fb629d7928eb1f02fe078686')]


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save(path,value):
    with path.open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def captured(root):
    return paths.verify_capture((root/'plan.json').read_bytes(),(root/'result.json').read_bytes(),(root/'capture.jsonl').read_bytes(),
        expected_plan_sha256=NATIVE_PLAN,expected_result_sha256=NATIVE_RESULT)


def identities(capture_root,old_capture):
    for model in MODELS:
        if sha((ROOT/model['path']).read_bytes())!=model['sha256']:raise ValueError('fixed model bytes changed')
    if sha(old_capture.read_bytes())!=OLD_CAPTURE:raise ValueError('old control capture changed')
    return dict(runtime=runtime_identity(),implementation_sha256=sha(Path(__file__).read_bytes()),models=MODELS,
                producer_plan_sha256=sha((capture_root/'plan.json').read_bytes()),
                producer_result_sha256=sha((capture_root/'result.json').read_bytes()),
                capture_sha256=sha((capture_root/'capture.jsonl').read_bytes()),old_capture_sha256=OLD_CAPTURE)


def prepare(capture_root,old_capture,work):
    if work.exists() or (Path.home()/'tmp').resolve() not in work.parents:raise ValueError('fresh private root required')
    values=captured(capture_root)
    selected=[v['snapshot'] for v in values if not v['baseline_run'] and v['snapshot'] is not None]
    requests=[native.population_input(v) for v in selected]
    for request,snapshot in zip(requests,selected,strict=True):request['candidates']=request['candidates'][:min(6,snapshot['product_state']['direct_count'])]
    value=identities(capture_root,old_capture)
    value.update(kind='native_path_model_parity_plan',version=1,requests=len(requests),request_sha256=sha(canonical_json_bytes(requests)),
                 selection='one response-arm snapshot per predefined condition; paired controls retained in audit',
                 limits=dict(startup_seconds=15.,request_seconds=.4,model_seconds=60.,shutdown_seconds=2.))
    work.mkdir();save(work/'plan.json',value)
    print(json.dumps(dict(status='prepared',plan_sha256=sha((work/'plan.json').read_bytes()),requests=len(requests))))


def run(capture_root,old_capture,work,expected):
    if sha((work/'plan.json').read_bytes())!=expected:raise ValueError('parity plan changed')
    plan=json.loads((work/'plan.json').read_bytes())
    if any(plan[k]!=v for k,v in identities(capture_root,old_capture).items()):raise ValueError('parity identity changed')
    save(work/'started.json',dict(owner_pid=os.getpid(),plan_sha256=expected))
    started=time.monotonic();result=dict(status='failed',plan_sha256=expected,models=[],real_test=False,gold_evidence=False,
                                       training=False,production_edits=False)
    try:
        events=[json.loads(v) for v in (capture_root/'capture.jsonl').read_bytes().splitlines()]
        old=[json.loads(v) for v in old_capture.read_bytes().splitlines()]
        if [paths.base_event(v) for v in events[:len(old)]]!=old:raise ValueError('native instrumentation changed original control behavior')
        values=captured(capture_root)
        snapshots=[v['snapshot'] for v in values if v['snapshot'] is not None]
        selected=[v['snapshot'] for v in values if not v['baseline_run'] and v['snapshot'] is not None]
        requests=[]
        for snapshot in selected:
            request=native.population_input(snapshot)
            request['candidates']=request['candidates'][:min(6,snapshot['product_state']['direct_count'])]
            requests.append(request)
        if len(requests)!=plan['requests'] or sha(canonical_json_bytes(requests))!=plan['request_sha256']:
            raise ValueError('parity request population changed')
        legacy=[dict(r,candidates=legacy_feature_candidates(r['candidates'])) for r in requests]
        scalar_elements=0
        for model in MODELS:
            width=model['width']
            for request,old_request in zip(requests,legacy,strict=True):
                candidates=old_request['candidates']
                arrays,_=encode_snapshot(dict(reading=request['reading'],candidate_snapshots=dict(
                    production_top6=dict(candidates=candidates),training_top32=dict(candidates=candidates))))
                actual,reference=encode_request(request,width),model_feed(arrays,0,width)
                for key in actual:
                    if actual[key].tobytes()!=reference[key].tobytes():raise ValueError('frozen feature bytes differ')
                    scalar_elements+=actual[key].size
            artifacts=dict(weights=(ROOT/model['path']).read_bytes(),gate=b'{}',
                tokenizer=canonical_json_bytes(dict(kind='tiny_character_hash',version=1,vocab_size=13312,context_length=64,
                    reading_length=32,surface_length=32,truncation='prefix')),
                features=canonical_json_bytes(dict(kind='tiny_candidate_features',version=1,width=width,cost_gap_scale=1000 if width==7 else None)))
            current=execute_model(requests,artifacts,Adapter(native_gru_factory,validate_gru),width,plan['limits'],deadline=time.monotonic()+90)
            reference=execute_model(legacy,artifacts,Adapter(gru_factory,validate_gru),width,plan['limits'],deadline=time.monotonic()+90)
            if not current['complete'] or not reference['complete'] or current['scores']!=reference['scores']:
                raise ValueError('fixed model score parity failed')
            result['models'].append(dict(name=model['name'],sha256=model['sha256'],feature_width=width,
                requests_each=len(requests),scores_compared=len(requests)*6,score_sha256=sha(canonical_json_bytes(current['scores'])),
                exact_score_parity=True,processes=[current['process'],reference['process']]))
        rows=[c for snapshot in snapshots for c in snapshot['candidates']]
        result.update(status='passed',events=len(values),snapshots=len(snapshots),no_conversion_events=len(values)-len(snapshots),
            candidates=len(rows),raw_edges=sum(len(c['path']['segments']) for c in rows),
            fused_candidates=sum(c['display_segment_count']<len(c['path']['segments']) for c in rows),
            system_path_nonexact_evidence=sum(all(s['source_category']=='system_dictionary' for s in c['path']['segments']) and c['evidence_tag']!=1 for c in rows),
            original_control_events=len(old),original_control_equal=True,projection_requests=len(requests),
            tensor_scalar_elements=scalar_elements,tensor_bytes_equal=True,actual_model_requests=len(requests)*len(MODELS)*2,
            native_worker_benchmark=False,accuracy_evidence=False)
    finally:
        result['elapsed_seconds']=round(time.monotonic()-started,3);save(work/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k in {'status','candidates','raw_edges','fused_candidates','system_path_nonexact_evidence','tensor_scalar_elements','actual_model_requests'}}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','run'))
    parser.add_argument('--capture-root',type=Path,required=True);parser.add_argument('--old-capture',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True);parser.add_argument('--plan-sha256')
    args=parser.parse_args();capture,old,work=(p.resolve() for p in (args.capture_root,args.old_capture,args.work_root))
    if args.stage=='prepare':prepare(capture,old,work)
    else:run(capture,old,work,args.plan_sha256)
