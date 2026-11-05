"""Rebuild combined consumption relations before selecting either fixed arm."""
from collections import Counter
import json
import time

from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.consumed_source import PERMITTED,quarantine_units,unit_key
from sakura_rerank.data.contrast_capacity import candidate_evidence
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.relation_witnesses import build_witness_graph,component_labels,IDENTITY_KINDS
from comparison_common import ROOT,HERE,PLAN,prior,source_pools,implementation,rows,write_rows,read,save,sha

CODE=(HERE/'prepare_cohorts.py',HERE/'comparison_common.py',HERE/'reserve_plan.py')
FIELDS=('stable_id','corpus','left_context','reading','target','candidate_request_id')


def calculate():
    started=time.monotonic();plan,old,annotations,annotation_receipts,old_units=source_pools()
    source=read(ROOT/'source-report.json');execution=read(ROOT/'source-execution.json')
    if execution['status']!='complete' or execution['report_sha256']!=sha(ROOT/'source-report.json'):
        raise ValueError('comparison_source_not_complete')
    for entry in source['artifacts'].values():
        if sha(ROOT/'source'/entry['path'])!=entry['sha256']: raise ValueError('comparison_source_artifact_changed')
    origins={r['stable_id']:r for r in rows(ROOT/'source'/source['artifacts']['row-origins']['path'])}
    if set(origins)!={r['stable_id'] for r in old}: raise ValueError('comparison_original_receipt_denominator')
    inputs={}
    for group,values in (('dictionary',old),('annotation',annotations)):
        for row in values:
            identifier=row['stable_id'];row_hash=canonical_json_hash(row)
            receipt=origins[identifier] if group=='dictionary' else annotation_receipts[identifier]
            if group=='dictionary' and receipt['source_row_sha256']!=row_hash:
                raise ValueError('comparison_source_receipt_row_changed')
            inputs[identifier]=dict(encoder_input={k:row[k] for k in FIELDS},group=group,unit_id=unit_key(row['source']),
                original_row_sha256=row_hash,source_metadata_sha256=canonical_json_hash(row['source']),
                original_input_sha256=canonical_json_hash([row['left_context'],row['reading']]),
                consumption_sha256=canonical_json_hash(receipt),label_task='original_source_reconstruction',
                reading_provenance='original_ruby_annotation' if group=='annotation' else 'frozen_unique_dictionary',
                ime_quality='unresolved',training_eligible=False,independent_gold_eligible=False)
    del old,annotations,origins,annotation_receipts
    original,_,_,_,_=prior.origin.source.load_inventory()
    coverage=list(rows(ROOT/'source'/source['artifacts']['wikipedia-coverage']['path']))
    print(json.dumps(dict(stage='combined_paragraph_quarantine',original_nodes=len(original.records),new_coverage=len(coverage),proposed_rows=len(inputs))),flush=True)
    graph=build_witness_graph(original.records+coverage)
    del original,coverage
    identity=component_labels(graph,IDENTITY_KINDS)
    content=component_labels(graph,('paragraph','sentence_exact','sentence_near','input'))
    decisions,unit_counts=quarantine_units(graph.records,identity,content)
    del identity,content
    if any(decisions[key]['status']==PERMITTED for key,value in old_units.items() if value['status']!=PERMITTED):
        raise ValueError('comparison_old_quarantine_restored')
    terminal={key:dict(stable_id=key,group=value['group'],corpus=value['encoder_input']['corpus'],
        status=decisions.get(value['unit_id'],{}).get('status','missing_source_coverage')) for key,value in inputs.items()}
    proposed={key for key,value in terminal.items() if value['status']==PERMITTED}
    active=[];matched=set()
    for row in graph.records:
        identifier=row['stable_id']
        if identifier in inputs:
            item=inputs[identifier]
            if row.get('input_hash')!=item['original_input_sha256'] or canonical_json_hash(row['source'])!=item['source_metadata_sha256']:
                raise ValueError('comparison_original_graph_input_changed')
            matched.add(identifier)
        if (row['population']=='historical' or identifier in proposed
                or (row['population']=='source_coverage' and decisions[unit_key(row['source'])]['status']==PERMITTED)):
            active.append(row)
    if matched!=set(inputs): raise ValueError('comparison_candidate_graph_coverage')
    inventory=dict(nodes=len(graph.records),graph=graph.audit,units=unit_counts,
        original_quarantined_units_preserved=sum(v['status']!=PERMITTED for v in old_units.values()))
    del graph,old_units
    print(json.dumps(dict(stage='combined_consumed_scope_closure',nodes=len(active),proposed_rows=len(proposed))),flush=True)
    excluded,components,audit=isolate_annotations(active)
    for key in excluded: terminal[key]['status']='combined_'+excluded[key]
    retained=proposed-set(excluded)
    # Rebuild on retained nodes, in reverse order. Never filter old representative edges.
    kept=[r for r in active if r['stable_id'] not in excluded]
    reverse_excluded,reverse_components,reverse_audit=isolate_annotations(list(reversed(kept)))
    if reverse_excluded or reverse_components!={key:components[key] for key in retained}:
        raise ValueError('comparison_reverse_consumption_replay')
    del active,kept,components
    components=reverse_components
    print(json.dumps(dict(stage='authenticate_mixed_candidates',rows=len(retained),source_exclusions=len(inputs)-len(retained))),flush=True)
    forward=prior.forward
    candidate_execution=read(forward.ROOT/'execution.json')
    _,identity,_,_,_,requests=forward.authenticate(candidate_execution['binding_commit'])
    selected_inputs=[inputs[key]['encoder_input'] for key in sorted(retained)]
    snapshots=prior.candidate_verifier.snapshots(selected_inputs,identity,candidate_execution,requests)
    evidence={};eligible={'jawiki':[],'dictionary_aozora':[],'annotation_aozora':[]}
    for key in sorted(retained):
        item=inputs[key];row=item['encoder_input'];snapshot=snapshots.get(row['candidate_request_id'])
        if snapshot is not None and (snapshot['reading']!=row['reading'] or snapshot['stable_id']!=row['candidate_request_id']):
            raise ValueError('comparison_candidate_reading_join')
        observed=candidate_evidence(row['target'],snapshot);evidence[key]=observed
        terminal[key]['status']='candidate_'+observed['status']
        if observed['eligible']:
            if not 2<=len(row['reading'])<=32 or not 8<=len(row['left_context'])<=64:
                raise ValueError('comparison_model_input_bounds')
            group='jawiki' if row['corpus']=='jawiki' else item['group']+'_aozora'
            eligible[group].append(key)
    counts={key:len(value) for key,value in eligible.items()}
    ready=all(n>=25000 for n in counts.values())
    cohorts={name:eligible['jawiki'][:25000]+eligible[name+'_aozora'][:25000] for name in ('dictionary','annotation')} if ready else {}
    memberships={name:set(ids) for name,ids in cohorts.items()}
    wanted=set().union(*memberships.values()) if ready else set()
    records=[]
    for key in sorted(wanted):
        item=inputs[key];row=dict(item['encoder_input'],component_id=components[key])
        records.append(dict(encoder_input=row,origin={k:v for k,v in item.items() if k!='encoder_input'},
            membership=[name for name,ids in memberships.items() if key in ids]))
    needed={row['encoder_input']['candidate_request_id'] for row in records}
    report=dict(kind='annotation_comparison_consumed_cohorts',status='ready_for_numeric_verification' if ready else 'insufficient_fixed_cohorts_do_not_fit',
        plan_sha256=sha(PLAN),source_report_sha256=sha(ROOT/'source-report.json'),original_dictionary_rows=162502,original_annotation_rows=35592,
        input_denominator=len(inputs),inventory=inventory,first_scope_audit=audit,final_scope_audit=reverse_audit,
        quarantined_or_connected_rows=len(inputs)-len(retained),source_retained_rows=len(retained),candidate_eligible_counts=counts,
        terminal_counts=dict(Counter(r['group']+'/'+r['corpus']+'/'+r['status'] for r in terminal.values())),
        reverse_replay_passed=True,prior_quarantine_preserved=True,rows_per_arm={k:len(v) for k,v in cohorts.items()},
        common_wikipedia_rows=25000 if ready else 0,union_selected_rows=len(records),unique_candidate_readings=len(needed),
        no_original_label_mutations=True,model_fits=0,model_inferences=0,new_native_requests=0,final_test_used=False,gold_certified=False,
        elapsed_seconds=round(time.monotonic()-started,3))
    return report,decisions,terminal,cohorts,records,{key:snapshots[key] for key in sorted(needed)},evidence


