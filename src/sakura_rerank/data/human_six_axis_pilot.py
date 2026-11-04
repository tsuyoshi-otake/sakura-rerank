"""Frozen six-axis human pilot: blinded packets, sealed A/B, third-party C.

This workflow records human findings, never modifies labels or certifies Gold.
The coordinator, not a self-declared reviewer ID, establishes human independence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash, canonical_jsonl_bytes
from .gold_pilot import IDENTIFIER, _publish, load_packet as load_legacy_packet

VERSION = 'gold-human-six-axis-v1'
POLICY_SHA = 'cc5d321e3f68e126cbb3199edd8f306d459f6330bd59ffae6f5c095797e20fee'
SOURCE_QUEUE_SHA = 'f43649996c9d175ea6a18239591e5bcde1001db93a8d14a849d6bc4b93b9e3c9'
AXES = {
    'source': ('matches', 'mismatch', 'unverifiable'),
    'reading': ('compatible', 'incompatible', 'unknown'),
    'input_unit': ('whole_unit_plausible', 'partial_unit_plausible', 'boundary_question', 'unknown'),
    'context': ('usable', 'defect_nonblocking', 'defect_blocking', 'unknown'),
    'meaning': ('identifiable', 'ambiguous', 'unknown'),
    'spelling': ('unique', 'multiple', 'protected_unresolved', 'unknown'),
}
UNKNOWN = {'unknown', 'unverifiable', 'protected_unresolved'}
DECLARATIONS = ('human_identity_checked', 'distinct_from_other_reviewers', 'no_prior_case_ai_exposure',
                'no_case_ai_assistance', 'no_peer_labels_before_seal')
MAX_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 10000


def _blob(value: object) -> bytes:
    return canonical_json_bytes(value) + b'\n'


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, limit: int = MAX_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('file violates regular-file byte bound')
    return path.read_bytes()


def _moment(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('invalid timestamp')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('timestamp must have timezone')
    return dt


def _text(value: object, maximum: int = 2000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and '\0' not in value


def _policy(raw: bytes) -> dict:
    if _sha(raw) != POLICY_SHA:
        raise ValueError('frozen human policy hash mismatch; use a new version for changes')
    value = json.loads(raw)
    if value['policy_version'] != VERSION or {k: set(v) for k,v in value['axes'].items()} != {k:set(v) for k,v in AXES.items()}:
        raise ValueError('axis contract mismatch')
    return value


def _review_id(role: str, case: str) -> str:
    return role.lower() + '-' + canonical_json_hash([VERSION, role, case])[:24]


def _form(packet_id: str, role: str, case: str) -> dict:
    return dict(record_type='human_six_axis_assessment', review_id=_review_id(role,case), role=role,
                reviewer_id=None, reviewer_kind=None, reviewed_at=None, packet_id=packet_id,
                policy_sha256=POLICY_SHA, roster_sha256=None, previous_event_sha256=None,
                previous_log_sha256=None, seal_sha256=None, basis_sha256=[],
                axes={k:dict(value=None, reason='') for k in AXES}, accepted_surfaces=[])


def _card(role: str, item: dict) -> dict:
    fields = ('left_context','reading','source_gold_surface','candidate_surfaces','gold_segment_surfaces')
    return dict(review_id=_review_id(role,item['case_id']), **{k:item[k] for k in fields},
                source_evidence=None, input_provenance='synthetic_dictionary_span')


def build_packet(queue: dict, policy_raw: bytes) -> dict[str, bytes]:
    """Pure deterministic builder; CLI/load bind it to the frozen source queue."""
    _policy(policy_raw)
    if len(queue) != 1000:
        raise ValueError('all 1000 cases required')
    fields = {'case_id','left_context','reading','source_gold_surface','candidate_surfaces','gold_segment_surfaces'}
    for case,item in queue.items():
        if set(item) != fields or item['case_id'] != case or item['candidate_surfaces'] != sorted(set(item['candidate_surfaces'])):
            raise ValueError('queue contract mismatch')
    qbytes = canonical_jsonl_bytes([queue[c] for c in sorted(queue)])
    packet_id = canonical_json_hash([VERSION, _sha(qbytes), POLICY_SHA])
    payloads = {'coordinator/queue.jsonl':qbytes, 'policy.json':policy_raw}
    guide = (
        '# 独立人手判定\n\n'
        'この役割の資料だけを使用し、policy.jsonを先に読んでください。全1000件・25件×40batchです。\n'
        '相手の判定・過去のAI提案・モデル出力を見ず、ケース別AI補助を使わずに六軸を判断します。\n'
        '原goldは監査対象として表示されています。候補は表記順で、変換器順位ではありません。\n'
        '独立原文証拠はないためsource=unverifiableです。意味の正しさとは別の判断です。\n'
        '全軸の値と具体的理由を記入し、不明はunknownにします。空欄を正解扱いしません。\n'
        '記録先はこの不変packetの外です。訂正は旧eventを消さずhashを指定した追記にします。\n'
        'reviewer_id・roster_sha256はcoordinatorから受け取ります。日時はtimezone付きで記録します。\n'
        'previous_log_sha256は自分の直前event、previous_event_sha256は同じ案件の自分の直前eventです。\n'
        '初回はnull、A/Bのseal_sha256はnull・basis_sha256は空です。\n'
        '双方の全件提出が揃うと固定されます。それ以後のA/B訂正には別runが必要です。\n'
        '疑義は資料の外の文脈を推測せず理由へ記録します。本文を外部サービスへ送らないでください。\n'
    ).encode('utf-8')
    for role in ('A','B'):
        payloads[f'reviewer-{role}/policy.json'] = policy_raw
        payloads[f'reviewer-{role}/GUIDE.md'] = guide
        ordered = sorted(queue, key=lambda c:canonical_json_hash([VERSION,role,c]))
        for start in range(0,1000,25):
            cases = ordered[start:start+25]
            payloads[f'reviewer-{role}/batch-{start//25+1:03d}.json'] = _blob(dict(
                packet_id=packet_id, policy_sha256=POLICY_SHA, role=role, cases=[_card(role,queue[c]) for c in cases]))
            payloads[f'reviewer-{role}/responses-{start//25+1:03d}.template.jsonl'] = canonical_jsonl_bytes([
                _form(packet_id,role,c) for c in cases])
    roster = dict(record_type='human_six_axis_assignment', packet_id=packet_id, policy_sha256=POLICY_SHA,
                  coordinator_id=None, confirmed_at=None, roles={role:dict(reviewer_id=None, reviewer_kind=None,
                  **{k:None for k in DECLARATIONS}) for role in ('A','B','C')})
    payloads['coordinator/assignment.template.json'] = _blob(roster)
    manifest = dict(kind=VERSION, packet_id=packet_id, queue_sha256=_sha(qbytes), policy_sha256=POLICY_SHA,
                    size=1000, gate_a_eligible=False, independent_test=False,
                    file_sha256={k:_sha(v) for k,v in sorted(payloads.items())})
    payloads['manifest.json'] = _blob(manifest)
    return payloads


def load_review_packet(path: Path) -> tuple[dict, dict]:
    """Regenerate allowlisted packet bytes: extra files and covert AI fields fail."""
    raw_queue = _read(path/'coordinator/queue.jsonl')
    if _sha(raw_queue) != SOURCE_QUEUE_SHA:
        raise ValueError('human packet is not the unchanged 1000-case cohort')
    rows = [json.loads(line) for line in raw_queue.splitlines()]
    queue = {r['case_id']:r for r in rows}
    if len(rows) != len(queue):
        raise ValueError('duplicate case')
    expected = build_packet(queue,_read(path/'policy.json',128*1024))
    actual_names = set()
    for item in path.rglob('*'):
        if item.is_symlink() or item.is_junction():
            raise ValueError('packet links not allowed')
        if item.is_file():
            actual_names.add(item.relative_to(path).as_posix())
        if len(actual_names)>len(expected):
            raise ValueError('unexpected packet files')
    if actual_names != set(expected) or any(_read(path/name) != raw for name,raw in expected.items()):
        raise ValueError('packet modified or contains unapproved evidence')
    return json.loads(expected['manifest.json']),queue


def validate_roster(roster: dict, manifest: dict) -> str:
    fields = {'record_type','packet_id','policy_sha256','coordinator_id','confirmed_at','roles'}
    if (not isinstance(roster,dict) or set(roster)!=fields or roster['record_type']!='human_six_axis_assignment'
            or roster['packet_id']!=manifest['packet_id'] or roster['policy_sha256']!=POLICY_SHA
            or not isinstance(roster['coordinator_id'],str) or not IDENTIFIER.fullmatch(roster['coordinator_id'])):
        raise ValueError('human assignment contract invalid')
    _moment(roster['confirmed_at'])
    if not isinstance(roster['roles'],dict) or set(roster['roles'])!={'A','B','C'}:
        raise ValueError('three assigned human roles required')
    identities=set()
    for role in ('A','B','C'):
        person=roster['roles'][role]
        if (not isinstance(person,dict) or set(person)!={'reviewer_id','reviewer_kind',*DECLARATIONS}
                or person['reviewer_kind']!='human' or not isinstance(person['reviewer_id'],str)
                or not IDENTIFIER.fullmatch(person['reviewer_id']) or person['reviewer_id'] in identities
                or any(person[k] is not True for k in DECLARATIONS)):
            raise ValueError('distinct humans and coordinator independence confirmations required')
        identities.add(person['reviewer_id'])
    return canonical_json_hash(roster)


def _validate_axes(event: dict, item: dict) -> None:
    values=event['axes']
    if not isinstance(values,dict) or set(values)!=set(AXES):
        raise ValueError('all six axes required')
    for axis,allowed in AXES.items():
        choice=values[axis]
        if (not isinstance(choice,dict) or set(choice)!={'value','reason'}
                or choice['value'] not in allowed or not _text(choice['reason'])):
            raise ValueError('axis value and explicit reason required')
    if values['source']['value']!='unverifiable':
        raise ValueError('this packet supplies no independent source evidence')
    surfaces=event['accepted_surfaces']
    if (not isinstance(surfaces,list) or len(surfaces)>32 or any(not _text(x,256) for x in surfaces)
            or surfaces!=sorted(set(surfaces)) or any(x not in item['candidate_surfaces'] for x in surfaces)):
        raise ValueError('explicit frozen candidate set required')
    v={k:x['value'] for k,x in values.items()}
    if v['spelling'] in ('unique','multiple'):
        if (v['reading']!='compatible' or v['input_unit'] not in ('whole_unit_plausible','partial_unit_plausible')
                or v['context'] not in ('usable','defect_nonblocking') or v['meaning']!='identifiable'
                or len(surfaces)<(1 if v['spelling']=='unique' else 2)
                or (v['spelling']=='unique' and len(surfaces)!=1)):
            raise ValueError('spelling judgment lacks required compatible axes or surfaces')
    elif surfaces:
        raise ValueError('unresolved spelling cannot propose labels')


def _signature(event: dict) -> tuple:
    return tuple(event['axes'][k]['value'] for k in AXES),tuple(event['accepted_surfaces'])


def _agreement(pairs: list[tuple[dict,dict]]) -> dict:
    per_axis={}
    for axis in AXES:
        vals=[(a['axes'][axis]['value'],b['axes'][axis]['value']) for a,b in pairs]
        informative=[(a,b) for a,b in vals if a not in UNKNOWN and b not in UNKNOWN]
        equal=sum(a==b for a,b in vals)
        iequal=sum(a==b for a,b in informative)
        per_axis[axis]=dict(equal=equal, paired=len(vals), rate=equal/len(vals) if vals else None,
            both_unknown=sum(a in UNKNOWN and b in UNKNOWN for a,b in vals),
            informative_equal=iequal, informative_paired=len(informative),
            informative_rate=iequal/len(informative) if informative else None)
    equal=sum(_signature(a)==_signature(b) for a,b in pairs)
    return dict(paired=len(pairs),missing_pairs=1000-len(pairs),joint_equal=equal,
                joint_rate=equal/len(pairs) if pairs else None, per_axis=per_axis)


def reconcile(manifest: dict, queue: dict, roster: dict | None, events: list[dict]) -> tuple[dict,list,list,dict|None]:
    """Replay append-only histories; seal immediately when all A/B cases exist."""
    if len(queue)!=1000 or len(events)>MAX_EVENTS:
        raise ValueError('pilot population or event count outside bound')
    if roster is None and events:
        raise ValueError('human events require an assigned roster')
    roster_sha=validate_roster(roster,manifest) if roster is not None else None
    lookup={(_review_id(r,c),r):c for c in queue for r in ('A','B','C')}
    latest,first,role_heads,role_times={}, {}, {}, {}
    seal=None
    ab_cases=0
    fields=set(_form(manifest['packet_id'],'A',next(iter(queue))))
    for number,event in enumerate(events,1):
        try:
            if not isinstance(event,dict) or set(event)!=fields:
                raise ValueError('fields mismatch')
            role=event['role']
            if not isinstance(role,str) or role not in ('A','B','C') or not isinstance(event['review_id'],str):
                raise ValueError('role invalid')
            case=lookup.get((event['review_id'],role))
            if (case is None or event['record_type']!='human_six_axis_assessment' or event['reviewer_kind']!='human'
                    or event['reviewer_id']!=roster['roles'][role]['reviewer_id']
                    or event['packet_id']!=manifest['packet_id'] or event['policy_sha256']!=POLICY_SHA
                    or event['roster_sha256']!=roster_sha):
                raise ValueError('identity or evidence mismatch')
            _validate_axes(event,queue[case])
            dt=_moment(event['reviewed_at'])
            if dt < _moment(roster['confirmed_at']) or (role in role_times and dt < role_times[role]):
                raise ValueError('backdated event')
            old=latest.get((case,role))
            if (event['previous_event_sha256']!=(canonical_json_hash(old) if old else None)
                    or event['previous_log_sha256']!=role_heads.get(role)):
                raise ValueError('history mismatch')
            if role in ('A','B'):
                if seal is not None or event['seal_sha256'] is not None or event['basis_sha256']!=[]:
                    raise ValueError('A/B sealed or exposed to adjudication evidence')
            else:
                if seal is None or event['seal_sha256']!=canonical_json_hash(seal):
                    raise ValueError('C requires all 1000 sealed A/B pairs')
                a,b=(latest[(case,r)] for r in ('A','B'))
                if (event['basis_sha256']!=[canonical_json_hash(a),canonical_json_hash(b)]
                        or _signature(a)==_signature(b) or dt<max(role_times['A'],role_times['B'])):
                    raise ValueError('C basis, time or disagreement invalid')
            first.setdefault((case,role),event)
            if old is None and role in ('A','B'):
                ab_cases+=1
            latest[(case,role)]=event
            role_heads[role]=canonical_json_hash(event)
            role_times[role]=dt
            if seal is None and ab_cases==2000:
                seal=dict(packet_id=manifest['packet_id'],policy_sha256=POLICY_SHA,roster_sha256=roster_sha,
                          ab_sha256=canonical_json_hash([[c,canonical_json_hash(latest[(c,'A')]),
                          canonical_json_hash(latest[(c,'B')])] for c in sorted(queue)]))
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            raise ValueError(f'human event {number}: contract invalid') from exc
    pairs=[(latest[(c,'A')],latest[(c,'B')]) for c in sorted(queue) if (c,'A') in latest and (c,'B') in latest]
    first_pairs=[(first[(c,'A')],first[(c,'B')]) for c in sorted(queue) if (c,'A') in first and (c,'B') in first]
    findings,tasks=[],[]
    disputed=adjudicated=0
    distribution={r:{axis:Counter() for axis in AXES} for r in ('A','B','final')}
    for c in sorted(queue):
        for r in ('A','B'):
            if (c,r) in latest:
                for axis in AXES:
                    distribution[r][axis][latest[(c,r)]['axes'][axis]['value']]+=1
        if seal is None:
            continue
        a,b=(latest[(c,r)] for r in ('A','B'))
        basis=[canonical_json_hash(a),canonical_json_hash(b)]
        final=a
        route='agreed_findings'
        if _signature(a)!=_signature(b):
            disputed+=1
            final=latest.get((c,'C'))
            route='adjudicated_findings'
            if final is None:
                form=_form(manifest['packet_id'],'C',c)
                form.update(roster_sha256=roster_sha,seal_sha256=canonical_json_hash(seal),basis_sha256=basis)
                tasks.append(dict(case=_card('C',queue[c]), basis_sha256=basis,
                    review_a={k:a[k] for k in ('axes','accepted_surfaces')},
                    review_b={k:b[k] for k in ('axes','accepted_surfaces')},response_template=form))
                continue
            adjudicated+=1
            basis.append(canonical_json_hash(final))
        findings.append(dict(kind='human_pilot_findings_not_gold',case_id=c,route=route,axes=final['axes'],
                             accepted_surfaces=final['accepted_surfaces'],basis_sha256=basis))
        for axis in AXES:
            distribution['final'][axis][final['axes'][axis]['value']]+=1
    current=_agreement(pairs)
    unequal=current['paired']-current['joint_equal']
    status=('awaiting_assignment' if roster is None else 'awaiting_dual_review' if seal is None
            else 'awaiting_adjudication' if tasks else 'pilot_findings_complete_no_gold')
    report=dict(kind=VERSION,status=status,selected=1000,packet_id=manifest['packet_id'],policy_sha256=POLICY_SHA,
        roster_sha256=roster_sha,events_sha256=canonical_json_hash(events),event_count=len(events),
        human_case_counts={r:sum(role==r for _,role in latest) for r in ('A','B','C')},
        human_independence_basis='coordinator_attestation_not_machine_identity_verification',
        initial_agreement=_agreement(first_pairs),current_agreement=current,
        adjudication=dict(disagreement_count=unequal,paired_denominator=len(pairs),
                         required_rate_on_paired=unequal/len(pairs) if pairs else None,
                         required_fraction_of_full_pilot=unequal/1000,requests_released=len(tasks)+adjudicated,
                         completed=adjudicated,completion_rate=adjudicated/disputed if disputed else None),
        distributions={r:{a:{v:counts[v] for v in AXES[a]} for a,counts in d.items()} for r,d in distribution.items()},
        seal_sha256=canonical_json_hash(seal) if seal else None,finalized_findings=len(findings),
        pending=1000-len(findings),source_independently_verified=0,certified_gold_count=0,certified_accuracy=None,
        gate_a_human_audit_pass=False,gate_a_owner_authorized_audit_pass=False,independent_test=False,
        final_holdout_valid_count=0,canonical_labels_changed=False,raw_text_in_report=False,raw_stable_ids_in_report=False)
    return report,findings,tasks,seal


def publish_round(path: Path, manifest: dict, queue: dict, roster: dict|None, events: list[dict],
                  previous: Path|None=None, previous_sha: str|None=None) -> dict:
    """Every non-empty run extends a pinned complete prior round, never a reset."""
    previous_hash=None
    if previous is None:
        if events or roster is not None or previous_sha is not None:
            raise ValueError('bootstrap must be empty and unassigned')
    else:
        raw=_read(previous/'round.json')
        if _sha(raw)!=previous_sha:
            raise ValueError('previous round checkpoint mismatch')
        prior=json.loads(raw)
        required={'events.jsonl','assignment.json','report.json','findings.jsonl','adjudication.jsonl','seal.json'}
        if set(prior['file_sha256'])!=required or prior['packet_id']!=manifest['packet_id']:
            raise ValueError('previous round contract mismatch')
        old={name:_read(previous/name) for name in required}
        if any(_sha(old[k])!=v for k,v in prior['file_sha256'].items()):
            raise ValueError('previous round modified')
        prior_events=[json.loads(line) for line in old['events.jsonl'].splitlines()]
        if len(prior_events)>len(events) or events[:len(prior_events)]!=prior_events:
            raise ValueError('event history rewritten or truncated')
        prior_roster=json.loads(old['assignment.json'])
        if prior_roster is not None and roster!=prior_roster:
            raise ValueError('assignment cannot change within a run')
        previous_hash=_sha(raw)
    report,findings,tasks,seal=reconcile(manifest,queue,roster,events)
    report['previous_round_sha256']=previous_hash
    payloads={'events.jsonl':canonical_jsonl_bytes(events),'assignment.json':_blob(roster),'report.json':_blob(report),
              'findings.jsonl':canonical_jsonl_bytes(findings),'adjudication.jsonl':canonical_jsonl_bytes(tasks),
              'seal.json':_blob(seal)}
    payloads['round.json']=_blob(dict(kind=VERSION,packet_id=manifest['packet_id'],previous_round_sha256=previous_hash,
                                    file_sha256={k:_sha(v) for k,v in payloads.items()}))
    _publish(path,payloads)
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare')
    prep.add_argument('--source-packet',type=Path,required=True)
    prep.add_argument('--policy',type=Path,required=True)
    prep.add_argument('--output',type=Path,required=True)
    boot=sub.add_parser('bootstrap')
    adv=sub.add_parser('advance')
    for p in (boot,adv):
        p.add_argument('--packet',type=Path,required=True)
        p.add_argument('--output',type=Path,required=True)
    adv.add_argument('--assignment',type=Path,required=True)
    adv.add_argument('--events',type=Path,required=True)
    adv.add_argument('--previous-round',type=Path,required=True)
    adv.add_argument('--previous-round-sha256',required=True)
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            legacy,queue,_=load_legacy_packet(args.source_packet)
            if legacy['queue_sha256']!=SOURCE_QUEUE_SHA:
                raise ValueError('source cohort differs from approved pilot')
            _publish(args.output,build_packet(queue,_read(args.policy,128*1024)))
        else:
            manifest,queue=load_review_packet(args.packet)
            if args.command=='bootstrap':
                report=publish_round(args.output,manifest,queue,None,[])
            else:
                events=[json.loads(line) for line in _read(args.events).splitlines()]
                roster=json.loads(_read(args.assignment,128*1024))
                report=publish_round(args.output,manifest,queue,roster,events,args.previous_round,args.previous_round_sha256)
            print(_blob(report).decode('utf-8'),end='')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        parser.exit(2,'human six-axis pilot failed validation; no result authorized\n')


if __name__=='__main__':
    main()
