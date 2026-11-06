"""Complete source-presence and direct input-exposure census; no model calls."""
from collections import Counter,defaultdict
import json

from sakura_rerank.data.consumed_numeric import MODEL_FIELDS,tensor_hash
from sakura_rerank.data.contrast_capacity import candidate_evidence
from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.research_tiny import character_ids
from sakura_rerank.source_model_inputs import encode_snapshot
from rebuild_common import CPU,HISTORICAL,previous,read,require


def old_inputs():
    cache=previous.previous.CACHE
    with (cache/'row-receipts.jsonl').open('rb') as stream:ledger=[json.loads(line) for line in stream]
    require(len(ledger)==75000 and canonical_json_hash([r['origin']['stable_id'] for r in ledger])==read(cache/'manifest.json')['source_order_sha256'],'cache_identity_order')
    current={}
    for condition in ('source','empty'):
        hashes=read(CPU/(condition+'-metadata.json'))['numeric_hashes']
        require(len(hashes)==len(ledger),'current_numeric_count')
        groups=defaultdict(list)
        for i,digest in enumerate(hashes):groups[digest].append(i)
        current[condition]=groups
    history=defaultdict(list)
    records=read(HISTORICAL)
    require(len(records)==14304 and Counter(r['split'] for r in records)==dict(train=12516,dev=1788),'historical_count')
    for row in records:history[row['numeric']].append(row)
    return ledger,current,history


def measure(rebuilds,snapshots,request_states):
    ledger,current,history=old_inputs();rows=[]
    for repair in rebuilds:
        row=repair['input'];entry=dict(parent_original_row_sha256=repair['lineage']['parent_original_row_sha256'],
            lineage_sha256=repair['lineage_sha256'],child_input_sha256=repair['lineage']['rebuilt_input_sha256'],
            status=repair['status'],candidate=None,numeric={})
        if row is not None:
            request=row['candidate_request_id'];snapshot=snapshots.get(request)
            entry['status']=request_states[request]
            entry['candidate']=candidate_evidence(row['target'],snapshot)
            if snapshot is not None:
                require(snapshot['reading']==row['reading'] and snapshot['stable_id']==request,'snapshot_reading')
                arrays,profile=encode_snapshot(snapshot)
                entry['encoding_profile']=profile
                for condition in ('empty','source'):
                    if condition=='source':
                        ids,length=character_ids(row['left_context'],64)
                        arrays['context_ids'][0]=ids;arrays['context_lengths'][0]=length
                    digest=tensor_hash(arrays,0,MODEL_FIELDS)
                    matches=current[condition].get(digest,[])
                    entry['numeric'][condition]=dict(input_sha256=digest,current_cache_rows=matches,
                        matching_parent_components=sorted({ledger[i]['origin']['component_id'] for i in matches}),
                        historical_matches=history.get(digest,[]))
        rows.append(entry)
    return rows


def summary(rows):
    measured=[r for r in rows if r['status']=='complete']
    counts=dict(parents=len(rows),measured_rows=len(measured),unmeasured_rows=len(rows)-len(measured),
        parent_outcomes=dict(Counter(r['status'] for r in rows)),
        source_presence={str(k):sum(r['candidate']['presence'][str(k)] for r in measured) for k in (1,5,6,10,32)},
        candidate_eligible_rows=sum(r['candidate']['eligible'] for r in measured),
        candidate_statuses=dict(Counter(r['candidate']['status'] for r in measured)),
        truncated_candidate_rows=sum(r['encoding_profile']['any_truncation'] for r in measured),
        encoded_collision_rows=sum(bool(r['encoding_profile']['encoded_surface_collision_pairs']) for r in measured),exposure={})
    for condition in ('source','empty'):
        values=[r['numeric'][condition] for r in measured];groups=Counter(r['input_sha256'] for r in values)
        counts['exposure'][condition]=dict(measured_rows=len(values),unique_inputs=len(groups),
            duplicate_groups=sum(n>1 for n in groups.values()),rows_in_duplicate_groups=sum(n for n in groups.values() if n>1),
            current_input_match_rows=sum(bool(r['current_cache_rows']) for r in values),
            historical_input_match_rows=sum(bool(r['historical_matches']) for r in values),
            historical_train_match_rows=sum(any(m['split']=='train' for m in r['historical_matches']) for r in values),
            historical_dev_match_rows=sum(any(m['split']=='dev' for m in r['historical_matches']) for r in values))
    return counts
