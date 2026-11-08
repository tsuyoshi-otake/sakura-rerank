"""Original annotation extraction and full history isolation for the reserved cohort."""
import argparse
from collections import Counter
import json
import time

from sakura_rerank.data.context_contrasts import extract_pool, select_contrasts
from sakura_rerank.data.context_pilot import annotation_units
from sakura_rerank.data.contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from sakura_rerank.data.corpus_v5 import _publish_directory_atomically
from sakura_rerank.data.kwdlc_probe import ProbeError, blob_sha1
from sakura_rerank.data.reconstruction_graph import isolate_source_scope
from experiment_common import ROOT, HERE, PREPARATION_ROOT, authenticate, implementation, preparation, read, rows, save, sha, write_rows

EXECUTION_COMMIT='dc39ee520df68cb99d99ec85905c19b3388e32f5'
CODE=(HERE/'cohort.py',HERE/'experiment_common.py','src/sakura_rerank/data/context_contrasts.py',
      'src/sakura_rerank/data/context_pilot.py','src/sakura_rerank/data/reconstruction_graph.py')


def source_metadata(document_id, unit):
    sentence=''.join(t['surface'] for t in unit)
    return dict(article_id='kwdlc:'+document_id, paragraph_hash=text_sha256(sentence),
                sentence_hash=text_sha256(sentence), sentence_shingle_hashes=sentence_shingle_hashes(sentence),
                template_cluster_id=None)


def generate():
    plan,spec=authenticate(EXECUTION_COMMIT)
    selection=read(plan['evaluation']['selection_path']);acquisition=read(ROOT/'acquisition.json')
    if (acquisition['identity']['selection_sha256']!=plan['evaluation']['selection_sha256']
            or acquisition['identity']['execution_plan_commit']!=EXECUTION_COMMIT
            or [r['index'] for r in acquisition['attempts']]!=list(range(1000))):
        raise ValueError('experiment_acquisition_denominator')
    pool=[];slots=[];coverage=[];counts=Counter()
    for document,attempt in zip(selection['documents'],acquisition['attempts']):
        if document['document_id']!=attempt['document_id']:
            raise ValueError('experiment_source_order')
        slot=dict(document_id=document['document_id'],target_id=None,status=attempt['status'])
        if attempt['status']!='received':
            slots.append(slot);continue
        path=ROOT/'source'/(document['document_id']+'.knp');raw=path.read_bytes()
        if (len(raw)!=document['bytes'] or blob_sha1(raw)!=document['git_blob_sha1']
                or sha(path)!=attempt['sha256']):
            raise ValueError('experiment_original_source_changed')
        try:
            targets,statuses=extract_pool(document['document_id'],raw,lexical_basis='original_lemma')
            units=annotation_units(document['document_id'],raw)
        except (ProbeError,UnicodeError,ValueError) as error:
            slot.update(status='parse_failure',error_type=type(error).__name__)
            slots.append(slot);continue
        # Direct token-position check, separate from extraction eligibility and prefix accumulation.
        for target in targets:
            unit=units[target['annotation_unit']];index=target['morpheme']
            if (target['target']!=unit[index]['surface'] or target['reading']!=unit[index]['reading']
                    or target['left_context']!=''.join(t['surface'] for t in unit[:index])[-64:]
                    or target['source']!=source_metadata(document['document_id'],unit)):
                raise ValueError('experiment_original_annotation_position')
        pool.extend(targets);counts.update(statuses)
        for index,unit in enumerate(units):
            coverage.append(dict(stable_id='annotation-source-unit-'+canonical_json_hash([document['document_id'],index]),
                population='source_coverage',source=source_metadata(document['document_id'],unit)))
        if targets:
            chosen=min(targets,key=lambda r:canonical_json_hash([spec['seed'],spec['selection_domain'],r['stable_id']]))
            slot.update(status='eligible_before_history',target_id=chosen['stable_id'])
        else:
            slot['status']='no_eligible_target'
        slots.append(slot)
    if len(pool)>spec['limits']['extracted_targets'] or len(slots)!=1000:
        raise ValueError('experiment_source_population_bound')
    return pool,slots,coverage,dict(counts)


def prepare():
    started=time.monotonic();head,code=implementation(CODE)
    first=generate()
    if first!=generate():
        raise ValueError('experiment_source_replay')
    staging=ROOT/'prepared.partial';staging.mkdir(exist_ok=False)
    artifacts={name:write_rows(staging/(name+'.jsonl.gz'),values)
               for name,values in zip(('pool','main-slots','source-coverage'),first[:3])}
    report=dict(kind='annotation_experiment_source_preparation',status='complete',
        pool_rows=len(first[0]),main_slots=len(first[1]),source_units=len(first[2]),extraction_counts=first[3],
        acquisition_sha256=sha(ROOT/'acquisition.json'),artifacts=artifacts,
        deterministic_replay=True,all_original_positions_verified=True,execution_commit=head,implementation=code,
        elapsed_seconds=round(time.monotonic()-started,3),model_fits=0,model_predictions=0,gold_certified=False,final_test_used=False)
    save(staging/'manifest.json',report)
    _publish_directory_atomically(staging,ROOT/'prepared',immutable_message='experiment_prepared_exists')
    save(ROOT/'preparation.json',report)
    return {key:report[key] for key in ('status','pool_rows','main_slots','source_units','elapsed_seconds')}


