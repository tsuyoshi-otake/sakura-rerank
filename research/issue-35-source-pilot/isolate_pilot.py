"""Full-history relations for provisional source hypotheses; no admission."""
import argparse
from collections import Counter
import gzip
import importlib.util
import json
import sys
import time

from sakura_rerank.data.reconstruction_graph import isolate_source_scope
from pilot35_common import ROOT, HERE, authenticate, committed, read, save, sha


def historical_records(bound):
    for path,digest in bound['history_artifacts'].items():
        if sha(path)!=digest:
            raise ValueError('pilot35_historical_artifact_changed')
    # Reuse the verified historical API, not the mutating old isolate/run entrypoint.
    previous_path='research/issue-33-annotation-experiment/cohort.py'
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:
        spec=importlib.util.spec_from_file_location('pilot35_previous_history',previous_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        previous=module.prior_inventory()
    finally:
        sys.path.pop(0)
    if len(previous)!=965889:
        raise ValueError('pilot35_base_history_count')
    for path in bound['metadata_files']:
        with gzip.open(path,'rb') as stream:
            for line in stream:
                row=json.loads(line)
                previous.append(row if row['population']=='source_coverage' else dict(row,population='historical'))
    if len(previous)!=988073:
        raise ValueError('pilot35_complete_history_count')
    return previous


def run(commit):
    started=time.monotonic()
    bound=json.loads(committed(HERE/'history-binding-v1.json',commit))
    authenticate(bound['plan_commit'])
    for path,digest in bound['code'].items():
        committed(path,commit)
        if sha(path)!=digest:
            raise ValueError('pilot35_history_code_changed')
    for path,digest in bound['pilot_artifacts'].items():
        if sha(path)!=digest:
            raise ValueError('pilot35_history_pilot_changed')
    decoded=read(ROOT/'decoded-pilot.json')
    metadata=[{k:r[k] for k in ('stable_id','population','source','input_hash')} for r in decoded['input_hypotheses']]
    previous=historical_records(bound)
    combined=previous+decoded['source_coverage']+metadata
    if len(combined)>1_000_000:
        raise ValueError('pilot35_existing_graph_limit')
    print(json.dumps(dict(stage='source_history_closure',historical_nodes=len(previous),new_nodes=len(combined)-len(previous))),flush=True)
    excluded,components,audit=isolate_source_scope(combined)
    reverse=isolate_source_scope(list(reversed(combined)))
    if (excluded,components,audit)!=reverse:
        raise ValueError('pilot35_full_reverse_closure_changed')
    save(ROOT/'source-relations.json',dict(excluded=excluded,components=components))
    strata={s['sentence_id']:s['stratum'] for s in decoded['slots']}
    counts=Counter();source_status={}
    for r in decoded['input_hypotheses']:
        status='historically_related' if r['stable_id'] in excluded else 'isolated_hypothesis'
        counts[strata[r['sentence_id']]+'/'+status]+=1
        source_status.setdefault(r['sentence_id'],set()).add(status)
    sources=Counter('+'.join(sorted(v)) for v in source_status.values())
    sources['no_input_hypothesis']=100-len(source_status)
    report=dict(kind='tatoeba_pilot_history_isolation',status='complete_not_admitted',
        binding_commit=commit,history_nodes=len(previous),new_source_units=100,new_input_hypotheses=len(metadata),
        strata=dict(counts),source_statuses=dict(sources),input_components=len(set(components.values())),
        excluded_input_hypotheses=len(excluded),audit=audit,full_reverse_replay=True,
        relations_sha256=sha(ROOT/'source-relations.json'),decoded_sha256=sha(ROOT/'decoded-pilot.json'),
        historical_metadata_only=True,original_splits_changed=False,calibration_admitted=0,gold_certified=False,
        final_test_used=False,elapsed_seconds=round(time.monotonic()-started,3),
        limitations=['Source owner grouping is conservative provenance, not proven original authorship.',
            'Translation linkage and undisclosed source lineage are not available in these two exports.',
            'Exact/near text and bounded-input isolation do not establish IME label quality.'])
    save(ROOT/'isolation-audit.json',report)
    return {k:report[k] for k in ('status','history_nodes','new_input_hypotheses','strata','source_statuses','input_components','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binding-commit',required=True)
    print(json.dumps(run(parser.parse_args().binding_commit)))
