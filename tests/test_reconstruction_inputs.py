"""Synthetic source/position contracts, without real corpus text."""
from collections import Counter
from copy import deepcopy
import unittest

from sakura_rerank.data.growth_corpus import GrowthExtractor
from sakura_rerank.data.reconstruction_inputs import paragraph_coverage,recover_dictionary_rows


class ReconstructionInputsTest(unittest.TestCase):
    def fixture(self):
        paragraphs=['これは合成されたテスト文章です。ここで学校について考える。後ろの文章は入力しない。']
        records=[dict(surface='学校',readings=['がっこう'])]
        rows=GrowthExtractor(records).document(paragraphs,'jawiki','123','456','train',8,Counter())
        self.assertEqual(len(rows),1)
        return paragraphs,rows,dict(corpus='jawiki',source_id='123',revision='456',readings={'学校':'がっこう'})

    def test_exact_source_preimage_and_complete_paragraph_coverage(self):
        paragraphs,rows,arguments=self.fixture();original=deepcopy(rows)
        receipts,indices=recover_dictionary_rows(paragraphs,rows,**arguments)
        self.assertEqual(rows,original);self.assertEqual(indices,[0])
        record=receipts[0]
        self.assertEqual(paragraphs[0][record['target_start']:record['target_end']],rows[0]['target'])
        self.assertFalse(record['training_eligible']);self.assertFalse(record['independent_gold_eligible'])
        coverage=paragraph_coverage(paragraphs,indices,corpus='jawiki',source_id='123',revision='456')
        self.assertEqual(len(coverage),3)
        self.assertTrue(all(set(row)=={'stable_id','population','source'} for row in coverage))
        self.assertNotIn('input_hash',coverage[0])
        self.assertNotIn('left_context',record)

    def test_source_context_revision_and_identity_changes_fail(self):
        paragraphs,rows,arguments=self.fixture()
        for field,value in [('left_context','これは違う前文脈の内容です'),('source_revision','457'),('stable_id','growth-'+'0'*64)]:
            changed=deepcopy(rows);changed[0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                recover_dictionary_rows(paragraphs,changed,**arguments)
        changed=deepcopy(rows);changed[0]['source']['sentence_shingle_hashes']=[]
        with self.assertRaises(ValueError): recover_dictionary_rows(paragraphs,changed,**arguments)

    def test_dictionary_provenance_and_label_promotions_fail(self):
        paragraphs,rows,arguments=self.fixture()
        for field,value in [('population','evaluation'),('label_kind','certified'),('independent_gold_eligible',True),('training_eligible',True),('reading','べつよみ')]:
            changed=deepcopy(rows);changed[0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                recover_dictionary_rows(paragraphs,changed,**arguments)
        with self.assertRaises(ValueError): recover_dictionary_rows(paragraphs,rows,**dict(arguments,readings={}))

    def test_duplicate_paragraph_positions_remain_disambiguated(self):
        paragraphs,rows,arguments=self.fixture()
        doubled=paragraphs*2
        records=[dict(surface='学校',readings=['がっこう'])]
        selected=GrowthExtractor(records).document(doubled,'jawiki','123','456','train',8,Counter())
        receipts,indices=recover_dictionary_rows(doubled,selected[::-1],**arguments)
        self.assertEqual(indices,[0,1]);self.assertEqual({r['paragraph_index'] for r in receipts},{0,1})
        with self.assertRaises(ValueError): recover_dictionary_rows(paragraphs,rows*2,**arguments)

    def test_changed_source_text_and_missing_source_span_fail(self):
        paragraphs,rows,arguments=self.fixture()
        with self.assertRaises(ValueError): recover_dictionary_rows([paragraphs[0]+'追加。'],rows,**arguments)
        with self.assertRaises(ValueError): recover_dictionary_rows([],rows,**arguments)

    def test_author_and_coverage_index_contracts(self):
        paragraphs,_,_=self.fixture()
        with self.assertRaises(ValueError): paragraph_coverage(paragraphs,[0],corpus='aozora',source_id='123',revision='456')
        valid=paragraph_coverage(paragraphs,[0],corpus='aozora',source_id='123',revision='456',author_id='789')
        self.assertEqual(valid[0]['source']['template_cluster_id'],'aozora-author-789')
        for author in ('789','invalid',0):
            with self.subTest(author=author),self.assertRaises(ValueError):
                paragraph_coverage(paragraphs,[0],corpus='jawiki',source_id='123',revision='456',author_id=author)
        for indices in ([0,0],[-1],[1],[False]):
            with self.subTest(indices=indices),self.assertRaises(ValueError):
                paragraph_coverage(paragraphs,indices,corpus='jawiki',source_id='123',revision='456')


if __name__=='__main__': unittest.main()
