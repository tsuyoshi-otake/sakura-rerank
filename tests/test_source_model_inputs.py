"""Legacy prefix behavior is observed, never concealed by input filtering."""
import copy
import unittest

import numpy as np

from sakura_rerank.source_model_inputs import INPUT_NAMES,encode_snapshot,model_feed


def snapshot(reading='はし',surfaces=None):
    surfaces=surfaces or ['橋','箸','端','はし','ハシ','端子']
    candidates=[dict(surface=s,local_cost=1000+100*i,source_category='system_dictionary',
                     segments=[dict(source_category='system_dictionary')]) for i,s in enumerate(surfaces)]
    return dict(reading=reading,candidate_snapshots=dict(production_top6=dict(candidates=candidates),
                                                       training_top32=dict(candidates=copy.deepcopy(candidates))))


class SourceModelInputTests(unittest.TestCase):
    def test_long_input_is_encoded_with_legacy_prefix_and_counted(self):
        value=snapshot('あ'*32+'い',surfaces=['う'*32+str(i) for i in range(6)])
        arrays,profile=encode_snapshot(value)
        self.assertEqual(arrays['reading_lengths'][0],32)
        self.assertTrue(profile['reading_truncated'])
        self.assertEqual(profile['surface_truncations'],6)
        self.assertEqual(profile['same_prefix_collision_pairs'],15)
        self.assertTrue(profile['any_truncation'])

    def test_32_characters_are_not_reported_as_truncated(self):
        _,profile=encode_snapshot(snapshot('あ'*32))
        self.assertFalse(profile['any_truncation'])

    def test_targets_and_source_metadata_cannot_affect_model_feed(self):
        left=snapshot();right=copy.deepcopy(left)
        right.update(target='untrusted-label',gold_index=5,left_context='not an observed session',owner='unknown')
        a,_=encode_snapshot(left);b,_=encode_snapshot(right)
        self.assertEqual(set(a),set(INPUT_NAMES))
        for name in a:np.testing.assert_array_equal(a[name],b[name])
        self.assertFalse(a['context_ids'].any())
        self.assertFalse(a['context_lengths'].any())

    def test_v1_and_r2_feeds_share_first_six_features(self):
        arrays,_=encode_snapshot(snapshot())
        a=model_feed(arrays,0,6);b=model_feed(arrays,0,7)
        self.assertEqual(a['features'].shape,(1,6,6))
        self.assertEqual(b['features'].shape,(1,6,7))
        np.testing.assert_array_equal(a['features'],b['features'][:,:,:6])
        self.assertTrue(all(v.flags.c_contiguous for v in a.values()))

    def test_duplicate_full_surfaces_are_not_representation_loss(self):
        _,profile=encode_snapshot(snapshot(surfaces=['橋']*6))
        self.assertEqual(profile['encoded_surface_collision_pairs'],0)

    def test_fewer_than_six_candidates_keep_real_count_and_zero_padding(self):
        for count in (1,2,3,5):
            value=snapshot()
            for snap in value['candidate_snapshots'].values():snap['candidates']=snap['candidates'][:count]
            arrays,profile=encode_snapshot(value)
            self.assertEqual(profile['candidate_count'],count)
            np.testing.assert_array_equal(arrays['candidate_mask'][0],np.arange(6)<count)
            for name in ('candidate_ids','candidate_lengths','features'):
                self.assertFalse(arrays[name][0,count:].any())

    def test_invalid_candidate_prefix_or_bounds_fail_without_partial_feed(self):
        for kind in ('different_prefix','long_reading','nan','too_many_segments'):
            value=snapshot()
            if kind=='different_prefix':value['candidate_snapshots']['production_top6']['candidates'][0]['surface']='changed'
            if kind=='long_reading':value['reading']='あ'*129
            if kind=='nan':
                for snap in value['candidate_snapshots'].values():snap['candidates'][0]['local_cost']=float('nan')
            if kind=='too_many_segments':
                for snap in value['candidate_snapshots'].values():snap['candidates'][0]['segments']=[{}]*19
            with self.assertRaises(ValueError):encode_snapshot(value)

    def test_model_width_and_row_index_are_explicit(self):
        arrays,_=encode_snapshot(snapshot())
        for index,width in ((-1,6),(1,6),(0,8)):
            with self.assertRaises(ValueError):model_feed(arrays,index,width)


if __name__=='__main__':unittest.main()
