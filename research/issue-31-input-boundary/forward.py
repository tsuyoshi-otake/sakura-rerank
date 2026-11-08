"""Bounded no-retry conversion. Every attempted batch gets a terminal receipt."""
import argparse
import json
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.input_boundary import aggregate
from sakura_rerank.data.kwdlc_probe import write_once
from common import (ROOT, PLAN, BINDING, BINARY, DICTIONARY, authenticate_input,
                    authenticate_population, identity, jsonl, load_old_snapshots, native, sha)


def run(input_commit):
    plan, _, _ = authenticate_population()
    bound = authenticate_input(input_commit)
    converter_identity = identity()
    snapshots = load_old_snapshots(converter_identity)
    requests = [json.loads(line) for line in (ROOT / "new-requests.jsonl").read_bytes().splitlines()]
    targets = [json.loads(line) for line in (ROOT / "targets.jsonl").read_bytes().splitlines()]
    output = ROOT / "candidates"
    output.mkdir(exist_ok=False)
    receipt = dict(kind="input_boundary_forward", status="failed", input_commit=input_commit,
                   input_binding_sha256=sha(BINDING), new_requests=len(requests), reused_requests=bound["reused_requests"],
                   batches=[], measured_new_requests=0, model_predictions=0, model_training=0, independent_test=False)
    start = time.monotonic()
    try:
        for offset in range(0, len(requests), plan["bounds"]["batch"]):
            remaining = plan["bounds"]["run_timeout_seconds"] - (time.monotonic()-start)
            if remaining <= 0:
                receipt["error_type"] = "RunTimeLimit"
                break
            batch = requests[offset:offset+plan["bounds"]["batch"]]
            directory = output / f"batch-{offset//plan['bounds']['batch']:03d}"
            directory.mkdir()
            terminal = dict(index=len(receipt["batches"]), status="failed", requests=len(batch))
            try:
                raw = jsonl(batch)
                write_once(directory / "input.jsonl", raw)
                write_once(directory / "identity.json", canonical_json_bytes(converter_identity) + b"\n")
                command = [str(BINARY.resolve()), "--input", str((directory/"input.jsonl").resolve()),
                           "--dictionary", str(DICTIONARY.resolve()), "--output", str((directory/"output.jsonl").resolve()),
                           "--report", str((directory/"native-report.json").resolve()), "--identity-manifest",
                           str((directory/"identity.json").resolve()), "--limit", "32"]
                with (directory/"stdout.log").open("xb") as out, (directory/"stderr.log").open("xb") as err:
                    process = subprocess.run(command, stdout=out, stderr=err,
                        timeout=min(remaining, plan["bounds"]["batch_timeout_seconds"]),
                        creationflags=subprocess.CREATE_NO_WINDOW)
                terminal["exit_code"] = process.returncode
                if process.returncode:
                    raise ValueError("converter_nonzero_exit")
                records = native.validate_result(directory, raw, converter_identity)
                identity()
                snapshots.update({row["stable_id"]: row for row in records})
                terminal.update(status="complete", input_sha256=sha(directory/"input.jsonl"),
                                output_sha256=sha(directory/"output.jsonl"))
                receipt["measured_new_requests"] += len(records)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                terminal["error_type"] = type(error).__name__
            finally:
                write_once(directory/"execution.json", canonical_json_bytes(terminal)+b"\n")
                receipt["batches"].append(dict(index=terminal["index"], status=terminal["status"],
                    requests=len(batch), execution_sha256=sha(directory/"execution.json")))
            print(json.dumps(dict(stage="boundary_forward", attempted=offset+len(batch), planned=len(requests))), flush=True)
            if terminal["status"] != "complete":
                break
        identity()
        authenticate_input(input_commit)
        result = aggregate(targets, {key: row["candidate_snapshots"]["training_top32"]["candidates"]
                                     for key, row in snapshots.items()})
        write_once(ROOT/"measurement.json", canonical_json_bytes(result)+b"\n")
        receipt.update(status="complete" if receipt["measured_new_requests"] == len(requests) else "partial",
                       measurement_sha256=sha(ROOT/"measurement.json"))
        return dict(slots=result["slots"], status=receipt["status"], new_requests=len(requests),
                    measured_new_requests=receipt["measured_new_requests"])
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        receipt["not_attempted_requests"] = len(requests)-sum(b["requests"] for b in receipt["batches"])
        receipt["failed_requests"] = sum(b["requests"] for b in receipt["batches"] if b["status"] != "complete")
        receipt["elapsed_seconds"] = round(time.monotonic()-start, 3)
        write_once(ROOT/"execution.json", canonical_json_bytes(receipt)+b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-commit", required=True)
    print(json.dumps(run(parser.parse_args().input_commit)))
