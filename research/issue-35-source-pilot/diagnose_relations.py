"""Post-hoc relation sensitivity; never restore excluded inputs or choose splits."""
import argparse
from collections import Counter, defaultdict
import json
import time

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.reconstruction_graph import build_source_graph
from sakura_rerank.data.relation_witnesses import KINDS, component_labels
from isolate_pilot import historical_records
from pilot35_common import ROOT, HERE, authenticate, committed, read, save, sha


def run(commit):
    started=time.monotonic()
    for path in (HERE/'diagnose_relations.py',HERE/'isolate_pilot.py'):
        committed(path,commit)
    bound=read(HERE/'history-binding-v1.json');authenticate(bound['plan_commit'])
    for path,digest in {**bound['code'],**bound['pilot_artifacts']}.items():
        if sha(path)!=digest:raise ValueError('pilot35_diagnostic_bound_input_changed')
    decoded=read(ROOT/'decoded-pilot.json');original=read(ROOT/'source-relations.json')
    save(ROOT/'diagnostic-reservation.json',dict(code_commit=commit,
        diagnostic_code_sha256=sha(HERE/'diagnose_relations.py'),
        rationale='Explain 268 historical relations after the sealed audit; exploratory, not split or gate selection.',
        views=['all','without_owner','without_input','identity_only','text_only'],
        exclusions_restored=0,model_inference=0,final_test_used=False))
    history=historical_records(bound)
    inputs=[{k:r[k] for k in ('stable_id','population','source','input_hash')} for r in decoded['input_hypotheses']]
    historical_keys={name:set() for name in ('input_hash','paragraph_hash','sentence_hash')}
    for row in history:
        if row['population']!='historical':continue
        if row.get('input_hash'):historical_keys['input_hash'].add(row['input_hash'])
        for field in ('paragraph_hash','sentence_hash'):historical_keys[field].add(row['source'][field])
    direct=Counter()
    for row in inputs:
        for field,keys in historical_keys.items():
            value=row['input_hash'] if field=='input_hash' else row['source'][field]
            if value in keys:direct[field]+=1
    graph=build_source_graph(history+decoded['source_coverage']+inputs)
    del history,historical_keys
    input_to_sentence={r['stable_id']:r['sentence_id'] for r in decoded['input_hypotheses']}
    views={}
    for name,kinds in (('all',KINDS),('without_owner',tuple(k for k in KINDS if k!='author')),
                       ('without_input',tuple(k for k in KINDS if k!='input')),
                       ('identity_only',KINDS[:3]),('text_only',KINDS[3:])):
        labels=component_labels(graph,kinds)
        historical={label for row,label in zip(graph.records,labels) if row['population']=='historical'}
        related={row['stable_id'] for row,label in zip(graph.records,labels)
                 if row['population']=='evaluation' and label in historical}
        if name=='all':
            if related!=set(original['excluded']):raise ValueError('pilot35_diagnostic_exclusions_differ')
            selected_labels={label for row,label in zip(graph.records,labels) if row['population']=='evaluation'}
            groups=defaultdict(list)
            for row,label in zip(graph.records,labels):
                if label in selected_labels:groups[label].append(row['stable_id'])
            hashes={key:canonical_json_hash(sorted(ids)) for key,ids in groups.items()}
            if {row['stable_id']:hashes[label] for row,label in zip(graph.records,labels)
                    if row['population']=='evaluation'}!=original['components']:
                raise ValueError('pilot35_diagnostic_components_differ')
        views[name]=dict(related_inputs=len(related),related_sentences=len({input_to_sentence[key] for key in related}))
    report=dict(kind='tatoeba_pilot_posthoc_relation_diagnostic',status='complete_descriptive_only',
        code_commit=commit,graph=graph.audit,views=views,direct_exact_historical_matches=dict(direct),
        original_full_components_and_exclusions_identical=True,exclusions_restored=0,
        final_test_used=False,labels_admitted=0,source_owner_is_not_proven_author=True,
        elapsed_seconds=round(time.monotonic()-started,3))
    save(ROOT/'relation-diagnostic.json',report)
    print(json.dumps({k:report[k] for k in ('status','views','direct_exact_historical_matches','elapsed_seconds')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--implementation-commit',required=True)
    run(parser.parse_args().implementation_commit)
