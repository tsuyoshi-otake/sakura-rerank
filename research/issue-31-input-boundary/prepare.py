"""Replay fixed annotations and freeze exact research views before new conversion."""
from collections import Counter
import json
from pathlib import Path

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.input_boundary import build_views, collect_requests, request_id
from sakura_rerank.data.kwdlc_probe import write_once
from common import ROOT, PLAN, PLAN_COMMIT, BINDING, authenticate_population, jsonl, pilot, sha


def generate():
    _, old, units = authenticate_population()
    rows = []
    for original in old:
        span = units[original["document_id"]][original["annotation_unit"]][original["start_morpheme"]:original["end_morpheme"]]
        row = build_views(span)
        if row["reading"] != original["reading"] or row["target"] != original["target"]:
            raise ValueError("reconstructed_span_differs")
        row.update(stable_id=original["stable_id"], document_id=original["document_id"],
                   policy=original["policy"], original_status=original["status"],
                   gold_certified=False, training_eligible=False, observed_ime_boundary=False)
        rows.append(row)
    requests = collect_requests(rows)
    old_ids = {request_id(json.loads(line)["reading"]) for line in (pilot.ROOT / "requests.jsonl").read_bytes().splitlines()}
    new = [row for row in requests if row["stable_id"] not in old_ids]
    return rows, requests, new


def run():
    first, second = generate(), generate()
    raw = [jsonl(rows) for rows in first]
    if raw != [jsonl(rows) for rows in second]:
        raise ValueError("preparation_replay_differs")
    ROOT.mkdir(exist_ok=False)
    names = ("targets", "requests", "new-requests")
    for name, content in zip(names, raw):
        write_once(ROOT / (name + ".jsonl"), content)
    code = ["src/sakura_rerank/data/input_boundary.py",
            "research/issue-31-input-boundary/common.py",
            "research/issue-31-input-boundary/prepare.py",
            "research/issue-31-input-boundary/forward.py",
            "research/issue-31-quality/run_reference_probe.py"]
    bound = dict(kind="input_boundary_research_binding", plan_commit=PLAN_COMMIT, plan_sha256=sha(PLAN),
                 artifacts={name: sha(ROOT / (name + ".jsonl")) for name in names},
                 code={path: sha(path) for path in code}, slots=len(first[0]), requests=len(first[1]),
                 new_requests=len(first[2]), reused_requests=len(first[1])-len(first[2]),
                 statuses=dict(Counter(r["status"] for r in first[0])),
                 literal_slots=sum(r["token_classes"].get("literal", 0)>0 for r in first[0]),
                 deterministic_byte_replay=True, old_converter_outcomes_already_exposed=True,
                 new_converter_outcomes_seen=False, gold_certified=False, independent_test=False)
    for path in (ROOT / "input-binding.json", BINDING):
        write_once(path, canonical_json_bytes(bound) + b"\n")
    return {k: bound[k] for k in ("slots", "requests", "new_requests", "reused_requests", "statuses", "literal_slots")}


if __name__ == "__main__":
    print(json.dumps(run()))
