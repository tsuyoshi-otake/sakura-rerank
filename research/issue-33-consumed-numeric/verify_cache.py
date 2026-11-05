"""Reconstruct every numeric element without using the producer's encoder."""
from collections import Counter,defaultdict
import hashlib
import json

from sakura_rerank.data.consumed_numeric import PURPOSE,MODEL_FIELDS,LABEL_FIELDS,SHAPES,dtype_for,load_prepared_cache
from sakura_rerank.data.contracts import canonical_json_hash
from numeric_common import ROOT,POLICY,load_inputs,read_json,save,sha


def original_encoding(row,snapshot):
    import numpy as np
    values={name:np.zeros(shape,dtype=dtype_for(name)) for name,shape in SHAPES.items()}
    def chars(text,width):
        if not 0 < len(text) <= width:
            raise ValueError("numeric_verifier_text_bound")
        return np.asarray([1+(ord(c)*2654435761)%13311 for c in text]+[0]*(width-len(text)),dtype="<i8")
    values["context_ids"]=chars(row["left_context"],64)
    values["context_lengths"][...]=len(row["left_context"])
    values["reading_ids"]=chars(row["reading"],32)
    values["reading_lengths"][...]=len(row["reading"])
    top=snapshot["candidate_snapshots"]["production_top6"]["candidates"]
    if top!=snapshot["candidate_snapshots"]["training_top32"]["candidates"][:6] or not 2<=len(top)<=6:
        raise ValueError("numeric_verifier_candidate_prefix")
    costs=[float(c["local_cost"]) for c in top]
    minimum,span=min(costs),max(max(costs)-min(costs),1.0)
    positives=[]
    for index,candidate in enumerate(top):
        surface=candidate["surface"]
        prefix=0
        while prefix<min(len(row["reading"]),len(surface)) and row["reading"][prefix]==surface[prefix]:
            prefix+=1
        cost=costs[index]
        values["candidate_ids"][index]=chars(surface,32)
        values["candidate_lengths"][index]=len(surface)
        values["candidate_mask"][index]=True
        values["features"][index]=[-(cost-minimum)/span,-index/5,min(len(candidate["segments"]),8)/8,
            len(surface)/32,prefix/max(len(row["reading"]),len(surface),1),
            float(candidate["source_category"]=="system_dictionary"),-np.float32(np.log1p(max(cost-minimum,0.0)/1000.0))]
        values["correct_mask"][index]=surface==row["target"]
        values["baseline_equivalent"][index]=surface==top[0]["surface"]
        if surface==row["target"]:
            positives.append(index)
            if any(s["source_category"]!="system_dictionary" for s in candidate["segments"]):
                raise ValueError("numeric_verifier_target_path")
    if len(positives)!=1:
        raise ValueError("numeric_verifier_unique_source_target")
    values["gold"][...]=positives[0]
    return values


