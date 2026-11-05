"""Post-observation diagnostic: index evidence for measured missing components.

Index absence is not a wrong label. This uses the index of the same dictionary
image and never edits annotations, rebuilds candidates, or invents readings.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.input_boundary import request_id
from sakura_rerank.data.pilot_doubt_evidence import dictionary_evidence
from common import ROOT, identity, load_old_snapshots, sha
from publish import R2, publish, run as verify_measurement

INDEX_MANIFEST = Path("manifests/system-dictionary-index-verified.json")
INDEX_MANIFEST_SHA = "f9c4b5b4c3e0ce518dc86b61092d81debfe14be802ef94e4b42ef0d9f9faf22d"
INDEX = Path("data/generated/system-dictionary-index.jsonl")


def run():
    report = verify_measurement()
    converter_identity = identity()
    manifest = json.loads(INDEX_MANIFEST.read_bytes())
    if sha(INDEX_MANIFEST) != INDEX_MANIFEST_SHA or manifest["dictionary_sha256"] != converter_identity["dictionary_sha256"]:
        raise ValueError("dictionary_index_identity_differs")
    records = load_old_snapshots(converter_identity)
    execution = json.loads((R2/"execution.json").read_bytes())
    for attempt in execution["attempts"]:
        if attempt["status"] != "complete":
            continue
        directory = R2/"candidates"/f"request-{attempt['index']:04d}"
        receipt = json.loads((directory/"execution.json").read_bytes())
        # Full native validation was just performed by verify_measurement;
        # retain that byte identity when loading the one authenticated record.
        if sha(directory/"execution.json") != attempt["execution_sha256"] or sha(directory/"output.jsonl") != receipt["output_sha256"]:
            raise ValueError("verified_snapshot_replaced")
        row = json.loads((directory/"output.jsonl").read_bytes())
        records[request_id(row["reading"])] = row
    targets = [json.loads(line) for line in (ROOT/"targets.jsonl").read_bytes().splitlines()]
    missing, slots = {}, []
    for row in targets:
        view = row["views"]["morpheme_diagnostic"]
        keys = []
        if view["status"] != "ready":
            continue
        for part in view["parts"]:
            if part["kind"] != "convert":
                continue
            snapshot = records.get(part["request_id"])
            if snapshot is None:
                raise ValueError("unmeasured_component_cannot_be_classified")
            candidates = snapshot["candidate_snapshots"]["training_top32"]["candidates"]
            if not any(c["surface"] == part["target"] for c in candidates):
                key = canonical_json_hash([part["reading"], part["target"]])
                missing[key] = part
                keys.append(key)
        whole = row["views"]["whole"]["parts"][0]
        snapshot = records.get(whole["request_id"])
        whole_missing = snapshot is not None and not any(c["surface"] == whole["target"] for c in snapshot["candidate_snapshots"]["training_top32"]["candidates"])
        slots.append(dict(stable_id=row["stable_id"], missing_component_keys=keys,
                          whole_top32_missing=whole_missing, whole_measured=snapshot is not None,
                          original_ready=row["original_status"] == "ready_for_forward_check",
                          whole_search_status=snapshot["candidate_snapshots"]["training_top32"]["exporter_run"]["result_status"] if snapshot else None))
    queue = {key: dict(left_context="", source_gold_surface=part["target"]) for key, part in missing.items()}
    found = dictionary_evidence(queue, sorted(queue), INDEX, manifest) if queue else {}
    categories, per_component = Counter(), {}
    for key, part in missing.items():
        readings = found[key].get(part["target"])
        kind = ("surface_absent_from_same_dictionary_index" if readings is None else
                "surface_present_annotated_reading_absent" if part["reading"] not in readings else
                "exact_surface_reading_indexed_but_not_top32")
        per_component[key] = kind
        categories[kind] += 1
    populations = defaultdict(Counter)
    for row in slots:
        groups = ["all_executable"]
        if row["whole_top32_missing"]:
            groups.append("whole_top32_missing")
            if row["original_ready"]:
                groups.append("original_43_whole_top32_missing")
        for population in groups:
            c = populations[population]
            c["slots"] += 1
            c["slots_with_missing_component"] += bool(row["missing_component_keys"])
            for kind in set(per_component[key] for key in row["missing_component_keys"]):
                c["slots/"+kind] += 1
            for key in row["missing_component_keys"]:
                c["occurrences/"+per_component[key]] += 1
            if row["whole_top32_missing"] and not row["missing_component_keys"]:
                c["all_components_present/"+row["whole_search_status"]] += 1
    detail = dict(slots=slots, component_categories=per_component)
    publish(ROOT/"component-audit-details.json", detail)
    result = dict(kind="input_boundary_component_index_diagnostic", post_observation_diagnostic=True,
                  source_report_sha256=sha(ROOT/"report.json"), dictionary_manifest_sha256=INDEX_MANIFEST_SHA,
                  dictionary_content_sha256=manifest["content_sha256"], dictionary_binary_sha256=manifest["dictionary_sha256"],
                  unique_missing_component_pairs=len(missing), unique_pair_categories=dict(categories),
                  populations={key:dict(value) for key,value in populations.items()},
                  private_details_sha256=sha(ROOT/"component-audit-details.json"), script_sha256=sha(__file__),
                  safety_threshold=report["safety_threshold"], labels_changed=0,
                  caveat="Categories are observed support discrepancies, not certified causes or label errors. Per-slot categories overlap. Indexed-pair absence from Top32 does not alone distinguish cost, quality filtering, segmentation or search budget.")
    publish(ROOT/"component-audit.json", result)
    publish(Path("reports/issue-31-input-boundary-components-v1.json"), result)
    return result


if __name__ == "__main__":
    result = run()
    print(json.dumps({key:result[key] for key in ("unique_missing_component_pairs", "unique_pair_categories", "populations")}))
