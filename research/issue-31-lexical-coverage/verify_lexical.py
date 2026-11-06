"""Independent substring selection and breadth-first lexical-cover replay."""
import argparse
from collections import Counter,defaultdict,deque
import json
import sys
import time
import unittest

from sakura_rerank.data.contracts import canonical_json_hash
from analyze_lexical import dictionary,summarize
from lexical_common import HERE,ROOT,authenticate,pairs,read,require,save,sha


def copy_reading(char):
    if '\u3041'<=char<='\u3096' or char=='ー':return char
    if '\u30a1'<=char<='\u30f6':return chr(ord(char)-96)
    return None


def reference(target,reading,first,copy):
    queue=deque([(0,0,0)]);seen={(0,0)}
    while queue:
        a,b,steps=queue.popleft()
        if (a,b)==(len(target),len(reading)):return steps
        if a==len(target):continue
        candidates=[]
        for surface,values in first.get(target[a],()):
            if target.startswith(surface,a):candidates.extend((surface,value) for value in values)
        if copy:
            value=copy_reading(target[a])
            if value is not None:candidates.append((target[a],value))
        for surface,value in candidates:
            next_state=(a+len(surface),b+len(value))
            if next_state not in seen and reading.startswith(value,b):seen.add(next_state);queue.append((*next_state,steps+1))
    return None


def verify(commit):
    started=time.monotonic();plan,guard=authenticate(commit);expected=pairs();analysis=read(ROOT/'analysis.json')
    require(analysis['plan_commit']==commit and analysis['plan_sha256']==sha(HERE/'plan-v1.json'),'analysis_binding')
    for name,digest in analysis['artifacts'].items():require(sha(ROOT/name)==digest,'analysis_artifact')
    require(read(ROOT/'pairs.json')['rows']==expected,'source_pair_replay')
    selected,metadata=dictionary([r['target'] for r in expected],independent=True)
    require(selected==read(ROOT/'relevant-lexicon.json')['rows'] and metadata['relevant_index_sha256']==analysis['dictionary']['relevant_index_sha256'],'independent_index_selection')
    by_surface={r['surface']:r['readings'] for r in selected};first=defaultdict(list)
    for surface,values in by_surface.items():first[surface[0]].append((surface,values))
    observed=read(ROOT/'lexical-rows.json')['rows'];require(len(observed)==1340,'lexical_pair_count')
    counters=defaultdict(Counter);witnesses=0;covered=0;work_bounds=0
    for pair,row in zip(expected,observed,strict=True):
        target,reading=pair['target'],pair['reading'];indexed=by_surface.get(target,[])
        require(all(row[k]==v for k,v in pair.items() if k not in ('target','reading'))
            and row['pair_sha256']==canonical_json_hash(pair) and row['target_sha256']==canonical_json_hash(target)
            and row['reading_sha256']==canonical_json_hash(reading) and row['surface_indexed']==bool(indexed)
            and row['indexed_readings_count']==len(indexed) and row['indexed_readings_sha256']==canonical_json_hash(indexed)
            and row['exact_pair']==(reading in indexed),'pair_dictionary_identity')
        for condition,copy in (('dictionary_only',False),('dictionary_plus_literal',True)):
            value=row[condition]
            if value['status']=='work_bound':
                require(value['witness'] is None and value['minimum_units'] is None
                    and (value['visited_states']>=plan['limits']['states_per_pair'] or value['examined_edges']>plan['limits']['edges_per_pair']),'explicit_work_bound')
                work_bounds+=1;continue
            minimum=reference(target,reading,first,copy)
            require(value['minimum_units']==minimum and value['status']==('absent' if minimum is None else 'covered'),'independent_cover')
            if minimum is None:
                require(value['witness'] is None,'absence_has_no_witness');continue
            covered+=1;witness=value['witness'];require(len(witness)==minimum,'minimum_witness')
            a=b=0
            for edge in witness:
                require(edge['target_start']==a and edge['reading_start']==b and edge['target_end']>a and edge['reading_end']>b,'witness_continuity')
                x,y=target[a:edge['target_end']],reading[b:edge['reading_end']]
                if edge['kind']=='dictionary':require(y in by_surface.get(x,[]),'witness_dictionary_pair')
                else:require(copy and edge['kind']=='literal_kana' and len(x)==1 and copy_reading(x)==y,'witness_literal')
                a,b=edge['target_end'],edge['reading_end'];witnesses+=1
            require((a,b)==(len(target),len(reading)),'witness_complete')
        if pair['condition']=='dictionary_control':terminal='dictionary_reading_control'
        elif row['dictionary_plus_literal']['status']=='work_bound':terminal='lexical_work_bound'
        elif pair['native_presence']['32']:
            terminal='native_present_index_cover' if row['dictionary_plus_literal']['minimum_units'] is not None else 'native_present_outside_index_model'
        elif reading in indexed:terminal='native_missing_exact_entry'
        elif row['dictionary_plus_literal']['minimum_units'] is not None:terminal='native_missing_composed_index_cover'
        else:terminal='native_missing_no_index_cover'
        counters[pair['condition']][terminal]+=1
    require(summarize(observed)==analysis['census'],'aggregate_replay')
    for name,counts in counters.items():require(dict(counts)==analysis['census'][name]['terminal_counts'],'independent_terminal_census')
    require(guard.blocked==0,'forbidden_read')
    proof=dict(status='passed',plan_commit=commit,analysis_sha256=sha(ROOT/'analysis.json'),pairs_verified=1340,
        substring_selection_independent=True,relevant_dictionary_rows_verified=len(selected),graph_conditions_verified=2680,
        covered_graphs=covered,witness_units_verified=witnesses,work_bound_graphs=work_bounds,
        terminal_censuses_independently_verified=4,forbidden_data_reads=guard.blocked,elapsed_seconds=round(time.monotonic()-started,3),
        new_native_requests=0,new_model_calls=0,training_admission=False,gold_admission=False,final_test=False)
    save(ROOT/'verification.json',proof);return proof


def tests():
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    value=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-tests.json',value);require(result.wasSuccessful() and not result.skipped,'full_tests_failed');return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('verify','tests'));parser.add_argument('--commit');args=parser.parse_args()
    try:result=tests() if args.stage=='tests' else verify(args.commit)
    except Exception as error:
        value=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith('lexical_audit_'):value['error_code']=str(error)
        print(json.dumps(value),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
