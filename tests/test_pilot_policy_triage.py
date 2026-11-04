from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sakura_rerank.data.ai_pilot_review import summarize
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.pilot_policy_triage import load_baseline, summarize_triage


class PilotPolicyTriageTests(unittest.TestCase):
    def setUp(self):
        self.queue = {f'synthetic-{i}': dict(case_id=f'synthetic-{i}', source_gold_surface='合成',
                      candidate_surfaces=['合成', 'ごうせい'], left_context='PRIVATE_CONTEXT') for i in range(1000)}
        self.manifest = dict(queue_sha256='a'*64)
        self.policy = dict(policy_version='gold-pilot-triage-v1', reviewer_kind='ai_teacher',
                           reviewer_id='codex-primary', gate_a_eligible=False, independent_test=False,
                           labels_may_be_applied=False,
                           rules={'E3': dict(name='kana_kanji', action='review_form', definition='Synthetic only')})
        self.policy_raw = canonical_json_bytes(self.policy)
        self.base_sha = 'b'*64
        self.base = {}
        for i, (case, row) in enumerate(self.queue.items()):
            decision = dict(case_id=case, verdict='context_insufficient' if i<2 else 'unique_correct',
                            accepted_surfaces=[] if i<2 else ['合成'], reason='Synthetic')
            self.base[case] = decision, canonical_json_hash(decision), '2026-11-04T00:00:00Z'
        self.events = []
        previous = None
        for i in range(2):
            case = f'synthetic-{i}'
            event = dict(case_id=case, prior_event_sha256=self.base[case][1],
                evidence_case_sha256=canonical_json_hash(self.queue[case]), base_report_sha256=self.base_sha,
                queue_sha256=self.manifest['queue_sha256'], policy_sha256=hashlib.sha256(self.policy_raw).hexdigest(),
                reviewer_kind='ai_teacher', reviewer_id='codex-primary', reviewed_at='2026-11-04T01:00:00Z',
                previous_log_sha256=previous, rule='E3', reason='PRIVATE_CASE_REASON')
            self.events.append(event)
            previous = canonical_json_hash(event)

    def run_summary(self, events=None, policy=None):
        raw = b''.join(canonical_json_bytes(e)+b'\n' for e in (self.events if events is None else events))
        return summarize_triage(raw, self.policy_raw if policy is None else canonical_json_bytes(policy),
                                self.queue, self.manifest, self.base, self.base_sha)

    def test_complete_routing_is_not_gold_and_public_report_has_no_case_text(self):
        report = self.run_summary()
        self.assertEqual((report['selected'], report['reviewed'], report['pending']), (2,2,0))
        self.assertEqual(report['other_cases_not_reassessed'], 998)
        self.assertEqual(report['rule_counts'], {'E3':2})
        self.assertEqual(report['human_review_count'], 0)
        for field in ('independent_double_review', 'independent_test', 'eligible_for_label_application',
                      'canonical_labels_changed', 'gate_a_human_audit_pass', 'gate_a_owner_authorized_audit_pass'):
            self.assertIs(report[field], False)
        self.assertIsNone(report['certified_accuracy'])
        text = json.dumps(report, ensure_ascii=False)
        for raw in ('synthetic-', '合成', 'PRIVATE_'):
            self.assertNotIn(raw, text)

    def test_missing_duplicate_or_outside_flagged_population_rejected(self):
        for events in ([], self.events[:1], [self.events[0],self.events[0]],
                       [dict(self.events[0],case_id='synthetic-4'),self.events[1]]):
            with self.subTest(events=len(events)), self.assertRaises(ValueError):
                self.run_summary(events)

    def test_stale_evidence_wrong_policy_and_broken_chain_rejected(self):
        for key in ('prior_event_sha256', 'evidence_case_sha256', 'base_report_sha256',
                    'queue_sha256', 'policy_sha256', 'previous_log_sha256'):
            events = copy.deepcopy(self.events)
            events[1][key] = 'f'*64
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.run_summary(events)
        with self.assertRaises(ValueError):
            self.run_summary(list(reversed(self.events)))

    def test_label_fields_human_provenance_unknown_rule_empty_reason_rejected(self):
        for mutation in ({'accepted_surfaces':['合成']}, {'reviewer_kind':'human'}, {'reviewer_id':'human-A'},
                         {'rule':'XX'}, {'reason':' '}, {'reason':'x'*2001}, {'reviewed_at':'2026-11-04'},
                         {'reviewed_at':'2026-11-03T00:00:00Z'}):
            events = copy.deepcopy(self.events)
            events[1].update(mutation)
            with self.subTest(mutation=list(mutation)), self.assertRaises(ValueError):
                self.run_summary(events)

    def test_policy_cannot_promote_to_certified_labels(self):
        for field in ('gate_a_eligible', 'independent_test', 'labels_may_be_applied'):
            policy = dict(self.policy, **{field:True})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_summary(policy=policy)

    def test_unbound_population_and_resource_limits_rejected(self):
        self.base.pop('synthetic-999')
        with self.assertRaises(ValueError):
            self.run_summary()
        with self.assertRaisesRegex(ValueError, 'bound'):
            summarize_triage(b' '* (2*1024*1024+1), self.policy_raw, {}, {}, {}, '')

    def test_rules_cannot_smuggle_case_text_into_public_names(self):
        policy = copy.deepcopy(self.policy)
        policy['rules']['E3']['name'] = 'raw case 日本'
        with self.assertRaises(ValueError):
            self.run_summary(policy=policy)

    def test_full_baseline_replay_requires_exact_previous_report(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            ai_policy = dict(policy_version='gold-pilot-ai-v1', gate_a_eligible=False,
                             independent_test=False, human_review_count=0, reviewer_kind='ai_teacher')
            policy_raw = canonical_json_bytes(ai_policy)
            (folder/'policy.json').write_bytes(policy_raw)
            policy_sha = hashlib.sha256(policy_raw).hexdigest()
            ordered = sorted(self.queue, key=lambda c: canonical_json_hash(['A',c]))
            for batch in range(40):
                value = dict(batch=batch+1, queue_sha256=self.manifest['queue_sha256'], policy_sha256=policy_sha,
                             reviewer_kind='ai_teacher', reviewer_id='codex-primary', reviewed_at='2026-11-04T00:00:00Z',
                             decisions=[self.base[c][0] for c in ordered[batch*25:(batch+1)*25]])
                (folder/f'batch-{batch+1:03d}.json').write_bytes(canonical_json_bytes(value))
            summary = summarize(folder,self.queue,self.manifest,policy_sha)
            report_path = folder/'report.json'
            report_path.write_bytes(canonical_json_bytes(summary))
            latest, _ = load_baseline(folder,self.queue,self.manifest,folder/'policy.json',report_path)
            self.assertEqual(set(latest),set(self.queue))
            summary['counts']['unique_correct'] = 1000
            report_path.write_bytes(canonical_json_bytes(summary))
            with self.assertRaisesRegex(ValueError, 'exact complete'):
                load_baseline(folder,self.queue,self.manifest,folder/'policy.json',report_path)
            for malformed in ([], None, 5):
                (folder/'policy.json').write_bytes(canonical_json_bytes(malformed))
                with self.subTest(policy=malformed), self.assertRaises(ValueError):
                    load_baseline(folder,self.queue,self.manifest,folder/'policy.json',report_path)


if __name__ == '__main__':
    unittest.main()
