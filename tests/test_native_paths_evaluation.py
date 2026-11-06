"""Schema5 path-to-evaluator contracts on synthetic data; never real Gold."""
import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from sakura_rerank import native_paths as paths,native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_payload import RunnerError
from sakura_rerank.evaluation_worker import Adapter,validate_gru
from sakura_rerank.native_path_inputs import encode_request,native_gru_factory
from tests import test_native_population_evaluation as population
from tests.test_native_paths import add_paths


def path_factory(artifacts,width):
    scorer=population.fixtures.synthetic_factory(artifacts,width)
    class Scorer:
        def score(self,request):
            self.feed=encode_request(request,7)
            assert set(request)=={'reading','left_context','context_policy','candidates'}
            return scorer.score(request)
        def close(self):scorer.close()
    return Scorer()


@unittest.skipUnless(os.name=='nt','bounded evaluator targets Windows')
class NativePathEvaluationTests(unittest.TestCase):
    put=population.NativePopulationEvaluationTests.put
    seal_evidence=population.NativePopulationEvaluationTests.seal_evidence
    seal_plan=population.NativePopulationEvaluationTests.seal_plan
    trusted_fixture=population.NativePopulationEvaluationTests.trusted_fixture
    ledger=population.NativePopulationEvaluationTests.ledger
    assert_terminal=population.NativePopulationEvaluationTests.assert_terminal
    seal_execution=population.NativePopulationEvaluationTests.seal_execution
    run_job=population.NativePopulationEvaluationTests.run_job
    seal_all=population.NativePopulationEvaluationTests.seal_all
    seal_native=population.NativePopulationEvaluationTests.seal_native
    seal_native_test=population.NativePopulationEvaluationTests.seal_native_test
    seal_population=population.NativePopulationEvaluationTests.seal_population
    seal_population_test=population.NativePopulationEvaluationTests.seal_population_test

    def setUp(self):
        population.NativePopulationEvaluationTests.setUp(self)
        self.experiment['version']=5
        for row in self.rows:
            row['native_capture']=add_paths(row['native_capture'])
            row['input']=copy.deepcopy(native.population_input(paths.inspect_event(row['native_capture'])['snapshot']))
        self.adapters['synthetic']=Adapter(path_factory,population.fixtures.synthetic_validate)
        for model in self.experiment['models']:model['adapter_identity']=self.adapters['synthetic'].identity()
        self.seal_paths()

    def seal_paths(self):
        mapping={r['case_key']:hashlib.sha256(canonical_json_bytes(r['native_capture'])).hexdigest() for r in self.rows}
        provenance=dict(kind='native_evaluation_provenance',version=1,source_head=native.HEAD,
            producer_plan_sha256='b'*64,producer_result_sha256='c'*64,capture_sha256='d'*64,case_capture_sha256=mapping)
        self.put('provenance','provenance',canonical_json_bytes(provenance))
        self.put('policy','policy',canonical_json_bytes(paths.evaluation_policy(self.plan['artifacts']['provenance']['sha256'])))
        for key in ('gate','current-gate'):
            gate=json.loads((self.root/(key+'.bin')).read_bytes());gate['bindings']['policy']=self.plan['artifacts']['policy']['sha256']
            self.put(key,'gate',canonical_json_bytes(gate))
        self.seal_path_test()

    def seal_path_test(self):
        self.put('test','test',canonical_json_bytes(dict(kind='evaluation_cohort',version=5,cases=self.rows)))
        self.seal_execution()

    def test_spawned_workers_encode_paths_and_preserve_full_population(self):
        with self.trusted_fixture():result=self.run_job()
        self.assert_terminal('completed')
        self.assertEqual(result['execution_schema_version'],5)
        self.assertEqual(result['metrics']['overall']['candidate_population']['total'],9874)
        self.assertEqual(sum(m['attempted'] for m in result['models']),5992)
        sealed=json.loads(next(self.registry.glob('observations-*.json')).read_bytes())
        self.assertEqual(sealed['path_contract'],paths.CONTRACT)
        self.assertEqual(len(sealed['native_projection_bindings']),3000)
        self.assertTrue(all(r['legacy_feature_provenance_verified'] and not r['final_evaluation_admitted']
                            for r in sealed['native_projection_bindings']))
        self.assertEqual(result['safety_references'],['converter_top1','native_local_selection'])
        self.assertFalse(result['release_eligible'])

    def test_path_tail_tamper_is_rejected_before_any_model(self):
        self.rows[1]['input']['candidates'][-1]['path']['segments'][0]['source_category']='user_dictionary'
        self.seal_path_test()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('started')):
            with self.assertRaises(ValueError):self.run_job()
        self.assert_terminal('failed')

    def test_missing_path_is_not_recovered_from_a_native_evidence_tag(self):
        del self.rows[0]['native_capture']['captures'][0]['candidates'][0]['path']
        self.seal_paths()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('started')):
            with self.assertRaises(ValueError):self.run_job()
        self.assert_terminal('failed')

    def test_native_session_replay_still_fails(self):
        self.rows[9]['native_capture']=copy.deepcopy(self.rows[5]['native_capture'])
        self.rows[9]['native_capture']['fixture']=9
        self.seal_paths()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('started')):
            with self.assertRaisesRegex(ValueError,'snapshot replayed'):self.run_job()
        self.assert_terminal('failed')

    def test_research_path_factory_cannot_replace_current_product(self):
        adapter=Adapter(native_gru_factory,validate_gru);self.adapters['path']=adapter
        current=next(m for m in self.experiment['models'] if m['model']=='current_tiny')
        current.update(adapter='path',adapter_identity=adapter.identity(),feature_width=6)
        self.seal_execution()
        with self.trusted_fixture(),self.assertRaises(RunnerError):self.run_job()
        self.assertEqual(self.ledger(),[])


if __name__=='__main__':unittest.main()
