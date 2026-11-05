"""Contracts for the separate, posthoc #33 analysis (not model acceptance tests)."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location("fundamental_diagnostics", Path(__file__).resolve().parents[1]/"research/issue-33-fundamentals/diagnose.py")
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


class FundamentalDiagnosticsTests(unittest.TestCase):
    def arrays(self):
        return dict(candidate_mask=np.ones((4,3),dtype=bool),
                    correct_mask=np.array([[1,0,0],[0,1,0],[0,0,0],[1,1,0]],dtype=bool),
                    baseline_equivalent=np.array([[1,0,0],[1,0,0],[1,0,0],[1,1,0]],dtype=bool),
                    context_ids=np.arange(4*64).reshape(4,64),context_lengths=np.array([8,9,10,11]))

    def test_surface_counts_missing_gold_and_strict_gate(self):
        arrays=self.arrays()
        scores=np.array([[0,1.7,-3],[0,2,-3],[0,2,-3],[0,2,-3]],dtype=float)
        raw=diagnostics.outcomes(scores,arrays)[0]
        gated=diagnostics.outcomes(scores,arrays,True)[0]
        self.assertEqual(raw,dict(rows=4,correct=2,changed=3,rescue=1,harm=1,wrong_to_wrong=1))
        self.assertEqual(gated,dict(rows=4,correct=3,changed=2,rescue=1,harm=0,wrong_to_wrong=1))

    def test_padded_score_cannot_win_and_nonfinite_fails(self):
        arrays=self.arrays();arrays["candidate_mask"][:,2]=False
        scores=np.tile([0,1,999],(4,1)).astype(float)
        self.assertTrue((diagnostics.outcomes(scores,arrays)[1]==1).all())
        scores[0,0]=np.nan
        with self.assertRaises(ValueError): diagnostics.outcomes(scores,arrays)

    def test_context_variants_leave_original_and_other_inputs_unchanged(self):
        arrays=self.arrays();before={k:v.copy() for k,v in arrays.items()}
        meta=[dict(corpus="a",context_chars=int(n)) for n in arrays["context_lengths"]]
        variants=dict(diagnostics.variants(arrays,meta))
        self.assertEqual(len(variants),6)
        np.testing.assert_array_equal(variants["tail8"]["context_ids"][1,:8],arrays["context_ids"][1,1:9])
        self.assertEqual(int(variants["empty"]["context_lengths"].sum()),0)
        for key in arrays: np.testing.assert_array_equal(arrays[key],before[key])
        for variant in variants.values():
            for key in ("candidate_mask","correct_mask","baseline_equivalent"):
                self.assertIs(variant[key],arrays[key])

    def test_shuffle_respects_groups_is_deterministic_and_has_no_fixed_points(self):
        arrays=self.arrays()
        meta=[dict(corpus="a" if i<2 else "b",context_chars=8) for i in range(4)]
        _,donor=diagnostics.shuffled_context(arrays,meta,123)
        _,again=diagnostics.shuffled_context(arrays,meta,123)
        np.testing.assert_array_equal(donor,again)
        self.assertTrue((donor!=np.arange(4)).all())
        self.assertEqual([meta[i]["corpus"] for i in donor],[r["corpus"] for r in meta])
        with self.assertRaises(ValueError): diagnostics.shuffled_context(arrays,meta[:1],123)

    def test_oracle_bound_is_not_ensemble_accuracy(self):
        arrays=self.arrays()
        values=np.array([[0,2,-3],[0,2,-3],[0,2,-3],[0,2,-3]],dtype=float)
        result=diagnostics.saved_diagnostics({"one":values},arrays)
        self.assertEqual(result["overlap"]["any_model_correct"],2)
        self.assertEqual(result["overlap"]["label_aware_model_or_baseline_selection_ceiling_correct"],3)
        self.assertEqual(result["models"]["one"]["perfect_apply_or_keep_ceiling_correct"],3)


if __name__ == "__main__": unittest.main()
