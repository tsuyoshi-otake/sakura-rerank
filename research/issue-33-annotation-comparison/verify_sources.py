"""Check every saved source position directly, independently of span search."""
from collections import Counter,defaultdict
import hashlib
import json
import time

from sakura_rerank.data.contracts import canonical_json_hash,canonical_json_bytes,sentence_shingle_hashes,text_sha256
from sakura_rerank.data.growth_corpus import SEED,aozora_paragraphs
from sakura_rerank.data.jawiki_preprocess import _sentences
from comparison_common import ROOT,PLAN,prior,source_pools,dictionary_readings,rows,read,save,sha


def direct_check(row,receipt,paragraph,paragraph_index,*,author_id=None):
    start,end=receipt['target_start'],receipt['target_end'];si=receipt['sentence_index']
    sentences=list(_sentences(paragraph))
    if not 0<=si<len(sentences) or not 0<=start<end<=len(paragraph): raise ValueError('source_verifier_position_bound')
    offset,sentence=sentences[si]
    metadata=dict(article_id=('jawiki-page-' if row['corpus']=='jawiki' else 'aozora-work-')+row['source_id'],
        paragraph_hash=text_sha256(paragraph),sentence_hash=text_sha256(sentence),sentence_shingle_hashes=sentence_shingle_hashes(sentence),
        template_cluster_id='aozora-author-'+author_id if author_id else None)
    expected_id='growth-'+canonical_json_hash([SEED,row['corpus'],row['source_id'],row['source_revision'],paragraph_index,si,start-offset,end-offset,row['target']])
    if (row['source']!=metadata or row['stable_id']!=expected_id or paragraph[start:end]!=row['target']
            or not offset<=start<end<=offset+len(sentence) or paragraph[max(0,start-64):start]!=row['left_context']):
        raise ValueError('source_verifier_original_preimage')
    expected=dict(stable_id=row['stable_id'],source_row_sha256=canonical_json_hash(row),corpus=row['corpus'],source_id=row['source_id'],
        source_revision=row['source_revision'],paragraph_index=paragraph_index,sentence_index=si,context_start=max(0,start-64),target_start=start,target_end=end,
        paragraph_sha256=text_sha256(paragraph),context_sha256=text_sha256(row['left_context']),target_sha256=text_sha256(row['target']),
        reading_sha256=text_sha256(row['reading']),input_and_label_sha256=canonical_json_hash([row['left_context'],row['reading'],row['target']]),
        reading_provenance='frozen_unique_dictionary_not_contextual_annotation',ime_quality='unresolved',training_eligible=False,independent_gold_eligible=False)
    if receipt!=expected: raise ValueError('source_verifier_receipt_fields')


def verify():
    started=time.monotonic();plan,old,annotations,_,_=source_pools()
    report=read(ROOT/'source-report.json');execution=read(ROOT/'source-execution.json')
    if (execution['status']!='complete' or execution['report_sha256']!=sha(ROOT/'source-report.json')
            or report!=read(ROOT/'source/manifest.json') or report['plan_sha256']!=sha(PLAN)
            or report['source_dump_sha256']!=plan['source']['wikipedia_sha256']):
        raise ValueError('source_verifier_binding')
    for path,digest in report['implementation'].items():
        if sha(path)!=digest: raise ValueError('source_verifier_implementation_changed')
    for entry in report['artifacts'].values():
        if sha(ROOT/'source'/entry['path'])!=entry['sha256']: raise ValueError('source_verifier_artifact_changed')
    def artifact(name): return list(rows(ROOT/'source'/report['artifacts'][name]['path']))
    receipts={r['stable_id']:r for r in artifact('row-origins')}
    saved=artifact('wikipedia-paragraphs');paragraphs={(r['source_id'],r['paragraph_index']):r for r in saved}
    if len(paragraphs)!=len(saved): raise ValueError('source_verifier_duplicate_paragraph')
    readings=dictionary_readings();wiki_checked=set();work_rows=defaultdict(list);counts=Counter();used=set()
    for row in old:
        if row['reading']!=readings.get(row['target']): raise ValueError('source_verifier_dictionary_reading')
        if row['corpus']=='aozora': work_rows[row['source_id']].append(row);continue
        record=receipts[row['stable_id']];key=(row['source_id'],record['paragraph_index']);paragraph=paragraphs[key]
        if paragraph['source_revision']!=row['source_revision']: raise ValueError('source_verifier_wiki_revision')
        direct_check(row,record,paragraph['text'],record['paragraph_index'])
        wiki_checked.add(row['stable_id']);used.add(key);counts['jawiki']+=1
    if used!=set(paragraphs): raise ValueError('source_verifier_extra_or_missing_paragraphs')
    expected_coverage=[]
    for (source_id,pi),row in paragraphs.items():
        for si,(_,sentence) in enumerate(_sentences(row['text'])):
            expected_coverage.append(dict(stable_id='reconstruction-coverage-'+canonical_json_hash(['jawiki',source_id,row['source_revision'],pi,si]),
                population='source_coverage',source=dict(article_id='jawiki-page-'+source_id,paragraph_hash=text_sha256(row['text']),
                    sentence_hash=text_sha256(sentence),sentence_shingle_hashes=sentence_shingle_hashes(sentence),template_cluster_id=None)))
    actual_coverage=artifact('wikipedia-coverage')
    if sorted(expected_coverage,key=lambda r:r['stable_id'])!=actual_coverage:
        raise ValueError('source_verifier_complete_paragraph_coverage')
    _,archives,selection=prior.origin.source.source_identity();checked=set(wiki_checked)
    for archive in archives:
        work=work_rows.get(archive['work_id'])
        if not work: continue
        chosen=selection[archive['work_id']];raw=prior.origin.source.read_work(archive,chosen)
        if hashlib.sha256(raw).hexdigest()!=archive['decoded_sha256']: raise ValueError('source_verifier_original_work_bytes')
        original,_=aozora_paragraphs(raw)
        for row in work:
            receipt=receipts[row['stable_id']];pi=receipt['paragraph_index']
            if row['source_revision']!=archive['decoded_sha256']: raise ValueError('source_verifier_work_revision')
            direct_check(row,receipt,original[pi],pi,author_id=chosen['author_id'])
            checked.add(row['stable_id']);counts['aozora']+=1
    if checked!={r['stable_id'] for r in old} or set(receipts)!=checked or dict(counts)!=report['dictionary_rows_per_corpus']:
        raise ValueError('source_verifier_population')
    digest=hashlib.sha256()
    for key in sorted(receipts): digest.update(canonical_json_bytes(receipts[key])+b'\n')
    result=dict(kind='annotation_comparison_source_verification',status='passed',rows=len(checked),rows_per_corpus=dict(counts),
        complete_wikipedia_coverage=len(actual_coverage),wikipedia_paragraphs=len(paragraphs),annotation_rows=len(annotations),
        all_source_positions_directly_checked=True,full_receipts_sha256=digest.hexdigest(),report_sha256=sha(ROOT/'source-report.json'),
        script_sha256=sha(__file__),elapsed_seconds=round(time.monotonic()-started,3),
        verification_scope='Wiki recovered paragraph bytes checked against immutable original paragraph hashes and stable-ID preimages; Aozora original archives authenticated and positions checked. The complete Wiki dump is not parsed a second time.',
        reading_interpretation='Frozen dictionary provenance only; not contextual reading or IME correctness certification.',gold_certified=False,final_test_used=False,model_fits=0)
    save(ROOT/'source-verification.json',result)
    return result


if __name__=='__main__': print(json.dumps(verify()))
