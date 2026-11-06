"""Authenticate and check research captures of the pinned native dispatcher.

This boundary preserves all native candidates and both scheduling/application
identities. It does not certify an independent Gold label, a production session,
legacy per-edge feature provenance, or permit a final evaluation by itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct

from .current_tiny import EVIDENCE_TAGS, HEAD, protected_choice, validate_policy_facts
from .data.contracts import canonical_json_bytes

MAX_CANDIDATES = 768
MAX_TEXT_BYTES = 1536
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 1024
OFFSET = 0xCBF29CE484222325
MASK = (1 << 64)-1


class NativeSnapshotError(ValueError):
    """Sanitized rejection, never includes captured text or record fragments."""


def require(value, reason):
    if not value:
        raise NativeSnapshotError(reason)


def fields(value, keys):
    require(isinstance(value, dict) and value.keys() == set(keys), 'native capture fields differ')


def integer(value, low=0, high=MASK):
    require(type(value) is int and low <= value <= high, 'native integer outside bound')
    return value


def text_from_hex(value):
    require(isinstance(value, str) and 2 <= len(value) <= MAX_TEXT_BYTES*2
            and all(c in '0123456789abcdef' for c in value), 'native text encoding outside bound')
    try:
        return bytes.fromhex(value).decode('utf-8', errors='strict')
    except (ValueError, UnicodeError):
        raise NativeSnapshotError('native text encoding invalid') from None


def fingerprint(raw, initial=OFFSET):
    result=initial
    for byte in raw:
        result=((result^byte)*0x100000001B3)&MASK
    return result


def candidate_fingerprint(surface, cost, evidence):
    return fingerprint(surface.encode('utf-8')+struct.pack('<qB', cost, evidence))


def candidate_set_fingerprint(values):
    return fingerprint(b''.join(struct.pack('<Q', value) for value in values))


def _candidate(value):
    fields(value, {'surface_hex','cost','evidence','fingerprint'})
    text=text_from_hex(value['surface_hex'])
    cost=integer(value['cost'], -(1<<63), (1<<63)-1)
    tag=integer(value['evidence'], 0, 255)
    require(tag in EVIDENCE_TAGS, 'unknown native evidence')
    fp=integer(value['fingerprint'])
    require(fp==candidate_fingerprint(text,cost,tag), 'native candidate fingerprint differs')
    return {'surface':text,'local_cost':cost,'evidence_tag':tag,'native_fingerprint':fp}


def inspect_event(event):
    fields(event, {'fixture','scenario','baseline_run','work','captures','terminal'})
    integer(event['fixture'], 0, MAX_EVENTS-1)
    require(isinstance(event['scenario'],str) and 1<=len(event['scenario'])<=32
            and set(event['scenario'])<=set('abcdefghijklmnopqrstuvwxyz_'), 'invalid scenario identity')
    require(type(event['baseline_run']) is bool, 'baseline control missing')
    require(event['terminal'] in {'None','Ready','Applied','LocalFallback','TimedOut'}, 'unknown native terminal')
    work=event['work']
    require(isinstance(work,dict) and type(work.get('scheduled')) is bool and type(work.get('built')) is bool,
            'native scheduling evidence missing')
    require(not work['built'] or work['scheduled'], 'native build without scheduling')
    scores=[]
    if not work['built']:
        fields(work, {'scheduled','built'})
    else:
        fields(work, {'scheduled','built','owner','session','generation','reading_hash','reading_bytes',
            'candidate_set','model_candidates','response_key','response_candidate_set','response_count',
            'response_fingerprints','response_score_bits','response_finite','response_ready','response_present'})
        for key in ('owner','session','generation','reading_hash','candidate_set','response_candidate_set'):
            integer(work[key])
        integer(work['reading_bytes'],1,MAX_TEXT_BYTES)
        require(isinstance(work['model_candidates'],list) and 2<=len(work['model_candidates'])<=6,
                'native model candidate count invalid')
        for row in work['model_candidates']:
            fields(row, {'surface_hex','cost','fingerprint'})
            text_from_hex(row['surface_hex'])
            integer(row['cost'], -(1<<63), (1<<63)-1)
            integer(row['fingerprint'])
        require(work['candidate_set']==candidate_set_fingerprint([c['fingerprint'] for c in work['model_candidates']]),
                'native work candidate set differs')
        require(isinstance(work['response_key'],list) and len(work['response_key'])==5, 'native response key malformed')
        for value in work['response_key']: integer(value)
        count=integer(work['response_count'],0,6)
        for key in ('response_fingerprints','response_score_bits'):
            require(isinstance(work[key],list) and len(work[key])==count, 'native response shape differs')
            for value in work[key]: integer(value,0,(1<<32)-1 if key=='response_score_bits' else MASK)
        for key in ('response_finite','response_ready','response_present'):
            require(type(work[key]) is bool,'native response boolean invalid')
        scores=[struct.unpack('<f',struct.pack('<I',value))[0] for value in work['response_score_bits']]
        require(work['response_finite']==all(math.isfinite(value) for value in scores), 'native finite flag differs')
    captures=event['captures']
    require(isinstance(captures,list) and len(captures)<=1, 'native capture coverage ambiguous')
    summary={'fixture':event['fixture'],'scenario':event['scenario'],'baseline_run':event['baseline_run'],
             'scheduled':work['scheduled'],'built':work['built'],'native_terminal':event['terminal']}
    if not captures:
        require(event['terminal']!='Applied','native applied without a candidate capture')
        return dict(summary,status='no_conversion_snapshot',snapshot=None)
    capture=captures[0]
    fields(capture, {'owner','session','generation','reading_hex','direct_count','baseline_index','selected_index',
                    'selection_calls','candidate_set','candidates'})
    for key in ('owner','session','generation','candidate_set'): integer(capture[key])
    reading=text_from_hex(capture['reading_hex'])
    require(isinstance(capture['candidates'],list) and 1<=len(capture['candidates'])<=MAX_CANDIDATES,
            'native candidate population outside bound')
    candidates=[_candidate(value) for value in capture['candidates']]
    direct=integer(capture['direct_count'],1,len(candidates))
    baseline=integer(capture['baseline_index'],0,direct-1)
    selected=integer(capture['selected_index'],0,direct-1)
    calls=integer(capture['selection_calls'],0,1)
    prefix=candidates[:min(6,direct)]
    fingerprints=[c['native_fingerprint'] for c in prefix]
    require(capture['candidate_set']==candidate_set_fingerprint(fingerprints), 'native dispatch candidate set differs')
    key=[capture['owner'],capture['session'],capture['generation'],fingerprint(reading.encode()),len(reading.encode())]
    request_matches=response_matches=False
    if work['built']:
        request_matches=([work[k] for k in ('owner','session','generation','reading_hash','reading_bytes')]==key
            and work['candidate_set']==capture['candidate_set'] and len(work['model_candidates'])==len(prefix)
            and all((text_from_hex(a['surface_hex']),a['cost'],a['fingerprint'])==
                    (b['surface'],b['local_cost'],b['native_fingerprint'])
                    for a,b in zip(work['model_candidates'],prefix,strict=False)))
        response_matches=(work['response_present'] and work['response_ready'] and work['response_key']==key
            and work['response_candidate_set']==capture['candidate_set'] and work['response_count']==len(prefix)
            and work['response_fingerprints']==fingerprints and work['response_finite'])
    choice=protected_choice(scores,[c['evidence_tag'] for c in prefix]) if calls and response_matches else None
    applied=choice is not None
    require(selected==(choice if applied else baseline),'native selection differs from captured identity/priority')
    require((event['terminal']=='Applied')==applied,'native application terminal differs')
    if event['baseline_run']:
        require(not work.get('response_present',False) and selected==baseline,'local control used a neural result')
    facts={'source_head':HEAD,'baseline_index':baseline,'direct_count':direct,
           'evidence_tags':[c['evidence_tag'] for c in candidates],
           'schedule_eligible':work['built'] and request_matches,'selection_allowed':bool(calls)}
    validate_policy_facts(facts,len(candidates))
    snapshot={'reading':reading,'candidates':candidates,'product_state':facts,
              'request_identity_matches':request_matches,'response_identity_matches':response_matches,
              'selected_index':selected,'identity':key,'candidate_set':capture['candidate_set']}
    return dict(summary,status='captured',snapshot=snapshot,applied=applied)


def _document(raw):
    def pairs(items):
        value={}
        for key,item in items:
            require(key not in value,'duplicate native JSON key')
            value[key]=item
        return value
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False,'nonfinite native JSON'))
    except (ValueError,UnicodeError,RecursionError):
        raise NativeSnapshotError('invalid native capture JSON') from None


def verify_capture(plan_raw,result_raw,capture_raw,*,expected_plan_sha256,expected_result_sha256):
    """The caller pins expected digests externally; supplied flags cannot enroll trust."""
    require(len(plan_raw)<=2*1024*1024 and len(result_raw)<=1024*1024
            and len(capture_raw)<=MAX_CAPTURE_BYTES,'native artifact byte bound exceeded')
    require(hashlib.sha256(plan_raw).hexdigest()==expected_plan_sha256
            and hashlib.sha256(result_raw).hexdigest()==expected_result_sha256,'native plan/result commitment differs')
    plan,result=_document(plan_raw),_document(result_raw)
    require(isinstance(plan,dict) and isinstance(result,dict),'native metadata objects required')
    require(plan.get('kind')=='native_state_probe_plan' and type(plan.get('version')) is int
            and plan['version']==2 and plan.get('source_head')==HEAD
            and plan.get('synthetic_response_injection') is True, 'unsupported native producer contract')
    require(result.get('kind')=='native_state_probe_result' and type(result.get('version')) is int and result['version']==2
            and result.get('status')=='passed' and result.get('plan_sha256')==expected_plan_sha256
            and result.get('capture_sha256')==hashlib.sha256(capture_raw).hexdigest(),'native capture commitment differs')
    for key in ('real_test','model_inference','gold_evidence','production_edits'):
        require(result.get(key) is False,'diagnostic cannot assert evaluation or production permission')
    lines=capture_raw.splitlines()
    require(0<len(lines)<=MAX_EVENTS and len(lines)==result.get('fixture_count')==plan.get('expected_fixture_count'),
            'native event denominator differs')
    values=[inspect_event(_document(line)) for line in lines]
    require([v['fixture'] for v in values]==list(range(len(values))), 'native event ordering or replay differs')
    require(sum(v['status']=='captured' for v in values)==result.get('capture_count')
            and sum(v.get('applied',False) for v in values)==result.get('applied'), 'native reported totals differ')
    require(len(values)%2==0,'unpaired native control population')
    scenarios=set()
    for baseline,current in zip(values[::2],values[1::2],strict=True):
        require(baseline['baseline_run'] and not current['baseline_run']
                and baseline['scenario']==current['scenario'] and baseline['scenario'] not in scenarios,
                'native control pairing or replay differs')
        scenarios.add(baseline['scenario'])
        require(baseline['status']==current['status'],'native control capture population changed')
        if baseline['snapshot'] is not None:
            for key in ('reading','candidates','product_state'):
                require(baseline['snapshot'][key]==current['snapshot'][key], 'native control state changed')
    return values


def bind_evaluator_input(snapshot,request,facts):
    """Bind observable native fields without inventing legacy per-edge features.

    This is called before invoking any model. Legacy schema2 still caps32 rows;
    an unsupported complete native population is rejected, never clipped or
    removed from a dataset. Feature/category provenance remains separate.
    """
    require(snapshot is not None,'no native conversion snapshot to bind')
    candidates=snapshot['candidates']
    require(len(candidates)<=32, 'native population exceeds legacy evaluator contract')
    require(isinstance(request,dict) and request.get('reading')==snapshot['reading']
            and request.get('left_context')=='' and request.get('context_policy')=='sakura_input_committed_same_session',
            'native input or context differs')
    supplied=request.get('candidates')
    require(isinstance(supplied,list) and len(supplied)==len(candidates),'native candidate population differs')
    require(all(isinstance(a,dict) and type(a.get('rank')) is int and a['rank']==i
                and type(a.get('local_cost')) is int and a['local_cost']==b['local_cost']
                and a.get('surface')==b['surface'] for i,(a,b) in enumerate(zip(supplied,candidates,strict=True))),
            'native candidate projection differs')
    require(canonical_json_bytes(validate_policy_facts(facts,len(candidates)))==canonical_json_bytes(snapshot['product_state']),
            'native policy facts differ')
    return {'input_sha256':hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
            'policy_facts_sha256':hashlib.sha256(canonical_json_bytes(facts)).hexdigest(),
            'native_snapshot_sha256':hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest(),
            'purpose':'native_projection_binding','legacy_feature_provenance_verified':False,
            'gold_certified':False,'final_evaluation_admitted':False}
