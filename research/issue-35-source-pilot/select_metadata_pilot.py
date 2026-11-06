"""Choose source IDs using only export metadata; never decode sentence/readings."""
import argparse
from collections import Counter
import hashlib
import json

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.tatoeba_source import raw_export_rows as raw_rows
from pilot35_common import ROOT,HERE,authenticate,save,read,sha


def run(commit):
    plan=authenticate(commit);acquired=read(ROOT/'acquisition.json')
    if acquired['status']!='complete' or acquired['not_attempted']:
        raise ValueError('pilot35_complete_exports_required')
    for item in acquired['attempts']:
        if sha(ROOT/'exports'/item['file'])!=item['sha256']:raise ValueError('pilot35_export_bytes_changed')
    sentences={};transcriptions={};counts=Counter();editors=set();owners=set();seen_keys=set()
    for number,raw,fields in raw_rows(ROOT/'exports/jpn_sentences_detailed.tsv.bz2',6):
        if fields[1]!=b'jpn':raise ValueError('pilot35_sentence_language')
        key=int(fields[0])
        if key in sentences:raise ValueError('pilot35_duplicate_sentence_id')
        owner=None if fields[3] in (b'',b'\\N') else hashlib.sha256(b'tatoeba-owner\0'+fields[3]).hexdigest()
        if owner:owners.add(owner)
        sentences[key]=dict(line=number,raw_line_sha256=hashlib.sha256(raw).hexdigest(),owner_token=owner)
    for number,raw,fields in raw_rows(ROOT/'exports/jpn_transcriptions.tsv.bz2',5):
        if fields[1]!=b'jpn':raise ValueError('pilot35_transcription_language')
        counts['all_transcriptions']+=1
        if fields[2]!=b'Hrkt':counts['other_script']+=1;continue
        key=int(fields[0])
        if key in seen_keys:raise ValueError('pilot35_duplicate_transcription_key')
        seen_keys.add(key)
        if key not in sentences:counts['no_licensed_sentence_membership']+=1;continue
        named=fields[3] not in (b'',b'\\N')
        editor=hashlib.sha256(b'tatoeba-editor\0'+fields[3]).hexdigest() if named else None
        if editor:editors.add(editor)
        stratum='named_editor' if named else 'no_editor'
        counts[stratum]+=1
        transcriptions[key]=dict(stratum=stratum,line=number,raw_line_sha256=hashlib.sha256(raw).hexdigest(),editor_token=editor)
    chosen=[]
    for stratum,required in plan['selection']['strata'].items():
        ids=[key for key,row in transcriptions.items() if row['stratum']==stratum]
        if len(ids)<required:raise ValueError('pilot35_metadata_capacity_insufficient')
        ordered=sorted(ids,key=lambda key:canonical_json_hash([plan['seed'],plan['selection']['domain'],key]))
        chosen += [dict(sentence_id=key,sentence=sentences[key],transcription=transcriptions[key]) for key in ordered[:required]]
    if len(chosen)!=100 or len({r['sentence_id'] for r in chosen})!=100:raise ValueError('pilot35_selection_denominator')
    selection=dict(kind='tatoeba_metadata_selected_pilot',snapshot=plan['snapshot'],rows=chosen,
        plan_commit=commit,plan_sha256=sha(HERE/'plan-v1.json'),acquisition_sha256=sha(ROOT/'acquisition.json'),
        chosen_before_semantic_decode=True,model_predictions=0)
    save(ROOT/'selection.json',selection)
    report=dict(kind='tatoeba_metadata_profile',status='selected_not_admitted',sentences=len(sentences),
        transcription_counts=dict(counts),sentence_owner_tokens=len(owners),transcription_editor_tokens=len(editors),
        selected_counts=dict(Counter(r['transcription']['stratum'] for r in chosen)),
        semantic_sentence_decodes=0,semantic_transcription_decodes=0,
        selection_sha256=sha(ROOT/'selection.json'),acquisition_sha256=sha(ROOT/'acquisition.json'),
        corpus_quality_precision=None,independent_ime_gold=0,calibration_admitted=0)
    save(ROOT/'metadata-profile.json',report)
    save(HERE/'selection-binding-v1.json',dict(kind='tatoeba_pilot_selection_binding',plan_commit=commit,
        selection_sha256=sha(ROOT/'selection.json'),metadata_profile_sha256=sha(ROOT/'metadata-profile.json'),
        acquisition_sha256=sha(ROOT/'acquisition.json'),slots=100,selection_strata=plan['selection']['strata'],
        semantic_decode_authorized_only_after_this_binding_is_committed=True,gold_certified=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan-commit',required=True)
    print(json.dumps(run(parser.parse_args().plan_commit)))
