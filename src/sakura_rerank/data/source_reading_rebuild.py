"""Append-only reconstruction of exact original-annotation reading conflicts.

This changes a derived research example, never its parent or the source text.
New IDs preserve source/component ancestry and confer no fitting/Gold status.
"""
from .contracts import canonical_json_hash, text_sha256
from .source_reading_gate import assess

POLICY = dict(name='exact-original-reading-rebuild',version=1,minimum_reading_characters=2,
              maximum_reading_characters=32,mapping='fullwidth_katakana_to_hiragana_only',
              target_and_context='unchanged',training_eligible=False,independent_gold_eligible=False)


def rebuild(row,source,paragraph,parent_decision,*,parent_dictionary_only=False):
    """Require the actual parent gate decision; rebuild only its exact conflict."""
    decision=assess(row,source,paragraph,allow_dictionary_only=parent_dictionary_only)
    if (parent_decision!=decision or decision['terminal']!='pending_reading_conflict'
            or row['corpus']!='aozora' or source['origin_kind']!='frozen_unique_dictionary'):
        raise ValueError('reading_rebuild_exact_parent_conflict_required')
    spans=[s for s in paragraph['spans'] if s['start']==source['start'] and s['end']==source['end']]
    if len(spans)!=1:
        raise ValueError('reading_rebuild_exact_annotation_required')
    original=spans[0]['reading']
    reading=''.join(chr(ord(c)-0x60) if 0x30A1<=ord(c)<=0x30F6 else c for c in original)
    if reading==row['reading']:
        raise ValueError('reading_rebuild_reading_unchanged')
    base=dict(kind='source_annotation_rebuild_weak_supervision',version=1,policy_sha256=canonical_json_hash(POLICY),
        parent_input_sha256=canonical_json_hash(row),parent_source_sha256=canonical_json_hash(source),
        parent_original_row_sha256=source['original_row_sha256'],parent_decision_sha256=canonical_json_hash(parent_decision),
        parent_component_sha256=canonical_json_hash(row['component_id']),original_annotation_reading_sha256=text_sha256(original),
        parent_reading_sha256=text_sha256(row['reading']),rebuilt_reading_sha256=text_sha256(reading),
        original_annotation_characters=len(original),rebuilt_reading_characters=len(reading),
        training_eligible=False,independent_gold_eligible=False,independent_evaluation_eligible=False)
    if not POLICY['minimum_reading_characters']<=len(reading)<=POLICY['maximum_reading_characters']:
        lineage=dict(base,status='pending_rebuilt_reading_bounds',rebuilt_input_sha256=None)
        return dict(status=lineage['status'],lineage=lineage,lineage_sha256=canonical_json_hash(lineage),input=None,source=None)
    identity='reading-rebuild-'+canonical_json_hash(base)
    child=dict(row,stable_id=identity,reading=reading,candidate_request_id='growth-reading-'+canonical_json_hash(reading))
    lineage=dict(base,status='rebuilt_source_ready',rebuilt_input_sha256=canonical_json_hash(child))
    digest=canonical_json_hash(lineage)
    child_source=dict(source,origin_kind='original_ruby',original_row_sha256=digest)
    checked=assess(child,child_source,paragraph)
    if checked['terminal']!='ready_original_annotation':
        raise ValueError('reading_rebuild_child_not_source_consistent')
    return dict(status=lineage['status'],lineage=lineage,lineage_sha256=digest,input=child,source=child_source)
