"""Single-AI six-axis diagnostic evidence, disjoint from human/Gold contracts."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash
from .gold_pilot import load_packet

POLICY_SHA='dd1671662c8506c2a8182279e775952f25ddf69bba2eb1c861367d9c81accc1b'
VALUES={
    'reading':{'C':'compatible','S':'suspect','U':'unknown'},
    'input_unit':{'W':'whole_plausible','B':'boundary_question','U':'unknown'},
    'context':{'U':'usable','N':'defect_nonblocking','B':'defect_blocking','X':'unknown'},
    'meaning':{'S':'supported','A':'ambiguous','U':'unknown'},
    'spelling':{'O':'ordinary_plausible','T':'style_underdetermined','P':'protected_unverified','U':'unknown'},
}
MACHINE_CHECKS = {
    'frozen_row_binding_exact', 'packet_frozen_exact', 'provenance_exact',
    'source_left_context_exact', 'captured_full_reading_paths_valid',
}


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:
        raise ValueError('AI six-axis evidence file bound invalid')
    return path.read_bytes()


def _moment(value: object) -> datetime:
    if not isinstance(value,str) or len(value)>64:
        raise ValueError('invalid review timestamp')
    moment=datetime.fromisoformat(value.replace('Z','+00:00'))
    if moment.tzinfo is None:
        raise ValueError('review timestamp must be aware')
    return moment


def load_inputs(packet: Path, machine_report: Path, evidence: Path) -> tuple[dict,dict,dict,str]:
    manifest,queue,_=load_packet(packet)
    raw=_read(machine_report,1024*1024)
    report=json.loads(raw)
    source=_read(evidence,4*1024*1024)
    if (report['kind']!='machine_pilot_evidence_not_gold' or report['checked']!=1000
            or report['queue_sha256']!=manifest['queue_sha256']
            or report['evidence_sha256']!=hashlib.sha256(source).hexdigest()
            or report['canonical_labels_changed'] is not False
            or report['independent_source_correctness_verified'] is not False):
        raise ValueError('machine evidence binding mismatch')
    unverified = ('semantic_reading_validity_verified', 'real_user_input_boundary_verified',
                  'intended_spelling_verified', 'independent_label_review', 'independent_test',
                  'gate_a_human_audit_pass', 'gate_a_owner_authorized_audit_pass')
    if (any(report[name] is not False for name in unverified)
            or report['certified_accuracy'] is not None
            or report['human_review_count'] != 0 or report['final_holdout_valid_count'] != 0):
        raise ValueError('machine checks cannot certify language or independent review')
    rows=[json.loads(line) for line in source.splitlines()]
    machine={r['case_id']:r for r in rows}
    if len(rows)!=1000 or set(machine)!=set(queue):
        raise ValueError('machine case coverage mismatch')
    for case,row in machine.items():
        if (row['packet_case_sha256']!=canonical_json_hash(queue[case]) or row['source_target_comparison']!='exact'
                or set(row['checks']) != MACHINE_CHECKS
                or any(v is not True for v in row['checks'].values())):
            raise ValueError('source evidence is not exact for all selected cases')
    return manifest,queue,machine,hashlib.sha256(raw).hexdigest()


def ordered_cases(queue: dict) -> list[str]:
    return sorted(queue,key=lambda c:canonical_json_hash(['A',c]))


def validate_decision(value: dict, case: str, machine: dict) -> None:
    if (not isinstance(value,dict) or set(value)!={'case_id','axes','reason','machine_evidence_sha256'}
            or value['case_id']!=case or value['machine_evidence_sha256']!=canonical_json_hash(machine[case])):
        raise ValueError('decision evidence contract mismatch')
    axes=value['axes']
    if (not isinstance(axes,dict) or set(axes)!=set(VALUES)
            or any(not isinstance(axes[k],str) or axes[k] not in VALUES[k].values() for k in VALUES)):
        raise ValueError('all five explicit linguistic axes required')
    if not isinstance(value['reason'],str) or not value['reason'].strip() or len(value['reason'])>2000 or '\0' in value['reason']:
        raise ValueError('individual reason required')
    if axes['context']=='defect_blocking' and axes['meaning']=='supported':
        raise ValueError('blocking context cannot support an identified meaning')


def validate_batch(batch: dict, queue: dict, manifest: dict, machine: dict, machine_sha: str) -> list[dict]:
    fields={'batch','queue_sha256','policy_sha256','machine_report_sha256','reviewer_kind','reviewer_id','reviewed_at','decisions'}
    if (not isinstance(batch,dict) or set(batch)!=fields or type(batch['batch']) is not int
            or not 1<=batch['batch']<=20 or len(queue)!=1000 or batch['queue_sha256']!=manifest['queue_sha256']
            or batch['policy_sha256']!=POLICY_SHA or batch['machine_report_sha256']!=machine_sha
            or batch['reviewer_kind']!='ai_teacher' or batch['reviewer_id']!='codex-primary'):
        raise ValueError('AI batch provenance mismatch')
    _moment(batch['reviewed_at'])
    expected=ordered_cases(queue)[(batch['batch']-1)*50:batch['batch']*50]
    if not isinstance(batch['decisions'],list) or len(batch['decisions'])!=50:
        raise ValueError('batch needs 50 explicit decisions')
    for case,decision in zip(expected,batch['decisions'],strict=True):
        validate_decision(decision,case,machine)
    return batch['decisions']


def summarize(directory: Path, queue: dict, manifest: dict, machine: dict, machine_sha: str,
              previous: dict|None=None, baseline: dict|None=None, baseline_sha: str|None=None) -> dict:
    if not directory.is_dir():
        raise ValueError('AI review directory missing')
    latest,initial,hashes,times,files={},{},{},{},{}
    batches=sorted(directory.glob('batch-*.json'))
    if len(batches)>20:
        raise ValueError('batch count exceeds 20')
    for path in batches:
        raw=_read(path,1024*1024)
        batch=json.loads(raw)
        decisions=validate_batch(batch,queue,manifest,machine,machine_sha)
        if path.name!=f"batch-{batch['batch']:03d}.json":
            raise ValueError('batch filename mismatch')
        files[path.name]=hashlib.sha256(raw).hexdigest()
        for d in decisions:
            case=d['case_id']
            latest[case]=initial[case]=d
            hashes[case]=canonical_json_hash(d)
            times[case]=_moment(batch['reviewed_at'])
    amendments=[]
    journal=directory/'amendments.jsonl'
    if journal.exists():
        lines=_read(journal,4*1024*1024).splitlines()
        if len(lines)>2000:
            raise ValueError('amendment count exceeds bound')
        for line in lines:
            e=json.loads(line)
            fields={'queue_sha256','policy_sha256','machine_report_sha256','reviewer_kind','reviewer_id','reviewed_at',
                    'previous_event_sha256','previous_log_sha256','decision'}
            if (not isinstance(e,dict) or set(e)!=fields or e['queue_sha256']!=manifest['queue_sha256']
                    or e['policy_sha256']!=POLICY_SHA or e['machine_report_sha256']!=machine_sha
                    or e['reviewer_kind']!='ai_teacher' or e['reviewer_id']!='codex-primary'):
                raise ValueError('amendment provenance mismatch')
            case=e['decision']['case_id']
            if case not in latest:
                raise ValueError('amendment without initial review')
            validate_decision(e['decision'],case,machine)
            moment=_moment(e['reviewed_at'])
            if (e['previous_event_sha256']!=hashes[case] or e['previous_log_sha256']!=(amendments[-1] if amendments else None)
                    or moment<times[case]):
                raise ValueError('amendment history mismatch')
            latest[case]=e['decision']
            hashes[case]=canonical_json_hash(e)
            times[case]=moment
            amendments.append(hashes[case])
    if previous is not None and (previous['queue_sha256']!=manifest['queue_sha256']
            or previous['policy_sha256']!=POLICY_SHA or previous['machine_report_sha256']!=machine_sha
            or any(files.get(k)!=v for k,v in previous['batch_sha256'].items())
            or amendments[:len(previous['amendment_sha256'])]!=previous['amendment_sha256']):
        raise ValueError('AI history rewritten or truncated')
    def count(rows):
        return {axis:{v:sum(d['axes'][axis]==v for d in rows.values()) for v in choices.values()}
                for axis,choices in VALUES.items()}
    combinations=Counter(tuple(d['axes'][axis] for axis in VALUES) for d in latest.values())
    report = dict(schema_version=1,kind='single_ai_six_axis_diagnostics',selected=1000,reviewed=len(latest),pending=1000-len(latest),
        status='ai_review_complete_no_gold' if len(latest)==1000 else 'ai_review_in_progress',counts=count(latest),
        initial_counts=count(initial),axis_combinations=[dict(axes=dict(zip(VALUES,combo)),count=n) for combo,n in sorted(combinations.items())],
        source_axis=dict(preprocessed_exact=len(latest),independently_verified=0),batch_sha256=files,amendment_sha256=amendments,
        self_correction_count=len(amendments),queue_sha256=manifest['queue_sha256'],policy_sha256=POLICY_SHA,
        machine_report_sha256=machine_sha,reviewer_kind='ai_teacher',reviewer_count=1,human_review_count=0,
        independent_review=False,blinded_to_source_gold=False,prior_case_exposure=True,certified_accuracy=None,
        unique_intended_output_certified=False,gate_a_human_audit_pass=False,gate_a_owner_authorized_audit_pass=False,
        independent_test=False,final_holdout_valid_count=0,canonical_labels_changed=False,
        raw_text_in_report=False,raw_stable_ids_in_report=False)
    if baseline is not None:
        if set(baseline) != set(queue) or not baseline_sha:
            raise ValueError('baseline population binding mismatch')
        cohorts = {}
        for name, is_unique in (('old_unique', True), ('old_flagged', False)):
            selected = {case for case, (decision, _, _) in baseline.items()
                        if (decision['verdict'] == 'unique_correct') == is_unique}
            reviewed = {case: d for case, d in latest.items() if case in selected}
            cohorts[name] = dict(selected=len(selected), reviewed=len(reviewed),
                                 pending=len(selected)-len(reviewed), counts=count(reviewed))
        report['baseline_comparison'] = dict(
            base_report_sha256=baseline_sha, cohorts=cohorts,
            interpretation='Conditional descriptions, not accuracy, independent agreement or transitions to valid labels',
        )
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packet','machine-report','machine-evidence','policy','reviews'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--previous-report',type=Path)
    for name in ('baseline-reviews', 'baseline-policy', 'baseline-report'):
        parser.add_argument('--'+name, type=Path)
    args=parser.parse_args()
    try:
        if hashlib.sha256(_read(args.policy,128*1024)).hexdigest()!=POLICY_SHA:
            raise ValueError('frozen AI policy mismatch')
        manifest,queue,machine,machine_sha=load_inputs(args.packet,args.machine_report,args.machine_evidence)
        previous=json.loads(_read(args.previous_report,1024*1024)) if args.previous_report else None
        baseline_args = (args.baseline_reviews, args.baseline_policy, args.baseline_report)
        baseline, baseline_sha = None, None
        if any(baseline_args):
            if not all(baseline_args):
                raise ValueError('all baseline arguments required')
            from .pilot_policy_triage import load_baseline
            baseline, baseline_sha = load_baseline(args.baseline_reviews, queue, manifest,
                                                   args.baseline_policy, args.baseline_report)
        report=summarize(args.reviews,queue,manifest,machine,machine_sha,previous,baseline,baseline_sha)
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        parser.exit(2,'AI six-axis validation failed; no result authorized\n')
    print(canonical_json_bytes(report).decode('utf-8'))


if __name__=='__main__':
    main()
