"""Freeze one source-only comparison frame; never train or score models here."""
import argparse
import bz2
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import unittest

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.knbc_research import project_member, reserve_remaining
from sakura_rerank.data.knbc_source import parse_member

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ROOT = REPO/'data/generated/issue-33-knbc-screening-v1/attempt-02'
PILOT = REPO/'data/generated/issue-35-knbc-format-pilot-v1/attempt-01'
QUAL = REPO/'data/generated/issue-35-knbc-qualification-v1'
ARCHIVE = QUAL/'attempt-01/archive.quarantine.tar.bz2'
PLAN = HERE/'plan-v1.json'
ARCHIVE_SHA = '2df066f321f57413dc94404a60273b84a85c67b55fc5d2c8a34926074c1b83a4'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical_json_bytes(value)+b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def committed(path, commit):
    raw = subprocess.check_output(['git', 'show', commit+':'+Path(path).relative_to(REPO).as_posix()], timeout=30)
    require(raw == Path(path).read_bytes(), 'knbc_screening_uncommitted_bytes')
    return raw


def archive():
    raw = ARCHIVE.read_bytes()
    require(len(raw) == 4968025 and hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA, 'knbc_screening_archive_identity')
    decoder = bz2.BZ2Decompressor()
    expanded = decoder.decompress(raw, max_length=128*1024*1024+1)
    require(len(expanded) <= 128*1024*1024 and decoder.eof and not decoder.unused_data, 'knbc_screening_archive_bound')
    return tarfile.open(fileobj=io.BytesIO(expanded), mode='r:')


def member_bytes(arc, slot):
    member = arc.getmember(slot['archive_name'])
    require(member.isfile() and member.size == slot['bytes'] <= 65536, 'knbc_screening_member_metadata')
    with arc.extractfile(member) as stream:
        raw = stream.read(65537)
    require(len(raw) == slot['bytes'] and hashlib.sha256(raw).hexdigest() == slot['source_raw_sha256'],
            'knbc_screening_member_identity')
    return raw


def pilot_history():
    report = read(PILOT/'pilot-report.json')
    require(sha(PILOT/'parsed-slots.private.json') == report['slots_sha256']
            and sha(PILOT/'consumption-ledger.private.jsonl') == report['ledger_sha256'], 'knbc_screening_pilot_artifacts')
    previous = sha(REPO/'research/issue-35-knbc-format-pilot/decode-binding-v1.json')
    events = [json.loads(line) for line in (PILOT/'consumption-ledger.private.jsonl').read_bytes().splitlines()]
    for event in events:
        value = dict(event)
        digest = value.pop('event_sha256')
        require(value['previous_sha256'] == previous and canonical_json_hash(value) == digest, 'knbc_screening_pilot_ledger')
        previous = digest
    require(previous == report['ledger_head'] and len(events) == 100, 'knbc_screening_pilot_extent')
    selection, rows = read(PILOT/'selection.private.json'), read(PILOT/'parsed-slots.private.json')
    for event, row, slot in zip(events, rows, selection['slots'], strict=True):
        require(all(event[k] == row[k] for k in ('index', 'article', 'family', 'path', 'role',
                'source_raw_sha256', 'status', 'semantic_read_attempted')), 'knbc_screening_pilot_event_identity')
        require(all(row[k] == slot[k] for k in ('index', 'article', 'family', 'path', 'source_raw_sha256')),
                'knbc_screening_pilot_slot_identity')
    return selection, rows


def project_existing():
    selection, old_rows = pilot_history()
    counts, units, attempts = Counter(), 0, 0
    with archive() as arc:
        for old, slot in zip(old_rows, selection['slots'], strict=True):
            require(old['path'] == slot['path'] and old['index'] == slot['index'], 'knbc_screening_pilot_order')
            raw = member_bytes(arc, slot)
            attempts += 1
            if old['annotation'] is None:
                try:
                    parse_member(raw)
                except ValueError as error:
                    require(str(error) == 'knbc_empty_sentence', 'knbc_screening_changed_failed_pilot')
                else:
                    raise ValueError('knbc_screening_failed_pilot_became_valid')
                counts['previous_empty_annotation'] += 1
                continue
            require(parse_member(raw) == old['annotation'], 'knbc_screening_pilot_parse_changed')
            value = project_member(raw, slot)
            counts[value['status']] += 1
            units += value['bunsetsu_count']
    result = dict(status='existing_pilot_replayed', slots=attempts, whole_bunsetsu=units,
                  statuses=dict(counts), new_semantic_members=0, fits=0, inference=0, gold_admission=False)
    save(ROOT/'pilot-rule-check.json', result)
    return result


