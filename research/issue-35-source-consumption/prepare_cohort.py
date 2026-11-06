"""Freeze policy, select by metadata, then consume only committed source slots."""
import argparse
from collections import Counter
import hashlib
import json
import platform
import subprocess
import sys

from sakura_rerank.data.tatoeba_consumption import POLICY_VERSION, consume_slot, reserve_metadata_slots
from sakura_rerank.data.tatoeba_source import SourceFormatError, decode_export_field, raw_export_rows
from consume35_common import HERE, PAST, PLAN, ROOT, UNITS, authenticate, committed, read, save, sha

SELECTION = HERE/'selection-binding-v1.json'


def plan():
    acquisition = read(PAST/'acquisition.json')
    if acquisition['status'] != 'complete' or acquisition['not_attempted']:
        raise ValueError('consumption_source_acquisition_incomplete')
    old = read('research/issue-35-source-units/plan-v1.json')
    files = [PAST/'acquisition.json', PAST/'selection.json', PAST/'decoded-pilot.json',
             UNITS/'source-units.json', UNITS/'requests.json', UNITS/'native-report-v2.json',
             UNITS/'request-ledger-v2.json', 'research/issue-35-source-pilot/history-binding-v1.json',
             'research/issue-35-source-units/plan-v1.json', 'reports/issue-35-source-units-v1.json']
    for row in acquisition['attempts']:
        path = PAST/'exports'/row['file']
        if sha(path) != row['sha256']:
            raise ValueError('consumption_export_changed')
        files.append(path)
    code = list(HERE.glob('*.py')) + [HERE/'contract-v1.md',
        'src/sakura_rerank/data/tatoeba_consumption.py', 'src/sakura_rerank/data/tatoeba_input_units.py',
        'src/sakura_rerank/data/tatoeba_source.py', 'src/sakura_rerank/data/input_boundary.py',
        'tests/test_tatoeba_consumption.py']
    current = subprocess.check_output(['git', '-C', '../sakura-input', 'rev-parse', 'HEAD'], text=True, timeout=30).strip()
    if subprocess.check_output(['git', '-C', '../sakura-input', 'status', '--porcelain'], timeout=30):
        raise ValueError('consumption_sakura_input_not_clean')
    runtime = {**old['native'], 'current_sakura_input_head': current, 'maximum_unique_requests': 4000,
               'permission': 'Exact committed request binding required before execution.'}
    spec = dict(kind='continuous_source_consumption_plan_v1', parent_issue=1, issues=[31, 32, 35],
        policy=POLICY_VERSION, source_snapshot='tatoeba-jpn-weekly-20261031',
        seed='prospective-source-consumption-20261106-v1', slots=1000, previous_slots=100,
        previous_exposure='Bytes and metadata already acquired;100 semantic slots consumed. Prospective research only.',
        selection='Smallest SHA256(policy,seed,ID), licensed Hrkt intersection; no editor quota or content filter.',
        label='Original source reconstruction hypothesis; no unique IME correctness certification.',
        source=read('research/issue-35-source-pilot/plan-v1.json')['source'],
        contract_sha256=sha(HERE/'contract-v1.md'), native=runtime,
        unchanged=old['unchanged'], forbidden=old['forbidden'],
        environment=dict(python=sys.version,platform=platform.platform(),new_dependencies=0),
        inputs={str(p).replace('\\','/'):sha(p) for p in files},
        code={str(p).replace('\\','/'):sha(p) for p in code})
    save(PLAN, spec)
    return dict(stage='plan',slots=1000,plan_sha256=sha(PLAN),semantic_decodes=0,native_calls=0)


def metadata_rows():
    sentences = {}
    for number, raw, fields in raw_export_rows(PAST/'exports/jpn_sentences_detailed.tsv.bz2', 6):
        key = int(fields[0])
        if fields[1] != b'jpn' or key in sentences:
            raise ValueError('consumption_sentence_metadata')
        owner = None if fields[3] in (b'',b'\\N') else hashlib.sha256(b'tatoeba-owner\0'+fields[3]).hexdigest()
        sentences[key] = dict(line=number,raw_line_sha256=hashlib.sha256(raw).hexdigest(),owner_token=owner)
    seen = set()
    for number, raw, fields in raw_export_rows(PAST/'exports/jpn_transcriptions.tsv.bz2',5):
        if fields[1] != b'jpn':
            raise ValueError('consumption_transcription_language')
        if fields[2] != b'Hrkt':
            continue
        key = int(fields[0])
        if key in seen:
            raise ValueError('consumption_duplicate_transcription')
        seen.add(key)
        if key not in sentences:
            continue
        editor = None if fields[3] in (b'',b'\\N') else hashlib.sha256(b'tatoeba-editor\0'+fields[3]).hexdigest()
        yield dict(sentence_id=key,sentence=sentences[key],transcription=dict(line=number,
            raw_line_sha256=hashlib.sha256(raw).hexdigest(),editor_token=editor,
            stratum='named_editor' if editor is not None else 'no_editor'))


