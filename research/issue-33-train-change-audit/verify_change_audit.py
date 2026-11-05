"""Recount saved train predictions by scalar decisions and replay fixed exposure."""
from collections import Counter, defaultdict
import io
import json
from pathlib import Path
import sys

import numpy as np

from audit_training import ROOT, HERE, authenticate, authenticated_bytes, load_training, TrainingReadGuard, sha, save


def scalar_observation(scores, arrays, gated):
    result = {key:np.zeros(len(scores),dtype=np.int64 if key=='winner' else bool) for key in
              ('winner','correct','baseline_correct','rescue','harm','wrong_to_wrong','changed','failed_inference')}
    margins=np.full(len(scores),np.nan,dtype=np.float32)
    for i, row in enumerate(scores):
        valid=[j for j in range(6) if arrays['candidate_mask'][i,j]]
        failed=not valid or not all(np.isfinite(v) for v in row)
        winner=0 if failed else max(valid,key=lambda j:float(row[j]))
        if gated and not np.float32(row[winner]-row[0])>np.float32(1.7):winner=0
        before=bool(arrays['correct_mask'][i,0]);after=bool(arrays['correct_mask'][i,winner])
        changed=not bool(arrays['baseline_equivalent'][i,winner])
        for key,value in dict(winner=winner,correct=after,baseline_correct=before,rescue=not before and after,
            harm=before and not after,wrong_to_wrong=not before and not after and changed,changed=changed,failed_inference=failed).items():
            result[key][i]=value
        alternative=[j for j in valid if not arrays['baseline_equivalent'][i,j]]
        if not failed and alternative:
            best=max(alternative,key=lambda j:float(row[j]));margins[i]=np.float32(row[best]-row[0])
    result['proposed_change_margin']=margins
    return result


def close(actual, expected):
    if expected is None:
        assert actual is None
    else:
        assert np.allclose(actual,expected,atol=2e-6,rtol=1e-7), (actual,expected)


