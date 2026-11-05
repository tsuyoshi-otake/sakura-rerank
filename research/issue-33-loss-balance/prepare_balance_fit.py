"""Authenticate fresh research inputs and train-derived weights before fit permission."""
from collections import defaultdict
import io
import json
import os
from pathlib import Path
import sys

from sakura_rerank.data.contracts import canonical_json_hash
from balance_common import ROOT,HERE,PLAN,authenticate,previous,read,sha,save,rows
from balance_candidates import bound_inputs,completed_snapshots,verify_saved
from balance_fit_contract import BINDING,PLAN_COMMIT,MODEL_CODE,TRAIN_CACHE,load_training,reference
from balanced_loss import source_class_weights,weighted_c2_loss


def run():
    import numpy as np
    import torch
    plan=authenticate(PLAN_COMMIT)
    loss_tests=read(ROOT/'loss-unit-tests.json')
    if not loss_tests['successful'] or loss_tests['tests']<7 or loss_tests['skipped']:
        raise ValueError('balance_loss_contract_tests_required')
    candidate=read(ROOT/'candidate-report.json');cohort=read(ROOT/'cohort.json')
    if candidate['status']!='ready' or cohort['status']!='ready' or candidate['main_rows']<500:
        raise ValueError('balance_ready_research_inputs_required')
    _,targets,identity,snapshots,new=bound_inputs(candidate['binding_commit'])
    execution=read(ROOT/'candidate-execution.json')
    if sha(ROOT/'candidate-execution.json')!=candidate['execution_sha256'] or execution['not_attempted'] or execution['stop_reason']:
        raise ValueError('balance_all_candidate_terminals_required')
    snapshots.update(completed_snapshots(new,execution,identity))
    cache=ROOT/'evaluation-cache'
    if sha(cache/'arrays.npz')!=candidate['arrays_sha256'] or sha(cache/'metadata.json')!=candidate['metadata_sha256']:
        raise ValueError('balance_evaluation_cache_changed')
    with np.load(io.BytesIO((cache/'arrays.npz').read_bytes()),allow_pickle=False) as saved:
        arrays={key:np.array(saved[key]) for key in saved.files}
    numeric=verify_saved(targets,snapshots,arrays)
    metadata=read(cache/'metadata.json')
    if [r['stable_id'] for r in targets]!=[r['stable_id'] for r in metadata]:
        raise ValueError('balance_evaluation_order_changed')
    for row,meta in zip(targets,metadata):
        snapshot=snapshots.get(row['candidate_request_id'])
        candidates=[] if snapshot is None else snapshot['candidate_snapshots']['training_top32']['candidates']
        expected={str(k):any(c['surface']==row['target'] for c in candidates[:k]) for k in (1,5,6,10,32)}
        if expected!=meta['source_exact_presence']:raise ValueError('balance_candidate_presence_differs')
    groups=defaultdict(list);strata=defaultdict(list)
    for i,row in enumerate(targets):
        if 'contrast' in row['roles']:groups[row['contrast_group']].append(i)
        length=len(row['left_context'])
        strata[('main' in row['roles'],0 if length<16 else 1 if length<32 else 2)].append(i)
    supported={group for group,indexes in groups.items() if all(metadata[i]['source_exact_presence']['6'] for i in indexes)}
    shuffle=list(range(len(targets)));singletons=0
    for indexes in strata.values():
        ordered=sorted(indexes,key=lambda i:canonical_json_hash([plan['seed'],plan['shuffle_domain'],targets[i]['stable_id']]))
        if len(ordered)==1:singletons+=1
        for i,j in zip(ordered,ordered[1:]+ordered[:1]):shuffle[i]=j
    if sorted(shuffle)!=list(range(len(targets))):raise ValueError('balance_shuffle_not_bijective')
    conditions=dict(contexts=plan['evaluation']['contexts'],shuffle=shuffle,singleton_shuffle_rows=singletons,
        populations=dict(main=[i for i,r in enumerate(targets) if 'main' in r['roles']],
            contrast_all=[i for i,r in enumerate(targets) if 'contrast' in r['roles']],
            contrast_supported=[i for i,r in enumerate(targets) if r['contrast_group'] in supported]),
        target_order_sha256=canonical_json_hash([r['stable_id'] for r in targets]),gate_margin=1.7,
        inference_backend='CPU PyTorch float32, one thread',source_form_only=True)
    proof_path=previous.PREPARATION_ROOT/'numeric-r2/report.json'
    numeric_proof=read(proof_path);manifest=read(TRAIN_CACHE/'manifest.json')
    if numeric_proof['status']!='passed' or numeric_proof['cache_manifest_sha256']!=sha(TRAIN_CACHE/'manifest.json'):
        raise ValueError('balance_training_numeric_proof_missing')
    for name,digest in manifest['artifacts'].items():
        if sha(TRAIN_CACHE/name)!=digest:raise ValueError('balance_training_cache_changed')
    training_paths=[TRAIN_CACHE/name for name in ('arrays.npz','row-receipts.jsonl','cohort-indices.json','manifest.json')]
    training_paths.append(Path(plan['training']['initial_checkpoint']))
    code=[HERE/name for name in ('train_balance.py','balance_fit_contract.py','balance_common.py','prepare_balance_fit.py','balanced_loss.py')]
    code += [MODEL_CODE,Path('research/issue-21-retrain/run.py'),Path('src/sakura_rerank/research_tiny.py'),
        Path('src/sakura_rerank/data/consumed_numeric.py'),Path('research/issue-33-annotation-experiment/experiment_fit_contract.py')]
    environment=dict(python=sys.version.split()[0],torch=torch.__version__,numpy=np.__version__)
    if environment!=dict(python='3.13.13',torch='2.12.1+cu130',numpy='2.3.5'):
        raise ValueError('balance_fixed_fit_environment_changed')
    result=dict(kind='loss_balance_fit_binding',purpose='fixed_loss_contribution_fit',
        plan_path=PLAN.as_posix(),plan_commit=PLAN_COMMIT,plan_sha256=sha(PLAN),environment=environment,
        training_artifacts={p.as_posix():sha(p) for p in training_paths},code={p.as_posix():sha(p) for p in code},
        training_numeric_proof_sha256=sha(proof_path),candidate_binding_sha256=sha(HERE/'candidate-binding-v1.json'),
        candidate_reverification=numeric,loss_test_receipt_sha256=sha(ROOT/'loss-unit-tests.json'),
        main_rows=len(conditions['populations']['main']),
        population_sizes={k:len(v) for k,v in conditions['populations'].items()},
        training_rows=50000,training_source_counts=dict(jawiki=25000,aozora=25000),fits=3,
        tf32=False,amp=False,evaluation_arrays_in_training=False,all_fits_sealed_before_scoring=True,
        original_label_admissions=0,gold_certified=False,final_test_used=False,safety_threshold=.0025)
    train_arrays,indices,_=load_training(result)
    weights,statistics=source_class_weights(train_arrays['correct_mask'][:,0],indices)
    specified=plan['training']['weights']
    for label in ('correct','error'):
        ratio=specified['annotation_aozora_'+label]
        if (statistics['dictionary_aozora_'+label]!=ratio['numerator']
                or statistics['annotation_aozora_'+label]!=ratio['denominator']):
            raise ValueError('balance_frozen_weight_counts_differ')
    if (not statistics['common_wikipedia_weights_unchanged']
            or abs(statistics['annotation_total_weight_mass']-50000)>.01):
        raise ValueError('balance_expected_weight_mass_differs')
    harness=reference(result);model=harness.build_model('C2')
    # Direct all-ones loss AND gradient equivalence against authenticated C2.
    generator=torch.Generator().manual_seed(20261106)
    scores=torch.randn(7,6,generator=generator,requires_grad=True)
    mask=torch.ones(7,6,dtype=torch.bool);gold=torch.arange(7)%6
    original=harness.loss_fn(scores,gold,mask,'C2')
    weighted=weighted_c2_loss(scores,gold,mask,torch.ones(7))
    first=torch.autograd.grad(original,scores,retain_graph=True)[0]
    second=torch.autograd.grad(weighted,scores)[0]
    if not torch.equal(original,weighted) or not torch.equal(first,second):
        raise ValueError('balance_unit_weight_loss_or_gradient_changed')
    # Publish only after source, candidate, train and loss checks have all passed.
    save(ROOT/'conditions.json',conditions)
    weight_path=ROOT/'training-weights.npy'
    with weight_path.open('xb') as stream:
        np.save(stream,weights,allow_pickle=False);stream.flush();os.fsync(stream.fileno())
    result['training_artifacts'][weight_path.as_posix()]=sha(weight_path)
    evaluation_paths=[ROOT/name for name in ('evaluation-cache/arrays.npz','evaluation-cache/metadata.json',
        'conditions.json','forward-targets.jsonl.gz','candidate-report.json','cohort.json','preparation.json')]
    result.update(evaluation_artifacts={p.as_posix():sha(p) for p in evaluation_paths},weight_derivation=statistics,
        train_loader_preflight=dict(rows=len(train_arrays['gold']),rows_per_arm={k:len(v) for k,v in indices.items()},
            model_parameters=sum(p.numel() for p in model.parameters()),model_predictions=0,optimizer_updates=0,
            unit_weight_loss_and_gradient_bit_equal=True))
    save(BINDING,result);save(ROOT/'fit-binding.json',result)
    return {key:result[key] for key in ('fits','training_rows','population_sizes','candidate_reverification','weight_derivation')}


if __name__=='__main__':
    print(json.dumps(run()))
