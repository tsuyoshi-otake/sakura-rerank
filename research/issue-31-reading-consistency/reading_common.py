"""Bindings for applying the new source gate to previously consumed rows only."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby

sys.path.insert(0,'research/issue-31-conflict-source')
try:
    import conflict_common as previous
    from source_evidence import provenance, read_archive
finally:
    sys.path.pop(0)

HERE=Path('research/issue-31-reading-consistency')
_attempt=os.environ.get('SAKURA_READING_ATTEMPT','attempt-01')
if not re.fullmatch('attempt-0[1-8]',_attempt):raise ValueError('reading_gate_attempt_bound')
ROOT=Path('data/generated/issue-31-reading-consistency-v1')/_attempt
PRIOR=Path('data/generated/issue-31-conflict-source-v1/attempt-02')


def require(condition, code):
    if not condition:raise ValueError('reading_gate_'+code)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('xb') as stream:stream.write(canonical_json_bytes(value)+b'\n')


def freeze():
    old=read(previous.HERE/'plan-v1.json')
    inputs=dict(old['inputs'])
    for path in [previous.HERE/'plan-v1.json',Path('reports/issue-31-conflict-source-v1.json'),
                 PRIOR/'audit.json',PRIOR/'verification.json',PRIOR/'rows.json',PRIOR/'repair-proposals.json']:
        inputs[path.as_posix()]=sha(path)
    code=dict(old['code'])
    paths=sorted(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/source_reading_gate.py'),Path('tests/test_source_reading_gate.py')]
    code.update({p.as_posix():sha(p) for p in paths})
    plan=dict(kind='source_reading_consistency_preparation',version=1,issue=31,parent_issue=1,
        prior_commit='e1129af697c1289ae7b48c1aae6fa989d1ebd964',inputs=inputs,code=code,
        population='same75000 previously consumed weak-source reconstruction rows; no new evaluation source',rows=75000,
        default_policy='Missing original reading evidence is pending. Exact matches prepare source reconstruction only; all contradictions/uncertain original annotations stay pending.',
        execution_policy=dict(allow_dictionary_only=True,reason='Preserve explicitly labelled dictionary-only weak sources from the existing research recipe; this is not training/Gold admission and cannot override an observed conflict or uncertain annotation.'),
        generation_order='Wikipedia source-paragraph stream order, then lexically sorted Aozora work ID, retaining original cohort order within each source. Preserve original identity/components; never compare by row position across pools.',
        publication='New immutable directory; complete decision hash chain for all rows. Pending rows absent from prepared payload. Authenticated candidate/numeric-only reader validates staging before atomic publication.',
        expected_from_prior=dict(ready_original_annotation=25567,ready_dictionary_only_weak=48518,pending_reading_conflict=335,
            pending_annotation_scope=567,pending_annotation_parse=11,pending_annotation_reading=2),
        limits=dict(rows=100000,decoded_artifact_bytes=268435456,concurrency=1,retries=0,stage_seconds=1800),
        expected_effect='Prevent demonstrated source-reading contradictions and unresolved annotation scopes from entering new preparation without changing the original labels or denominator.',
        expected_cost='Two bounded original-source passes and one complete regression suite; no downloads, native conversion or model execution.',
        new_fits=0,model_inferences=0,native_requests=0,labels_changed=0,threshold_selection=False,calibration=False,final_test=False,
        training_admission=False,gold_admission=False,safety_limit=0.0025,
        gold_requirements=dict(point_estimate=0.995,wilson95_lower=0.990,final_valid_minimum=3000))
    save(HERE/'plan-v1.json',plan)
    return dict(status='plan_frozen',inputs=len(inputs),code_files=len(code))


def authenticate(commit):
    plan=json.loads(previous.committed(HERE/'plan-v1.json',commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'bound_artifact_changed')
    for path in plan['code']:previous.committed(path,commit)
    registry=read(previous.REGISTRY)
    selection={r['work_id']:r for r in read(previous.GROWTH/'aozora-selection.json')}
    require(len(registry)==len({r['work_id'] for r in registry})==546,'registry_population')
    require(all(selection[r['work_id']]['partition']=='train' for r in registry),'train_sources_only')
    allowed=list(plan['inputs'])
    for record in registry:
        require(re.fullmatch('[0-9]+',record['work_id']),'work_path')
        allowed.extend(previous.GROWTH/'aozora-download'/(record['work_id']+suffix) for suffix in ('.json','.zip'))
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:from experiment_fit_contract import TrainingReadGuard
    finally:sys.path.pop(0)
    guard=TrainingReadGuard(Path.cwd(),allowed,ROOT)
    sys.addaudithook(guard)
    return plan,registry,selection,guard


def population():
    cohort=list(previous.rows(previous.BASE/'scope-v1/cohorts/rows.jsonl.gz',75000))
    require(len(cohort)==len({r['encoder_input']['stable_id'] for r in cohort})==75000,'cohort_population')
    origins=provenance(cohort)
    return cohort,origins


def source_records(cohort,origins,registry,selection):
    """One original-source pass; assessment is computed by the new producer."""
    from collections import defaultdict
    by_wiki,by_work=defaultdict(list),defaultdict(list)
    for index,meta in enumerate(origins):
        if meta['corpus']=='jawiki':by_wiki[(meta['source_id'],meta['paragraph_index'])].append(index)
        else:
            require(meta['corpus']=='aozora','source_corpus')
            by_work[meta['source_id']].append(index)
    def record(index,paragraph):
        meta=origins[index]
        source=dict(origin_kind='original_ruby' if meta['annotation_origin'] else 'frozen_unique_dictionary',
            revision_sha256=canonical_json_hash(meta['source_revision']),paragraph_sha256=meta['paragraph_sha256'],
            original_row_sha256=cohort[index]['origin']['original_row_sha256'],start=meta['target_start'],end=meta['target_end'])
        return cohort[index]['encoder_input'],source,paragraph
    found=set()
    for paragraph in previous.rows(previous.BASE/'source/wikipedia-paragraphs.jsonl.gz',62404):
        key=(paragraph['source_id'],paragraph['paragraph_index'])
        if key not in by_wiki:continue
        require(key not in found,'duplicate_wikipedia_paragraph')
        found.add(key)
        for index in by_wiki[key]:
            require(paragraph['source_revision']==origins[index]['source_revision'],'wikipedia_revision')
            yield record(index,paragraph['text'])
    require(found==set(by_wiki),'wikipedia_source_complete')
    receipts={r['work_id']:r for r in registry}
    for work in sorted(by_work):
        require(work in receipts,'missing_work')
        receipt=receipts[work]
        raw=read_archive(receipt,selection[work])
        paragraphs,_=paragraphs_with_ruby(raw)
        require(len(paragraphs)==receipt['paragraph_count'],'source_paragraph_count')
        for index in by_work[work]:
            meta=origins[index]
            require(meta['source_revision']==receipt['decoded_sha256'],'source_revision')
            paragraph=paragraphs[meta['paragraph_index']]
            if meta['annotation_origin']:require(paragraph['source_line_sha256']==meta['source_line_sha256'],'annotation_line')
            yield record(index,paragraph)
