"""Bounded reference-exporter execution shared by new research cohorts.

Callers authenticate inputs, binary, dictionary and validators before/after use.
This boundary owns each leaf subprocess, output directory and terminal receipt.
It never retries, validates Gold, changes a converter, or prints raw input.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once

REJECTION = b"research exporter failed: converter returned an invalid candidate count\n"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute_request(directory, index, request, identity, binary, dictionary, validator, timeout):
    directory.mkdir()
    result = dict(index=index, stable_id=request["stable_id"], status="failed")
    record = None
    start = time.monotonic()
    try:
        raw = canonical_json_bytes(request)+b"\n"
        write_once(directory/"input.jsonl", raw)
        write_once(directory/"identity.json", canonical_json_bytes(identity)+b"\n")
        result["input_sha256"] = sha(directory/"input.jsonl")
        command = [str(binary.resolve()), "--input", str((directory/"input.jsonl").resolve()),
                   "--dictionary", str(dictionary.resolve()), "--output", str((directory/"output.jsonl").resolve()),
                   "--report", str((directory/"native-report.json").resolve()), "--identity-manifest",
                   str((directory/"identity.json").resolve()), "--limit", "32"]
        with (directory/"stdout.log").open("xb") as out, (directory/"stderr.log").open("xb") as err:
            process = subprocess.run(command, stdout=out, stderr=err, timeout=timeout,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        result["exit_code"] = process.returncode
        if process.returncode == 0:
            record = validator(directory, raw, identity)[0]
            result.update(status="complete", output_sha256=sha(directory/"output.jsonl"))
        elif (process.returncode == 2 and (directory/"stderr.log").read_bytes() == REJECTION
              and not (directory/"output.jsonl").exists() and not (directory/"native-report.json").exists()):
            result.update(status="candidate_count_rejected", stderr_sha256=sha(directory/"stderr.log"))
        else:
            result["error_type"] = "UnexpectedNativeExit"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["error_type"] = type(error).__name__
    finally:
        result["elapsed_seconds"] = round(time.monotonic()-start, 3)
        write_once(directory/"execution.json", canonical_json_bytes(result)+b"\n")
    return dict(index=index, status=result["status"], execution_sha256=sha(directory/"execution.json")), record


def execute_requests(requests, output, identity, binary, dictionary, validator, *, concurrency=2,
                     request_timeout=30, total_timeout=600, progress=None):
    if not 0 <= len(requests) <= 16000 or concurrency not in (1, 2) or not 0 < request_timeout <= 120 or not 0 < total_timeout <= 900:
        raise ValueError("reference_execution_bound")
    if len({r["stable_id"] for r in requests}) != len(requests):
        raise ValueError("reference_execution_duplicate_request")
    output.mkdir(exist_ok=False)
    attempts, records = [], {}
    stop_reason = None
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for offset in range(0, len(requests), concurrency):
            remaining = total_timeout-(time.monotonic()-start)
            if remaining <= 0:
                stop_reason = "RunTimeLimit"
                break
            futures = {}
            for i, request in enumerate(requests[offset:offset+concurrency]):
                index = offset+i
                directory = output/f"request-{index:04d}"
                future = executor.submit(execute_request, directory, index, request, identity, binary, dictionary,
                                         validator, min(remaining, request_timeout))
                futures[future] = index
            for future in as_completed(futures):
                try:
                    terminal, record = future.result()
                except Exception as error:
                    # A failed receipt write is itself observable; never call
                    # that already-scheduled subprocess "not attempted".
                    terminal = dict(index=futures[future], status="failed_without_receipt", error_type=type(error).__name__)
                    record = None
                attempts.append(terminal)
                if record is not None:
                    records[record["stable_id"]] = record
                if terminal["status"] not in ("complete", "candidate_count_rejected"):
                    stop_reason = "UnexpectedRequestFailure"
            if progress is not None and (offset % 100 == 0 or stop_reason):
                progress(len(attempts), len(requests))
            if stop_reason:
                break
    attempts.sort(key=lambda a: a["index"])
    return dict(attempts=attempts, not_attempted=len(requests)-len(attempts), stop_reason=stop_reason,
                elapsed_seconds=round(time.monotonic()-start, 3)), records
