"""Exact pre-fusion path capture binding; never derive origins from evidence tags."""
from __future__ import annotations
import hashlib

from . import native_snapshot as native
from .data.contracts import canonical_json_bytes

CONTRACT='pre_fusion_converter_path_v1'
MAX_EDGES=64
CATEGORIES=frozenset({'system_dictionary','user_dictionary','reading_fallback','katakana_fallback',
                      'passthrough_fallback','generated_literal'})
PATH_FIELDS={'kind','reading_hex','surface_hex','segments'}
EDGE_FIELDS={'reading_start','reading_end','text_start','text_end','left_id','right_id','flags','source_category'}
CANDIDATE_FIELDS={'rank','surface','local_cost','evidence_tag','native_fingerprint','path','display_segment_count'}


def validate_path(path,reading,surface,display_count):
    native.fields(path,PATH_FIELDS)
    native.require(path['kind'] in ('viterbi_materialization','synthetic_materialization'),'unknown native path origin')
    native.require(native.text_from_hex(path['reading_hex'])==reading
                   and native.text_from_hex(path['surface_hex'])==surface,'path reading or surface changed after materialization')
    segments=path['segments']
    native.require(isinstance(segments,list) and 1<=len(segments)<=MAX_EDGES,'raw path count outside bound')
    native.integer(display_count,1,len(segments))
    raw_reading,raw_surface=reading.encode(),surface.encode()
    reading_end=text_end=0
    for segment in segments:
        native.fields(segment,EDGE_FIELDS)
        for key in ('reading_start','reading_end','text_start','text_end'):native.integer(segment[key],0,native.MAX_TEXT_BYTES)
        for key in ('left_id','right_id','flags'):native.integer(segment[key],0,65535)
        native.require(isinstance(segment['source_category'],str) and segment['source_category'] in CATEGORIES,'unknown raw path source')
        native.require(segment['reading_start']==reading_end and reading_end<segment['reading_end']<=len(raw_reading)
                       and segment['text_start']==text_end and text_end<segment['text_end']<=len(raw_surface),
                       'raw path does not cover contiguous input')
        try:
            raw_reading[reading_end:segment['reading_end']].decode('utf-8',errors='strict')
            raw_surface[text_end:segment['text_end']].decode('utf-8',errors='strict')
        except UnicodeError:
            raise native.NativeSnapshotError('raw path boundary splits UTF-8') from None
        reading_end,text_end=segment['reading_end'],segment['text_end']
    native.require(reading_end==len(raw_reading) and text_end==len(raw_surface),'raw path is incomplete')
    if path['kind']=='synthetic_materialization':
        native.require(all(s['source_category'] in {'reading_fallback','generated_literal'} for s in segments),
                       'synthetic constructor claims dictionary provenance')
    return path


def base_event(event):
    """Remove only the declared extension; native identity remains authoritative."""
    native.require(isinstance(event,dict) and type(event.get('path_version')) is int and event['path_version']==1,
                   'native path capture version differs')
    stripped={k:v for k,v in event.items() if k!='path_version'}
    captures=event.get('captures')
    native.require(isinstance(captures,list) and len(captures)<=1,'ambiguous path capture')
    stripped['captures']=[]
    for frame in captures:
        native.require(isinstance(frame,dict) and isinstance(frame.get('candidates'),list)
                       and 1<=len(frame['candidates'])<=native.MAX_CANDIDATES,'path candidates missing or outside bound')
        rows=[]
        for candidate in frame['candidates']:
            native.fields(candidate,{'surface_hex','cost','evidence','fingerprint','path','display_segment_count'})
            rows.append({k:v for k,v in candidate.items() if k not in ('path','display_segment_count')})
        stripped['captures'].append(dict(frame,candidates=rows))
    return stripped


def inspect_event(event):
    checked=native.inspect_event(base_event(event))
    snapshot=checked['snapshot']
    if snapshot is None:return checked
    for candidate,captured in zip(snapshot['candidates'],event['captures'][0]['candidates'],strict=True):
        validate_path(captured['path'],snapshot['reading'],candidate['surface'],captured['display_segment_count'])
        candidate.update(path=captured['path'],display_segment_count=captured['display_segment_count'])
    return checked


