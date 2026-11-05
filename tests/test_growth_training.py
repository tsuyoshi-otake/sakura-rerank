import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY=Path(__file__).resolve().parents[1]/"research/issue-33-data-growth"
sys.path.insert(0,str(DIRECTORY))
spec=importlib.util.spec_from_file_location("growth_train",DIRECTORY/"train.py")
training=importlib.util.module_from_spec(spec);spec.loader.exec_module(training)
sys.path.remove(str(DIRECTORY))


@unittest.skipUnless(importlib.util.find_spec("torch"),"optional PyTorch is not installed")
class TrainingBatchTests(unittest.TestCase):
    def test_full_cycles_cross_batch_boundaries_without_dropping_rows(self):
        import numpy as np
        indices=np.arange(10,17,dtype=np.int64)
        batches=list(training.batches(indices,20261105,4,9))
        self.assertEqual([len(batch) for batch in batches],[4]*9)
        values=np.concatenate(batches).tolist()
        self.assertTrue(set(values)<=set(indices.tolist()))
        for offset in range(0,35,7):self.assertEqual(sorted(values[offset:offset+7]),indices.tolist())

    def test_seed_reproduces_the_whole_update_budget(self):
        import numpy as np
        indices=np.arange(23,dtype=np.int64)
        a=np.concatenate(list(training.batches(indices,17,8,12)))
        b=np.concatenate(list(training.batches(indices,17,8,12)))
        self.assertTrue(np.array_equal(a,b))
        self.assertEqual(a.shape,(96,))


if __name__=="__main__":unittest.main()
