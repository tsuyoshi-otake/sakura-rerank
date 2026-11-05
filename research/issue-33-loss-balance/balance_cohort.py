"""Fresh evaluation source reconstruction and complete historical isolation."""
import argparse
from collections import Counter
import json
import subprocess
import time

from sakura_rerank.data.context_contrasts import extract_pool,select_contrasts
from sakura_rerank.data.context_pilot import annotation_units
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.corpus_v5 import _publish_directory_atomically
from sakura_rerank.data.kwdlc_probe import blob_sha1
from sakura_rerank.data.reconstruction_graph import isolate_source_scope
from balance_common import ROOT,HERE,PAST,authenticate,boundary,read,rows,save,sha,write_rows

PLAN_COMMIT='8ea14eed349b375a63b09c744d3bf40c15ee196b'

PAST_CODE='research/issue-33-annotation-experiment/cohort.py'


def implementation():
    paths=[HERE/'balance_cohort.py',HERE/'balance_common.py',HERE/'acquire_sources.py',PAST_CODE,
           'src/sakura_rerank/data/context_contrasts.py','src/sakura_rerank/data/context_pilot.py',
           'src/sakura_rerank/data/reconstruction_graph.py']
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True,timeout=15).strip()
    for path in paths:boundary.committed(path,head)
    return head,{str(p):sha(p) for p in paths}


def prior_module():
    return boundary.load_script('loss_balance_historical_cohort',PAST_CODE)


def generate():
    plan=authenticate(PLAN_COMMIT);selection=read(plan['evaluation']['selection_path'])
    acquisition=read(ROOT/'acquisition.json');previous=prior_module()
    if (acquisition['status']!='complete' or acquisition['identity']['execution_plan_commit']!=PLAN_COMMIT
            or acquisition['identity']['selection_sha256']!=plan['evaluation']['selection_sha256']
            or [a['index'] for a in acquisition['attempts']]!=list(range(615))
            or any(a['status']!='received' for a in acquisition['attempts'])):
        raise ValueError('balance_complete_source_acquisition_required')
    for path,digest in acquisition['identity']['code'].items():
        if sha(path)!=digest:raise ValueError('balance_acquisition_code_changed')
    pool=[];slots=[];coverage=[];counts=Counter()
    for document,attempt in zip(selection['documents'],acquisition['attempts']):
        if document['document_id']!=attempt['document_id']:raise ValueError('balance_source_order')
        path=ROOT/'source'/(document['document_id']+'.knp');raw=path.read_bytes()
        if len(raw)!=document['bytes'] or blob_sha1(raw)!=document['git_blob_sha1'] or sha(path)!=attempt['sha256']:
            raise ValueError('balance_original_source_changed')
        # Parse failure aborts publication; there is no partial trusted cohort.
        targets,statuses=extract_pool(document['document_id'],raw,lexical_basis='original_lemma')
        units=annotation_units(document['document_id'],raw)
        for target in targets:
            unit=units[target['annotation_unit']];token=unit[target['morpheme']]
            if (target['target']!=token['surface'] or target['reading']!=token['reading']
                    or target['left_context']!=''.join(t['surface'] for t in unit[:target['morpheme']])[-64:]
                    or target['source']!=previous.source_metadata(document['document_id'],unit)):
                raise ValueError('balance_original_position_check')
        pool.extend(targets);counts.update(statuses)
        for index,unit in enumerate(units):
            coverage.append(dict(stable_id='annotation-source-unit-'+canonical_json_hash([document['document_id'],index]),
                population='source_coverage',source=previous.source_metadata(document['document_id'],unit)))
        chosen=min(targets,key=lambda r:canonical_json_hash([plan['seed'],plan['selection_domain'],r['stable_id']])) if targets else None
        slots.append(dict(document_id=document['document_id'],target_id=None if chosen is None else chosen['stable_id'],
                          status='no_eligible_target' if chosen is None else 'eligible_before_history'))
    if len(pool)>plan['limits']['extracted_targets'] or len(slots)!=615:
        raise ValueError('balance_source_population_bound')
    return pool,slots,coverage,dict(counts)


def prepare():
    start=time.monotonic();head,code=implementation();result=generate()
    if result!=generate():raise ValueError('balance_source_replay_differs')
    staging=ROOT/'prepared.partial';staging.mkdir(exist_ok=False)
    artifacts={name:write_rows(staging/(name+'.jsonl.gz'),value) for name,value in
               zip(('pool','main-slots','source-coverage'),result[:3])}
    report=dict(kind='loss_balance_source_preparation',status='complete',code_commit=head,code=code,
        pool_rows=len(result[0]),main_slots=615,source_units=len(result[2]),extraction_counts=result[3],
        artifacts=artifacts,acquisition_sha256=sha(ROOT/'acquisition.json'),deterministic_replay=True,
        original_positions_verified=True,elapsed_seconds=round(time.monotonic()-start,3),new_fits=0,model_predictions=0,
        final_test_used=False,gold_certified=False)
    save(staging/'manifest.json',report)
    _publish_directory_atomically(staging,ROOT/'prepared',immutable_message='balance_prepared_exists')
    save(ROOT/'preparation.json',report)
    return {k:report[k] for k in ('status','pool_rows','main_slots','source_units','elapsed_seconds')}


