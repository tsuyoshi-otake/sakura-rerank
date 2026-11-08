"""Frozen KNBC format pilot: metadata reservation, bounded decode and replay."""
import argparse
import ast
import bz2
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import heapq
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import unittest

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.knbc_source import parse_member, reserve_slots

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
ROOT=REPO/'data/generated/issue-35-knbc-format-pilot-v1/attempt-01'
PAST=REPO/'data/generated/issue-35-knbc-qualification-v1'
ARCHIVE=PAST/'attempt-01/archive.quarantine.tar.bz2'
INVENTORY=PAST/'attempt-02/member-inventory.json'
PLAN=HERE/'plan-v1.json'
BINDING=HERE/'decode-binding-v1.json'


def require(value,code):
    if not value: raise ValueError(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:
        stream.write(canonical_json_bytes(value)+b'\n');stream.flush();os.fsync(stream.fileno())


def committed(path,commit):
    raw=subprocess.run(['git','show',commit+':'+Path(path).relative_to(REPO).as_posix()],check=True,capture_output=True,timeout=30).stdout
    require(raw==Path(path).read_bytes(),'pilot_committed_bytes')
    return raw


def freeze():
    paths=[ARCHIVE,INVENTORY,PAST/'attempt-02/documentation-exposure.json',PAST/'attempt-02/document-00.raw',
        PAST/'attempt-02/document-01.raw',PAST/'attempt-02/manual-readable-pages.private.json',
        ROOT/'format-README.private.md',REPO/'reports/issue-35-knbc-qualification-v1.json']
    raw=(ROOT/'format-README.private.md').read_bytes()
    require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()=='0223eaf0edc185484ad4fe1de80913052b144ddf','format_document_identity')
    code=list(HERE.glob('*.py'))+[REPO/'src/sakura_rerank/data/knbc_source.py',REPO/'tests/test_knbc_source.py',REPO/'src/sakura_rerank/data/contracts.py']
    plan=dict(kind='knbc_source_format_pilot_plan',version=1,issue=35,parent_issue=1,related_issues=[31,32,33],
        created_at_utc=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),seed=20261106,
        source_archive_sha256=sha(ARCHIVE),official_cryptographic_digest=None,acquisition_level='official_https_quarantine_only',
        input_hashes={p.relative_to(REPO).as_posix():sha(p) for p in paths},code_hashes={p.relative_to(REPO).as_posix():sha(p) for p in code},
        expected_inventory_members=13589,expected_articles=249,expected_prefix_families=81,
        expected_sentence_candidate_files=4186,expected_unclassified_members=1,expected_fileinfos=249,
        articles=20,slots_per_article=5,max_semantic_members=100,
        selection='Force articles containing unclassified metadata members, reserve those members first, then choose remaining articles and files by canonical SHA256 rank. Keep exactly five slots per article, including missing slots; no content/reading/model filter or replacement.',
        population='4186 article-prefixed sentence candidates,249 fileinfos metadata files,1 unclassified member. The latter is a diagnostic slot, not silently dropped or called a sentence.',
        byte_audit='Hash every opaque corpus1 non-fileinfos member before selection. Preserve exact-byte aliases and their cross-article relations; do not deduplicate or select on labels.',
        consumed_scope='Each reserved article and syntactic prefix family remains unavailable to a later independent Test. Prefix families are conservative relations, not verified author identities. Preserve all attempted members including parse failures.',
        source_fields='KNP surface/reading/lemma/grammar/notes remain distinct. ER, ambiguity, style and alternative annotations are flags, never replacement labels. Annotation surface is not verified original source or IME intention.',
        documentation_check='Exact joined annotation surface of at least8 characters, after whitespace removal for comparison only, against complete exposed provider documentation. A negative diagnostic does not establish independence.',
        history='No source/input/history isolation or independent evaluation admission is asserted. Future history binding must consume the complete ledger, reserved articles/families and byte aliases.',
        limits=dict(compressed_bytes=16*1024*1024,expanded_bytes=128*1024*1024,member_bytes=65536,semantic_members=100,stage_seconds=300,retries=0,concurrency=1),
        expected_effect='Determine whether actual source fields separate original/corrected annotation and usable readings before label construction.',
        expected_cost='One opaque29MB corpus-member hash census, at most100 fixed members from20 articles, independent byte/field replay and full tests; no fitting or native calls.',
        native_requests=0,model_inferences=0,new_fits=0,training_admission=False,gold_admission=False,calibration=False,final_test=False,
        safety_limit=.0025,gold_point=.995,gold_wilson95_lower=.990,gold_final_valid_minimum=3000)
    save(PLAN,plan);return dict(status='sealed',plan_sha256=sha(PLAN))


