"""Read-only, text-free diagnostics of frozen train/dev converter snapshots.

The reader authenticates the complete source but discards holdout lines before
JSON parsing. Its projection is local-only; only audit() returns public counts.
No model predictions, split reassignment, or label application is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash, validate_record

MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MAX_ROWS = 100_000


def read_projection(path: Path, expected_sha256: str) -> tuple[list[dict], dict]:
    """Return validated train/dev projections and aggregate source evidence.

    Each local projection owns original provenance, original gold and shuffled-
    presentation inputs. It must never be published as an aggregate report.
    Hash/bounds/schema failure publishes nothing; errors never contain text.
    """
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('source SHA-256 must be lowercase hex')
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('source exceeds byte bound')
    digest = hashlib.sha256()
    rows, ids = [], set()
    skipped = total = size = 0
    with path.open('rb') as source:
        while line := source.readline(MAX_LINE_BYTES + 1):
            size += len(line)
            total += 1
            if len(line) > MAX_LINE_BYTES or size > MAX_SOURCE_BYTES or total > MAX_ROWS:
                raise ValueError('source exceeds line/row/byte bound')
            digest.update(line)
            if b',"split":"final-holdout",' in line:
                skipped += 1
                continue
            try:
                record = validate_record(json.loads(line))
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError(f'source row {total}: invalid contract') from error
            if record['split'] not in ('train', 'dev'):
                raise ValueError('source requires canonical holdout markers')
            if record['is_fixture'] or not record['training_eligible']:
                raise ValueError('source must contain eligible non-fixture rows')
            if record['stable_id'] in ids:
                raise ValueError('duplicate source identity')
            ids.add(record['stable_id'])
            candidates = record['candidate_snapshots']['training_top32']['candidates']
            top6 = record['candidate_snapshots']['production_top6']['candidates']
            text_input = [record['session']['left_context'], record['reading'],
                          [c['surface'] for c in top6]]
            # Superset of current feature inputs, not a claim of tensor equality.
            feature_input = [text_input, [{k: c[k] for k in
                             ('rank', 'local_cost', 'source_category', 'segments')}
                             for c in top6]]
            rows.append({
                'stable_id': record['stable_id'], 'split': record['split'],
                'source': record['source'], 'converter_provenance': record['converter_provenance'],
                'input_key': canonical_json_hash(text_input),
                'feature_input_key': canonical_json_hash(feature_input),
                'left_context': record['session']['left_context'], 'reading': record['reading'],
                'gold_surface': record['gold_surface'], 'gold_index': record['gold_index'],
                'gold_segments': candidates[record['gold_index']]['segments'],
                'candidate_surfaces': [c['surface'] for c in candidates],
                'top6_count': len(top6),
                'row_sha256': hashlib.sha256(line).hexdigest(),
            })
    if digest.hexdigest() != expected_sha256:
        raise ValueError('source SHA-256 mismatch')
    if not rows:
        raise ValueError('source has no train/dev rows')
    return rows, {'sha256': expected_sha256, 'bytes': size, 'source_rows': total,
                  'train_dev_rows': len(rows), 'holdout_rows_skipped_before_json': skipped}


def _groups(rows: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        value = row.get(field) if field in ('input_key', 'feature_input_key') else row['source'][field]
        if value is not None:
            groups[value].append(row)
    return dict(groups)


def audit(rows: list[dict], source: dict) -> dict:
    """Aggregate exact overlap and distribution; never emit row identifiers."""
    profiles = {}
    for split in ('train', 'dev'):
        subset = [r for r in rows if r['split'] == split]
        counts = Counter(n=len(subset))
        for row in subset:
            for k in (1, 5, 6, 10, 32):
                counts[f'top{k}'] += 0 <= row['gold_index'] < k
            counts['empty_context'] += not row['left_context']
            counts['context_at64'] += len(row['left_context']) == 64
            counts['reading_le9'] += len(row['reading']) <= 9
            counts['gold_single_segment'] += len(row['gold_segments']) == 1
        text_groups = _groups(subset, 'input_key')
        counts['repeated_input_groups'] = sum(len(g) > 1 for g in text_groups.values())
        counts['excess_input_rows'] = sum(len(g) - 1 for g in text_groups.values())
        counts['conflicting_gold_groups'] = sum(len({r['gold_surface'] for r in g}) > 1
                                               for g in text_groups.values())
        profiles[split] = dict(counts)
    overlaps = {}
    for field in ('article_id', 'paragraph_hash', 'sentence_hash', 'template_cluster_id',
                  'input_key', 'feature_input_key'):
        cross = [g for g in _groups(rows, field).values() if len({r['split'] for r in g}) > 1]
        overlaps[field] = {
            'groups': len(cross),
            'train_rows': sum(r['split'] == 'train' for g in cross for r in g),
            'dev_rows': sum(r['split'] == 'dev' for g in cross for r in g),
            'gold_conflict_groups': sum(len({r['gold_surface'] for r in g}) > 1 for g in cross),
        }
    pins = {canonical_json_hash(r['converter_provenance']) for r in rows}
    if len(pins) != 1:
        raise ValueError('mixed converter provenance')
    return {'schema_version': 1, 'report_kind': 'frozen_train_dev_diagnostics',
            'source': source, 'converter_provenance': rows[0]['converter_provenance'],
            'profiles': profiles, 'cross_split_exact_overlap': overlaps,
            'near_duplicate_check': 'not_recomputed_use_separately_bound_split_report',
            'population': 'oracle-selected eligible Tier A train/dev, not general converter traffic',
            'data_changed': False, 'model_scores_read': False, 'raw_text_in_report': False,
            'raw_stable_ids_in_report': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, source = read_projection(args.source, args.source_sha256)
        result = audit(rows, source)
        # Exclusive output creation; reports never replace an earlier run.
        output = args.output.open('xb')
        try:
            with output:
                output.write(canonical_json_bytes(result) + b'\n')
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
    except (ValueError, OSError) as error:
        parser.exit(2, f'diagnostic failed: {type(error).__name__}\n')


if __name__ == '__main__':
    main()
