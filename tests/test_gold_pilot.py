from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.gold_pilot import (
    _publish, load_packet, prepare, reconcile, verify_history_extension,
)

POLICY = Path(__file__).parents[1] / 'research/gold-pilot-policy-v1.json'


def projection(i, split='train'):
    return {'stable_id': f'synthetic-{i:04d}', 'split': split,
            'source': {'article_id': f'article-{i}', 'paragraph_hash': str(i),
                       'sentence_hash': str(i), 'template_cluster_id': None},
            'converter_provenance': {'kind': 'synthetic-unit-test'},
            'input_key': f'input-{i}', 'feature_input_key': f'feature-{i}',
            'left_context': f'synthetic context {i}', 'reading': 'synthetic reading',
            'gold_surface': '日本', 'gold_index': 0,
            'gold_segments': [{'text_start': 0, 'text_end': 6}],
            'candidate_surfaces': ['日本', 'にほん'], 'top6_count': 2,
            'row_sha256': 'a' * 64}


def event(manifest, case, role, verdict='unique_correct', surfaces=None, **updates):
    result = {'case_id': case, 'role': role, 'reviewer_id': 'human-' + role,
              'reviewer_kind': 'human', 'reviewed_at': '2026-11-04T10:00:00+09:00',
              'verdict': verdict, 'accepted_surfaces': ['日本'] if surfaces is None else surfaces,
              'reason': 'Synthetic test judgment, not human evidence',
              'queue_sha256': manifest['queue_sha256'], 'policy_sha256': manifest['policy_sha256'],
              'previous_event_sha256': None, 'basis_sha256': []}
    result.update(updates)
    return result


class GoldPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [projection(i) for i in range(1005)]
        cls.payloads = prepare(cls.rows, {'sha256': 'b' * 64}, POLICY.read_bytes())
        cls.manifest = json.loads(cls.payloads['manifest.json'])
        cls.queue = {r['case_id']: r for r in map(json.loads, cls.payloads['queue.jsonl'].splitlines())}
        cls.bindings = {r['case_id']: r for r in map(json.loads, cls.payloads['coordinator-only-bindings.jsonl'].splitlines())}
        cls.case = next(iter(cls.queue))

    def check(self, events):
        return reconcile(self.manifest, self.queue, self.bindings, events)

    def test_selection_is_deterministic_and_train_only(self):
        rows = list(reversed(self.rows)) + [projection(2000, 'dev'), projection(2001, 'final-holdout')]
        self.assertEqual(self.payloads, prepare(rows, {'sha256': 'b' * 64}, POLICY.read_bytes()))
        self.assertEqual(len(self.queue), 1000)
        self.assertEqual(self.manifest['eligible_train_input_groups'], 1005)

    def test_duplicate_input_cannot_fill_sample_and_insufficient_pool_fails(self):
        rows = [projection(i) for i in range(999)]
        extra = projection(9999)
        extra['input_key'] = rows[0]['input_key']
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            prepare(rows + [extra], {}, POLICY.read_bytes())

    def test_blind_packet_and_utf8_segmentation(self):
        for item in self.queue.values():
            self.assertEqual(item['gold_segment_surfaces'], ['日本'])
            self.assertEqual(item['candidate_surfaces'], sorted(item['candidate_surfaces']))
            for forbidden in ['stable_id', 'split', 'gold_index', 'local_cost', 'model', 'prediction']:
                self.assertNotIn(forbidden, item)
        a = json.loads(self.payloads['reviewer-A/batch-001.json'])
        b = json.loads(self.payloads['reviewer-B/batch-001.json'])
        self.assertNotEqual(a['cases'], b['cases'])
        self.assertEqual(len(a['cases']), 25)

    def test_empty_review_has_explicit_terminal_and_no_quality_claim(self):
        report, proposals, disputed = self.check([])
        self.assertEqual(report['status'], 'awaiting_dual_review')
        self.assertEqual(report['pending'], 1000)
        self.assertIsNone(report['agreement_rate'])
        self.assertFalse(proposals or disputed)
        self.assertFalse(report['gate_a_human_audit_pass'])

    def test_all_perfect_reviews_still_cannot_pass_gate_a(self):
        events = [event(self.manifest, c, r) for c in self.queue for r in ('A', 'B')]
        report, proposals, disputed = self.check(events)
        self.assertEqual(report['status'], 'pilot_complete_no_gate')
        self.assertEqual(report['finalized'], 1000)
        self.assertEqual(report['agreement_rate'], 1)
        self.assertFalse(report['gate_a_human_audit_pass'])
        self.assertFalse(report['gate_a_owner_authorized_audit_pass'])
        self.assertEqual(report['final_holdout_valid_count'], 0)
        self.assertFalse(disputed)
        self.assertTrue(all(p['kind'] == 'pilot_proposal_not_applied' for p in proposals))

    def test_role_identity_and_ai_rejection(self):
        a = event(self.manifest, self.case, 'A')
        for update in [{'reviewer_kind': 'ai_teacher'}, {'reviewer_id': 'human-A'}]:
            b = event(self.manifest, self.case, 'B', **update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.check([a, b])

    def test_disagreement_requires_bound_adjudication(self):
        a = event(self.manifest, self.case, 'A')
        b = event(self.manifest, self.case, 'B', 'context_insufficient', [])
        report, proposals, disputed = self.check([a, b])
        self.assertEqual(report['counts']['awaiting_adjudication'], 1)
        self.assertEqual(len(disputed), 1)
        self.assertFalse(proposals)
        c = event(self.manifest, self.case, 'C', basis_sha256=[canonical_json_hash(a), canonical_json_hash(b)])
        report, proposals, _ = self.check([a, b, c])
        self.assertEqual(report['finalized'], 1)
        self.assertEqual(len(proposals[0]['review_evidence_sha256']), 3)

    def test_amendment_invalidates_old_adjudication_and_preserves_history(self):
        a = event(self.manifest, self.case, 'A')
        b = event(self.manifest, self.case, 'B', 'context_insufficient', [])
        c = event(self.manifest, self.case, 'C', basis_sha256=[canonical_json_hash(a), canonical_json_hash(b)])
        b2 = dict(b, reason='New synthetic reason', previous_event_sha256=canonical_json_hash(b))
        report, proposals, _ = self.check([a, b, c, b2])
        self.assertEqual(report['event_count'], 4)
        self.assertEqual(report['counts']['awaiting_adjudication'], 1)
        self.assertFalse(proposals)

    def test_unresolved_agreement_is_not_complete(self):
        report, proposals, _ = self.check([event(self.manifest, self.case, r, 'unresolved', []) for r in ('A', 'B')])
        self.assertEqual(report['counts']['awaiting_adjudication'], 1)
        self.assertFalse(proposals)

    def test_duplicate_event_and_contract_mutations_fail_closed(self):
        a = event(self.manifest, self.case, 'A')
        with self.assertRaises(ValueError):
            self.check([a, a])
        mutations = [dict(queue_sha256='0' * 64), dict(policy_sha256='0' * 64),
                     dict(reviewed_at='2026-11-04T10:00:00'), dict(reason=''),
                     dict(accepted_surfaces=['not-in-candidates']), dict(verdict='valid'),
                     dict(previous_event_sha256='0' * 64), dict(basis_sha256=['wrong']),
                     dict(extra='unsupported')]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.check([dict(a, **mutation)])

    def test_packet_tampering_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'packet'
            _publish(path, self.payloads)
            self.assertEqual(load_packet(path)[0], self.manifest)
            with self.assertRaises(ValueError):
                _publish(path, self.payloads)
            with (path / 'queue.jsonl').open('ab') as f:
                f.write(b'\n')
            with self.assertRaisesRegex(ValueError, 'hash'):
                load_packet(path)

    def test_publication_failure_cleans_staging(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'packet'
            with patch('sakura_rerank.data.gold_pilot.os.fsync', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    _publish(path, self.payloads)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_report_is_aggregate_only(self):
        a = event(self.manifest, self.case, 'A')
        report, _, _ = self.check([a])
        encoded = json.dumps(report)
        for value in [self.case, 'human-A', '日本', 'Synthetic test judgment']:
            self.assertNotIn(value, encoded)

    def test_blank_templates_are_not_human_evidence(self):
        template = json.loads(self.payloads['reviewer-A/responses-001.template.jsonl'].splitlines()[0])
        self.assertIsNone(template['reviewer_kind'])
        with self.assertRaises(ValueError):
            self.check([template])

    def test_history_extension_rejects_prior_deletion_or_edits(self):
        a = event(self.manifest, self.case, 'A')
        b = event(self.manifest, self.case, 'B')
        report = self.check([a])[0]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'report.json').write_text(json.dumps(report), encoding='utf-8')
            (p/'events.jsonl').write_text(json.dumps(a)+'\n', encoding='utf-8')
            self.assertEqual(verify_history_extension(p, self.manifest, [a,b]), canonical_json_hash(report))
            for changed in [[], [b], [dict(a, reason='changed'), b]]:
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    verify_history_extension(p, self.manifest, changed)


if __name__ == '__main__':
    unittest.main()
