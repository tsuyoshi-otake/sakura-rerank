"""Training-only outcomes after the two CPU output sets have been sealed."""
import argparse
import io
import json
import sys
import numpy as np

from sakura_rerank.data.consumed_numeric import LABEL_FIELDS,MODEL_FIELDS,tensor_hash,validate_arrays,verify_chain
from proposal_common import CACHE,HERE,OOF,ROOT,committed,guard_summary,install_read_guard,read,save,sha
from proposal_metrics import input_ceiling
from run_cpu import bound

sys.path.insert(0,'research/issue-33-train-change-audit')
try:from change_metrics import observations,partitions,summary
finally:sys.path.pop(0)


def populations(records,indices,metadata):
    groups=partitions(indices,75000);groups['union']=np.arange(75000)
    for arm,positions in indices.items():
        groups[arm]=np.asarray(positions,np.int64)
        for fold in range(5):
            groups[arm+'/fold-'+str(fold)]=np.asarray([i for i in positions if metadata['arms'][arm]['row_fold'][records[i]['row_key']]==fold],np.int64)
    return groups


def analyze(commit):
    committed(HERE/'analyze_proposals.py',commit);committed(HERE/'proposal_metrics.py',commit)
    inference=read(ROOT/'inference.json');spec=bound(inference['binding_commit']);seal=read(ROOT/'outputs-seal.json')
    if inference['status']!='complete' or seal['status']!='complete' or seal['inference_sha256']!=sha(ROOT/'inference.json') or not seal['labels_not_yet_decoded']:
        raise ValueError('proposal_labels_before_complete_scores')
    save(ROOT/'analysis-reservation.json',dict(code_commit=commit,outputs_seal_sha256=sha(ROOT/'outputs-seal.json'),labels='bound_training_only'))
    guard=install_read_guard([CACHE/'arrays.npz',CACHE/'manifest.json',CACHE/'row-receipts.jsonl',CACHE/'cohort-indices.json',OOF/'training-identities.json'])
    manifest=read(CACHE/'manifest.json')
    with np.load(io.BytesIO((CACHE/'arrays.npz').read_bytes()),allow_pickle=False) as archive:arrays={key:archive[key] for key in archive.files}
    validate_arrays(arrays,75000)
    ledger=verify_chain((CACHE/'row-receipts.jsonl').read_bytes(),75000,manifest['row_chain_head'])
    for i,row in enumerate(ledger):
        if tensor_hash(arrays,i,MODEL_FIELDS)!=row['input_tensor_sha256'] or tensor_hash(arrays,i,LABEL_FIELDS)!=row['label_tensor_sha256']:
            raise ValueError('proposal_training_sidecar_changed')
    identities=read(OOF/'training-identities.json');records=identities['rows'];indices=read(CACHE/'cohort-indices.json');results={}
    for condition in spec['conditions']:
        item=next(r for r in inference['conditions'] if r['condition']==condition)
        if sha(ROOT/(condition+'-scores.npz'))!=item['scores_sha256']:raise ValueError('proposal_sealed_scores_changed')
        with np.load(ROOT/(condition+'-scores.npz'),allow_pickle=False) as archive:scores=archive['scores'];states=archive['states']
        if scores.shape!=(75000,6) or not np.isfinite(scores).all() or not np.all(states==1):raise ValueError('proposal_incomplete_scores')
        metadata=read(ROOT/(condition+'-metadata.json'));groups=populations(records,indices,metadata)
        observed={label:observations(scores,arrays,gated) for label,gated in (('ungated',False),('published_L_gt_1p7',True))}
        results[condition]=dict(metrics={label:{name:summary(value,positions) for name,positions in groups.items()} for label,value in observed.items()},
            input_label_limits={name:input_ceiling(metadata['numeric_hashes'],arrays['correct_mask'],positions) for name,positions in groups.items()})
    result=dict(kind='fixed_cpu_training_proposal_diagnostic',status='source_reconstruction_census_not_independent_accuracy',code_commit=commit,
        outputs_seal_sha256=sha(ROOT/'outputs-seal.json'),results=results,training_rows=75000,training_sidecar_rows_verified=75000,
        new_fits=0,threshold_search=False,calibration=False,final_test=False,independent_accuracy_estimated=False,gold_certified=False,safety_limit=.0025,
        scope='All denominators are the previously consumed source training pool. Reported empirical information ceilings do not certify Japanese conversion intent.',
        **guard_summary(guard))
    save(ROOT/'analysis.json',result)
    return dict(status=result['status'],conditions=2,metric_populations=sum(len(v) for r in results.values() for v in r['metrics'].values()),new_fits=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);print(json.dumps(analyze(parser.parse_args().commit)))
