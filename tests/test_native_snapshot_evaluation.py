"""Hash-bound native schema integration on synthetic evaluation data only."""
import copy
import hashlib
import json
import os
import struct
import unittest
from unittest.mock import patch

from sakura_rerank import current_tiny as current, native_snapshot as native
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_payload import RunnerError
from sakura_rerank.evaluation_worker import Adapter, gru_factory, validate_gru
from tests import test_current_tiny_evaluation as product_fixture
from tests import test_evaluation_runner as fixtures


def capture_for(row,index):
    facts=row['product_state']; source=row['input']
    candidates=[dict(surface_hex=c['surface'].encode().hex(),cost=c['local_cost'],evidence=tag,
        fingerprint=native.candidate_fingerprint(c['surface'],c['local_cost'],tag))
        for c,tag in zip(source['candidates'],facts['evidence_tags'],strict=True)]
    prefix=candidates[:min(6,facts['direct_count'])]
    fingerprints=[c['fingerprint'] for c in prefix]
    cset=native.candidate_set_fingerprint(fingerprints)
    key=[1,index+1,7,native.fingerprint(source['reading'].encode()),len(source['reading'].encode())]
    scores=[10. if i==2 else -float(i) for i in range(len(prefix))]
    work=dict(scheduled=False,built=False)
    if facts['schedule_eligible']:
        work=dict(scheduled=True,built=True,owner=key[0],session=key[1],generation=key[2],reading_hash=key[3],
            reading_bytes=key[4],candidate_set=cset,
            model_candidates=[{k:v for k,v in c.items() if k!='evidence'} for c in prefix],
            response_key=key,response_candidate_set=cset,response_count=len(prefix),response_fingerprints=fingerprints,
            response_score_bits=[struct.unpack('<I',struct.pack('<f',s))[0] for s in scores],
            response_finite=True,response_ready=True,response_present=True)
    choice=(current.protected_choice(scores,facts['evidence_tags'][:len(prefix)])
            if facts['selection_allowed'] and facts['schedule_eligible'] else None)
    captured=dict(owner=key[0],session=key[1],generation=key[2],reading_hex=source['reading'].encode().hex(),
        direct_count=facts['direct_count'],baseline_index=facts['baseline_index'],
        selected_index=facts['baseline_index'] if choice is None else choice,
        selection_calls=int(facts['selection_allowed']),candidate_set=cset,candidates=candidates)
    return dict(fixture=index%1024,scenario='synthetic',baseline_run=False,work=work,captures=[captured],
        terminal='Applied' if choice is not None else 'Ready' if work['built'] else 'None')


