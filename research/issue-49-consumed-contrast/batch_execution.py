"""Sequential bounded native batches, with every member's terminal accounted."""
from collections import Counter
import hashlib
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once

REJECTION = b"research exporter failed: converter returned an invalid candidate count\n"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute_batch(batch, directory, identity, binary, dictionary, validator, timeout):
    directory.mkdir()
    raw = b"".join(canonical_json_bytes(r)+b"\n" for r in batch)
    terminal = dict(status="failed", request_count=len(batch), input_sha256=hashlib.sha256(raw).hexdigest())
    records = []
    started = time.monotonic()
    try:
        write_once(directory/"input.jsonl", raw)
        write_once(directory/"identity.json", canonical_json_bytes(identity)+b"\n")
        command = [str(binary.resolve()), "--input", str((directory/"input.jsonl").resolve()),
            "--dictionary", str(dictionary.resolve()), "--output", str((directory/"output.jsonl").resolve()),
            "--report", str((directory/"native-report.json").resolve()), "--identity-manifest",
            str((directory/"identity.json").resolve()), "--limit", "32"]
        with (directory/"stdout.log").open("xb") as out, (directory/"stderr.log").open("xb") as err:
            process = subprocess.run(command, stdout=out, stderr=err, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        terminal["exit_code"] = process.returncode
        if process.returncode == 0:
            validated = validator(directory, raw, identity)
            if len(validated) != len(batch) or {r["stable_id"] for r in validated} != {r["stable_id"] for r in batch}:
                raise ValueError("native_batch_validation_coverage")
            terminal.update(status="complete", output_sha256=digest(directory/"output.jsonl"))
            records = validated
        elif (process.returncode == 2 and (directory/"stderr.log").read_bytes() == REJECTION
                and not (directory/"output.jsonl").exists() and not (directory/"native-report.json").exists()):
            terminal.update(status="candidate_count_rejected", stderr_sha256=digest(directory/"stderr.log"))
        else:
            terminal["error_type"] = "UnexpectedNativeExit"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        terminal["error_type"] = type(error).__name__
    finally:
        terminal["elapsed_seconds"] = round(time.monotonic()-started, 3)
        write_once(directory/"execution.json", canonical_json_bytes(terminal)+b"\n")
    return terminal, records


def execute_batches(requests, output, identity, binary, dictionary, validator, *, total_timeout=900, progress=None):
    if (not 0 <= len(requests) <= 20000 or not 0 < total_timeout <= 900
            or len({r["stable_id"] for r in requests}) != len(requests)):
        raise ValueError("native_batch_execution_bound")
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    attempts, records, outcomes = [], {}, Counter()
    stop = None
    for offset in range(0, len(requests), 100):
        remaining = total_timeout-(time.monotonic()-started)
        if remaining <= 0:
            stop = "RunTimeLimit"
            break
        batch, index = requests[offset:offset+100], offset//100
        directory = output/f"batch-{index:05d}"
        try:
            result, validated = execute_batch(batch, directory, identity, binary, dictionary, validator, min(30, remaining))
            terminal = dict(index=index, offset=offset, request_count=len(batch), status=result["status"],
                            execution_sha256=digest(directory/"execution.json"))
        except Exception as error:
            terminal = dict(index=index, offset=offset, request_count=len(batch), status="failed_without_receipt", error_type=type(error).__name__)
            validated = []
        attempts.append(terminal)
        outcomes[terminal["status"]] += len(batch)
        records.update((r["stable_id"], r) for r in validated)
        if progress is not None and (index % 10 == 0 or offset+len(batch) == len(requests)):
            progress(offset+len(batch), len(requests))
        if terminal["status"] not in ("complete", "candidate_count_rejected"):
            stop = "UnexpectedBatchFailure"
            break
    attempted = sum(a["request_count"] for a in attempts)
    return dict(attempts=attempts, request_outcomes=dict(outcomes), not_attempted=len(requests)-attempted,
                stop_reason=stop, elapsed_seconds=round(time.monotonic()-started,3)), records
