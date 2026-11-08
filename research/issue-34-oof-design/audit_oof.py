"""Audit existing training identities and saved-model exposure without fitting."""
import argparse
from collections import Counter
import hashlib
import json
import platform
import subprocess
import sys

from sakura_rerank.data.consumed_numeric import verify_chain
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.gate_oof import component_folds,nested_schedule,score_exposure
from oof_common import CACHE,HERE,ROOT,authenticate,read,save,sha

PAST='data/generated/issue-33-annotation-experiment-v1/'
AUDIT='data/generated/issue-33-train-change-audit-v1/'


def plan():
    fit=read('research/issue-33-annotation-experiment/fit-binding-v1.json')
    models=read('research/issue-33-train-change-audit/plan-v1.json')['models']
    paths=list(fit['training_artifacts'])+list(fit['code'])+[
        'research/issue-33-annotation-experiment/fit-binding-v1.json',fit['plan_path'],
        'research/issue-33-train-change-audit/plan-v1.json',PAST+'training-execution.json',
        AUDIT+'profile.json',AUDIT+'inference.json',AUDIT+'scores.npz',AUDIT+'verification.json',
        'reports/issue-35-source-models-v1.json','research/issue-33-loss-balance/evaluation-binding-v1.json']
    paths+=[m['path'] for m in read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']]
    for path,digest in fit['training_artifacts'].items():
        if sha(path)!=digest:raise ValueError('oof_training_binding_changed')
    code=list(HERE.glob('*.py'))+['src/sakura_rerank/gate_oof.py','tests/test_gate_oof.py',
        'src/sakura_rerank/data/consumed_numeric.py','src/sakura_rerank/data/contracts.py']
    head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    if subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30):raise ValueError('oof_input_checkout_not_clean')
    value=dict(kind='train_only_nested_oof_feasibility_plan',issues=[34,33,35],parent_issue=1,
        previous_commit='14a80eeae00aeb75925050d6899081bffd0f9126',training_rows=75000,fold_count=5,
        fold_policy='Union all75000 recorded components and original/numeric inputs first, retain bridge rows, then allocate each50000-row arm by complete components; largest first, size then component hash, least loaded fold then index.',
        label_policy='No labels or scores decoded for folding; preserve weak source-reconstruction admission and all records.',
        ancestry_policy='Direct fitting and selection plus initialization/teacher ancestors; absent or incomplete lineage is unknown, never an empty clean root.',
        nested_policy='Outer test fold absent from every inner score generator and ancestor. Five outer and20 inner roles;10 symmetric pairs share only with identical complete training identity.',
        initial_reference29='Ancestry is not fully authenticated by this audit. Preserve unknown; do not certify residual source-disjoint records as OOF.',
        declared_models=models,inputs={str(p).replace('\\','/'):sha(p) for p in sorted(set(paths))},
        code={str(p).replace('\\','/'):sha(p) for p in code},
        limits=dict(rows=100000,models=64,folds=10,wall_seconds=600,retries=0),
        current_sakura_input_head=head,current_sakura_input_clean=True,
        environment=dict(python=sys.version.split()[0],platform=platform.platform(),new_dependencies=0),
        new_fits=0,new_inference=0,threshold_selection=False,calibration=False,final_test=False,gold_admission=False,
        original_safety_limit=.0025,permission='Metadata feasibility and synthetic protocol verification only.')
    save(HERE/'plan-v1.json',value);return dict(stage='planned',plan_sha256=sha(HERE/'plan-v1.json'),new_fits=0)


def load_identities():
    manifest=read(CACHE/'manifest.json');raw=(CACHE/'row-receipts.jsonl').read_bytes()
    if len(raw)>256*1024*1024:raise ValueError('oof_metadata_byte_bound')
    ledger=verify_chain(raw,75000,manifest['row_chain_head']);indices=read(CACHE/'cohort-indices.json')
    if canonical_json_hash([r['origin']['stable_id'] for r in ledger])!=manifest['source_order_sha256']:
        raise ValueError('oof_source_order_changed')
    a,b=set(indices['dictionary']),set(indices['annotation']);common=a&b
    if len(a)!=50000 or len(b)!=50000 or len(common)!=25000 or a|b!=set(range(75000)):
        raise ValueError('oof_cohort_population')
    rows=[]
    for i,row in enumerate(ledger):
        origin=row['origin']
        if origin['training_eligible'] is not False or origin['independent_gold_eligible'] is not False:
            raise ValueError('oof_source_admission_changed')
        group='wikipedia' if i in common else 'dictionary_aozora' if i in a else 'annotation_aozora'
        rows.append(dict(row_key=hashlib.sha256(('gate-oof-row-v1\n'+origin['group']+'\n'+origin['stable_id']).encode()).hexdigest(),
            component_key=origin['component_id'],original_input_key=origin['original_input_sha256'],
            numeric_input_key=row['input_tensor_sha256'],group=group))
    return rows,indices,manifest


