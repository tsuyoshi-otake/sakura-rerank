"""Freeze label-free projections and their complete component dependencies."""
import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS,tensor_hash,verify_chain
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.gate_oof import component_folds,score_exposure
from sakura_rerank.gate_proposal_inputs import project_inputs,projected_folds
from proposal_common import CACHE,HERE,LINEAGE,OOF,ROOT,authenticate,committed,guard_summary,input_arrays,install_read_guard,read,save,sha


def require(value,code):
    if not value:raise ValueError('proposal_'+code)


def plan():
    public=Path('reports/issue-34-selector-lineage-v1.json')
    report=json.loads(committed(public,'183fecdb0cadc1ca6e63d8806daffd9340099ffa'))
    require(report['verification']['status']=='passed' and report['audit']['source']['selected_rows']==75000,'lineage_evidence')
    model=dict(name='reference29',path='data/generated/issue-29-distill-gate/student-fp32.onnx',
        sha256=report['audit']['ancestry']['onnx_sha256'],checkpoint_sha256=report['audit']['ancestry']['checkpoint_sha256'],feature_dim=7)
    paths=[public,LINEAGE/'audit.json',LINEAGE/'verification.json',LINEAGE/'expanded-model-exposure.json',LINEAGE/'historical-numeric.json',
        OOF/'training-identities.json',OOF/'folds.json',OOF/'audit.json',OOF/'verification.json',
        'research/issue-33-loss-balance/evaluation-binding-v1.json']
    paths += [CACHE/name for name in ('manifest.json','arrays.npz','row-receipts.jsonl','cohort-indices.json')]
    code=list(HERE.glob('*.py'))+[Path(p) for p in ('src/sakura_rerank/gate_proposal_inputs.py','tests/test_gate_proposal_inputs.py','tests/test_gate_proposal_metrics.py',
        'src/sakura_rerank/gate_oof.py','src/sakura_rerank/data/consumed_numeric.py','src/sakura_rerank/data/contracts.py',
        'src/sakura_rerank/source_model_inputs.py','research/issue-33-annotation-experiment/experiment_fit_contract.py',
        'research/issue-33-annotation-experiment/experiment_common.py','research/issue-33-train-change-audit/change_metrics.py')]
    head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    require(not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'input_checkout')
    spec=dict(kind='fixed_cpu_gate_proposal_plan',issues=[34,33,32,35],parent_issue=1,
        previous_commit='183fecdb0cadc1ca6e63d8806daffd9340099ffa',model=model,
        inputs={str(p).replace('\\','/'):sha(p) for p in paths},code={p.as_posix():sha(p) for p in code},
        rows=75000,conditions=['source','empty'],input_fields=list(MODEL_FIELDS),
        context_policy='Source-prefix is synthetic, not observed session text. Empty replaces only context_ids and context_lengths with zeros. No right/document context.',
        fold_policy='Preserve all original union components, then join exact projected-input equality across the full75000-row union before restricting either50000-row arm. No row exclusions or random splits.',
        historical_input_policy='Compare each projected input to all14304 authenticated actual historical train/dev numeric inputs; propagate any match through the derived components. Do not infer that a counterfactual old empty-context input was actually fitted.',
        analysis_policy='After all CPU scores are sealed, decode only the bound training sidecars. Recount fixed ungated and published L>1.7 outcomes, input-label conflicts and empirical deterministic source-match ceilings. No threshold search or claim of independent Japanese accuracy.',
        cpu=dict(provider='CPUExecutionProvider',gpu_disabled=True,batch=1,intra_op_threads=1,inter_op_threads=1,
            warmup_per_condition=200,benchmark_per_condition=10000,quality_per_condition=75000,replay_per_condition=75000),
        limits=dict(rows=100000,input_bytes=268435456,stage_seconds=1800,retries=0,concurrency=1),
        environment=dict(python=sys.version.split()[0],numpy=np.__version__,onnxruntime='1.23.2',platform=platform.platform(),new_dependencies=0),
        sakura_input_head=head,sakura_input_clean=True,new_ranker_fits=0,new_gate_fits=0,fit_permission=False,threshold_selection=False,
        calibration=False,final_test=False,gold_admission=False,safety_limit=.0025,
        expected_effect='Create reproducible fixed-selector gate inputs and reveal projected equality/label-conflict limits before fitting.',
        expected_cost='150000 quality CPU calls plus150000 replay calls and20000 benchmark calls;1800-second deadline per stage. No downloads, native conversion or GPU fitting.')
    save(HERE/'plan-v1.json',spec);return dict(stage='planned',plan_sha256=sha(HERE/'plan-v1.json'))


def fold_summary(records,folds,positions):
    source=Counter(records[i]['group'] for i in positions)
    sizes=Counter(folds['row_component'][records[i]['row_key']] for i in positions)
    return dict(rows=len(positions),source_groups=dict(source),components=len(sizes),largest_component=max(sizes.values()),
        fold_sizes=folds['fold_sizes'],fold_group_counts=folds['fold_group_counts'],empty_folds=sum(n==0 for n in folds['fold_sizes']))


