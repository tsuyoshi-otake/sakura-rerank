"""Immutable 1,000-row operations pilot; never certifies Gate A or changes gold.

prepare writes a new local packet directory. reconcile validates append-only
human event chains and writes a new aggregate report plus proposed overlays.
Pilot completion and independent final data-quality certification are distinct.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash, canonical_jsonl_bytes
from .frozen_diagnostics import read_projection

PILOT_SIZE = 1000
SEED = 20261104
POLICY_VERSION = 'gold-pilot-v1'
VERDICTS = ('unique_correct', 'orthographic_equivalent', 'context_insufficient',
            'wrong_reading', 'wrong_segmentation', 'wrong_gold_surface',
            'extraction_noise', 'unresolved')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
MAX_PACKET_BYTES = 32 * 1024 * 1024
MAX_EVENT_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10000


def _blob(value: object) -> bytes:
    return canonical_json_bytes(value) + b'\n'


def _publish(path: Path, payloads: dict[str, bytes]) -> None:
    """Own staging cleanup; a destination must be new (no overwrite/retry)."""
    if path.exists():
        raise ValueError('destination already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.gold-pilot-', dir=path.parent))
    try:
        for name, payload in payloads.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        # Windows rename refuses any existing destination. No partial publication.
        if path.exists():
            raise ValueError('destination appeared during publication')
        staging.rename(path)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def prepare(rows: list[dict], source: dict, policy: bytes) -> dict[str, bytes]:
    """Select train-only unique bounded inputs, independent of model outcomes."""
    policy_value = json.loads(policy)
    if policy_value.get('policy_version') != POLICY_VERSION:
        raise ValueError('unsupported pilot policy')
    if policy_value.get('pilot_size') != PILOT_SIZE or policy_value.get('gate_a_eligible') is not False:
        raise ValueError('pilot policy cannot authorize Gate A')
    if policy_value.get('verdicts') != list(VERDICTS):
        raise ValueError('policy verdict contract mismatch')
    policy_sha = hashlib.sha256(policy).hexdigest()
    pool = {}
    for row in sorted(rows, key=lambda r: r['stable_id']):
        if row['split'] == 'train':
            pool.setdefault(row['input_key'], row)
    if len(pool) < PILOT_SIZE:
        raise ValueError('insufficient distinct training inputs for pilot')
    selected = sorted(pool.values(), key=lambda r: canonical_json_hash([SEED, r['input_key']]))[:PILOT_SIZE]
    queue, binding = [], []
    for row in selected:
        case_id = 'p-' + canonical_json_hash([SEED, row['stable_id']])[:24]
        # Lexical order removes original converter rank; no costs or predictions.
        surfaces = sorted(set(row['candidate_surfaces']))
        item = {'case_id': case_id, 'left_context': row['left_context'],
                'reading': row['reading'], 'source_gold_surface': row['gold_surface'],
                'candidate_surfaces': surfaces,
                'gold_segment_surfaces': [row['gold_surface'].encode('utf-8')[s['text_start']:s['text_end']].decode('utf-8')
                                          for s in row['gold_segments']]}
        queue.append(item)
        binding.append({'case_id': case_id, 'stable_id': row['stable_id'],
                        'source_row_sha256': row['row_sha256'], 'old_gold_surface': row['gold_surface'],
                        'source': row['source'], 'converter_provenance': row['converter_provenance']})
    queue.sort(key=lambda x: x['case_id'])
    binding.sort(key=lambda x: x['case_id'])
    qbytes = canonical_jsonl_bytes(queue)
    bbytes = canonical_jsonl_bytes(binding)
    manifest = {'schema_version': 1, 'kind': 'gold_operations_pilot',
                'policy_version': POLICY_VERSION, 'policy_sha256': policy_sha,
                'source': source, 'seed': SEED, 'size': PILOT_SIZE,
                'sampling': 'deterministic equal-probability distinct train input groups; not a population quality estimate',
                'eligible_train_input_groups': len(pool),
                'queue_sha256': hashlib.sha256(qbytes).hexdigest(),
                'binding_sha256': hashlib.sha256(bbytes).hexdigest(),
                'gate_a_eligible': False, 'independent_test': False,
                'original_data_changed': False, 'raw_text_in_manifest': False}
    payloads = {'manifest.json': _blob(manifest), 'queue.jsonl': qbytes,
                'coordinator-only-bindings.jsonl': bbytes, 'policy.json': policy}
    for role in ('A', 'B'):
        # Distinct review orders discourage copying; neither sees the other pass.
        ordered = sorted(queue, key=lambda r: canonical_json_hash([role, r['case_id']]))
        for start in range(0, PILOT_SIZE, 25):
            batch = ordered[start:start + 25]
            payloads[f'reviewer-{role}/batch-{start // 25 + 1:03d}.json'] = _blob({
                'role': role, 'queue_sha256': manifest['queue_sha256'],
                'policy_sha256': policy_sha, 'instructions': policy_value['review_instructions'],
                'cases': batch})
            payloads[f'reviewer-{role}/responses-{start // 25 + 1:03d}.template.jsonl'] = canonical_jsonl_bytes([
                {'case_id': item['case_id'], 'role': role, 'reviewer_id': None,
                 'reviewer_kind': None, 'reviewed_at': None, 'verdict': None,
                 'accepted_surfaces': [], 'reason': '',
                 'queue_sha256': manifest['queue_sha256'], 'policy_sha256': policy_sha,
                 'previous_event_sha256': None, 'basis_sha256': []} for item in batch])
    payloads['REVIEW.md'] = (
        '# Gold pilot review\n\n'
        '担当者A/Bには対応するreviewerディレクトリとpolicy.jsonだけを渡してください。\n'
        '他の判定者の資料・判定、coordinator-only-bindings.jsonlは見せません。\n'
        '各batchは25件、全40batch。原文一致と一意正解を分け、方針に従って判断します。\n'
        '人手判定は未記入です。AIで代筆・水増ししないでください。\n'
        '判定はresearch/gold-pilot-protocol.mdのJSONL event形式で保存します。\n'
        'このpilotは独立TestでもGate A品質保証でもありません。\n'
    ).encode('utf-8')
    return payloads


def load_packet(path: Path) -> tuple[dict, dict, dict]:
    names = ('manifest.json', 'queue.jsonl', 'coordinator-only-bindings.jsonl', 'policy.json')
    payloads = {}
    for name in names:
        p = path / name
        if p.is_symlink() or p.stat().st_size > MAX_PACKET_BYTES:
            raise ValueError('packet exceeds regular-file bound')
        payloads[name] = p.read_bytes()
    manifest = json.loads(payloads['manifest.json'])
    if (manifest.get('kind') != 'gold_operations_pilot' or manifest.get('size') != PILOT_SIZE
            or manifest.get('gate_a_eligible') is not False or manifest.get('independent_test') is not False):
        raise ValueError('not an operations pilot')
    for name, field in [('queue.jsonl', 'queue_sha256'), ('coordinator-only-bindings.jsonl', 'binding_sha256'),
                        ('policy.json', 'policy_sha256')]:
        if hashlib.sha256(payloads[name]).hexdigest() != manifest[field]:
            raise ValueError('packet hash mismatch')
    queue = [json.loads(line) for line in payloads['queue.jsonl'].splitlines()]
    bindings = [json.loads(line) for line in payloads['coordinator-only-bindings.jsonl'].splitlines()]
    qmap = {x['case_id']: x for x in queue}
    bmap = {x['case_id']: x for x in bindings}
    if len(queue) != PILOT_SIZE or len(qmap) != PILOT_SIZE or len(bindings) != PILOT_SIZE or set(qmap) != set(bmap):
        raise ValueError('packet identities mismatch')
    return manifest, qmap, bmap


def reconcile(manifest: dict, queue: dict, bindings: dict, events: list[dict]) -> tuple[dict, list, list]:
    """Validate human history and return aggregate state, proposals, adjudications.

    Roles must be distinct humans. Amendments append a hash-linked event; earlier
    evidence is retained. Adjudications bind the exact latest A/B event hashes.
    Missing, disputed or unresolved cases remain explicit pending terminal states.
    No proposal is applied to a dataset, model or Gate A.
    """
    if len(events) > MAX_EVENTS:
        raise ValueError('event count exceeds bound')
    latest, reviewers = {}, {}
    fields = {'case_id', 'role', 'reviewer_id', 'reviewer_kind', 'reviewed_at', 'verdict',
              'accepted_surfaces', 'reason', 'queue_sha256', 'policy_sha256',
              'previous_event_sha256', 'basis_sha256'}
    for number, event in enumerate(events, 1):
        def invalid():
            raise ValueError(f'event {number}: invalid review contract')
        if not isinstance(event, dict) or set(event) != fields:
            invalid()
        if event['case_id'] not in queue or event['role'] not in ('A', 'B', 'C'):
            invalid()
        if event['reviewer_kind'] != 'human' or not isinstance(event['reviewer_id'], str) or not IDENTIFIER.fullmatch(event['reviewer_id']):
            invalid()
        role, identity = event['role'], event['reviewer_id']
        if role in reviewers and reviewers[role] != identity:
            invalid()
        if any(r != role and user == identity for r, user in reviewers.items()):
            invalid()
        reviewers[role] = identity
        if event['queue_sha256'] != manifest['queue_sha256'] or event['policy_sha256'] != manifest['policy_sha256']:
            invalid()
        try:
            timestamp = datetime.fromisoformat(event['reviewed_at'].replace('Z', '+00:00'))
        except (ValueError, TypeError, AttributeError):
            invalid()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            invalid()
        if event['verdict'] not in VERDICTS or not isinstance(event['reason'], str) or not 1 <= len(event['reason']) <= 2000 or '\0' in event['reason']:
            invalid()
        surfaces = event['accepted_surfaces']
        if (not isinstance(surfaces, list) or len(surfaces) > 32 or
                any(not isinstance(s, str) or not 1 <= len(s) <= 256 or '\0' in s for s in surfaces)):
            invalid()
        if surfaces != sorted(set(surfaces)) or any(s not in queue[event['case_id']]['candidate_surfaces'] for s in surfaces):
            invalid()
        verdict = event['verdict']
        if verdict == 'unique_correct' and surfaces != [bindings[event['case_id']]['old_gold_surface']]:
            invalid()
        if verdict == 'orthographic_equivalent' and (len(surfaces) < 2 or bindings[event['case_id']]['old_gold_surface'] not in surfaces):
            invalid()
        if verdict in ('context_insufficient', 'unresolved', 'extraction_noise', 'wrong_reading', 'wrong_segmentation') and surfaces:
            invalid()
        if verdict == 'wrong_gold_surface' and (len(surfaces) != 1 or bindings[event['case_id']]['old_gold_surface'] in surfaces):
            invalid()
        key = (event['case_id'], role)
        previous = latest.get(key)
        if event['previous_event_sha256'] != (canonical_json_hash(previous) if previous else None):
            invalid()
        if previous and timestamp < datetime.fromisoformat(previous['reviewed_at'].replace('Z', '+00:00')):
            invalid()
        if role != 'C':
            if event['basis_sha256'] != []:
                invalid()
        else:
            a, b = (latest.get((event['case_id'], r)) for r in ('A', 'B'))
            if not a or not b or event['basis_sha256'] != [canonical_json_hash(a), canonical_json_hash(b)]:
                invalid()
        latest[key] = event
    counts = Counter()
    proposals, disputed = [], []
    agreement = dual = 0
    for case_id in sorted(queue):
        a, b, c = (latest.get((case_id, r)) for r in ('A', 'B', 'C'))
        if not a or not b:
            counts['awaiting_dual_review'] += 1
            continue
        dual += 1
        equal = (a['verdict'], a['accepted_surfaces']) == (b['verdict'], b['accepted_surfaces'])
        agreement += equal
        if equal and a['verdict'] != 'unresolved':
            final = a
            basis = [canonical_json_hash(a), canonical_json_hash(b)]
        elif c and c['basis_sha256'] == [canonical_json_hash(a), canonical_json_hash(b)] and c['verdict'] != 'unresolved':
            final, basis = c, [canonical_json_hash(a), canonical_json_hash(b), canonical_json_hash(c)]
        else:
            counts['awaiting_adjudication'] += 1
            disputed.append({'case': queue[case_id], 'review_a': a, 'review_b': b})
            continue
        counts[final['verdict']] += 1
        proposals.append({'kind': 'pilot_proposal_not_applied', 'case_id': case_id,
                          **bindings[case_id], 'policy_sha256': manifest['policy_sha256'],
                          'queue_sha256': manifest['queue_sha256'], 'verdict': final['verdict'],
                          'proposed_accepted_surfaces': final['accepted_surfaces'],
                          'review_evidence_sha256': basis})
    pending = counts['awaiting_dual_review'] + counts['awaiting_adjudication']
    status = 'pilot_complete_no_gate' if not pending else ('awaiting_dual_review' if counts['awaiting_dual_review'] else 'awaiting_adjudication')
    report = {'schema_version': 1, 'kind': 'gold_operations_pilot_status', 'status': status,
              'queue_sha256': manifest['queue_sha256'], 'policy_sha256': manifest['policy_sha256'],
              'events_sha256': canonical_json_hash(events), 'event_count': len(events),
              'selected': len(queue), 'dual_reviewed': dual, 'agreement_count': agreement,
              'agreement_rate': agreement / dual if dual else None, 'pending': pending,
              'finalized': len(proposals), 'counts': dict(sorted(counts.items())),
              'gate_a_human_audit_pass': False, 'gate_a_owner_authorized_audit_pass': False,
              'final_holdout_valid_count': 0, 'independent_test': False,
              'canonical_labels_changed': False, 'raw_text_in_report': False,
              'raw_stable_ids_in_report': False}
    return report, proposals, disputed


def verify_history_extension(previous: Path, manifest: dict, events: list[dict]) -> str:
    """Bind a subsequent round to the entire immutable earlier event sequence."""
    report_path, events_path = previous / 'report.json', previous / 'events.jsonl'
    if report_path.stat().st_size > MAX_EVENT_BYTES or events_path.stat().st_size > MAX_EVENT_BYTES:
        raise ValueError('previous round exceeds bound')
    report = json.loads(report_path.read_bytes())
    old = [json.loads(line) for line in events_path.read_bytes().splitlines()]
    if (report['queue_sha256'] != manifest['queue_sha256'] or
            report['policy_sha256'] != manifest['policy_sha256'] or
            canonical_json_hash(old) != report['events_sha256'] or
            len(old) > len(events) or events[:len(old)] != old):
        raise ValueError('previous round was changed or truncated')
    return canonical_json_hash(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    build = subs.add_parser('prepare')
    build.add_argument('--source', type=Path, required=True)
    build.add_argument('--source-sha256', required=True)
    build.add_argument('--policy', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    check = subs.add_parser('reconcile')
    check.add_argument('--packet', type=Path, required=True)
    check.add_argument('--events', type=Path, required=True)
    check.add_argument('--output', type=Path, required=True)
    check.add_argument('--previous-round', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            rows, source = read_projection(args.source, args.source_sha256)
            _publish(args.output, prepare(rows, source, args.policy.read_bytes()))
        else:
            manifest, queue, bindings = load_packet(args.packet)
            if args.events.stat().st_size > MAX_EVENT_BYTES:
                raise ValueError('event file exceeds byte bound')
            events = [json.loads(line) for line in args.events.read_bytes().splitlines()]
            report, proposals, disputed = reconcile(manifest, queue, bindings, events)
            report['previous_round_report_sha256'] = (
                verify_history_extension(args.previous_round, manifest, events)
                if args.previous_round else None)
            _publish(args.output, {'report.json': _blob(report),
                                  'events.jsonl': canonical_jsonl_bytes(events),
                                  'proposals-not-applied.jsonl': canonical_jsonl_bytes(proposals),
                                  'adjudication.jsonl': canonical_jsonl_bytes(disputed)})
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f'pilot failed: {type(error).__name__}; no result authorized\n')


if __name__ == '__main__':
    main()