def authenticate(commit):
    plan=json.loads(committed(PLAN,commit))
    for path,digest in {**plan['input_hashes'],**plan['code_hashes']}.items():
        require(sha(REPO/path)==digest,'pilot_bound_bytes_changed')
    for path in plan['code_hashes']:committed(REPO/path,commit)
    return plan


def open_archive():
    raw=ARCHIVE.read_bytes()
    require(len(raw)==4968025 and hashlib.sha256(raw).hexdigest()=='2df066f321f57413dc94404a60273b84a85c67b55fc5d2c8a34926074c1b83a4','pilot_archive_identity')
    dec=bz2.BZ2Decompressor(); expanded=dec.decompress(raw,max_length=128*1024*1024+1)
    require(len(expanded)<=128*1024*1024 and dec.eof and not dec.unused_data,'pilot_archive_bound')
    return tarfile.open(fileobj=io.BytesIO(expanded),mode='r:')


def select(commit):
    plan=authenticate(commit)
    save(ROOT/'selection-reservation.json',dict(plan_commit=commit,plan_sha256=sha(PLAN),semantic_decode=False,owner_pid=os.getpid()))
    inventory=read(INVENTORY); selected=reserve_slots(inventory,plan['source_archive_sha256'])
    census=selected['census']
    require(census['candidate_files']==4186 and census['unclassified_files']==1 and census['fileinfos_files']==249
            and census['article_groups']==249 and census['prefix_families']==81 and census['slots']==100,'pilot_population')
    members=[r for r in inventory if r['kind']=='file' and r['name'].split('/')[1:2]==['corpus1'] and Path(r['name']).name!='fileinfos']
    hashes={};aliases=defaultdict(list);first_bytes={}
    with open_archive() as archive:
        for item in members:
            member=archive.getmember(item['archive_name'])
            require(member.isfile() and member.size==item['bytes']<=65536,'pilot_member_metadata')
            with archive.extractfile(member) as stream:raw=stream.read(65537)
            require(len(raw)==member.size,'pilot_member_read')
            digest=hashlib.sha256(raw).hexdigest()
            if digest in first_bytes: require(raw==first_bytes[digest],'pilot_hash_collision')
            else:first_bytes[digest]=raw
            hashes[item['name']]=digest;aliases[digest].append(item['name'])
    for slot in selected['slots']:slot['source_raw_sha256']=hashes.get(slot['path'])
    selected.update(plan_commit=commit,plan_sha256=sha(PLAN),selection_sha256=canonical_json_hash(selected['slots']))
    save(ROOT/'member-hashes.private.json',hashes)
    save(ROOT/'byte-aliases.private.json',{k:v for k,v in aliases.items() if len(v)>1})
    save(ROOT/'selection.private.json',selected)
    report=dict(status='reserved_before_semantic_decode',census=census,opaque_hashed_members=len(hashes),
        opaque_hashed_bytes=sum(r['bytes'] for r in members),exact_byte_alias_groups=sum(len(v)>1 for v in aliases.values()),
        selection_sha256=sha(ROOT/'selection.private.json'),member_hashes_sha256=sha(ROOT/'member-hashes.private.json'),
        aliases_sha256=sha(ROOT/'byte-aliases.private.json'),corpus_member_semantic_decodes=0)
    save(ROOT/'selection-report.json',report);return report


