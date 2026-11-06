"""Source/numeric identity joins and denied permission escalation."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.source_research_recipe import build_recipe, load_recipe


def fixture():
    cohort, decisions, prepared, receipts = [], [], [], []
    states = ['ready_dictionary_only_weak', 'ready_original_annotation', 'pending_reading_conflict',
              'ready_original_annotation', 'pending_annotation_scope', 'ready_dictionary_only_weak']
    previous = '0' * 64
    for i, state in enumerate(states):
        corpus = 'jawiki' if i == 0 else 'aozora'
        group = 'annotation' if i == 3 else 'dictionary'
        source_kind = 'original_ruby' if i == 3 else 'frozen_unique_dictionary'
        item = dict(stable_id='synthetic-'+str(i), component_id='synthetic-component-'+str(i), corpus=corpus,
                    left_context='synthetic-prefix', reading='かな', target='仮名', candidate_request_id='synthetic-request')
        origin = dict(group=group, original_row_sha256=canonical_json_hash(['original', i]), reading_provenance=source_kind,
                      training_eligible=False, independent_gold_eligible=False, ime_quality='unresolved')
        row = dict(encoder_input=item, origin=origin,
                   membership=['dictionary', 'annotation'] if i == 0 else [group])
        decision = dict(input_sha256=canonical_json_hash(item), source=dict(original_row_sha256=origin['original_row_sha256'], origin_kind=source_kind),
                        terminal=state, candidate_preparation_allowed=state.startswith('ready_'), training_eligible=False, independent_gold_eligible=False)
        sealed = dict(origin, stable_id=item['stable_id'], component_id=item['component_id'], cohort_record_sha256=canonical_json_hash(row))
        receipt = dict(index=i, previous_sha256=previous, origin=sealed,
                       input_tensor_sha256=canonical_json_hash(['input', i]), label_tensor_sha256=canonical_json_hash(['label', i]))
        previous = canonical_json_hash(receipt)
        receipt['record_sha256'] = previous
        cohort.append(row); decisions.append(decision); receipts.append(receipt)
        if state.startswith('ready_'):
            prepared.append(dict(input=item, decision_sha256=canonical_json_hash(decision)))
    pool = dict(manifest=dict(input_rows=6, preparable_rows=4, training_eligible=False, independent_gold_eligible=False),
                decisions=list(reversed(decisions)), rows=list(reversed(prepared)))
    cache = dict(rows=6, training_eligible=False, independent_gold_eligible=False, row_chain_head=previous,
                 source_order_sha256=canonical_json_hash([r['encoder_input']['stable_id'] for r in cohort]))
    return cohort, pool, receipts, cache


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.cohort, self.pool, self.receipts, self.cache = fixture()

    def build(self, weak=True):
        return build_recipe(self.cohort, self.pool, self.receipts, source_manifest_sha256='1'*64,
                            numeric_manifest_sha256='2'*64, numeric_manifest=self.cache, allow_dictionary_only=weak)

    def reject(self):
        with self.assertRaises((ValueError, KeyError)):
            self.build()

    def test_hash_join_preserves_numeric_order_despite_reversed_source_pool(self):
        recipe = self.build()
        self.assertEqual(recipe['selected_indices'], dict(dictionary=[0, 1, 5], annotation=[0, 3]))
        self.assertEqual(recipe['original_indices'], dict(dictionary=[0, 1, 2, 4, 5], annotation=[0, 3]))
        self.assertEqual(recipe['summary']['population_rows'], 6)
        self.assertFalse(recipe['training_eligible'])
        self.assertEqual([r['component_id'] for r in recipe['rows']], ['synthetic-component-'+str(i) for i in range(6)])

    def test_strict_policy_drops_weak_rows_without_hiding_denominator(self):
        recipe = self.build(False)
        self.assertEqual(recipe['selected_indices'], dict(dictionary=[1], annotation=[3]))
        self.assertEqual(recipe['summary']['terminal_counts'], dict(weak_source_disabled=2, eligible_for_fit_binding=2, pending_source=2))

    def test_dictionary_origin_with_actual_annotation_keeps_annotation_tier(self):
        self.assertEqual(self.build()['rows'][1]['tier'], 'original_annotation')

    def test_original_payloads_remain_unchanged(self):
        before = deepcopy((self.cohort, self.pool, self.receipts, self.cache))
        self.build()
        self.assertEqual(before, (self.cohort, self.pool, self.receipts, self.cache))

    def test_missing_cohort_row_rejected(self):
        self.cohort.pop(); self.reject()

    def test_changed_reading_cannot_inherit_source_decision(self):
        self.cohort[0]['encoder_input']['reading'] = 'べつ'; self.reject()

    def test_changed_original_label_cannot_inherit_numeric_receipt(self):
        self.cohort[0]['origin']['original_row_sha256'] = '3'*64; self.reject()

    def test_changed_component_cannot_erase_lineage(self):
        self.cohort[0]['encoder_input']['component_id'] = 'another'; self.reject()

    def test_changed_numeric_label_hash_rejected(self):
        self.receipts[0]['label_tensor_sha256'] = '3'*64; self.reject()

    def test_reordered_numeric_rows_rejected(self):
        self.receipts.reverse(); self.reject()

    def test_pending_source_in_prepared_payload_rejected(self):
        d = next(d for d in self.pool['decisions'] if d['terminal'] == 'pending_reading_conflict')
        self.pool['rows'][0] = dict(input=self.cohort[2]['encoder_input'], decision_sha256=canonical_json_hash(d))
        self.reject()

    def test_duplicate_source_decision_rejected(self):
        self.pool['decisions'][0] = self.pool['decisions'][1]; self.reject()

    def test_unknown_source_state_rejected(self):
        self.pool['decisions'][0]['terminal'] = 'ai_certified'; self.reject()

    def test_truthy_non_boolean_policy_rejected(self):
        with self.assertRaises(ValueError): self.build(1)

    def test_cache_cannot_claim_gold_admission(self):
        self.cache['independent_gold_eligible'] = True; self.reject()

    def test_cohort_cannot_claim_training_admission(self):
        self.cohort[0]['origin']['training_eligible'] = True; self.reject()

    def test_evaluation_membership_rejected(self):
        self.cohort[0]['membership'] = ['test']; self.reject()

    def test_final_numeric_chain_anchor_rejected(self):
        self.cache['row_chain_head'] = '9'*64; self.reject()

    def test_numeric_order_anchor_rejected(self):
        self.cache['source_order_sha256'] = '9'*64; self.reject()

    def test_empty_population_rejected(self):
        self.cohort.clear(); self.receipts.clear(); self.reject()

    def consume(self, recipe, *, purpose='fit_binding_preparation', digest_override=None, bindings=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'recipe.json'
            raw = canonical_json_bytes(recipe)+b'\n'; path.write_bytes(raw)
            return load_recipe(path, digest_override or hashlib.sha256(raw).hexdigest(),
                               expected_bindings=bindings or recipe['bindings'], purpose=purpose)

    def test_bound_consumer_reproduces_recipe(self):
        recipe = self.build(); self.assertEqual(self.consume(recipe), recipe)

    def test_consumer_rejects_training_gold_calibration_and_test_purposes(self):
        for purpose in ('training', 'gold', 'calibration', 'test', 'numeric_verification'):
            with self.subTest(purpose=purpose), self.assertRaises(ValueError): self.consume(self.build(), purpose=purpose)

    def test_consumer_rejects_wrong_artifact_or_cache_binding(self):
        recipe = self.build()
        with self.assertRaises(ValueError): self.consume(recipe, digest_override='0'*64)
        with self.assertRaises(ValueError): self.consume(recipe, bindings=dict(recipe['bindings'], numeric_manifest_sha256='9'*64))

    def test_resealed_pending_index_injection_rejected(self):
        recipe = self.build(); recipe['selected_indices']['dictionary'].append(2)
        with self.assertRaises(ValueError): self.consume(recipe)

    def test_resealed_permission_escalation_rejected(self):
        for key in ('training_eligible', 'independent_gold_eligible', 'independent_evaluation_eligible'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                recipe = self.build(); recipe[key] = True; self.consume(recipe)

    def test_resealed_changed_policy_or_census_rejected(self):
        recipe = self.build(); recipe['policy']['allow_dictionary_only'] = False
        with self.assertRaises(ValueError): self.consume(recipe)
        recipe = self.build(); recipe['summary']['selected_union'] += 1
        with self.assertRaises(ValueError): self.consume(recipe)


if __name__ == '__main__':
    unittest.main()
