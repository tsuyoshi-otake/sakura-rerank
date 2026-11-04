"""Machine evidence for every pilot case; not human labels or semantic Gold."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash, canonical_jsonl_bytes, validate_record
from .gold_pilot import _publish, load_packet
from .tier_a import validate_source_spans

MAX_BYTES = 512 * 1024 * 1024
MAX_LINE = 256 * 1024
MAX_ROWS = 100000
ID = re.compile(rb'(?:^|,)"stable_id":"([^"\\]+)"(?=,|})')


def selected_rows(path: Path, expected_sha: str, wanted: set[str], *, frozen: bool) -> tuple[dict, dict]:
    """Hash every byte, parse only selected records; skip holdout before parsing."""
    if not re.fullmatch('[0-9a-f]{64}', expected_sha) or path.is_symlink() or path.stat().st_size>MAX_BYTES:
        raise ValueError('evidence hash or file bound invalid')
    wanted_bytes={v.encode('ascii'):v for v in wanted}
    selected={}
    digest=hashlib.sha256()
    rows=size=skipped=0
    with path.open('rb') as stream:
        while line:=stream.readline(MAX_LINE+1):
            rows+=1
            size+=len(line)
            if len(line)>MAX_LINE or size>MAX_BYTES or rows>MAX_ROWS:
                raise ValueError('evidence line/row/byte bound exceeded')
            digest.update(line)
            if frozen and b',"split":"final-holdout",' in line:
                skipped+=1
                continue
            identity=ID.search(line)
            if identity is None or identity[1] not in wanted_bytes:
                continue
            stable=wanted_bytes[identity[1]]
            if stable in selected:
                raise ValueError('duplicate selected evidence')
            record=json.loads(line)
            if record['stable_id']!=stable:
                raise ValueError('evidence identity mismatch')
            if frozen:
                record=validate_record(record)
                if record['split']!='train' or record['is_fixture'] or not record['training_eligible']:
                    raise ValueError('pilot evidence must be eligible real train data')
            else:
                # Only the preceding 64 characters and target survive projection.
                record=validate_source_spans([record])[0]
            selected[stable]=(record,hashlib.sha256(line).hexdigest())
    if digest.hexdigest()!=expected_sha or set(selected)!=wanted:
        raise ValueError('evidence hash or selected coverage mismatch')
    return selected,dict(sha256=expected_sha,bytes=size,rows=rows,selected_parsed=len(selected),
                         holdout_skipped_before_json=skipped,nonselected_parsed=0)


def inspect_cases(queue: dict, bindings: dict, spans: dict, frozen: dict) -> tuple[dict,list]:
    """Compare source provenance and captured paths without judging language."""
    if len(queue)!=1000 or set(queue)!=set(bindings):
        raise ValueError('complete unchanged pilot required')
    wanted={b['stable_id'] for b in bindings.values()}
    if len(wanted)!=1000 or set(spans)!=wanted or set(frozen)!=wanted:
        raise ValueError('evidence cases missing or unexpected')
    evidence=[]
    counts=Counter()
    candidate_count=0
    for case in sorted(queue):
        q,b=queue[case],bindings[case]
        span,span_sha=spans[b['stable_id']]
        row,row_sha=frozen[b['stable_id']]
        # Validation checks contiguous UTF-8 ranges covering full reading/surface
        # for every captured candidate, as well as the dictionary-backed gold path.
        row=validate_record(row)
        candidates=row['candidate_snapshots']['training_top32']['candidates']
        gold=candidates[row['gold_index']]
        segments=[gold['surface'].encode('utf-8')[s['text_start']:s['text_end']].decode('utf-8') for s in gold['segments']]
        checks=dict(
            frozen_row_binding_exact=row_sha==b['source_row_sha256'],
            packet_frozen_exact=(q['reading']==row['reading'] and q['source_gold_surface']==row['gold_surface']
                and b['old_gold_surface']==row['gold_surface'] and q['left_context']==row['session']['left_context']
                and q['candidate_surfaces']==sorted({c['surface'] for c in candidates})
                and q['gold_segment_surfaces']==segments),
            provenance_exact=(span['source']==row['source']==b['source']
                and row['converter_provenance']==b['converter_provenance']),
            source_left_context_exact=span['left_context']==q['left_context'],
            captured_full_reading_paths_valid=True)
        original=span['gold_surface']
        comparison=('exact' if original==q['source_gold_surface'] else 'nfkc_only'
                    if unicodedata.normalize('NFKC',original)==unicodedata.normalize('NFKC',q['source_gold_surface'])
                    else 'different')
        counts['source_target_'+comparison]+=1
        for key,value in checks.items():
            counts[key+'_pass' if value else key+'_fail']+=1
        candidate_count+=len(candidates)
        evidence.append(dict(case_id=case,source_span_row_sha256=span_sha,frozen_row_sha256=row_sha,
            packet_case_sha256=canonical_json_hash(q),source_target_comparison=comparison,checks=checks))
    report=dict(schema_version=1,kind='machine_pilot_evidence_not_gold',selected=1000,checked=1000,
        counts=dict(sorted(counts.items())),captured_candidates_structurally_validated=candidate_count,
        status='evidence_consistent_no_semantic_claim' if not any(k.endswith('_fail') for k in counts)
            and not counts['source_target_different'] else 'evidence_discrepancies_require_investigation',
        source_evidence_scope='separately_stored_preprocessed_source_spans_from_the_same_extractor',
        new_converter_execution=False,semantic_reading_validity_verified=False,
        intended_spelling_verified=False,real_user_input_boundary_verified=False,
        independent_source_correctness_verified=False,human_review_count=0,independent_label_review=False,
        certified_accuracy=None,gate_a_human_audit_pass=False,gate_a_owner_authorized_audit_pass=False,
        independent_test=False,final_holdout_valid_count=0,canonical_labels_changed=False,
        raw_text_in_report=False,raw_stable_ids_in_report=False)
    return report,evidence


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packet','source-spans','source-manifest','frozen','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try:
        manifest,queue,bindings=load_packet(args.packet)
        if args.source_manifest.stat().st_size>1024*1024:
            raise ValueError('source manifest oversized')
        source_manifest_raw=args.source_manifest.read_bytes()
        source_manifest=json.loads(source_manifest_raw)
        if source_manifest['manifest_kind']!='jawiki_tier_a_source_spans' or source_manifest['verification_status']!='verified':
            raise ValueError('verified source-span manifest required')
        wanted={b['stable_id'] for b in bindings.values()}
        spans,span_info=selected_rows(args.source_spans,source_manifest['content_sha256'],wanted,frozen=False)
        frozen,frozen_info=selected_rows(args.frozen,manifest['source']['sha256'],wanted,frozen=True)
        report,evidence=inspect_cases(queue,bindings,spans,frozen)
        report.update(queue_sha256=manifest['queue_sha256'],binding_sha256=manifest['binding_sha256'],
                      source_spans=span_info,frozen_source=frozen_info,
                      source_manifest_sha256=hashlib.sha256(source_manifest_raw).hexdigest(),
                      extractor_git_sha=source_manifest['extractor_git_sha'])
        raw=canonical_jsonl_bytes(evidence)
        report['evidence_sha256']=hashlib.sha256(raw).hexdigest()
        _publish(args.output,{'report.json':canonical_json_bytes(report)+b'\n','evidence.jsonl':raw})
        print(canonical_json_bytes(report).decode('utf-8'))
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        parser.exit(2,'pilot evidence validation failed; no result authorized\n')


if __name__=='__main__':
    main()
