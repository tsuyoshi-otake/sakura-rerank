import unittest
import numpy as np

from sakura_rerank.growth_metrics import observe,summarize


class GrowthMetricTests(unittest.TestCase):
    def fixture(self):
        arrays=dict(candidate_mask=np.array([[1,1,1]]*5+[[0,0,0]],dtype=bool),
            correct_mask=np.array([[1,0,0],[0,1,0],[0,0,1],[1,1,0],[1,0,0],[0,0,0]],dtype=bool),
            baseline_equivalent=np.array([[1,0,0],[1,0,0],[1,0,0],[1,1,0],[1,0,0],[0,0,0]],dtype=bool))
        arrays={key:np.pad(value,((0,0),(0,3))) for key,value in arrays.items()}
        scores=np.array([[0,2,0],[0,2,0],[0,2,0],[0,2,0],[float("nan"),0,0],[0,0,0]],dtype=float)
        return arrays,np.pad(scores,((0,0),(0,3)),constant_values=-10000)

    def test_surface_equivalence_failures_and_fixed_denominators(self):
        arrays,scores=self.fixture();result=summarize(observe(arrays,scores,"ungated"))
        self.assertEqual([result[k] for k in ("rows","rescue","harm","wrong_to_wrong","changed")],[6,1,1,1,3])
        self.assertEqual(result["correct"],3)
        self.assertEqual(result["candidate_acquisition_failure"],1)
        self.assertEqual(result["model_inference_failure"],1)
        self.assertEqual(result["precision"]["value"],1/3)
        self.assertEqual(result["recall"]["denominator"],3)

    def test_threshold_is_strict_and_never_drops_a_row(self):
        arrays,scores=self.fixture();scores[0,1]=1.7
        result=summarize(observe(arrays,scores,"gated"))
        self.assertEqual(result["rows"],6)
        self.assertEqual(result["harm"],0)
        self.assertEqual(result["baseline_gain"],1/6)


if __name__=="__main__":unittest.main()
