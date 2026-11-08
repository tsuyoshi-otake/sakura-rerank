"""One fixed reading per process; expected export rejection is observable evidence."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.input_boundary import aggregate
from sakura_rerank.data.kwdlc_probe import write_once
from common import (ROOT, BINDING, BINARY, DICTIONARY, authenticate_input, authenticate_population,
                    committed, identity, jsonl, load_old_snapshots, native, sha)

R2 = ROOT / "isolated-r2"
PLAN = Path("research/issue-31-input-boundary/isolation-r2.json")
EXPECTED_ERROR = b"research exporter failed: converter returned an invalid candidate count\n"


def execute_one(index, request, converter_identity, timeout):
    directory = R2 / "candidates" / f"request-{index:04d}"
    directory.mkdir()
    terminal = dict(index=index, stable_id=request["stable_id"], status="failed")
    record = None
    start = time.monotonic()
    try:
        raw = jsonl([request])
        write_once(directory/"input.jsonl", raw)
        write_once(directory/"identity.json", canonical_json_bytes(converter_identity)+b"\n")
        terminal["input_sha256"] = sha(directory/"input.jsonl")
        command = [str(BINARY.resolve()), "--input", str((directory/"input.jsonl").resolve()),
                   "--dictionary", str(DICTIONARY.resolve()), "--output", str((directory/"output.jsonl").resolve()),
                   "--report", str((directory/"native-report.json").resolve()), "--identity-manifest",
                   str((directory/"identity.json").resolve()), "--limit", "32"]
        with (directory/"stdout.log").open("xb") as out, (directory/"stderr.log").open("xb") as err:
            process = subprocess.run(command, stdout=out, stderr=err, timeout=timeout,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        terminal["exit_code"] = process.returncode
        if process.returncode == 0:
            records = native.validate_result(directory, raw, converter_identity)
            record = records[0]
            terminal.update(status="complete", output_sha256=sha(directory/"output.jsonl"))
        elif (process.returncode == 2 and (directory/"stderr.log").read_bytes() == EXPECTED_ERROR
              and not (directory/"output.jsonl").exists() and not (directory/"native-report.json").exists()):
            terminal.update(status="candidate_count_rejected", stderr_sha256=sha(directory/"stderr.log"))
        else:
            terminal["error_type"] = "UnexpectedNativeExit"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        terminal["error_type"] = type(error).__name__
    finally:
        terminal["elapsed_seconds"] = round(time.monotonic()-start, 3)
        write_once(directory/"execution.json", canonical_json_bytes(terminal)+b"\n")
    return dict(index=index, status=terminal["status"], execution_sha256=sha(directory/"execution.json")), record


def run(execution_commit):
    plan = json.loads(committed(PLAN, execution_commit))
    committed(Path(__file__).relative_to(Path.cwd()) if Path(__file__).is_absolute() else Path(__file__), execution_commit)
    authenticate_population()
    bound = authenticate_input(plan["input_commit"])
    if sha(BINDING) != plan["input_binding_sha256"]:
        raise ValueError("r2_input_binding_differs")
    converter_identity = identity()
    snapshots = load_old_snapshots(converter_identity)
    requests = [json.loads(line) for line in (ROOT/"new-requests.jsonl").read_bytes().splitlines()]
    if len(requests) != plan["bounds"]["requests"]:
        raise ValueError("r2_request_population_differs")
    targets = [json.loads(line) for line in (ROOT/"targets.jsonl").read_bytes().splitlines()]
    (R2/"candidates").mkdir(parents=True, exist_ok=False)
    receipt = dict(kind="input_boundary_isolated_execution", status="failed", execution_commit=execution_commit,
                   plan_sha256=sha(PLAN), input_binding_sha256=sha(BINDING),
                   first_attempt_receipt_sha256=sha(ROOT/"execution.json"),
                   requests=len(requests), reused_requests=bound["reused_requests"], attempts=[])
    start = time.monotonic()
    try:
        # Bounded waves avoid an unbounded executor queue and define failure ownership.
        with ThreadPoolExecutor(max_workers=plan["bounds"]["concurrency"]) as executor:
            for offset in range(0, len(requests), plan["bounds"]["concurrency"]):
                remaining = plan["bounds"]["run_timeout_seconds"]-(time.monotonic()-start)
                if remaining <= 0:
                    receipt["stop_reason"] = "RunTimeLimit"
                    break
                wave = requests[offset:offset+plan["bounds"]["concurrency"]]
                futures = [executor.submit(execute_one, offset+i, row, converter_identity,
                           min(remaining, plan["bounds"]["request_timeout_seconds"])) for i, row in enumerate(wave)]
                stop = False
                for future in as_completed(futures):
                    terminal, record = future.result()
                    receipt["attempts"].append(terminal)
                    if record is not None:
                        snapshots[record["stable_id"]] = record
                    stop = stop or terminal["status"] == "failed"
                if offset % 100 == 0:
                    print(json.dumps(dict(stage="isolated_boundary", attempted=len(receipt["attempts"]),
                                          total=len(requests))), flush=True)
                if stop:
                    receipt["stop_reason"] = "UnexpectedRequestFailure"
                    break
        identity()
        authenticate_input(plan["input_commit"])
        result = aggregate(targets, {key: row["candidate_snapshots"]["training_top32"]["candidates"]
                                     for key, row in snapshots.items()})
        write_once(R2/"measurement.json", canonical_json_bytes(result)+b"\n")
        receipt.update(status="complete" if len(receipt["attempts"]) == len(requests) and "stop_reason" not in receipt else "partial",
                       measurement_sha256=sha(R2/"measurement.json"))
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        receipt["attempts"].sort(key=lambda a: a["index"])
        receipt["counts"] = dict(Counter(a["status"] for a in receipt["attempts"]))
        receipt["not_attempted"] = len(requests)-len(receipt["attempts"])
        receipt["elapsed_seconds"] = round(time.monotonic()-start, 3)
        write_once(R2/"execution.json", canonical_json_bytes(receipt)+b"\n")
    return {key: receipt[key] for key in ("status", "counts", "not_attempted", "elapsed_seconds")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-commit", required=True)
    print(json.dumps(run(parser.parse_args().execution_commit)))
