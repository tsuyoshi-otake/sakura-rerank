"""Authenticate the complete unused-source reservation and acquire it once."""
import argparse
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_hash
from balance_common import ROOT,HERE,PLAN,authenticate,boundary,read,save,sha

PLAN_COMMIT='8ea14eed349b375a63b09c744d3bf40c15ee196b'


def verify_reservation():
    plan=authenticate(PLAN_COMMIT);spec=plan['evaluation']
    membership_path=Path('data/generated/issue-31-kwdlc-probe-v1/train.id')
    tree_path=Path('data/generated/issue-41-language-pretraining-v1/tree.json')
    if sha(membership_path)!=spec['membership_sha256'] or sha(tree_path)!=spec['tree_sha256']:
        raise ValueError('balance_reservation_metadata_changed')
    membership=set(membership_path.read_text(encoding='utf-8').splitlines());old=set();counts=[]
    for path,digest in spec['reservation_metadata'].items():
        if sha(path)!=digest:raise ValueError('balance_previous_reservation_changed')
        value=read(path);documents=value.get('documents',value.get('selected_documents'))
        ids={r['document_id'] for r in documents}
        if len(ids)!=len(documents) or old&ids:raise ValueError('balance_previous_document_overlap')
        old.update(ids);counts.append(len(ids))
    expected=sorted(membership-old,key=lambda d:(canonical_json_hash([20261106,'loss-balance-v1',d]),d))
    selection=read(spec['selection_path']);selected=selection['documents'];tree=read(tree_path)
    by_path={r['path']:r for r in tree['tree']}
    if (len(old)!=3300 or len(membership)!=3915 or len(selected)!=615
            or [r['document_id'] for r in selected]!=expected or tree['truncated']
            or selection['corpus_commit']!=spec['source_commit'] or selection['corpus_tree']!=spec['source_tree']):
        raise ValueError('balance_unused_reservation_differs')
    for row in selected:
        source=by_path[row['path']]
        if (not row['path'].startswith('knp/') or row['path'].rsplit('/',1)[-1]!=row['document_id']+'.knp'
                or row['bytes']!=source['size'] or row['git_blob_sha1']!=source['sha']):
            raise ValueError('balance_reserved_blob_differs')
    if sum(r['bytes'] for r in selected)!=spec['expected_source_bytes']:
        raise ValueError('balance_reserved_bytes_differ')
    return plan,selection,dict(status='passed',membership=3915,prior_documents=3300,prior_counts=sorted(counts),
        reserved_documents=615,remaining_documents=0,overlap=0,source_bytes=spec['expected_source_bytes'],
        selection_sha256=spec['selection_sha256'],source_bodies_read=0,final_test_used=False,public_dev_test_used=False)


def run(code_commit):
    plan,selection,verification=verify_reservation()
    paths=[HERE/name for name in ('acquire_sources.py','balance_common.py','run_stage.py')]+[Path('research/reserved_source_acquisition.py')]
    for path in paths:boundary.committed(path,code_commit)
    save(ROOT/'reservation-verification.json',verification)
    identity=dict(execution_plan_commit=PLAN_COMMIT,execution_plan_sha256=sha(PLAN),plan_sha256=sha(PLAN),
        selection_sha256=plan['evaluation']['selection_sha256'],code_commit=code_commit,
        code={p.as_posix():sha(p) for p in paths})
    save(ROOT/'source-reservation.json',dict(**identity,documents=615,retries=0,replacements=0,final_test=False))
    executor=boundary.load_script('loss_balance_reserved_sources','research/reserved_source_acquisition.py')
    outcome=executor.acquire(ROOT,selection['documents'],plan['evaluation'],identity)
    return dict(status=outcome['status'],received=sum(r['status']=='received' for r in outcome['attempts']),
        slots=len(outcome['attempts']),elapsed_seconds=outcome['elapsed_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--code-commit',required=True)
    print(json.dumps(run(parser.parse_args().code_commit)))
