import unittest

from sakura_rerank.data.growth_numeric import eligible_target,encode


def candidate(surface,cost=0,source="system_dictionary"):
    return dict(surface=surface,local_cost=cost,source_category=source,segments=[dict(source_category=source)])


class NumericTests(unittest.TestCase):
    def test_training_requires_unique_target_and_dictionary_path(self):
        self.assertTrue(eligible_target("正解",[candidate("候補"),candidate("正解",100)])[0])
        for values in ([candidate("正解")],[candidate("候補"),candidate("別")],
                       [candidate("正解"),candidate("正解",100)],
                       [candidate("候補"),candidate("正解",100,"fallback")]):
            self.assertFalse(eligible_target("正解",values)[0])

    def test_cache_counts_missing_targets_and_surface_equivalent_candidates(self):
        target=dict(stable_id="a",component_id="b",corpus="jawiki",reading="よみ",left_context="前文が八文字以上ある",target="正解",candidate_request_id="r")
        snapshots={"r":dict(candidate_snapshots={"training_top32":dict(candidates=[candidate("候補"),candidate("候補",100),candidate("正解",200)])})}
        arrays,metadata=encode([target,dict(target,candidate_request_id="missing")],snapshots)
        self.assertEqual(arrays["gold"].tolist(),[2,-1])
        self.assertEqual(arrays["baseline_equivalent"][0].tolist(),[True,True,False,False,False,False])
        self.assertEqual(arrays["correct_mask"][0].tolist(),[False,False,True,False,False,False])
        self.assertFalse(arrays["candidate_mask"][1].any())
        self.assertEqual(metadata[1]["acquisition_status"],"failed")
        self.assertEqual(arrays["features"].shape,(2,6,7))


if __name__=="__main__":unittest.main()