def aggregate_folds(rows,result):
    counts=Counter(r['group'] for r in rows);components={};by_group={}
    for row in rows:
        key=result['row_component'][row['row_key']];components.setdefault(key,Counter())[row['group']]+=1
    for group,count in counts.items():
        values=[c[group] for c in components.values() if c[group]]
        by_group[group]=dict(rows=count,components=len(values),largest_component=max(values),largest_fraction=max(values)/count)
    return dict(rows=len(rows),components=len(components),largest_component=max(result['component_sizes'].values()),
        fold_sizes=result['fold_sizes'],fold_group_counts=result['fold_group_counts'],source_groups=by_group,
        empty_folds=sum(v==0 for v in result['fold_sizes']),equal_fold_target=len(rows)/result['fold_count'],
        smallest_train_rows=len(rows)-max(result['fold_sizes']),source_independence_certified=False)


def execute(commit):
    spec=authenticate(commit);save(ROOT/'audit-reservation.json',dict(plan_commit=commit,new_fits=0,new_inference=0))
    rows,indices,manifest=load_identities();union=component_folds(rows,5)
    if union!=component_folds(list(reversed(rows)),5):raise ValueError('oof_reverse_partition_differed')
    arm_results={};arm_summaries={};arm_keys={}
    for arm,positions in indices.items():
        # Keep links through the other arm: removing bridge rows is not isolation.
        subset=[{**rows[i],'component_key':union['row_component'][rows[i]['row_key']]} for i in positions]
        arm_results[arm]=component_folds(subset,5);arm_summaries[arm]=aggregate_folds(subset,arm_results[arm]);arm_keys[arm]={r['row_key'] for r in subset}
    training=read(PAST+'training-execution.json');execution=read(AUDIT+'inference.json')
    if training['status']!='complete' or execution['status']!='complete' or execution['scores_sha256']!=sha(AUDIT+'scores.npz'):
        raise ValueError('oof_historical_execution_changed')
    root_model=spec['declared_models'][0];root_sha=root_model['sha256'];models={root_sha:dict(fit_components=[],selection_components=[],parents=[],lineage_complete=False)}
    receipts={m['name']:m for m in training['models']};exposures=[]
    for item in spec['declared_models'][1:]:
        receipt=receipts[item['name']];arm=receipt['arm']
        if receipt['status']!='complete' or receipt['steps']!=500 or receipt['examples']!=128000 or receipt['checkpoint_sha256']!=item['sha256'] or receipt['initial_checkpoint_sha256']!=root_sha:
            raise ValueError('oof_fitted_checkpoint_receipt')
        fits={union['row_component'][key] for key in arm_keys[arm]}
        models[item['sha256']]=dict(fit_components=sorted(fits),selection_components=[],parents=[root_sha],lineage_complete=True)
        seen_original={rows[i]['original_input_key'] for i in indices[arm]};seen_numeric={rows[i]['numeric_input_key'] for i in indices[arm]}
        unseen=[r for r in rows if r['row_key'] not in arm_keys[arm]]
        overlap=sum(union['row_component'][r['row_key']] in fits for r in unseen)
        exposures.append(dict(model=item['name'],arm=arm,direct_fit_rows=50000,rows_not_directly_fitted=len(unseen),
            unseen_original_input_matches=sum(r['original_input_key'] in seen_original for r in unseen),
            unseen_numeric_input_matches=sum(r['numeric_input_key'] in seen_numeric for r in unseen),
            unseen_but_component_connected=overlap,unseen_and_component_unconnected=len(unseen)-overlap,
            complete_ancestry_authenticated=False,certified_reusable_oof_rows=0))
    proofs={}
    for item in spec['declared_models']:
        proofs[item['name']]=score_exposure(item['sha256'],set(union['row_component'].values()),models)
    schedule=nested_schedule(5);save(ROOT/'nested-schedule.json',schedule)
    save(ROOT/'training-identities.json',dict(rows=rows,indices=indices))
    save(ROOT/'folds.json',dict(union=union,arms=arm_results))
    save(ROOT/'model-exposure.json',models)
    report=dict(kind='train_only_oof_feasibility',status='audited_no_fit_permission',plan_commit=commit,
        training_metadata_rows=len(rows),union=aggregate_folds(rows,union),arms=arm_summaries,
        source_admission=dict(training_eligible=manifest['training_eligible'],independent_gold_eligible=manifest['independent_gold_eligible']),
        saved_score_models=7,saved_score_conditions=len(execution['conditions']),saved_cpu_parity_passed=execution['cpu_parity_passed'],
        saved_score_exposure=exposures,model_provenance_checks=proofs,reference29_lineage='unknown_pending_complete_ancestry_binding',
        nested_schedule=schedule,observed_prior_fit_seconds=[m['elapsed_seconds'] for m in training['models']],
        metadata_hashes={name:sha(ROOT/name) for name in ('training-identities.json','folds.json','model-exposure.json','nested-schedule.json')},
        new_fits=0,new_inference=0,new_labels=0,calibration=False,final_test=False,threshold_selection=False,
        safety_limit=.0025,gold_certified=False,release_eligible=False)
    save(ROOT/'audit.json',report)
    return dict(status=report['status'],rows=len(rows),union_components=report['union']['components'],
        arms={name:dict(rows=r['rows'],fold_sizes=r['fold_sizes'],source_groups=r['source_groups']) for name,r in arm_summaries.items()},
        source_unseen_reuse=exposures,new_fits=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','execute'));parser.add_argument('--commit')
    args=parser.parse_args();print(json.dumps(plan() if args.stage=='plan' else execute(args.commit)))
