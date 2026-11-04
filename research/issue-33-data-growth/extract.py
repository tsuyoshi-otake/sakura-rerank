"""Bounded extraction/acquisition for committed Issue-33 source reservations."""
from __future__ import annotations

import argparse
import bz2
from collections import Counter
import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.growth_corpus import GrowthExtractor, aozora_paragraphs, partition, wiki_page_selected
from sakura_rerank.data.jawiki_preprocess import clean_wikitext, load_dictionary_inputs, MAX_PAGE_TEXT_CHARS
from sakura_rerank.data.kwdlc_probe import write_once
from prepare_sources import ROOT, sha

BINDING = Path("manifests/data-growth-source-reservations-v1.json")
DICTIONARY_SHA = "4a3b04ea02ec601a1b23eedd6eb4c19582cd36c39f098c2d0ad61b259fd6c072"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class DownloadBudgetExceeded(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_bytes())


def authenticate(commit):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("full_reservation_commit_required")
    raw = subprocess.check_output(["git", "show", commit + ":" + BINDING.as_posix()], timeout=30)
    if raw != BINDING.read_bytes() or raw != (ROOT / "source-preparation.json").read_bytes():
        raise ValueError("source_reservation_changed")
    binding = json.loads(raw)
    for name, key in (("aozora-selection.json", "aozora_selection_sha256"),
                      ("historical-articles.json", "article_ids_sha256"),
                      ("history-source-metadata.jsonl.gz", "history_metadata_sha256")):
        if sha(ROOT / name) != binding[key]:
            raise ValueError("bound_source_metadata_changed")
    plan = Path("research/issue-33-data-growth/plan-v1.json")
    if sha(plan) != binding["plan_sha256"]:
        raise ValueError("registered_plan_changed")
    return binding, read(plan)


def extractor():
    path = Path("data/generated/system-dictionary-index.jsonl")
    if sha(path) != DICTIONARY_SHA:
        raise ValueError("dictionary_index_changed")
    records, _ = load_dictionary_inputs(path, Path("manifests/system-dictionary-index-verified.json"))
    return GrowthExtractor(records)


def publish_targets(directory, rows, receipt):
    temporary = directory / "targets.partial.jsonl"
    digest, count, size = hashlib.sha256(), 0, 0
    with temporary.open("xb") as stream:
        for row in rows:
            raw = canonical_json_bytes(row) + b"\n"
            size += len(raw)
            if size > 1024**3 or count >= 200_000:
                raise ValueError("source_target_output_bound")
            stream.write(raw)
            digest.update(raw)
            count += 1
    temporary.rename(directory / "targets.jsonl")
    receipt.update(target_count=count, target_bytes=size, targets_sha256=digest.hexdigest())


def wiki(directory, plan, receipt):
    dump = Path(plan["jawiki"]["path"])
    if sha(dump) != plan["jawiki"]["sha256"]:
        raise ValueError("pinned_wikipedia_dump_changed")
    excluded = set(read(ROOT / "historical-articles.json"))
    extract = extractor()
    counts = Counter()
    receipt["counts"] = counts
    def rows():
        with bz2.open(dump, "rb") as stream:
            iterator = ET.iterparse(stream, events=("start", "end"))
            _, root = next(iterator)
            for event, element in iterator:
                if event != "end" or element.tag.rsplit("}", 1)[-1] != "page":
                    continue
                counts["pages_scanned"] += 1
                fields = {child.tag.rsplit("}", 1)[-1]: child for child in element}
                page_id = fields.get("id").text if fields.get("id") is not None else None
                if (fields.get("ns") is None or fields["ns"].text != "0" or "redirect" in fields
                        or page_id is None or not page_id.isdigit() or "revision" not in fields):
                    counts["non_target_page"] += 1
                elif "jawiki-page-" + page_id in excluded:
                    counts["historical_article_excluded"] += 1
                elif not wiki_page_selected(page_id, plan["jawiki"].get("page_sample_slot", 0)):
                    counts["page_not_sampled"] += 1
                else:
                    rev = {child.tag.rsplit("}", 1)[-1]: child for child in fields["revision"]}
                    text = rev["text"].text or "" if "text" in rev else ""
                    revision = rev["id"].text if "id" in rev else None
                    if not revision or not revision.isdigit() or len(text) > MAX_PAGE_TEXT_CHARS:
                        counts["invalid_or_oversized_page"] += 1
                    else:
                        paragraphs, cleaning = clean_wikitext(text)
                        counts.update(cleaning)
                        population = partition("jawiki", page_id)
                        counts["pages_" + population] += 1
                        yield from extract.document(paragraphs, "jawiki", page_id, revision,
                            population, plan["jawiki"]["max_targets_per_page"], counts)
                if counts["pages_scanned"] % 100_000 == 0:
                    print(json.dumps({"stage":"wiki", "pages_scanned":counts["pages_scanned"],
                                      "targets":counts["targets_retained"]}), flush=True)
                element.clear()
                root.clear()
    publish_targets(directory, rows(), receipt)


