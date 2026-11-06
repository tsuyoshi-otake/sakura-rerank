"""Add explicit source-only exposure without repeating native conversion."""
import argparse
from collections import Counter
import json
import time

from sakura_rerank.data.reconstruction_graph import build_source_graph
from sakura_rerank.data.source_exposure import exposed_source_inputs
from consume35_common import HERE, PAST, ROOT, authenticate, committed, read, save, sha
from isolate_consumption import history_records

BINDING=HERE/'source-exposure-binding-v1.json'


def seal():
    history=read(ROOT/'history-report.json');old=read(HERE/'history-binding-v1.json')
    authenticate(old['plan_commit'])
    files=[ROOT/name for name in ('consumed-slots.json','source-relations.json','history-report.json','native-report.json','source-exposure-reproducer.json')]
    code=[HERE/'source_exposure_audit.py',HERE/'isolate_consumption.py',
          'src/sakura_rerank/data/source_exposure.py','src/sakura_rerank/data/reconstruction_graph.py',
          'src/sakura_rerank/data/relation_witnesses.py','tests/test_source_exposure.py']
    save(BINDING,dict(kind='explicit_consumed_source_exposure_binding',plan_commit=old['plan_commit'],
        original_history_commit=history['binding_commit'],exposed_sources=100,semantics='All previously decoded pilot sources, including invalid readings.',
        inputs={str(p).replace('\\','/'):sha(p) for p in files},code={str(p).replace('\\','/'):sha(p) for p in code},
        old_results_retained=True,native_retries=0,restore_exclusions=False))
    return dict(status='sealed',binding_sha256=sha(BINDING))


def run(commit):
    bound=json.loads(committed(BINDING,commit));authenticate(bound['plan_commit'])
    for path,digest in {**bound['inputs'],**bound['code']}.items():
        if sha(path)!=digest:raise ValueError('source_exposure_bound_bytes_changed')
    for path in bound['code']:committed(path,commit)
    save(ROOT/'source-exposure-reservation.json',dict(binding_commit=commit,exposed_sources=100,native_retries=0))
    start=time.monotonic();previous,_=history_records();rows=read(ROOT/'consumed-slots.json')['rows']
    records=list(previous)
    for row in rows:
        if row['source_coverage'] is not None:records.append(row['source_coverage'])
        records.extend({k:r[k] for k in ('stable_id','population','source','input_hash')} for r in row['inputs'])
    exposed=[r['stable_id'] for r in read(PAST/'decoded-pilot.json')['source_coverage']]
    print(json.dumps(dict(stage='source_exposure_forward',nodes=len(records),exposed_sources=len(exposed))),flush=True)
    graph=build_source_graph(records);extra=exposed_source_inputs(graph,exposed);del graph
    print(json.dumps(dict(stage='source_exposure_reverse',nodes=len(records))),flush=True)
    reverse=build_source_graph(list(reversed(records)))
    if extra!=exposed_source_inputs(reverse,list(reversed(exposed))):raise ValueError('source_exposure_reverse_parity')
    del reverse
    old=read(ROOT/'source-relations.json');excluded={**old['excluded']}
    for key in extra:excluded.setdefault(key,'semantically_exposed_source_relation')
    save(ROOT/'source-relations-v2.json',dict(excluded=excluded,components=old['components']))
    statuses=Counter()
    for row in rows:
        status='no_input_hypothesis' if not row['inputs'] else 'historically_related' if any(p['stable_id'] in excluded for p in row['inputs']) else 'isolated_hypothesis'
        statuses[status]+=1
    report=dict(status='complete_explicit_source_exposure',binding_commit=commit,nodes=len(records),
        exposed_source_count=len(exposed),includes_sources_without_valid_readings=True,
        connected_research_inputs=len(extra),additional_excluded_inputs=len(set(excluded)-set(old['excluded'])),
        original_exclusions_retained=True,full_reverse_parity=True,source_statuses=dict(statuses),
        relations_sha256=sha(ROOT/'source-relations-v2.json'),elapsed_seconds=round(time.monotonic()-start,3),
        native_retries=0,final_test=False,gold_admission=0)
    save(ROOT/'source-exposure-report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','execute'));parser.add_argument('--commit')
    args=parser.parse_args();print(json.dumps(seal() if args.stage=='seal' else run(args.commit)))