def run():
    head,code=implementation(CODE)
    report,decisions,terminal,cohorts,records,snapshots,evidence=calculate()
    output=ROOT/'cohorts.partial';output.mkdir(exist_ok=False)
    artifacts={}
    for name,values in [('unit-decisions',(decisions[k] for k in sorted(decisions))),('terminals',(terminal[k] for k in sorted(terminal))),
        ('rows',records),('snapshots',snapshots.values()),('candidate-evidence',(dict(stable_id=k,evidence=evidence[k]) for k in sorted(evidence)))]:
        artifacts[name]=write_rows(output/(name+'.jsonl.gz'),values)
    save(output/'identities.json',cohorts)
    report.update(execution_commit=head,implementation=code,artifacts=artifacts,identities_sha256=sha(output/'identities.json'))
    save(output/'manifest.json',report);output.rename(ROOT/'cohorts')
    save(ROOT/'cohort-report.json',report)
    return report


if __name__=='__main__':
    if (ROOT/'cohort-reservation.json').exists(): raise SystemExit('comparison_cohorts_already_reserved')
    save(ROOT/'cohort-reservation.json',dict(plan_sha256=sha(PLAN),stage='mixed_consumption'))
    started=time.monotonic()
    try: result=run()
    except Exception as error:
        save(ROOT/'cohort-execution.json',dict(status='failed',error_type=type(error).__name__,elapsed_seconds=round(time.monotonic()-started,3)))
        print(json.dumps(dict(status='failed',error_type=type(error).__name__)),flush=True)
        raise SystemExit(1) from None
    save(ROOT/'cohort-execution.json',dict(status='complete',report_sha256=sha(ROOT/'cohort-report.json'),elapsed_seconds=round(time.monotonic()-started,3)))
    print(json.dumps({k:result[k] for k in ('status','candidate_eligible_counts','rows_per_arm','union_selected_rows','elapsed_seconds')}),flush=True)