def seal(plan_commit):
    authenticate(plan_commit)
    save(BINDING,dict(kind='knbc_format_decode_binding',plan_commit=plan_commit,plan_sha256=sha(PLAN),
        selection_sha256=sha(ROOT/'selection.private.json'),selection_report_sha256=sha(ROOT/'selection-report.json'),
        member_hashes_sha256=sha(ROOT/'member-hashes.private.json'),aliases_sha256=sha(ROOT/'byte-aliases.private.json'),
        semantic_member_limit=100,all_reserved_articles_and_families_excluded_from_future_test=True,
        failed_slots_remain_exposed=True,original_data_changed=False,training_admission=False,gold_admission=False,final_test=False))
    return dict(status='sealed',binding_sha256=sha(BINDING))


def binding(commit):
    bound=json.loads(committed(BINDING,commit));authenticate(bound['plan_commit'])
    for key,name in [('selection_sha256','selection.private.json'),('selection_report_sha256','selection-report.json'),
                     ('member_hashes_sha256','member-hashes.private.json'),('aliases_sha256','byte-aliases.private.json')]:
        require(sha(ROOT/name)==bound[key],'pilot_selection_changed')
    return bound,read(ROOT/'selection.private.json')


def documentation_text():
    texts=read(PAST/'attempt-02/manual-readable-pages.private.json')
    texts += [(PAST/'attempt-02'/name).read_text(encoding='utf-8') for name in ('document-00.raw','document-01.raw')]
    texts.append((ROOT/'format-README.private.md').read_text(encoding='utf-8'))
    return '\n'.join(''.join(t.split()) for t in texts)


def summarize(rows):
    parsed=[r['annotation'] for r in rows if r['annotation'] is not None]
    return dict(slots=len(rows),statuses=dict(Counter(r['status'] for r in rows)),
        semantic_read_attempts=sum(r['semantic_read_attempted'] for r in rows),parsed_annotation_units=len(parsed),
        annotation_tokens=sum(len(a['tokens']) for a in parsed),alternative_rows=sum(a['alternative_rows'] for a in parsed),
        token_reading_kinds=dict(Counter(t['reading_kind'] for a in parsed for t in a['tokens'])),
        document_flags=dict(Counter(f for a in parsed for f in a['flags'])),
        document_exact_surface_hits=sum(r['documentation_exact_surface_hit'] for r in rows),
        original_source_verified=0,ime_units_verified=0,gold_admitted=0)