def select(commit):
    spec = authenticate(commit)
    previous = [r['sentence_id'] for r in read(PAST/'selection.json')['rows']]
    save(ROOT/'selection-reservation.json',dict(plan_commit=commit,slots=spec['slots'],semantic_decodes=0))
    # The second metadata scan reverses source order without decoding text.
    rows = list(metadata_rows())
    selected = reserve_metadata_slots(rows,previous,count=spec['slots'],seed=spec['seed'])
    if selected != reserve_metadata_slots(reversed(rows),previous,count=spec['slots'],seed=spec['seed']):
        raise ValueError('consumption_selection_replay')
    save(ROOT/'selection.json',dict(rows=selected,plan_commit=commit,exposed_ids_excluded=len(previous)))
    summary = dict(kind='prospective_source_metadata_selection',slots=len(selected),population=len(rows),
        available_after_previous_exposure=len(rows)-len(previous),previous_excluded=len(previous),
        strata=dict(Counter(r['transcription']['stratum'] for r in selected)),
        semantic_decodes=0,replacements=0,reverse_order_parity=True,
        selection_sha256=sha(ROOT/'selection.json'),plan_commit=commit)
    save(ROOT/'selection-report.json',summary)
    save(SELECTION,dict(kind='prospective_source_selection_binding_v1',plan_commit=commit,
        selection_sha256=sha(ROOT/'selection.json'),report_sha256=sha(ROOT/'selection-report.json'),
        slots=spec['slots'],decode_only_after_commit=True,final_test=False,gold_admission=False))
    return summary


def decode(commit):
    bound = json.loads(committed(SELECTION,commit))
    spec = authenticate(bound['plan_commit'])
    for name,key in (('selection.json','selection_sha256'),('selection-report.json','report_sha256')):
        if sha(ROOT/name) != bound[key]:
            raise ValueError('consumption_selected_artifact_changed')
    selected = read(ROOT/'selection.json')['rows']
    if len(selected) != bound['slots'] or len({r['sentence_id'] for r in selected}) != bound['slots']:
        raise ValueError('consumption_full_denominator')
    save(ROOT/'semantic-reservation.json',dict(selection_commit=commit,slots=bound['slots'],
        selection_sha256=bound['selection_sha256'],exposure='prospective_source_research',final_test=False))
    wanted = {r['sentence_id']:r for r in selected}
    fields_by_kind = {}
    for kind,filename,columns in (('sentence','jpn_sentences_detailed.tsv.bz2',6),
                                  ('transcription','jpn_transcriptions.tsv.bz2',5)):
        records = {}
        for number,raw,fields in raw_export_rows(PAST/'exports'/filename,columns):
            key = int(fields[0])
            if key not in wanted or (kind=='transcription' and fields[2]!=b'Hrkt'):
                continue
            expected = wanted[key][kind]
            if key in records or number!=expected['line'] or hashlib.sha256(raw).hexdigest()!=expected['raw_line_sha256']:
                raise ValueError('consumption_selected_raw_identity')
            records[key] = fields
        if set(records) != set(wanted):
            raise ValueError('consumption_selected_missing')
        fields_by_kind[kind] = records
    slots, requests = [], {}
    for index,meta in enumerate(selected):
        key = meta['sentence_id']
        sentence = transcription = None
        error_reason = None
        try:
            sentence = decode_export_field(fields_by_kind['sentence'][key][2])
            transcription = decode_export_field(fields_by_kind['transcription'][key][4])
        except SourceFormatError as error:
            error_reason = str(error)
        result = consume_slot(meta,sentence,transcription,snapshot=spec['source_snapshot'],slot=index)
        if error_reason:
            result['status'] = error_reason
        result.update(sentence=sentence,transcription=transcription)
        for item in result['inputs']:
            request = dict(stable_id=item['request_id'],reading=item['reading'])
            if request['stable_id'] in requests and requests[request['stable_id']] != request:
                raise ValueError('consumption_request_collision')
            requests[request['stable_id']] = request
        slots.append(result)
    if len(requests)>spec['native']['maximum_unique_requests']:
        raise ValueError('consumption_request_budget')
    save(ROOT/'consumed-slots.json',dict(rows=slots,selection_commit=commit))
    save(ROOT/'requests.json',dict(requests=[requests[k] for k in sorted(requests)]))
    summary = dict(kind='prospective_source_consumption',status='prepared_not_admitted',slots=len(slots),
        source_statuses=dict(Counter(r['status'] for r in slots)),source_exact=sum(r['source_exact'] for r in slots),
        coverage=sum(r['source_coverage'] is not None for r in slots),inputs=sum(len(r['inputs']) for r in slots),
        requests=len(requests),strata=dict(Counter(r['stratum'] for r in slots)),
        consumed_sha256=sha(ROOT/'consumed-slots.json'),requests_sha256=sha(ROOT/'requests.json'),
        selection_commit=commit,plan_commit=bound['plan_commit'],gold_admission=0,final_test=False,model_fits=0)
    save(ROOT/'preparation.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('plan','select','decode'))
    parser.add_argument('--commit');args=parser.parse_args()
    print(json.dumps(plan() if args.stage=='plan' else (select if args.stage=='select' else decode)(args.commit)))
