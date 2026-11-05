"""Build a new bounded numeric cache; no model or legacy-cache consumer."""
from collections import Counter,defaultdict
import json
import os
import platform
import subprocess
import time

from sakura_rerank.data.consumed_numeric import PURPOSE,project,schema,validate_arrays,chain_entry
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.growth_numeric import encode
from numeric_common import ROOT,PLAN,POLICY,PLAN_COMMIT,boundary,load_inputs,save,sha

CODE=("src/sakura_rerank/data/consumed_numeric.py","research/issue-33-consumed-numeric/numeric_common.py",
      "research/issue-33-consumed-numeric/build_cache.py")


def build():
    import numpy as np
    head=subprocess.check_output(["git","rev-parse","HEAD"],text=True,timeout=30).strip()
    for path in CODE:
        boundary.committed(path,head)
    plan,targets,components,receipts,snapshots=load_inputs()
    policy=sha(POLICY)
    inputs,projected_snapshots,seals=[],{},[]
    for row in targets:
        request=row["candidate_request_id"]
        value,snapshot,seal=project(row,receipts[row["stable_id"]],snapshots[request],components[row["stable_id"]],policy)
        if request in projected_snapshots and projected_snapshots[request]!=snapshot:
            raise ValueError("consumed_numeric_projection_depends_on_target")
        inputs.append(value);projected_snapshots[request]=snapshot;seals.append(seal)
    print(json.dumps(dict(stage="encode_authorized_projections",rows=len(inputs),readings=len(projected_snapshots))),flush=True)
    arrays,_=encode(inputs,projected_snapshots)
    validate_arrays(arrays,len(inputs))
    working,output=ROOT/"cache.partial",ROOT/"cache"
    if output.exists():
        raise ValueError("consumed_numeric_cache_already_published")
    working.mkdir(exist_ok=False)
    with (working/"arrays.npz").open("xb") as stream:
        np.savez_compressed(stream,**arrays)
        stream.flush();os.fsync(stream.fileno())
    previous="0"*64
    duplicate_labels,duplicate_components,counts=defaultdict(set),defaultdict(set),Counter()
    with (working/"row-receipts.jsonl").open("xb") as stream:
        for index,seal in enumerate(seals):
            record=chain_entry(index,previous,seal,arrays)
            stream.write(canonical_json_bytes(record)+b"\n")
            previous=record["record_sha256"]
            key=record["input_tensor_sha256"]
            counts[key]+=1
            duplicate_labels[key].add(record["label_tensor_sha256"])
            duplicate_components[key].add(seal["component_id"])
        stream.flush();os.fsync(stream.fileno())
    artifacts={name:sha(working/name) for name in ("arrays.npz","row-receipts.jsonl")}
    if any((working/name).stat().st_size>plan["bounds"]["artifact_bytes"] for name in artifacts):
        raise ValueError("consumed_numeric_output_size_bound")
    duplicate_summary=dict(unique_model_inputs=len(counts),duplicate_groups=sum(n>1 for n in counts.values()),
        duplicate_rows=sum(n for n in counts.values() if n>1),surplus_rows=sum(n-1 for n in counts.values()),
        conflicting_label_groups=sum(len(v)>1 for v in duplicate_labels.values()),
        cross_component_groups=sum(len(v)>1 for v in duplicate_components.values()))
    manifest=dict(kind="source_reconstruction_numeric_cache",status="prepared_unverified",rows=len(inputs),
        array_schema=schema(len(inputs)),artifacts=artifacts,row_chain_head=previous,
        allowed_consumer=PURPOSE,policy_sha256=policy,plan_sha256=sha(PLAN),plan_commit=PLAN_COMMIT,
        source_order_sha256=canonical_json_hash([r["stable_id"] for r in targets]),
        source_components=len(set(components.values())),unique_readings=len(projected_snapshots),
        all_annotation_denominators=plan["population"],input_tensor_duplicates=duplicate_summary,
        implementation={path:sha(path) for path in CODE},execution_commit=head,
        versions=dict(python=platform.python_version(),numpy=np.__version__),
        raw_array_bytes=sum(array.nbytes for array in arrays.values()),
        model_fits=0,model_inferences=0,new_native_requests=0,training_eligible=False,independent_gold_eligible=False,
        final_test_used=False,gold_certified=False,safety_threshold=.0025)
    save(working/"manifest.json",manifest)
    working.rename(output)
    report=dict(kind="consumed_numeric_preparation",status="prepared_unverified",rows=len(inputs),
        source_components=manifest["source_components"],unique_readings=len(projected_snapshots),
        cache_manifest_sha256=sha(output/"manifest.json"),row_chain_head=previous,array_schema=manifest["array_schema"],
        artifact_sha256=artifacts,raw_array_bytes=manifest["raw_array_bytes"],
        compressed_array_bytes=(output/"arrays.npz").stat().st_size,receipt_bytes=(output/"row-receipts.jsonl").stat().st_size,
        input_tensor_duplicates=duplicate_summary,original_annotation_denominators=plan["population"],
        policy_sha256=policy,plan_sha256=sha(PLAN),implementation=manifest["implementation"],execution_commit=head,
        model_fits=0,model_inferences=0,new_native_requests=0,legacy_training_labels_admitted=0,
        final_test_used=False,gold_certified=False,safety_threshold=.0025)
    save(ROOT/"report.json",report)
    save("reports/issue-33-consumed-numeric-v1.json",report)
    return {key:report[key] for key in ("status","rows","source_components","unique_readings","raw_array_bytes","compressed_array_bytes","input_tensor_duplicates")}


if __name__=="__main__":
    ROOT.mkdir(parents=True,exist_ok=True)
    reservation=ROOT/"reservation.json"
    if reservation.exists():
        raise ValueError("consumed_numeric_attempt_already_reserved")
    save(reservation,dict(status="reserved",plan_sha256=sha(PLAN)))
    started=time.monotonic()
    try:
        result=build()
    except Exception as error:
        save(ROOT/"execution.json",dict(status="failed",error_type=type(error).__name__,elapsed_seconds=round(time.monotonic()-started,3)))
        print(json.dumps(dict(status="failed",error_type=type(error).__name__)),flush=True)
        raise SystemExit(1) from None
    save(ROOT/"execution.json",dict(status="complete",report_sha256=sha(ROOT/"report.json"),elapsed_seconds=round(time.monotonic()-started,3)))
    print(json.dumps(result))