@unittest.skipUnless(os.name=='nt','evaluation containment targets Windows')
class NativeEvaluationTests(unittest.TestCase):
    put=fixtures.RunnerTests.put
    seal_evidence=fixtures.RunnerTests.seal_evidence
    seal_plan=fixtures.RunnerTests.seal_plan
    trusted_fixture=fixtures.RunnerTests.trusted_fixture
    ledger=fixtures.RunnerTests.ledger
    assert_terminal=fixtures.RunnerTests.assert_terminal
    seal_execution=fixtures.RunnerTests.seal_execution
    run_job=fixtures.RunnerTests.run_job
    seal_all=product_fixture.ProductEvaluationTests.seal_all

    def setUp(self):
        product_fixture.ProductEvaluationTests.setUp(self)
        self.experiment['version']=3
        for i,row in enumerate(self.rows): row['native_capture']=capture_for(row,i)
        self.seal_native()

    def seal_native(self):
        mapping={r['case_key']:hashlib.sha256(canonical_json_bytes(r['native_capture'])).hexdigest() for r in self.rows}
        provenance=dict(kind='native_evaluation_provenance',version=1,source_head=current.HEAD,
            producer_plan_sha256='b'*64,producer_result_sha256='c'*64,capture_sha256='d'*64,case_capture_sha256=mapping)
        self.put('provenance','provenance',canonical_json_bytes(provenance))
        self.put('policy','policy',canonical_json_bytes(native.evaluation_policy(self.plan['artifacts']['provenance']['sha256'])))
        for key in ('gate','current-gate'):
            gate=json.loads((self.root/(key+'.bin')).read_bytes())
            gate['bindings']['policy']=self.plan['artifacts']['policy']['sha256']
            self.put(key,'gate',canonical_json_bytes(gate))
        self.seal_native_test()

    def seal_native_test(self):
        self.put('test','test',canonical_json_bytes(dict(kind='evaluation_cohort',version=3,cases=self.rows)))
        self.seal_execution()

    def test_native_bindings_are_checked_and_sealed_before_model_scoring(self):
        with self.trusted_fixture(): result=self.run_job()
        self.assert_terminal('completed')
        self.assertEqual(result['execution_schema_version'],3)
        self.assertEqual(result['metrics']['overall']['record_count'],3000)
        self.assertEqual(result['safety_references'],['converter_top1','native_local_selection'])
        self.assertEqual(sum(m['attempted'] for m in result['models']),6000)
        sealed=json.loads(next(self.registry.glob('observations-*.json')).read_bytes())
        self.assertEqual(len(sealed['native_projection_bindings']),3000)
        self.assertTrue(all(not r['legacy_feature_provenance_verified'] and not r['final_evaluation_admitted']
                            for r in sealed['native_projection_bindings']))
        self.assertFalse(result['release_eligible'])

    def test_changed_capture_consumes_once_and_never_starts_model(self):
        self.rows[0]['native_capture']['captures'][0]['baseline_index']=1
        self.seal_native_test()  # Preserve the prior producer commitment.
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('model started')):
            with self.assertRaises(ValueError):self.run_job()
        self.assert_terminal('failed')

    def test_native_session_replay_cannot_hide_behind_a_new_fixture_id(self):
        first=copy.deepcopy(self.rows[0]['native_capture'])
        first['fixture']=4
        self.rows[4]['native_capture']=first
        self.seal_native()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('model started')):
            with self.assertRaisesRegex(ValueError,'snapshot replayed'):self.run_job()
        self.assert_terminal('failed')

    def test_missing_capture_cannot_be_replaced_by_declared_policy_facts(self):
        del self.rows[0]['native_capture']
        self.seal_native_test()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('model started')):
            with self.assertRaises(ValueError):self.run_job()
        self.assert_terminal('failed')

    def test_legacy_gru_feature_provenance_is_not_inferred_from_native_evidence(self):
        adapter=Adapter(gru_factory,validate_gru)
        self.adapters['legacy']=adapter
        model=next(m for m in self.experiment['models'] if m['model']=='r2')
        model.update(adapter='legacy',adapter_identity=adapter.identity(),feature_width=7)
        self.seal_execution()
        with self.trusted_fixture(),self.assertRaises(RunnerError):self.run_job()
        self.assertEqual(self.ledger(),[])

    def test_large_native_population_fails_whole_legacy_evaluation_without_clipping(self):
        row=self.rows[0]
        row['input']['candidates'].extend(fixtures.candidate(row['input']['reading'],'synthetic-tail-'+str(i),i)
                                           for i in range(3,108))
        row['product_state']['direct_count']=108
        row['product_state']['evidence_tags']=[1]*108
        row['native_capture']=capture_for(row,0)
        self.assertEqual(len(native.inspect_event(row['native_capture'])['snapshot']['candidates']),108)
        self.seal_native()
        with self.trusted_fixture(),patch('sakura_rerank.evaluation_runner.execute_model',side_effect=AssertionError('model started')):
            with self.assertRaises(ValueError):self.run_job()
        self.assert_terminal('failed')
        self.assertEqual(len(self.rows),3000)
        self.assertEqual(len(self.rows[0]['input']['candidates']),108)


if __name__=='__main__':unittest.main()
