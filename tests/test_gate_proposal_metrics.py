"""Information-loss bounds retain all targets and distinguish overlap from conflict."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

path=Path(__file__).resolve().parents[1]/'research/issue-34-cpu-proposals/proposal_metrics.py'
spec=importlib.util.spec_from_file_location('gate_proposal_metrics',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class GateProposalMetricsTests(unittest.TestCase):
    def test_same_input_conflicting_targets_have_irreducible_error(self):
        correct=np.eye(6,dtype=np.bool_)[[0,0,1,2]]
        result=module.input_ceiling(['a','a','a','b'],correct,list(range(4)))
        self.assertEqual(result['maximum_source_matches'],3);self.assertEqual(result['unavoidable_source_mismatches'],1)
        self.assertEqual(result['incompatible_label_groups'],1);self.assertEqual(result['rows_in_incompatible_groups'],3)

    def test_identical_labels_are_duplicates_not_conflicts(self):
        result=module.input_ceiling(['a','a'],np.eye(6,dtype=np.bool_)[[2,2]],[0,1])
        self.assertEqual(result['duplicate_excess'],1);self.assertEqual(result['incompatible_label_groups'],0)
        self.assertEqual(result['empirical_source_match_ceiling'],1)

    def test_overlapping_acceptable_sets_do_not_imply_impossible_choice(self):
        correct=np.zeros((2,6),np.bool_);correct[0,[0,1]]=True;correct[1,[1,2]]=True
        result=module.input_ceiling(['a','a'],correct,[0,1])
        self.assertEqual(result['label_variation_groups'],1);self.assertEqual(result['incompatible_label_groups'],0)

    def test_selected_population_is_not_replaced_with_majority_examples(self):
        correct=np.eye(6,dtype=np.bool_)[[0,0,1]]
        result=module.input_ceiling(['a','a','a'],correct,[1,2])
        self.assertEqual(result['rows'],2);self.assertEqual(result['maximum_source_matches'],1)

    def test_empty_population_and_invalid_denominators(self):
        correct=np.eye(6,dtype=np.bool_)[[0,1]]
        self.assertIsNone(module.input_ceiling(['a','b'],correct,[])['empirical_source_match_ceiling'])
        for positions in ([0,0],[2],[-1]):
            with self.assertRaises(ValueError):module.input_ceiling(['a','b'],correct,positions)
        with self.assertRaises(ValueError):module.input_ceiling(['a'],correct,[0])


if __name__=='__main__':unittest.main()
