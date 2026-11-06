"""Bound only the source/measurement contract needed for lexical diagnosis."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash

HERE=Path('research/issue-31-lexical-coverage')
_attempt=os.environ.get('SAKURA_LEXICAL_ATTEMPT','attempt-01')
if not re.fullmatch('attempt-0[1-8]',_attempt):raise ValueError('lexical_audit_attempt_bound')
ROOT=Path('data/generated/issue-31-lexical-coverage-v1')/_attempt
OLD=Path('data/generated/issue-31-source-extents-v1/attempt-01')
PUBLIC=Path('reports/issue-31-source-extents-v1.json')
PREVIOUS_PLAN=Path('research/issue-31-source-extents/plan-v1.json')
COHORT=Path('data/generated/issue-33-annotation-comparison-v1/attempt-02/scope-v1/cohorts/rows.jsonl.gz')
INDEX=Path('data/generated/system-dictionary-index.jsonl')
MANIFEST=Path('manifests/system-dictionary-index-verified.json')
VIEWS=('original_ruby','literal_suffix','supported_run')


def require(condition,code):
    if not condition:raise ValueError('lexical_audit_'+code)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def save(path,value):
    raw=canonical_json_bytes(value)+b'\n';require(len(raw)<=128*1024*1024,'artifact_bound')
    with Path(path).open('xb') as stream:stream.write(raw)


def committed(path,commit):
    require(isinstance(commit,str) and re.fullmatch('[0-9a-f]{40}',commit),'commit_required')
    raw=subprocess.check_output(['git','show',commit+':'+Path(path).as_posix()],timeout=30)
    require(raw==Path(path).read_bytes(),'committed_bytes_changed');return raw


def prior_contract():
    report=json.loads(committed(PUBLIC,'c230327ac41b71a09125cd30f9fb00a53a2adce4'))
    require(report['verification']['status']=='passed' and report['plan_sha256']==sha(PREVIOUS_PLAN),'prior_verification')
    for stage in ('preparation','native','verification'):
        name='native-report.json' if stage=='native' else stage+'.json'
        require(read(OLD/name)==report[stage],'prior_report_contract')
    require(sha(OLD/'preparation.json')==report['verification']['preparation_sha256']
        and sha(OLD/'native-report.json')==report['verification']['native_report_sha256'],'prior_report_hash')
    for name in ('source-extents.json','raw-overlap.json','requests.json'):
        require(sha(OLD/name)==report['preparation']['artifacts'][name],'prior_source_artifact')
    require(sha(OLD/'measurements.json')==report['native']['measurements_sha256'],'prior_measurements')
    require(sha(COHORT)==read(PREVIOUS_PLAN)['inputs'][COHORT.as_posix()],'old_control_cohort')
    return report


def freeze():
    prior=prior_contract();native=prior['reference_runtime'];head=subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()
    require(not subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30),'dirty_sakura_input')
    paths=[PUBLIC,PREVIOUS_PLAN,COHORT,INDEX,MANIFEST,Path(native['dictionary'])]
    paths.extend(OLD/name for name in ('preparation.json','native-report.json','verification.json','source-extents.json','measurements.json','raw-overlap.json','requests.json'))
    scripts=sorted(HERE.glob('*.py'))+[Path(p) for p in ('src/sakura_rerank/data/lexical_cover.py','tests/test_lexical_cover.py',
        'src/sakura_rerank/data/jawiki_preprocess.py','src/sakura_rerank/data/tier_a.py','src/sakura_rerank/data/contracts.py',
        'src/sakura_rerank/data/tatoeba_input_units.py','src/sakura_rerank/data/tatoeba_source.py','src/sakura_rerank/data/input_boundary.py',
        'research/issue-33-annotation-experiment/experiment_fit_contract.py','research/issue-33-annotation-experiment/experiment_common.py')]
    plan=dict(kind='exact_indexed_lexical_coverage',version=1,issue=31,parent_issue=1,prior_commit='c230327ac41b71a09125cd30f9fb00a53a2adce4',
        inputs={p.as_posix():sha(p) for p in paths},code={p.as_posix():sha(p) for p in scripts},
        source_parents=335,source_view_pairs=1005,dictionary_reading_controls=335,pairs=1340,
        selection='All1005 sealed views and all335 original dictionary-reading controls; never select only candidate misses or omit uncertain lexical results.',
        lexical_models=['exact_dictionary_pairs_only','exact_dictionary_pairs_plus_literal_kana'],
        interpretation='Exact full target/reading cover by indexed tokens is weaker than runtime reachability. No POS/connection costs, pruning, learning, user dictionary or semantic intent is inferred. Native-positive exceptions to this simplified index model must be reported.',
        literal_policy='Only one-to-one literal Hiragana/fullwidth Katakana-to-Hiragana copying; no unknown-Kanji reading, NFKC, historical modernization or spelling acceptance.',
        limits=dict(target_characters=256,reading_characters=128,states_per_pair=33153,edges_per_pair=1000000,
            dictionary_bytes=67108864,dictionary_records=368341,stage_seconds=1800,retries=0,concurrency=1),
        source_evidence='Reuse authenticated PR69 source/measurement artifacts and original cohort hashes. No additional native execution or final/evaluation labels.',
        dictionary=dict(index_sha256=sha(INDEX),manifest_sha256=sha(MANIFEST),compiled_sha256=native['dictionary_sha256'],
            source_head=read(MANIFEST)['sakura_input_head'],reference_exporter_source_head=native['exporter_source_head']),
        current_sakura_input_head=head,current_sakura_input_clean=True,
        expected_effect='Locate missing exact dictionary correspondence versus index-composable but unobserved source targets, before choosing data policy or another ranker experiment. No accuracy lift is assumed.',
        expected_cost='Two authenticated dictionary/source passes,1340 pair analyses with independent graph replay, full tests. No downloads, native/model execution or GPU fitting.',
        new_fits=0,model_inferences=0,native_requests=0,original_labels_changed=0,training_admission=False,gold_admission=False,
        threshold_selection=False,calibration=False,final_test=False,production_change=False,safety_limit=.0025,gold_requirements=prior['gold_requirements'])
    require(sha(native['dictionary'])==native['dictionary_sha256']==read(MANIFEST)['dictionary_sha256'],'compiled_dictionary_identity')
    save(HERE/'plan-v1.json',plan);return dict(status='plan_frozen',inputs=len(paths),code_files=len(scripts),pairs=1340)


def authenticate(commit):
    plan=json.loads(committed(HERE/'plan-v1.json',commit))
    for path,digest in {**plan['inputs'],**plan['code']}.items():require(sha(path)==digest,'bound_artifact_changed')
    for path in plan['code']:committed(path,commit)
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:from experiment_fit_contract import TrainingReadGuard
    finally:sys.path.pop(0)
    guard=TrainingReadGuard(Path.cwd(),plan['inputs'],ROOT);sys.addaudithook(guard)
    prior_contract();return plan,guard


def pairs():
    source=read(OLD/'source-extents.json')['rows'];observations=read(OLD/'measurements.json')['rows']
    measured={(r['parent_original_row_sha256'],r['view']):r for r in observations}
    require(len(source)==335 and len(measured)==len(observations)==1005,'prior_population')
    by_parent={r['parent_original_row_sha256']:r for r in source};require(len(by_parent)==335,'unique_parents')
    controls={};count=0;decoded=0
    with gzip.open(COHORT,'rb') as stream:
        for line in stream:
            count+=1;decoded+=len(line);require(count<=75000 and len(line)<=262144 and decoded<=128*1024*1024,'cohort_read_bound')
            record=json.loads(line);key=record['origin']['original_row_sha256']
            if key not in by_parent:continue
            require(key not in controls,'duplicate_control');row=record['encoder_input'];anchor=by_parent[key]['views']['original_ruby']
            require(canonical_json_hash(row)==anchor['lineage']['parent_input_sha256'] and row['target']==anchor['hypothesis']['target'],'control_parent_binding')
            controls[key]=dict(parent=key,condition='dictionary_control',target=row['target'],reading=row['reading'],
                source_input_sha256=canonical_json_hash(row),native_presence=None,training_eligible=False,independent_gold_eligible=False,independent_evaluation_eligible=False)
    require(count==75000 and set(controls)==set(by_parent),'control_population')
    result=[controls[k] for k in sorted(controls)]
    for parent in sorted(by_parent):
        for name in VIEWS:
            view=by_parent[parent]['views'][name];row=view['input'];observed=measured[(parent,name)]
            require(row is not None and observed['status']=='complete' and observed['child_input_sha256']==canonical_json_hash(row)
                and observed['lineage_sha256']==view['lineage_sha256'],'source_measurement_join')
            result.append(dict(parent=parent,condition=name,target=row['target'],reading=row['reading'],
                source_input_sha256=canonical_json_hash(row),native_presence=observed['candidate']['presence'],
                training_eligible=False,independent_gold_eligible=False,independent_evaluation_eligible=False))
    require(len(result)==1340,'all_pairs');return result