def decode(commit):
    bound,selection=binding(commit)
    save(ROOT/'decode-reservation.json',dict(binding_commit=commit,binding_sha256=sha(BINDING),slots=100,owner_pid=os.getpid(),
        future_test_unavailable_articles=sorted({s['article'] for s in selection['slots']}),
        future_test_unavailable_prefix_families=sorted({s['family'] for s in selection['slots']})))
    raw_dir=ROOT/'raw-members';raw_dir.mkdir()
    rows=[];previous=sha(BINDING);doc=documentation_text()
    with open_archive() as archive,(ROOT/'consumption-ledger.private.jsonl').open('xb') as ledger:
        for slot in selection['slots']:
            row=dict(slot,status='missing_metadata_slot',semantic_read_attempted=False,annotation=None,
                     documentation_exact_surface_hit=False,training_admission=False,gold_admission=False,final_test=False)
            if slot['path'] is not None:
                member=archive.getmember(slot['archive_name'])
                require(member.isfile() and member.size==slot['bytes']<=65536,'pilot_selected_member')
                with archive.extractfile(member) as stream:raw=stream.read(65537)
                require(len(raw)==slot['bytes'] and hashlib.sha256(raw).hexdigest()==slot['source_raw_sha256'],'pilot_selected_hash')
                with (raw_dir/f"slot-{slot['index']:03d}.raw").open('xb') as output:output.write(raw)
                row['semantic_read_attempted']=True
                try:
                    row['annotation']=parse_member(raw,expected_sid=Path(slot['path']).name if slot['role']=='sentence_candidate' else None)
                    row['status']='parsed_annotation' if slot['role']=='sentence_candidate' else 'unclassified_parsed_annotation'
                    surface=''.join(row['annotation']['annotation_surface'].split())
                    row['documentation_exact_surface_hit']=len(surface)>=8 and surface in doc
                except (ValueError,UnicodeError) as error:
                    row['status']='pending_'+(str(error) if isinstance(error,ValueError) and str(error).isidentifier() else type(error).__name__)
            event={k:row[k] for k in ('index','article','family','path','role','source_raw_sha256','status','semantic_read_attempted')}
            event.update(previous_sha256=previous,training_admission=False,gold_admission=False,final_test=False)
            previous=canonical_json_hash(event);event['event_sha256']=previous
            ledger.write(canonical_json_bytes(event)+b'\n');ledger.flush();os.fsync(ledger.fileno())
            rows.append(row)
    save(ROOT/'parsed-slots.private.json',rows)
    report=dict(status='complete_source_format_research_not_gold',binding_commit=commit,summary=summarize(rows),
        slots_sha256=sha(ROOT/'parsed-slots.private.json'),ledger_sha256=sha(ROOT/'consumption-ledger.private.jsonl'),ledger_head=previous,
        reserved_articles=len({s['article'] for s in selection['slots']}),reserved_prefix_families=len({s['family'] for s in selection['slots']}),
        source_input_history_isolation_verified=False,author_mapping_verified=False,original_labels_changed=0,
        native_requests=0,model_inferences=0,new_fits=0,gold_admission=False,calibration=False,final_test=False)
    save(ROOT/'pilot-report.json',report);return report


