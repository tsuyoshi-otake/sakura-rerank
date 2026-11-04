"""Authenticate historical source metadata and reserve Aozora works before text access."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from sakura_rerank.data.contracts import canonical_json_bytes, canonical_json_hash
from sakura_rerank.data.growth_corpus import history_metadata, select_aozora
from sakura_rerank.data.kwdlc_probe import write_once

ROOT = Path("data/generated/issue-33-data-growth-v1")
PLAN = Path("research/issue-33-data-growth/plan-v1.json")
PLAN_COMMIT = "0145c72"
SOURCES = (
    ("jawiki-tier-a-source-spans-verified.json", "source-spans.jsonl"),
    ("jawiki-tier-a-source-spans-expanded-verified.json", "source-spans-expanded-a.jsonl"),
    ("jawiki-tier-a-source-spans-expanded-v2-verified.json", "source-spans-expanded-v2-a.jsonl"),
    ("jawiki-tier-a-source-spans-expanded-v3-verified.json", "source-spans-expanded-v3-a.jsonl"),
    ("jawiki-tier-a-source-spans-expanded-v4-verified.json", "source-spans-expanded-v4-a.jsonl"),
    ("jawiki-tier-a-source-spans-v5-slot120-verified.json", "issue15-v5-slot120/source-spans-a.jsonl"),
)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare() -> dict:
    committed = subprocess.check_output(["git", "show", PLAN_COMMIT + ":" + PLAN.as_posix()], timeout=30)
    if PLAN.read_bytes() != committed:
        raise ValueError("registered_plan_changed")
    plan = json.loads(committed)
    index = ROOT / "sources/aozora-index.csv"
    if sha(index) != plan["aozora"]["index_csv_sha256"]:
        raise ValueError("aozora_metadata_changed")
    with index.open(encoding="utf-8-sig", newline="") as stream:
        selection, selection_counts = select_aozora(list(csv.DictReader(stream)))
    # Nothing below decodes historic targets, contexts, labels or candidates.
    article_ids, receipts, count = set(), [], 0
    destination = ROOT / "history-source-metadata.jsonl.gz"
    if destination.exists() or (ROOT / "source-preparation.json").exists():
        raise ValueError("source_preparation_already_published")
    temporary = ROOT / "history-source-metadata.partial.gz"
    with temporary.open("xb") as file, gzip.GzipFile(fileobj=file, mode="wb", filename="", mtime=0) as output:
        for manifest_name, filename in SOURCES:
            manifest_path = Path("manifests") / manifest_name
            original = subprocess.check_output(["git", "show", PLAN_COMMIT + ":" + manifest_path.as_posix()], timeout=30)
            if json.loads(manifest_path.read_bytes()) != json.loads(original):
                raise ValueError("historical_manifest_changed")
            manifest = json.loads(original)
            source = Path("data/generated") / filename
            digest, rows = hashlib.sha256(), 0
            with source.open("rb") as stream:
                while line := stream.readline(256 * 1024 + 1):
                    if rows >= 1_000_000:
                        raise ValueError("historical_source_row_bound")
                    digest.update(line)
                    item = history_metadata(line)
                    article_ids.add(item["source"]["article_id"])
                    item["stable_id"] = "history-" + canonical_json_hash(item)
                    output.write(canonical_json_bytes(item) + b"\n")
                    rows += 1
            if digest.hexdigest() != manifest["content_sha256"] or rows != manifest["record_count"]:
                raise ValueError("historical_source_file_changed")
            receipts.append(dict(path=source.as_posix(), rows=rows, sha256=digest.hexdigest(),
                                 committed_manifest_sha256=hashlib.sha256(original).hexdigest(),
                                 checkout_manifest_sha256=sha(manifest_path)))
            count += rows
    temporary.rename(destination)
    write_once(ROOT / "historical-articles.json", canonical_json_bytes(sorted(article_ids)) + b"\n")
    write_once(ROOT / "aozora-selection.json", canonical_json_bytes(selection) + b"\n")
    report = dict(kind="growth_source_reservations", schema_version=1, status="complete",
        plan_commit=subprocess.check_output(["git", "rev-parse", PLAN_COMMIT], text=True, timeout=30).strip(),
        plan_sha256=hashlib.sha256(committed).hexdigest(), history_sources=receipts,
        historical_rows=count, historical_articles=len(article_ids),
        history_metadata_sha256=sha(destination), article_ids_sha256=sha(ROOT / "historical-articles.json"),
        aozora_selection_sha256=sha(ROOT / "aozora-selection.json"), aozora=selection_counts,
        historical_text_labels_candidates_decoded=False, aozora_work_text_accessed=False,
        raw_text_in_report=False, new_final_test_used=False, gold_certified=False)
    write_once(ROOT / "source-preparation.json", canonical_json_bytes(report) + b"\n")
    return report


if __name__ == "__main__":
    result = prepare()
    print(canonical_json_bytes(result).decode("utf-8"))
