"""Native identity/fallback mutations; compiled-native evidence is separate."""
import copy
import hashlib
import json
import struct
import unittest

from sakura_rerank import native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes


def event(*, count=3, baseline=0, allowed=True, response=True, baseline_run=False):
    reading='あ'
    candidates=[]
    for i in range(count):
        surface='synthetic'+str(i)
        candidates.append(dict(surface_hex=surface.encode().hex(),cost=100+i,evidence=1,
            fingerprint=native.candidate_fingerprint(surface,100+i,1)))
    prefix=candidates[:6]
    fingerprints=[c['fingerprint'] for c in prefix]
    candidate_set=native.candidate_set_fingerprint(fingerprints)
    key=[1,2,3,native.fingerprint(reading.encode()),len(reading.encode())]
    scores=[10. if i==2 else -float(i) for i in range(len(prefix))]
    work=dict(scheduled=True,built=True,owner=key[0],session=key[1],generation=key[2],reading_hash=key[3],
        reading_bytes=key[4],candidate_set=candidate_set,
        model_candidates=[{k:v for k,v in c.items() if k!='evidence'} for c in prefix],
        response_key=key,response_candidate_set=candidate_set,response_count=len(prefix),
        response_fingerprints=fingerprints,response_score_bits=[struct.unpack('<I',struct.pack('<f',s))[0] for s in scores],
        response_finite=True,response_ready=True,response_present=response)
    chosen=2 if allowed and response else baseline
    capture=dict(owner=1,session=2,generation=3,reading_hex=reading.encode().hex(),direct_count=count,
        baseline_index=baseline,selected_index=chosen,selection_calls=int(allowed),candidate_set=candidate_set,candidates=candidates)
    return dict(fixture=0,scenario='synthetic',baseline_run=baseline_run,work=work,captures=[capture],
                terminal='Applied' if allowed and response else 'Ready' if response else 'None')


def bundle():
    events=[event(response=False,baseline_run=True),event()]
    events[1]['fixture']=1
    raw=b'\n'.join(canonical_json_bytes(v) for v in events)+b'\n'
    plan=canonical_json_bytes(dict(kind='native_state_probe_plan',version=2,source_head=native.HEAD,
        synthetic_response_injection=True,expected_fixture_count=2))
    plan_sha=hashlib.sha256(plan).hexdigest()
    result=canonical_json_bytes(dict(kind='native_state_probe_result',version=2,status='passed',plan_sha256=plan_sha,
        capture_sha256=hashlib.sha256(raw).hexdigest(),fixture_count=2,capture_count=2,applied=1,
        real_test=False,model_inference=False,gold_evidence=False,production_edits=False))
    return plan,result,raw,dict(expected_plan_sha256=plan_sha,expected_result_sha256=hashlib.sha256(result).hexdigest())