def prior_inventory():
    authenticate(EXECUTION_COMMIT)
    graph,_,_,_,_=preparation.prior.origin.source.load_inventory()
    source=read(PREPARATION_ROOT/'source-report.json')
    coverage_path=PREPARATION_ROOT/'source'/source['artifacts']['wikipedia-coverage']['path']
    if sha(coverage_path)!=source['artifacts']['wikipedia-coverage']['sha256']:
        raise ValueError('experiment_previous_coverage_changed')
    previous=[dict(row,population='historical') if row['population']!='source_coverage' else row
              for row in graph.records]
    del graph
    previous.extend(rows(coverage_path))
    if len(previous)!=965889:
        raise ValueError('experiment_history_population')
    return previous


def isolate():
    started=time.monotonic();head,code=implementation(CODE)
    plan,_=authenticate(EXECUTION_COMMIT);prep=read(ROOT/'preparation.json')
    for artifact in prep['artifacts'].values():
        if sha(ROOT/'prepared'/artifact['path'])!=artifact['sha256']:
            raise ValueError('experiment_prepared_bytes_changed')
    pool=list(rows(ROOT/'prepared/pool.jsonl.gz'))
    slots=list(rows(ROOT/'prepared/main-slots.jsonl.gz'))
    coverage=list(rows(ROOT/'prepared/source-coverage.jsonl.gz'))
    previous=prior_inventory()
    metadata=[dict(stable_id=row['stable_id'],population='evaluation',source=row['source'],
        input_hash=canonical_json_hash([row['left_context'],row['reading']])) for row in pool]
    combined=previous+metadata+coverage
    print(json.dumps(dict(stage='annotation_full_source_closure',previous_nodes=len(previous),
        eligible_inputs=len(pool),new_source_units=len(coverage),total_nodes=len(combined))),flush=True)
    excluded,components,audit=isolate_source_scope(combined)
    reverse_excluded,reverse_components,reverse_audit=isolate_source_scope(list(reversed(combined)))
    if (excluded,components,audit)!=(reverse_excluded,reverse_components,reverse_audit):
        raise ValueError('experiment_full_reverse_replay')
    del combined,previous,metadata,reverse_excluded,reverse_components
    retained=[row for row in pool if row['stable_id'] not in excluded]
    contrasts,contrast_counts=select_contrasts(retained,maximum_groups=100)
    if select_contrasts(list(reversed(retained)),maximum_groups=100)!=(contrasts,contrast_counts):
        raise ValueError('experiment_contrast_replay')
    for slot in slots:
        if slot['status']=='eligible_before_history':
            slot['status']='historical_relation' if slot['target_id'] in excluded else 'retained'
    main_ids={slot['target_id'] for slot in slots if slot['status']=='retained'}
    groups={row['stable_id']:row['contrast_group'] for row in contrasts}
    selected=[]
    for row in sorted(retained,key=lambda r:r['stable_id']):
        roles=(['main'] if row['stable_id'] in main_ids else [])+(['contrast'] if row['stable_id'] in groups else [])
        if roles:
            selected.append(dict(row,roles=roles,source_component=components[row['stable_id']],
                                 contrast_group=groups.get(row['stable_id'])))
    if len(selected)>1400 or any(row['stable_id'] in excluded for row in selected):
        raise ValueError('experiment_selected_population')
    staging=ROOT/'cohort.partial';staging.mkdir(exist_ok=False)
    artifacts={name:write_rows(staging/(name+'.jsonl.gz'),values)
               for name,values in (('selected',selected),('main-terminal',slots))}
    save(staging/'source-relations.json',dict(excluded=excluded,components=components))
    report=dict(kind='annotation_experiment_cohort',
        status='ready' if len(main_ids)>=plan['evaluation']['readiness']['main_minimum'] else 'insufficient_do_not_train',
        prior_inventory_nodes=965889,pool_rows=len(pool),retained_pool_rows=len(retained),excluded_rows=len(excluded),
        source_units=len(coverage),main_slots=1000,main_statuses=dict(Counter(s['status'] for s in slots)),
        contrast_counts=contrast_counts,selected_rows=len(selected),audit=audit,full_reverse_replay=True,
        historical_nodes_are_evaluation_only_copies=True,original_training_changed=False,
        preparation_sha256=sha(ROOT/'preparation.json'),artifacts=artifacts,
        relations_sha256=sha(staging/'source-relations.json'),execution_commit=head,implementation=code,
        elapsed_seconds=round(time.monotonic()-started,3),model_fits=0,model_predictions=0,gold_certified=False,final_test_used=False)
    save(staging/'manifest.json',report)
    _publish_directory_atomically(staging,ROOT/'cohort',immutable_message='experiment_cohort_exists')
    save(ROOT/'cohort.json',report)
    return {key:report[key] for key in ('status','pool_rows','retained_pool_rows','excluded_rows','main_statuses',
                                       'contrast_counts','selected_rows','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','isolate'))
    print(json.dumps(dict(prepare=prepare,isolate=isolate)[parser.parse_args().stage]()))
