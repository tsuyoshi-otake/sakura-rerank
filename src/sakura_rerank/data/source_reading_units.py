"""Bounded original-source extent hypotheses; never inferred IME input units.

Native diagnostics have their existing 1..128 reading / 1..256 surface bounds.
The stricter preparation bounds remain separate and confer no admission here.
"""
import unicodedata

from .contracts import canonical_json_hash,text_sha256
from .source_reading_rebuild import rebuild
from .tatoeba_input_units import kana_projection

VIEWS=('original_ruby','literal_suffix','supported_run')
POLICY=dict(version=1,views=VIEWS,reading_projection='fullwidth_katakana_to_hiragana_only',
    native_reading_min=1,native_reading_max=128,native_target_min=1,native_target_max=256,
    preparation_reading_min=2,preparation_reading_max=32,preparation_target_max=32,preparation_prefix_min=8,
    context_max=64,clipping=False,training_eligible=False,independent_gold_eligible=False)


def _units(paragraph):
    text=paragraph['text'];result=[];position=0
    def literal(start,end):
        for i in range(start,end):
            value=kana_projection(text[i])
            origin=('literal_kana' if value is not None else 'literal_boundary'
                if unicodedata.category(text[i])[0] in 'PSZ' or text[i].isspace() else 'unannotated_reading')
            result.append(dict(start=i,end=i+1,reading=value,origin=origin))
    for span in paragraph['spans']:
        literal(position,span['start'])
        value=kana_projection(span['reading']) if 1<=len(span['reading'])<=32 else None
        valid=(span['kind']!='unresolved_base' and span['start']<span['end'] and value is not None
            and 1<=len(value)<=32 and span['reading'] not in ('ママ','まま'))
        result.append(dict(start=span['start'],end=span['end'],reading=value if valid else None,
            origin='original_ruby' if valid else 'unresolved_annotation'))
        position=span['end']
    literal(position,len(text))
    return result


def build(row,source,paragraph,parent_decision,*,parent_dictionary_only=False):
    """Authenticate the exact conflicting parent before deriving all three views."""
    parent=rebuild(row,source,paragraph,parent_decision,parent_dictionary_only=parent_dictionary_only)
    units=_units(paragraph)
    anchors=[i for i,u in enumerate(units) if (u['start'],u['end'])==(source['start'],source['end']) and u['origin']=='original_ruby']
    if len(anchors)!=1:raise ValueError('source_extent_anchor_required')
    anchor=anchors[0];suffix=anchor+1
    while suffix<len(units) and units[suffix]['origin']=='literal_kana':suffix+=1
    left,right=anchor,anchor+1
    while left and units[left-1]['reading'] is not None:left-=1
    while right<len(units) and units[right]['reading'] is not None:right+=1
    ranges=dict(original_ruby=(anchor,anchor+1),literal_suffix=(anchor,suffix),supported_run=(left,right))
    views={};text=paragraph['text']
    for name in VIEWS:
        low,high=ranges[name];parts=units[low:high];start,end=parts[0]['start'],parts[-1]['end']
        reading=''.join(u['reading'] for u in parts);target=text[start:end];prefix=text[max(0,start-64):start]
        if (any(a['end']!=b['start'] for a,b in zip(parts,parts[1:]))
                or not start<=source['start']<source['end']<=end):raise ValueError('source_extent_continuity')
        expanded=(start,end)!=(source['start'],source['end']);pending=[]
        if not 1<=len(reading)<=128:pending.append('native_reading_bound')
        if not 1<=len(target)<=256:pending.append('native_surface_bound')
        if expanded and paragraph['flags']['orphan_marker']:pending.append('annotation_parse_uncertainty')
        status='pending_source_extent' if pending else 'source_extent_diagnostic_ready'
        preparation=dict(reading=2<=len(reading)<=32,target=1<=len(target)<=32,prefix=8<=len(prefix)<=64)
        lineage=dict(kind='original_source_extent_hypothesis',version=1,view=name,policy_sha256=canonical_json_hash(POLICY),
            parent_original_row_sha256=source['original_row_sha256'],parent_rebuild_sha256=canonical_json_hash(parent),
            parent_input_sha256=canonical_json_hash(row),parent_source_sha256=canonical_json_hash(source),
            parent_component_sha256=canonical_json_hash(row['component_id']),source_evidence_sha256=canonical_json_hash([source,paragraph]),
            start=start,end=end,reading_sha256=text_sha256(reading),target_sha256=text_sha256(target),prefix_sha256=text_sha256(prefix),
            parts_sha256=canonical_json_hash(parts),status=status,pending_reasons=pending,training_eligible=False,
            independent_gold_eligible=False,independent_evaluation_eligible=False)
        child=None
        if not pending:
            child=dict(stable_id='source-extent-'+canonical_json_hash(lineage),component_id=row['component_id'],corpus=row['corpus'],
                left_context=prefix,reading=reading,target=target,candidate_request_id='growth-reading-'+canonical_json_hash(reading))
        lineage['candidate_input_sha256']=canonical_json_hash(child) if child is not None else None
        views[name]=dict(status=status,lineage=lineage,lineage_sha256=canonical_json_hash(lineage),input=child,
            hypothesis=dict(start=start,end=end,reading=reading,target=target,left_context=prefix,parts=parts),
            expanded=expanded,added_left_characters=source['start']-start,added_right_characters=end-source['end'],
            left_stop='source_start' if low==0 else units[low-1]['origin'],
            right_stop='source_end' if high==len(units) else units[high]['origin'],
            preparation_bounds=preparation,within_preparation_bounds=all(preparation.values()),
            grammatical_boundary_verified=False,ime_gold=False)
    return dict(parent_original_row_sha256=source['original_row_sha256'],parent_rebuild_sha256=canonical_json_hash(parent),views=views)
