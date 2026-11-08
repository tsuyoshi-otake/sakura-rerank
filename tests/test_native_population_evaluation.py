"""Schema4 end-to-end population checks; no real Gold/weights/Test artifacts."""
import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from sakura_rerank import current_tiny as current, native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_payload import RunnerError
from sakura_rerank.evaluation_worker import Adapter, gru_factory, validate_gru
from sakura_rerank.test_use_registry import TestUseError
from tests import test_evaluation_runner as fixtures
from tests import test_native_snapshot_evaluation as captured


def strict_native_factory(artifacts,width):
    scorer=fixtures.synthetic_factory(artifacts,width)
    class Scorer:
        def score(self,request):
            assert 2<=len(request['candidates'])<=6
            native.validate_population_input(request)
            return scorer.score(request)
        def close(self):scorer.close()
    return Scorer()


@unittest.skipUnless(os.name=='nt','evaluation containment targets Windows')
class NativePopulationEvaluationTests(unittest.TestCase):
    put=fixtures.RunnerTests.put
    seal_evidence=fixtures.RunnerTests.seal_evidence
    seal_plan=fixtures.RunnerTests.seal_plan
    trusted_fixture=fixtures.RunnerTests.trusted_fixture
    ledger=fixtures.RunnerTests.ledger
    assert_terminal=fixtures.RunnerTests.assert_terminal
    seal_execution=fixtures.RunnerTests.seal_execution
    run_job=fixtures.RunnerTests.run_job
    seal_all=captured.NativeEvaluationTests.seal_all
    seal_native=captured.NativeEvaluationTests.seal_native
    seal_native_test=captured.NativeEvaluationTests.seal_native_test

    def setUp(self):
        captured.NativeEvaluationTests.setUp(self)
        self.experiment['version']=4
        for index,count in ((0,108),(1,768),(4,6)):
            row=self.rows[index]
            row['input']['candidates'].extend(fixtures.candidate(row['input']['reading'],'tail-'+str(i),i)
                                               for i in range(3,count))
            row['product_state'].update(direct_count=count,evidence_tags=[1]*count)
            if index<2:
                row['product_state'].update(baseline_index=count-1,selection_allowed=False)
                row['gold']=row['input']['candidates'][-1]['surface']
        self.rows[2]['input']['reading']='あ'*512
        self.rows[4]['input']['candidates'][0]['surface']='😀'*384
        self.rows[4]['gold']='😀'*384
        duplicate=copy.deepcopy(self.rows[3]['input']['candidates'][0])
        duplicate['rank']=3
        self.rows[3]['input']['candidates'].append(duplicate)
        self.rows[3]['product_state'].update(direct_count=4,evidence_tags=[1]*4)
        for i,row in enumerate(self.rows):
            row['native_capture']=captured.capture_for(row,i)
            row['input']=native.population_input(native.inspect_event(row['native_capture'])['snapshot'])
        self.evidence['oracle6_present']=2997
        self.adapters['synthetic']=Adapter(strict_native_factory,fixtures.synthetic_validate)
        for model in self.experiment['models']:model['adapter_identity']=self.adapters['synthetic'].identity()
        self.seal_population()

    def seal_population(self):
        mapping={r['case_key']:hashlib.sha256(canonical_json_bytes(r['native_capture'])).hexdigest() for r in self.rows}
        provenance=dict(kind='native_evaluation_provenance',version=1,source_head=current.HEAD,
            producer_plan_sha256='b'*64,producer_result_sha256='c'*64,capture_sha256='d'*64,case_capture_sha256=mapping)
        self.put('provenance','provenance',canonical_json_bytes(provenance))
        self.put('policy','policy',canonical_json_bytes(native.evaluation_policy(self.plan['artifacts']['provenance']['sha256'],full_population=True)))
        for key in ('gate','current-gate'):
            gate=json.loads((self.root/(key+'.bin')).read_bytes())
            gate['bindings']['policy']=self.plan['artifacts']['policy']['sha256']
            self.put(key,'gate',canonical_json_bytes(gate))
        self.seal_population_test()

    def seal_population_test(self):
        self.put('test','test',canonical_json_bytes(dict(kind='evaluation_cohort',version=4,cases=self.rows)))
        self.seal_execution()

    def test_spawned_workers_keep_full_population_tail_fallback_and_separate_prefix(self):
        with self.trusted_fixture():result=self.run_job()
        self.assert_terminal('completed')
        self.assertEqual(result['execution_schema_version'],4)
        metrics=result['metrics']['overall']
        self.assertEqual(metrics['record_count'],3000)
        self.assertEqual(metrics['candidate_population']['total'],9874)
        self.assertEqual(metrics['candidate_population']['maximum'],768)
        self.assertEqual(metrics['observed_candidate_oracle']['all']['numerator'],2999)
        self.assertEqual(metrics['observed_candidate_oracle']['32']['numerator'],2997)
        self.assertEqual(metrics['candidate_population']['present_outside_model_prefix'],2)
        self.assertEqual(sum(m['attempted'] for m in result['models']),5992)
        sealed=json.loads(next(self.registry.glob('observations-*.json')).read_bytes())
        self.assertEqual(sealed['full_candidate_counts'][:5],[108,768,3,4,6])
        self.assertEqual(sealed['candidate_counts'][:5],[6,6,3,4,6])
        self.assertEqual(sum(r['candidate_count'] for r in sealed['native_projection_bindings']),9874)
        for i in (0,1):
            observation=sealed['runs']['current-tiny']['observations'][self.rows[i]['case_key']]
            self.assertEqual(observation,dict(status='not_eligible',ranking=None,attempted=False))
        self.assertEqual(result['metrics']['slices']['context-empty']['metrics']['candidate_population'],metrics['candidate_population'])
        self.assertEqual(result['metrics']['converter_reference']['cohort_sha256'],metrics['cohort_sha256'])
        self.assertEqual(result['safety_references'],['converter_top1','native_local_selection'])
        self.assertFalse(result['release_eligible'])
        with self.trusted_fixture(),self.assertRaises(TestUseError):self.run_job()

    def shorten_direct_prefix(self):
        # Row 4 keeps six native candidates but only the first three are direct, so
        # Gold at index 4 lies inside a blind first six yet outside the scored prefix.
        row=self.rows[4]
        row['product_state'].update(direct_count=3)
        row['gold']=row['input']['candidates'][4]['surface']
        row['native_capture']=captured.capture_for(row,4)
        row['input']=native.population_input(native.inspect_event(row['native_capture'])['snapshot'])

    def test_oracle6_evidence_counts_only_the_scored_direct_prefix(self):
        self.shorten_direct_prefix()
        self.evidence['oracle6_present']=2996
        self.seal_population()
        with self.trusted_fixture():self.run_job()
        self.assert_terminal('completed')

    def test_oracle6_evidence_counting_a_non_direct_tail_is_rejected(self):
        self.shorten_direct_prefix()
        self.evidence['oracle6_present']=2997
        self.seal_population()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('started')):
            with self.assertRaisesRegex(RunnerError,'actual oracle differs'):self.run_job()
        self.assert_terminal('failed')

    def test_tail_change_consumes_once_and_cannot_start_model(self):
        self.rows[0]['input']['candidates'].pop()
        self.seal_population_test()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('started')):
            with self.assertRaises(ValueError):self.run_job()
        self.assert_terminal('failed')

    def test_native_session_replay_is_rejected_in_new_schema(self):
        self.rows[9]['native_capture']=copy.deepcopy(self.rows[5]['native_capture'])
        self.rows[9]['native_capture']['fixture']=9
        self.seal_population()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('started')):
            with self.assertRaisesRegex(ValueError,'snapshot replayed'):self.run_job()
        self.assert_terminal('failed')

    def test_old_current_adapter_and_legacy_features_refused_before_consumption(self):
        for factory,validator in ((current.current_factory,current.validate_current),(gru_factory,validate_gru)):
            adapter=Adapter(factory,validator)
            self.adapters['legacy']=adapter
            model=next(m for m in self.experiment['models'] if m['model']=='current_tiny')
            model.update(adapter='legacy',adapter_identity=adapter.identity(),feature_width=6)
            self.seal_execution()
            with self.trusted_fixture(),self.assertRaises(RunnerError):self.run_job()
            self.assertEqual(self.ledger(),[])

    def test_worker_failure_keeps_all_populations_and_unattempted_rows(self):
        def failed(requests,*args,**kwargs):
            self.assertEqual(len(requests),1498)
            self.assertTrue(all(len(r['candidates'])<=6 for r in requests))
            return dict(states=['error']+['unavailable']*1497,scores=[None]*1498,complete=False,
                        terminal='worker_failure',process=None,attempted=1)
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',failed):result=self.run_job()
        self.assert_terminal('completed')
        self.assertEqual(result['status'],'incomplete')
        metrics=result['metrics']['overall']
        counts=metrics['models']['current-tiny']['terminal_counts']
        self.assertEqual((counts['not_eligible'],counts['error'],counts['unavailable']),(1502,1,1497))
        self.assertEqual(metrics['candidate_population']['total'],9874)
        self.assertEqual(metrics['models']['current-tiny']['effective_changes'],0)


if __name__=='__main__':unittest.main()
