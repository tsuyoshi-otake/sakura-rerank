import unittest

from sakura_rerank.data.ranking_signal import conflicts,describe,coverage


def row(i,target="甲",reading="こう",source=None,context=None):
    return dict(stable_id=str(i),reading=reading,target=target,left_context=context or "合成文脈"+str(i),
                source=dict(article_id=source or str(i)))


class RankingSignalTests(unittest.TestCase):
    def test_single_form_dominance_is_not_a_context_contrast(self):
        result,forms,witnesses=describe([row(i) for i in range(10)])
        self.assertEqual(result["single_form_rows"],10)
        self.assertEqual(result["reading_majority_disagreement_rows"],0)
        self.assertEqual(witnesses,[])
        self.assertEqual(coverage([row(11,"乙")],forms)["row_states"],{"target_form_unseen":1})

    def test_four_independent_contexts_produce_a_surface_witness(self):
        data=[row(0),row(1),row(2,"乙"),row(3,"乙")]
        result,forms,witnesses=describe(data)
        self.assertEqual(result["witness_rows"],4);self.assertEqual(len(witnesses),1)
        self.assertEqual(result["reading_majority_disagreement_rows"],2)
        for r in data:r["contrast_group"]="synthetic"
        self.assertEqual(coverage(data,forms)["contrast_states"],{"both_forms_at_least_two_train_rows":1})
        for r in data:r["source"]["article_id"]="shared"
        self.assertEqual(describe(data)[0]["witness_rows"],0)

    def test_conflict_ceiling_counts_majority_not_all_conflicting_rows(self):
        result=conflicts([("a","x"),("a","x"),("a","y"),("b","z")])
        self.assertEqual(result["contradictory_rows"],3)
        self.assertEqual(result["unavoidable_source_disagreements"],1)
        self.assertEqual(result["empirical_deterministic_source_ceiling"],.75)

    def test_audit_replay_is_order_independent_and_duplicate_ids_fail(self):
        data=[row(i,"甲" if i<3 else "乙") for i in range(6)]
        first=describe(data);second=describe(list(reversed(data)))
        self.assertEqual(first[0],second[0]);self.assertEqual(first[1],second[1]);self.assertEqual(first[2],second[2])
        with self.assertRaises(ValueError):describe([row(0),row(0)])


if __name__=="__main__":unittest.main()
