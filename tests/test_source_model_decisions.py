"""Published gates, padding, ties and model failures keep explicit semantics."""
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]/'research/issue-35-source-models'
sys.path.insert(0,str(HERE))
try:
    from source_score_outcomes import fixed_observation
finally:
    sys.path.pop(0)


class SourceModelDecisionTests(unittest.TestCase):
    def test_gate_is_strict_and_uses_frozen_threshold(self):
        self.assertEqual(fixed_observation([0,1.7,-1,-2,-3,-4],'complete',6,1.7).status,'abstained')
        self.assertEqual(fixed_observation([0,1.700001,-1,-2,-3,-4],'complete',6,1.7).ranking[0],1)

    def test_ties_preserve_local_order(self):
        self.assertEqual(fixed_observation([1]*6,'complete',6).ranking,tuple(range(6)))
        self.assertEqual(fixed_observation([1]*6,'complete',6,0).status,'abstained')

    def test_inactive_slots_cannot_win_even_with_large_output(self):
        self.assertEqual(fixed_observation([0,1,100,100,100,100],'complete',2).ranking,(1,0))

    def test_failure_and_unavailability_preserve_attempt_status(self):
        failed=fixed_observation([], 'error',2)
        absent=fixed_observation([], 'unavailable',2)
        self.assertTrue(failed.attempted);self.assertFalse(absent.attempted)
        self.assertIsNone(failed.ranking);self.assertIsNone(absent.ranking)

    def test_bad_output_has_explicit_fallback_terminal(self):
        for scores in ([1,2],[float('nan')]*6,[float('inf')]*6):
            self.assertEqual(fixed_observation(scores,'complete',6).status,'malformed')

    def test_invalid_input_contract_is_not_silently_a_fallback(self):
        for count,status,tau in ((0,'complete',None),(7,'complete',None),(6,'unknown',None),(6,'complete',-1)):
            with self.assertRaises(ValueError):fixed_observation([0]*6,status,count,tau)


if __name__=='__main__':unittest.main()
