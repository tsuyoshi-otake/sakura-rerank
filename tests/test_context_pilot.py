import unittest

from sakura_rerank.data.context_pilot import (
    POLICIES,aggregate,annotation_units,empty_slots,extract_slots,span_candidates,
)
from sakura_rerank.data.kwdlc_probe import ProbeError

DOC="w201106-0000000001"


def token(surface,reading):
    return f"{surface} {reading} {surface} 名詞 6 普通名詞 1 * 0 * 0"


def document(first):
    return (f"# S-ID:{DOC}-1\n* -1D\n"+first+"\nEOS\n"+
            f"# S-ID:{DOC}-2\n* -1D\n+ -1D\n{token('かな','かな')}\nEOS\n"+
            f"# S-ID:{DOC}-3\n* -1D\n+ -1D\n{token('かな','かな')}\nEOS\n").encode("utf8")


class ContextPilotTests(unittest.TestCase):
    def test_four_policies_keep_original_annotation_and_phrase_width(self):
        raw=document("\n".join("+ -1D\n"+token(s,r) for s,r in [("学校","がっこう"),("に","に"),("行く","いく")]))
        rows=extract_slots(DOC,raw)
        self.assertEqual([r["policy"] for r in rows],list(POLICIES))
        self.assertEqual(rows[-1]["target"],"学校に行く")
        self.assertEqual(rows[-1]["reading"],"がっこうにいく")
        self.assertEqual(rows[-1]["morphemes"],3)
        self.assertTrue(all(not r["gold_certified"] and not r["training_eligible"] for r in rows))
        self.assertEqual(rows,extract_slots(DOC,raw))

    def test_context_is_bounded_left_only_and_split_units_reset(self):
        raw=document("+ -1D\n"+token("あ"*90,"あ"*90)+"\n+ -1D\n"+token("漢字","かんじ")+"\n+ -1D\n"+token("あと","あと"))
        row=extract_slots(DOC,raw)[0]
        self.assertEqual(row["left_context"],"あ"*64)
        self.assertNotIn("あと",row["left_context"])
        split=raw.replace((DOC+"-1").encode(),(DOC+"-1-01").encode())
        extra=f"# S-ID:{DOC}-1-02\n+ -1D\n{token('かな','かな')}\nEOS\n".encode()
        split=split.replace(("# S-ID:"+DOC+"-2").encode(),extra+("# S-ID:"+DOC+"-2").encode())
        units=annotation_units(DOC,split)
        self.assertEqual(len(units),4)
        self.assertEqual(len(units[1]),1)

    def test_no_target_slots_are_retained_without_backfill(self):
        rows=extract_slots(DOC,document("+ -1D\n"+token("漢字","かんじ")))
        self.assertEqual([r["status"] for r in rows],["ready_for_forward_check"]*2+["no_target"]*2)
        self.assertEqual(len({r["stable_id"] for r in rows}),4)

    def test_alternative_and_special_reading_do_not_become_ground_truth(self):
        raw=document("+ -1D\n"+token("漢字","かんじ")+"\n@ "+token("漢字","かんぢ"))
        self.assertEqual(extract_slots(DOC,raw)[0]["status"],"alternative_annotation")
        raw=document("+ -1D\n"+token("漢字","カンジ"))
        self.assertEqual(extract_slots(DOC,raw)[0]["status"],"special_reading_annotation")

    def test_long_reading_is_retained_and_model_bound_is_separate(self):
        row=extract_slots(DOC,document("+ -1D\n"+token("漢字","あ"*33)))[0]
        self.assertEqual(row["status"],"ready_for_forward_check")
        self.assertFalse(row["existing_model_bounds"])
        row=extract_slots(DOC,document("+ -1D\n"+token("漢字","あ"*129)))[0]
        self.assertEqual(row["status"],"length_outside_converter_contract")

    def test_missing_phrase_annotations_do_not_invent_boundaries(self):
        rows=extract_slots(DOC,document(token("漢字","かんじ")))
        self.assertEqual(rows[0]["status"],"ready_for_forward_check")
        self.assertTrue(all(r["status"]=="no_target" for r in rows[1:]))
        with self.assertRaises(ProbeError):span_candidates([],"unsupported")

    def test_malformed_source_fails_without_raw_text_in_error(self):
        raw=document("+ -1D\n漢字 invalid")
        with self.assertRaises(ProbeError) as caught:extract_slots(DOC,raw)
        self.assertNotIn("漢字",str(caught.exception))
        rows=empty_slots(DOC,"parse_failure")
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r["status"]=="parse_failure" for r in rows))

    def test_measured_missing_and_unmeasured_have_distinct_denominators(self):
        rows=extract_slots(DOC,document("+ -1D\n"+token("漢字","かんじ")))
        rows[0]["request_id"]="one";rows[1]["request_id"]="two"
        candidates={"one":[dict(surface="漢字",segments=[dict(source_category="system_dictionary")])],"two":[]}
        result=aggregate(rows,candidates)
        self.assertEqual(result["by_policy"]["morpheme"]["measured"],1)
        self.assertEqual(result["by_policy"]["basic_phrase"]["measured_top32_missing"],1)
        self.assertEqual(result["by_policy"]["two_basic_phrases"]["unmeasured"],1)
        with self.assertRaises(ProbeError):aggregate(rows+rows,candidates)

    def test_unresolved_annotation_cannot_silently_be_counted_as_measured(self):
        rows=extract_slots(DOC,document("+ -1D\n"+token("漢字","カンジ")))
        rows[0]["request_id"]="bad"
        with self.assertRaises(ProbeError):aggregate(rows,{"bad":[]})


if __name__=="__main__":unittest.main()
