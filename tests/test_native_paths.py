"""Raw path contracts and unchanged model math on synthetic cases."""
import copy
import hashlib
import unittest

from sakura_rerank import native_paths as paths,native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.native_path_inputs import encode_request,legacy_feature_candidates
from sakura_rerank.source_model_inputs import encode_snapshot,model_feed
from tests.test_native_snapshot import event


def add_paths(value):
    value=copy.deepcopy(value);value['path_version']=1
    for frame in value['captures']:
        for candidate in frame['candidates']:
            candidate['path']=dict(kind='viterbi_materialization',reading_hex=frame['reading_hex'],surface_hex=candidate['surface_hex'],
                segments=[dict(reading_start=0,reading_end=len(bytes.fromhex(frame['reading_hex'])),text_start=0,
                    text_end=len(bytes.fromhex(candidate['surface_hex'])),left_id=0,right_id=0,flags=0,source_category='system_dictionary')])
            candidate['display_segment_count']=1
    return value


def request_for(value):return native.population_input(paths.inspect_event(value)['snapshot'])


class NativePathTests(unittest.TestCase):
    def test_extension_preserves_native_base_and_all768_candidates(self):
        raw=event(count=768,baseline=767,allowed=False)
        extended=add_paths(raw)
        self.assertEqual(paths.base_event(extended),raw)
        inspected=paths.inspect_event(extended)
        request=native.population_input(inspected['snapshot'])
        row=dict(input=request,product_state=inspected['snapshot']['product_state'],native_capture=extended)
        receipt,_=paths.bind_evaluation_case(row,hashlib.sha256(canonical_json_bytes(extended)).hexdigest())
        self.assertEqual(receipt['candidate_count'],768)
        self.assertTrue(receipt['legacy_feature_provenance_verified'])
        self.assertFalse(receipt['final_evaluation_admitted'])

    def test_path_tamper_missing_and_extra_fields_are_refused(self):
        original=add_paths(event())
        for mutation in ('missing','gap','end','source','flags','text','reading','display','synthetic','extra'):
            value=copy.deepcopy(original);c=value['captures'][0]['candidates'][0];p=c['path'];s=p['segments'][0]
            if mutation=='missing':del c['path']
            if mutation=='gap':s['reading_start']=1
            if mutation=='end':s['text_end']-=1
            if mutation=='source':s['source_category']='guessed'
            if mutation=='flags':s['flags']=True
            if mutation=='text':p['surface_hex']='41'
            if mutation=='reading':p['reading_hex']='41'
            if mutation=='display':c['display_segment_count']=2
            if mutation=='synthetic':p['kind']='synthetic_materialization'
            if mutation=='extra':p['certified']=True
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):paths.inspect_event(value)

    def test_path_coordinates_are_utf8_bytes_and_must_cover_both_strings(self):
        edge=dict(reading_start=0,reading_end=3,text_start=0,text_end=3,left_id=1,right_id=1,flags=0,source_category='system_dictionary')
        path=dict(kind='viterbi_materialization',reading_hex='かな'.encode().hex(),surface_hex='仮名'.encode().hex(),
                  segments=[edge,dict(edge,reading_start=3,reading_end=6,text_start=3,text_end=6)])
        paths.validate_path(path,'かな','仮名',1)
        path['segments'][0]['reading_end']=2;path['segments'][1]['reading_start']=2
        with self.assertRaisesRegex(ValueError,'UTF-8'):paths.validate_path(path,'かな','仮名',1)

    def test_path_population_and_policy_commitments_are_distinct(self):
        value=add_paths(event());snapshot=paths.inspect_event(value)['snapshot'];request=copy.deepcopy(native.population_input(snapshot))
        row=dict(input=request,product_state=snapshot['product_state'],native_capture=value)
        digest=hashlib.sha256(canonical_json_bytes(value)).hexdigest()
        row['input']['candidates'][0]['path']['segments'][0]['source_category']='user_dictionary'
        with self.assertRaises(ValueError):paths.bind_evaluation_case(row,digest)
        self.assertNotEqual(paths.evaluation_policy('a'*64),native.evaluation_policy('a'*64,full_population=True))

    def test_diagnostic_metadata_cannot_claim_model_or_gold_admission(self):
        values=[add_paths(event(response=False,baseline_run=True)),add_paths(event())];values[1]['fixture']=1
        raw=b'\n'.join(canonical_json_bytes(v) for v in values)+b'\n'
        plan=canonical_json_bytes(dict(kind='native_state_probe_plan',version=3,source_head=native.HEAD,path_contract=paths.CONTRACT,
                                      synthetic_response_injection=True,expected_fixture_count=2))
        ps=hashlib.sha256(plan).hexdigest()
        result=dict(kind='native_state_probe_result',version=2,status='passed',plan_sha256=ps,capture_sha256=hashlib.sha256(raw).hexdigest(),
                    fixture_count=2,capture_count=2,applied=1,real_test=False,model_inference=False,gold_evidence=False,production_edits=False)
        for key in (None,'gold_evidence','model_inference'):
            changed=dict(result)
            if key:changed[key]=True
            serialized=canonical_json_bytes(changed)
            kwargs=dict(expected_plan_sha256=ps,expected_result_sha256=hashlib.sha256(serialized).hexdigest())
            if key:
                with self.assertRaises(ValueError):paths.verify_capture(plan,serialized,raw,**kwargs)
            else:self.assertEqual(len(paths.verify_capture(plan,serialized,raw,**kwargs)),2)


