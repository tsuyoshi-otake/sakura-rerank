"""Measure fixed pilot slots using the separately authenticated reference converter."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

from sakura_rerank.data.context_pilot import aggregate
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from sakura_rerank.data.reference_probe import authenticate_identity
from acquire import ROOT,PLAN,authenticate,sha

sys.path.insert(0,str(Path("research/issue-31-quality").resolve()))
from run_reference_probe import validate_result

BINDING=Path("manifests/context-pilot-input-v1.json")
INPUT_COMMIT="7f1fff8c9bd41e3361cdf6c11e5cba4a45ead6f0"
IDENTITY=Path("manifests/reference-probe-identity-v1.json")
BINARY=Path("data/generated/issue-31-reference-exporter-v1/probe-exporter.exe")
DICTIONARY=Path("data/generated/issue-31-exporter-restoration-v1/system.dic")


def run():
    plan,_=authenticate()
    committed=subprocess.check_output(["git","show",INPUT_COMMIT+":"+BINDING.as_posix()],timeout=30)
    if committed!=BINDING.read_bytes() or committed!=(ROOT/"input-binding.json").read_bytes():
        raise ValueError("committed_input_binding_changed")
    bound=json.loads(committed)
    for name in ("targets","requests"):
        if sha(ROOT/(name+".jsonl"))!=bound[name+"_sha256"]:raise ValueError("pilot_inputs_changed")
    targets=[json.loads(line) for line in (ROOT/"targets.jsonl").read_bytes().splitlines()]
    requests=[json.loads(line) for line in (ROOT/"requests.jsonl").read_bytes().splitlines()]
    identity=authenticate_identity(IDENTITY,plan["converter"]["identity_sha256"],BINARY,DICTIONARY)
    output=ROOT/"candidates";output.mkdir(exist_ok=False)
    receipt=dict(kind="context_pilot_forward",status="failed",input_commit=INPUT_COMMIT,
        input_binding_sha256=sha(BINDING),identity_sha256=sha(IDENTITY),
        binary_sha256=sha(BINARY),dictionary_sha256=sha(DICTIONARY),script_sha256=sha(__file__),
        native_validator_sha256=sha("research/issue-31-quality/run_reference_probe.py"),batches=[],
        converter_requests=len(requests),planned_slots=1000,model_predictions=0,model_training=0,
        gold_certified=False,independent_test=False,legacy_training_eligible=False)
    start=time.monotonic();snapshots={}
    try:
        for offset in range(0,len(requests),100):
            batch=requests[offset:offset+100]
            directory=output/f"batch-{offset//100:03d}";directory.mkdir()
            raw=b"".join(canonical_json_bytes(r)+b"\n" for r in batch)
            write_once(directory/"input.jsonl",raw)
            write_once(directory/"identity.json",canonical_json_bytes(identity)+b"\n")
            terminal=dict(index=offset//100,status="failed",requests=len(batch),input_sha256=sha(directory/"input.jsonl"))
            try:
                command=[str(BINARY.resolve()),"--input",str((directory/"input.jsonl").resolve()),
                    "--dictionary",str(DICTIONARY.resolve()),"--output",str((directory/"output.jsonl").resolve()),
                    "--report",str((directory/"native-report.json").resolve()),"--identity-manifest",
                    str((directory/"identity.json").resolve()),"--limit","32"]
                with (directory/"stdout.log").open("xb") as out,(directory/"stderr.log").open("xb") as err:
                    process=subprocess.run(command,stdout=out,stderr=err,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
                terminal["exit_code"]=process.returncode
                if process.returncode:raise RuntimeError("converter_failed")
                records=validate_result(directory,raw,identity)
                snapshots.update({r["stable_id"]:r["candidate_snapshots"]["training_top32"]["candidates"] for r in records})
                terminal.update(status="complete",output_sha256=sha(directory/"output.jsonl"))
            except (subprocess.TimeoutExpired,RuntimeError) as error:
                terminal["error_type"]=type(error).__name__
            finally:
                write_once(directory/"execution.json",canonical_json_bytes(terminal)+b"\n")
                receipt["batches"].append(dict(index=terminal["index"],status=terminal["status"],requests=len(batch),execution_sha256=sha(directory/"execution.json")))
            print(json.dumps(dict(stage="forward",processed_readings=offset+len(batch),total=len(requests))),flush=True)
        authenticate_identity(IDENTITY,plan["converter"]["identity_sha256"],BINARY,DICTIONARY)
        result=aggregate(targets,snapshots)
        result.update(kind="context_pilot_measurement",input_commit=INPUT_COMMIT,input_binding_sha256=sha(BINDING),
                      ready_readings=len(requests),measured_readings=len(snapshots),forward_failures=len(requests)-len(snapshots))
        write_once(ROOT/"measurement.json",canonical_json_bytes(result)+b"\n")
        receipt.update(status="complete",measurement_sha256=sha(ROOT/"measurement.json"),measured_readings=len(snapshots))
        return result
    except Exception as error:
        receipt["error_type"]=type(error).__name__
        raise
    finally:
        receipt["not_attempted_requests"]=len(requests)-sum(x["requests"] for x in receipt["batches"])
        receipt["elapsed_seconds"]=round(time.monotonic()-start,3)
        write_once(ROOT/"forward-execution.json",canonical_json_bytes(receipt)+b"\n")


if __name__=="__main__":
    result=run();print(json.dumps({k:result[k] for k in ("slots","ready_readings","measured_readings","forward_failures")}))