def execute(commit):
    start=time.monotonic();spec=authenticate(commit)
    save(ROOT/'preparation-reservation.json',dict(plan_commit=commit,labels_decoded=False,new_fits=0))
    guard=install_read_guard(spec['inputs']);terminal=dict(status='failed',plan_commit=commit)
    try:
        lineage=read(LINEAGE/'verification.json');history=read(LINEAGE/'audit.json');models=read(LINEAGE/'expanded-model-exposure.json')
        require(lineage['status']=='passed' and lineage['audit_sha256']==sha(LINEAGE/'audit.json')
            and lineage['expanded_models_sha256']==sha(LINEAGE/'expanded-model-exposure.json'),'verified_lineage_binding')
        require(history['ancestry']['checkpoint_sha256']==spec['model']['checkpoint_sha256'],'checkpoint_lineage')
        manifest=read(CACHE/'manifest.json');arrays=input_arrays(CACHE/'arrays.npz',spec['inputs'][(CACHE/'arrays.npz').as_posix()])
        require(manifest['training_eligible'] is False and manifest['independent_gold_eligible'] is False,'admission')
        ledger=verify_chain((CACHE/'row-receipts.jsonl').read_bytes(),75000,manifest['row_chain_head'])
        require(canonical_json_hash([r['origin']['stable_id'] for r in ledger])==manifest['source_order_sha256'],'source_order')
        identities=read(OOF/'training-identities.json');records=identities['rows'];base=read(OOF/'folds.json')['union'];indices=read(CACHE/'cohort-indices.json')
        require(len(records)==75000 and identities['indices']==indices,'metadata_population')
        for i,row in enumerate(ledger):require(tensor_hash(arrays,i,MODEL_FIELDS)==row['input_tensor_sha256']==records[i]['numeric_input_key'],'source_input_hash')
        historical=read(LINEAGE/'historical-numeric.json')
        old_inputs={role:{r['numeric'] for r in historical if r['split']==role} for role in ('train','dev')}
        results={};artifacts={}
        for condition in spec['conditions']:
            projected=project_inputs(arrays,condition);hashes=[tensor_hash(projected,i,MODEL_FIELDS) for i in range(75000)]
            folds=projected_folds(records,base['row_component'],hashes,5);arm_folds={}
            for arm,positions in indices.items():
                subset=[dict(records[i],component_key=folds['row_component'][records[i]['row_key']],numeric_input_key=hashes[i]) for i in positions]
                arm_folds[arm]=component_folds(subset,5)
            matched={role:{folds['row_component'][records[i]['row_key']] for i,h in enumerate(hashes) if h in values} for role,values in old_inputs.items()}
            condition_models={**models,spec['model']['checkpoint_sha256']:{**models[spec['model']['checkpoint_sha256']],
                'fit_components':sorted(matched['train']),'selection_components':sorted(matched['train']|matched['dev'])}}
            exposed=matched['train']|matched['dev'];proof=score_exposure(spec['model']['checkpoint_sha256'],set(folds['row_component'].values()),condition_models)
            meta=dict(numeric_hashes=hashes,union=folds,arms=arm_folds,historical_match_components={role:sorted(v) for role,v in matched.items()})
            with (ROOT/(condition+'-inputs.npz')).open('xb') as stream:np.savez_compressed(stream,**projected)
            save(ROOT/(condition+'-metadata.json'),meta)
            counts=Counter(hashes)
            results[condition]=dict(union=fold_summary(records,folds,list(range(75000))),
                arms={arm:fold_summary(records,arm_folds[arm],positions) for arm,positions in indices.items()},
                unique_numeric_inputs=len(counts),duplicate_input_groups=sum(n>1 for n in counts.values()),duplicate_input_excess=75000-len(counts),
                direct_historical_numeric_matches={role:sum(h in values for h in hashes) for role,values in old_inputs.items()},
                history_connected_components=len(exposed),history_connected_rows=sum(folds['row_component'][r['row_key']] in exposed for r in records),
                recorded_provenance=proof,source_labels_decoded=0)
            for suffix in ('inputs.npz','metadata.json'):
                name=condition+'-'+suffix;artifacts[name]=sha(ROOT/name)
            print(json.dumps(dict(stage='projection_prepared',condition=condition,**results[condition])),flush=True)
        terminal.update(status='complete',conditions=results,artifacts=artifacts,labels_decoded=0,new_fits=0,new_inference=0,
            source_cache_admission_changed=False,final_test=False)
    except Exception as error:terminal['error_type']=type(error).__name__;raise
    finally:
        terminal.update(elapsed_seconds=round(time.monotonic()-start,3),**guard_summary(guard));save(ROOT/'preparation.json',terminal)
    return dict(status=terminal['status'],conditions=len(results),labels_decoded=0,elapsed_seconds=terminal['elapsed_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','execute'));parser.add_argument('--commit');args=parser.parse_args()
    print(json.dumps(plan() if args.stage=='plan' else execute(args.commit)))
