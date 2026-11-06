"""Full native extent and surface metrics; all examples are synthetic."""
import copy
import unittest

from sakura_rerank import current_tiny as current, native_snapshot as native
from sakura_rerank.evaluation_metrics import EvaluationCase, EvaluationError, EvaluationRun, Observation, evaluate_runs
from tests.test_evaluation_runner import key
from tests.test_native_snapshot import event


class NativePopulationTests(unittest.TestCase):
    def test_full_population_binds_tail_without_legacy_descriptors(self):
        for count in (32,33,108,768):
            snapshot=native.inspect_event(event(count=count,baseline=count-1,allowed=False))['snapshot']
            request=native.population_input(snapshot)
            receipt=native.bind_population_input(snapshot,request,snapshot['product_state'])
            self.assertEqual(receipt['candidate_count'],count)
            self.assertFalse(receipt['legacy_feature_provenance_verified'])
            self.assertEqual(request['candidates'][-1]['rank'],count-1)
            self.assertNotIn('segments',request['candidates'][-1])

    def test_population_rejects_overflow_tail_tamper_and_invented_features(self):
        snapshot=native.inspect_event(event(count=768))['snapshot']
        request=native.population_input(snapshot)
        for change in ('overflow','drop','reorder','cost','evidence','fingerprint','segments','reading','context'):
            invalid=copy.deepcopy(request)
            if change=='overflow':invalid['candidates'].append(dict(invalid['candidates'][-1],rank=768))
            if change=='drop':invalid['candidates'].pop()
            if change=='reorder':invalid['candidates'][-1],invalid['candidates'][-2]=invalid['candidates'][-2],invalid['candidates'][-1]
            if change=='cost':invalid['candidates'][-1]['local_cost']+=1
            if change=='evidence':invalid['candidates'][-1]['evidence_tag']=2
            if change=='fingerprint':invalid['candidates'][-1]['native_fingerprint']^=1
            if change=='segments':invalid['candidates'][-1]['segments']=[]
            if change=='reading':invalid['reading']='other'
            if change=='context':invalid['left_context']='other'
            with self.subTest(change=change),self.assertRaises(native.NativeSnapshotError):
                native.bind_population_input(snapshot,invalid,snapshot['product_state'])

    def test_duplicate_surface_is_not_deduplicated_or_reordered(self):
        value=event(count=108,allowed=False)
        value['captures'][0]['candidates'][-1]=dict(value['captures'][0]['candidates'][0])
        snapshot=native.inspect_event(value)['snapshot']
        request=native.population_input(snapshot)
        self.assertEqual(native.bind_population_input(snapshot,request,snapshot['product_state'])['candidate_count'],108)
        self.assertEqual(request['candidates'][0]['surface'],request['candidates'][-1]['surface'])

    def test_text_capacity_is_utf8_bytes_not_characters(self):
        for text in ('a'*1536,'あ'*512,'😀'*384):
            self.assertEqual(native.validate_native_text(text),text)
        for text in ('a'*1537,'あ'*513,'😀'*385,'\ud800',''):
            with self.assertRaises(native.NativeSnapshotError):native.validate_native_text(text)

    def test_native_projection_preserves_full_length_feature_but_only32_tokens(self):
        for text in ('a'*1536,'あ'*512,'😀'*384):
            rows=[dict(surface=text,local_cost=1),dict(surface='B',local_cost=2)]
            feed=current.protocol_feed(rows,full_population=True)
            self.assertEqual(feed['candidate_lengths'][0,0],32)
            self.assertEqual(feed['features'][0,0,3],len(text)/32)
            with self.assertRaises(current.ProductContractError):current.protocol_feed(rows)
        for text in ('あ'*513,'a'*1537,'\ud800'):
            with self.assertRaises(current.ProductContractError):
                current.protocol_feed([dict(surface=text,local_cost=1),dict(surface='B',local_cost=2)],full_population=True)

    def test_new_policy_never_silently_reuses_legacy_binding(self):
        old=native.evaluation_policy('a'*64)
        new=native.evaluation_policy('a'*64,full_population=True)
        self.assertNotEqual(old,new)
        self.assertEqual((old['version'],new['version']),(2,3))
        self.assertEqual(new['safety_references'],old['safety_references'])


class NativePopulationMetricsTests(unittest.TestCase):
    def evaluate(self,rows,observations,**options):
        return evaluate_runs(rows,{'model':EvaluationRun(observations,True)},comparisons=[('model','baseline')],
                             bootstrap_replicates=100,**options)

    def test_oracle_tail_and_fallback_retained_with_both_safety_references(self):
        surfaces=tuple(str(i) for i in range(768))
        rows=[EvaluationCase(key(1),key('c'),surfaces,'767',767,6),
              EvaluationCase(key(2),key('c'),surfaces,'107',0,6),
              EvaluationCase(key(3),key('c'),surfaces,'absent',0,6)]
        outcomes={rows[0].case_key:Observation('not_eligible',attempted=False),
                  rows[1].case_key:Observation('timeout'),rows[2].case_key:Observation('unavailable',attempted=False)}
        local=self.evaluate(rows,outcomes,candidate_contract='native_full_population_v1')
        raw=self.evaluate(rows,outcomes,candidate_contract='native_full_population_v1',reference_baseline='converter_top1')
        self.assertEqual(local['observed_candidate_oracle']['all']['numerator'],2)
        self.assertEqual(local['observed_candidate_oracle']['32']['numerator'],0)
        self.assertEqual(local['candidate_population']['present_outside_model_prefix'],2)
        self.assertEqual(local['candidate_population']['full_oracle_misses'],1)
        self.assertEqual(local['candidate_population']['total'],2304)
        self.assertEqual(local['models']['model']['accuracy']['numerator'],1)
        self.assertEqual(local['models']['model']['effective_changes'],0)
        self.assertEqual(raw['models']['model']['correction_success'],1)
        self.assertEqual(local['models']['model']['prediction_sha256'],raw['models']['model']['prediction_sha256'])
        self.assertEqual(local['harm_limit'],.0025)
        with self.assertRaises(EvaluationError):self.evaluate(rows,outcomes)

    def test_all_oracle_is_surface_based_and_tail_enters_cohort_hash(self):
        row=EvaluationCase(key(1),key('c'),('gold','other','gold'),'gold',0,2)
        outcomes={row.case_key:Observation('applied',(1,0))}
        report=self.evaluate([row],outcomes,candidate_contract='native_full_population_v1')
        self.assertEqual(report['observed_candidate_oracle']['all']['numerator'],1)
        self.assertEqual(report['models']['model']['baseline_correct_destroyed'],1)
        other=EvaluationCase(row.case_key,row.component_key,('gold','other','changed'),'gold',0,2)
        changed=self.evaluate([other],outcomes,candidate_contract='native_full_population_v1')
        self.assertNotEqual(report['cohort_sha256'],changed['cohort_sha256'])

    def test_unknown_contract_and_invalid_native_text_or_count_fail(self):
        for candidates,gold in ((('a',)*769,'a'),(('😀'*385,),'a'),(('a',),'\ud800')):
            row=EvaluationCase(key(1),key('c'),candidates,gold)
            with self.assertRaises(EvaluationError):
                self.evaluate([row],{},candidate_contract='native_full_population_v1')
        with self.assertRaises(EvaluationError):self.evaluate([],{},candidate_contract='unknown')


if __name__=='__main__':unittest.main()
