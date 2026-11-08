"""Direct scalar source/native recount and immutable artifact verification."""
import ast
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unicodedata

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.tatoeba_source import audit_pair
from consume35_common import HERE, PAST, ROOT, UNITS, authenticate, committed, load_script, read, save, sha
from native_consumption import bound_inputs, checked_result
from prepare_cohort import metadata_rows


def scalar_groups(slots,snapshots,excluded):
    manual=defaultdict(Counter)
    for row in slots:
        isolation='no_input_hypothesis' if not row['inputs'] else 'historically_related' if any(p['stable_id'] in excluded for p in row['inputs']) else 'isolated_hypothesis'
        status=row['view']['status'] if row['view'] is not None else row['status']
        if status=='ready':status='measured' if all(p['request_id'] in snapshots for p in row['inputs']) else 'unmeasured'
        for group in ('all',row['stratum'],isolation):
            counts=manual[group];counts['slots']+=1;counts[status]+=1
            if status=='measured':
                counts['parts']+=len(row['inputs'])
                for k in (1,5,6,10,32):counts['all_parts_at_'+str(k)]+=all(p['target'] in snapshots[p['request_id']][:k] for p in row['inputs'])
            for part in row['inputs']:
                if part['request_id'] not in snapshots:counts['unmeasured_parts']+=1;continue
                counts['measured_parts']+=1
                for k in (1,5,6,10,32):counts['parts_at_'+str(k)]+=part['target'] in snapshots[part['request_id']][:k]
    return {k:dict(v) for k,v in manual.items()}


