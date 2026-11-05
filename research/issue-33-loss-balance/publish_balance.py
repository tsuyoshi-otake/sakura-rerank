"""Publish only verified aggregate results; keep sources and numeric data private."""
import argparse
from pathlib import Path

from balance_common import ROOT,PLAN,read,save,sha


def checked_aggregate(value):
    forbidden={'stable_id','source_id','document_id','reading','target','left_context','candidate_snapshots',
        'raw_text','observed_data_read_paths','state_dict','shuffle','source_component'}
    if isinstance(value,dict):
        if set(value)&forbidden:raise ValueError('balance_private_field_in_public_projection')
        for child in value.values():checked_aggregate(child)
    elif isinstance(value,list):
        for child in value:checked_aggregate(child)


def run(verify_existing=False):
    proof=read(ROOT/'verification.json')
    if proof['status']!='passed':raise ValueError('balance_verified_results_required')
    copies={
        'reports/issue-33-loss-balance-v1.json':('model-report.json','model_report_sha256'),
        'reports/issue-33-loss-balance-cpu-v1.json':('cpu-benchmark/report.json','cpu_report_sha256')}
    publications={}
    for destination,(source,field) in copies.items():
        path=ROOT/source
        if sha(path)!=proof[field]:raise ValueError('balance_verified_report_changed')
        checked_aggregate(read(path));publications[destination]=path.read_bytes()
    checked_aggregate(proof)
    publications['reports/issue-33-loss-balance-verification-v1.json']=(ROOT/'verification.json').read_bytes()
    acquisition=read(ROOT/'acquisition.json');prep=read(ROOT/'preparation.json');cohort=read(ROOT/'cohort.json')
    candidate=read(ROOT/'candidate-report.json');train=read(ROOT/'training-execution.json');plan=read(PLAN)
    for name,field in [('preparation.json','source_report_sha256'),('cohort.json','cohort_report_sha256'),
                       ('training-execution.json','training_report_sha256'),('candidate-report.json','candidate_report_sha256')]:
        if sha(ROOT/name)!=proof[field]:raise ValueError('balance_verified_execution_changed')
    stages=[]
    stage_names=('acquisition','candidate-preparation','candidate-preparation-v2','candidate-preparation-v3',
        'candidates','cpu-benchmark','fit-preparation','full-tests','inference','isolate','loss-tests',
        'model-seal','prepare','prepare-v2','statistics','training','verification','verification-v2')
    for stage in stage_names:
        path=ROOT/(stage+'-runner.json')
        value=read(path)
        stages.append({k:value[k] for k in ('stage','status','exit_code','elapsed_seconds')})
    execution=dict(kind='loss_balance_aggregate_execution',issue=33,parent=1,plan_sha256=sha(PLAN),
        source=dict(snapshot_commit=plan['evaluation']['source_commit'],snapshot_tree=plan['evaluation']['source_tree'],
            public_train_documents=3915,prior_reserved_documents=3300,new_reserved_documents=615,unused_documents_remaining=0,
            selection_sha256=plan['evaluation']['selection_sha256'],status=acquisition['status'],
            original_git_blobs_verified=615,total_bytes=plan['evaluation']['expected_source_bytes'],
            started_at=acquisition['started_at'],finished_at=acquisition['finished_at'],
            retries=acquisition['retries'],replacements=acquisition['replacements'],rights=plan['evaluation']['rights'],
            eligible_inputs=prep['pool_rows'],original_source_units=prep['source_units'],deterministic_replay=prep['deterministic_replay']),
        isolation=dict(previous_nodes=cohort['previous_inventory_nodes'],complete_nodes=cohort['audit']['records'],
            excluded_inputs=cohort['excluded_rows'],retained_inputs=cohort['retained_pool_rows'],
            reverse_replay=cohort['full_reverse_replay'],main_slots=cohort['main_slots'],main_statuses=cohort['main_statuses'],
            contrast_counts=cohort['contrast_counts'],selected_rows=cohort['selected_rows'],
            relations_sha256=cohort['relations_sha256'],history_projection_sha256=cohort['history_projection_sha256']),
        candidates=candidate,training={k:train[k] for k in ('status','environment','rows_per_arm','fits_planned','models',
            'elapsed_seconds','not_attempted_fits','forbidden_data_read_attempts','evaluation_arrays_loaded','weight_derivation')},
        tests=read(ROOT/'full-unit-tests.json'),stages=stages,safety_threshold=.0025,production_adoption=False,
        gold_certified=False,independent_human_ime_gold=0,final_test_used=False,
        original_integrity=proof['original_integrity'])
    checked_aggregate(execution)
    from sakura_rerank.data.contracts import canonical_json_bytes
    publications['reports/issue-33-loss-balance-execution-v1.json']=canonical_json_bytes(execution)+b'\n'
    for destination,raw in publications.items():
        path=Path(destination)
        if verify_existing:
            if path.read_bytes()!=raw:raise ValueError('balance_publication_differs')
        else:
            with path.open('xb') as stream:stream.write(raw)
    return dict(status='verified' if verify_existing else 'published',files={p:sha(p) for p in publications})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify-existing',action='store_true')
    args=parser.parse_args();result=run(args.verify_existing)
    if not args.verify_existing:save(ROOT/'publication.json',result)
    print(__import__('json').dumps(result))