def row_digest(values,names):
    digest=hashlib.sha256()
    for name in names:
        array=values[name]
        header=json.dumps([name,array.dtype.str,list(array.shape)],ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
        digest.update(header);digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def original_seal(row,receipt,snapshot,component):
    projected={key:row[key] for key in ("stable_id","corpus","left_context","reading","target","candidate_request_id")}
    projected["component_id"]=component
    candidates=[]
    for candidate in snapshot["candidate_snapshots"]["training_top32"]["candidates"]:
        candidates.append({"surface":candidate["surface"],"local_cost":candidate["local_cost"],"source_category":candidate["source_category"],
            "segments":[{"source_category":segment["source_category"]} for segment in candidate["segments"]]})
    projection={"candidate_snapshots":{"training_top32":{"candidates":candidates},"production_top6":{"candidates":candidates[:6]}}}
    return dict(stable_id=row["stable_id"],component_id=component,policy_sha256=sha(POLICY),
        original_row_sha256=canonical_json_hash(row),consumption_sha256=canonical_json_hash(receipt),
        snapshot_sha256=canonical_json_hash(snapshot),projection_sha256=canonical_json_hash([projected,projection]),
        label_task="original_annotation_reconstruction",ime_quality="unresolved",training_eligible=False,independent_gold_eligible=False)


def verify():
    import numpy as np
    report=read_json(ROOT/"report.json")
    execution=read_json(ROOT/"execution.json")
    if execution["status"]!="complete" or execution["report_sha256"]!=sha(ROOT/"report.json"):
        raise ValueError("numeric_verifier_build_not_complete")
    for path,digest in report["implementation"].items():
        if sha(path)!=digest:
            raise ValueError("numeric_verifier_implementation_changed")
    plan,targets,components,receipts,snapshots=load_inputs()
    arrays,records,manifest=load_prepared_cache(ROOT/"cache",report["cache_manifest_sha256"],purpose=PURPOSE)
    if (len(targets)!=manifest["rows"] or len(records)!=len(targets) or report["rows"]!=len(targets)
            or manifest["source_order_sha256"]!=canonical_json_hash([r["stable_id"] for r in targets])
            or manifest["all_annotation_denominators"]!=plan["population"]
            or manifest["policy_sha256"]!=sha(POLICY) or report["artifact_sha256"]!=manifest["artifacts"]
            or manifest["row_chain_head"]!=report["row_chain_head"]):
        raise ValueError("numeric_verifier_manifest_denominator")
    counts,labels,component_groups=Counter(),defaultdict(set),defaultdict(set)
    print(json.dumps(dict(stage="independent_complete_tensor_reconstruction",rows=len(targets))),flush=True)
    for index,row in enumerate(targets):
        snapshot=snapshots[row["candidate_request_id"]]
        expected=original_encoding(row,snapshot)
        for name,value in expected.items():
            if not np.array_equal(arrays[name][index],value) or arrays[name][index].tobytes()!=value.tobytes():
                raise ValueError("numeric_verifier_tensor_difference_"+name)
        if records[index]["origin"]!=original_seal(row,receipts[row["stable_id"]],snapshot,components[row["stable_id"]]):
            raise ValueError("numeric_verifier_origin_binding")
        input_hash,label_hash=row_digest(expected,MODEL_FIELDS),row_digest(expected,LABEL_FIELDS)
        if input_hash!=records[index]["input_tensor_sha256"] or label_hash!=records[index]["label_tensor_sha256"]:
            raise ValueError("numeric_verifier_independent_row_digest")
        counts[input_hash]+=1;labels[input_hash].add(label_hash);component_groups[input_hash].add(components[row["stable_id"]])
    duplicates=dict(unique_model_inputs=len(counts),duplicate_groups=sum(n>1 for n in counts.values()),
        duplicate_rows=sum(n for n in counts.values() if n>1),surplus_rows=sum(n-1 for n in counts.values()),
        conflicting_label_groups=sum(len(v)>1 for v in labels.values()),cross_component_groups=sum(len(v)>1 for v in component_groups.values()))
    if duplicates!=manifest["input_tensor_duplicates"] or duplicates!=report["input_tensor_duplicates"]:
        raise ValueError("numeric_verifier_duplicate_recount")
    result=dict(kind="consumed_numeric_verification",status="passed",rows=len(targets),arrays_verified=len(arrays),
        tensor_elements_verified=sum(a.size for a in arrays.values()),bitwise_tensor_equality=True,
        all_origin_projections_verified=True,input_tensor_duplicates=duplicates,
        cache_manifest_sha256=report["cache_manifest_sha256"],row_chain_head=manifest["row_chain_head"],
        report_sha256=sha(ROOT/"report.json"),policy_sha256=sha(POLICY),script_sha256=sha(__file__),
        source_rows_preserved=plan["population"],model_fits=0,model_inferences=0,new_native_requests=0,
        legacy_training_labels_admitted=0,final_test_used=False,gold_certified=False)
    save(ROOT/"verification.json",result)
    save("reports/issue-33-consumed-numeric-verification-v1.json",result)
    return result


if __name__=="__main__":
    print(json.dumps(verify()))
