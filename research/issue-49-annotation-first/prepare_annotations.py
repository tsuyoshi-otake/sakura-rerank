"""Deterministic full-base extraction and source-complete isolation, no fitting."""
from collections import Counter
from contextlib import ExitStack
import gzip
import hashlib
import json
import subprocess
import time

from sakura_rerank.data.annotation_first import extract_work
from sakura_rerank.data.annotation_isolation import isolate_annotations
from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from annotation_common import (ROOT, PLAN, PLAN_COMMIT, SOURCE_RECEIPTS, authenticate, read_work,
    compressed_rows, history_and_original_train, boundary, read_json, rows, save, sha)

CODE = ("research/issue-49-annotation-first/annotation_common.py", "research/issue-49-annotation-first/prepare_annotations.py",
        "src/sakura_rerank/data/annotation_first.py", "src/sakura_rerank/data/annotation_isolation.py")


def code_binding():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=30).strip()
    for path in CODE:
        boundary.committed(path, head)
    return dict(execution_commit=head, implementation={p: sha(p) for p in CODE})


def prepare():
    binding = code_binding()
    plan, receipts, selection = authenticate()
    output = ROOT / "prepared"
    output.mkdir(exist_ok=False)
    counts, flags, cleaner_counts = Counter(), Counter(), Counter()
    totals = Counter()
    digests = {name: hashlib.sha256() for name in ("targets", "terminals", "coverage")}
    per_work = []
    with ExitStack() as stack:
        streams = {}
        for name in digests:
            file = stack.enter_context((output / (name + ".jsonl.gz")).open("xb"))
            streams[name] = stack.enter_context(gzip.GzipFile(fileobj=file, filename="", mode="wb", mtime=0))
        for index, receipt in enumerate(receipts):
            work = selection[receipt["work_id"]]
            raw = read_work(receipt, work)
            targets, terminals, coverage, summary = extract_work(raw, work["work_id"], work["author_id"], receipt["decoded_sha256"])
            counts.update(summary["terminal_counts"])
            flags.update(summary["overlapping_exclusion_flags"])
            cleaner_counts.update(summary["original_cleaner"]["original_cleaner_counts"])
            for name, records in (("targets", targets), ("terminals", terminals), ("coverage", coverage)):
                totals[name] += len(records)
                if totals[name] > (plan["bounds"]["coverage_nodes"] if name == "coverage" else plan["bounds"]["annotations"]):
                    raise ValueError("annotation_extraction_population_bound")
                for row in records:
                    line = canonical_json_bytes(row) + b"\n"
                    digests[name].update(line)
                    streams[name].write(line)
            per_work.append(dict(work_id=work["work_id"], source_revision=receipt["decoded_sha256"],
                targets=len(targets), annotations=len(terminals), source_nodes=len(coverage),
                content_sha256=canonical_json_hash([targets, terminals, coverage])))
            if index % 100 == 0:
                print(json.dumps(dict(stage="annotation_extraction", works=index + 1, total_works=len(receipts),
                                     annotation_slots=totals["terminals"], provisional_targets=totals["targets"])), flush=True)
    save(output / "work-receipts.json", per_work)
    result = dict(kind="annotation_first_preparation", status="complete", works=len(receipts), counts=dict(totals),
        terminal_counts=dict(counts), overlapping_exclusion_flags=dict(flags), frozen_cleaner_counts=dict(cleaner_counts),
        plan_commit=PLAN_COMMIT, plan_sha256=sha(PLAN), source_receipts_sha256=sha(SOURCE_RECEIPTS),
        artifacts={name: sha(output / (name + ".jsonl.gz")) for name in digests},
        content_sha256={name: digest.hexdigest() for name, digest in digests.items()},
        work_receipts_sha256=sha(output / "work-receipts.json"), **binding,
        model_fits=0, gold_certified=False, final_test_used=False)
    save(ROOT / "preparation.json", result)
    save("reports/issue-49-annotation-preparation-v1.json", result)
    return {k: result[k] for k in ("status", "works", "counts", "terminal_counts")}


