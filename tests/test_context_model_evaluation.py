import importlib.util
import sys
import unittest

import numpy as np

sys.path.insert(0,"research/issue-40-context-contrast")
try:
    spec=importlib.util.spec_from_file_location("context_evaluation_contract_test","research/issue-40-context-contrast/evaluate_models.py")
    evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
finally:sys.path.pop(0)


class ContextModelEvaluationTests(unittest.TestCase):
    def test_context_ablation_preserves_every_other_input_and_original_arrays(self):
        arrays=dict(context_ids=np.array([[1,2],[3,0]]),context_lengths=np.array([2,1]),features=np.array([9,8]))
        conditions=dict(shuffle=[1,0])
        empty=evaluation.context_arrays(arrays,conditions,"empty")
        shuffled=evaluation.context_arrays(arrays,conditions,"shuffled")
        np.testing.assert_array_equal(empty["context_lengths"],[0,0])
        np.testing.assert_array_equal(shuffled["context_lengths"],[1,2])
        np.testing.assert_array_equal(shuffled["context_ids"],[[3,0],[1,2]])
        np.testing.assert_array_equal(arrays["context_ids"],[[1,2],[3,0]])
        self.assertIs(shuffled["features"],arrays["features"])
        with self.assertRaises(ValueError):evaluation.context_arrays(arrays,conditions,"future-context")

    def test_contrast_clusters_union_document_and_reading_group_dependencies(self):
        rows=[dict(stable_id=str(i),source_component=s,contrast_group=g) for i,(s,g) in enumerate(
            [("a","x"),("b","x"),("b","y"),("c","y")])]
        independent=evaluation.cluster_ids(rows,list(range(4)),False)
        grouped=evaluation.cluster_ids(rows,list(range(4)),True)
        self.assertEqual(len(set(independent)),3)
        self.assertEqual(len(set(grouped)),1)
        self.assertEqual(grouped,list(reversed(evaluation.cluster_ids(rows,list(reversed(range(4))),True))))

    def test_no_applications_keep_precision_interval_undefined(self):
        observation=dict(correct=np.array([True,False]),baseline=np.array([True,False]),changed=np.array([False,False]))
        result=evaluation.uncertainty(observation,[0,1],["a","b"])
        self.assertIsNone(result["ratios"]["precision"]["ci95"])
        self.assertEqual(result["ratios"]["precision"]["invalid_replicates"],2000)
        self.assertEqual(result["ratios"]["baseline_gain"]["ci95"],[0.0,0.0])


if __name__=="__main__":unittest.main()