class NativeSnapshotTests(unittest.TestCase):
    def test_paired_capture_requires_external_commitments(self):
        plan,result,raw,kw=bundle()
        values=native.verify_capture(plan,result,raw,**kw)
        self.assertEqual([v['applied'] for v in values],[False,True])
        with self.assertRaises(native.NativeSnapshotError):
            native.verify_capture(plan,result,raw+b'\n',**kw)
        with self.assertRaises(native.NativeSnapshotError):
            native.verify_capture(plan,result+b' ',raw,**kw)

    def test_full_native_population_and_tail_local_preference_are_preserved(self):
        value=native.inspect_event(event(count=108,baseline=100,allowed=False))
        snapshot=value['snapshot']
        self.assertEqual(len(snapshot['candidates']),108)
        self.assertEqual(snapshot['product_state']['baseline_index'],100)
        self.assertFalse(snapshot['product_state']['selection_allowed'])
        self.assertEqual(snapshot['selected_index'],100)

    def test_each_response_identity_mismatch_keeps_local_selection(self):
        for key_index in range(5):
            with self.subTest(key=key_index):
                row=event()
                row['work']['response_key'][key_index]+=1
                row['captures'][0]['selected_index']=0
                row['terminal']='Ready'
                value=native.inspect_event(row)
                self.assertFalse(value['applied'])
                self.assertFalse(value['snapshot']['response_identity_matches'])

    def test_candidate_response_set_fingerprint_count_and_nan_fail_closed(self):
        for mode in ('candidate_set','fingerprint','count','nan','ready','present'):
            with self.subTest(mode=mode):
                row=event(); work=row['work']
                if mode=='candidate_set': work['response_candidate_set']^=1
                elif mode=='fingerprint': work['response_fingerprints'][0]^=1
                elif mode=='count':
                    work['response_count']-=1
                    work['response_fingerprints'].pop(); work['response_score_bits'].pop()
                elif mode=='nan':
                    work['response_score_bits'][0]=0x7FC00000; work['response_finite']=False
                elif mode=='ready': work['response_ready']=False
                else: work['response_present']=False
                row['captures'][0]['selected_index']=0; row['terminal']='Ready'
                self.assertFalse(native.inspect_event(row)['applied'])

    def test_changed_reading_between_scheduling_and_conversion_is_not_eligible(self):
        row=event()
        row['captures'][0]['reading_hex']='い'.encode().hex()
        row['captures'][0]['selected_index']=0; row['terminal']='Ready'
        value=native.inspect_event(row)
        self.assertFalse(value['snapshot']['request_identity_matches'])
        self.assertFalse(value['snapshot']['product_state']['schedule_eligible'])

    def test_applied_claim_cannot_override_stale_identity(self):
        row=event(); row['work']['response_key'][0]+=1
        with self.assertRaises(native.NativeSnapshotError): native.inspect_event(row)

    def test_native_evidence_is_in_candidate_fingerprint(self):
        row=event(); row['captures'][0]['candidates'][0]['evidence']=2
        with self.assertRaises(native.NativeSnapshotError): native.inspect_event(row)

    def test_protected_local_selection_does_not_consume_ready_result(self):
        row=event(allowed=False,baseline=1)
        value=native.inspect_event(row)
        self.assertTrue(value['snapshot']['response_identity_matches'])
        self.assertFalse(value['applied'])
        self.assertEqual(value['snapshot']['selected_index'],1)

    def test_integer_boolean_and_text_bounds_are_strict(self):
        changes=[('baseline_index',True),('direct_count',769),('selection_calls',2),('reading_hex','zz')]
        for field,value in changes:
            with self.subTest(field=field):
                row=event(); row['captures'][0][field]=value
                with self.assertRaises(native.NativeSnapshotError): native.inspect_event(row)

    def test_no_conversion_is_retained_without_invented_candidates(self):
        row=event(); row.update(work={'scheduled':False,'built':False},captures=[],terminal='None')
        value=native.inspect_event(row)
        self.assertEqual(value['status'],'no_conversion_snapshot')
        self.assertIsNone(value['snapshot'])

    def test_binding_rejects_reorder_changed_scope_and_unobserved_context(self):
        snapshot=native.inspect_event(event())['snapshot']
        request=dict(reading=snapshot['reading'],left_context='',context_policy='sakura_input_committed_same_session',
            candidates=[dict(rank=i,surface=c['surface'],local_cost=c['local_cost']) for i,c in enumerate(snapshot['candidates'])])
        facts=snapshot['product_state']
        receipt=native.bind_evaluator_input(snapshot,request,facts)
        self.assertFalse(receipt['legacy_feature_provenance_verified'])
        self.assertFalse(receipt['final_evaluation_admitted'])
        changed=copy.deepcopy(request); changed['candidates'].reverse()
        with self.assertRaises(native.NativeSnapshotError): native.bind_evaluator_input(snapshot,changed,facts)
        changed=copy.deepcopy(request); changed['left_context']='unobserved'
        with self.assertRaises(native.NativeSnapshotError): native.bind_evaluator_input(snapshot,changed,facts)
        changed=dict(facts,selection_allowed=False)
        with self.assertRaises(native.NativeSnapshotError): native.bind_evaluator_input(snapshot,request,changed)

    def test_legacy_binding_never_clips_large_native_population(self):
        snapshot=native.inspect_event(event(count=108))['snapshot']
        with self.assertRaisesRegex(native.NativeSnapshotError,'legacy evaluator'):
            native.bind_evaluator_input(snapshot,{},snapshot['product_state'])

    def test_duplicate_json_and_permission_claims_are_not_provenance(self):
        plan,result,raw,kw=bundle()
        changed=json.loads(result); changed['gold_evidence']=True
        result=canonical_json_bytes(changed); kw['expected_result_sha256']=hashlib.sha256(result).hexdigest()
        with self.assertRaises(native.NativeSnapshotError): native.verify_capture(plan,result,raw,**kw)
        with self.assertRaises(native.NativeSnapshotError): native._document(b'{"a":1,"a":2}')

    def test_resealed_replay_and_control_divergence_are_rejected(self):
        plan,result,raw,kw=bundle()
        events=[json.loads(line) for line in raw.splitlines()]
        events[1]['baseline_run']=True
        raw=b'\n'.join(canonical_json_bytes(v) for v in events)+b'\n'
        changed=json.loads(result); changed['capture_sha256']=hashlib.sha256(raw).hexdigest()
        result=canonical_json_bytes(changed); kw['expected_result_sha256']=hashlib.sha256(result).hexdigest()
        with self.assertRaises(native.NativeSnapshotError): native.verify_capture(plan,result,raw,**kw)


if __name__=='__main__': unittest.main()
