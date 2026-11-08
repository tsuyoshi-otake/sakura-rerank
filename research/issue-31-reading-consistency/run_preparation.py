"""Apply the source gate, then directly verify source and consumer behavior."""
import argparse
from collections import Counter
import json
import sys
import time
import unittest

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.source_reading_gate import prepare,load_prepared
from reading_common import HERE,ROOT,PRIOR,authenticate,freeze,population,source_records,read,require,save,sha


def run(commit):
    started=time.monotonic()
    plan,registry,selection,guard=authenticate(commit)
    cohort,origins=population()
    result=prepare(source_records(cohort,origins,registry,selection),ROOT/'pool',
        source_binding_sha256=sha(HERE/'plan-v1.json'),expected_rows=75000,
        allow_dictionary_only=plan['execution_policy']['allow_dictionary_only'])
    require(result['terminal_counts']==plan['expected_from_prior'],'preparation_terminal_counts')
    require(guard.blocked==0,'forbidden_read')
    report=dict(status='complete',code_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),
        pool_manifest_sha256=sha(ROOT/'pool/manifest.json'),input_rows=result['input_rows'],preparable_rows=result['preparable_rows'],
        pending_rows=result['pending_rows'],terminal_counts=result['terminal_counts'],forbidden_data_reads=guard.blocked,
        elapsed_seconds=round(time.monotonic()-started,3),training_admission=False,gold_admission=False,new_fits=0,final_test=False)
    save(ROOT/'preparation.json',report)
    return report


def verify(commit):
    started=time.monotonic()
    plan,registry,selection,guard=authenticate(commit)
    preparation=read(ROOT/'preparation.json')
    require(preparation['code_commit']==commit and preparation['plan_sha256']==sha(HERE/'plan-v1.json'),'execution_binding')
    current=load_prepared(ROOT/'pool',preparation['pool_manifest_sha256'],purpose='numeric_verification')
    cohort,origins=population()
    # Prior audit is a separately committed source-state implementation, not
    # a decision supplied to the producer. Reconcile by identity, never new order.
    prior=read(PRIOR/'rows.json')
    require(len(prior)==75000,'prior_population')
    state_by_original={r['original_row_sha256']:r['reading_evidence'] for r in prior}
    require(len(state_by_original)==75000,'prior_original_identity')
    by_input={canonical_json_hash(r['encoder_input']):r for r in cohort}
    require(len(by_input)==75000,'unique_input_hashes')
    allowed=[]
    counts,states=Counter(),Counter()
    expected_order=[]
    for row,source,paragraph in source_records(cohort,origins,registry,selection):
        # Separate source-state calculation from the new gate's assess function.
        if row['corpus']=='jawiki':state='wikipedia_no_original_reading_annotation'
        else:
            start,end=source['start'],source['end']
            overlaps=[s for s in paragraph['spans'] if s['start']<end and start<s['end']]
            if any(s['kind']=='unresolved_base' for s in overlaps):state='ruby_parse_unresolved'
            elif not overlaps:state='ruby_parse_unresolved' if paragraph['flags']['orphan_marker'] else 'no_ruby_overlap'
            elif len(overlaps)!=1 or (overlaps[0]['start'],overlaps[0]['end'])!=(start,end):state='ruby_scope_differs'
            else:
                import re
                observed=overlaps[0]['reading']
                if not re.fullmatch('[ぁ-ゖァ-ヶー]{1,32}',observed) or observed in ('ママ','まま'):state='exact_ruby_nonphonetic_or_out_of_bounds'
                else:
                    reading=''.join(chr(ord(c)-96) if 'ァ'<=c<='ヶ' else c for c in observed)
                    state='exact_ruby_reading_match' if reading==row['reading'] else 'exact_ruby_reading_disagreement'
        require(state==state_by_original[source['original_row_sha256']],'prior_source_state')
        decision=current['decisions'][len(expected_order)]
        expected_order.append(canonical_json_hash(row))
        require(decision['input_sha256']==expected_order[-1] and decision['source']==source
                and decision['evidence_sha256']==canonical_json_hash([source,paragraph]) and decision['reading_evidence']==state,'original_source_replay')
        table={'exact_ruby_reading_match':'ready_original_annotation','no_ruby_overlap':'ready_dictionary_only_weak',
            'wikipedia_no_original_reading_annotation':'ready_dictionary_only_weak','exact_ruby_reading_disagreement':'pending_reading_conflict',
            'ruby_scope_differs':'pending_annotation_scope','ruby_parse_unresolved':'pending_annotation_parse',
            'exact_ruby_nonphonetic_or_out_of_bounds':'pending_annotation_reading'}
        expected=table[state]
        require(decision['terminal']==expected,'independent_terminal')
        counts[expected]+=1
        states[state]+=1
        if expected in ('ready_original_annotation','ready_dictionary_only_weak'):allowed.append(row)
    require(len(expected_order)==len(set(expected_order))==75000 and set(expected_order)==set(by_input),'all_original_rows_preserved')
    require(dict(counts)==plan['expected_from_prior'] and [r['input'] for r in current['rows']]==allowed,'consumer_population')
    required_repairs={r['original_row_sha256'] for r in read(PRIOR/'repair-proposals.json')['rows']}
    held_repairs={d['source']['original_row_sha256'] for d in current['decisions'] if d['terminal']=='pending_reading_conflict'}
    require(required_repairs==held_repairs and len(held_repairs)==335,'all_prior_repairs_held')
    require(guard.blocked==0,'forbidden_read')
    proof=dict(status='passed',code_commit=commit,preparation_sha256=sha(ROOT/'preparation.json'),
        pool_manifest_sha256=preparation['pool_manifest_sha256'],original_rows_verified=75000,source_states_independently_recomputed=75000,
        consumer_rows_verified=len(allowed),pending_rows_verified=75000-len(allowed),prior_reading_conflicts_held=len(held_repairs),
        original_labels_changed=0,terminal_counts=dict(counts),reading_evidence_counts=dict(states),forbidden_data_reads=guard.blocked,
        elapsed_seconds=round(time.monotonic()-started,3),training_admission=False,gold_admission=False,new_fits=0,final_test=False)
    save(ROOT/'verification.json',proof)
    return proof


def tests():
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    report=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-tests.json',report)
    require(result.wasSuccessful() and not result.skipped,'tests_failed')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','prepare','verify','tests'));parser.add_argument('--commit');args=parser.parse_args()
    try:
        result=freeze() if args.stage=='plan' else tests() if args.stage=='tests' else run(args.commit) if args.stage=='prepare' else verify(args.commit)
    except Exception as error:
        info=dict(status='failed',error_type=type(error).__name__)
        if isinstance(error,ValueError) and str(error).startswith(('reading_gate_','source_reading_','conflict_')):info['error_code']=str(error)
        print(json.dumps(info),flush=True);sys.exit(1)
    print(json.dumps(result),flush=True)
