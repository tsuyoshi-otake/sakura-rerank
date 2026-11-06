"""Prospective metadata reservation and exact continuous-source consumption.

This boundary emits research hypotheses only. Administrative ownership and
transcription editing do not establish authorship, pronunciation or IME intent.
The selection function accepts metadata only and consumes the complete stream.
"""
from __future__ import annotations

import heapq
import re

from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .tatoeba_input_units import build_source_units
from .tatoeba_source import audit_pair

POLICY_VERSION = 'tatoeba-continuous-source-v1'
PURPOSE = 'prospective_source_reconstruction_only'
MAX_POPULATION = 500_000
MAX_RESERVATION = 10_000


def validate_metadata(row: dict) -> None:
    """No source text, readings, native scores or semantic filters are permitted."""
    if not isinstance(row, dict) or set(row) != {'sentence_id', 'sentence', 'transcription'}:
        raise ValueError('consumption_metadata_fields')
    key = row['sentence_id']
    if type(key) is not int or not 0 < key < 2**63:
        raise ValueError('consumption_metadata_id')
    for kind, extra in (('sentence', {'owner_token'}),
                        ('transcription', {'editor_token', 'stratum'})):
        item = row[kind]
        if not isinstance(item, dict) or set(item) != {'line', 'raw_line_sha256'} | extra:
            raise ValueError('consumption_metadata_fields')
        if type(item['line']) is not int or not 1 <= item['line'] <= MAX_POPULATION:
            raise ValueError('consumption_metadata_line')
        for name in ('raw_line_sha256', 'owner_token' if kind == 'sentence' else 'editor_token'):
            value = item[name]
            if value is None and name != 'raw_line_sha256':
                continue
            if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('consumption_metadata_hash')
    trans = row['transcription']
    if trans['stratum'] != ('named_editor' if trans['editor_token'] is not None else 'no_editor'):
        raise ValueError('consumption_editor_provenance')


def reserve_metadata_slots(rows, previous_ids, *, count: int, seed: str) -> list[dict]:
    """O(N log count) fixed-ID selection; malformed/excluded inputs never refill slots."""
    if type(count) is not int or not 1 <= count <= MAX_RESERVATION:
        raise ValueError('consumption_reservation_bound')
    if not isinstance(seed, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,128}', seed):
        raise ValueError('consumption_seed_bound')
    previous = set(previous_ids)
    if len(previous) > MAX_POPULATION or any(type(i) is not int or not 0 < i < 2**63 for i in previous):
        raise ValueError('consumption_history_ids')
    seen = set()

    def eligible():
        for row in rows:
            validate_metadata(row)
            key = row['sentence_id']
            if key in seen or len(seen) >= MAX_POPULATION:
                raise ValueError('consumption_population_identity_or_bound')
            seen.add(key)
            if key not in previous:
                yield canonical_json_hash([POLICY_VERSION, seed, key]), key, row

    chosen = heapq.nsmallest(count, eligible(), key=lambda item: (item[0], item[1]))
    if not previous <= seen:
        raise ValueError('consumption_exposure_history_missing')
    if len(chosen) != count:
        raise ValueError('consumption_capacity_insufficient')
    return [item[2] for item in chosen]


def consume_slot(metadata: dict, sentence: str | None, transcription: str | None,
                 *, snapshot: str, slot: int) -> dict:
    """Preserve one terminal slot and all original positions; never certify a label."""
    validate_metadata(metadata)
    if not isinstance(snapshot, str) or not re.fullmatch('[a-z0-9-]{1,128}', snapshot):
        raise ValueError('consumption_snapshot_name')
    if type(slot) is not int or not 0 <= slot < MAX_RESERVATION:
        raise ValueError('consumption_slot_bound')
    identity = canonical_json_hash([POLICY_VERSION, snapshot, metadata['sentence_id']])
    owner = metadata['sentence']['owner_token']
    result = dict(slot=slot, sentence_id=metadata['sentence_id'], stable_id='tatoeba-consumed-'+identity,
                  policy=POLICY_VERSION, purpose=PURPOSE, stratum=metadata['transcription']['stratum'],
                  status='invalid_source_fields', source_coverage=None, inputs=[], view=None,
                  provenance=dict(administrative_owner_token=owner,
                                  transcription_editor_token=metadata['transcription']['editor_token'],
                                  original_author_token=None, translation_lineage=None,
                                  imported_human_verdicts=0, independent_reading_verified=False),
                  source_exact=False, ime_gold=False, calibration_admitted=False,
                  final_test=False, session_context_available=False)
    if not isinstance(sentence, str) or not sentence or len(sentence) > 10_000:
        return result
    signature = sentence_shingle_hashes(sentence)
    if len(signature) > 1024:
        result['status'] = 'source_signature_bound'
        return result
    source = dict(article_id='tatoeba:'+str(metadata['sentence_id']),
                  paragraph_hash=text_sha256(sentence), sentence_hash=text_sha256(sentence),
                  sentence_shingle_hashes=signature,
                  template_cluster_id=None if owner is None else 'tatoeba-owner:'+owner)
    # The legacy graph's conservative owner relation is retained, not called authorship.
    result['source_coverage'] = dict(stable_id='tatoeba-consumption-source-'+identity,
                                     population='source_coverage', source=source)
    if not isinstance(transcription, str):
        return result
    projected = build_source_units(sentence, transcription)
    alignment, _ = audit_pair(sentence, transcription)
    view = projected['views']['literal_runs']
    result.update(status=projected['status'], source_exact=alignment['source_exact'],
                  view=view, projected_units=projected.get('projected_units', 0))
    if view['status'] != 'ready':
        if projected['status'] == 'source_projected_not_certified':
            result['status'] = view['status']
        return result
    if len(signature) > 512:
        result['status'] = 'input_signature_bound'
        result['view'] = dict(status='input_signature_bound', parts=[])
        return result
    if ''.join(p['target'] if p['kind'] == 'convert' else p['text'] for p in view['parts']) != sentence:
        raise ValueError('consumption_source_roundtrip')
    inputs = []
    for index, part in enumerate(view['parts']):
        original = sentence[part['start']:part['end']]
        if original != part.get('target', part.get('text')):
            raise ValueError('consumption_source_position')
        if part['kind'] != 'convert':
            continue
        inputs.append(dict(stable_id='tatoeba-consumption-input-'+canonical_json_hash([identity, index]),
                           population='evaluation', source=source,
                           input_hash=canonical_json_hash(['', part['reading']]),
                           left_context='', context_kind='no_observed_session_context',
                           reading=part['reading'], target=part['target'], request_id=part['request_id'],
                           start=part['start'], end=part['end'], part_index=index))
    result.update(status='ready_source_hypothesis', inputs=inputs)
    return result
