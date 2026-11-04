"""Read-only policy routing for an immutable single-AI pilot; never emit labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .ai_pilot_review import summarize
from .contracts import canonical_json_bytes, canonical_json_hash
from .gold_pilot import load_packet


def _read(path: Path, limit: int = 2 * 1024 * 1024) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('triage input violates regular-file size bound')
    return path.read_bytes()


def _moment(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('triage time invalid')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('triage time must be aware')
    return parsed


def load_baseline(directory: Path, queue: dict, manifest: dict, ai_policy: Path,
                  previous_report: Path) -> tuple[dict, str]:
    """Validate the complete frozen report before exposing its latest case events."""
    raw_report = _read(previous_report)
    previous = json.loads(raw_report)
    if not isinstance(previous, dict):
        raise ValueError('triage baseline report must be an object')
    raw_policy = _read(ai_policy, 128 * 1024)
    policy = json.loads(raw_policy)
    if (not isinstance(policy, dict) or policy.get('policy_version') != 'gold-pilot-ai-v1'
            or policy.get('gate_a_eligible') is not False
            or policy.get('independent_test') is not False
            or policy.get('human_review_count') != 0
            or policy.get('reviewer_kind') != 'ai_teacher'):
        raise ValueError('triage baseline must be an uncertified AI pilot')
    current = summarize(directory, queue, manifest, hashlib.sha256(raw_policy).hexdigest(), previous)
    if current != previous or current['reviewed'] != 1000:
        raise ValueError('triage requires the exact complete baseline report')
    latest = {}
    for file in sorted(directory.glob('batch-*.json')):
        batch = json.loads(_read(file, 256 * 1024))
        for decision in batch['decisions']:
            latest[decision['case_id']] = (decision, canonical_json_hash(decision), batch['reviewed_at'])
    journal = directory / 'amendments.jsonl'
    if journal.exists():
        for line in _read(journal).splitlines():
            event = json.loads(line)
            latest[event['decision']['case_id']] = (event['decision'], canonical_json_hash(event), event['reviewed_at'])
    return latest, hashlib.sha256(raw_report).hexdigest()


def summarize_triage(raw: bytes, policy_raw: bytes, queue: dict, manifest: dict,
                     baseline: dict, base_sha: str) -> dict:
    """Require one explicit route for every non-unique case; publish aggregates only."""
    if len(raw) > 2 * 1024 * 1024 or len(policy_raw) > 128 * 1024:
        raise ValueError('triage input exceeds bound')
    policy = json.loads(policy_raw)
    if (not isinstance(policy, dict) or policy.get('policy_version') != 'gold-pilot-triage-v1'
            or policy.get('reviewer_kind') != 'ai_teacher' or policy.get('reviewer_id') != 'codex-primary'
            or any(policy.get(k) is not False for k in ('gate_a_eligible', 'independent_test', 'labels_may_be_applied'))):
        raise ValueError('triage policy cannot authorize labels or certification')
    rules = policy.get('rules')
    if not isinstance(rules, dict) or not 1 <= len(rules) <= 32:
        raise ValueError('triage rules invalid')
    for code, rule in rules.items():
        if (not re.fullmatch(r'[A-Z][0-9]', code) or not isinstance(rule, dict)
                or set(rule) != {'name', 'action', 'definition'}
                or any(not isinstance(rule[k], str) or not re.fullmatch(r'[a-z_]{1,64}', rule[k]) for k in ('name', 'action'))
                or not isinstance(rule['definition'], str) or not 1 <= len(rule['definition']) <= 2000):
            raise ValueError('triage rule contract invalid')
    if len(queue) != 1000 or set(baseline) != set(queue):
        raise ValueError('triage baseline population mismatch')
    selected = {c for c, (d, _, _) in baseline.items() if d['verdict'] != 'unique_correct'}
    lines = raw.splitlines()
    if len(lines) > 1000:
        raise ValueError('triage event count exceeds bound')
    policy_sha = hashlib.sha256(policy_raw).hexdigest()
    seen, previous_hash = set(), None
    counts, actions, prior, cross = Counter(), Counter(), Counter(), Counter()
    for line in lines:
        event = json.loads(line)
        fields = {'case_id', 'prior_event_sha256', 'evidence_case_sha256', 'base_report_sha256',
                  'queue_sha256', 'policy_sha256', 'reviewer_kind', 'reviewer_id', 'reviewed_at',
                  'previous_log_sha256', 'rule', 'reason'}
        if not isinstance(event, dict) or set(event) != fields:
            raise ValueError('triage event fields mismatch; labels are not permitted')
        case = event['case_id']
        if not isinstance(case, str) or case not in selected or case in seen:
            raise ValueError('triage case missing, duplicate or outside flagged cohort')
        decision, event_hash, reviewed_at = baseline[case]
        if (event['prior_event_sha256'] != event_hash
                or event['evidence_case_sha256'] != canonical_json_hash(queue[case])
                or event['base_report_sha256'] != base_sha
                or event['queue_sha256'] != manifest['queue_sha256']
                or event['policy_sha256'] != policy_sha
                or event['previous_log_sha256'] != previous_hash
                or event['reviewer_kind'] != 'ai_teacher' or event['reviewer_id'] != 'codex-primary'
                or _moment(event['reviewed_at']) < _moment(reviewed_at)):
            raise ValueError('triage evidence, provenance or history mismatch')
        rule, reason = event['rule'], event['reason']
        if (not isinstance(rule, str) or rule not in rules or not isinstance(reason, str)
                or not reason.strip() or len(reason) > 2000):
            raise ValueError('triage route and explicit reason required')
        counts[rule] += 1
        actions[rules[rule]['action']] += 1
        prior[decision['verdict']] += 1
        cross[(decision['verdict'], rule)] += 1
        seen.add(case)
        previous_hash = canonical_json_hash(event)
    if seen != selected:
        raise ValueError('triage incomplete; no complete report may be emitted')
    return dict(schema_version=1, kind='single_ai_policy_triage_no_labels', status='complete_triage_no_labels',
                pilot_population=1000, selected=len(selected), reviewed=len(seen), pending=0,
                other_cases_not_reassessed=1000-len(selected), rule_counts=dict(sorted(counts.items())),
                action_counts=dict(sorted(actions.items())), prior_verdict_counts=dict(sorted(prior.items())),
                prior_by_rule=[dict(prior_verdict=v, rule=r, count=n) for (v,r),n in sorted(cross.items())],
                queue_sha256=manifest['queue_sha256'], base_report_sha256=base_sha,
                policy_sha256=policy_sha, ledger_sha256=hashlib.sha256(raw).hexdigest(),
                final_event_sha256=previous_hash, reviewer_kind='ai_teacher', reviewer_count=1,
                human_review_count=0, independent_double_review=False, independent_test=False,
                canonical_labels_changed=False, eligible_for_label_application=False,
                gate_a_human_audit_pass=False, gate_a_owner_authorized_audit_pass=False,
                certified_accuracy=None, independent_valid_holdout_count=0,
                raw_text_in_report=False, raw_stable_ids_in_report=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('packet', 'ai-policy', 'batches', 'base-report', 'triage-policy', 'ledger'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest, queue, _ = load_packet(args.packet)
        baseline, base_sha = load_baseline(args.batches, queue, manifest, args.ai_policy, args.base_report)
        report = summarize_triage(_read(args.ledger), _read(args.triage_policy, 128 * 1024),
                                  queue, manifest, baseline, base_sha)
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('policy triage validation failed; no report emitted')
    print(canonical_json_bytes(report).decode('utf-8'))


if __name__ == '__main__':
    main()
