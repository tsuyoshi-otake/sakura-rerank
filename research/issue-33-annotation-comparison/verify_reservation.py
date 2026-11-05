"""Recompute the fixed unseen public-train reservation without opening text."""
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_hash
from comparison_common import ROOT,authenticate,read,save,sha


def verify():
    plan=authenticate();spec=plan['evaluation'];selection=read(spec['selection_path'])
    membership_path=Path('data/generated/issue-31-kwdlc-probe-v1/train.id')
    tree_path=Path('data/generated/issue-41-language-pretraining-v1/tree.json')
    if sha(membership_path)!=spec['membership_sha256'] or sha(tree_path)!=spec['tree_sha256']:
        raise ValueError('reservation_verifier_metadata_changed')
    membership=set(membership_path.read_text(encoding='utf-8').splitlines())
    exposed=set();counts=[]
    for path,digest in spec['reservation_metadata'].items():
        if sha(path)!=digest: raise ValueError('reservation_verifier_prior_hash')
        old=read(path);documents=old.get('selected_documents',old.get('documents'))
        identifiers={row['document_id'] for row in documents}
        if len(identifiers)!=len(documents) or exposed & identifiers:
            raise ValueError('reservation_verifier_prior_duplicate')
        exposed.update(identifiers);counts.append(len(documents))
    expected=sorted(membership-exposed,key=lambda doc:(canonical_json_hash([20261105,'annotation-recipe-v1',doc]),doc))[:1000]
    selected=selection['documents'];identifiers=[row['document_id'] for row in selected]
    tree=read(tree_path);by_path={row['path']:row for row in tree['tree']}
    if (len(membership)!=3915 or len(exposed)!=2300 or not exposed<=membership or identifiers!=expected
            or len(set(identifiers))!=1000 or set(identifiers)&exposed or tree['truncated']
            or selection['corpus_tree']!=tree['sha'] or selection['corpus_commit']!=spec['source_commit']):
        raise ValueError('reservation_verifier_membership_or_order')
    for row in selected:
        source=by_path[row['path']]
        if (not row['path'].startswith('knp/') or row['path'].rsplit('/',1)[-1]!=row['document_id']+'.knp'
                or row['git_blob_sha1']!=source['sha'] or row['bytes']!=source['size']):
            raise ValueError('reservation_verifier_document_binding')
    result=dict(kind='annotation_comparison_research_reservation_verification',status='passed',public_train_membership=len(membership),
        previous_documents=len(exposed),previous_reservation_counts=sorted(counts),reserved_documents=len(identifiers),overlap=0,
        remaining_documents=len(membership-exposed)-len(identifiers),source_bytes=sum(r['bytes'] for r in selected),
        selection_sha256=sha(spec['selection_path']),full_selection_order_recomputed=True,source_bodies_opened_by_verifier=0,
        public_dev_test_used=False,final_test_used=False,gold_certified=False,script_sha256=sha(__file__))
    if result['source_bytes']!=spec['expected_source_bytes']: raise ValueError('reservation_verifier_byte_count')
    save(ROOT/'reservation-verification.json',result)
    return result


if __name__=='__main__': print(json.dumps(verify()))
