"""Synthetic evaluation-boundary cases that the training-only validator rejects."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

from sakura_rerank.data.growth_numeric import encode

_spec=importlib.util.spec_from_file_location('annotation_evaluation_numeric',
    Path(__file__).resolve().parents[1]/'research/issue-33-annotation-experiment/numeric_verifier.py')
numeric=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(numeric)


def target(surface='仮甲'):
    return dict(stable_id='synthetic-row',component_id='synthetic-component',corpus='synthetic',
                left_context='あいうえおかきく',reading='かこう',target=surface,candidate_request_id='synthetic-request')


def snapshot(surfaces):
    candidates=[dict(surface=surface,local_cost=1000+index*1000,source_category='system_dictionary',
                     segments=[dict(source_category='system_dictionary')]) for index,surface in enumerate(surfaces)]
    return dict(candidate_snapshots=dict(training_top32=dict(candidates=candidates),
                                        production_top6=dict(candidates=candidates[:6])))


class EvaluationNumericTests(unittest.TestCase):
    def assert_verified(self,row,snapshots):
        arrays,_=encode([row],snapshots)
        self.assertTrue(numeric.verify_saved([row],snapshots,arrays)['bitwise_equal'])
        return arrays

    def test_failed_acquisition_is_an_explicit_empty_candidate_row(self):
        arrays=self.assert_verified(target(),{})
        self.assertEqual(int(arrays['gold'][0]),-1)
        self.assertFalse(arrays['candidate_mask'].any())
        self.assertFalse(arrays['correct_mask'].any())
        self.assertEqual(int(arrays['reading_lengths'][0]),3)

    def test_source_absence_keeps_candidates_and_negative_gold(self):
        arrays=self.assert_verified(target(),{'synthetic-request':snapshot(['仮乙','仮丙'])})
        self.assertEqual(int(arrays['gold'][0]),-1)
        self.assertEqual(int(arrays['candidate_mask'].sum()),2)
        self.assertTrue(arrays['baseline_equivalent'][0,0])
        self.assertAlmostEqual(float(arrays['features'][0,1,6]),-np.log(2),places=6)

    def test_candidate_truncation_never_changes_original_surface_label(self):
        surface='仮'*33
        arrays=self.assert_verified(target('仮'*32),{'synthetic-request':snapshot([surface,'仮乙'])})
        self.assertEqual(int(arrays['candidate_lengths'][0,0]),32)
        self.assertEqual(float(arrays['features'][0,0,3]),33/32)
        self.assertFalse(arrays['correct_mask'].any())

    def test_duplicate_exact_surfaces_retain_all_equivalences(self):
        arrays=self.assert_verified(target(),{'synthetic-request':snapshot(['仮甲','仮甲'])})
        self.assertEqual(int(arrays['gold'][0]),0)
        self.assertEqual(int(arrays['correct_mask'].sum()),2)
        self.assertEqual(int(arrays['baseline_equivalent'].sum()),2)

    def test_byte_mutation_including_signed_zero_is_detected(self):
        row=target();snapshots={'synthetic-request':snapshot(['仮甲','仮乙'])}
        arrays,_=encode([row],snapshots)
        self.assertTrue(np.signbit(arrays['features'][0,0,6]))
        arrays['features'][0,0,6]=0.
        with self.assertRaisesRegex(ValueError,'evaluation_complete_tensor_difference'):
            numeric.verify_saved([row],snapshots,arrays)

    def test_candidate_prefix_and_input_bound_cannot_silently_change(self):
        row=target();value=snapshot(['仮甲','仮乙'])
        value['candidate_snapshots']['production_top6']['candidates']=[]
        with self.assertRaisesRegex(ValueError,'evaluation_candidate_prefix'):
            numeric.original_arrays([row],{'synthetic-request':value})
        row['left_context']='短'
        with self.assertRaisesRegex(ValueError,'evaluation_input_length'):
            numeric.original_arrays([row],{})


if __name__=='__main__':
    unittest.main()