def verified_preparation():
    authenticate()
    receipt = read_json(ROOT / "preparation.json")
    if receipt["status"] != "complete" or receipt["plan_sha256"] != sha(PLAN):
        raise ValueError("annotation_complete_preparation_required")
    for name, expected in receipt["artifacts"].items():
        if sha(ROOT / "prepared" / (name + ".jsonl.gz")) != expected:
            raise ValueError("annotation_prepared_artifact_changed")
    for path, expected in receipt["implementation"].items():
        if sha(path) != expected:
            raise ValueError("annotation_frozen_implementation_changed")
    return receipt


def isolate():
    binding = code_binding()
    prep = verified_preparation()
    historical, old_train, proof = history_and_original_train()
    old_ids = {r["stable_id"] for r in old_train}
    targets = list(compressed_rows(ROOT / "prepared/targets.jsonl.gz"))
    coverage = list(compressed_rows(ROOT / "prepared/coverage.jsonl.gz"))
    metadata = [dict(stable_id=r["stable_id"], population="train", source=r["source"],
                     input_hash=canonical_json_hash([r["left_context"], r["reading"]])) for r in targets]
    records = historical + old_train + coverage + metadata
    print(json.dumps(dict(stage="annotation_source_closure", historical=len(historical), old_train=len(old_train),
        source_nodes=len(coverage), annotation_targets=len(targets), total_nodes=len(records))), flush=True)
    excluded, components, audit = isolate_annotations(records)
    retained = [r for r in targets if r["stable_id"] not in excluded]
    prior_admitted = {r["stable_id"] for r in rows("data/generated/issue-41-language-pretraining-v1/lm-admitted-fragments.jsonl")}
    newly_connected = prior_admitted & set(excluded)
    output = ROOT / "isolated"
    output.mkdir(exist_ok=False)
    with (output / "retained.jsonl.gz").open("xb") as stream, gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as compressed:
        for row in retained:
            compressed.write(canonical_json_bytes(dict(row, component_id=components[row["stable_id"]])) + b"\n")
    save(output / "relations.json", dict(excluded=excluded, components=components))
    save(output / "newly-connected-old-train.json", sorted(newly_connected))
    result = dict(kind="annotation_first_source_isolation", status="retained" if retained else "no_retained_source_do_not_fit",
        annotation_slots=prep["counts"]["terminals"], provisional_targets=len(targets), retained_targets=len(retained),
        excluded_targets=len(targets) - len(retained), original_train_rows=len(old_train),
        original_train_excluded=sum(s in excluded for s in old_ids),
        previously_admitted_train_newly_connected=len(newly_connected), historical=proof, audit=audit,
        preparation_sha256=sha(ROOT / "preparation.json"), **binding,
        artifacts={name: sha(output / name) for name in ("retained.jsonl.gz", "relations.json", "newly-connected-old-train.json")},
        model_fits=0, original_data_changed=False, gold_certified=False, final_test_used=False)
    save(ROOT / "isolation.json", result)
    save("reports/issue-49-annotation-isolation-v1.json", result)
    return {k: result[k] for k in ("status", "annotation_slots", "provisional_targets", "retained_targets", "excluded_targets",
                                 "original_train_excluded", "previously_admitted_train_newly_connected", "audit")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "isolate"))
    stage = parser.parse_args().stage
    ROOT.mkdir(exist_ok=True)
    receipt_path = ROOT / (stage + "-execution.json")
    if receipt_path.exists():
        raise SystemExit("immutable_annotation_execution_exists")
    start = time.monotonic()
    try:
        summary = prepare() if stage == "prepare" else isolate()
    except Exception as error:
        receipt = dict(status="failed", stage=stage, error_type=type(error).__name__,
                       elapsed_seconds=round(time.monotonic() - start, 3))
        save(receipt_path, receipt)
        print(json.dumps(receipt))
        raise SystemExit(1) from None
    else:
        save(receipt_path, dict(status="complete", stage=stage, elapsed_seconds=round(time.monotonic() - start, 3)))
        print(json.dumps(summary))
