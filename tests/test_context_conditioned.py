import importlib.util
from pathlib import Path
import tempfile
import unittest

from sakura_rerank.context_conditioned import build_context_conditioned
from sakura_rerank import research_tiny

try:
    import torch
except ImportError:
    torch=None


@unittest.skipIf(torch is None,"optional PyTorch unavailable")
class ContextConditionedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(torch.set_num_threads,torch.get_num_threads());torch.set_num_threads(1)

    def models(self):
        torch.manual_seed(20261105)
        # Public reference core needs no ignored historical harness or datasets.
        # The real seven-feature C2 state mapping is also checked at fit time.
        base=research_tiny.build_model().eval()
        model=build_context_conditioned(research_tiny.build_model).eval()
        model.load_state_dict(base.state_dict(),strict=True)
        return base,model

    def inputs(self):
        torch.manual_seed(123)
        return [torch.randint(1,100,(2,64)),torch.tensor([8,0]),torch.randint(1,100,(2,32)),torch.tensor([3,4]),
                torch.randint(1,100,(2,6,32)),torch.full((2,6),5,dtype=torch.int64),
                torch.randn(2,6,research_tiny.FEATURE_DIM),torch.tensor([[True,True,True,False,False,False],[True]*6])]

    def test_same_parameter_names_shapes_and_exact_initial_weight_mapping(self):
        base,model=self.models()
        self.assertEqual(set(base.state_dict()),set(model.state_dict()))
        for key,value in base.state_dict().items():self.assertTrue(torch.equal(value,model.state_dict()[key]))
        self.assertEqual(sum(p.numel() for p in base.parameters()),sum(p.numel() for p in model.parameters()))

    def test_empty_context_matches_reference_and_invalid_candidates_stay_masked(self):
        base,model=self.models();inputs=self.inputs();inputs[1].zero_()
        with torch.no_grad():expected=base(*inputs);actual=model(*inputs)
        torch.testing.assert_close(actual,expected,atol=1e-6,rtol=1e-6)
        self.assertTrue(torch.equal(actual[~inputs[-1]],torch.full_like(actual[~inputs[-1]],-10000.0)))

    def test_padding_after_declared_lengths_cannot_change_scores(self):
        _,model=self.models();inputs=self.inputs()
        changed=[t.clone() for t in inputs]
        for i in range(2):
            changed[0][i,changed[1][i]:]=200
            changed[2][i,changed[3][i]:]=201
            for j in range(6):changed[4][i,j,changed[5][i,j]:]=202
        with torch.no_grad():torch.testing.assert_close(model(*inputs),model(*changed),atol=0,rtol=0)

    def test_candidate_permutation_moves_scores_with_candidate_features(self):
        _,model=self.models();inputs=self.inputs();order=torch.tensor([5,2,4,0,1,3])
        permuted=inputs[:4]+[inputs[i][:,order] for i in range(4,8)]
        with torch.no_grad():torch.testing.assert_close(model(*permuted),model(*inputs)[:,order],atol=1e-6,rtol=1e-6)

    def test_context_gradient_reaches_candidate_path_without_direct_context_scorer_block(self):
        _,model=self.models();inputs=self.inputs()
        inputs[0].fill_(500);inputs[1].fill_(8)
        with torch.no_grad():model.scorer[0].weight[:,:model.encoder.hidden_size].zero_()
        model(*inputs)[0,0].backward()
        self.assertGreater(float(model.embedding.weight.grad[500].abs().sum()),0.0)

    @unittest.skipUnless(importlib.util.find_spec("onnx") and importlib.util.find_spec("onnxruntime"),"optional ONNX runtime unavailable")
    def test_exported_cpu_scores_match_both_empty_and_nonempty_context(self):
        import numpy as np
        import onnx
        import onnxruntime as ort
        _,model=self.models();inputs=self.inputs()
        names=("context_ids","context_lengths","reading_ids","reading_lengths","candidate_ids","candidate_lengths","features","candidate_mask")
        with tempfile.TemporaryDirectory(prefix="context-onnx-test-") as directory:
            path=Path(directory)/"model.onnx"
            torch.onnx.export(model,tuple(t[:1] for t in inputs),path,input_names=list(names),output_names=["scores"],
                dynamic_axes={name:{0:"batch"} for name in (*names,"scores")},opset_version=18,dynamo=False)
            onnx.checker.check_model(onnx.load(path))
            options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
            session=ort.InferenceSession(str(path),sess_options=options,providers=["CPUExecutionProvider"])
            with torch.no_grad():expected=model(*inputs).numpy()
            actual=session.run(None,{name:t.numpy() for name,t in zip(names,inputs)})[0]
            np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=1e-5)
            del session


if __name__=="__main__":unittest.main()
