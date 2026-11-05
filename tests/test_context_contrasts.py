import unittest

from sakura_rerank.data.context_contrasts import extract_pool, select_contrasts
from test_context_pilot import DOC, document, token


def row(index, target, representative, document_id=None, context=None):
    return dict(stable_id="r"+str(index), reading="はし", pos="名詞", target=target,
                representative=representative, document_id=document_id or "d"+str(index),
                left_context=context or "文脈を区別する"+str(index))


class ContextContrastTests(unittest.TestCase):
    def test_sidecar_keeps_reading_and_bounded_preceding_context(self):
        raw=document("+ -1D\n"+token("あ"*70,"あ"*70)+"\n+ -1D\n"+
                     token("橋","はし")+' "代表表記:橋/はし"\n+ -1D\n'+token("あと","あと"))
        rows, counts=extract_pool(DOC,raw)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["left_context"],"あ"*64)
        self.assertEqual(rows[0]["target"],"橋")
        self.assertEqual(rows[0]["representative"],"橋/はし")
        self.assertFalse(rows[0]["gold_certified"] or rows[0]["training_eligible"])
        self.assertEqual(sum(counts.values()),5)

    def test_missing_or_multiple_representatives_remain_unresolved(self):
        for suffix in ("", ' "代表表記:橋/はし?端/はし"', ' "代表表記:橋/はし 代表表記:端/はし"'):
            raw=document("+ -1D\n"+token("あ"*8,"あ"*8)+"\n+ -1D\n"+token("橋","はし")+suffix)
            rows,counts=extract_pool(DOC,raw)
            self.assertEqual(rows,[])
            self.assertEqual(counts["unresolved_representative_annotation"],1)

    def test_lexical_quartet_has_two_targets_four_documents_and_distinct_contexts(self):
        rows=[row(i,"橋" if i<2 else "箸","橋/はし" if i<2 else "箸/はし") for i in range(4)]
        selected,counts=select_contrasts(rows)
        self.assertEqual(len(selected),4)
        self.assertEqual(counts["selected_groups"],1)
        self.assertEqual(len({r["document_id"] for r in selected}),4)
        self.assertEqual(select_contrasts(rows),select_contrasts(list(reversed(rows))))

    def test_same_representative_spelling_variants_do_not_become_lexical_contrasts(self):
        rows=[row(i,"橋" if i<2 else "はし","橋/はし") for i in range(4)]
        self.assertEqual(select_contrasts(rows)[0],[])

    def test_shared_document_or_context_does_not_satisfy_independence_proxy(self):
        for field in ("document_id","left_context"):
            rows=[row(i,"橋" if i<2 else "箸","橋/はし" if i<2 else "箸/はし") for i in range(4)]
            for r in rows:r[field]="same"
            self.assertEqual(select_contrasts(rows)[0],[])

    def test_duplicate_population_and_unsafe_bounds_are_rejected(self):
        r=row(1,"橋","橋/はし")
        with self.assertRaises(ValueError):select_contrasts([r,r])
        with self.assertRaises(ValueError):select_contrasts([r],maximum_groups=0)


if __name__=="__main__":unittest.main()
