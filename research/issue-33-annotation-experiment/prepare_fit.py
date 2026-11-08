"""Verify ready inputs and freeze all training and evaluation conditions before fitting."""
from collections import defaultdict
import io
import json
from pathlib import Path
import sys

from sakura_rerank.data.contracts import canonical_json_hash
from experiment_common import ROOT,HERE,TRAIN_CACHE,PREPARATION_ROOT,EXECUTION_PLAN,read,sha,save,rows,preparation
from candidates import bound_inputs,completed_snapshots
from numeric_verifier import verify_saved
from experiment_fit_contract import BINDING,MODEL_CODE,load_training,reference


def run():
    import numpy as np
    import torch
    plan=preparation.authenticate()
    candidate=read(ROOT/'candidate-report.json');cohort=read(ROOT/'cohort.json')
    if candidate['status']!='ready' or cohort['status']!='ready' or candidate['main_rows']<500:
        raise ValueError('ready_independent_research_inputs_required')
    bound,targets,identity,snapshots,new=bound_inputs(candidate['binding_commit'])
    execution=read(ROOT/'candidate-execution.json')
    if sha(ROOT/'candidate-execution.json')!=candidate['execution_sha256'] or execution['not_attempted'] or execution['stop_reason']:
        raise ValueError('all_candidate_terminals_required')
    snapshots.update(completed_snapshots(new,execution,identity))
    cache=ROOT/'evaluation-cache'
    if sha(cache/'arrays.npz')!=candidate['arrays_sha256'] or sha(cache/'metadata.json')!=candidate['metadata_sha256']:
        raise ValueError('evaluation_cache_changed')
    with np.load(io.BytesIO((cache/'arrays.npz').read_bytes()),allow_pickle=False) as saved:
        arrays={key:np.array(saved[key]) for key in saved.files}
    numeric=verify_saved(targets,snapshots,arrays)
    metadata=read(cache/'metadata.json')
    if [r['stable_id'] for r in targets]!=[r['stable_id'] for r in metadata]:
        raise ValueError('evaluation_target_order_changed')
    for row,meta in zip(targets,metadata):
        snapshot=snapshots.get(row['candidate_request_id'])
        candidates=[] if snapshot is None else snapshot['candidate_snapshots']['training_top32']['candidates']
        expected={str(k):any(c['surface']==row['target'] for c in candidates[:k]) for k in (1,5,6,10,32)}
        if expected!=meta['source_exact_presence']:
            raise ValueError('independent_candidate_presence_differs')
    groups=defaultdict(list);strata=defaultdict(list)
    for i,row in enumerate(targets):
        if 'contrast' in row['roles']:groups[row['contrast_group']].append(i)
        length=len(row['left_context'])
        strata[('main' in row['roles'],0 if length<16 else 1 if length<32 else 2)].append(i)
    supported={group for group,indexes in groups.items() if all(metadata[i]['source_exact_presence']['6'] for i in indexes)}
    shuffle=list(range(len(targets)));singletons=0
    for indexes in strata.values():
        ordered=sorted(indexes,key=lambda i:canonical_json_hash([20261105,'annotation-shuffle',targets[i]['stable_id']]))
        if len(ordered)==1:singletons+=1
        for i,j in zip(ordered,ordered[1:]+ordered[:1]):shuffle[i]=j
    if sorted(shuffle)!=list(range(len(targets))):raise ValueError('fixed_shuffle_not_bijective')
    conditions=dict(contexts=['intact','empty','shuffled'],shuffle=shuffle,singleton_shuffle_rows=singletons,
        populations=dict(main=[i for i,r in enumerate(targets) if 'main' in r['roles']],
            contrast_all=[i for i,r in enumerate(targets) if 'contrast' in r['roles']],
            contrast_supported=[i for i,r in enumerate(targets) if r['contrast_group'] in supported]),
        target_order_sha256=canonical_json_hash([r['stable_id'] for r in targets]),gate_margin=1.7,
        inference_backend='CPU PyTorch float32, one thread',source_form_only=True)
    save(ROOT/'conditions.json',conditions)
    numeric_proof=read(PREPARATION_ROOT/'numeric-r2/report.json')
    manifest=read(TRAIN_CACHE/'manifest.json')
    if numeric_proof['status']!='passed' or numeric_proof['cache_manifest_sha256']!=sha(TRAIN_CACHE/'manifest.json'):
        raise ValueError('training_numeric_proof_missing')
    training_paths=[TRAIN_CACHE/name for name in ('arrays.npz','row-receipts.jsonl','cohort-indices.json','manifest.json')]
    for name,digest in manifest['artifacts'].items():
        if sha(TRAIN_CACHE/name)!=digest:raise ValueError('training_cache_changed')
    training_paths.append(Path(plan['training']['initial_checkpoint']))
    if sha(plan['training']['initial_checkpoint'])!=plan['training']['initial_checkpoint_sha256']:
        raise ValueError('fixed_initial_checkpoint_changed')
    evaluation_paths=[ROOT/name for name in ('evaluation-cache/arrays.npz','evaluation-cache/metadata.json',
        'conditions.json','forward-targets.jsonl.gz','candidate-report.json','cohort.json','preparation.json')]
    code=[HERE/name for name in ('train_models.py','experiment_fit_contract.py','experiment_common.py','prepare_fit.py')]
    code += [MODEL_CODE,Path('research/issue-21-retrain/run.py'),Path('src/sakura_rerank/research_tiny.py'),
             Path('src/sakura_rerank/data/consumed_numeric.py')]
    environment=dict(python=sys.version.split()[0],torch=torch.__version__,numpy=np.__version__)
    if environment!=dict(python='3.13.13',torch='2.12.1+cu130',numpy='2.3.5'):
        raise ValueError('fixed_fit_environment_changed')
    if sha(MODEL_CODE)!='d0e24a57ccf9d5a1aa5fc3c9de0b3ff4ef8124bd15c126fc47c9c3bfbf55216d':
        raise ValueError('fixed_c2_harness_changed')
    result=dict(kind='paired_annotation_fit_binding',purpose='paired_source_reconstruction_fit',
        plan_path=preparation.PLAN.as_posix(),plan_commit=preparation.PLAN_COMMIT,plan_sha256=sha(preparation.PLAN),
        execution_plan_sha256=sha(EXECUTION_PLAN),environment=environment,
        training_artifacts={p.as_posix():sha(p) for p in training_paths},
        evaluation_artifacts={p.as_posix():sha(p) for p in evaluation_paths},code={p.as_posix():sha(p) for p in code},
        training_numeric_proof_sha256=sha(PREPARATION_ROOT/'numeric-r2/report.json'),
        candidate_binding_sha256=sha(HERE/'candidate-binding-v1.json'),candidate_reverification=numeric,
        main_rows=len(conditions['populations']['main']),population_sizes={k:len(v) for k,v in conditions['populations'].items()},
        training_rows_per_arm=50000,training_source_counts=dict(jawiki=25000,aozora=25000),
        fits=6,tf32=False,amp=False,evaluation_arrays_in_training=False,all_fits_sealed_before_scoring=True,
        original_label_admissions=0,gold_certified=False,final_test_used=False,safety_threshold=.0025)
    train_arrays,indices,_=load_training(result)
    harness=reference(result)
    model=harness.build_model('C2')
    result['train_loader_preflight']=dict(rows=len(train_arrays['gold']),rows_per_arm={k:len(v) for k,v in indices.items()},
        model_parameters=sum(p.numel() for p in model.parameters()),model_predictions=0,optimizer_updates=0)
    save(BINDING,result);save(ROOT/'fit-binding.json',result)
    return {key:result[key] for key in ('fits','training_rows_per_arm','population_sizes','candidate_reverification')}


if __name__=='__main__':
    print(json.dumps(run()))
