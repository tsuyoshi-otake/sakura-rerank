from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.pilot_doubt_evidence import (
    aggregate, cleaner_probes, dictionary_evidence, read_bytes, selected_cases, validate_sources,
)


class PilotDoubtEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.queue = {'synthetic': dict(source_gold_surface='架空', left_context='新', reading='かくう')}
        self.prior = {'synthetic': dict(axes=dict(reading='compatible', input_unit='boundary_question', context='usable'))}
        self.dictionary = {'synthetic': {'架空': ['かくう']}}
        self.bindings = {'prior_report_sha256': 'a' * 64}
        self.row = dict(case_id='synthetic', queue_case_sha256=canonical_json_hash(self.queue['synthetic']),
                        prior_decision_sha256=canonical_json_hash(self.prior['synthetic']),
                        dictionary_matches_sha256=canonical_json_hash(self.dictionary['synthetic']),
                        outcome='plausible_partial_input', source_ids=[], probe_ids=[],
                        reason='Synthetic partial input', remaining_uncertainty='Not observed user intent')
        self.supplement = dict(kind='pilot_doubt_evidence_not_gold', reviewer_kind='ai_teacher',
                               reviewer_id='codex-primary', reviewed_at='2026-11-04T09:00:00Z',
                               bindings=self.bindings, sources=[], decisions=[self.row])
        excerpt = 'Synthetic primary evidence'
        self.source = dict(id='source-1', url='https://example.org/source', title='Synthetic', excerpt=excerpt,
                           excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
                           accessed_at='2026-11-04T09:00:00Z', kind='institutional_primary',
                           scope='Reading only', limit='Not intended output')

    def result(self, supplement=None):
        return aggregate(self.queue, self.prior, self.dictionary, supplement or self.supplement, self.bindings)

    def test_all_outcomes_complete_without_gold_or_private_text(self):
        for outcome in ('plausible_partial_input', 'insufficient_evidence', 'external_reading_support',
                        'external_contextual_reading_conflict', 'reproducible_context_problem'):
            with self.subTest(outcome=outcome):
                s = copy.deepcopy(self.supplement)
                s['decisions'][0]['outcome'] = outcome
                if outcome.startswith('external_'):
                    s['sources'] = [self.source]
                    s['decisions'][0]['source_ids'] = ['source-1']
                if outcome == 'reproducible_context_problem':
                    self.prior['synthetic']['axes']['context'] = 'defect_nonblocking'
                    s['decisions'][0]['prior_decision_sha256'] = canonical_json_hash(self.prior['synthetic'])
                    s['decisions'][0]['probe_ids'] = ['empty_title']
                result = self.result(s)
                self.assertEqual(result['status'], 'evidence_complete_no_gold')
                self.assertEqual(sum(result['counts'].values()), 1)
                for key in ('independent_review', 'independent_test', 'canonical_labels_changed',
                            'gate_a_human_audit_pass', 'gate_a_owner_authorized_audit_pass'):
                    self.assertIs(result[key], False)
                self.assertIsNone(result['certified_accuracy'])
                self.assertEqual(result['certified_gold_count'], 0)
                self.assertNotIn('架空', json.dumps(result, ensure_ascii=False))
                self.assertNotIn('Synthetic partial input', json.dumps(result))
                self.assertNotIn('case_id', result)

    def test_missing_duplicate_reordered_or_nonselected_cases_fail(self):
        for rows in ([], [self.row, self.row], [dict(self.row, case_id='other')]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.result(dict(self.supplement, decisions=rows))
        with self.assertRaises(ValueError):
            selected_cases(self.queue, {})
        self.queue['second'] = dict(self.queue['synthetic'])
        self.prior['second'] = copy.deepcopy(self.prior['synthetic'])
        self.dictionary['second'] = dict(self.dictionary['synthetic'])
        rows = [dict(self.row, case_id=c) for c in selected_cases(self.queue, self.prior)]
        self.assertEqual(self.result(dict(self.supplement, decisions=rows))['reviewed'], 2)
        with self.assertRaises(ValueError):
            self.result(dict(self.supplement, decisions=list(reversed(rows))))

    def test_provenance_and_label_promotion_rejected(self):
        for change in (dict(reviewer_kind='human'), dict(reviewer_id='independent'),
                       dict(bindings={}), dict(reviewed_at='2026-11-04'), dict(gold=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.result(dict(self.supplement, **change))
        for change in (dict(queue_case_sha256='x'), dict(prior_decision_sha256='x'),
                       dict(dictionary_matches_sha256='x'), dict(accepted_surfaces=['架空']),
                       dict(outcome='gold'), dict(reason=''), dict(remaining_uncertainty='')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.result(dict(self.supplement, decisions=[dict(self.row, **change)]))

    def test_evidence_references_are_required_and_closed(self):
        for change in (dict(outcome='external_reading_support'), dict(source_ids=['missing']),
                       dict(probe_ids=['unknown']), dict(probe_ids=['empty_title', 'empty_title']),
                       dict(outcome='reproducible_context_problem', probe_ids=['empty_title'])):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.result(dict(self.supplement, decisions=[dict(self.row, **change)]))
        with self.assertRaises(ValueError):
            self.result(dict(self.supplement, sources=[self.source]))

    def test_source_hash_url_identity_time_and_limits(self):
        self.assertEqual(set(validate_sources([self.source])), {'source-1'})
        for change in (dict(excerpt='changed'), dict(url='http://example.org/'),
                       dict(url='https://user:password@example.org/'), dict(accessed_at='2026-11-04'),
                       dict(kind='search_snippet'), dict(limit='')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_sources([dict(self.source, **change)])
        with self.assertRaises(ValueError):
            validate_sources([self.source, self.source])

    def test_synthetic_cleaner_failure_mechanisms_are_reproduced(self):
        self.assertEqual(cleaner_probes(), {'math_residue': True, 'empty_title': True})
        self.prior['synthetic']['axes']['context'] = 'defect_nonblocking'
        self.row.update(outcome='reproducible_context_problem', probe_ids=['empty_title'],
                        prior_decision_sha256=canonical_json_hash(self.prior['synthetic']))
        with patch('sakura_rerank.data.pilot_doubt_evidence.cleaner_probes', return_value={'empty_title': False}):
            with self.assertRaises(ValueError):
                self.result()

    def test_dictionary_stream_hash_count_and_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'dictionary.jsonl'
            rows = [dict(surface='架空', readings=['かくう']), dict(surface='新架空', readings=['しんかくう'])]
            raw = b''.join(canonical_json_bytes(r) + b'\n' for r in rows)
            path.write_bytes(raw)
            manifest = dict(manifest_kind='system_dictionary_surface_index', verification_status='verified',
                            normalization='exact_unicode_v1', content_sha256=hashlib.sha256(raw).hexdigest(), record_count=2)
            found = dictionary_evidence(self.queue, ['synthetic'], path, manifest)
            self.assertEqual(found['synthetic'], {r['surface']: r['readings'] for r in rows})
            for change in (dict(record_count=1), dict(content_sha256='x'), dict(normalization='nfkc')):
                with self.assertRaises(ValueError):
                    dictionary_evidence(self.queue, ['synthetic'], path, dict(manifest, **change))
            path.write_bytes(raw + b'x' * 16385)
            with self.assertRaises(ValueError):
                dictionary_evidence(self.queue, ['synthetic'], path, manifest)

    def test_source_file_bound_missing_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'evidence'
            with self.assertRaises(ValueError):
                read_bytes(path)
            path.write_bytes(b'1234')
            with self.assertRaises(ValueError):
                read_bytes(path, 3)
            with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
                read_bytes(path)

    def test_selection_union_not_sum_and_unflagged_denominator_preserved(self):
        self.prior['synthetic']['axes'].update(reading='unknown', context='defect_nonblocking')
        self.assertEqual(selected_cases(self.queue, self.prior), ['synthetic'])
        self.queue['unflagged'] = dict(self.queue['synthetic'])
        self.prior['unflagged'] = dict(axes=dict(reading='compatible', input_unit='whole_plausible', context='usable'))
        self.row.update(outcome='insufficient_evidence', prior_decision_sha256=canonical_json_hash(self.prior['synthetic']))
        result = self.result()
        self.assertEqual((result['pilot_population'], result['selected']), (2, 1))
        self.assertEqual(result['counts']['insufficient_evidence'], 1)


if __name__ == '__main__':
    unittest.main()
