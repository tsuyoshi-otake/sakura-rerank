"""Pinned input contracts and write-once artifacts for annotation-first research."""
import gzip
import json
from pathlib import Path
import sys
import zipfile

from sakura_rerank.data.contracts import canonical_json_hash

sys.path.insert(0, "research/issue-48-contrast-data")
try:
    from audit_capacity import boundary, read_json, rows, save, sha, LANGUAGE_ROOT, TRAIN_ROOT
finally:
    sys.path.pop(0)
sys.path.insert(0, "research/issue-41-language-pretraining")
try:
    import prepare_language as old_language
finally:
    sys.path.pop(0)

ROOT = Path("data/generated/issue-49-annotation-first-v1")
PLAN = Path("research/issue-49-annotation-first/plan-v1.json")
PLAN_COMMIT = "04fe8fc1beb7b728b02706a66c27436457a1314e"
SOURCE_ROOT = Path("data/generated/issue-33-data-growth-v1")
SOURCE_RECEIPTS = Path("data/generated/issue-48-contrast-data-v1/ruby-v1/source-receipts.json")


def compressed_rows(path):
    with gzip.open(path, "rb") as stream:
        for line in stream:
            if len(line) > 256 * 1024:
                raise ValueError("annotation_jsonl_line_bound")
            yield json.loads(line)


def authenticate():
    plan = json.loads(boundary.committed(PLAN, PLAN_COMMIT))
    for path, expected in plan["sources"].items():
        if sha(path) != expected:
            raise ValueError("annotation_bound_input_changed")
    receipts = read_json(SOURCE_RECEIPTS)
    if len(receipts) != plan["bounds"]["works"] or len({r["work_id"] for r in receipts}) != len(receipts):
        raise ValueError("annotation_work_reservation_differs")
    selection = {r["work_id"]: r for r in read_json(SOURCE_ROOT / "aozora-selection.json")}
    if any(selection[r["work_id"]]["partition"] != "train" for r in receipts):
        raise ValueError("annotation_evaluation_source_forbidden")
    return plan, receipts, selection


def read_work(receipt, selection):
    work_id = receipt["work_id"]
    metadata_path = SOURCE_ROOT / "aozora-download" / (work_id + ".json")
    if sha(metadata_path) != receipt["acquisition_receipt_sha256"]:
        raise ValueError("annotation_download_receipt_changed")
    download = read_json(metadata_path)
    if (download["status"] != "downloaded" or selection["partition"] != "train"
            or any(download[k] != value for k, value in selection.items())):
        raise ValueError("annotation_reserved_metadata_differs")
    archive_path = metadata_path.with_suffix(".zip")
    if sha(archive_path) != receipt["archive_sha256"]:
        raise ValueError("annotation_source_archive_changed")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].is_dir() or not 0 < entries[0].file_size <= 32 * 1024 * 1024:
            raise ValueError("annotation_archive_bound")
        raw = archive.read(entries[0])
    return raw  # extract_work rechecks the exact decoded revision.


def history_and_original_train():
    """Same authenticated history as #41/#48, plus old train input bridges."""
    old_language.bound_plan(old_language.PLAN_COMMIT)
    prep = read_json("manifests/language-pretraining-data-v1.json")
    cohort = read_json("manifests/language-research-cohort-v1.json")
    if sha(LANGUAGE_ROOT / "preparation.json") != cohort["preparation_sha256"]:
        raise ValueError("annotation_latest_history_preparation_changed")
    for name, expected in read_json(LANGUAGE_ROOT / "preparation.json")["artifacts"].items():
        if sha(LANGUAGE_ROOT / (name + ".jsonl")) != expected:
            raise ValueError("annotation_latest_history_changed")
    historical, proof = old_language.source_history()
    approved = set()
    for part in ("issue-33-data-growth-v1/wiki", "issue-33-data-growth-v1/aozora-extract", "issue-33-data-growth-v2/wiki-extra"):
        for row in rows(Path("data/generated") / part / "targets.jsonl"):
            if row["population"] == "train":
                approved.add(row["stable_id"])
    historical = [r for r in historical if r["stable_id"] not in approved]
    historical.extend(dict(r, population="historical") for r in rows(LANGUAGE_ROOT / "source-coverage.jsonl"))
    historical.extend(dict(stable_id="language-eval-history-" + r["stable_id"], population="historical", source=r["source"],
        input_hash=canonical_json_hash([r["left_context"], r["reading"]])) for r in rows(LANGUAGE_ROOT / "pool.jsonl"))
    previous = prep["source_isolation"]
    if len(historical) != previous["historical_records"] or proof != previous["history"] or len(approved) != previous["approved_growth_train_ids"]:
        raise ValueError("annotation_historical_population_differs")
    source_path = TRAIN_ROOT / "isolation/selected.jsonl"
    if sha(source_path) != prep["source_sha256"]:
        raise ValueError("annotation_original_training_source_changed")
    old_train = []
    with source_path.open("rb") as stream:
        for line in stream:
            if b'"population":"train"' not in line:
                continue
            row = json.loads(line)
            if row["population"] != "train" or row["stable_id"] not in approved:
                raise ValueError("annotation_original_train_marker_differs")
            old_train.append(dict(stable_id=row["stable_id"], population="train", source=row["source"],
                input_hash=canonical_json_hash([row["left_context"], row["reading"]])))
    if len(old_train) != previous["original_train_fragments"]:
        raise ValueError("annotation_original_train_count_differs")
    return historical, old_train, dict(historical_records=len(historical), original_train_rows=len(old_train), history=proof)
