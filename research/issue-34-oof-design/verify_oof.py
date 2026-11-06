"""Reproduce the metadata audit with graph traversal and heap allocation."""
import argparse
from collections import Counter,defaultdict
import hashlib
import heapq
import itertools
import json
from pathlib import Path
import subprocess
import sys

from oof_common import CACHE,HERE,ROOT,authenticate,committed,read,save,sha


def require(value,code):
    if not value:raise ValueError('oof_verification_'+code)


def checksum(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def component_key(keys):return hashlib.sha256(('gate-oof-component-v1\n'+'\n'.join(sorted(keys))+'\n').encode()).hexdigest()


def reconstruct_metadata():
    saved=read(ROOT/'training-identities.json');indices=read(CACHE/'cohort-indices.json')
    require(saved['indices']==indices,'indices');a=set(indices['dictionary']);b=set(indices['annotation']);common=a&b
    manifest=read(CACHE/'manifest.json');previous='0'*64;records=[];stable=[]
    with (CACHE/'row-receipts.jsonl').open('rb') as stream:
        for index,raw in enumerate(stream):
            row=json.loads(raw);origin=row['origin']
            require(row['index']==index and row['previous_sha256']==previous,'chain_order')
            previous=checksum({k:v for k,v in row.items() if k!='record_sha256'})
            require(previous==row['record_sha256'],'chain_hash');stable.append(origin['stable_id'])
            key=hashlib.sha256(('gate-oof-row-v1\n'+origin['group']+'\n'+origin['stable_id']).encode()).hexdigest()
            group='wikipedia' if index in common else 'dictionary_aozora' if index in a else 'annotation_aozora'
            require(origin['training_eligible'] is False and origin['independent_gold_eligible'] is False,'admission')
            records.append(dict(row_key=key,group=group,component_key=origin['component_id'],
                original_input_key=origin['original_input_sha256'],numeric_input_key=row['input_tensor_sha256']))
    require(len(records)==75000 and len(set(stable))==75000 and previous==manifest['row_chain_head'],'chain_population')
    require(checksum(stable)==manifest['source_order_sha256'] and records==saved['rows'],'all_identities')
    return records,indices


def graph_components(rows):
    adjacency=[[] for _ in rows];first={}
    for i,row in enumerate(rows):
        for field in ('component_key','original_input_key','numeric_input_key'):
            token=(field,row[field])
            if token in first:
                j=first[token];adjacency[i].append(j);adjacency[j].append(i)
            else:first[token]=i
    visited=set();parts={}
    for start in range(len(rows)):
        if start in visited:continue
        pending=[start];visited.add(start);members=[]
        while pending:
            i=pending.pop();members.append(rows[i]['row_key'])
            for j in adjacency[i]:
                if j not in visited:visited.add(j);pending.append(j)
        key=component_key(members)
        for rowkey in members:parts[rowkey]=key
    return parts


def independently_allocate(rows,components,fold_count=5):
    members=defaultdict(list)
    for row in rows:members[components[row['row_key']]].append(row['row_key'])
    # Rehash each retained membership set, retaining all incoming graph links.
    groups={component_key(keys):keys for keys in members.values()};queue=[(0,i) for i in range(fold_count)]
    row_fold={};row_component={};totals=[0]*fold_count
    for component,keys in sorted(groups.items(),key=lambda item:(-len(item[1]),item[0])):
        size,fold=heapq.heappop(queue);totals[fold]=size+len(keys);heapq.heappush(queue,(totals[fold],fold))
        for key in keys:row_fold[key]=fold;row_component[key]=component
    source=[Counter() for _ in range(fold_count)]
    for row in rows:source[row_fold[row['row_key']]][row['group']]+=1
    return dict(row_component=row_component,row_fold=row_fold,component_sizes={k:len(v) for k,v in groups.items()},
        fold_sizes=totals,fold_group_counts=[dict(c) for c in source],fold_count=fold_count,
        independent_source_certified=False,fit_permission=False)


def check_summary(rows,folds,summary):
    source=defaultdict(Counter)
    for row in rows:source[row['group']][folds['row_component'][row['row_key']]]+=1
    require(summary['rows']==len(rows) and summary['components']==len(folds['component_sizes']),'summary_count')
    require(summary['fold_sizes']==folds['fold_sizes'] and summary['fold_group_counts']==folds['fold_group_counts'],'summary_folds')
    require(summary['largest_component']==max(folds['component_sizes'].values()),'largest_component')
    for group,values in source.items():
        require(summary['source_groups'][group]==dict(rows=sum(values.values()),components=len(values),largest_component=max(values.values()),largest_fraction=max(values.values())/sum(values.values())),'source_summary')
    require(summary['smallest_train_rows']==len(rows)-max(folds['fold_sizes']),'train_size')


def check_exposures(rows,indices,components,plan,report):
    metadata=read(ROOT/'model-exposure.json');names={m['name']:m['sha256'] for m in plan['declared_models']}
    for result in report['saved_score_exposure']:
        arm=result['arm'];fitted=set(indices[arm]);others=set(range(len(rows)))-fitted
        original={rows[i]['original_input_key'] for i in fitted};numeric={rows[i]['numeric_input_key'] for i in fitted}
        seen={components[rows[i]['row_key']] for i in fitted}
        overlap=sum(components[rows[i]['row_key']] in seen for i in others)
        expected=dict(direct_fit_rows=len(fitted),rows_not_directly_fitted=len(others),
            unseen_original_input_matches=sum(rows[i]['original_input_key'] in original for i in others),
            unseen_numeric_input_matches=sum(rows[i]['numeric_input_key'] in numeric for i in others),
            unseen_but_component_connected=overlap,unseen_and_component_unconnected=len(others)-overlap)
        require(all(result[k]==v for k,v in expected.items()),'model_row_overlap')
        require(set(metadata[names[result['model']]]['fit_components'])==seen,'model_fit_components')
    universe=set(components.values())
    for name,key in names.items():
        pending=[key];visited=set();fit=set();selection=set();incomplete=0;missing=set()
        while pending:
            current=pending.pop()
            if current in visited:continue
            visited.add(current)
            if current not in metadata:missing.add(current);continue
            value=metadata[current];incomplete+=not value['lineage_complete'];pending.extend(value['parents'])
            fit.update(set(value['fit_components'])&universe);selection.update(set(value['selection_components'])&universe)
        result=report['model_provenance_checks'][name]
        require(result['fit_overlap_components']==len(fit) and result['selection_overlap_components']==len(selection),'ancestry_overlaps')
        require(result['incomplete_models']==incomplete and result['missing_models']==len(missing),'ancestry_unknown')
        require(not result['oof_eligible'] and not result['lineage_complete'],'unknown_not_admitted')
    return dict(saved_models_checked=len(names),fitted_model_population_checks=len(report['saved_score_exposure']),certified_oof_rows=0)


def check_schedule(schedule):
    k=schedule['fold_count'];all_folds=set(range(k));wanted={frozenset()}|{frozenset([i]) for i in range(k)}|{frozenset(p) for p in itertools.combinations(range(k),2)}
    require({frozenset(v['excluded_folds']) for v in schedule['ranker_jobs'].values()}==wanted,'schedule_jobs')
    for job in schedule['ranker_jobs'].values():require(set(job['training_folds'])==all_folds-set(job['excluded_folds']),'job_complement')
    uses=Counter();checked=0
    for outer in schedule['outer_folds']:
        heldout=outer['gate_test_fold'];require(heldout not in schedule['ranker_jobs'][outer['test_score_job']]['training_folds'],'outer_score')
        require({r['gate_training_fold'] for r in outer['gate_training_scores']}==all_folds-{heldout},'inner_coverage')
        for row in outer['gate_training_scores']:
            job=schedule['ranker_jobs'][row['score_job']]
            require(set(job['excluded_folds'])=={heldout,row['gate_training_fold']},'inner_ancestry_exclusions')
            uses[row['score_job']]+=1;checked+=1
    require(len(uses)==10 and set(uses.values())=={2} and checked==20,'symmetric_roles')
    require(schedule['ranker_fits_with_identical_pair_reuse']==16 and schedule['ranker_fits_without_pair_reuse']==26 and schedule['gate_fits']==6,'fit_budget')
    require(checksum({key:value for key,value in schedule.items() if key!='schedule_sha256'})==schedule['schedule_sha256'],'schedule_hash')
    require(not schedule['fit_permission'] and not schedule['calibration_permission'] and not schedule['final_test_permission'],'schedule_permissions')
    return dict(outer_folds=5,inner_score_roles=20,conditional_unique_ranker_fits=16,unshared_ranker_fits=26,gate_fits=6,new_fits=0)


def verify(commit):
    committed(HERE/'verify_oof.py',commit);save(ROOT/'verification-reservation.json',dict(code_commit=commit,new_fits=0))
    report=read(ROOT/'audit.json');plan=authenticate(report['plan_commit'])
    for name,digest in report['metadata_hashes'].items():require(sha(ROOT/name)==digest,'audit_artifacts')
    rows,indices=reconstruct_metadata();components=graph_components(rows);folds=read(ROOT/'folds.json')
    expected=independently_allocate(rows,components);require(expected==folds['union'],'union_graph_and_heap')
    check_summary(rows,expected,report['union'])
    for arm,positions in indices.items():
        subset=[rows[i] for i in positions];expected=independently_allocate(subset,components)
        require(expected==folds['arms'][arm],'retained_arm_graph');check_summary(subset,expected,report['arms'][arm])
    exposure=check_exposures(rows,indices,components,plan,report);schedule=check_schedule(report['nested_schedule'])
    old=subprocess.run([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(old.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','old_integrity')
    checkpoints=json.loads(committed(Path('research/issue-33-loss-balance/evaluation-binding-v1.json'),'5fcbb79afcf109391f75e6e880228c259d11f4a4'))['models']
    for model in checkpoints:require(sha(model['path'])==model['sha256'],'old_checkpoint')
    head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    require(head==plan['current_sakura_input_head'] and not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'input_checkout')
    result=dict(status='passed',code_commit=commit,metadata_rows=75000,graph_components=len(set(components.values())),fold_population_checks=3,
        exposure=exposure,nested_schedule=schedule,original_integrity=integrity,old_checkpoints_unchanged=len(checkpoints),
        audit_sha256=sha(ROOT/'audit.json'),sakura_input_head=head,sakura_input_clean=True,new_fits=0,new_inference=0,final_test=False)
    save(ROOT/'verification.json',result);print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);verify(parser.parse_args().commit)
