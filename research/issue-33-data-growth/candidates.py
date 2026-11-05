"""Acquire one authenticated candidate snapshot per distinct fixed reading."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import time

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.reference_probe import authenticate_identity, validate_probe_records
from prepare_sources import sha
from extend_wiki import ROOT

INPUT_BINDING=Path("manifests/data-growth-input-reservations-v2.json")
IDENTITY=Path("manifests/reference-probe-identity-v1.json")
IDENTITY_SHA="9193ee9d387d0431016347e881e2fb245833ea0d603b829e91494e3258d65877"
BINARY=Path("data/generated/issue-31-reference-exporter-v1/probe-exporter.exe")
DICTIONARY=Path("data/generated/issue-31-exporter-restoration-v1/system.dic")


def execute(commit):
    if len(commit)!=40 or any(c not in "0123456789abcdef" for c in commit):raise ValueError("full_commit_required")
    raw=subprocess.check_output(["git","show",commit+":"+INPUT_BINDING.as_posix()],timeout=30)
    if raw!=INPUT_BINDING.read_bytes() or raw!=(ROOT/"isolation/execution.json").read_bytes():raise ValueError("input_reservation_changed")
    binding=json.loads(raw)
    if binding["status"]!="complete":raise ValueError("isolated_fixed_population_required")
    for name in ("requests","selected"):
        if sha(ROOT/"isolation"/(name+".jsonl"))!=binding[name+"_sha256"]:raise ValueError("input_population_changed")
    requests=[json.loads(line) for line in (ROOT/"isolation/requests.jsonl").read_bytes().splitlines()]
    if len(requests)!=binding["unique_readings"]:raise ValueError("reading_population_changed")
    identity=authenticate_identity(IDENTITY,IDENTITY_SHA,BINARY,DICTIONARY)
    output=ROOT/"candidates"
    output.mkdir(exist_ok=False)
    receipt=dict(kind="growth_candidate_execution",status="failed",input_commit=commit,
        input_binding_sha256=hashlib.sha256(raw).hexdigest(),identity_sha256=IDENTITY_SHA,
        legacy_training_eligible=False,gold_certified=False,new_final_test_used=False,batches=[],
        reuse_contract="same reading, immutable converter/dictionary; converter has no left-context input")
    counts=Counter()
    start=time.monotonic()
    try:
        for offset in range(0,len(requests),100):
            batch=requests[offset:offset+100]
            directory=output/f"batch-{offset//100:05d}"
            directory.mkdir()
            input_raw=b"".join(canonical_json_bytes(row)+b"\n" for row in batch)
            write_once(directory/"input.jsonl",input_raw)
            write_once(directory/"identity.json",canonical_json_bytes(identity)+b"\n")
            command=[str(BINARY.resolve()),"--input",str((directory/"input.jsonl").resolve()),
                "--dictionary",str(DICTIONARY.resolve()),"--output",str((directory/"output.jsonl").resolve()),
                "--report",str((directory/"native-report.json").resolve()),
                "--identity-manifest",str((directory/"identity.json").resolve()),"--limit","32"]
            terminal=dict(status="failed",request_count=len(batch),input_sha256=hashlib.sha256(input_raw).hexdigest())
            try:
                with (directory/"stdout.log").open("xb") as out,(directory/"stderr.log").open("xb") as err:
                    process=subprocess.run(command,stdout=out,stderr=err,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
                terminal["exit_code"]=process.returncode
                if process.returncode!=0:raise RuntimeError("converter_exit_failure")
                candidate_raw=(directory/"output.jsonl").read_bytes()
                rows=validate_probe_records(candidate_raw,batch,identity)
                statuses=Counter(row["candidate_snapshots"]["training_top32"]["exporter_run"]["result_status"] for row in rows)
                expected=dict(dictionary_sha256=identity["dictionary_sha256"],exporter_binary_sha256=identity["exporter_binary_sha256"],
                    exporter_git_sha=identity["exporter_git_sha"],effective_converter_bound=32,requested_limit=32,
                    input_sha256=terminal["input_sha256"],output_sha256=hashlib.sha256(candidate_raw).hexdigest(),record_count=len(rows),
                    search_exhausted_record_count=statuses["search_exhausted"],truncated_record_count=statuses["truncated"],
                    total_candidate_count=sum(len(r["candidate_snapshots"]["training_top32"]["candidates"]) for r in rows),
                    status="exported",verification_status="unverified")
                if json.loads((directory/"native-report.json").read_bytes())!=expected:raise ValueError("native_receipt_differs")
                terminal.update(status="complete",output_sha256=expected["output_sha256"])
                counts.update(statuses)
                counts["validated_readings"]+=len(rows)
            except (subprocess.TimeoutExpired,RuntimeError) as error:
                terminal["error_type"]=type(error).__name__
                counts["failed_readings"]+=len(batch)
            finally:
                write_once(directory/"execution.json",canonical_json_bytes(terminal)+b"\n")
            receipt["batches"].append(dict(index=offset//100,execution_sha256=sha(directory/"execution.json")))
            print(json.dumps({"stage":"candidates","processed":offset+len(batch),"total":len(requests),"failed":counts["failed_readings"]}),flush=True)
        authenticate_identity(IDENTITY,IDENTITY_SHA,BINARY,DICTIONARY)
        if counts["validated_readings"]+counts["failed_readings"]!=len(requests):raise ValueError("unaccounted_readings")
        receipt.update(status="complete",counts=dict(counts))
        return receipt
    except Exception as error:
        receipt.update(error_type=type(error).__name__,counts=dict(counts))
        raise
    finally:
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(output/"execution.json",canonical_json_bytes(receipt)+b"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-commit",required=True)
    print(canonical_json_bytes(execute(parser.parse_args().input_commit)).decode("utf-8"))
