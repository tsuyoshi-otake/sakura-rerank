import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

try:
    import numpy as np
    import torch
except ImportError:
    np=None
    torch=None

ROOT=Path(__file__).parents[1]
if np is not None and torch is not None:
    spec=importlib.util.spec_from_file_location('balanced_reconstruction_loss',ROOT/'research/issue-33-loss-balance/balanced_loss.py')
    loss=importlib.util.module_from_spec(spec);spec.loader.exec_module(loss)


@unittest.skipIf(np is None or torch is None,'numpy/torch unavailable')
class BalancedReconstructionLossTests(unittest.TestCase):
    def test_all_one_weights_preserve_legacy_loss_and_gradients(self):
        tree=ast.parse((ROOT/'research/issue-21-retrain/run.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='loss_fn')
        namespace={'LABEL_SMOOTHING':.05,'rt':SimpleNamespace(TOP_K=6)}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'legacy_c2_loss','exec'),namespace)
        original=torch.tensor([[1.,0.,-.5,-10000.,-10000.,-10000.],[.5,1.,0.,.3,-10000.,-10000.]],requires_grad=True)
        proposed=original.detach().clone().requires_grad_(True)
        mask=torch.tensor([[True,True,True,False,False,False],[True,True,True,True,False,False]])
        gold=torch.tensor([0,2])
        before=namespace['loss_fn'](original,gold,mask,'C2')
        after=loss.weighted_c2_loss(proposed,gold,mask,torch.ones(2))
        self.assertTrue(torch.equal(before,after))
        before.backward();after.backward();self.assertTrue(torch.equal(original.grad,proposed.grad))

    def test_source_mass_and_common_rows_remain_fixed(self):
        correct=np.array([True,True,False,True, True,True,True,False, True,False,False,False])
        cohorts={'dictionary':np.arange(8),'annotation':np.array([0,1,2,3,8,9,10,11])}
        weights,info=loss.source_class_weights(correct,cohorts,4)
        self.assertTrue(np.array_equal(weights[:8],np.ones(8,dtype=np.float32)))
        self.assertEqual(weights[8],3)
        self.assertTrue(np.allclose(weights[9:],1/3))
        self.assertAlmostEqual(info['annotation_total_weight_mass'],8,places=6)

    def test_batch_weight_sum_is_not_the_reduction_denominator(self):
        scores=torch.zeros((2,6));mask=torch.ones((2,6),dtype=torch.bool);gold=torch.tensor([0,1])
        result=loss.weighted_c2_loss(scores,gold,mask,torch.tensor([.25,.5]))
        self.assertAlmostEqual(float(result),float(torch.log(torch.tensor(6.)))*.375,places=6)

    def test_missing_annotation_class_fails_closed(self):
        cohorts={'dictionary':np.array([0,1,2,3]),'annotation':np.array([0,1,4,5])}
        with self.assertRaises(ValueError):loss.source_class_weights(np.array([True,False,True,False,True,True]),cohorts,2)

    def test_invalid_gold_mask_is_rejected(self):
        scores=torch.zeros((1,6));mask=torch.tensor([[True,False,False,False,False,False]])
        with self.assertRaises(ValueError):loss.weighted_c2_loss(scores,torch.tensor([1]),mask,torch.ones(1))

    def test_nonpositive_and_nonfinite_weights_are_rejected(self):
        scores=torch.zeros((1,6));mask=torch.ones((1,6),dtype=torch.bool);gold=torch.tensor([0])
        for value in (0.,-1.,float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                loss.weighted_c2_loss(scores,gold,mask,torch.tensor([value]))


if __name__=='__main__':unittest.main()
