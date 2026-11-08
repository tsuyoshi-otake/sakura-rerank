"""Separately bind and execute source-presence probes; never label/model admission."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import subprocess
import threading

from sakura_rerank.data.reference_probe import authenticate_identity
from sakura_rerank.data.tatoeba_input_units import VIEWS,score_units
from unit35_common import ROOT,HERE,PLAN,authenticate,committed,load_script,read,save,sha

BINDING=HERE/'native-binding-v1.json'
IDENTITY=Path('manifests/reference-probe-identity-v1.json')


def runtime(plan):
    spec=plan['native']
    if (subprocess.check_output(['git','-C','../sakura-input','rev-parse','HEAD'],text=True,timeout=30).strip()!=spec['current_sakura_input_head']
            or subprocess.check_output(['git','-C','../sakura-input','status','--porcelain'],timeout=30)):
        raise ValueError('unit35_current_input_checkout_changed')
    return authenticate_identity(IDENTITY,spec['runtime_identity_sha256'],Path(spec['executable']),Path(spec['dictionary']))


def seal(plan_commit):
    plan=authenticate(plan_commit);runtime(plan)
    preparation=read(ROOT/'preparation.json');requests=read(ROOT/'requests.json')['requests']
    if (preparation['slots']!=100 or preparation['requests']!=len(requests)
            or sha(ROOT/'requests.json')!=preparation['requests_sha256']
            or sha(ROOT/'source-units.json')!=preparation['source_units_sha256']):
        raise ValueError('unit35_preparation_changed')
    paths=[HERE/'unit_native.py','research/reference_execution.py','research/issue-31-quality/run_reference_probe.py',
        'src/sakura_rerank/data/reference_probe.py','src/sakura_rerank/data/research_exporter.py',
        'src/sakura_rerank/data/contracts.py']
    code={str(p).replace('\\','/'):sha(p) for p in paths}
    bound=dict(kind='source_unit_native_binding_v1',plan_commit=plan_commit,plan_sha256=sha(PLAN),
        source_units_sha256=sha(ROOT/'source-units.json'),requests_sha256=sha(ROOT/'requests.json'),
        preparation_sha256=sha(ROOT/'preparation.json'),requests=len(requests),reused_requests=0,
        maximum_validated_output_bytes=512*1024*1024,code=code,
        old_source_admission_unchanged=True,source_reconstruction_diagnostic_only=True,
        model_predictions=0,gold_certified=False,final_test_used=False)
    save(BINDING,bound)
    print(json.dumps(dict(requests=len(requests),binding_sha256=sha(BINDING),native_executed=False)))


def bound_inputs(commit):
    bound=json.loads(committed(BINDING,commit));plan=authenticate(bound['plan_commit'])
    for path,digest in bound['code'].items():
        committed(path,commit)
        if sha(path)!=digest:raise ValueError('unit35_native_code_changed')
    for filename,key in (('source-units.json','source_units_sha256'),('requests.json','requests_sha256'),('preparation.json','preparation_sha256')):
        if sha(ROOT/filename)!=bound[key]:raise ValueError('unit35_native_input_changed')
    return bound,plan,runtime(plan)


def aggregate_units(rows,snapshots):
    counts=defaultdict(Counter);cross=Counter()
    for row in rows:
        if set(row['views'])!=set(VIEWS):raise ValueError('unit35_metric_view_contract')
        scores=score_units(row,snapshots)
        for name,score in scores.items():
            for stratum in ('all',row['stratum']):
                counter=counts[stratum+'/'+name];counter['slots']+=1;counter[score['status']]+=1
                if score['status']=='measured':
                    counter['conversion_parts']+=score['parts']
                    for k,present in score['all_parts_present'].items():counter['source_supported_at_'+k]+=present
        if scores['whole_source']['status']=='measured' and not scores['whole_source']['all_parts_present']['32']:
            cross['whole_top32_missing']+=1
            for name in ('literal_runs','ruby_fragments'):
                status=('unmeasured' if scores[name]['status']!='measured' else
                        'all_parts_supported' if scores[name]['all_parts_present']['32'] else 'component_missing')
                cross[name+'/'+status]+=1
    return dict(by_stratum_view={key:dict(value) for key,value in counts.items()},whole_miss_comparison=dict(cross))


def execute(commit):
    bound,plan,identity=bound_inputs(commit);spec=plan['native']
    requests=read(ROOT/'requests.json')['requests'];rows=read(ROOT/'source-units.json')['rows']
    if not len(requests)==bound['requests']<=spec['maximum_unique_requests']:
        raise ValueError('unit35_native_request_bound')
    save(ROOT/'native-reservation.json',dict(binding_commit=commit,binding_sha256=sha(BINDING),requests=len(requests),slots=100))
    executor=load_script('unit35_reference_execution','research/reference_execution.py')
    validator=load_script('unit35_reference_validator','research/issue-31-quality/run_reference_probe.py')
    output_bytes=0;lock=threading.Lock()
    def validate(directory,raw,identity):
        nonlocal output_bytes
        size=(directory/'output.jsonl').stat().st_size
        with lock:
            output_bytes+=size
            if output_bytes>bound['maximum_validated_output_bytes']:raise ValueError('unit35_native_output_bound')
        return validator.validate_result(directory,raw,identity)
    execution,snapshots=executor.execute_requests(requests,ROOT/'candidates',identity,
        Path(spec['executable']),Path(spec['dictionary']),validate,
        concurrency=spec['concurrency'],request_timeout=spec['request_timeout_seconds'],total_timeout=spec['total_timeout_seconds'],
        progress=lambda done,total:print(json.dumps(dict(stage='source_unit_forward',processed=done,total=total)),flush=True))
    execution.update(binding_commit=commit,binding_sha256=sha(BINDING))
    save(ROOT/'native-execution.json',execution)
    bound_inputs(commit)
    surfaces={key:record['candidate_snapshots']['training_top32']['candidates'] for key,record in snapshots.items()}
    stats=aggregate_units(rows,surfaces)
    report=dict(kind='source_unit_native_diagnostic',status='complete' if not execution['not_attempted'] and execution['stop_reason'] is None else 'incomplete',
        binding_commit=commit,slots=100,unique_requests=len(requests),measured_requests=len(snapshots),
        outcomes=dict(Counter(a['status'] for a in execution['attempts'])),not_attempted=execution['not_attempted'],
        validated_output_bytes=output_bytes,execution_sha256=sha(ROOT/'native-execution.json'),
        elapsed_seconds=execution['elapsed_seconds'],**stats,
        interpretations=dict(whole_source='Whole-reading source-exact Top-k',literal_runs='All conversion parts source-exact at k, not joint rank',
            ruby_fragments='All original ruby bases source-exact at k; not complete words or sentences'),
        independent_accuracy=None,independent_gold_quality=None,confidence_interval=None,
        interval_reason='Exposed stratified source diagnostic with unresolved labels and shared ownership; not a representative independent accuracy estimate.',
        source_policy_changed=False,models_run=0,fits=0,gold_admitted=0,calibration_admitted=0,final_test_used=False)
    save(ROOT/'native-report.json',report)
    print(json.dumps({k:report[k] for k in ('status','unique_requests','measured_requests','outcomes','not_attempted','by_stratum_view','elapsed_seconds')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('seal','execute'));parser.add_argument('--commit',required=True)
    args=parser.parse_args();(seal if args.stage=='seal' else execute)(args.commit)
