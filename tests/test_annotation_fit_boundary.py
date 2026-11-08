"""Train-only access and immutable-byte contracts for the paired research fit."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]/'research/issue-33-annotation-experiment'
sys.path.insert(0,str(HERE))
try:
    _spec=importlib.util.spec_from_file_location('annotation_fit_boundary_tests',HERE/'experiment_fit_contract.py')
    fit=importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(fit)
finally:
    sys.path.pop(0)


class FitBoundaryTests(unittest.TestCase):
    def test_only_bound_training_reads_and_owned_model_outputs_are_allowed(self):
        root=Path.cwd();allowed=root/'data/generated/synthetic-train/arrays.npz'
        output=root/'data/generated/synthetic-fit/models'
        guard=fit.TrainingReadGuard(root,[allowed],output)
        guard('open',(str(allowed),'rb',0))
        guard.check(output/'model.pt','rb')
        self.assertEqual(len(guard.observed),2)
        for path in (root/'data/generated/synthetic-eval/arrays.npz',root/'data/downloads/synthetic-source',
                     output/'..'/'evaluation.npz'):
            with self.assertRaisesRegex(ValueError,'evaluation_or_unbound_data_read_forbidden'):
                guard.check(path,'rb')
        self.assertEqual(guard.blocked,3)

    def test_read_write_mode_and_os_read_flags_cannot_bypass_guard(self):
        root=Path.cwd();guard=fit.TrainingReadGuard(root,[],root/'data/generated/synthetic-fit/models')
        forbidden=root/'data/generated/synthetic-eval/arrays.npz'
        for mode in ('r+b','a+',None):
            with self.assertRaises(ValueError):guard.check(forbidden,mode,0)
        guard.check(123,'rb')
        guard.check(root/'src/synthetic-code.py','rb')

    def test_authenticated_bytes_are_retained_after_path_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'artifact';path.write_bytes(b'original')
            digest=hashlib.sha256(b'original').hexdigest()
            raw=fit.authenticated_bytes(path,digest,8)
            path.write_bytes(b'replaced')
            self.assertEqual(raw,b'original')
            with self.assertRaisesRegex(ValueError,'authenticated_bytes_changed'):
                fit.authenticated_bytes(path,digest,8)

    def test_input_size_is_bounded_before_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'artifact';path.write_bytes(b'12345')
            with self.assertRaisesRegex(ValueError,'fit_artifact_byte_bound'):
                fit.authenticated_bytes(path,hashlib.sha256(b'12345').hexdigest(),4)


if __name__=='__main__':
    unittest.main()
