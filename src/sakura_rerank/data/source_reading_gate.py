"""Original-reading checks for new, unadmitted source-reconstruction preparation.

The producer recomputes evidence from exact source spans. The consumer accepts
only the resulting bound pool, never pending rows. Neither boundary admits
training, certifies Japanese/IME correctness, nor changes an original label.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

from .aozora_ruby_evidence import ruby_state
from .contracts import canonical_json_bytes, canonical_json_hash, text_sha256

MAX_ROWS = 100000
MAX_BYTES = 256*1024*1024
MAX_LINE = 16384
INPUT_FIELDS = {'stable_id','component_id','corpus','left_context','reading','target','candidate_request_id'}
SOURCE_FIELDS = {'origin_kind','revision_sha256','paragraph_sha256','original_row_sha256','start','end'}
STATES = {'exact_ruby_reading_match','exact_ruby_reading_disagreement','no_ruby_overlap',
          'ruby_scope_differs','ruby_parse_unresolved','exact_ruby_nonphonetic_or_out_of_bounds',
          'wikipedia_no_original_reading_annotation'}


def _require(condition, code):
    if not condition:
        raise ValueError('source_reading_'+code)


def _digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def policy(allow_dictionary_only=False):
    _require(type(allow_dictionary_only) is bool, 'policy_boolean')
    return dict(version=1, allow_dictionary_only=allow_dictionary_only,
                meaning='source_reconstruction_only', training_eligible=False, independent_gold_eligible=False)


def _input(row):
    _require(isinstance(row,dict) and set(row)==INPUT_FIELDS, 'input_schema')
    _require(row['corpus'] in ('aozora','jawiki'), 'input_corpus')
    for key, low, high in (('stable_id',1,256),('component_id',1,256),('left_context',8,64),('reading',2,32),('target',1,32)):
        _require(isinstance(row[key],str) and low<=len(row[key])<=high, 'input_bounds')
    _require(row['candidate_request_id']=='growth-reading-'+canonical_json_hash(row['reading']), 'reading_request')


def _terminal(state, origin, allow_dictionary_only):
    _require(state in STATES and origin in ('frozen_unique_dictionary','original_ruby'), 'evidence_state')
    if state=='exact_ruby_reading_match':
        return 'ready_original_annotation'
    if state in ('no_ruby_overlap','wikipedia_no_original_reading_annotation'):
        return 'ready_dictionary_only_weak' if origin=='frozen_unique_dictionary' and allow_dictionary_only else 'pending_annotation_missing'
    return {'exact_ruby_reading_disagreement':'pending_reading_conflict',
            'ruby_scope_differs':'pending_annotation_scope', 'ruby_parse_unresolved':'pending_annotation_parse',
            'exact_ruby_nonphonetic_or_out_of_bounds':'pending_annotation_reading'}[state]


def assess(row, source, paragraph, *, allow_dictionary_only=False):
    """Caller authenticates source bytes/revision; no caller-supplied verdict."""
    current_policy=policy(allow_dictionary_only)
    _input(row)
    _require(isinstance(source,dict) and set(source)==SOURCE_FIELDS, 'source_schema')
    _require(all(_digest(source[k]) for k in ('revision_sha256','paragraph_sha256','original_row_sha256')), 'source_hash')
    _require(source['origin_kind'] in ('frozen_unique_dictionary','original_ruby'), 'source_origin')
    if row['corpus']=='jawiki':
        _require(isinstance(paragraph,str) and source['origin_kind']=='frozen_unique_dictionary', 'wikipedia_contract')
        text=paragraph
    else:
        _require(isinstance(paragraph,dict) and set(paragraph)=={'text','spans','line_number','source_line_sha256','flags'}, 'ruby_paragraph_schema')
        text=paragraph['text']
        _require(isinstance(paragraph['spans'],list) and len(paragraph['spans'])<=20000
                 and isinstance(paragraph['flags'],dict) and set(paragraph['flags'])=={'orphan_marker'}
                 and type(paragraph['flags']['orphan_marker']) is bool, 'ruby_metadata')
        _require(type(paragraph['line_number']) is int and paragraph['line_number']>=0 and _digest(paragraph['source_line_sha256']), 'ruby_source_line')
    _require(isinstance(text,str) and 1<=len(text)<=100000 and text_sha256(text)==source['paragraph_sha256'], 'paragraph_hash_or_bound')
    start,end=source['start'],source['end']
    _require(type(start) is int and type(end) is int and 0<=start<end<=len(text)
             and text[start:end]==row['target'] and text[max(0,start-64):start]==row['left_context'], 'exact_span_and_prefix')
    if row['corpus']=='aozora':
        previous=0
        for span in paragraph['spans']:
            _require(isinstance(span,dict) and set(span)=={'start','end','reading','kind','base_sha256'}, 'ruby_span_schema')
            a,b=span['start'],span['end']
            _require(type(a) is int and type(b) is int and previous<=a<=b<=len(text)
                     and (a<b or span['kind']=='unresolved_base')
                     and span['kind'] in ('explicit','implicit_kanji','unresolved_base')
                     and isinstance(span['reading'],str) and len(span['reading'])<=100000
                     and text_sha256(text[a:b])==span['base_sha256'], 'ruby_span_integrity')
            previous=b
        state,_=ruby_state(paragraph,start,end,row['reading'])
    else:
        state='wikipedia_no_original_reading_annotation'
    terminal=_terminal(state,source['origin_kind'],allow_dictionary_only)
    return dict(input_sha256=canonical_json_hash(row), source=dict(source),
                evidence_sha256=canonical_json_hash([source,paragraph]), reading_evidence=state,
                terminal=terminal, candidate_preparation_allowed=terminal.startswith('ready_'),
                policy_sha256=canonical_json_hash(current_policy), training_eligible=False,
                independent_gold_eligible=False)


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def _write(stream, value):
    raw=canonical_json_bytes(value)+b'\n'
    _require(len(raw)<=MAX_LINE, 'output_line_bound')
    stream.write(raw)
    return len(raw)


def prepare(records, destination, *, source_binding_sha256, expected_rows, allow_dictionary_only=False):
    """Publish one complete new pool; any failed input publishes no destination.

    records yields (original encoder row, source extent/provenance, paragraph).
    Pending rows retain full decision history but cannot enter prepared rows.
    """
    current_policy=policy(allow_dictionary_only)
    _require(_digest(source_binding_sha256) and type(expected_rows) is int and 1<=expected_rows<=MAX_ROWS, 'preparation_binding')
    destination=Path(destination).absolute()
    _require(destination.parent.is_dir() and not destination.exists() and not destination.is_symlink(), 'destination_exists_or_parent_missing')
    staging=destination.parent/('.'+destination.name+'.partial-'+uuid.uuid4().hex)
    staging.mkdir()
    owned=staging.resolve()
    previous='0'*64
    counts,states=Counter(),Counter()
    seen=set()
    total=ready=ledger_bytes=prepared_bytes=0
    try:
        with (staging/'decisions.jsonl.gz').open('xb') as ledger_file, (staging/'prepared-rows.jsonl.gz').open('xb') as rows_file:
            with gzip.GzipFile(filename='',mode='wb',fileobj=ledger_file,mtime=0) as ledger_stream, gzip.GzipFile(filename='',mode='wb',fileobj=rows_file,mtime=0) as rows_stream:
                for row,source,paragraph in records:
                    _require(total<expected_rows, 'input_count_exceeded')
                    decision=assess(row,source,paragraph,allow_dictionary_only=allow_dictionary_only)
                    _require(row['stable_id'] not in seen, 'duplicate_input_identity')
                    seen.add(row['stable_id'])
                    entry=dict(index=total,previous_sha256=previous,decision=decision)
                    previous=canonical_json_hash(entry)
                    ledger_bytes+=_write(ledger_stream,dict(entry,entry_sha256=previous))
                    if decision['candidate_preparation_allowed']:
                        prepared_bytes+=_write(rows_stream,dict(input=row,decision_sha256=canonical_json_hash(decision)))
                        ready+=1
                    counts[decision['terminal']]+=1
                    states[decision['reading_evidence']]+=1
                    total+=1
                    _require(max(ledger_bytes,prepared_bytes)<=MAX_BYTES, 'decoded_output_bound')
        _require(total==expected_rows and ready>0, 'population_incomplete_or_no_preparable_rows')
        manifest=dict(kind='source_reading_screened_reconstruction_pool',version=1,source_binding_sha256=source_binding_sha256,
            policy=current_policy,input_rows=total,preparable_rows=ready,pending_rows=total-ready,terminal_counts=dict(counts),
            reading_evidence_counts=dict(states),decision_chain_head=previous,
            artifacts={name:dict(sha256=_sha(staging/name),bytes=(staging/name).stat().st_size,decoded_bytes=decoded)
                       for name,decoded in (('decisions.jsonl.gz',ledger_bytes),('prepared-rows.jsonl.gz',prepared_bytes))},
            training_eligible=False,independent_gold_eligible=False,consumer_purposes=['candidate_generation','numeric_verification'])
        with (staging/'manifest.json').open('xb') as stream:
            stream.write(canonical_json_bytes(manifest)+b'\n')
        load_prepared(staging,_sha(staging/'manifest.json'),purpose='candidate_generation')
        _require(not destination.exists(), 'destination_created_during_preparation')
        staging.rename(destination)
        return manifest
    finally:
        if staging.exists():
            _require(staging.resolve()==owned and owned.parent==destination.parent.resolve() and not staging.is_symlink(), 'staging_cleanup_scope')
            shutil.rmtree(staging)


def _read_lines(path, descriptor):
    _require(not path.is_symlink() and path.is_file() and path.stat().st_size==descriptor['bytes']
             and 0<descriptor['bytes']<=MAX_BYTES and _sha(path)==descriptor['sha256'], 'artifact_binding')
    decoded=0
    with gzip.open(path,'rb') as stream:
        while True:
            line=stream.readline(MAX_LINE+1)
            if not line: break
            decoded+=len(line)
            _require(len(line)<=MAX_LINE and line.endswith(b'\n') and decoded<=MAX_BYTES, 'decoded_input_bound')
            yield json.loads(line)
    _require(decoded==descriptor['decoded_bytes'], 'decoded_byte_count')


def load_prepared(root, expected_manifest_sha256, *, purpose):
    """Authenticated gate consumer; intentionally no training/Gold purpose."""
    _require(purpose in ('candidate_generation','numeric_verification') and _digest(expected_manifest_sha256), 'consumer_purpose_or_binding')
    root=Path(root)
    _require(root.is_dir() and not root.is_symlink() and {p.name for p in root.iterdir()}=={'manifest.json','decisions.jsonl.gz','prepared-rows.jsonl.gz'}, 'pool_directory')
    path=root/'manifest.json'
    _require(not path.is_symlink() and 0<path.stat().st_size<=65536, 'manifest_size')
    raw=path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest()==expected_manifest_sha256, 'manifest_hash')
    manifest=json.loads(raw)
    _require(set(manifest)=={'kind','version','source_binding_sha256','policy','input_rows','preparable_rows','pending_rows','terminal_counts',
                             'reading_evidence_counts','decision_chain_head','artifacts','training_eligible','independent_gold_eligible','consumer_purposes'}, 'manifest_schema')
    _require(manifest['kind']=='source_reading_screened_reconstruction_pool' and manifest['version']==1
             and manifest['training_eligible'] is False and manifest['independent_gold_eligible'] is False
             and manifest['consumer_purposes']==['candidate_generation','numeric_verification']
             and _digest(manifest['source_binding_sha256']) and _digest(manifest['decision_chain_head']), 'manifest_admission')
    current_policy=policy(manifest['policy']['allow_dictionary_only'])
    _require(manifest['policy']==current_policy and type(manifest['input_rows']) is int and 1<=manifest['input_rows']<=MAX_ROWS
             and type(manifest['preparable_rows']) is int and type(manifest['pending_rows']) is int
             and 0<manifest['preparable_rows']<=manifest['input_rows']
             and manifest['pending_rows']==manifest['input_rows']-manifest['preparable_rows'], 'manifest_population')
    _require(set(manifest['artifacts'])=={'decisions.jsonl.gz','prepared-rows.jsonl.gz'}, 'artifact_names')
    for item in manifest['artifacts'].values():
        _require(set(item)=={'sha256','bytes','decoded_bytes'} and _digest(item['sha256'])
                 and type(item['bytes']) is int and type(item['decoded_bytes']) is int and 0<item['decoded_bytes']<=MAX_BYTES, 'artifact_schema')
    previous='0'*64
    decisions=[]
    allowed=[]
    seen=set()
    counts,states=Counter(),Counter()
    for entry in _read_lines(root/'decisions.jsonl.gz',manifest['artifacts']['decisions.jsonl.gz']):
        _require(len(decisions)<manifest['input_rows'] and set(entry)=={'index','previous_sha256','decision','entry_sha256'}
                 and type(entry['index']) is int and entry['index']==len(decisions) and entry['previous_sha256']==previous, 'decision_sequence')
        previous=canonical_json_hash({k:v for k,v in entry.items() if k!='entry_sha256'})
        _require(previous==entry['entry_sha256'], 'decision_chain')
        decision=entry['decision']
        _require(set(decision)=={'input_sha256','source','evidence_sha256','reading_evidence','terminal','candidate_preparation_allowed',
                                 'policy_sha256','training_eligible','independent_gold_eligible'}, 'decision_schema')
        _require(set(decision['source'])==SOURCE_FIELDS and all(_digest(decision['source'][k]) for k in ('revision_sha256','paragraph_sha256','original_row_sha256')),
                 'decision_source')
        _require(type(decision['source']['start']) is int and type(decision['source']['end']) is int
                 and 0<=decision['source']['start']<decision['source']['end']<=100000, 'decision_extent')
        terminal=_terminal(decision['reading_evidence'],decision['source']['origin_kind'],current_policy['allow_dictionary_only'])
        _require(decision['terminal']==terminal and type(decision['candidate_preparation_allowed']) is bool
                 and decision['candidate_preparation_allowed']==terminal.startswith('ready_')
                 and decision['policy_sha256']==canonical_json_hash(current_policy) and decision['training_eligible'] is False
                 and decision['independent_gold_eligible'] is False and _digest(decision['input_sha256'])
                 and _digest(decision['evidence_sha256']) and decision['input_sha256'] not in seen, 'decision_policy')
        seen.add(decision['input_sha256'])
        decisions.append(decision)
        if decision['candidate_preparation_allowed']: allowed.append(decision)
        counts[terminal]+=1
        states[decision['reading_evidence']]+=1
    _require(len(decisions)==manifest['input_rows'] and previous==manifest['decision_chain_head']
             and len(allowed)==manifest['preparable_rows'] and dict(counts)==manifest['terminal_counts']
             and dict(states)==manifest['reading_evidence_counts'], 'decision_totals')
    prepared=[]
    identities=set()
    for row in _read_lines(root/'prepared-rows.jsonl.gz',manifest['artifacts']['prepared-rows.jsonl.gz']):
        _require(len(prepared)<len(allowed) and set(row)=={'input','decision_sha256'}, 'prepared_schema_or_count')
        _input(row['input'])
        decision=allowed[len(prepared)]
        _require(row['decision_sha256']==canonical_json_hash(decision) and canonical_json_hash(row['input'])==decision['input_sha256']
                 and row['input']['stable_id'] not in identities, 'prepared_row_binding')
        identities.add(row['input']['stable_id'])
        prepared.append(row)
    _require(len(prepared)==len(allowed), 'prepared_count')
    return dict(manifest=manifest,decisions=decisions,rows=prepared)
