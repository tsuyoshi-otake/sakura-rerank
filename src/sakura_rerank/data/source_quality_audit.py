"""Counterfactual source-quality audit of immutable train rows; never train/test modification."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_jsonl_bytes, validate_record
from .gold_pilot import _publish
from .source_quality import QUALITY_POLICY, QUALITY_REASONS, quality_flags

MAX_BYTES = 512 * 1024 * 1024
MAX_LINE = 256 * 1024
MAX_ROWS = 100000


def audit_train(path: Path, expected_sha: str) -> tuple[dict, bytes]:
    """Authenticate all source bytes, parse only train, retain the original denominator.

    The returned evidence has stable IDs and belongs in ignored local storage.
    It is a routing ledger, not an applied label overlay or a new dataset split.
    """
    if (not re.fullmatch('[0-9a-f]{64}', expected_sha) or path.is_symlink()
            or not path.is_file() or path.stat().st_size > MAX_BYTES):
        raise ValueError('source hash or file bound invalid')
    digest, size, total = hashlib.sha256(), 0, 0
    excluded, reasons, combinations = Counter(), Counter(), Counter()
    ids, evidence = set(), []
    with path.open('rb') as source:
        while line := source.readline(MAX_LINE + 1):
            total += 1
            size += len(line)
            if len(line) > MAX_LINE or size > MAX_BYTES or total > MAX_ROWS:
                raise ValueError('source line/byte/row bound exceeded')
            digest.update(line)
            if b',"split":"final-holdout",' in line:
                excluded['final-holdout'] += 1
                continue
            if b',"split":"dev",' in line:
                excluded['dev'] += 1
                continue
            if b',"split":"train",' not in line:
                raise ValueError('canonical split marker required')
            row = validate_record(json.loads(line))
            if row['split'] != 'train' or row['is_fixture'] or not row['training_eligible']:
                raise ValueError('eligible non-fixture train record required')
            stable = row['stable_id']
            if stable in ids:
                raise ValueError('duplicate training identity')
            ids.add(stable)
            flags = quality_flags(row['session']['left_context'], row['gold_surface'])
            reasons.update(flags)
            combinations[flags] += 1
            evidence.append(dict(stable_id=stable, source_row_sha256=hashlib.sha256(line).hexdigest(),
                                 reasons=list(flags), proposed_route='quarantine' if flags else 'retain'))
    if digest.hexdigest() != expected_sha or not evidence:
        raise ValueError('source hash mismatch or no training rows')
    ledger = canonical_jsonl_bytes(evidence)
    retained = combinations[()]
    report = dict(
        schema_version=1, kind='source_quality_train_counterfactual', policy=QUALITY_POLICY,
        source_sha256=expected_sha, source_bytes=size, source_rows=total,
        dev_skipped_before_json=excluded['dev'], holdout_skipped_before_json=excluded['final-holdout'],
        original_train_denominator=len(evidence), proposed_retained=retained,
        proposed_quarantined=len(evidence)-retained,
        reasons={name: reasons[name] for name in QUALITY_REASONS},
        combinations=[dict(reasons=list(k), count=v) for k, v in sorted(combinations.items())],
        evidence_sha256=hashlib.sha256(ledger).hexdigest(), evidence_rows=len(evidence),
        scope='exact bounded left64 plus target on historical eligible train; not full source paragraphs',
        canonical_labels_changed=False, dataset_modified=False, model_scores_read=False,
        dev_parsed=False, holdout_parsed=False, gold_certified=False, accuracy_estimated=False,
        gate_a_pass=False, raw_text_in_report=False, raw_stable_ids_in_report=False,
    )
    return report, ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        report, ledger = audit_train(args.source, args.source_sha256)
        _publish(args.output_directory, {'report.json': canonical_json_bytes(report)+b'\n',
                                         'evidence.jsonl': ledger})
    except (OSError, ValueError, TypeError, KeyError):
        parser.exit(2, 'Source-quality audit failed; no result authorized\n')
    print(canonical_json_bytes(report).decode('utf-8'))


if __name__ == '__main__':
    main()
