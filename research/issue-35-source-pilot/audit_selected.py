"""Decode only preselected IDs and keep all source-pilot terminal slots private."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json

from sakura_rerank.data.contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from sakura_rerank.data.tatoeba_source import (
    SourceFormatError, audit_pair, decode_export_field, is_kana_reading, raw_export_rows,
)
from pilot35_common import ROOT, HERE, authenticate, committed, read, save, sha


def run(selection_commit, implementation_commit):
    bound = json.loads(committed(HERE/'selection-binding-v1.json', selection_commit))
    plan = authenticate(bound['plan_commit'])
    code = {str(p).replace('\\', '/'): sha(p) for p in (
        HERE/'audit_selected.py', 'src/sakura_rerank/data/tatoeba_source.py')}
    for path in code:
        committed(path, implementation_commit)
    for path, key in (('selection.json','selection_sha256'), ('metadata-profile.json','metadata_profile_sha256'),
                      ('acquisition.json','acquisition_sha256')):
        if sha(ROOT/path) != bound[key]:
            raise ValueError('pilot35_selection_bound_artifact_changed')
    selected = read(ROOT/'selection.json')['rows']
    if len(selected) != 100:
        raise ValueError('pilot35_audit_denominator')
    selected_map = {r['sentence_id']:r for r in selected}
    save(ROOT/'semantic-reservation.json', dict(selection_commit=selection_commit,
        implementation_commit=implementation_commit, code=code, selection_sha256=bound['selection_sha256'],
        authorized_slots=100, exposure='research_only', final_test_used=False))
    fields_by_kind = {}
    for kind, filename, columns in (('sentence','jpn_sentences_detailed.tsv.bz2',6),
                                     ('transcription','jpn_transcriptions.tsv.bz2',5)):
        item = next(r for r in read(ROOT/'acquisition.json')['attempts'] if r['file']==filename)
        if sha(ROOT/'exports'/filename) != item['sha256']:
            raise ValueError('pilot35_semantic_source_changed')
        records = {}
        for number, raw, fields in raw_export_rows(ROOT/'exports'/filename, columns):
            key = int(fields[0])
            if key not in selected_map or (kind=='transcription' and fields[2]!=b'Hrkt'):
                continue
            expected = selected_map[key][kind]
            if number!=expected['line'] or hashlib.sha256(raw).hexdigest()!=expected['raw_line_sha256'] or key in records:
                raise ValueError('pilot35_selected_row_identity')
            records[key] = fields
        if set(records) != set(selected_map):
            raise ValueError('pilot35_selected_row_missing')
        fields_by_kind[kind] = records
    slots, coverage, inputs = [], [], []
    strata = defaultdict(Counter)
    for slot_number, row in enumerate(selected):
        key = row['sentence_id']; stratum = row['transcription']['stratum']
        slot = dict(slot=slot_number, sentence_id=key, stratum=stratum, source_exact=False,
                    human_verdicts=0, gold_certified=False)
        try:
            sentence = decode_export_field(fields_by_kind['sentence'][key][2])
            transcription = decode_export_field(fields_by_kind['transcription'][key][4])
            result, parsed = audit_pair(sentence, transcription)
            slot.update(result, sentence=sentence, transcription=transcription,
                        parsed=None if parsed is None else asdict(parsed))
            if sentence:
                source = dict(article_id='tatoeba:'+str(key), paragraph_hash=text_sha256(sentence),
                    sentence_hash=text_sha256(sentence), sentence_shingle_hashes=sentence_shingle_hashes(sentence),
                    template_cluster_id=None if row['sentence']['owner_token'] is None else 'tatoeba-owner:'+row['sentence']['owner_token'])
                if len(source['sentence_shingle_hashes'])>1024:
                    raise SourceFormatError('source_signature_bound')
                coverage.append(dict(stable_id='tatoeba-source-'+canonical_json_hash([plan['snapshot'],key]),
                                     population='source_coverage',source=source))
                for index, span in enumerate(parsed.spans if parsed and result['source_exact'] else ()):
                    reason = ('unverified_reading_characters' if not is_kana_reading(span.reading) else
                              'input_bound' if len(span.reading)>128 or len(source['sentence_shingle_hashes'])>512 else
                              'control_characters' if result['control_characters'] else 'source_hypothesis')
                    strata[stratum]['span/'+reason] += 1
                    if reason!='source_hypothesis':
                        continue
                    context = sentence[:span.start][-64:]
                    if sentence[span.start:span.end]!=span.base:
                        raise ValueError('pilot35_original_span_changed')
                    inputs.append(dict(stable_id='tatoeba-ruby-'+canonical_json_hash([plan['snapshot'],key,index]),
                        population='evaluation',source=source,input_hash=canonical_json_hash([context,span.reading]),
                        sentence_id=key,annotation_index=index,left_context=context,reading=span.reading,
                        target=span.base,provenance='source_ruby_hypothesis_not_verified_ime_input'))
        except SourceFormatError as error:
            slot.update(status=str(error),source_exact=False)
        strata[stratum]['slots'] += 1
        strata[stratum]['status/'+slot['status']] += 1
        for name in ('ruby_spans','kana_reading_spans','unannotated_han','control_characters'):
            strata[stratum][name] += slot.get(name,0)
        slots.append(slot)
    if len(inputs)>10000 or len(coverage)!=100:
        raise ValueError('pilot35_complete_source_coverage_required')
    save(ROOT/'decoded-pilot.json',dict(slots=slots,source_coverage=coverage,input_hypotheses=inputs))
    report = dict(kind='tatoeba_source_alignment_pilot',status='complete_source_audit_not_admission',
        plan_commit=bound['plan_commit'],selection_commit=selection_commit,implementation_commit=implementation_commit,code=code,
        strata={k:dict(v) for k,v in strata.items()},slots=100,source_units=len(coverage),
        input_hypotheses=len(inputs),human_verdicts=0,source_editor_verdicts_imported_as_human=0,
        independently_verified_readings=0,independent_ime_gold=0,quality_precision=None,
        model_inference=0,fits=0,final_test_used=False,calibration_admitted=0,
        reservation_sha256=sha(ROOT/'semantic-reservation.json'),decoded_sha256=sha(ROOT/'decoded-pilot.json'),
        acquisition_sha256=sha(ROOT/'acquisition.json'),selection_sha256=sha(ROOT/'selection.json'))
    save(ROOT/'alignment-audit.json',report)
    return {k:report[k] for k in ('status','strata','slots','source_units','input_hypotheses','independent_ime_gold')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--selection-commit',required=True)
    parser.add_argument('--implementation-commit',required=True)
    args=parser.parse_args();print(json.dumps(run(args.selection_commit,args.implementation_commit)))
