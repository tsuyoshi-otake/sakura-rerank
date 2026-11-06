"""Direct verification with independent graph traversal and teacher arithmetic."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from sakura_rerank.gate_oof import score_exposure
from lineage_common import HERE,ROOT,OLD,SOURCE,CACHE,OOF,authenticate,committed,read,rows,save,sha


def require(value,code):
    if not value:raise ValueError('lineage_verification_'+code)


def encoded(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()


def checksum(value):return hashlib.sha256(encoded(value)).hexdigest()


def artifact_links(plan):
    source=read(SOURCE/'source-report.json');scope=read(SOURCE/'scope-v1/report.json');prep=read(SOURCE/'preparation-checks.json')
    for base,report,names in ((SOURCE/'source',source,['wikipedia-coverage']),
        (SOURCE/'scope-v1/cohorts',scope,['unit-decisions','terminals'])):
        for name in names:
            item=report['artifacts'][name];path=(base/item['path']).as_posix()
            require(plan['inputs'][path]==item['sha256']==sha(path),'original_parent_artifact_link')
    require(prep['status']=='passed' and prep['scope_report_sha256']==sha(SOURCE/'scope-v1/report.json')
        and prep['cache_manifest_sha256']==sha(CACHE/'manifest.json'),'original_preparation_link')
    execution=read(SOURCE/'scope-v1/execution.json')
    require(execution['status']=='complete' and execution['report_sha256']==sha(SOURCE/'scope-v1/report.json'),'scope_execution')
    require(read(OOF/'verification.json')['audit_sha256']==sha(OOF/'audit.json'),'prior_oof_verification')


def graph_check(audit):
    nodes=list(rows(ROOT/'nodes.jsonl.gz'));require(len(nodes)==audit['source']['nodes'],'nodes')
    require(len({r['stable_id'] for r in nodes})==len(nodes),'duplicate_nodes')
    with np.load(ROOT/'edges.npz',allow_pickle=False) as archive:edges={key:archive[key] for key in archive.files}
    require(set(edges)=={'left','right','labels'} and len(edges['left'])==len(edges['right'])==audit['source']['edges'],'edge_counts')
    adjacency=[[] for _ in nodes]
    for a,b in zip(edges['left'],edges['right']):
        a,b=int(a),int(b);require(0<=a<b<len(nodes),'edge_bounds');adjacency[a].append(b);adjacency[b].append(a)
    component=[-1]*len(nodes);keys={};historical=set();population=Counter();sizes=[]
    for first in range(len(nodes)):
        if component[first]!=-1:continue
        stack=[first];component[first]=first;members=[];roles=set()
        while stack:
            current=stack.pop();members.append(current);roles.add(nodes[current]['population'])
            for other in adjacency[current]:
                if component[other]==-1:component[other]=first;stack.append(other)
        require(len({int(edges['labels'][i]) for i in members})==1,'saved_component_split')
        sizes.append(len(members));roles.discard('source_coverage');population['+'.join(sorted(roles)) or 'source_only']+=1
        if 'historical' in roles:historical.add(first)
        keys[first]=checksum(sorted(nodes[i]['stable_id'] for i in members))
    require(len(sizes)==len(set(map(int,edges['labels'])))==audit['source']['components'],'saved_component_merge')
    require(dict(population)==audit['source']['population_components'] and len(historical)==audit['source']['historical_components'],'source_populations')
    require(sum(r['population']=='historical' for r in nodes)==218189,'conservative_history_count')
    positions={r['stable_id']:i for i,r in enumerate(nodes)};frozen=read(ROOT/'frozen-identities.json')
    require({k:len(v) for k,v in frozen.items()}=={'train':12516,'dev':1788,'final-holdout':3576},'frozen_denominator')
    for ids in frozen.values():
        for key in ids:require(nodes[positions[key]]['population']=='historical','frozen_covered')
    projection=read(ROOT/'selected-projection.json');require(len(projection)==75000,'selected_count')
    previous='0'*64;selected_ids=[];source_components=set();new_numeric=set()
    with (CACHE/'row-receipts.jsonl').open('rb') as stream:
        for index,raw in enumerate(stream):
            row=json.loads(raw);origin=row['origin'];saved=projection[index]
            require(row['index']==index and row['previous_sha256']==previous,'receipt_order')
            previous=checksum({k:v for k,v in row.items() if k!='record_sha256'});require(previous==row['record_sha256'],'receipt_hash')
            node=saved['node'];require(saved['index']==index and saved['stable_id']==origin['stable_id']==nodes[node]['stable_id'],'identity_join')
            require(nodes[node]['population']=='train' and component[node] not in historical,'history_disconnection')
            require(keys[component[node]]==origin['component_id']==saved['source_component'],'component_hash')
            require(saved['numeric']==row['input_tensor_sha256'],'numeric_identity')
            require(origin['training_eligible'] is False and origin['independent_gold_eligible'] is False,'old_admission')
            selected_ids.append(origin['stable_id']);source_components.add(saved['source_component']);new_numeric.add(saved['numeric'])
    cache=read(CACHE/'manifest.json')
    require(len(selected_ids)==75000 and previous==cache['row_chain_head'] and checksum(selected_ids)==cache['source_order_sha256'],'receipt_population')
    require(len(source_components)==audit['source']['selected_source_components'],'source_component_count')
    old=read(ROOT/'historical-numeric.json');require(len(old)==14304 and not any(r['numeric'] in new_numeric for r in old),'numeric_overlap')
    require(Counter(r['split'] for r in old)=={'train':12516,'dev':1788},'numeric_denominator')
    return dict(nodes=len(nodes),edges=len(edges['left']),components=len(keys),frozen_covered=17880,selected_covered=75000,
        historical_connected=0,numeric_matches=0,selected_source_components=len(source_components)),old


def teacher_and_numeric(old_numeric):
    # Recompute the exact final teacher independently of the original ensemble helper.
    expected=np.zeros((12516,6),np.float64)
    for seed,epoch in zip((20260814,20261103,20261104),(9,8,10)):
        with np.load(f'data/generated/issue-21-retrain/oof/C2-s{seed}.npz',allow_pickle=False) as archive:
            expected+=archive['scores'][epoch-1].astype(np.float64)
    expected/=3
    with np.load(OLD/'teachers.npz',allow_pickle=False) as archive:
        require(np.array_equal(expected,archive['final']),'teacher_element_replay')
    names=('context_ids','context_lengths','reading_ids','reading_lengths','candidate_ids','candidate_lengths','features','candidate_mask')
    offset=0
    with (np.load('data/generated/sakura-rerank-tiny-v1-research/train-dev-cache.npz',allow_pickle=False) as archive,
          np.load('data/generated/issue-21-retrain/costs.npz',allow_pickle=False) as stored_costs):
        for split,count in (('train',12516),('dev',1788)):
            arrays={key:archive[split+'_'+key] for key in names};mask=arrays['candidate_mask'];cost=stored_costs[split]
            minimum=np.min(np.where(mask,cost,np.inf),axis=1,keepdims=True)
            gap=np.where(mask,-np.log1p(np.maximum(cost-minimum,0.0)/1000.0),0.0).astype(np.float32)
            arrays['features']=np.concatenate((arrays['features'],gap[...,None]),axis=2)
            for index in range(count):
                digest=hashlib.sha256()
                for key in names:
                    value=np.asarray(arrays[key][index]);digest.update(encoded([key,value.dtype.str,list(value.shape)]));digest.update(value.tobytes(order='C'))
                require(digest.hexdigest()==old_numeric[offset+index]['numeric'] and old_numeric[offset+index]['split']==split,'numeric_replay')
            offset+=count
    return dict(teacher_elements=int(expected.size),teacher_exact=True,old_numeric_rows=offset,old_label_arrays_decoded=0)


def ancestry_graph(audit):
    r=read('reports/issue-29-distill-gate.json');models={};old=read(OOF/'model-exposure.json');root=audit['ancestry']['checkpoint_sha256']
    def add(key,parents=()):models[key]=dict(fit_components=[],selection_components=[],parents=list(parents),lineage_complete=True)
    selection21=read('data/generated/issue-21-retrain/selection.json')
    for key in selection21['oof_files'].values():add(key)
    selection21_sha=sha('data/generated/issue-21-retrain/selection.json');add(selection21_sha,selection21['oof_files'].values())
    for key in r['artifacts']['nested_teacher_sha256'].values():add(key)
    teacher_selection=r['artifacts']['teacher_selection_sha256'];add(teacher_selection,r['artifacts']['nested_teacher_sha256'].values())
    teacher=r['artifacts']['teachers_sha256'];add(teacher,[teacher_selection,selection21_sha])
    for key in r['artifacts']['student_oof_sha256'].values():add(key,[teacher_selection])
    crossfit=r['artifacts']['crossfit_sha256'];add(crossfit,r['artifacts']['student_oof_sha256'].values())
    selection=r['artifacts']['selection_sha256'];add(selection,[crossfit])
    decision=r['artifacts']['decision_accuracy_sha256'];add(decision,[selection,crossfit])
    add(root,[teacher,decision]);old.update(models)
    universe=set(read(OOF/'folds.json')['union']['row_component'].values())
    proof=score_exposure(root,universe,old)
    require(proof['lineage_complete'] and proof['oof_eligible'] and not proof['fit_overlap_components'] and not proof['selection_overlap_components'],'expanded_ancestry')
    # Unknown legacy roles were conservatively included in the closure, not called clean.
    save(ROOT/'expanded-model-exposure.json',old)
    return dict(nodes=len(models),projected=proof,conservative_historical_rows=218189,
        collapsed_root_verdict_matches=proof['oof_eligible']==audit['projected_reference29']['oof_eligible'])


def static_contracts():
    path=Path('research/issue-29-distill-gate/run.py');tree=ast.parse(path.read_bytes())
    body=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='distill_epochs')
    calls=[n for n in ast.walk(body) if isinstance(n,ast.Call)]
    require(any(isinstance(n.func,ast.Attribute) and n.func.attr=='build_model' and len(n.args)==1 and isinstance(n.args[0],ast.Constant) and n.args[0].value=='C2' for n in calls),'fresh_c2_constructor')
    require(not any(isinstance(n.func,ast.Attribute) and n.func.attr in ('load_state_dict','load','from_pretrained') for n in calls),'no_pretrained_student_load')
    tree=ast.parse(Path('research/issue-21-retrain/run.py').read_bytes())
    body=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='train_epochs')
    require(not any(isinstance(n,ast.Attribute) and n.attr in ('load_state_dict','load','from_pretrained') for n in ast.walk(body)),'no_pretrained_teacher_load')
    for path in HERE.glob('*.py'):
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec')
        used={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        unused=[a.asname or a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names if (a.asname or a.name.split('.')[0]) not in used]
        require(not unused,'unused_import')
    return dict(fresh_student_constructor=True,no_pretrained_student_load=True,no_pretrained_teacher_load=True,python_files=len(list(HERE.glob('*.py'))),syntax_import_checks=True)


def verify(commit):
    committed(HERE/'verify_lineage.py',commit);save(ROOT/'verification-reservation.json',dict(code_commit=commit))
    audit=read(ROOT/'audit.json');plan=authenticate(audit['plan_commit']);artifact_links(plan)
    for name,digest in audit['metadata_artifacts'].items():require(sha(ROOT/name)==digest,'saved_evidence_hash')
    graph,old_numeric=graph_check(audit);arithmetic=teacher_and_numeric(old_numeric);parents=ancestry_graph(audit)
    old=subprocess.run([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],capture_output=True,text=True,check=True,timeout=120)
    integrity=json.loads(old.stdout.strip().splitlines()[-1]);require(integrity['status']=='passed','old_integrity')
    checkpoints=read('research/issue-33-loss-balance/evaluation-binding-v1.json')['models']
    for model in checkpoints:require(sha(model['path'])==model['sha256'],'old_checkpoint')
    result=dict(status='passed',code_commit=commit,graph=graph,arithmetic=arithmetic,ancestry=parents,static=static_contracts(),
        original_integrity=integrity,old_checkpoints_unchanged=len(checkpoints),audit_sha256=sha(ROOT/'audit.json'),
        expanded_models_sha256=sha(ROOT/'expanded-model-exposure.json'),new_fits=0,new_inference=0,final_test=False)
    save(ROOT/'verification.json',result);print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);verify(parser.parse_args().commit)
