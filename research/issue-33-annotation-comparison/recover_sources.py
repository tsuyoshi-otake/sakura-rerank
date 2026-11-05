"""One bounded dump pass authenticates every candidate dictionary fragment."""
import bz2
from collections import Counter,defaultdict
import hashlib
import json
import time
import xml.etree.ElementTree as ET

from sakura_rerank.data.growth_corpus import aozora_paragraphs
from sakura_rerank.data.jawiki_preprocess import clean_wikitext
from sakura_rerank.data.reconstruction_inputs import recover_dictionary_rows,paragraph_coverage
from comparison_common import ROOT,HERE,PLAN,prior,source_pools,dictionary_readings,implementation,write_rows,read,save,sha

CODE=(HERE/'recover_sources.py',HERE/'comparison_common.py',HERE/'reserve_plan.py',
      'src/sakura_rerank/data/reconstruction_inputs.py')


def run():
    started=time.monotonic();plan,old,annotations,_,_=source_pools()
    head,code=implementation(CODE);readings=dictionary_readings()
    work=ROOT/'source.partial';work.mkdir(exist_ok=False)
    source=plan['source'];dump=source['wikipedia_dump']
    if sha(dump)!=source['wikipedia_sha256']: raise ValueError('comparison_wikipedia_dump_changed')
    by_page=defaultdict(list);by_work=defaultdict(list)
    for row in old: (by_page if row['corpus']=='jawiki' else by_work)[row['source_id']].append(row)
    wiki_receipts=[];coverage=[];paragraphs_saved=[];pages_saved=[];seen=set();pages=0;cleaning=Counter()
    print(json.dumps(dict(stage='original_wikipedia_positions',wanted_pages=len(by_page),target_rows=sum(map(len,by_page.values())))),flush=True)
    with bz2.open(dump,'rb') as stream:
        iterator=ET.iterparse(stream,events=('start','end'));_,root=next(iterator)
        for event,element in iterator:
            if event!='end' or element.tag.rsplit('}',1)[-1]!='page': continue
            pages+=1
            if time.monotonic()-started>plan['bounds']['source_stage_seconds']: raise TimeoutError('comparison_source_deadline')
            fields={child.tag.rsplit('}',1)[-1]:child for child in element}
            page_id=fields['id'].text if 'id' in fields else None
            if page_id in by_page:
                if page_id in seen or fields['ns'].text!='0' or 'redirect' in fields:
                    raise ValueError('comparison_reserved_page_identity')
                revision={child.tag.rsplit('}',1)[-1]:child for child in fields['revision']}
                text=revision['text'].text or '';revision_id=revision['id'].text
                if len(text)>plan['bounds']['wikipedia_page_chars']: raise ValueError('comparison_wikipedia_page_bound')
                paragraphs,counts=clean_wikitext(text);cleaning.update(counts)
                recovered,used=recover_dictionary_rows(paragraphs,by_page[page_id],corpus='jawiki',source_id=page_id,
                    revision=revision_id,readings=readings)
                wiki_receipts.extend(recovered)
                coverage.extend(paragraph_coverage(paragraphs,used,corpus='jawiki',source_id=page_id,revision=revision_id))
                paragraphs_saved.extend(dict(source_id=page_id,source_revision=revision_id,paragraph_index=pi,text=paragraphs[pi]) for pi in used)
                pages_saved.append(dict(source_id=page_id,source_revision=revision_id,wikitext_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                    original_paragraphs=len(paragraphs),consumed_paragraphs=len(used),verified_rows=len(recovered)))
                seen.add(page_id)
                if len(coverage)>200000: raise ValueError('comparison_wikipedia_coverage_bound')
            if pages%100000==0:
                print(json.dumps(dict(stage='wikipedia_scan',pages=pages,matched_pages=len(seen),verified_rows=len(wiki_receipts),elapsed_seconds=round(time.monotonic()-started,1))),flush=True)
            element.clear();root.clear()
    if seen!=set(by_page): raise ValueError('comparison_reserved_page_missing')
    aozora_receipts=[];_,archives,selection=prior.origin.source.source_identity()
    for receipt in archives:
        rows=by_work.get(receipt['work_id'])
        if not rows: continue
        if time.monotonic()-started>plan['bounds']['source_stage_seconds']: raise TimeoutError('comparison_source_deadline')
        entry=selection[receipt['work_id']];raw=prior.origin.source.read_work(receipt,entry)
        if hashlib.sha256(raw).hexdigest()!=receipt['decoded_sha256']: raise ValueError('comparison_work_revision_changed')
        paragraphs,_=aozora_paragraphs(raw)
        recovered,_=recover_dictionary_rows(paragraphs,rows,corpus='aozora',source_id=receipt['work_id'],revision=receipt['decoded_sha256'],
            readings=readings,author_id=entry['author_id'])
        aozora_receipts.extend(recovered)
    all_receipts=sorted(wiki_receipts+aozora_receipts,key=lambda r:r['stable_id'])
    if len(all_receipts)!=len(old) or {r['stable_id'] for r in all_receipts}!={r['stable_id'] for r in old}:
        raise ValueError('comparison_source_denominator')
    artifacts={}
    for name,values in [('row-origins',all_receipts),('wikipedia-coverage',sorted(coverage,key=lambda r:r['stable_id'])),
        ('wikipedia-paragraphs',sorted(paragraphs_saved,key=lambda r:(r['source_id'],r['paragraph_index']))),
        ('wikipedia-pages',sorted(pages_saved,key=lambda r:r['source_id']))]:
        artifacts[name]=write_rows(work/(name+'.jsonl.gz'),values)
    report=dict(kind='annotation_comparison_source_recovery',status='source_verified_not_admitted',plan_sha256=sha(PLAN),execution_commit=head,implementation=code,
        original_dictionary_rows=len(old),dictionary_rows_per_corpus=dict(Counter(r['corpus'] for r in old)),annotation_rows=len(annotations),
        verified_original_rows=len(all_receipts),wikipedia_pages=len(seen),wikipedia_scanned_pages=pages,
        wikipedia_consumed_paragraphs=len(paragraphs_saved),wikipedia_coverage_nodes=len(coverage),aozora_works=len(by_work),
        frozen_cleaner_counts=dict(cleaning),artifacts=artifacts,source_dump_sha256=source['wikipedia_sha256'],elapsed_seconds=round(time.monotonic()-started,3),
        gold_certified=False,model_fits=0,model_inferences=0,new_native_requests=0,final_test_used=False)
    save(work/'manifest.json',report)
    work.rename(ROOT/'source')
    save(ROOT/'source-report.json',report)
    return report


if __name__=='__main__':
    if (ROOT/'source-reservation.json').exists(): raise SystemExit('comparison_source_already_reserved')
    save(ROOT/'source-reservation.json',dict(plan_sha256=sha(PLAN),stage='source_recovery'))
    started=time.monotonic()
    try:
        result=run()
    except Exception as error:
        save(ROOT/'source-execution.json',dict(status='failed',error_type=type(error).__name__,elapsed_seconds=round(time.monotonic()-started,3)))
        print(json.dumps(dict(status='failed',error_type=type(error).__name__)),flush=True)
        raise SystemExit(1) from None
    save(ROOT/'source-execution.json',dict(status='complete',report_sha256=sha(ROOT/'source-report.json'),elapsed_seconds=round(time.monotonic()-started,3)))
    print(json.dumps({k:result[k] for k in ('status','verified_original_rows','wikipedia_pages','wikipedia_consumed_paragraphs','wikipedia_coverage_nodes','elapsed_seconds')}),flush=True)