def run():
    selected_bound=read(HERE/'selection-binding-v1.json')
    plan=authenticate(selected_bound['plan_commit'])
    native=read(ROOT/'native-report.json')
    bound,_,identity=bound_inputs(native['binding_commit'])
    slots=read(ROOT/'consumed-slots.json')['rows'];selected=read(ROOT/'selection.json')['rows']
    previous={r['sentence_id'] for r in read(PAST/'selection.json')['rows']}
    population=list(metadata_rows())
    independent=sorted((r for r in population if r['sentence_id'] not in previous),
        key=lambda r:(hashlib.sha256(json.dumps([plan['policy'],plan['seed'],r['sentence_id']],
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),r['sentence_id']))[:1000]
    assert selected==independent and len(slots)==1000 and len({r['sentence_id'] for r in slots})==1000
    assert not previous & {r['sentence_id'] for r in slots}
    expected_requests={};positions=0
    for number,(row,meta) in enumerate(zip(slots,selected)):
        assert row['slot']==number and row['sentence_id']==meta['sentence_id']
        assert row['provenance']['administrative_owner_token']==meta['sentence']['owner_token']
        assert row['provenance']['transcription_editor_token']==meta['transcription']['editor_token']
        assert row['provenance']['original_author_token'] is None and row['provenance']['translation_lineage'] is None
        assert not row['ime_gold'] and not row['calibration_admitted'] and not row['final_test']
        alignment,parsed=audit_pair(row['sentence'],row['transcription'])
        assert alignment['source_exact']==row['source_exact']
        if row['status']!='ready_source_hypothesis':
            assert not row['inputs']
            if row['status']=='empty_or_missing_ruby':assert alignment['status']==row['status']
            elif row['status']=='unsupported_source_or_reading':
                phonetic=lambda c: 0x3041<=ord(c)<=0x3096 or 0x30a1<=ord(c)<=0x30f6 or c=='ー'
                assert parsed is not None and (any(not phonetic(c) for p in parsed.spans for c in p.reading)
                    or any(not phonetic(c) and unicodedata.category(c)[0] not in 'PS' for p in parsed.literal_segments for c in p))
            else:raise ValueError('consumption_unexpected_source_terminal')
            continue
        sentence=row['sentence']
        assert parsed.surface==sentence and row['source_exact']
        # Original source positions and reading spans are reconstructed without build_source_units.
        by_start={p.start:p for p in parsed.spans}
        pieces=[];pos=0
        while pos<len(sentence):
            span=by_start.get(pos)
            if span:
                pieces.append((span.start,span.end,span.base,span.reading));pos=span.end
            else:
                pieces.append((pos,pos+1,sentence[pos],sentence[pos]));pos+=1
        view=row['view'];assert view['status']=='ready'
        assert ''.join(p.get('target',p.get('text')) for p in view['parts'])==sentence
        for item in row['inputs']:
            assert item['left_context']=='' and item['context_kind']=='no_observed_session_context'
            assert sentence[item['start']:item['end']]==item['target']
            chosen=[p for p in pieces if item['start']<=p[0] and p[1]<=item['end']]
            original=''.join(p[3] for p in chosen)
            projected=''.join(chr(ord(c)-96) if 0x30a1<=ord(c)<=0x30f6 else c for c in original)
            assert projected==item['reading'] and ''.join(p[2] for p in chosen)==item['target']
            assert item['input_hash']==canonical_json_hash(['',item['reading']])
            expected_requests[item['request_id']]=dict(stable_id=item['request_id'],reading=item['reading'])
            positions+=1
    requests=read(ROOT/'requests.json')['requests']
    assert requests==[expected_requests[key] for key in sorted(expected_requests)]
    assert len(requests)==bound['requests'] and len(requests)<=4000
    validator=load_script('consume35_verify_validator','research/issue-31-quality/run_reference_probe.py')
    ledger=read(ROOT/'request-ledger.json')['rows'];snapshots={};observed_bytes=0
    assert [r['index'] for r in ledger]==list(range(len(requests)))
    for item,request in zip(ledger,requests):
        directory=ROOT/'candidates'/f"request-{item['index']:04d}"
        assert item['status']!='not_attempted' and item['terminal'] is not None
        result,record=checked_result(directory,request,item['terminal'],identity,validator)
        assert result['status']==item['status']
        if (directory/'output.jsonl').exists():observed_bytes+=(directory/'output.jsonl').stat().st_size
        if record is not None:snapshots[request['stable_id']]=[p['surface'] for p in record['candidate_snapshots']['training_top32']['candidates']]
    excluded=read(ROOT/'source-relations.json')['excluded'];manual=scalar_groups(slots,snapshots,excluded)
    assert manual==native['groups']
    assert dict(Counter(r['status'] for r in ledger))==native['outcomes']
    assert observed_bytes==native['output_bytes'] and not native['not_attempted'] and native['native_calls']==len(requests)
    history=read(ROOT/'history-report.json')
    assert history['full_reverse_parity'] and history['administrative_owner_links_retained']
    assert history['relations_sha256']==sha(ROOT/'source-relations.json')
    prior_requests={r['stable_id'] for r in read(UNITS/'requests.json')['requests']}
    occurrences=[p for r in read(UNITS/'source-units.json')['rows'] for v in r['views'].values() for p in v['parts'] if p['kind']=='convert']
    assert {p['request_id'] for p in occurrences}==prior_requests
    assert len(occurrences)==history['previous_native_occurrences'] and len(prior_requests)==history['previous_native_requests']
    assert history['history_nodes']==988073+100+312+len(occurrences)
    exposure=read(ROOT/'source-exposure-report.json')
    exposure_binding=json.loads(committed(HERE/'source-exposure-binding-v1.json',exposure['binding_commit']))
    for path,digest in {**exposure_binding['inputs'],**exposure_binding['code']}.items():assert sha(path)==digest
    assert exposure['full_reverse_parity'] and exposure['exposed_source_count']==100
    assert exposure['relations_sha256']==sha(ROOT/'source-relations-v2.json')
    revised=read(ROOT/'source-relations-v2.json')['excluded']
    assert all(revised.get(key)==reason for key,reason in excluded.items())
    assert len(set(revised)-set(excluded))==exposure['additional_excluded_inputs']
    corrected=scalar_groups(slots,snapshots,revised)
    assert corrected['all']==manual['all']
    models=json.loads(committed('research/issue-33-loss-balance/evaluation-binding-v1.json','5fcbb79afcf109391f75e6e880228c259d11f4a4'))['models']
    for model in models:assert sha(model['path'])==model['sha256']
    completed=subprocess.run([sys.executable,'research/issue-33-data-growth/verify_integrity.py'],capture_output=True,timeout=300)
    assert completed.returncode==0
    integrity=json.loads(completed.stdout)
    assert integrity['status']=='passed' and integrity['original_artifacts']==16 and integrity['bound_fit_artifacts']==25
    files=list(HERE.glob('*.py'))+[Path('src/sakura_rerank/data/tatoeba_consumption.py'),Path('src/sakura_rerank/data/source_exposure.py'),
        Path('tests/test_tatoeba_consumption.py'),Path('tests/test_source_consumption_metrics.py'),Path('tests/test_source_exposure.py')]
    for path in files:
        tree=ast.parse(path.read_bytes());compile(tree,str(path),'exec')
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)) and getattr(node,'module',None)!='__future__':
                assert all((a.asname or a.name.split('.')[0]) in names for a in node.names)
    tests=read(ROOT/'full-unit-tests-r2.json')
    assert tests['successful'] and not tests['errors'] and not tests['failures'] and not tests['skipped']
    save(ROOT/'source-metrics-v2.json',dict(groups=corrected,original_native_report_sha256=sha(ROOT/'native-report.json'),
        explicit_source_exposure_sha256=sha(ROOT/'source-exposure-report.json'),native_retries=0))
    report=dict(status='passed',slots=len(slots),positions=positions,requests=len(requests),groups=len(manual),
        verification_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,timeout=30).strip(),
        verification_code_sha256=sha(HERE/'verify_consumption.py'),
        independent_metadata_ordering=True,source_position_and_projection_recount=True,
        native_receipts_revalidated=True,scalar_metric_recount=True,full_unit_tests=tests,
        old_integrity=integrity,unchanged_checkpoints=len(models),python_files_compiled=len(files),unused_imports=0,
        native_report_sha256=sha(ROOT/'native-report.json'),history_report_sha256=sha(ROOT/'history-report.json'),
        source_exposure_sha256=sha(ROOT/'source-exposure-report.json'),corrected_metrics_sha256=sha(ROOT/'source-metrics-v2.json'),
        fits=0,model_inference=0,gold_admission=0,final_test=False)
    save(ROOT/'verification.json',report)
    print(json.dumps(report))


if __name__=='__main__':run()
