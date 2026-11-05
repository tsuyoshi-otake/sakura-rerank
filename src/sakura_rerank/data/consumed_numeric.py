"""Minimal source-reconstruction projections and bounded numeric verification.

This module does not authorize fitting, independent evaluation or Gold labels.
The caller authenticates original row/receipt/snapshot bytes and the policy.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from .consumed_source import unit_key
from .contrast_capacity import candidate_evidence
from .contracts import canonical_json_bytes, canonical_json_hash, text_sha256

PURPOSE = "source_annotation_numeric_verification"
MODEL_FIELDS = ("context_ids", "context_lengths", "reading_ids", "reading_lengths",
                "candidate_ids", "candidate_lengths", "features", "candidate_mask")
LABEL_FIELDS = ("gold", "correct_mask", "baseline_equivalent")
SHAPES = dict(context_ids=(64,), context_lengths=(), reading_ids=(32,), reading_lengths=(),
              candidate_ids=(6,32), candidate_lengths=(6,), features=(6,7), candidate_mask=(6,),
              gold=(), correct_mask=(6,), baseline_equivalent=(6,))
MAX_BYTES = 512 * 1024 * 1024


def project(row, consumption, snapshot, component, policy_sha256):
    """Provenance in, explicitly limited encoder input and hash-only seal out."""
    if (not re.fullmatch(r"[0-9a-f]{64}", policy_sha256) or not isinstance(component,str) or not component
            or row["population"] != "train" or row["corpus"] != "aozora"
            or row["training_eligible"] is not False or row["independent_gold_eligible"] is not False
            or row["label_kind"] != "source_annotated_weak_supervision"
            or row["context_origin"] != "synthetic_source_prefix_not_observed_session"
            or not 8 <= len(row["left_context"]) <= 64 or not 2 <= len(row["reading"]) <= 32
            or not 1 <= len(row["target"]) <= 32):
        raise ValueError("consumed_numeric_source_contract")
    expected = dict(stable_id=row["stable_id"], unit_id=unit_key(row["source"]), consumer="source_verification",
        source_revision=row["source_revision"], source_line_sha256=row["source_line_sha256"], paragraph_index=row["paragraph_index"],
        context_start=max(0,row["paragraph_start"]-64),target_start=row["paragraph_start"],target_end=row["paragraph_end"],
        context_sha256=text_sha256(row["left_context"]),target_sha256=text_sha256(row["target"]),reading_sha256=text_sha256(row["reading"]),
        input_and_label_sha256=canonical_json_hash([row["left_context"],row["reading"],row["target"]]),
        training_eligible=False,independent_gold_eligible=False)
    if consumption != expected:
        raise ValueError("consumed_numeric_origin_receipt_differs")
    request = "growth-reading-"+canonical_json_hash(row["reading"])
    if (snapshot is None or row["candidate_request_id"] != request or snapshot["stable_id"] != request
            or snapshot["reading"] != row["reading"] or not candidate_evidence(row["target"],snapshot)["eligible"]):
        raise ValueError("consumed_numeric_candidate_contract")
    encoder_row = {key:row[key] for key in ("stable_id","corpus","left_context","reading","target","candidate_request_id")}
    encoder_row["component_id"] = component
    candidates = [dict(surface=c["surface"],local_cost=c["local_cost"],source_category=c["source_category"],
                       segments=[dict(source_category=s["source_category"]) for s in c["segments"]])
                  for c in snapshot["candidate_snapshots"]["training_top32"]["candidates"]]
    encoder_snapshot = dict(candidate_snapshots=dict(training_top32=dict(candidates=candidates),
                                                      production_top6=dict(candidates=candidates[:6])))
    seal = dict(stable_id=row["stable_id"],component_id=component,policy_sha256=policy_sha256,
        original_row_sha256=canonical_json_hash(row),consumption_sha256=canonical_json_hash(consumption),
        snapshot_sha256=canonical_json_hash(snapshot),projection_sha256=canonical_json_hash([encoder_row,encoder_snapshot]),
        label_task="original_annotation_reconstruction",ime_quality="unresolved",training_eligible=False,independent_gold_eligible=False)
    return encoder_row, encoder_snapshot, seal


def dtype_for(name):
    return "|b1" if name in ("candidate_mask","correct_mask","baseline_equivalent") else "<f4" if name=="features" else "<i8"


def schema(rows):
    if type(rows) is not int or not 1 <= rows <= 100000:
        raise ValueError("consumed_numeric_row_bound")
    return {name:dict(shape=[rows,*shape],dtype=dtype_for(name)) for name,shape in SHAPES.items()}


def validate_arrays(arrays, rows):
    import numpy as np
    expected = schema(rows)
    if set(arrays) != set(expected):
        raise ValueError("consumed_numeric_array_names")
    for name, spec in expected.items():
        array = arrays[name]
        if list(array.shape)!=spec["shape"] or array.dtype.str!=spec["dtype"] or not array.flags.c_contiguous:
            raise ValueError("consumed_numeric_array_schema")
    if not np.isfinite(arrays["features"]).all():
        raise ValueError("consumed_numeric_nonfinite_features")
    mask = arrays["candidate_mask"]
    counts = mask.sum(axis=1)
    if (np.any(counts<2) or np.any(counts>6) or not np.array_equal(mask,np.arange(6)[None,:]<counts[:,None])
            or np.any(arrays["gold"]<0) or np.any(arrays["gold"]>=counts)
            or not np.array_equal(arrays["correct_mask"],np.arange(6)[None,:]==arrays["gold"][:,None])
            or not arrays["baseline_equivalent"][:,0].all() or np.any(arrays["baseline_equivalent"] & ~mask)):
        raise ValueError("consumed_numeric_mask_or_label")
    for prefix, lower, upper in (("context",8,64),("reading",2,32),("candidate",1,32)):
        ids, lengths = arrays[prefix+"_ids"], arrays[prefix+"_lengths"]
        active = mask if prefix=="candidate" else np.ones(rows,dtype=np.bool_)
        if np.any(lengths[active]<lower) or np.any(lengths[active]>upper) or np.any(lengths[~active]!=0):
            raise ValueError("consumed_numeric_length_bound")
        positions = np.arange(upper) < lengths[...,None]
        if np.any(ids[positions]<1) or np.any(ids[positions]>=13312) or np.any(ids[~positions]!=0):
            raise ValueError("consumed_numeric_token_or_padding")
    if np.any(arrays["features"][~mask]!=0):
        raise ValueError("consumed_numeric_feature_padding")


def tensor_hash(arrays, index, names):
    import numpy as np
    digest = hashlib.sha256()
    for name in names:
        value = np.asarray(arrays[name][index])
        digest.update(canonical_json_bytes([name,value.dtype.str,list(value.shape)]))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def chain_entry(index, previous, seal, arrays):
    record = dict(index=index,previous_sha256=previous,origin=seal,
        input_tensor_sha256=tensor_hash(arrays,index,MODEL_FIELDS),
        label_tensor_sha256=tensor_hash(arrays,index,LABEL_FIELDS))
    return dict(record,record_sha256=canonical_json_hash(record))


def verify_chain(raw, rows, expected_head):
    if len(raw)>MAX_BYTES:
        raise ValueError("consumed_numeric_ledger_size")
    lines = raw.splitlines()
    if len(lines)!=rows or not raw.endswith(b"\n"):
        raise ValueError("consumed_numeric_ledger_count")
    previous, records, seen = "0"*64, [], set()
    for index,line in enumerate(lines):
        if len(line)>16384:
            raise ValueError("consumed_numeric_ledger_line_bound")
        record = json.loads(line)
        if (set(record)!={"index","previous_sha256","origin","input_tensor_sha256","label_tensor_sha256","record_sha256"}
                or record["index"]!=index or record["previous_sha256"]!=previous
                or canonical_json_hash({k:v for k,v in record.items() if k!="record_sha256"})!=record["record_sha256"]
                or record["origin"]["stable_id"] in seen):
            raise ValueError("consumed_numeric_ledger_chain")
        previous=record["record_sha256"]
        seen.add(record["origin"]["stable_id"])
        records.append(record)
    if previous!=expected_head:
        raise ValueError("consumed_numeric_ledger_head")
    return records


def _bounded_bytes(path, limit):
    with path.open("rb") as stream:
        raw=stream.read(limit+1)
    if len(raw)>limit:
        raise ValueError("consumed_numeric_artifact_size_bound")
    return raw


def load_prepared_cache(root, expected_manifest_sha256, *, purpose):
    """Verified byte loading for numeric verification only; no fit capability."""
    import numpy as np
    root = Path(root)
    if purpose != PURPOSE:
        raise ValueError("consumed_numeric_purpose_not_authorized")
    raw = _bounded_bytes(root/"manifest.json",65536)
    if hashlib.sha256(raw).hexdigest()!=expected_manifest_sha256:
        raise ValueError("consumed_numeric_manifest_binding")
    manifest=json.loads(raw)
    if (manifest["kind"]!="source_reconstruction_numeric_cache" or manifest["status"]!="prepared_unverified"
            or manifest["training_eligible"] is not False or manifest["independent_gold_eligible"] is not False
            or manifest["allowed_consumer"]!=PURPOSE or manifest["array_schema"]!=schema(manifest["rows"])):
        raise ValueError("consumed_numeric_manifest_scope")
    artifacts={}
    for name,expected in manifest["artifacts"].items():
        if name not in ("arrays.npz","row-receipts.jsonl"):
            raise ValueError("consumed_numeric_artifact_name")
        artifacts[name]=_bounded_bytes(root/name,MAX_BYTES)
        if hashlib.sha256(artifacts[name]).hexdigest()!=expected:
            raise ValueError("consumed_numeric_artifact_changed")
    if set(manifest["artifacts"])!={"arrays.npz","row-receipts.jsonl"}:
        raise ValueError("consumed_numeric_artifact_set")
    with zipfile.ZipFile(io.BytesIO(artifacts["arrays.npz"])) as archive:
        infos=archive.infolist()
        if (len(infos)!=len(SHAPES) or {i.filename for i in infos}!={name+".npy" for name in SHAPES}
                or sum(i.file_size for i in infos)>MAX_BYTES):
            raise ValueError("consumed_numeric_archive_bound")
        for info in infos:
            with archive.open(info) as stream:
                version=np.lib.format.read_magic(stream)
                if version not in ((1,0),(2,0)):
                    raise ValueError("consumed_numeric_array_version")
                reader=np.lib.format.read_array_header_1_0 if version==(1,0) else np.lib.format.read_array_header_2_0
                shape,fortran,dtype=reader(stream)
                spec=manifest["array_schema"][info.filename[:-4]]
                if list(shape)!=spec["shape"] or dtype.str!=spec["dtype"] or dtype.hasobject or fortran:
                    raise ValueError("consumed_numeric_archive_schema")
    with np.load(io.BytesIO(artifacts["arrays.npz"]),allow_pickle=False) as archive:
        arrays={name:archive[name] for name in SHAPES}
    validate_arrays(arrays,manifest["rows"])
    records=verify_chain(artifacts["row-receipts.jsonl"],manifest["rows"],manifest["row_chain_head"])
    for index,record in enumerate(records):
        if (record["origin"]["policy_sha256"]!=manifest["policy_sha256"]
                or record["origin"]["label_task"]!="original_annotation_reconstruction" or record["origin"]["ime_quality"]!="unresolved"
                or record["origin"]["training_eligible"] is not False or record["origin"]["independent_gold_eligible"] is not False
                or tensor_hash(arrays,index,MODEL_FIELDS)!=record["input_tensor_sha256"]
                or tensor_hash(arrays,index,LABEL_FIELDS)!=record["label_tensor_sha256"]):
            raise ValueError("consumed_numeric_row_binding")
    for array in arrays.values():
        array.flags.writeable=False
    return arrays,records,manifest
