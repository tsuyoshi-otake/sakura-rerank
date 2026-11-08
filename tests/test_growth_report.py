"""Exercise the entire frozen comparison family without real evaluation data."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

DIRECTORY=Path(__file__).resolve().parents[1]/"research/issue-33-data-growth"
sys.path.insert(0,str(DIRECTORY))
spec=importlib.util.spec_from_file_location("growth_evaluation",DIRECTORY/"evaluate.py")
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
sys.path.remove(str(DIRECTORY))


class GrowthReportTests(unittest.TestCase):
    def test_complete_family_and_undefined_precision_keep_fixed_population(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"cache").mkdir();(root/"evaluation").mkdir()
            mask=np.zeros((4000,6),dtype=bool);mask[:,:2]=True
            correct=np.zeros_like(mask);correct[:,0]=True
            np.savez(root/"cache/evaluation.npz",candidate_mask=mask,correct_mask=correct,baseline_equivalent=correct)
            scores=np.zeros((4000,6),dtype=np.float32);scores[:,0]=1
            seeds=[20260814,20261103,20261104]
            runs={"reference":scores}
            runs.update({f"{cohort}-s{seed}":scores for cohort in ("wiki_small","wiki_large","mixed") for seed in seeds})
            np.savez(root/"evaluation/scores.npz",**runs)
            (root/"evaluation/execution.json").write_text(json.dumps(dict(status="complete",fit_commit="f"*40,
                scores_sha256=evaluation.sha(root/"evaluation/scores.npz"))),encoding="utf-8")
            metadata=[dict(component_id="component",corpus="jawiki" if i<2000 else "aozora",reading_chars=4,
                source_exact_presence={str(k):True for k in (1,5,6,10,32)}) for i in range(4000)]
            (root/"cache/evaluation-metadata.jsonl").write_text("\n".join(json.dumps(row) for row in metadata),encoding="utf-8")
            published=[]
            def write(path,raw):
                if path.is_relative_to(root):path.write_bytes(raw)
                else:published.append(raw)
            with patch.object(evaluation,"ROOT",root),patch.object(evaluation,"authenticate_fit",return_value=({},dict(training=dict(seeds=seeds)))),patch.object(evaluation,"write_once",side_effect=write):
                result=evaluation.report("f"*40)
            self.assertEqual(result["rows"],4000)
            self.assertEqual(len(result["models"]),20)
            self.assertEqual(len(result["contrasts"]),50)
            self.assertEqual(len(published),1)
            for model in result["models"].values():
                self.assertEqual(model["accuracy"]["value"],1)
                self.assertIsNone(model["precision"]["value"])
                self.assertEqual(model["component_ci95"]["precision"]["invalid_replicates"],10000)
                self.assertIsNone(model["component_ci95"]["precision"]["ci95"])


if __name__=="__main__":unittest.main()