def freeze():
    ROOT.mkdir(parents=True, exist_ok=True)
    require(read(ROOT/'pilot-rule-check.json')['slots'] == 100, 'knbc_screening_pilot_first')
    selection, _ = pilot_history()
    inventory = read(QUAL/'attempt-02/member-inventory.json')
    reservation = reserve_remaining(inventory, selection, read(PILOT/'member-hashes.private.json'))
    require(reservation['census']['slots'] == 2786 and reservation['census']['families'] == 62,
            'knbc_screening_expected_capacity')
    save(ROOT/'selection.private.json', reservation)
    inputs = [ARCHIVE, QUAL/'attempt-02/member-inventory.json', PILOT/'selection.private.json',
        PILOT/'member-hashes.private.json', PILOT/'parsed-slots.private.json', PILOT/'consumption-ledger.private.jsonl',
        PILOT/'pilot-report.json', QUAL/'attempt-02/document-00.raw', QUAL/'attempt-02/document-01.raw',
        QUAL/'attempt-02/manual-readable-pages.private.json', PILOT/'format-README.private.md',
        ROOT/'selection.private.json', ROOT/'pilot-rule-check.json']
    inputs.extend([REPO/'research/issue-35-knbc-format-pilot/decode-binding-v1.json',
        ROOT.parent/'attempt-01/pilot-failure.json', ROOT.parent/'attempt-01/pilot-terminal.json'])
    spec = importlib.util.spec_from_file_location('knbc_screening_history', HERE/'history.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs.extend(module.binding_inputs())
    code = list(HERE.glob('*.py'))+[REPO/'src/sakura_rerank/data/knbc_research.py',
        REPO/'src/sakura_rerank/data/knbc_source.py', REPO/'src/sakura_rerank/data/contracts.py',
        REPO/'tests/test_knbc_research.py']
    code.extend(module.binding_code())
    plan = dict(kind='knbc_screened_dictionary_research_frame', version=1, issue=33, parent_issue=1,
        created_at_utc=datetime.now(timezone.utc).isoformat(), prior_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        source_archive_sha256=ARCHIVE_SHA, official_cryptographic_digest=None,
        source_license='Existing pinned three-clause BSD-style provider terms; no source redistribution.',
        inputs={p.relative_to(REPO).as_posix():sha(p) for p in inputs},
        code={p.relative_to(REPO).as_posix():sha(p) for p in code},
        census=reservation['census'], candidate_limit=2786, model_calls=0, fits=0,
        selection='All62 remaining prefix families; every2786 sentence member is one fixed slot. Choose one complete provider bunsetsu by position hash before checking validity. No replacements, clipping, punctuation removal or guessed readings.',
        source_label='Literal annotated surface for source reconstruction only. Whole sentences with ER/reading ambiguity/style are pending. Lemma ambiguity alone is not a reading error. Empty observed session context.',
        history='Preserve all prior families and pilot failures; full source/input relations and consumed-source exposure remain mandatory. Future candidate/numeric projection has its own history check before fit.',
        readiness=dict(minimum_retained_slots=500, minimum_recorded_components=20,
            meaning='Candidate-binding preparation only; not fit, Gold, calibration or final Test admission.'),
        stopping='One source preparation. If prerequisites/readiness fail, do not fit or replace source slots. No automatic new source/tooling expansion.',
        limits=dict(stage_seconds=600, history_seconds=900, retries=0, concurrency=1, member_bytes=65536, expanded_bytes=134217728, graph_nodes=1000000),
        safety_limit=.0025, gold_point=.995, gold_wilson95_lower=.990, gold_final_valid_minimum=3000,
        training_admission=False, gold_admission=False, calibration=False, final_test=False, production_change=False)
    save(PLAN, plan)
    return dict(status='frozen_before_new_source_decode', plan_sha256=sha(PLAN), census=reservation['census'])


def authenticate(commit):
    plan = json.loads(committed(PLAN, commit))
    for path, digest in {**plan['inputs'], **plan['code']}.items():
        require(sha(REPO/path) == digest, 'knbc_screening_bound_bytes_changed')
    for path in plan['code']:
        committed(REPO/path, commit)
    return plan


def prepare(commit):
    plan = authenticate(commit)
    selected = read(ROOT/'selection.private.json')['slots']
    save(ROOT/'consumption-reservation.json', dict(commit=commit, plan_sha256=sha(PLAN),
        slots=len(selected), all_reserved_families_consumed_even_on_failure=True, owner_pid=os.getpid()))
    results, previous = [], sha(ROOT/'consumption-reservation.json')
    documentation = ''.join(read(QUAL/'attempt-02/manual-readable-pages.private.json'))
    documentation += ''.join(p.read_text(encoding='utf-8') for p in
        (QUAL/'attempt-02/document-00.raw', QUAL/'attempt-02/document-01.raw', PILOT/'format-README.private.md'))
    documentation = ''.join(documentation.split())
    with (ROOT/'consumption-ledger.private.jsonl').open('xb') as ledger, archive() as arc:
        for slot in selected:
            event = dict(index=slot['index'], source_sha256=slot['source_raw_sha256'], previous=previous,
                         state='semantic_access_reserved')
            event['event_sha256'] = canonical_json_hash(event)
            previous = event['event_sha256']
            ledger.write(canonical_json_bytes(event)+b'\n')
            ledger.flush()
            os.fsync(ledger.fileno())
            raw = member_bytes(arc, slot)
            try:
                result = project_member(raw, slot)
                surface = ''.join(parse_member(raw)['annotation_surface'].split())
                result['documentation_exact_hit'] = len(surface) >= 8 and surface in documentation
                if result['documentation_exact_hit']:
                    result.update(status='pending_exposed_documentation', input=None)
            except (ValueError, UnicodeError) as error:
                code = str(error) if isinstance(error, ValueError) and str(error).isidentifier() else 'invalid_source_encoding'
                result = dict(index=slot['index'], status='pending_'+code, source_coverage=None, input=None,
                              gold_admission=False, training_admission=False, final_test=False)
            results.append(result)
    require(len(results) == plan['candidate_limit'], 'knbc_screening_incomplete_preparation')
    save(ROOT/'source-slots.private.json', dict(rows=results))
    report = dict(status='prepared_not_admitted', slots=len(results),
        statuses=dict(Counter(r['status'] for r in results)),
        source_coverage=sum(r['source_coverage'] is not None for r in results),
        input_hypotheses=sum(r['input'] is not None for r in results),
        slots_sha256=sha(ROOT/'source-slots.private.json'),
        ledger_sha256=sha(ROOT/'consumption-ledger.private.jsonl'), ledger_head=previous,
        model_calls=0, fits=0, final_test=False, gold_admission=False)
    save(ROOT/'preparation.json', report)
    return report


def checks(targeted):
    suite = unittest.defaultTestLoader.discover(str(REPO/'tests'), pattern='test_knbc_research.py' if targeted else 'test*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    value = dict(tests=result.testsRun, passed=result.wasSuccessful(), errors=len(result.errors),
                 failures=len(result.failures), skipped=len(result.skipped))
    save(ROOT/('targeted-tests.json' if targeted else 'full-tests.json'), value)
    require(result.wasSuccessful() and not result.skipped, 'knbc_screening_tests_failed')
    return value


def extra(stage, commit):
    spec = importlib.util.spec_from_file_location('knbc_screening_history', HERE/'history.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, stage)(commit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('pilot', 'freeze', 'prepare', 'history', 'verify', 'targeted', 'tests'))
    parser.add_argument('--commit', default='')
    args = parser.parse_args()
    try:
        value = (project_existing() if args.stage == 'pilot' else freeze() if args.stage == 'freeze'
                 else prepare(args.commit) if args.stage == 'prepare' else checks(args.stage == 'targeted')
                 if args.stage in ('targeted', 'tests') else extra(args.stage, args.commit))
        print(json.dumps(value), flush=True)
    except Exception as error:
        value = dict(status='failed', stage=args.stage, error_type=type(error).__name__,
                     error_code=str(error) if isinstance(error, ValueError) and str(error).isidentifier() else None)
        save(ROOT/(args.stage+'-failure.json'), value)
        print(json.dumps(value), flush=True)
        raise SystemExit(1)
