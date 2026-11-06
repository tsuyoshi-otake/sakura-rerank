"""Metadata-only contracts for component folds and nested gate-score provenance.

The caller authenticates source metadata and complete model ancestry. A valid
recorded proof is not a claim about unknown source relations, Gold or safety.
"""
from collections import Counter,defaultdict
import hashlib
import json
import re

MAX_ROWS=100_000
MAX_MODELS=64
_SHA=re.compile('[0-9a-f]{64}')


def _digest(value):
    if not isinstance(value,str) or _SHA.fullmatch(value) is None:
        raise ValueError('oof_hash_contract')
    return value


def component_folds(records,fold_count=5):
    """Join all recorded components and both input identities, without labels.

    Stable largest-component-first allocation balances total row count only.
    Source balance and statistical adequacy remain explicit audit results.
    """
    if type(fold_count) is not int or not 2<=fold_count<=10 or not 1<=len(records)<=MAX_ROWS:
        raise ValueError('oof_population_bound')
    keys=[];parents=list(range(len(records)));sizes=[1]*len(records);groups=[];seen={}
    def find(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,record in enumerate(records):
        if set(record)!={'row_key','component_key','original_input_key','numeric_input_key','group'}:
            raise ValueError('oof_identity_fields')
        key=_digest(record['row_key']);keys.append(key)
        group=record['group']
        if not isinstance(group,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',group):
            raise ValueError('oof_group_contract')
        groups.append(group)
        for field in ('component_key','original_input_key','numeric_input_key'):
            token=(field,_digest(record[field]))
            if token not in seen:seen[token]=i;continue
            a,b=find(i),find(seen[token])
            if a!=b:
                if sizes[a]<sizes[b]:a,b=b,a
                parents[b]=a;sizes[a]+=sizes[b]
    if len(set(keys))!=len(keys):raise ValueError('oof_duplicate_row_key')
    members=defaultdict(list)
    for i,key in enumerate(keys):members[find(i)].append(key)
    identities={root:hashlib.sha256(('gate-oof-component-v1\n'+'\n'.join(sorted(values))+'\n').encode()).hexdigest() for root,values in members.items()}
    components={identities[root]:sorted(values) for root,values in members.items()}
    row_component={key:identities[find(i)] for i,key in enumerate(keys)}
    totals=[0]*fold_count;assigned={}
    for key in sorted(components,key=lambda value:(-len(components[value]),value)):
        fold=min(range(fold_count),key=lambda f:(totals[f],f));assigned[key]=fold;totals[fold]+=len(components[key])
    row_fold={key:assigned[component] for key,component in row_component.items()}
    source_counts=[Counter() for _ in range(fold_count)]
    for key,group in zip(keys,groups):source_counts[row_fold[key]][group]+=1
    return dict(row_component=row_component,row_fold=row_fold,component_sizes={k:len(v) for k,v in components.items()},
        fold_sizes=totals,fold_group_counts=[dict(c) for c in source_counts],fold_count=fold_count,
        independent_source_certified=False,fit_permission=False)


def score_exposure(model_key,excluded_components,models):
    """Check all fitting/selection and initialization/teacher ancestors.

    Incomplete or missing lineage produces an explicit ineligible result.
    Cycles and malformed metadata fail closed rather than dropping an ancestor.
    The caller includes the prediction fold AND outer gate-test fold in excluded.
    """
    _digest(model_key)
    if not isinstance(models,dict) or not 1<=len(models)<=MAX_MODELS:
        raise ValueError('oof_model_bound')
    if not isinstance(excluded_components,(set,frozenset)) or not 1<=len(excluded_components)<=MAX_ROWS:
        raise ValueError('oof_exclusion_bound')
    for value in excluded_components:_digest(value)
    for key,model in models.items():
        _digest(key)
        if (not isinstance(model,dict) or set(model)!={'fit_components','selection_components','parents','lineage_complete'}
                or type(model['lineage_complete']) is not bool):
            raise ValueError('oof_model_contract')
        for field in ('fit_components','selection_components','parents'):
            values=model[field];limit=MAX_MODELS if field=='parents' else MAX_ROWS
            if not isinstance(values,(list,tuple,set,frozenset)) or len(values)>limit or len(set(values))!=len(values):
                raise ValueError('oof_ancestry_bound')
            for value in values:_digest(value)
    active=set();visited=set();missing=set();incomplete=set();fit=set();selection=set()
    def visit(key):
        if key in active:raise ValueError('oof_ancestry_cycle')
        if key in visited:return
        if key not in models:missing.add(key);return
        active.add(key);model=models[key]
        if not model['lineage_complete']:incomplete.add(key)
        fit.update(set(model['fit_components'])&excluded_components)
        selection.update(set(model['selection_components'])&excluded_components)
        for parent in model['parents']:visit(parent)
        active.remove(key);visited.add(key)
    visit(model_key)
    overlap=fit|selection;unknown=bool(missing or incomplete)
    eligible=not overlap and not unknown
    return dict(status='eligible_recorded_provenance' if eligible else 'overlap' if overlap else 'unknown_lineage',
        oof_eligible=eligible,overlap_components=len(overlap),fit_overlap_components=len(fit),
        selection_overlap_components=len(selection),known_models_visited=len(visited),missing_models=len(missing),
        incomplete_models=len(incomplete),lineage_complete=not unknown,independent_source_certified=False)


def nested_schedule(fold_count=5):
    """Plan exclusion sets only: no model training or ancestry certification.

    Symmetric inner fits may be shared only when the whole training identity
    (rows, initialization/teachers, preprocessing, order, seed and recipe) matches.
    """
    if type(fold_count) is not int or not 3<=fold_count<=10:
        raise ValueError('oof_nested_fold_bound')
    def job(excluded):return 'exclude-'+('-'.join(map(str,sorted(excluded))) if excluded else 'none')
    jobs={};outer=[]
    for heldout in range(fold_count):
        single=[heldout];jobs[job(single)]=dict(excluded_folds=single,training_folds=[i for i in range(fold_count) if i!=heldout])
        inner=[]
        for validation in range(fold_count):
            if validation==heldout:continue
            pair=sorted((heldout,validation))
            jobs[job(pair)]=dict(excluded_folds=pair,training_folds=[i for i in range(fold_count) if i not in pair])
            inner.append(dict(gate_training_fold=validation,score_job=job(pair)))
        outer.append(dict(gate_test_fold=heldout,test_score_job=job(single),gate_training_scores=inner))
    jobs[job([])]=dict(excluded_folds=[],training_folds=list(range(fold_count)))
    payload=dict(fold_count=fold_count,ranker_jobs=jobs,outer_folds=outer,
        final_gate_training_scores=[dict(gate_training_fold=i,score_job=job([i])) for i in range(fold_count)],
        final_ranker_job=job([]),ranker_fits_with_identical_pair_reuse=len(jobs),
        ranker_fits_without_pair_reuse=fold_count+fold_count*(fold_count-1)+1,gate_fits=fold_count+1,
        pair_reuse_requires_complete_fit_identity=True,fit_permission=False,calibration_permission=False,final_test_permission=False)
    payload['schedule_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return payload
