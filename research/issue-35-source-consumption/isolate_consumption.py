"""Complete history including the actual empty-context inputs of the old pilot."""
import argparse
from collections import Counter
import json
import sys
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.reconstruction_graph import isolate_source_scope
from consume35_common import HERE, PAST, ROOT, UNITS, authenticate, committed, read, save, sha

BINDING = HERE/'history-binding-v1.json'


def history_records():
    sys.path.insert(0,'research/issue-35-source-pilot')
    try:
        from isolate_pilot import historical_records
        previous = historical_records(read('research/issue-35-source-pilot/history-binding-v1.json'))
    finally:
        sys.path.pop(0)
    old = read(PAST/'decoded-pilot.json')
    previous.extend(old['source_coverage'])
    previous.extend({**{k:r[k] for k in ('stable_id','source','input_hash')},'population':'historical'}
                    for r in old['input_hypotheses'])
    sources = {r['source']['article_id']:r['source'] for r in old['source_coverage']}
    seen_requests = set()
    native_history = []
    for row in read(UNITS/'source-units.json')['rows']:
        for name,view in row['views'].items():
            for index,part in enumerate(view['parts']):
                if part['kind']!='convert':
                    continue
                seen_requests.add(part['request_id'])
                native_history.append(dict(stable_id='tatoeba-pr61-input-'+canonical_json_hash([row['stable_id'],name,index]),
                    population='historical',source=sources['tatoeba:'+str(row['sentence_id'])],
                    input_hash=canonical_json_hash(['',part['reading']])))
    if seen_requests != {r['stable_id'] for r in read(UNITS/'requests.json')['requests']}:
        raise ValueError('consumption_previous_native_input_coverage')
    previous.extend(native_history)
    return previous, dict(previous_base=988073,previous_sources=100,previous_ruby_inputs=312,
                          previous_native_occurrences=len(native_history),previous_native_requests=len(seen_requests))


def seal(plan_commit):
    authenticate(plan_commit)
    files=[ROOT/'consumed-slots.json',ROOT/'preparation.json',ROOT/'selection.json',
           'research/issue-35-source-pilot/history-binding-v1.json']
    code=[HERE/'isolate_consumption.py','research/issue-35-source-pilot/isolate_pilot.py',
          'research/issue-35-source-pilot/pilot35_common.py','src/sakura_rerank/data/reconstruction_graph.py',
          'src/sakura_rerank/data/relation_witnesses.py','src/sakura_rerank/data/splitter.py']
    save(BINDING,dict(kind='prospective_consumption_history_binding',plan_commit=plan_commit,
        inputs={str(p).replace('\\','/'):sha(p) for p in files},
        code={str(p).replace('\\','/'):sha(p) for p in code},
        maximum_nodes=1000000,old_owner_relations_preserved=True,old_exclusions_restored=0))
    return dict(stage='history_sealed',binding_sha256=sha(BINDING))


def run(commit):
    start=time.monotonic()
    bound=json.loads(committed(BINDING,commit));authenticate(bound['plan_commit'])
    for path,digest in {**bound['inputs'],**bound['code']}.items():
        if sha(path)!=digest:raise ValueError('consumption_history_binding_changed')
    for path in bound['code']:committed(path,commit)
    save(ROOT/'history-reservation.json',dict(binding_commit=commit,metadata_only=True,final_test=False))
    previous,previous_counts=history_records()
    rows=read(ROOT/'consumed-slots.json')['rows']
    new=[]
    for row in rows:
        if row['source_coverage'] is not None:new.append(row['source_coverage'])
        new.extend({k:r[k] for k in ('stable_id','population','source','input_hash')} for r in row['inputs'])
    combined=previous+new
    if len(combined)>bound['maximum_nodes']:raise ValueError('consumption_graph_bound')
    print(json.dumps(dict(stage='history_forward',historical_nodes=len(previous),new_nodes=len(new))),flush=True)
    excluded,components,audit=isolate_source_scope(combined)
    print(json.dumps(dict(stage='history_reverse',nodes=len(combined))),flush=True)
    if (excluded,components,audit)!=isolate_source_scope(list(reversed(combined))):
        raise ValueError('consumption_graph_reverse_parity')
    save(ROOT/'source-relations.json',dict(excluded=excluded,components=components))
    strata=Counter();sentences=Counter()
    for row in rows:
        status=('no_input_hypothesis' if not row['inputs'] else
                'historically_related' if any(r['stable_id'] in excluded for r in row['inputs']) else 'isolated_hypothesis')
        sentences[status]+=1;strata[row['stratum']+'/'+status]+=1
    report=dict(kind='prospective_source_history',status='complete_not_admitted',binding_commit=commit,
        history_nodes=len(previous),new_nodes=len(new),**previous_counts,full_reverse_parity=True,
        source_statuses=dict(sentences),strata=dict(strata),input_hypotheses=sum(len(r['inputs']) for r in rows),
        excluded_inputs=len(excluded),input_components=len(set(components.values())),audit=audit,
        relations_sha256=sha(ROOT/'source-relations.json'),elapsed_seconds=round(time.monotonic()-start,3),
        administrative_owner_links_retained=True,unknown_creators_and_translations_unverified=True,
        old_exclusions_restored=0,original_splits_changed=False,gold_admitted=0,final_test=False)
    save(ROOT/'history-report.json',report)
    return {k:report[k] for k in ('status','history_nodes','new_nodes','source_statuses','strata','excluded_inputs','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','execute'));parser.add_argument('--commit',required=True)
    args=parser.parse_args();print(json.dumps((seal if args.stage=='seal' else run)(args.commit)))
