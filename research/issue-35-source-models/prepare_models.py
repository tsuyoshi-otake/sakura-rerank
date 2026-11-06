"""Bind fixed models, authenticate source snapshots, and prepare label-free arrays."""
import argparse
from collections import Counter
import importlib.metadata
import json
import platform
import subprocess
import sys

import numpy as np

from sakura_rerank.source_model_inputs import INPUT_NAMES,encode_snapshot
from model35_common import HERE,PLAN,ROOT,SOURCE,authenticate,read,save,sha


def plan():
    v1=read('manifests/sakura-rerank-tiny-v1-research-prototype.json')
    r2=read('manifests/sakura-rerank-tiny-v1-research-r2.json')
    student_report=read('reports/issue-29-distill-gate.json')
    export_path='data/generated/issue-29-distill-gate/export.json'
    if sha(export_path)!=student_report['artifacts']['export_sha256']:raise ValueError('source_models_student_export_binding')
    student=read(export_path)
    gate_r2=read('reports/issue-25-confidence-gate.json')['final_selection']['20260814']['main']['gate']
    gate_student=student_report['final_selection']['main']['gate']
    if (gate_r2['score'],gate_r2['tau'],gate_student['score'],gate_student['tau'])!=('L',2.9,'L',1.7):
        raise ValueError('source_models_published_gates_differ')
    models=[]
    for name,directory,item,width,tau in (
        ('v1','data/generated/sakura-rerank-tiny-v1-research',v1['exports']['fp32'],6,None),
        ('r2','data/generated/sakura-rerank-tiny-r2-research',r2['exports']['fp32'],7,2.9),
        ('issue29','data/generated/issue-29-distill-gate',student['onnx']['fp32'],7,1.7)):
        path=directory+'/'+item['file']
        if sha(path)!=item['sha256']:raise ValueError('source_models_manifest_binary_mismatch')
        models.append(dict(name=name,path=path,sha256=item['sha256'],feature_dim=width,published_gate_tau=tau))
    current=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    if subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30):raise ValueError('source_models_input_checkout_not_clean')
    paths=[SOURCE/name for name in ('consumed-slots.json','preparation.json','requests.json','request-ledger.json',
        'native-report.json','source-relations-v2.json','source-metrics-v2.json','source-exposure-report.json','verification.json')]
    paths += ['reports/issue-35-source-consumption-v1.json','manifests/sakura-rerank-tiny-v1-research-prototype.json',
        'manifests/sakura-rerank-tiny-v1-research-r2.json','reports/issue-25-confidence-gate.json','reports/issue-29-distill-gate.json',export_path,
        'research/issue-35-source-consumption/native-binding-v1.json','research/issue-35-source-consumption/source-exposure-binding-v1.json']
    code=list(HERE.glob('*.py'))+['src/sakura_rerank/source_model_inputs.py','src/sakura_rerank/research_tiny.py',
        'src/sakura_rerank/research_tiny_r2.py','src/sakura_rerank/evaluation_metrics.py','src/sakura_rerank/evaluation_statistics.py',
        'tests/test_source_model_inputs.py']
    spec=dict(kind='fixed_source_model_comparison_plan_v1',issues=[35,33,32],parent_issue=1,
        source_commit='4a50a2c2326f7ab6b8a68415f9d687af277b4b05',source_slots=1000,native_requests=1230,
        label_task='Original source reconstruction; not independent IME correctness or Gold.',
        primary_population='All native-measurable source parts; all1000 slots remain in the report with unmeasured statuses.',
        context='Empty observed session context; never synthesize host/source prefix context.',
        prefix_contract='Keep legacy first32 reading/surface characters; report overflow and encoded-text collisions, no exclusion by length/oracle.',
        source_history='Final explicit-source-exposure relation v2, keeping original report unchanged.',models=models,
        variants=['v1-ungated','r2-ungated','r2-published-gate','issue29-ungated','issue29-published-gate'],
        thresholds='Published strict float64(score_top-score_local)>tau; no selection or adjustment here.',
        slices=['all','isolated_hypothesis','historically_related','prefix_complete','prefix_truncated','named_editor','no_editor'],
        comparisons=[['v1-ungated','baseline'],['r2-ungated','baseline'],['r2-published-gate','baseline'],
            ['issue29-ungated','baseline'],['issue29-published-gate','baseline'],['r2-ungated','v1-ungated'],
            ['issue29-ungated','v1-ungated'],['issue29-ungated','r2-ungated'],['issue29-published-gate','r2-published-gate']],
        statistics=dict(bootstrap_replicates=10000,seed=20261106,scope='Conditional source-reconstruction intervals on recorded components; no independent Gold/safety certification.'),
        execution=dict(provider='CPUExecutionProvider',gpu_disabled=True,batch=1,intra_op_threads=1,inter_op_threads=1,
            maximum_requests=4000,maximum_input_bytes=64*1024*1024,stage_timeout_seconds=900,automatic_retries=0,
            warmup_runs=200,benchmark_runs=10000,benchmark_scope='session.run only with prebuilt fixed-source inputs; not end-to-end IME latency'),
        current_sakura_input_head=current,current_sakura_input_clean=True,
        permission='Preparation only until separate committed exact-input inference binding; no prior source admission promotion.',
        forbidden=dict(fits=True,threshold_selection=True,gold_admission=True,calibration_admission=True,final_test=True,
            native_regeneration=True,production_changes=True,distribution=True),
        unchanged=read('research/issue-35-source-consumption/plan-v1.json')['unchanged'],
        environment=dict(python=sys.version,platform=platform.platform(),packages={p:importlib.metadata.version(p) for p in ('numpy','onnxruntime','onnx')},new_dependencies=0),
        inputs={str(p).replace('\\','/'):sha(p) for p in paths},code={str(p).replace('\\','/'):sha(p) for p in code})
    save(PLAN,spec)
    return dict(stage='planned',model_artifacts=len(models),plan_sha256=sha(PLAN),model_calls=0)


