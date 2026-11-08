import importlib.util
import sys
import unittest

sys.path.insert(0,"research/issue-41-language-pretraining")
try:
    spec=importlib.util.spec_from_file_location("language_guard_test","research/issue-41-language-pretraining/fit_language.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
finally:sys.path.pop(0)


class LanguageTrainingGuardTests(unittest.TestCase):
    def test_evaluation_arrays_sources_and_candidate_files_are_blocked(self):
        for path in (module.ROOT/"cache/evaluation.npz",module.ROOT/"source/synthetic.knp",module.ROOT/"candidates/synthetic.json",
                     module.PRIOR_ROOT/"cache/evaluation.npz",module.TRAIN_ROOT/"cache/evaluation.npz",module.ROOT/"forward-targets.jsonl"):
            with self.subTest(path=path):
                with self.assertRaises(PermissionError):module.forbid_evaluation_access("open",(path,"rb",0))

    def test_train_arrays_and_checkpoint_io_are_allowed(self):
        for path in (module.ROOT/"language-windows.npz",module.TRAIN_ROOT/"cache/train.npz",module.ROOT/"models/synthetic/model.pt"):
            module.forbid_evaluation_access("open",(path,"rb",0))
        module.forbid_evaluation_access("open",(1,"w",0))
        module.forbid_evaluation_access("other",())


if __name__=="__main__":unittest.main()
