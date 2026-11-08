"""Research advancement requires paired benefit AND no seed's harm increase."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('loss_balance_statistics_contract',
    Path(__file__).resolve().parents[1]/'research/issue-33-loss-balance/balance_statistics.py')
statistics=importlib.util.module_from_spec(spec);spec.loader.exec_module(statistics)


class LossBalanceStatisticsTests(unittest.TestCase):
    def test_positive_accuracy_with_one_harm_increase_does_not_advance(self):
        result=statistics.mean_seed_comparison(['a','b'],[[1,1]]*3,[-3,1,-2],inference_complete=True)
        self.assertEqual(result['ci95'],[1.,1.])
        self.assertFalse(result['no_seed_harm_increase'])
        self.assertFalse(result['advances'])

    def test_positive_accuracy_and_nonincreasing_harm_require_complete_inference(self):
        for complete in (True,False):
            result=statistics.mean_seed_comparison(['a','a','b'],[[1,1,1]]*3,[0,-1,-3],inference_complete=complete)
            self.assertEqual(result['interval']['component_count'],2)
            self.assertEqual(result['advances'],complete)

    def test_shared_draws_cancel_opposite_seed_effects(self):
        result=statistics.mean_seed_comparison(['a','b'],[[1,-1],[-1,1],[0,0]],[0,0,0],inference_complete=True)
        self.assertEqual(result['ci95'],[0.,0.])
        self.assertFalse(result['advances'])

    def test_positive_mean_does_not_hide_a_losing_seed(self):
        result=statistics.mean_seed_comparison(['a','b'],[[1,1],[1,1],[-1,-1]],[-1,-2,-3],inference_complete=True)
        self.assertGreater(result['ci95'][0],0)
        self.assertFalse(result['advances'])

    def test_invalid_harm_count_shape_and_type_fail_closed(self):
        for harms in ([0,0],[0.,0.,0.],[[0,0,0]]):
            with self.subTest(harms=harms),self.assertRaises(ValueError):
                statistics.mean_seed_comparison(['a'],[[1]]*3,harms,inference_complete=True)


if __name__=='__main__':unittest.main()
