"""Direct scalar/regex and metadata-sampling verification, with no new labels."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.tatoeba_source import raw_export_rows
from pilot35_common import ROOT, HERE, authenticate, read, save, sha


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def run():
    plan=authenticate('98c74d4eb51c9a479101503c6a08907400601cdc')
    selection=read(ROOT/'selection.json');metadata=read(ROOT/'metadata-profile.json')
    alignment=read(ROOT/'alignment-audit.json');decoded=read(ROOT/'decoded-pilot.json')
    isolation=read(ROOT/'isolation-audit.json');relations=read(ROOT/'source-relations.json')
    assert alignment['decoded_sha256']==sha(ROOT/'decoded-pilot.json')
    assert isolation['relations_sha256']==sha(ROOT/'source-relations.json')
    assert metadata['selection_sha256']==sha(ROOT/'selection.json')
    acquisition=read(ROOT/'acquisition.json')
    for item in acquisition['attempts']:
        path=ROOT/'exports'/item['file']
        assert path.stat().st_size==item['bytes_received'] and sha(path)==item['sha256']
    licensed={int(fields[0]) for _,_,fields in raw_export_rows(ROOT/'exports/jpn_sentences_detailed.tsv.bz2',6)}
    counts=Counter();candidates={'named_editor':[],'no_editor':[]}
    for _,_,fields in raw_export_rows(ROOT/'exports/jpn_transcriptions.tsv.bz2',5):
        counts['all_transcriptions']+=1
        if fields[2]!=b'Hrkt':counts['other_script']+=1;continue
        key=int(fields[0])
        if key not in licensed:counts['no_licensed_sentence_membership']+=1;continue
        stratum='no_editor' if fields[3] in (b'',b'\\N') else 'named_editor'
        counts[stratum]+=1;candidates[stratum].append(key)
    assert counts==metadata['transcription_counts'] and len(licensed)==metadata['sentences']
    chosen=[]
    for stratum,size in plan['selection']['strata'].items():
        chosen.extend(sorted(candidates[stratum],key=lambda key:digest([plan['seed'],plan['selection']['domain'],key]))[:size])
    assert chosen==[r['sentence_id'] for r in selection['rows']]
    # A second grammar strategy reconstructs literal segments and full bases.
    status=Counter();spans=Counter();malformed=Counter();positions=0
    for slot in decoded['slots']:
        text=slot['transcription'];matches=list(re.finditer(r'\[([^\[\]]*)\]',text))
        valid=True;last=0;surface=[];projection=[];seen=[];position=0
        for match in matches:
            literal=text[last:match.start()]
            if any(char in literal for char in '[]|'):valid=False
            surface.append(literal);projection.append(literal);position+=len(literal)
            parts=match.group(1).split('|')
            if len(parts)<2:valid=False;malformed['missing_separator']+=1
            elif not parts[0]:valid=False;malformed['empty_base']+=1
            elif not ''.join(parts[1:]):valid=False;malformed['empty_reading']+=1
            if len(parts)>=2:
                reading=''.join(parts[1:]);base=parts[0]
                seen.append((position,position+len(base),base,reading,tuple(parts[1:])))
                surface.append(base);projection.append(reading);position+=len(base)
            last=match.end()
        literal=text[last:]
        if any(char in literal for char in '[]|'):valid=False
        surface.append(literal);projection.append(literal)
        if valid:
            assert slot['source_exact']==(''.join(surface)==slot['sentence'])
            assert slot['parsed']['surface']==''.join(surface)
            assert slot['parsed']['phonetic_projection']==''.join(projection)
            actual=[(s['start'],s['end'],s['base'],s['reading'],tuple(s['reading_parts'])) for s in slot['parsed']['spans']]
            assert actual==seen
            positions+=len(seen);spans[slot['stratum']]+=len(seen)
        else:
            assert not slot['source_exact'] and slot['parsed'] is None
        status[slot['stratum']+'/'+slot['status']]+=1
    assert len(decoded['slots'])==100 and len(decoded['source_coverage'])==100
    for stratum,values in alignment['strata'].items():
        assert values['ruby_spans']==spans[stratum]
        for key,count in values.items():
            if key.startswith('status/'):
                assert status[stratum+'/'+key.split('/',1)[1]]==count
    slots={s['sentence_id']:s for s in decoded['slots']}
    input_ids=set();input_status=Counter();boundary_counts=Counter()
    for row in decoded['input_hypotheses']:
        slot=slots[row['sentence_id']];span=slot['parsed']['spans'][row['annotation_index']]
        assert row['target']==slot['sentence'][span['start']:span['end']]==span['base']
        assert row['reading']==span['reading'] and row['left_context']==slot['sentence'][:span['start']][-64:]
        assert row['input_hash']==digest([row['left_context'],row['reading']])
        following=slot['sentence'][span['end']:span['end']+1]
        preceding=slot['sentence'][max(0,span['start']-1):span['start']]
        boundary_counts['total']+=1
        boundary_counts['single_codepoint_base']+=len(span['base'])==1
        boundary_counts['following_hiragana']+=bool(following and '\u3041'<=following<='\u3096')
        boundary_counts['following_basic_han']+=bool(following and '\u4e00'<=following<='\u9fff')
        boundary_counts['preceding_basic_han']+=bool(preceding and '\u4e00'<=preceding<='\u9fff')
        assert row['stable_id'] not in input_ids;input_ids.add(row['stable_id'])
        label='historically_related' if row['stable_id'] in relations['excluded'] else 'isolated_hypothesis'
        input_status[slot['stratum']+'/'+label]+=1
    assert set(relations['components'])==input_ids
    assert input_status==isolation['strata']
    assert isolation['history_nodes']==988073 and isolation['audit']['records']==988073+100+len(input_ids)
    assert isolation['full_reverse_replay'] and not isolation['gold_certified']
    code=list(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/tatoeba_source.py'),Path('tests/test_tatoeba_source.py'),Path('tests/test_tatoeba_acquisition.py')]
    for path in code:
        raw=path.read_bytes();ast.parse(raw);compile(raw,str(path),'exec')
    result=dict(kind='tatoeba_source_pilot_direct_verification',status='passed',
        metadata_ids_reselected=len(chosen),licensed_sentence_ids=len(licensed),transcription_counts=dict(counts),
        source_slots_recounted=100,regex_span_positions_reconstructed=positions,statuses=dict(status),
        malformed_annotation_reasons=dict(malformed),input_hypotheses_reconstructed=len(input_ids),
        boundary_observations_not_quality_verdicts=dict(boundary_counts),
        isolation_counts_recounted=True,python_files_compiled=len(code),
        compared_decoded_sha256=sha(ROOT/'decoded-pilot.json'),model_inference=0,new_human_verdicts=0,gold_certified=False)
    save(ROOT/'direct-verification.json',result)
    print(json.dumps(result))
    # Read-only historical integrity checker; its output contains hashes/counts only.
    completed=subprocess.run([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],capture_output=True,timeout=300)
    if completed.returncode:
        raise ValueError('pilot35_historical_integrity_failure')
    historical=json.loads(completed.stdout)
    if historical['status']!='passed' or historical['original_artifacts']!=16 or historical['bound_fit_artifacts']!=25:
        raise ValueError('pilot35_historical_integrity_counts')
    save(ROOT/'historical-integrity.json',historical)
    return result


if __name__=='__main__':run()