class NativePathInputTests(unittest.TestCase):
    def test_byte_parity_with_frozen_encoder_for_one_through_six_slots(self):
        import numpy as np
        for count in range(1,7):
            request=request_for(add_paths(event(count=max(count,3))))
            request['candidates']=request['candidates'][:count]
            legacy=legacy_feature_candidates(request['candidates'])
            source=dict(reading=request['reading'],candidate_snapshots=dict(production_top6=dict(candidates=legacy),training_top32=dict(candidates=legacy)))
            arrays,_=encode_snapshot(source)
            for width in (6,7):
                actual=encode_request(request,width);expected=model_feed(arrays,0,width)
                self.assertEqual(actual.keys(),expected.keys())
                for key in actual:self.assertEqual(actual[key].tobytes(),expected[key].tobytes())
                self.assertEqual(np.count_nonzero(actual['candidate_mask']),count)

    def test_pre_fusion_count_and_system_flag_do_not_use_native_evidence_group(self):
        request=request_for(add_paths(event()))
        candidate=request['candidates'][0]
        candidate['surface']='仮名仮名仮名';candidate['evidence_tag']=10
        candidate['native_fingerprint']=native.candidate_fingerprint(candidate['surface'],candidate['local_cost'],10)
        request['reading']='かなかなかな'
        for item in request['candidates']:
            item['path']['reading_hex']=request['reading'].encode().hex()
            item['path']['segments'][0]['reading_end']=18
        candidate['path']['surface_hex']=candidate['surface'].encode().hex()
        candidate['path']['segments']=[dict(reading_start=i*6,reading_end=(i+1)*6,text_start=i*6,text_end=(i+1)*6,
            left_id=1,right_id=1,flags=32,source_category='system_dictionary') for i in range(3)]
        candidate['display_segment_count']=1
        values=encode_request(request,6)
        self.assertEqual(values['features'][0,0,2],3/8)
        self.assertEqual(values['features'][0,0,5],1.)
        candidate['path']['segments'][1]['source_category']='user_dictionary'
        self.assertEqual(encode_request(request,6)['features'][0,0,5],0.)

    def test_native_extent_keeps_model_truncation_and_full_surface_feature(self):
        request=request_for(add_paths(event()))
        request['reading']='あ'*512
        for candidate in request['candidates']:
            candidate['surface']='😀'*384
            candidate['native_fingerprint']=native.candidate_fingerprint(candidate['surface'],candidate['local_cost'],candidate['evidence_tag'])
            p=candidate['path'];p.update(reading_hex=request['reading'].encode().hex(),surface_hex=candidate['surface'].encode().hex())
            p['segments'][0].update(reading_end=1536,text_end=1536)
        values=encode_request(request,7)
        self.assertEqual(values['reading_lengths'][0],32)
        self.assertEqual(values['candidate_lengths'][0,0],32)
        self.assertEqual(values['features'][0,0,3],12.)
        self.assertFalse(values['context_ids'].any())
        with self.assertRaises(ValueError):encode_request(request,8)


if __name__=='__main__':unittest.main()
