"""Reserve all remaining research sources and fix the train-derived loss weights."""
import copy
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_hash
from balance_common import ROOT,HERE,PLAN,PAST,read,save,sha


def run():
    prior=read('research/issue-33-annotation-comparison/plan-v2.json')
    metadata=dict(prior['evaluation']['reservation_metadata'])
    metadata[prior['evaluation']['selection_path']]=prior['evaluation']['selection_sha256']
    membership_path=Path('data/generated/issue-31-kwdlc-probe-v1/train.id')
    tree_path=Path('data/generated/issue-41-language-pretraining-v1/tree.json')
    if sha(membership_path)!=prior['evaluation']['membership_sha256'] or sha(tree_path)!=prior['evaluation']['tree_sha256']:
        raise ValueError('balance_membership_metadata_changed')
    membership=set(membership_path.read_text(encoding='utf-8').splitlines());exposed=set()
    for path,digest in metadata.items():
        if sha(path)!=digest:raise ValueError('balance_prior_reservation_changed')
        value=read(path);items=value.get('documents',value.get('selected_documents'))
        ids={r['document_id'] for r in items}
        if len(ids)!=len(items) or exposed&ids:raise ValueError('balance_prior_reservations_overlap')
        exposed.update(ids)
    if len(membership)!=3915 or len(exposed)!=3300 or not exposed<=membership:
        raise ValueError('balance_prior_document_counts')
    tree=read(tree_path)
    if tree['truncated'] or tree['sha']!=prior['evaluation']['source_tree']:
        raise ValueError('balance_source_tree_changed')
    chosen=sorted(membership-exposed,key=lambda d:(canonical_json_hash([20261106,'loss-balance-v1',d]),d))
    entries={r['path'].rsplit('/',1)[-1][:-4]:r for r in tree['tree'] if r['path'].startswith('knp/') and r['path'].endswith('.knp')}
    docs=[dict(document_id=d,path=entries[d]['path'],git_blob_sha1=entries[d]['sha'],bytes=entries[d]['size']) for d in chosen]
    if len(docs)!=615:raise ValueError('balance_remaining_source_count')
    ROOT.mkdir(exist_ok=False)
    selection=dict(kind='loss_balance_research_reservation',corpus_commit=prior['evaluation']['source_commit'],
        corpus_tree=tree['sha'],documents=docs,previous_documents=3300,remaining_after_reservation=0,body_accessed=False,final_test=False)
    save(ROOT/'selection.json',selection)
    fit=read('research/issue-33-annotation-experiment/fit-binding-v1.json')
    training=read(PAST/'training-execution.json')
    if training['status']!='complete' or training['not_attempted_fits'] or training['forbidden_data_read_attempts']:
        raise ValueError('balance_complete_prior_fits_required')
    controls=[dict(name=m['name'],arm=m['arm'],seed=m['seed'],path=(PAST/'models'/m['name']/'model.pt').as_posix(),sha256=m['checkpoint_sha256']) for m in training['models']]
    if len(controls)!=6 or any(sha(m['path'])!=m['sha256'] for m in controls):
        raise ValueError('balance_control_checkpoint_changed')
    evaluation=copy.deepcopy(prior['evaluation'])
    evaluation.update(documents=615,prior_exposed_documents=3300,selection_path=(ROOT/'selection.json').as_posix(),
        selection_sha256=sha(ROOT/'selection.json'),expected_source_bytes=sum(d['bytes'] for d in docs),reservation_metadata=metadata,
        selection='All 615 remaining public-train documents, ordered by SHA256 [20261106, loss-balance-v1, document_id]. No replacement. Public dev/test excluded.',
        main='One target per document, minimum canonical SHA256 [20261106, loss-balance-main, stable_id] before candidates/models. Preserve all 615 terminal slots.',
        primary='Mean of three paired weighted-minus-unweighted annotation seed accuracy differences on intact/ungated main, shared-component bootstrap 2000 draws seed20261106.',
        advance_rule='All three accuracy point differences nonnegative, shared-component mean 95% lower bound above zero, and ungated harm does not increase for any seed. One primary comparison; secondary metrics descriptive. Research advancement only.',
        models='All three new weighted fits, three immutable annotation controls, three immutable dictionary anchors, initial #29 reference; no best seed selection.',
        shuffle='Fixed role/context-length stratified cyclic permutation, domain loss-balance-shuffle, seed20261106.',
        isolation='Complete previous 965889-node inventory plus all 10572 eligible inputs and all 3132 source units from the prior 1000-document experiment. Project old input hashes for leakage history only; do not feed their words/labels into the unchanged train cache. Add every new source unit and eligible input, rebuild forward/reverse closure.',
        inference_backend=dict(device='cpu',dtype='float32',threads=1,interop_threads=1,tf32=False,amp=False))
    recipe=copy.deepcopy(prior['training'])
    recipe.update(fits=3,rows=50000,arm='annotation',updates_per_fit=500,validation_during_fit=False,
        loss='Unchanged C2 smoothed listwise per-example CE, multiplied by fixed source/baseline-correctness weights, then arithmetic batch mean. Never divide by random batch weight sum.',
        weights=dict(common_wikipedia=1.0,annotation_aozora_correct=dict(numerator=18776,denominator=12830),
            annotation_aozora_error=dict(numerator=6224,denominator=12170)),
        weight_derivation='Match the old Aozora correct/error prevalence while preserving expected total Aozora loss mass and all rows. No evaluation-dependent coefficient search.',
        control_retraining=False,control_checkpoints=controls,
        start_rule='Only after fresh source isolation, candidate/numeric verification, at least 500 main rows, loss/weight tests and a separately committed fit binding. No fits if readiness fails.')
    paths=['research/issue-33-annotation-comparison/plan-v2.json','research/issue-33-annotation-experiment/execution-plan-v1.json',
        'research/issue-33-annotation-experiment/fit-binding-v1.json','research/issue-33-annotation-experiment/cohort.py',
        'research/issue-33-annotation-experiment/numeric_verifier.py','research/issue-33-annotation-experiment/experiment_fit_contract.py',
        'research/issue-33-annotation-experiment/train_models.py','research/issue-33-annotation-experiment/experiment_statistics.py',
        'reports/issue-33-annotation-experiment-verification-v1.json','reports/issue-33-train-change-audit-v1.json',
        'reports/issue-33-train-change-verification-v1.json','reports/issue-33-train-change-exposure-v1.json',
        (PAST/'training-execution.json').as_posix(),(PAST/'preparation.json').as_posix(),(PAST/'cohort.json').as_posix()]
    paths+=list(fit['training_artifacts'])+list(fit['code'])
    paths+=['src/sakura_rerank/data/context_contrasts.py','src/sakura_rerank/data/context_pilot.py',
            'src/sakura_rerank/data/reconstruction_graph.py','research/reserved_source_acquisition.py']
    inputs={p:sha(p) for p in dict.fromkeys(paths)}
    plan=dict(kind='fixed_loss_contribution_comparison',schema_version=1,issue=33,parent=1,related=[49,34,32],date='2026-11-06',
        hypothesis='Matching Aozora baseline-correct/error loss contribution reduces broad unnecessary changes while retaining useful repairs on unused sources; source rows, model, initial weights and exposure stay fixed.',
        inputs=inputs,training=recipe,evaluation=evaluation,
        limits=dict(nodes=1000000,extracted_targets=20000,selected_rows=1015,source_seconds=900,other_stage_seconds=1800,artifact_bytes=536870912),
        seed=20261106,selection_domain='loss-balance-main',shuffle_domain='loss-balance-shuffle',
        cpu_benchmark={**prior['cpu_benchmark'],'models':['annotation_control','weighted'],'seed':20260814},
        sakura_input_observed=dict(head='bcf42d3ad931c6e081ae4b3fbd4d0e6cd9377d88',worktree_clean=True),
        safety_threshold=.0025,final_test_used=False,gold_certified=False,production_adoption=False,
        quality_policy='Existing source-reconstruction permission only. No new label admissions, independent IME Gold or source licensing changes.',
        expected_cost='Approximately 3.5MB source transfer plus one full source-graph reconstruction and reverse replay; prior 1000-document graph cost 248s. Three fixed 500-update fits after readiness, CPU-only inference and 10000 runs per predesignated export. Hard stage bounds apply; actual costs recorded.',
        expected_effect='Unknown. The frozen train-derived weighting isolates one mixture effect; it may reduce harms while also losing rescues. Failure of the primary rule retains the existing model.')
    save(PLAN,plan)
    return dict(reserved_documents=615,previous_documents=3300,remaining=0,source_bytes=evaluation['expected_source_bytes'],
        selection_sha256=evaluation['selection_sha256'],new_fits=0,body_accessed=False)


if __name__=='__main__':print(json.dumps(run()))