def verify(commit):
    _,selection=binding(commit);rows=read(ROOT/'parsed-slots.private.json');report=read(ROOT/'pilot-report.json')
    require(len(rows)==len(selection['slots'])==100 and sha(ROOT/'parsed-slots.private.json')==report['slots_sha256'],'pilot_row_proof')
    require(sha(ROOT/'consumption-ledger.private.jsonl')==report['ledger_sha256'],'pilot_ledger_hash')
    events=[json.loads(line) for line in (ROOT/'consumption-ledger.private.jsonl').read_bytes().splitlines()]
    previous=sha(BINDING)
    for index,(event,row,slot) in enumerate(zip(events,rows,selection['slots'],strict=True)):
        event_hash=event.pop('event_sha256')
        require(event['previous_sha256']==previous and canonical_json_hash(event)==event_hash,'pilot_ledger_chain')
        previous=event_hash
        require(row['index']==index and all(row[k]==v for k,v in slot.items()),'pilot_slot_identity')
        require(all(event[k]==row[k] for k in ('index','article','family','path','role','source_raw_sha256','status','semantic_read_attempted')),'pilot_exposure_identity')
        if slot['path'] is not None:
            raw=(ROOT/'raw-members'/f'slot-{index:03d}.raw').read_bytes()
            require(hashlib.sha256(raw).hexdigest()==slot['source_raw_sha256'],'pilot_raw_replay')
            if row['annotation'] is not None:
                fields=[line.split(maxsplit=11) for line in raw.decode('utf-8').splitlines()
                        if line and not line.startswith(('#','* ','+ ','@ ')) and line!='EOS']
                require(len(fields)==len(row['annotation']['tokens']),'pilot_independent_token_count')
                for original,token in zip(fields,row['annotation']['tokens'],strict=True):
                    require(original[:3]==[token['annotated_surface'],token['annotated_reading'],token['lemma']]
                        and (original[11] if len(original)==12 else '')==token['notes'],'pilot_independent_fields')
    require(previous==report['ledger_head'] and summarize(rows)==report['summary'],'pilot_summary_replay')
    inventory=read(INVENTORY); hashes=read(ROOT/'member-hashes.private.json')
    members=[r for r in inventory if r['name'] in hashes]
    list_path=ROOT/'byte-audit-members.private.txt'
    with list_path.open('xb') as output:output.write(('\n'.join(r['archive_name'] for r in members)+'\n').encode())
    result=subprocess.run(['tar','-xOf',str(ARCHIVE),'-T',str(list_path)],capture_output=True,check=True,timeout=60)
    require(len(result.stdout)==sum(r['bytes'] for r in members),'pilot_independent_archive_bytes')
    offset=0
    for item in members:
        raw=result.stdout[offset:offset+item['bytes']];offset+=item['bytes']
        require(hashlib.sha256(raw).hexdigest()==hashes[item['name']],'pilot_independent_archive_hash')
    # Independent heap-based selection over the metadata roles; no corpus text.
    by_article=defaultdict(list);unknown=defaultdict(list)
    for item in members:
        article=item['name'].split('/')[2];by_article[article].append(item)
        if not Path(item['name']).name.startswith(article+'-'):unknown[article].append(item)
    rank=lambda value:(canonical_json_hash(['knbc-format-v1',20261106,selection['archive_sha256'],value]),value)
    articles=heapq.nsmallest(20,unknown,key=rank)
    articles+=heapq.nsmallest(20-len(articles),set(by_article)-set(articles),key=rank)
    expected=[]
    for article in articles:
        forced=heapq.nsmallest(5,unknown[article],key=lambda r:rank(r['name']))
        names={r['name'] for r in forced}
        candidates=heapq.nsmallest(5-len(forced),(r for r in by_article[article] if r['name'] not in names),key=lambda r:rank(r['name']))
        group=[r['name'] for r in forced+candidates];expected+=group+[None]*(5-len(group))
    require(expected==[r['path'] for r in rows],'pilot_independent_selection')
    value=dict(status='passed',independent_archive_members=len(members),independent_archive_bytes=len(result.stdout),
        independent_selection_slots=len(expected),ledger_events=len(events),independent_parsed_field_rows=sum(len(r['annotation']['tokens']) for r in rows if r['annotation']),
        original_labels_changed=0,model_inferences=0,final_test=False)
    save(ROOT/'verification.json',value);return value


def checks(targeted):
    files=sorted(HERE.glob('*.py'))+[REPO/'src/sakura_rerank/data/knbc_source.py',REPO/'tests/test_knbc_source.py']
    for path in files:compile(ast.parse(path.read_bytes()),str(path),'exec')
    suite=unittest.defaultTestLoader.discover(str(REPO/'tests'),pattern='test_knbc_source.py' if targeted else 'test*.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    value=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),static_files=len(files))
    save(ROOT/('targeted-tests.json' if targeted else 'full-tests.json'),value)
    require(result.wasSuccessful() and not result.skipped and result.testsRun==(18 if targeted else 972),'pilot_tests')
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('freeze','select','seal','decode','verify','targeted','tests'));parser.add_argument('--commit',default='')
    args=parser.parse_args()
    try:
        value=freeze() if args.stage=='freeze' else select(args.commit) if args.stage=='select' else seal(args.commit) if args.stage=='seal' else decode(args.commit) if args.stage=='decode' else verify(args.commit) if args.stage=='verify' else checks(args.stage=='targeted')
        print(json.dumps(value),flush=True)
    except Exception as error:
        value=dict(status='failed',stage=args.stage,error_type=type(error).__name__,error_code=str(error) if isinstance(error,ValueError) and str(error).isidentifier() else None)
        save(ROOT/(args.stage+'-failure.json'),value);print(json.dumps(value),flush=True);raise SystemExit(1)
