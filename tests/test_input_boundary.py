import unittest

from sakura_rerank.data.input_boundary import (
    VIEWS, aggregate, build_views, collect_requests, request_id, score_view, token_class,
)


def token(surface, reading, alternative=False):
    return dict(surface=surface, reading=reading, alternative=alternative)


class InputBoundaryTests(unittest.TestCase):
    def test_phonetic_precedence_and_exact_literal_identity(self):
        self.assertEqual(token_class(token("ー", "ー")), "phonetic")
        for s in ("、", "「", "」", "☆", "。！？"):
            self.assertEqual(token_class(token(s, s)), "literal")
        for s, r in (("。", "."), ("Ａ", "Ａ"), ("1", "1"), ("一", "一"), ("カ", "カ"), ("", "")):
            self.assertEqual(token_class(token(s, r)), "unresolved")

    def test_split_preserves_literals_and_maximal_phonetic_runs(self):
        row = build_views([token("「", "「"), token("学校", "がっこう"), token("に", "に"),
                           token("、", "、"), token("行く", "いく"), token("。", "。")])
        self.assertEqual(row["reading"], "「がっこうに、いく。")
        split = row["views"]["literal_split"]
        self.assertEqual(split["conversion_parts"], 2)
        self.assertEqual([p["reading"] for p in split["parts"] if p["kind"] == "convert"], ["がっこうに", "いく"])
        self.assertEqual(row["views"]["morpheme_diagnostic"]["conversion_parts"], 3)
        for view in row["views"].values():
            self.assertEqual("".join(p.get("text", p.get("target", "")) for p in view["parts"]), "「学校に、行く。")

    def test_alternative_or_unsupported_token_blocks_all_views(self):
        for bad in (token("漢字", "かんじ", True), token("A", "A"), token("漢字", "カンジ")):
            row = build_views([token("学校", "がっこう"), bad])
            self.assertEqual(row["status"], "unsupported_annotation")
            self.assertTrue(all(v["parts"] == [] for v in row["views"].values()))

    def test_empty_literal_only_and_bounds_are_explicit(self):
        self.assertEqual(build_views([])["status"], "outside_input_bounds")
        self.assertEqual(build_views([token("。", "。")])["status"], "no_phonetic_input")
        self.assertEqual(build_views([token("字", "あ"*129)])["status"], "outside_input_bounds")
        row = build_views([token("字", "じ")]*33)
        self.assertEqual(row["views"]["whole"]["status"], "ready")
        self.assertEqual(row["views"]["morpheme_diagnostic"]["status"], "outside_part_bounds")

    def test_request_reuse_does_not_merge_different_target_labels(self):
        rows = [build_views([token(s, "はし")]) for s in ("橋", "箸")]
        requests = collect_requests(rows)
        self.assertEqual(requests, [dict(stable_id=request_id("はし"), reading="はし")])
        snapshots = {requests[0]["stable_id"]: [dict(surface="橋"), dict(surface="箸")]}
        self.assertTrue(score_view(rows[0]["views"]["whole"], snapshots)["all_parts_present"]["1"])
        self.assertFalse(score_view(rows[1]["views"]["whole"], snapshots)["all_parts_present"]["1"])

    def test_partial_failure_is_unmeasured_and_empty_result_is_measured_miss(self):
        view = build_views([token("橋", "はし"), token("、", "、"), token("道", "みち")])["views"]["literal_split"]
        snapshots = {request_id("はし"): [dict(surface="橋")]}
        self.assertEqual(score_view(view, snapshots), dict(status="unmeasured"))
        snapshots[request_id("みち")] = []
        score = score_view(view, snapshots)
        self.assertEqual(score["status"], "measured")
        self.assertEqual(score["ranks"], [1, None])
        self.assertFalse(score["all_parts_present"]["32"])

    def test_component_oracle_is_not_joint_rank(self):
        view = build_views([token("橋", "はし"), token("、", "、"), token("道", "みち")])["views"]["literal_split"]
        snapshots = {request_id(r): [dict(surface="別")]*5 + [dict(surface=s)] for r, s in (("はし", "橋"), ("みち", "道"))}
        score = score_view(view, snapshots)
        self.assertTrue(score["all_parts_present"]["6"])
        self.assertFalse(score["all_parts_present"]["1"])
        self.assertEqual(score["ranks"], [6, 6])

    def test_denominators_keep_unresolved_and_distinguish_component_support(self):
        rows = [build_views([token("橋", "はし"), token("道", "みち")]), build_views([token("字", "A")])]
        for i, row in enumerate(rows):
            row.update(stable_id=str(i), policy="basic_phrase", original_status="ready_for_forward_check" if i == 0 else "special_reading_annotation")
        snapshots = {request_id("はしみち"): [], request_id("はし"): [dict(surface="橋")], request_id("みち"): [dict(surface="道")]}
        result = aggregate(rows, snapshots)
        self.assertEqual(result["slots"], 2)
        self.assertEqual(result["by_policy_view"]["basic_phrase/whole"]["unsupported_annotation"], 1)
        self.assertEqual(result["whole_miss_component_support"]["morpheme_diagnostic/all_supported"], 1)
        with self.assertRaises(ValueError): aggregate(rows + rows, snapshots)


if __name__ == "__main__":
    unittest.main()
