"""Replay frozen native capture verification, reporting aggregate counts only."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.native_snapshot import NativeSnapshotError, bind_evaluator_input, verify_capture


def audit(root,plan_sha,result_sha):
    names=('plan.json','result.json','capture.jsonl')
    raw=[(root/name).read_bytes() for name in names]
    values=verify_capture(*raw,expected_plan_sha256=plan_sha,expected_result_sha256=result_sha)
    counts=Counter(events=len(values),captured=0,no_conversion=0,legacy_bound=0,legacy_unrepresentable=0,
        native_candidates=0,applied=0,request_identity_mismatch=0,local_selection_outside_model_prefix=0,
        scheduling_without_application_permission=0)
    maximum=0
    by_scenario={}
    binding_digests=[]
    for value in values:
        snapshot=value['snapshot']
        if snapshot is None:
            counts['no_conversion']+=1
            continue
        counts['captured']+=1
        counts['applied']+=value['applied']
        counts['native_candidates']+=len(snapshot['candidates'])
        maximum=max(maximum,len(snapshot['candidates']))
        counts['request_identity_mismatch']+=value['built'] and not snapshot['request_identity_matches']
        facts=snapshot['product_state']
        counts['local_selection_outside_model_prefix']+=facts['baseline_index']>=6
        counts['scheduling_without_application_permission']+=value['built'] and not facts['selection_allowed']
        request={'reading':snapshot['reading'],'left_context':'','context_policy':'sakura_input_committed_same_session',
            'candidates':[dict(rank=i,surface=c['surface'],local_cost=c['local_cost']) for i,c in enumerate(snapshot['candidates'])]}
        try:
            binding=bind_evaluator_input(snapshot,request,facts)
        except NativeSnapshotError:
            if len(snapshot['candidates'])<=32:
                raise
            counts['legacy_unrepresentable']+=1
        else:
            counts['legacy_bound']+=1
            binding_digests.append(hashlib.sha256(canonical_json_bytes(binding)).hexdigest())
        if not value['baseline_run']:
            by_scenario[value['scenario']]={'scheduled':value['scheduled'],'built':value['built'],
                'native_candidate_count':len(snapshot['candidates']),'baseline_index':facts['baseline_index'],
                'selected_index':snapshot['selected_index'],'selection_allowed':facts['selection_allowed'],
                'request_identity_matches':snapshot['request_identity_matches'],
                'response_identity_matches':snapshot['response_identity_matches'],'applied':value['applied']}
    if counts['legacy_bound']+counts['legacy_unrepresentable']+counts['no_conversion']!=counts['events']:
        raise ValueError('native denominator not reconciled')
    return {'kind':'native_state_capture_audit','version':1,'status':'passed','counts':dict(counts),
        'max_native_candidate_count':maximum,'paired_controls_verified':len(values)//2,
        'artifact_sha256':{name:hashlib.sha256(data).hexdigest() for name,data in zip(names,raw,strict=True)},
        'binding_sequence_sha256':hashlib.sha256(canonical_json_bytes(binding_digests)).hexdigest(),
        'synthetic_scenarios':by_scenario,'legacy_feature_provenance_verified':False,
        'live_host_or_worker_timing_verified':False,'gold_certified':False,'accuracy_claim':False,
        'final_evaluation_admitted':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--result-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.work_root,args.plan_sha256,args.result_sha256)
    with args.output.open('xb') as stream:
        stream.write(canonical_json_bytes(report)+b'\n')
    print(json.dumps({'status':report['status'],**report['counts'],'max_native_candidates':report['max_native_candidate_count']}))
