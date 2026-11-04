"""Owner-authorized AI pilot evidence, disjoint from the human review contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash
from .gold_pilot import VERDICTS, load_packet

KINDS = {'V': 'unique_correct', 'O': 'orthographic_equivalent', 'C': 'context_insufficient',
         'R': 'wrong_reading', 'S': 'wrong_segmentation', 'G': 'wrong_gold_surface',
         'N': 'extraction_noise', 'U': 'unresolved'}


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('AI timestamp invalid')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('AI timestamp must be aware')
    return parsed


def _decision(decision: dict, item: dict) -> None:
    if not isinstance(decision, dict) or set(decision) != {'case_id', 'verdict', 'accepted_surfaces', 'reason'}:
        raise ValueError('AI decision fields mismatch')
    if decision['case_id'] != item['case_id'] or decision['verdict'] not in VERDICTS:
        raise ValueError('AI decision identity or verdict mismatch')
    if not isinstance(decision['reason'], str) or not decision['reason'].strip() or len(decision['reason']) > 2000:
        raise ValueError('AI reason missing or oversized')
    surfaces = decision['accepted_surfaces']
    if not isinstance(surfaces, list) or any(not isinstance(s, str) for s in surfaces):
        raise ValueError('AI surfaces must be strings')
    if surfaces != sorted(set(surfaces)) or any(s not in item['candidate_surfaces'] for s in surfaces):
        raise ValueError('AI proposed surface is not a frozen candidate')
    v, gold = decision['verdict'], item['source_gold_surface']
    if v == 'unique_correct' and surfaces != [gold]:
        raise ValueError('AI unique verdict must retain source gold')
    if v == 'orthographic_equivalent' and (len(surfaces) < 2 or gold not in surfaces):
        raise ValueError('AI equivalence needs explicit alternatives')
    if v == 'wrong_gold_surface' and (len(surfaces) != 1 or gold in surfaces):
        raise ValueError('AI corrected surface must differ')
    if v not in ('unique_correct', 'orthographic_equivalent', 'wrong_gold_surface') and surfaces:
        raise ValueError('AI unresolved or defective evidence cannot invent gold')


def validate_batch(value: dict, queue: dict, manifest: dict, policy_sha: str) -> list[dict]:
    if (not isinstance(value, dict) or set(value) != {'batch', 'queue_sha256', 'policy_sha256', 'reviewer_kind', 'reviewer_id',
                      'reviewed_at', 'decisions'} or value['reviewer_kind'] != 'ai_teacher'
            or value['reviewer_id'] != 'codex-primary' or value['queue_sha256'] != manifest['queue_sha256']
            or value['policy_sha256'] != policy_sha or type(value['batch']) is not int
            or not 1 <= value['batch'] <= 40):
        raise ValueError('AI batch provenance mismatch')
    _timestamp(value['reviewed_at'])
    if len(queue) != 1000:
        raise ValueError('AI pilot requires the frozen 1000-case queue')
    ordered = sorted(queue.values(), key=lambda r: canonical_json_hash(['A', r['case_id']]))
    expected = ordered[(value['batch'] - 1) * 25:value['batch'] * 25]
    if not isinstance(value['decisions'], list) or len(value['decisions']) != 25:
        raise ValueError('AI batch must contain 25 explicit decisions')
    for item, decision in zip(expected, value['decisions'], strict=True):
        _decision(decision, item)
    return value['decisions']


def summarize(directory: Path, queue: dict, manifest: dict, policy_sha: str,
              previous: dict | None = None) -> dict:
    if not directory.is_dir():
        raise ValueError('AI review directory missing')
    counts, batches, latest, event_hashes, times = Counter(), {}, {}, {}, {}
    files = sorted(directory.glob('batch-*.json'))
    if len(files) > 40:
        raise ValueError('AI batch count exceeds bound')
    for file in files:
        if file.stat().st_size > 256 * 1024:
            raise ValueError('AI batch exceeds bound')
        raw = file.read_bytes()
        data = json.loads(raw)
        decisions = validate_batch(data, queue, manifest, policy_sha)
        if file.name != f"batch-{data['batch']:03d}.json":
            raise ValueError('AI batch filename mismatch')
        counts.update(x['verdict'] for x in decisions)
        batches[file.name] = hashlib.sha256(raw).hexdigest()
        for decision in decisions:
            case = decision['case_id']
            latest[case] = decision
            event_hashes[case] = canonical_json_hash(decision)
            times[case] = _timestamp(data['reviewed_at'])
    initial_counts = dict(sorted(counts.items()))
    amendments, transitions = [], Counter()
    journal = directory / 'amendments.jsonl'
    if journal.exists():
        if journal.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('AI amendment journal exceeds bound')
        lines = journal.read_bytes().splitlines()
        if len(lines) > 2000:
            raise ValueError('AI amendment count exceeds bound')
        for line in lines:
            event = json.loads(line)
            fields = {'queue_sha256', 'policy_sha256', 'reviewer_kind', 'reviewer_id',
                      'reviewed_at', 'previous_event_sha256', 'previous_log_sha256', 'decision'}
            if (not isinstance(event, dict) or set(event) != fields
                    or event['queue_sha256'] != manifest['queue_sha256']
                    or event['policy_sha256'] != policy_sha
                    or event['reviewer_kind'] != 'ai_teacher' or event['reviewer_id'] != 'codex-primary'
                    or not isinstance(event['decision'], dict)):
                raise ValueError('AI amendment provenance mismatch')
            decision = event['decision']
            case = decision.get('case_id')
            if not isinstance(case, str) or case not in latest:
                raise ValueError('AI amendment has no initial review')
            _decision(decision, queue[case])
            moment = _timestamp(event['reviewed_at'])
            if (event['previous_event_sha256'] != event_hashes[case]
                    or event['previous_log_sha256'] != (amendments[-1] if amendments else None)
                    or moment < times[case]):
                raise ValueError('AI amendment history mismatch')
            transitions[latest[case]['verdict'] + ' -> ' + decision['verdict']] += 1
            counts[latest[case]['verdict']] -= 1
            counts[decision['verdict']] += 1
            latest[case], times[case] = decision, moment
            event_hashes[case] = canonical_json_hash(event)
            amendments.append(event_hashes[case])
    if previous is not None:
        if (previous.get('queue_sha256') != manifest['queue_sha256']
                or previous.get('policy_sha256') != policy_sha
                or any(batches.get(k) != v for k, v in previous['batch_sha256'].items())
                or amendments[:len(previous['amendment_sha256'])] != previous['amendment_sha256']):
            raise ValueError('AI report history was rewritten or truncated')
    reviewed = sum(counts.values())
    return {'schema_version': 1, 'kind': 'owner_authorized_single_ai_pilot',
            'status': 'ai_review_complete_no_gate' if reviewed == 1000 else 'ai_review_in_progress',
            'selected': 1000, 'reviewed': reviewed, 'pending': 1000-reviewed,
            'counts': {v: counts[v] for v in sorted(VERDICTS)}, 'batch_sha256': batches,
            'initial_counts': initial_counts, 'amendment_sha256': amendments,
            'self_correction_count': len(amendments), 'self_correction_transitions': dict(sorted(transitions.items())),
            'queue_sha256': manifest['queue_sha256'], 'policy_sha256': policy_sha,
            'reviewer_kind': 'ai_teacher', 'reviewer_count': 1, 'human_review_count': 0,
            'independent_double_review': False, 'independent_test': False,
            'canonical_labels_changed': False, 'gate_a_human_audit_pass': False,
            'gate_a_owner_authorized_audit_pass': False,
            'certified_accuracy': None, 'independent_valid_holdout_count': 0,
            'raw_text_in_report': False, 'raw_stable_ids_in_report': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--batches', type=Path, required=True)
    parser.add_argument('--previous-report', type=Path)
    args = parser.parse_args()
    try:
        manifest, queue, _ = load_packet(args.packet)
        raw_policy = args.policy.read_bytes()
        policy = json.loads(raw_policy)
        if (policy.get('policy_version') != 'gold-pilot-ai-v1' or policy.get('gate_a_eligible') is not False
                or policy.get('reviewer_kind') != 'ai_teacher' or policy.get('human_review_count') != 0
                or policy.get('independent_test') is not False):
            raise ValueError('AI pilot policy invalid')
        previous = json.loads(args.previous_report.read_bytes()) if args.previous_report else None
        report = summarize(args.batches, queue, manifest, hashlib.sha256(raw_policy).hexdigest(), previous)
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('AI review validation failed; no report emitted')
    print(canonical_json_bytes(report).decode('utf-8'))


if __name__ == '__main__':
    main()
