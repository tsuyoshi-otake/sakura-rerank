"""Prespecified shared-draw statistics; no seed selection or interval averaging."""
import importlib.util
from pathlib import Path
import unittest

_spec=importlib.util.spec_from_file_location('annotation_comparison_statistics',
    Path(__file__).resolve().parents[1]/'research/issue-33-annotation-experiment/experiment_statistics.py')
statistics=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statistics)


class PairedSeedTests(unittest.TestCase):
    def test_opposite_seed_effects_cancel_in_every_component_draw(self):
        result=statistics.mean_seed_comparison(['a','b','c','d'],
            [[1,1,-1,-1],[-1,-1,1,1],[0,0,0,0]],inference_complete=True)
        self.assertEqual(result['mean_difference'],0)
        self.assertEqual(result['ci95'],[0.,0.])
        self.assertEqual(result['interval']['component_count'],4)
        self.assertFalse(result['advances'])

    def test_all_three_positive_seeds_advance_only_with_completed_inference(self):
        for complete in (True,False):
            result=statistics.mean_seed_comparison(['same','same','other'],[[1,1,1]]*3,inference_complete=complete)
            self.assertEqual(result['ci95'],[1.,1.])
            self.assertEqual(result['interval']['component_count'],2)
            self.assertEqual(result['advances'],complete)

    def test_positive_mean_cannot_hide_a_negative_seed(self):
        result=statistics.mean_seed_comparison(['a','b'],[[1,1],[1,1],[-1,-1]],inference_complete=True)
        self.assertAlmostEqual(result['mean_difference'],1/3)
        self.assertGreater(result['ci95'][0],0)
        self.assertFalse(result['advances'])

    def test_missing_seed_and_out_of_range_indicators_are_rejected(self):
        for values in ([[1],[1]],[[2],[0],[0]],[[.5],[0.],[0.]]):
            with self.assertRaisesRegex(ValueError,'paired_seed_indicator_shape'):
                statistics.mean_seed_comparison(['a'],values,inference_complete=True)


if __name__=='__main__':
    unittest.main()