def download_aozora(directory, plan, receipt):
    limits = plan["aozora"]
    selection = read(ROOT / "aozora-selection.json")
    counts, total, previous = Counter(), 0, 0.0
    receipt["counts"] = counts
    opener = urllib.request.build_opener(NoRedirect)
    for index, work in enumerate(selection):
        completed = directory / (work["work_id"] + ".json")
        time.sleep(max(0, 1 - (time.monotonic() - previous)))
        previous = time.monotonic()
        result = dict(work, status="failed", attempted_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        # A crash after this reservation never permits a second request for this work.
        write_once(directory / (work["work_id"] + ".attempt.json"), canonical_json_bytes(result) + b"\n")
        try:
            request = urllib.request.Request(work["url"], headers={"User-Agent":"sakura-rerank-research/issue-33"})
            with opener.open(request, timeout=30) as response:
                if response.geturl() != work["url"]:
                    raise ValueError("source_redirect_not_registered")
                remaining = limits["max_total_download_bytes"] - total
                if remaining <= 0:
                    raise DownloadBudgetExceeded("total_download_byte_bound")
                raw = response.read(min(limits["max_zip_bytes_per_work"] + 1, remaining))
                total += len(raw)
                receipt["downloaded_bytes"] = total
                if total >= limits["max_total_download_bytes"]:
                    raise DownloadBudgetExceeded("total_download_byte_bound")
                if len(raw) > limits["max_zip_bytes_per_work"]:
                    raise ValueError("work_download_byte_bound")
                result["last_modified"] = response.headers.get("Last-Modified")
            # Inspect size/path without unpacking arbitrary filesystem entries.
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if (len(entries) != 1 or entries[0].is_dir() or not entries[0].filename.endswith(".txt")
                        or entries[0].file_size > limits["max_uncompressed_bytes_per_work"]):
                    raise ValueError("unsupported_work_archive")
                archive.read(entries[0])  # Verify CRC while still below the decompression bound.
            write_once(directory / (work["work_id"] + ".zip"), raw)
            result.update(status="downloaded", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        except urllib.error.HTTPError as error:
            result.update(error_type="HTTPError", http_status=error.code)
            if error.code == 429:
                result["retry_after"] = error.headers.get("Retry-After")
        except (ValueError, OSError, zipfile.BadZipFile) as error:
            result["error_type"] = type(error).__name__
        write_once(completed, canonical_json_bytes(result) + b"\n")
        counts[result["status"]] += 1
        if index % 10 == 0:
            print(json.dumps({"stage":"aozora_download", "completed":sum(counts.values()),
                              "downloaded":counts["downloaded"], "failed":counts["failed"]}), flush=True)
        if result.get("http_status") == 429:
            raise ValueError("rate_limit_stops_acquisition_no_immediate_retry")
        if result.get("error_type") == "DownloadBudgetExceeded":
            raise DownloadBudgetExceeded("total_download_byte_bound")
    receipt.update(selected_works=len(selection), downloaded_bytes=total)


def extract_aozora(directory, plan, receipt):
    selected = read(ROOT / "aozora-selection.json")
    downloads = ROOT / "aozora-download"
    if read(downloads / "execution.json")["status"] != "complete":
        raise ValueError("complete_acquisition_required")
    extract, counts = extractor(), Counter()
    receipt["counts"] = counts
    def rows():
        for work in selected:
            outcome = dict(work_id=work["work_id"], partition=work["partition"], status="failed_download")
            destination = directory / (work["work_id"] + ".json")
            acquisition = read(downloads / (work["work_id"] + ".json"))
            if acquisition["status"] != "downloaded":
                counts["failed_download_works"] += 1
                write_once(destination, canonical_json_bytes(outcome) + b"\n")
                continue
            path = downloads / (work["work_id"] + ".zip")
            if sha(path) != acquisition["sha256"]:
                raise ValueError("downloaded_work_changed")
            with zipfile.ZipFile(path) as archive:
                raw = archive.read(archive.infolist()[0])
            try:
                paragraphs, cleaned = aozora_paragraphs(raw)
            except (ValueError, UnicodeError) as error:
                counts["parse_failed_works"] += 1
                outcome.update(status="parse_failed", error_type=type(error).__name__,
                    reason="invalid_encoding" if isinstance(error, UnicodeError) else str(error))
                write_once(destination, canonical_json_bytes(outcome) + b"\n")
                continue
            counts.update(cleaned)
            counts["works_" + work["partition"]] += 1
            targets = extract.document(paragraphs, "aozora", work["work_id"],
                    hashlib.sha256(raw).hexdigest(), work["partition"], plan["aozora"]["max_targets_per_work"], counts)
            outcome.update(status="extracted", target_count=len(targets), cleaning=dict(cleaned))
            write_once(destination, canonical_json_bytes(outcome) + b"\n")
            for row in targets:
                row["source"]["template_cluster_id"] = "aozora-author-" + work["author_id"]
                yield row
    publish_targets(directory, rows(), receipt)


def run(mode, commit):
    binding, plan = authenticate(commit)
    directory = ROOT / mode
    directory.mkdir(exist_ok=False)
    start = time.monotonic()
    receipt = dict(kind="growth_source_execution", mode=mode, status="failed",
        source_reservation_commit=commit, plan_sha256=binding["plan_sha256"], gold_certified=False)
    try:
        {"wiki":wiki, "aozora-download":download_aozora, "aozora-extract":extract_aozora}[mode](directory, plan, receipt)
        receipt["status"] = "complete"
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic()-start, 3)
        write_once(directory / "execution.json", canonical_json_bytes(receipt) + b"\n")
    print(canonical_json_bytes(receipt).decode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("wiki","aozora-download","aozora-extract"), required=True)
    parser.add_argument("--reservation-commit", required=True)
    args = parser.parse_args()
    run(args.mode,args.reservation_commit)