def validate_input(request):
    native.fields(request,{'reading','left_context','context_policy','candidates'})
    candidates=request['candidates']
    native.require(isinstance(candidates,list) and 1<=len(candidates)<=native.MAX_CANDIDATES,'native path population outside bound')
    for candidate in candidates:native.fields(candidate,CANDIDATE_FIELDS)
    plain=[{k:v for k,v in c.items() if k not in ('path','display_segment_count')} for c in candidates]
    native.validate_population_input(dict(request,candidates=plain))
    for candidate in candidates:validate_path(candidate['path'],request['reading'],candidate['surface'],candidate['display_segment_count'])
    return [dict(c) for c in candidates]


def bind_evaluation_case(row,commitment):
    native.require(hashlib.sha256(canonical_json_bytes(row['native_capture'])).hexdigest()==commitment,
                   'native path capture differs from frozen provenance')
    checked=inspect_event(row['native_capture']);snapshot=checked['snapshot']
    native.require(not checked['baseline_run'] and snapshot is not None,'native evaluation input lacks a conversion snapshot')
    validate_input(row['input'])
    native.require(canonical_json_bytes(row['input'])==canonical_json_bytes(native.population_input(snapshot)),
                   'native path input differs')
    native.require(canonical_json_bytes(native.validate_policy_facts(row['product_state'],len(snapshot['candidates'])))
                   ==canonical_json_bytes(snapshot['product_state']),'native path policy facts differ')
    receipt={'input_sha256':hashlib.sha256(canonical_json_bytes(row['input'])).hexdigest(),
             'policy_facts_sha256':hashlib.sha256(canonical_json_bytes(row['product_state'])).hexdigest(),
             'native_snapshot_sha256':hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest(),
             'purpose':'native_path_feature_binding','candidate_count':len(snapshot['candidates']),
             'candidate_contract':'native_full_population_v1','path_contract':CONTRACT,
             'legacy_feature_provenance_verified':True,'gold_certified':False,'final_evaluation_admitted':False}
    return receipt,tuple(snapshot['identity'])


def evaluation_policy(provenance_sha256):
    return dict(native.evaluation_policy(provenance_sha256,full_population=True),version=4,
                native_provenance='native_dispatch_path_capture_v1',path_contract=CONTRACT,
                research_segment_count='pre_fusion_path_edges',research_system_feature='all_edges_system_dictionary')


def verify_capture(plan_raw,result_raw,capture_raw,*,expected_plan_sha256,expected_result_sha256):
    native.require(len(plan_raw)<=2*1024*1024 and len(result_raw)<=1024*1024
                   and len(capture_raw)<=native.MAX_CAPTURE_BYTES,'native path artifact bound exceeded')
    native.require(hashlib.sha256(plan_raw).hexdigest()==expected_plan_sha256
                   and hashlib.sha256(result_raw).hexdigest()==expected_result_sha256,'native path artifact commitment differs')
    plan,result=native._document(plan_raw),native._document(result_raw)
    native.require(isinstance(plan,dict) and isinstance(result,dict),'path metadata objects required')
    native.require(plan.get('kind')=='native_state_probe_plan' and type(plan.get('version')) is int and plan['version']==3
                   and plan.get('path_contract')==CONTRACT and plan.get('source_head')==native.HEAD
                   and plan.get('synthetic_response_injection') is True,'native path producer differs')
    native.require(result.get('kind')=='native_state_probe_result' and type(result.get('version')) is int and result['version']==2
                   and result.get('status')=='passed' and result.get('plan_sha256')==expected_plan_sha256
                   and result.get('capture_sha256')==hashlib.sha256(capture_raw).hexdigest(),'native path result differs')
    for key in ('real_test','model_inference','gold_evidence','production_edits'):
        native.require(result.get(key) is False,'path diagnostic does not grant admission')
    lines=capture_raw.splitlines()
    native.require(0<len(lines)<=native.MAX_EVENTS,'path event population outside bound')
    values=[inspect_event(native._document(line)) for line in lines]
    return native.verify_event_population(values,plan,result)