def run():
    plan,fit=authenticate()
    allowed=[*plan['training_artifacts'],*plan['prior_code'],*[m['path'] for m in plan['models']],
             plan['training_execution']['path'],'data/generated/issue-33-annotation-experiment-v1/fit-binding.json']
    guard=TrainingReadGuard(Path.cwd(),allowed,ROOT);sys.addaudithook(guard)
    arrays,cohorts,_=load_training(fit)
    a=set(map(int,cohorts['dictionary']));b=set(map(int,cohorts['annotation']))
    groups={k:np.array(sorted(v)) for k,v in dict(common_wikipedia=a&b,dictionary_aozora=a-b,annotation_aozora=b-a).items()}
    assert all(len(v)==25000 for v in groups.values())
    populations=dict(groups)
    for name,indexes in groups.items():
        for label,low,high in [('2',2,2),('3-4',3,4),('5-8',5,8),('9-32',9,32)]:
            populations[name+'/reading-'+label]=np.array([int(i) for i in indexes if low<=arrays['reading_lengths'][i]<=high],dtype=np.int64)
    report=json.loads((ROOT/'report.json').read_text());execution=json.loads((ROOT/'inference.json').read_text())
    assert report['inference_sha256']==sha(ROOT/'inference.json')
    assert execution['scores_sha256']==report['scores_sha256']==sha(ROOT/'scores.npz')
    bound=json.loads((ROOT/'reservation.json').read_text())
    for path,digest in bound['code'].items():assert sha(path)==digest
    with np.load(io.BytesIO((ROOT/'scores.npz').read_bytes()),allow_pickle=False) as stored:
        scores={k:np.array(stored[k]) for k in stored.files}
    assert len(scores)==14
    observed={};checked=0
    for key,value in scores.items():
        for gate in ['ungated','fixed_margin_1.7']:
            full=gate+'/'+key;obs=scalar_observation(value,arrays,gate!='ungated');observed[full]=obs
            for name,indexes in populations.items():
                claimed=report['metrics'][full][name]
                counts={k:int(obs[k][indexes].sum()) for k in ('correct','baseline_correct','rescue','harm','wrong_to_wrong','changed','failed_inference')}
                assert all(counts[k]==claimed[k] for k in counts)
                assert len(indexes)==claimed['rows']
                assert claimed['correction_failure']==counts['harm']+counts['wrong_to_wrong']
                for rate,numerator,denominator in [
                    ('source_correct_rate',counts['correct'],len(indexes)),('precision',counts['rescue'],counts['changed']),
                    ('recall',counts['rescue'],len(indexes)-counts['baseline_correct']),('coverage',counts['changed'],len(indexes)),
                    ('harm_rate',counts['harm'],counts['baseline_correct']),
                    ('error_application',counts['rescue']+counts['wrong_to_wrong'],len(indexes)-counts['baseline_correct'])]:
                    close(claimed[rate],None if not denominator else numerator/denominator)
                ranks=Counter(map(int,obs['winner'][indexes]));assert claimed['winner_rank_counts']==[ranks[j] for j in range(6)]
                margin=obs['proposed_change_margin'][indexes];margin=margin[np.isfinite(margin)]
                assert claimed['proposed_change_margin_rows']==len(margin)
                close(claimed['proposed_change_margin_quantiles'],None if not len(margin) else np.quantile(margin,[.1,.5,.9]))
                checked+=1
            for name,indexes in groups.items():
                counts=Counter((int(arrays['gold'][i]),int(obs['winner'][i])) for i in indexes)
                assert report['gold_rank_to_selected_rank'][full][name]==[[counts[(g,w)] for w in range(6)] for g in range(6)]
        print(json.dumps(dict(verified_condition=key,metric_populations=checked)),flush=True)
    pair_checks=0
    def verify_pair(claimed,first,second,indexes):
        for field in ('correct','rescue','harm','wrong_to_wrong','changed'):
            assert claimed[field+'_difference']==int(second[field][indexes].sum())-int(first[field][indexes].sum())
        assert claimed['winner_changes']==int((first['winner'][indexes]!=second['winner'][indexes]).sum())
        delta=second['proposed_change_margin'][indexes]-first['proposed_change_margin'][indexes];delta=delta[np.isfinite(delta)]
        assert claimed['margin_delta_rows']==len(delta) and claimed['margin_delta_positive']==int((delta>0).sum())
        close(claimed['margin_delta_quantiles'],None if not len(delta) else np.quantile(delta,[.1,.5,.9]))
    for key,values in report['annotation_minus_dictionary'].items():
        gate,context,seed=key.split('/');prefix=gate+'/'+context+'/'
        for name,indexes in groups.items():
            verify_pair(values[name],observed[prefix+'dictionary-s'+seed],observed[prefix+'annotation-s'+seed],indexes);pair_checks+=1
    for key,values in report['empty_minus_intact'].items():
        gate,model=key.split('/')
        for name,indexes in groups.items():
            verify_pair(values[name],observed[gate+'/intact/'+model],observed[gate+'/empty/'+model],indexes);pair_checks+=1
    ledger_path=next(p for p in fit['training_artifacts'] if p.endswith('/row-receipts.jsonl'))
    ledger=[json.loads(line) for line in authenticated_bytes(ledger_path,fit['training_artifacts'][ledger_path]).splitlines()]
    for name,indexes in groups.items():
        claimed=report['profile'][name];records=[ledger[int(i)] for i in indexes]
        inputs=Counter(r['input_tensor_sha256'] for r in records)
        labels=defaultdict(set)
        for r in records:labels[r['input_tensor_sha256']].add(r['label_tensor_sha256'])
        assert claimed['baseline_correct']==sum(bool(arrays['correct_mask'][i,0]) for i in indexes)
        assert claimed['input_duplicate_groups']==sum(v>1 for v in inputs.values())
        assert claimed['input_label_conflict_groups']==sum(len(v)>1 for v in labels.values())
    sys.path.insert(0,'research/issue-33-annotation-experiment')
    try:
        from train_models import batches
    finally:
        sys.path.pop(0)
    exposures=[];is_wiki=np.zeros(75000,dtype=bool);is_wiki[groups['common_wikipedia']]=True
    for seed in (20260814,20261103,20261104):
        counts={arm:np.zeros(75000,dtype=np.int64) for arm in cohorts};same=True
        for d,a in zip(batches(cohorts['dictionary'],seed,256,500),batches(cohorts['annotation'],seed,256,500)):
            same=bool(same and np.array_equal(d[is_wiki[d]],a[is_wiki[a]]))
            np.add.at(counts['dictionary'],d,1);np.add.at(counts['annotation'],a,1)
        assert all(int(v.sum())==128000 for v in counts.values())
        exposures.append(dict(seed=seed,common_wikipedia_same_per_update=same,
            common_wikipedia_exposures={arm:int(v[groups['common_wikipedia']].sum()) for arm,v in counts.items()},
            exposure_count_histograms={arm:dict(Counter(map(int,v[cohorts[arm]]))) for arm,v in counts.items()}))
    save(ROOT/'exposure-replay.json',dict(kind='fixed_sampler_replay',seeds=exposures,new_fits=0))
    result=dict(kind='train_change_direct_verification',status='passed',scalar_metric_populations=checked,paired_populations=pair_checks,
        training_rows=75000,profile_duplicate_checks=3,report_sha256=sha(ROOT/'report.json'),
        scores_sha256=sha(ROOT/'scores.npz'),exposure_sha256=sha(ROOT/'exposure-replay.json'),
        code_sha256=sha(HERE/'verify_change_audit.py'),forbidden_data_read_attempts=guard.blocked,
        cpu_parity_independently_rerun=False,cpu_parity_passed=execution['cpu_parity_passed'],
        cpu_numerical_limit='Original audit CPU/GPU sample is not allclose in six of fourteen conditions; no tolerance increase or claim of CPU-equivalent full census.',
        new_fits=0,gold_certified=False,final_test_used=False,production_adoption=False)
    assert guard.blocked==0
    save(ROOT/'verification.json',result)
    return result


if __name__=='__main__':print(json.dumps(run()))