def old_inventory():
    authenticate(PLAN_COMMIT);previous=prior_module();base=previous.prior_inventory()
    prep=read(PAST/'preparation.json')
    for name in ('pool','source-coverage'):
        artifact=prep['artifacts'][name]
        if sha(PAST/'prepared'/artifact['path'])!=artifact['sha256']:
            raise ValueError('balance_previous_source_artifact_changed')
    old_inputs=[dict(stable_id=r['stable_id'],population='historical',source=r['source'],
        input_hash=canonical_json_hash([r['left_context'],r['reading']])) for r in rows(PAST/'prepared/pool.jsonl.gz')]
    old_coverage=list(rows(PAST/'prepared/source-coverage.jsonl.gz'))
    if len(base)!=965889 or len(old_inputs)!=10572 or len(old_coverage)!=3132:
        raise ValueError('balance_previous_inventory_counts')
    artifacts={name:write_rows(ROOT/(name+'.jsonl.gz'),value) for name,value in
               (('previous-input-metadata',old_inputs),('previous-source-coverage',old_coverage))}
    save(ROOT/'historical-projection.json',dict(kind='loss_balance_history_projection',previous_nodes=979593,
        projected_input_nodes=10572,projected_source_units=3132,artifacts=artifacts,
        previous_preparation_sha256=sha(PAST/'preparation.json'),
        purpose='Leakage history only; old source strings hashed and discarded, no old target labels or scores used by fitting.'))
    return base+old_inputs+old_coverage


def isolate():
    start=time.monotonic();plan=authenticate(PLAN_COMMIT);head,code=implementation();prep=read(ROOT/'preparation.json')
    for artifact in prep['artifacts'].values():
        if sha(ROOT/'prepared'/artifact['path'])!=artifact['sha256']:raise ValueError('balance_prepared_source_changed')
    pool=list(rows(ROOT/'prepared/pool.jsonl.gz'));slots=list(rows(ROOT/'prepared/main-slots.jsonl.gz'))
    coverage=list(rows(ROOT/'prepared/source-coverage.jsonl.gz'));previous=old_inventory()
    metadata=[dict(stable_id=r['stable_id'],population='evaluation',source=r['source'],
        input_hash=canonical_json_hash([r['left_context'],r['reading']])) for r in pool]
    combined=previous+metadata+coverage
    if len(combined)>plan['limits']['nodes']:raise ValueError('balance_complete_inventory_bound')
    print(json.dumps(dict(stage='balance_full_history_closure',previous=len(previous),inputs=len(pool),source_units=len(coverage),total=len(combined))),flush=True)
    excluded,components,audit=isolate_source_scope(combined)
    rev_excluded,rev_components,rev_audit=isolate_source_scope(list(reversed(combined)))
    if (excluded,components,audit)!=(rev_excluded,rev_components,rev_audit):raise ValueError('balance_reverse_closure_differs')
    del combined,previous,rev_excluded,rev_components
    retained=[r for r in pool if r['stable_id'] not in excluded]
    contrasts,contrast_counts=select_contrasts(retained,maximum_groups=100)
    if select_contrasts(list(reversed(retained)),maximum_groups=100)!=(contrasts,contrast_counts):
        raise ValueError('balance_contrast_order_differs')
    for slot in slots:
        if slot['status']=='eligible_before_history':slot['status']='historical_relation' if slot['target_id'] in excluded else 'retained'
    main_ids={s['target_id'] for s in slots if s['status']=='retained'}
    group={r['stable_id']:r['contrast_group'] for r in contrasts};selected=[]
    for row in sorted(retained,key=lambda r:r['stable_id']):
        roles=(['main'] if row['stable_id'] in main_ids else [])+(['contrast'] if row['stable_id'] in group else [])
        if roles:selected.append(dict(row,roles=roles,source_component=components[row['stable_id']],contrast_group=group.get(row['stable_id'])))
    if len(selected)>plan['limits']['selected_rows']:raise ValueError('balance_selected_row_bound')
    staging=ROOT/'cohort.partial';staging.mkdir(exist_ok=False)
    artifacts={name:write_rows(staging/(name+'.jsonl.gz'),value) for name,value in
               (('selected',selected),('main-terminal',slots),('new-input-metadata',metadata),('new-source-coverage',coverage))}
    save(staging/'source-relations.json',dict(excluded=excluded,components=components))
    report=dict(kind='loss_balance_isolated_cohort',status='ready' if len(main_ids)>=500 else 'insufficient_do_not_train',
        code_commit=head,code=code,previous_inventory_nodes=979593,pool_rows=len(pool),source_units=len(coverage),
        main_slots=615,main_statuses=dict(Counter(s['status'] for s in slots)),retained_pool_rows=len(retained),excluded_rows=len(excluded),
        contrast_counts=contrast_counts,selected_rows=len(selected),audit=audit,full_reverse_replay=True,
        preparation_sha256=sha(ROOT/'preparation.json'),history_projection_sha256=sha(ROOT/'historical-projection.json'),
        artifacts=artifacts,relations_sha256=sha(staging/'source-relations.json'),elapsed_seconds=round(time.monotonic()-start,3),
        original_training_changed=False,new_fits=0,model_predictions=0,final_test_used=False,gold_certified=False)
    save(staging/'manifest.json',report)
    _publish_directory_atomically(staging,ROOT/'cohort',immutable_message='balance_cohort_exists')
    save(ROOT/'cohort.json',report)
    return {k:report[k] for k in ('status','pool_rows','retained_pool_rows','excluded_rows','main_statuses','contrast_counts','selected_rows','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','isolate'])
    print(json.dumps(dict(prepare=prepare,isolate=isolate)[parser.parse_args().stage]()))
