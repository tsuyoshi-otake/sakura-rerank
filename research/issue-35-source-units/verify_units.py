"""Direct positions, terminal outcomes and scalar source-presence recounts."""
import ast
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unicodedata

from sakura_rerank.data.contracts import ContractError
from unit35_common import ROOT,HERE,PAST,authenticate,read,save,sha,load_script,committed
from unit_native import bound_inputs


def h(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def run():
    plan=authenticate('1226b2dbc1e6bdbd59ec629619a8011736403f67')
    _,_,identity=bound_inputs('0fe29e14f3025267c499d8b6164b427d23676320')
    continuation=json.loads(committed(HERE/'native-continuation-v1.json','6a773ebed465f296f4be7de20b0249e7d21e9fd8'))
    for path,digest in continuation['previous_artifacts'].items():
        assert sha(path)==digest
    rows=read(ROOT/'source-units.json')['rows'];old=read(PAST/'decoded-pilot.json')
    source={r['sentence_id']:r for r in old['slots']}
    requests=read(ROOT/'requests.json')['requests'];expected_requests={};positions=0
    transliteration=str.maketrans({chr(n):chr(n-0x60) for n in range(0x30a1,0x30f7)})
    for row in rows:
        original=source[row['sentence_id']]
        if original['parsed'] is None:
            assert all(not v['parts'] for v in row['views'].values());continue
        sentence=original['sentence'];spans=original['parsed']['spans']
        assert row['target']==sentence and not row['ime_gold']
        cursor=0;pieces=[];covered=set()
        for span in spans:
            assert sentence[span['start']:span['end']]==span['base']
            pieces.extend([sentence[cursor:span['start']],span['reading']]);cursor=span['end']
            covered.update(range(span['start'],span['end']))
        pieces.append(sentence[cursor:])
        assert row['reading']==''.join(pieces).translate(transliteration)
        separators=[i for i,c in enumerate(sentence) if i not in covered and unicodedata.category(c)[0] in 'PS']
        expected=[];start=0
        for index in separators+[len(sentence)]:
            if index>start:expected.append((start,index,sentence[start:index]))
            start=index+1
        run_parts=[p for p in row['views']['literal_runs']['parts'] if p['kind']=='convert']
        assert [(p['start'],p['end'],p['target']) for p in run_parts]==expected
        assert [(p['start'],p['end'],p['target'],p['reading']) for p in row['views']['ruby_fragments']['parts']]==[
            (s['start'],s['end'],s['base'],s['reading'].translate(transliteration)) for s in spans]
        positions+=len(spans)
        for name,view in row['views'].items():
            if view['status']!='ready':continue
            if name!='ruby_fragments':
                assert ''.join(p['text'] if p['kind']=='literal' else p['target'] for p in view['parts'])==sentence
            for part in view['parts']:
                if part['kind']!='convert':continue
                assert part['target']==sentence[part['start']:part['end']]
                identifier='boundary-reading-'+h(part['reading'])
                assert part['request_id']==identifier
                expected_requests[identifier]=dict(stable_id=identifier,reading=part['reading'])
    assert len(rows)==100 and positions==312
    assert requests==[expected_requests[key] for key in sorted(expected_requests)]
    ledger=read(ROOT/'request-ledger-v2.json')['requests'];assert [r['index'] for r in ledger]==list(range(426))
    original=read(ROOT/'native-execution.json');assert {r['index'] for r in original['attempts']}==set(range(14))
    validator=load_script('unit35_final_native_validator','research/issue-31-quality/run_reference_probe.py')
    snapshots={};terminal_counts=Counter();segment_counts=Counter();output_bytes=0
    for index,(request,terminal) in enumerate(zip(requests,ledger)):
        directory=ROOT/('candidates' if index<14 else 'continuation-candidates')/f'request-{index:04d}'
        assert terminal['origin']==('first_attempt' if index<14 else 'continuation')
        receipt=read(directory/'execution.json');raw=(directory/'input.jsonl').read_bytes()
        assert json.loads(raw)==request and sha(directory/'input.jsonl')==receipt['input_sha256']
        terminal_counts[terminal['status']]+=1
        if (directory/'output.jsonl').exists():output_bytes+=(directory/'output.jsonl').stat().st_size
        if terminal['status']=='complete':
            assert receipt['status']=='complete' and receipt['exit_code']==0
            assert sha(directory/'output.jsonl')==receipt['output_sha256']
            record=validator.validate_result(directory,raw,identity)[0]
            snapshots[request['stable_id']]=record['candidate_snapshots']['training_top32']['candidates']
        elif terminal['status']=='output_contract_rejected':
            assert receipt['status']=='failed' and receipt['exit_code']==0
            assert sha(directory/'output.jsonl')==terminal['output_sha256']
            try:validator.validate_result(directory,raw,identity)
            except ContractError as error:
                assert hashlib.sha256(str(error).encode()).hexdigest()==terminal['validation_error_sha256']
            else:raise AssertionError('contract_rejection_not_reproduced')
            candidates=read(directory/'output.jsonl')['candidate_snapshots']['training_top32']['candidates']
            lengths=[len(c['segments']) for c in candidates]
            assert lengths==terminal['observed_segment_counts'] and any(n>18 for n in lengths)
            segment_counts.update(lengths)
        elif terminal['status']=='candidate_count_rejected':
            assert receipt['status']=='candidate_count_rejected' and receipt['exit_code']==2
            assert not (directory/'output.jsonl').exists() and not (directory/'native-report.json').exists()
            assert sha(directory/'stderr.log')==receipt['stderr_sha256']
            assert (directory/'stderr.log').read_bytes()==b'research exporter failed: converter returned an invalid candidate count\n'
        else:raise AssertionError('unresolved_native_terminal')
    # Scalar ranks independently of score_view/aggregate_units.
    counts=defaultdict(Counter);cross=Counter();paired=Counter();request_roles=defaultdict(set)
    for row in rows:
        scores={}
        for name,view in row['views'].items():
            parts=[p for p in view['parts'] if p['kind']=='convert']
            for part in parts:request_roles[part['request_id']].add(name)
            status=view['status']
            if status=='ready':status='unmeasured' if any(p['request_id'] not in snapshots for p in parts) else 'measured'
            ranks=[]
            if status=='measured':
                for part in parts:
                    candidates=snapshots[part['request_id']]
                    found=[i+1 for i,c in enumerate(candidates) if c['surface']==part['target']]
                    ranks.append(min(found) if found else None)
            present={k:status=='measured' and all(r is not None and r<=k for r in ranks) for k in (1,5,6,10,32)}
            scores[name]=(status,present)
            for stratum in ('all',row['stratum']):
                counter=counts[stratum+'/'+name];counter['slots']+=1;counter[status]+=1
                if status=='measured':
                    counter['conversion_parts']+=len(parts)
                    for k,value in present.items():counter['source_supported_at_'+str(k)]+=value
        if scores['whole_source'][0]=='measured' and not scores['whole_source'][1][32]:
            cross['whole_top32_missing']+=1
            for name in ('literal_runs','ruby_fragments'):
                label='unmeasured' if scores[name][0]!='measured' else 'all_parts_supported' if scores[name][1][32] else 'component_missing'
                cross[name+'/'+label]+=1
        def pair_state(name):
            return scores[name][0] if scores[name][0]!='measured' else 'supported32' if scores[name][1][32] else 'missing32'
        paired[pair_state('literal_runs')+'/'+pair_state('ruby_fragments')]+=1
    report=read(ROOT/'native-report-v2.json')
    assert {k:dict(v) for k,v in counts.items()}==report['by_stratum_view']
    assert dict(cross)==report['whole_miss_comparison']
    assert terminal_counts==report['outcomes'] and report['not_attempted']==0 and report['native_requests_retried']==0
    assert report['output_bytes_observed']==output_bytes
    failure_roles=defaultdict(Counter)
    for request,terminal in zip(requests,ledger):
        if terminal['status']=='complete':continue
        for role in request_roles[request['stable_id']]:failure_roles[role][terminal['status']]+=1
    owners=read(ROOT/'owner-diagnostic.json')
    group_records=Counter(r['source']['template_cluster_id'] for r in old['source_coverage']+old['input_hypotheses'] if r['source']['template_cluster_id'])
    assert sum(n-1 for n in group_records.values())==owners['selected_owner_omitted_edges']==320
    assert owners['legacy_author_edges_retained']==528894 and owners['all_retained_edge_endpoints_and_types_identical']
    assert owners['independent_null_owner_rebuild_parity'] and owners['original_exclusions_restored']==0
    # Authenticate all10 pre-existing models without loading model state or running inference.
    model_binding=json.loads(committed('research/issue-33-loss-balance/evaluation-binding-v1.json','5fcbb79afcf109391f75e6e880228c259d11f4a4'))
    for model in model_binding['models']:assert sha(model['path'])==model['sha256']
    historical=subprocess.run([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],capture_output=True,timeout=300)
    assert historical.returncode==0
    integrity=json.loads(historical.stdout)
    assert integrity['status']=='passed' and integrity['original_artifacts']==16 and integrity['bound_fit_artifacts']==25
    code=list(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/tatoeba_input_units.py'),Path('src/sakura_rerank/data/source_owner_diagnostic.py')]
    code += [Path('tests')/name for name in ('test_tatoeba_input_units.py','test_source_owner_diagnostic.py','test_source_unit_metrics.py','test_source_unit_continuation.py')]
    trees={p:ast.parse(p.read_bytes()) for p in code}
    exports=defaultdict(set)
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):exports[node.module].update(a.name for a in node.names)
    frozen_unused=[]
    for path,tree in trees.items():
        compile(tree,str(path),'exec');used={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}|exports[path.stem]
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)) and getattr(node,'module',None)!='__future__':
                for alias in node.names:
                    if (alias.asname or alias.name.split('.')[0]) in used:continue
                    # This planner was executed and hash-bound before corpus use.
                    # Preserve that provenance artifact; do not silently edit it
                    # merely to erase the finding from the historical code check.
                    if path.as_posix()=='research/issue-35-source-units/reserve_unit_plan.py' and alias.name=='ROOT':
                        assert sha(path)==plan['code'][path.as_posix()]
                        frozen_unused.append(dict(path=path.as_posix(),name=alias.name,reason='executed_hash_bound_planner_preserved'))
                    else:raise AssertionError(('unused_import',path.as_posix(),alias.name))
    result=dict(kind='source_units_direct_verification',status='passed',source_slots=100,source_ruby_positions=312,
        unique_requests=426,terminal_counts=dict(terminal_counts),native_requests_retried=0,
        scalar_metric_groups=len(counts),paired_literal_runs_vs_ruby_fragments=dict(paired),
        rejected_request_roles={k:dict(v) for k,v in failure_roles.items()},rejected_candidate_segment_counts=dict(segment_counts),
        output_bytes=output_bytes,selected_owner_edges_recounted=320,legacy_author_edges_retained=528894,
        old_integrity=integrity,unchanged_checkpoints=len(model_binding['models']),python_files_compiled=len(code),
        unbound_unused_imports=0,frozen_unused_imports=frozen_unused,
        report_sha256=sha(ROOT/'native-report-v2.json'),owner_report_sha256=sha(ROOT/'owner-diagnostic.json'),
        gold_certified=False,final_test_used=False,models_run=0)
    save(ROOT/'verification.json',result)
    print(json.dumps(result))


if __name__=='__main__':run()
