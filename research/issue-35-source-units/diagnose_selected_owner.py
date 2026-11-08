"""Selected administrative-owner sensitivity with all legacy relations intact."""
import argparse
from collections import Counter,defaultdict
import json
from itertools import zip_longest
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.reconstruction_graph import build_source_graph
from sakura_rerank.data.relation_witnesses import component_labels
from sakura_rerank.data.source_owner_diagnostic import administrative_owner_omissions
from unit35_common import ROOT,HERE,PAST,authenticate,committed,historical_records,read,save,sha


def related(graph,labels):
    seeds={label for row,label in zip(graph.records,labels) if row['population']=='historical'}
    return {row['stable_id'] for row,label in zip(graph.records,labels) if row['population']=='evaluation' and label in seeds}


def equivalent_partitions(first,second):
    forward={};reverse={}
    for left,right in zip(first,second):
        if forward.setdefault(left,right)!=right or reverse.setdefault(right,left)!=left:
            raise ValueError('unit35_rebuilt_owner_partition_differs')
    if len(first)!=len(second):raise ValueError('unit35_partition_length')


def run(plan_commit,implementation_commit):
    started=time.monotonic();authenticate(plan_commit)
    committed(HERE/'diagnose_selected_owner.py',implementation_commit)
    bound=read('research/issue-35-source-pilot/history-binding-v1.json')
    for path,digest in bound['code'].items():
        if sha(path)!=digest:raise ValueError('unit35_historical_code_changed')
    old=read(PAST/'decoded-pilot.json');original=read(PAST/'source-relations.json')
    save(ROOT/'owner-reservation.json',dict(plan_commit=plan_commit,implementation_commit=implementation_commit,
        code_sha256=sha(HERE/'diagnose_selected_owner.py'),slots=100,old_exclusions_restored=0))
    history=historical_records(bound)
    inputs=[{k:r[k] for k in ('stable_id','population','source','input_hash')} for r in old['input_hypotheses']]
    selected=old['source_coverage']+inputs;selected_ids={r['stable_id'] for r in selected}
    graph=build_source_graph(history+selected)
    del history
    labels=component_labels(graph)
    if related(graph,labels)!=set(original['excluded']):raise ValueError('unit35_original_exclusions_differ')
    relevant_labels={label for row,label in zip(graph.records,labels) if row['population']=='evaluation'}
    groups=defaultdict(list)
    for row,label in zip(graph.records,labels):
        if label in relevant_labels:groups[label].append(row['stable_id'])
    hashes={key:canonical_json_hash(sorted(ids)) for key,ids in groups.items()}
    if {row['stable_id']:hashes[label] for row,label in zip(graph.records,labels) if row['population']=='evaluation'}!=original['components']:
        raise ValueError('unit35_original_components_differ')
    del labels,groups,hashes
    omitted=administrative_owner_omissions(graph,selected_ids)
    masked=component_labels(graph,omitted=omitted)
    affected=related(graph,masked)
    print(json.dumps(dict(stage='selected_owner_view',nodes=len(graph.records),omitted_owner_edges=sum(omitted),related_inputs=len(affected))),flush=True)
    # Independent reconstruction changes only this source's administrative group.
    changed=[dict(row,source=dict(row['source'],template_cluster_id=None)) if row['stable_id'] in selected_ids else row
             for row in graph.records]
    for before,after in zip(graph.records,changed):
        if before['stable_id'] not in selected_ids and before!=after:
            raise ValueError('unit35_old_source_metadata_changed')
    rebuilt=build_source_graph(changed);rebuilt_labels=component_labels(rebuilt)
    if [r['stable_id'] for r in rebuilt.records]!=[r['stable_id'] for r in graph.records]:
        raise ValueError('unit35_rebuilt_node_order')
    equivalent_partitions(masked,rebuilt_labels)
    if related(rebuilt,rebuilt_labels)!=affected:raise ValueError('unit35_rebuilt_exclusions_differ')
    for kind,count in graph.audit['edge_kinds'].items():
        expected=count-sum(omitted) if kind=='author' else count
        if rebuilt.audit['edge_kinds'].get(kind,0)!=expected:
            raise ValueError('unit35_non_owner_edges_changed')
    expected_edges=((a,b,k) for index,(a,b,k) in enumerate(zip(graph.left,graph.right,graph.kinds)) if not omitted[index])
    for expected,actual in zip_longest(expected_edges,zip(rebuilt.left,rebuilt.right,rebuilt.kinds)):
        if expected!=actual:raise ValueError('unit35_retained_edge_wiring_changed')
    by_sentence={r['stable_id']:r['sentence_id'] for r in old['input_hypotheses']}
    owner_sizes=Counter(r['source']['template_cluster_id'] for r in old['source_coverage'] if r['source']['template_cluster_id'])
    total_old_author_edges=graph.audit['edge_kinds']['author']-sum(omitted)
    report=dict(kind='selected_source_owner_diagnostic',status='complete_diagnostic_not_admission',
        plan_commit=plan_commit,implementation_commit=implementation_commit,nodes=len(graph.records),
        original_related_inputs=len(original['excluded']),original_related_sentences=len({by_sentence[key] for key in original['excluded']}),
        selected_owner_omitted_edges=sum(omitted),legacy_author_edges_retained=total_old_author_edges,
        selected_owner_groups=len(owner_sizes),largest_selected_owner_sentence_count=max(owner_sizes.values(),default=0),
        related_inputs_after_selected_owner_omission=len(affected),related_sentences_after_selected_owner_omission=len({by_sentence[key] for key in affected}),
        original_component_and_exclusion_parity=True,independent_null_owner_rebuild_parity=True,
        all_non_owner_edge_counts_identical=True,old_records_unchanged=True,
        all_retained_edge_endpoints_and_types_identical=True,
        original_exclusions_restored=0,source_owner_is_proven_author=False,calibration_admitted=0,gold_certified=False,
        elapsed_seconds=round(time.monotonic()-started,3))
    save(ROOT/'owner-diagnostic.json',report)
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan-commit',required=True);parser.add_argument('--implementation-commit',required=True)
    args=parser.parse_args();run(args.plan_commit,args.implementation_commit)
