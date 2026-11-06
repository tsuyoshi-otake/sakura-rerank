"""Project a fixed historical selector into the new research component space.

Old cache labels and protected labels are never decoded. Full historical source
relations remain conservative, including unknown-role and selection exposures.
No score generation, fitting, threshold selection or data admission occurs.
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS,tensor_hash,verify_chain
from sakura_rerank.data.consumed_source import PERMITTED,unit_key
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.growth_isolation import historical_input_metadata
from sakura_rerank.data.reconstruction_graph import build_source_graph
from sakura_rerank.data.relation_witnesses import component_labels
from sakura_rerank.gate_oof import score_exposure
from lineage_common import HERE,ROOT,OLD,SOURCE,CACHE,OOF,FROZEN,authenticate,legacy,read,rows,save,sha,source_inventory,write_rows

SPLIT=re.compile(rb'(?<!\\)"split":"([a-z-]+)"')


def require(value,code):
    if not value:raise ValueError('lineage_'+code)


def plan():
    h=legacy();h.verify_inputs();source_inventory()
    report=read('reports/issue-29-distill-gate.json')
    inputs={str(p.relative_to(Path.cwd())):v for p,v in h.EXTRA_INPUTS.items()}
    inputs.update({(h.SRC21/p).relative_to(Path.cwd()).as_posix():v for p,v in h.gate.INPUTS.items()})
    for name in ('parity','teacher-selection','crossfit','selection','decision-accuracy','final','export','decision','dev-eval'):
        key=name.replace('-','_')+'_sha256'
        require(sha(OLD/(name+'.json'))==report['artifacts'][key],'old_report_link')
        inputs[(OLD/(name+'.json')).as_posix()]=report['artifacts'][key]
    for folder,prefix in (('nested','C2'),('students','C2KD')):
        key='nested_teacher_sha256' if folder=='nested' else 'student_oof_sha256'
        for seed,digest in report['artifacts'][key].items():inputs[(OLD/folder/(prefix+'-s'+seed+'.npz')).as_posix()]=digest
    inputs[(OLD/'teachers.npz').as_posix()]=report['artifacts']['teachers_sha256']
    inputs[(OLD/'final/student-s20260814.pt').as_posix()]=report['final_student']['checkpoint_sha256']
    inputs[(OLD/'student-fp32.onnx').as_posix()]=report['export']['onnx']['fp32']['sha256']
    for name,digest in read(h.SRC21/'selection.json')['oof_files'].items():
        inputs[(h.SRC21/'oof'/name).relative_to(Path.cwd()).as_posix()]=digest
    paths=[FROZEN,'reports/issue-29-distill-gate.json',h.SRC21/'prepare.report.json',h.SRC21/'cache-check.report.json',
        SOURCE/'scope-v1/report.json',SOURCE/'scope-v1/execution.json',SOURCE/'source-report.json',SOURCE/'preparation-checks.json',
        SOURCE/'numeric-r2/report.json',SOURCE/'numeric-r2/execution.json',OOF/'audit.json',OOF/'verification.json',
        OOF/'training-identities.json',OOF/'folds.json',OOF/'model-exposure.json','reports/issue-34-oof-design-v1.json',
        'research/issue-33-loss-balance/evaluation-binding-v1.json']
    paths += [CACHE/name for name in ('manifest.json','arrays.npz','row-receipts.jsonl','cohort-indices.json')]
    cohort=read(SOURCE/'scope-v1/report.json');source=read(SOURCE/'source-report.json')
    paths += [SOURCE/'scope-v1/cohorts'/cohort['artifacts'][name]['path'] for name in ('unit-decisions','terminals')]
    paths += [SOURCE/'source'/source['artifacts']['wikipedia-coverage']['path']]
    for path in paths:
        path=Path(path);path=path.relative_to(Path.cwd()) if path.is_absolute() else path
        inputs[path.as_posix()]=sha(path)
    for path,digest in inputs.items():require(sha(path)==digest,'planned_artifact')
    # Pin the actual imported repository modules, including transitive history adapters.
    code={p.as_posix():sha(p) for module in list(sys.modules.values())
        if (value:=getattr(module,'__file__',None)) and (p:=Path(value).resolve()).is_relative_to(Path.cwd())
        and p.suffix=='.py'}
    code={Path(p).relative_to(Path.cwd()).as_posix():v for p,v in code.items()}
    code.update({p.as_posix():sha(p) for p in HERE.glob('*.py')})
    code['src/sakura_rerank/research_tiny.py']=sha('src/sakura_rerank/research_tiny.py')
    # The generated historical harness is an input, not a newly tracked source file.
    for path in list(code):
        if path.startswith('data/'):
            inputs[path]=code.pop(path)
    head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    require(not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'input_not_clean')
    spec=dict(kind='fixed_selector_ancestry_plan',issues=[34,33,32,35],parent_issue=1,previous_commit='6eb9b6ea26f17c4a5ff9de6cc8909f40900b4483',
        inputs=inputs,code=code,training_rows=75000,old_frozen_rows=17880,old_cache_input_rows=14304,
        policy='Authenticate all recorded fitting, teacher, initialization and preprocessing sources. Conservatively include all218189 historical nodes for selection exposure; project through unchanged complete consumed-source closure plus exact numeric input equality.',
        source_exposure='Source closure proves only recorded relation disconnection. The75000 rows were already consumed in research; they are not fresh evaluation, calibration or Test.',
        preprocessing='Fixed character hash, fixed bounds and row-local features/cost-gap; no fitted vocabulary or pretrained initialization in #21 C2/#29.',
        limits=dict(nodes=1000000,edges=4000000,wall_seconds=1200,retries=0),
        new_fits=0,new_inference=0,threshold_selection=False,calibration=False,final_test=False,gold_admission=False,
        safety_limit=.0025,sakura_input_head=head,sakura_input_clean=True,
        expected_effect='Resolve whether a fixed external selector removes the need for16/26 new ranker fits; gate fitting still needs its own binding and independent evaluation.',
        expected_cost='One bounded reconstruction of813852 active metadata nodes plus linear witness and14304 numeric-input checks; no GPU, download or native conversion.')
    save(HERE/'plan-v1.json',spec)
    return dict(stage='planned',inputs=len(inputs),code_files=len(code),plan_sha256=sha(HERE/'plan-v1.json'))


def ancestry():
    h=legacy();h.verify_inputs()
    final=read(OLD/'final.json');decision=read(OLD/'decision-accuracy.json');selected=read(OLD/'selection.json');export=read(OLD/'export.json')
    require(final['decision_accuracy_sha256']==sha(OLD/'decision-accuracy.json') and decision['selection_sha256']==sha(OLD/'selection.json')
        and decision['crossfit_sha256']==sha(OLD/'crossfit.json') and selected['crossfit_sha256']==sha(OLD/'crossfit.json'),'selection_chain')
    require(export['final_sha256']==sha(OLD/'final.json') and export['checkpoint_sha256']==final['checkpoint_sha256']
        and final['epoch']==selected['epoch']==15 and final['seed']==selected['seed']==20260814,'final_chain')
    teachers=read(OLD/'teacher-selection.json')
    require(teachers['teachers_sha256']==sha(OLD/'teachers.npz') and teachers['final']['epochs']=={str(k):v for k,v in h.FINAL_EPOCHS.items()},'teacher_chain')
    values={}
    for seed in h.SEEDS:
        with np.load(h.SRC21/'oof'/f'C2-s{seed}.npz',allow_pickle=False) as archive:
            values[seed]=archive['scores']
        require(values[seed].shape==(20,12516,6) and np.isfinite(values[seed]).all(),'teacher_shape')
    with np.load(OLD/'teachers.npz',allow_pickle=False) as archive:teacher=archive['final']
    require(teacher.dtype==np.float64 and np.array_equal(h.final_teacher(values),teacher),'teacher_replay')
    manifest=read(h.V1_DIR/'train-dev-cache.manifest.json');prep=read(h.SRC21/'prepare.report.json')
    require(manifest['source']['sha256']==sha(FROZEN)==prep['inputs']['frozen_split_sha256']
        and prep['feature_and_gold_alignment_verified'] and prep['train_rows']==12516,'cache_source_binding')
    return dict(final_teacher_rows=12516,teacher_seeds=3,teacher_epochs=[9,8,10],teacher_bitwise_reproduced=True,
        final_epoch=15,final_seed=20260814,random_initialization=True,pretrained_weight_parents=0,
        learned_preprocessing_parents=0,recorded_selection_chain_authenticated=True,
        checkpoint_sha256=final['checkpoint_sha256'],onnx_sha256=export['onnx']['fp32']['sha256'],
        historical_report_sha256=sha('reports/issue-29-distill-gate.json'),prior_old_train_gate_oof_independence_certified=False),h


def source_projection(ledger):
    inventory=source_inventory();original,_,roles,_,_=inventory.load_inventory()
    require(len(original.records)==833600 and len(roles)==218189,'history_population')
    frozen={};frozen_ids=defaultdict(list);lookup={r['stable_id']:r for r in original.records if r['population']=='historical'}
    with FROZEN.open('rb') as stream:
        for line in stream:
            split=SPLIT.findall(line);require(len(split)==1,'split_marker')
            role=split[0].decode('ascii');require(role in ('train','dev','final-holdout'),'split_role')
            row=historical_input_metadata(line);key=row['stable_id']
            require(key not in frozen and lookup.get(key)==row and roles[key]=='frozen_'+role,'history_identity')
            frozen[key]=role;frozen_ids[role].append(key)
    require(Counter(frozen.values())=={'train':12516,'dev':1788,'final-holdout':3576},'frozen_counts')
    selected={r['origin']['stable_id']:r for r in ledger};require(len(selected)==75000,'selected_identity')
    cohort=read(SOURCE/'scope-v1/report.json');source=read(SOURCE/'source-report.json')
    decisions={r['unit_id']:r['status'] for r in rows(SOURCE/'scope-v1/cohorts/unit-decisions.jsonl.gz')}
    proposed={r['stable_id'] for r in rows(SOURCE/'scope-v1/cohorts/terminals.jsonl.gz')}
    require(len(decisions)==222619 and len(proposed)==198094 and set(selected)<=proposed,'scope_membership')
    original.records.extend(rows(SOURCE/'source'/source['artifacts']['wikipedia-coverage']['path']))
    active=[]
    for row in original.records:
        key=row['stable_id'];permitted=decisions.get(unit_key(row['source']))==PERMITTED
        if row['population']=='historical' or ((key in proposed or row['population']=='source_coverage') and permitted):active.append(row)
    del original,lookup
    require(len(active)==cohort['final_scope_audit']['records']==813852,'active_scope')
    print(json.dumps(dict(stage='rebuild_source_closure',nodes=len(active),history=len(roles))),flush=True)
    graph=build_source_graph(active);labels=component_labels(graph)
    members=defaultdict(list)
    for i,label in enumerate(labels):members[label].append(i)
    history_labels={labels[i] for i,r in enumerate(graph.records) if r['population']=='historical'}
    counts=Counter();components={};projected=[];numeric=set()
    for label,indices in members.items():
        populations={graph.records[i]['population'] for i in indices}-{'source_coverage'}
        counts['+'.join(sorted(populations)) or 'source_only']+=1
        if populations=={'train'}:
            component=canonical_json_hash(sorted(graph.records[i]['stable_id'] for i in indices))
            for i in indices:
                row=graph.records[i];key=row['stable_id']
                if key not in selected:continue
                receipt=selected[key];origin=receipt['origin']
                require(origin['component_id']==component and origin['source_metadata_sha256']==canonical_json_hash(row['source'])
                    and origin['original_input_sha256']==row['input_hash'],'selected_component_identity')
                components[key]=component;numeric.add(receipt['input_tensor_sha256'])
                projected.append(dict(node=i,index=receipt['index'],stable_id=key,numeric=receipt['input_tensor_sha256'],source_component=component))
    require(len(components)==75000 and dict(counts)==cohort['final_scope_audit']['population_component_counts'],'consumption_closure_replay')
    require(len(members)==cohort['final_scope_audit']['components'] and max(map(len,members.values()))==cohort['final_scope_audit']['largest_component'],'closure_counts')
    # Compact authenticated witnesses support an independent traversal without reopening labels.
    write_rows(ROOT/'nodes.jsonl.gz',(dict(stable_id=r['stable_id'],population=r['population']) for r in graph.records))
    with (ROOT/'edges.npz').open('xb') as stream:np.savez_compressed(stream,left=np.asarray(graph.left),right=np.asarray(graph.right),labels=np.asarray(labels,dtype=np.int32))
    save(ROOT/'selected-projection.json',sorted(projected,key=lambda r:r['index']))
    save(ROOT/'frozen-identities.json',frozen_ids)
    return dict(nodes=len(graph.records),edges=len(graph.left),components=len(members),historical_nodes=len(roles),
        historical_components=len(history_labels),population_components=dict(counts),frozen_rows=len(frozen),frozen_counts=dict(Counter(frozen.values())),
        selected_rows=len(components),selected_source_components=len(set(components.values())),selected_history_connected=0,
        original_quarantine_preserved=True,closure_replayed=True),numeric,frozen_ids


def numeric_projection(h,new_numeric,ids):
    private=[];overlap=Counter();cache=h.V1_DIR/'train-dev-cache.npz'
    with np.load(cache,allow_pickle=False) as archive,np.load(h.SRC21/'costs.npz',allow_pickle=False) as costs:
        for split in ('train','dev'):
            # Explicit input-only NPZ reads: no gold/correct/equivalence array access.
            arrays={name:archive[split+'_'+name] for name in MODEL_FIELDS}
            arrays['features']=h.h21.recipe_features(arrays,costs[split],'C2')
            require(len(arrays['reading_lengths'])==len(ids[split]),'old_numeric_order')
            for i,key in enumerate(ids[split]):
                value=tensor_hash(arrays,i,MODEL_FIELDS);hit=value in new_numeric;overlap[split]+=hit
                private.append(dict(stable_id=key,split=split,numeric=value))
    save(ROOT/'historical-numeric.json',private)
    return dict(input_rows=len(private),rows_by_split={k:len(ids[k]) for k in ('train','dev')},
        exact_numeric_matches=dict(overlap),old_label_arrays_decoded=0,holdout_numeric_arrays_decoded=0)


def execute(commit):
    started=time.monotonic();spec=authenticate(commit);save(ROOT/'reservation.json',dict(plan_commit=commit,new_fits=0,new_inference=0))
    old,h=ancestry();manifest=read(CACHE/'manifest.json')
    ledger=verify_chain((CACHE/'row-receipts.jsonl').read_bytes(),75000,manifest['row_chain_head'])
    require(manifest['training_eligible'] is False and manifest['independent_gold_eligible'] is False,'admission_changed')
    source,numeric,ids=source_projection(ledger);numeric_report=numeric_projection(h,numeric,ids)
    require(not any(numeric_report['exact_numeric_matches'].values()),'numeric_overlap_do_not_certify')
    models=read(OOF/'model-exposure.json');key=old['checkpoint_sha256']
    require(models[key]['lineage_complete'] is False,'prior_unknown_root_changed')
    # Empty projected exposure is justified by the full conservative closure, not by missing history.
    models[key]=dict(fit_components=[],selection_components=[],parents=[],lineage_complete=True)
    universe=set(read(OOF/'folds.json')['union']['row_component'].values())
    proof=score_exposure(key,universe,models);require(proof['oof_eligible'],'fixed_selector_projection')
    save(ROOT/'projected-model-exposure.json',models)
    artifacts={p.name:sha(p) for p in ROOT.iterdir() if p.name in ('nodes.jsonl.gz','edges.npz','selected-projection.json','frozen-identities.json','historical-numeric.json','projected-model-exposure.json')}
    result=dict(kind='fixed_selector_recorded_lineage_audit',status='recorded_ancestry_projected_no_fit_permission',plan_commit=commit,
        ancestry=old,source=source,numeric=numeric_report,projected_reference29=proof,metadata_artifacts=artifacts,
        fixed_ranker_new_fits_required=0,conditional_gate_fits=6,
        limitations=['Disjointness is relative to the recorded source/teacher/selection closure, not unrecorded human experimentation.',
            'The75000-row pool has already informed research. This is not a fresh independent evaluation or calibration cohort.',
            'Existing GPU scores have unresolved CPU numerical parity; no saved score is certified by this metadata audit.',
            'Source reconstruction labels are weak; complete ancestry does not certify Japanese conversion intent or Gold.',
            'Old train gate OOF results remain subject to outer-fold selection/teacher dependencies. This audit does not repair them.'],
        original_safety_limit=.0025,training_eligible=False,independent_gold_eligible=False,new_fits=0,new_inference=0,
        threshold_selection=False,calibration=False,final_test=False,production_change=False,
        elapsed_seconds=round(time.monotonic()-started,3))
    authenticate(commit);save(ROOT/'audit.json',result)
    return {k:result[k] for k in ('status','source','numeric','projected_reference29','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','execute'));parser.add_argument('--commit')
    args=parser.parse_args();print(json.dumps(plan() if args.stage=='plan' else execute(args.commit)))
