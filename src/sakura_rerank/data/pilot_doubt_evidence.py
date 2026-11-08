"""Read-only, hash-bound follow-up evidence for flagged pilot cases; never Gold."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .ai_six_axis_review import load_inputs, ordered_cases, summarize
from .contracts import canonical_json_bytes, canonical_json_hash
from .jawiki_preprocess import clean_wikitext

OUTCOMES = (
    'external_reading_support', 'external_contextual_reading_conflict',
    'plausible_partial_input', 'reproducible_context_problem', 'insufficient_evidence',
)
PROBES = {
    'math_residue': r'数学の説明。<math>\mbox{ for } x</math>',
    'empty_title': '架空の作品『{{仮タイトル}}』を批評した。',
}


def read_bytes(path: Path, limit: int = 1024 * 1024) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('evidence file bound invalid')
    return path.read_bytes()


def text_field(value: object, limit: int = 2000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and '\0' not in value


def selected_cases(queue: dict, decisions: dict) -> list[str]:
    if set(queue) != set(decisions):
        raise ValueError('complete prior review required')
    return [case for case in ordered_cases(queue)
            if decisions[case]['axes']['reading'] != 'compatible'
            or decisions[case]['axes']['input_unit'] == 'boundary_question'
            or decisions[case]['axes']['context'] in ('defect_nonblocking', 'defect_blocking')]


def dictionary_evidence(queue: dict, selected: list[str], path: Path, manifest: dict) -> dict:
    """One bounded stream; keep only targets and at most 32 preceding characters."""
    if (manifest['manifest_kind'] != 'system_dictionary_surface_index'
            or manifest['verification_status'] != 'verified'
            or manifest['normalization'] != 'exact_unicode_v1'
            or not 0 < len(selected) <= 1000):
        raise ValueError('dictionary/selection contract mismatch')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('dictionary file bound invalid')
    wanted = {}
    for case in selected:
        row = queue[case]
        left, target = row['left_context'], row['source_gold_surface']
        wanted[case] = [target] + [left[-n:] + target for n in range(1, min(len(left), 32) + 1)]
    needed = set().union(*map(set, wanted.values()))
    found, digest, count = {}, hashlib.sha256(), 0
    with path.open('rb') as stream:
        while line := stream.readline(16385):
            count += 1
            if len(line) > 16384 or count > 500000:
                raise ValueError('dictionary record bound invalid')
            digest.update(line)
            row = json.loads(line)
            if row['surface'] in needed:
                if row['surface'] in found:
                    raise ValueError('duplicate dictionary surface')
                if (not isinstance(row['readings'], list) or not row['readings']
                        or len(row['readings']) > 128
                        or any(not text_field(r, 256) for r in row['readings'])):
                    raise ValueError('invalid dictionary readings')
                found[row['surface']] = row['readings']
    if digest.hexdigest() != manifest['content_sha256'] or count != manifest['record_count']:
        raise ValueError('dictionary content binding mismatch')
    return {case: {surface: found[surface] for surface in wanted[case] if surface in found}
            for case in selected}


def cleaner_probes() -> dict:
    math, _ = clean_wikitext(PROBES['math_residue'])
    title, _ = clean_wikitext(PROBES['empty_title'])
    return {
        'math_residue': any(r'\mbox{' in p for p in math),
        'empty_title': any('『』' in p for p in title),
    }


def validate_sources(sources: list) -> dict:
    if not isinstance(sources, list) or len(sources) > 50:
        raise ValueError('source count bound invalid')
    result = {}
    fields = {'id', 'url', 'title', 'excerpt', 'excerpt_sha256', 'accessed_at', 'kind', 'scope', 'limit'}
    for source in sources:
        if not isinstance(source, dict) or set(source) != fields:
            raise ValueError('source fields invalid')
        if any(not text_field(source[k]) for k in fields):
            raise ValueError('source text invalid')
        parsed = urlsplit(source['url'])
        if (parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password
                or source['kind'] not in ('institutional_primary', 'practitioner_primary')
                or source['id'] in result
                or hashlib.sha256(source['excerpt'].encode()).hexdigest() != source['excerpt_sha256']
                or datetime.fromisoformat(source['accessed_at'].replace('Z', '+00:00')).tzinfo is None):
            raise ValueError('source identity/hash/time invalid')
        result[source['id']] = source
    return result


def aggregate(queue: dict, decisions: dict, dictionary: dict, supplement: dict,
              bindings: dict) -> dict:
    selected = selected_cases(queue, decisions)
    fields = {'kind', 'reviewer_kind', 'reviewer_id', 'reviewed_at', 'bindings', 'sources', 'decisions'}
    if (not isinstance(supplement, dict) or set(supplement) != fields
            or supplement['kind'] != 'pilot_doubt_evidence_not_gold'
            or supplement['reviewer_kind'] != 'ai_teacher' or supplement['reviewer_id'] != 'codex-primary'
            or supplement['bindings'] != bindings or not selected or set(dictionary) != set(selected)):
        raise ValueError('supplement provenance mismatch')
    if datetime.fromisoformat(supplement['reviewed_at'].replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('aware timestamp required')
    sources = validate_sources(supplement['sources'])
    rows = supplement['decisions']
    if not isinstance(rows, list) or len(rows) != len(selected):
        raise ValueError('all flagged cases required')
    probes = cleaner_probes()
    expected_fields = {'case_id', 'queue_case_sha256', 'prior_decision_sha256', 'dictionary_matches_sha256',
                       'outcome', 'source_ids', 'probe_ids', 'reason', 'remaining_uncertainty'}
    used_sources = set()
    for case, row in zip(selected, rows, strict=True):
        if (not isinstance(row, dict) or set(row) != expected_fields or row['case_id'] != case
                or row['queue_case_sha256'] != canonical_json_hash(queue[case])
                or row['prior_decision_sha256'] != canonical_json_hash(decisions[case])
                or row['dictionary_matches_sha256'] != canonical_json_hash(dictionary[case])
                or row['outcome'] not in OUTCOMES
                or not text_field(row['reason']) or not text_field(row['remaining_uncertainty'])):
            raise ValueError('individual evidence binding invalid')
        for key, allowed in (('source_ids', sources), ('probe_ids', probes)):
            ids = row[key]
            if (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
                    or len(ids) != len(set(ids)) or not set(ids) <= set(allowed)):
                raise ValueError('unknown or repeated evidence reference')
        outcome = row['outcome']
        if outcome.startswith('external_') and not row['source_ids']:
            raise ValueError('external finding requires a source')
        if outcome == 'reproducible_context_problem' and (
                not row['probe_ids'] or not all(probes[p] for p in row['probe_ids'])
                or decisions[case]['axes']['context'] not in ('defect_blocking', 'defect_nonblocking')):
            raise ValueError('context finding requires observed defect and reproduced mechanism')
        if outcome == 'plausible_partial_input' and (
                decisions[case]['axes']['input_unit'] != 'boundary_question'
                or decisions[case]['axes']['reading'] != 'compatible'
                or decisions[case]['axes']['context'] != 'usable'):
            raise ValueError('partial input requires separate reading/context checks')
        used_sources.update(row['source_ids'])
    if used_sources != set(sources):
        raise ValueError('unused external source')
    counts = Counter(row['outcome'] for row in rows)
    return dict(
        schema_version=1, kind='pilot_doubt_evidence_not_gold', status='evidence_complete_no_gold',
        pilot_population=len(queue), selected=len(selected), reviewed=len(rows), pending=0,
        counts={outcome: counts[outcome] for outcome in OUTCOMES}, bindings=bindings,
        supplement_sha256=canonical_json_hash(supplement),
        dictionary_target_single_reading_matches=sum(
            dictionary[c].get(queue[c]['source_gold_surface']) == [queue[c]['reading']] for c in selected),
        dictionary_left_overlap_cases=sum(len(dictionary[c]) > 1 for c in selected),
        # Ledger ids can name the person or place behind one case; publish neutral
        # labels in ledger-id order so the local ledger still resolves each one.
        external_sources=len(sources),
        source_excerpt_sha256={f'source-{i}': sources[k]['excerpt_sha256'] for i, k in enumerate(sorted(sources), 1)},
        synthetic_cleaner_probes=probes, synthetic_probes_establish_actual_source_cause=False,
        reviewer_kind='ai_teacher', reviewer_count=1, human_review_count=0,
        prior_case_exposure=True, independent_review=False, independent_test=False,
        canonical_labels_changed=False, certified_accuracy=None, certified_gold_count=0,
        gate_a_human_audit_pass=False, gate_a_owner_authorized_audit_pass=False,
        raw_text_in_report=False, raw_stable_ids_in_report=False,
    )


def run(args) -> dict:
    manifest, queue, machine, machine_sha = load_inputs(args.packet, args.machine_report, args.machine_evidence)
    raw_report = read_bytes(args.prior_report)
    prior = json.loads(raw_report)
    checked = summarize(args.reviews, queue, manifest, machine, machine_sha, prior)
    if checked != {k: v for k, v in prior.items() if k != 'baseline_comparison'} or checked['pending']:
        raise ValueError('prior review aggregate changed or incomplete')
    decisions = {}
    for name in sorted(prior['batch_sha256']):
        for row in json.loads(read_bytes(args.reviews / name))['decisions']:
            decisions[row['case_id']] = row
    journal = args.reviews / 'amendments.jsonl'
    if journal.exists():
        for line in read_bytes(journal, 4 * 1024 * 1024).splitlines():
            row = json.loads(line)['decision']
            decisions[row['case_id']] = row
    raw_manifest = read_bytes(args.dictionary_manifest)
    dm = json.loads(raw_manifest)
    dictionary = dictionary_evidence(queue, selected_cases(queue, decisions), args.dictionary, dm)
    bindings = dict(queue_sha256=manifest['queue_sha256'], prior_report_sha256=hashlib.sha256(raw_report).hexdigest(),
                    policy_sha256=prior['policy_sha256'], machine_report_sha256=machine_sha,
                    dictionary_manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
                    dictionary_content_sha256=dm['content_sha256'])
    return aggregate(queue, decisions, dictionary, json.loads(read_bytes(args.supplement)), bindings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('packet', 'machine-report', 'machine-evidence', 'reviews', 'prior-report',
                 'dictionary', 'dictionary-manifest', 'supplement'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        parser.exit(2, 'Doubt evidence validation failed; no result authorized\n')
    print(canonical_json_bytes(report).decode('utf-8'))


if __name__ == '__main__':
    main()
