"""Artifact authentication shared by preparation, execution and saved-output audit."""
import importlib.util
import json
from pathlib import Path
import subprocess

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.context_pilot import annotation_units, extract_slots
from sakura_rerank.data.input_boundary import request_id
from sakura_rerank.data.kwdlc_probe import blob_sha1
from sakura_rerank.data.reference_probe import authenticate_identity


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot = load_script("frozen_pilot_acquisition", "research/issue-39-context-pilot/acquire.py")
native = load_script("frozen_reference_validator", "research/issue-31-quality/run_reference_probe.py")
sha = pilot.sha
ROOT = Path("data/generated/issue-31-input-boundary-v1")
PLAN = Path("research/issue-31-input-boundary/plan-v1.json")
PLAN_COMMIT = "8627f98bcfcf7ea4b025adcf85dcd38ee2ceb173"
BINDING = Path("manifests/input-boundary-v1.json")
IDENTITY = Path("manifests/reference-probe-identity-v1.json")
BINARY = Path("data/generated/issue-31-reference-exporter-v1/probe-exporter.exe")
DICTIONARY = Path("data/generated/issue-31-exporter-restoration-v1/system.dic")


def committed(path, commit):
    raw = subprocess.check_output(["git", "show", commit + ":" + Path(path).as_posix()], timeout=30)
    if raw != Path(path).read_bytes():
        raise ValueError("committed_artifact_changed")
    return raw


def jsonl(rows):
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def authenticate_population():
    plan = json.loads(committed(PLAN, PLAN_COMMIT))
    _, selection = pilot.authenticate()
    old_binding = Path("manifests/context-pilot-input-v1.json")
    committed(old_binding, plan["population_commit"])
    if sha(old_binding) != plan["population_binding_sha256"]:
        raise ValueError("old_input_binding_changed")
    bound = json.loads(old_binding.read_bytes())
    for name in ("targets", "requests"):
        if sha(pilot.ROOT / (name + ".jsonl")) != bound[name + "_sha256"]:
            raise ValueError("old_population_changed")
    if bound["targets_sha256"] != plan["population_sha256"]:
        raise ValueError("population_plan_differs")
    for path, key in (("src/sakura_rerank/data/context_pilot.py", "extractor_sha256"),
                      ("src/sakura_rerank/data/kwdlc_probe.py", "legacy_format_reader_sha256")):
        if sha(path) != bound[key]:
            raise ValueError("old_reader_changed")
    acquisition = json.loads((pilot.ROOT / "acquisition.json").read_bytes())
    if sha(pilot.ROOT / "acquisition.json") != bound["acquisition_sha256"]:
        raise ValueError("old_acquisition_changed")
    attempts = {r["index"]: r for r in acquisition["attempts"]}
    regenerated, units = [], {}
    for index, doc in enumerate(selection["documents"]):
        path = pilot.ROOT / "source" / (doc["document_id"] + ".knp")
        raw = path.read_bytes()
        if (attempts[index]["status"] != "received" or sha(path) != attempts[index]["sha256"]
                or len(raw) != doc["bytes"] or blob_sha1(raw) != doc["git_blob_sha1"]):
            raise ValueError("old_source_changed")
        units[doc["document_id"]] = annotation_units(doc["document_id"], raw)
        for row in extract_slots(doc["document_id"], raw):
            if row["status"] == "ready_for_forward_check":
                row["request_id"] = "pilot-reading-" + canonical_json_hash(row["reading"])
            regenerated.append(row)
    if jsonl(regenerated) != (pilot.ROOT / "targets.jsonl").read_bytes() or len(regenerated) != 1000:
        raise ValueError("old_population_replay_differs")
    return plan, regenerated, units


def identity():
    plan = json.loads(committed(PLAN, PLAN_COMMIT))
    return authenticate_identity(IDENTITY, plan["converter_identity_sha256"], BINARY, DICTIONARY)


def load_old_snapshots(authenticated_identity):
    plan = json.loads(PLAN.read_bytes())
    report = json.loads(committed("reports/issue-39-context-pilot-v1.json", plan["population_commit"]))
    if sha(pilot.ROOT / "forward-execution.json") != report["forward_receipt_sha256"]:
        raise ValueError("old_forward_receipt_changed")
    execution = json.loads((pilot.ROOT / "forward-execution.json").read_bytes())
    if execution["status"] != "complete":
        raise ValueError("old_forward_incomplete")
    snapshots = {}
    for batch in execution["batches"]:
        directory = pilot.ROOT / "candidates" / f"batch-{batch['index']:03d}"
        if sha(directory / "execution.json") != batch["execution_sha256"]:
            raise ValueError("old_batch_receipt_changed")
        receipt = json.loads((directory / "execution.json").read_bytes())
        if receipt["status"] != "complete" or sha(directory / "output.jsonl") != receipt["output_sha256"]:
            raise ValueError("old_batch_output_changed")
        for row in native.validate_result(directory, (directory / "input.jsonl").read_bytes(), authenticated_identity):
            snapshots[request_id(row["reading"])] = row
    if len(snapshots) != 722:
        raise ValueError("old_snapshot_population_differs")
    return snapshots


def authenticate_input(commit):
    bound = json.loads(committed(BINDING, commit))
    if bound["plan_sha256"] != sha(PLAN) or bound["plan_commit"] != PLAN_COMMIT:
        raise ValueError("input_plan_binding_differs")
    if BINDING.read_bytes() != (ROOT / "input-binding.json").read_bytes():
        raise ValueError("local_input_binding_differs")
    for name in ("targets", "requests", "new-requests"):
        if sha(ROOT / (name + ".jsonl")) != bound["artifacts"][name]:
            raise ValueError("bound_input_changed")
    for path, expected in bound["code"].items():
        if sha(path) != expected:
            raise ValueError("bound_implementation_changed")
    return bound
