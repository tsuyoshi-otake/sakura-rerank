import importlib.util
from pathlib import Path
import unittest

try:
    import numpy as np
except ImportError:
    np=None

spec=importlib.util.spec_from_file_location('train_change_metrics',Path(__file__).parents[1]/'research/issue-33-train-change-audit/change_metrics.py')
if np is not None:
    metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)


@unittest.skipIf(np is None,'numpy unavailable')
class TrainChangeAuditTests(unittest.TestCase):
    def arrays(self):
        correct=np.array([[True,False,True,False,False,False], [False,True,False,False,False,False], [False,False,True,False,False,False]])
        equivalent=np.zeros((3,6),dtype=bool);equivalent[:,0]=True;equivalent[0,2]=True
        return dict(correct_mask=correct,baseline_equivalent=equivalent,candidate_mask=np.ones((3,6),dtype=bool))

    def test_equivalent_choice_is_not_a_change_and_counts_reconcile(self):
        scores=np.zeros((3,6),dtype=np.float32);scores[0,2]=3;scores[1,1]=3;scores[2,1]=3
        out=metrics.summary(metrics.observations(scores,self.arrays()),np.arange(3))
        self.assertEqual([out[k] for k in ('correct','rescue','harm','wrong_to_wrong','changed')],[2,1,0,1,2])

    def test_strict_gate_boundary_preserves_local_choice(self):
        scores=np.zeros((3,6),dtype=np.float32);scores[1,1]=np.float32(1.7)
        self.assertEqual(metrics.observations(scores,self.arrays(),True)['winner'][1],0)
        scores[1,1]=np.nextafter(np.float32(1.7),np.float32(2))
        self.assertEqual(metrics.observations(scores,self.arrays(),True)['winner'][1],1)

    def test_nonfinite_and_empty_candidates_fall_back_in_denominator(self):
        scores=np.zeros((3,6),dtype=np.float32);scores[0,1]=np.nan
        arrays=self.arrays();arrays['candidate_mask'][1]=False
        out=metrics.summary(metrics.observations(scores,arrays),np.arange(3))
        self.assertEqual(out['rows'],3);self.assertEqual(out['failed_inference'],2)
        self.assertEqual(out['changed'],0);self.assertIsNone(out['precision'])

    def test_partition_requires_complete_disjoint_equal_source_cohorts(self):
        groups=metrics.partitions({'dictionary':[0,1,2,3],'annotation':[0,1,4,5]},6,2)
        self.assertEqual(groups['common_wikipedia'].tolist(),[0,1])
        with self.assertRaises(ValueError):metrics.partitions({'dictionary':[0,1,2,3],'annotation':[0,1,2,5]},6,2)

    def test_reading_slices_do_not_drop_or_duplicate_rows(self):
        groups={'source':np.arange(4)}
        result=metrics.slices(groups,np.array([2,3,8,32]))
        self.assertEqual([len(result['source/reading-'+x]) for x in ('2','3-4','5-8','9-32')],[1,1,1,1])

    def test_paired_delta_uses_identical_membership(self):
        scores=np.zeros((3,6),dtype=np.float32);first=metrics.observations(scores,self.arrays())
        scores[0,1]=2;scores[1,1]=2;second=metrics.observations(scores,self.arrays())
        delta=metrics.paired(first,second,np.arange(3))
        self.assertEqual(delta['correct_difference'],0)
        self.assertEqual(delta['harm_difference'],1)
        self.assertEqual(delta['rescue_difference'],1)


if __name__=='__main__':unittest.main()