def authenticated_snapshots():
    sys.path.insert(0,'research/issue-35-source-consumption')
    try:
        from native_consumption import bound_inputs,checked_result
        from consume35_common import load_script
        report=read(SOURCE/'native-report.json')
        _,_,identity=bound_inputs(report['binding_commit'])
        validator=load_script('source_models_saved_native_validator','research/issue-31-quality/run_reference_probe.py')
        requests=read(SOURCE/'requests.json')['requests'];ledger=read(SOURCE/'request-ledger.json')['rows']
        result={};outcomes=Counter()
        for request,event in zip(requests,ledger,strict=True):
            status,record=checked_result(SOURCE/'candidates'/f"request-{event['index']:04d}",request,event['terminal'],identity,validator)
            if status['status']!=event['status']:raise ValueError('source_models_native_terminal_changed')
            outcomes[status['status']]+=1
            if record is not None:result[request['stable_id']]=record
        if dict(outcomes)!=report['outcomes']:raise ValueError('source_models_native_population_changed')
        return result
    finally:
        sys.path.pop(0)


def prepare(commit):
    spec=authenticate(commit)
    save(ROOT/'preparation-reservation.json',dict(plan_commit=commit,source_slots=1000,model_calls=0))
    snapshots=authenticated_snapshots();identities=sorted(snapshots);arrays={};profiles={}
    for index,key in enumerate(identities):
        values,profile=encode_snapshot(snapshots[key]);profiles[key]=profile
        if index==0:arrays={name:np.zeros((len(identities),*value.shape[1:]),dtype=value.dtype) for name,value in values.items()}
        for name in INPUT_NAMES:arrays[name][index]=values[name][0]
    if not len(identities)<=spec['execution']['maximum_requests'] or sum(a.nbytes for a in arrays.values())>spec['execution']['maximum_input_bytes']:
        raise ValueError('source_models_numeric_bound')
    with (ROOT/'model-inputs.npz').open('xb') as stream:np.savez(stream,**arrays)
    save(ROOT/'input-index.json',dict(request_ids=identities,profiles=profiles))
    observed=read(SOURCE/'consumed-slots.json')['rows'];relations=read(SOURCE/'source-relations-v2.json')
    cases=[];slots=[];slot_counts=Counter();indexes={key:i for i,key in enumerate(identities)}
    for row in observed:
        state='source_unresolved' if not row['inputs'] else 'native_unmeasured' if any(p['request_id'] not in snapshots for p in row['inputs']) else 'native_measured'
        slot_counts[state]+=1
        slots.append(dict(slot=row['slot'],status=state,stratum=row['stratum'],input_ids=[p['stable_id'] for p in row['inputs']]))
        for item in row['inputs']:
            if item['request_id'] not in snapshots:continue
            snapshot=snapshots[item['request_id']]
            cases.append(dict(stable_id=item['stable_id'],slot=row['slot'],request_id=item['request_id'],tensor_index=indexes[item['request_id']],
                component=relations['components'][item['stable_id']],historically_related=item['stable_id'] in relations['excluded'],stratum=row['stratum'],
                target=item['target'],candidates=[c['surface'] for c in snapshot['candidate_snapshots']['training_top32']['candidates']],
                prefix_truncated=profiles[item['request_id']]['any_truncation']))
    # Only the evaluator opens this sidecar after every model output is sealed.
    save(ROOT/'source-cases.json',dict(cases=cases,slots=slots,source_slots=1000,slot_statuses=dict(slot_counts)))
    report=dict(kind='fixed_source_model_preparation',status='prepared_not_inferred',plan_commit=commit,
        source_slots=1000,slot_statuses=dict(slot_counts),source_part_cases=len(cases),unique_numeric_inputs=len(identities),
        historical_part_cases=sum(c['historically_related'] for c in cases),
        profiles=dict(requests_with_reading_truncation=sum(p['reading_truncated'] for p in profiles.values()),
            requests_with_any_truncation=sum(p['any_truncation'] for p in profiles.values()),
            truncated_candidate_surfaces=sum(p['surface_truncations'] for p in profiles.values()),
            encoded_surface_collision_pairs=sum(p['encoded_surface_collision_pairs'] for p in profiles.values()),
            same_prefix_collision_pairs=sum(p['same_prefix_collision_pairs'] for p in profiles.values()),
            hash_collision_pairs=sum(p['hash_collision_pairs'] for p in profiles.values())),
        input_tensor_sha256=sha(ROOT/'model-inputs.npz'),input_index_sha256=sha(ROOT/'input-index.json'),
        source_cases_sha256=sha(ROOT/'source-cases.json'),input_array_bytes=sum(a.nbytes for a in arrays.values()),
        model_input_fields=list(INPUT_NAMES),label_fields_in_model_feed=0,model_calls=0,gold_admission=0,final_test=False)
    save(ROOT/'preparation.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','prepare'));parser.add_argument('--commit')
    args=parser.parse_args();print(json.dumps(plan() if args.stage=='plan' else prepare(args.commit)))
