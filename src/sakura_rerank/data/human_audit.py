"""Deterministic Tier A human-review queues and fail-closed quality reports."""

from __future__ import annotations

import hashlib
import json
import math
import re
import copy
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ..atomic_io import write_bytes_atomic, write_bytes_pair_atomic
from .contracts import canonical_json_bytes, canonical_jsonl_bytes, validate_records
from .tier_a import TierAError


QUEUE_SCHEMA_VERSION = 1
QUEUE_RECORD_TYPE = "tier_a_human_audit_item"
QUEUE_MANIFEST_KIND = "tier_a_human_audit_queue"
RESPONSE_SCHEMA_VERSION = 1
RESPONSE_RECORD_TYPE = "tier_a_human_audit_response"
REPORT_SCHEMA_VERSION = 1
REPORT_KIND = "tier_a_human_audit_quality"
APPLICATION_REPORT_KIND = "tier_a_human_audit_application"
MAX_QUEUE_RECORDS = 100_000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_QUEUE_BYTES = 256 * 1024 * 1024
MAX_NOTE_CHARS = 2_000
VERDICTS = (
    "valid",
    "wrong_reading",
    "wrong_segmentation",
    "wrong_gold_surface",
    "ambiguous",
    "extraction_noise",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_STRATUM = re.compile(
    r"reading-(?:01-02|03-09|10-30|31-128)/candidates-(?:02-06|07-16|17-32)/local-(?:correct|wrong)"
)
_QUEUE_MANIFEST_FIELDS = {
    "schema_version",
    "manifest_kind",
    "selection_algorithm",
    "seed",
    "minimum_sample_size",
    "dataset_record_count",
    "dataset_content_sha256",
    "record_count",
    "final_holdout_count",
    "split_counts",
    "stratum_counts",
    "content_sha256",
    "raw_text_in_queue",
    "raw_text_in_manifest",
}


def _reading_bucket(length: int) -> str:
    if length <= 2:
        return "reading-01-02"
    if length <= 9:
        return "reading-03-09"
    if length <= 30:
        return "reading-10-30"
    return "reading-31-128"


def _candidate_bucket(count: int) -> str:
    if count <= 6:
        return "candidates-02-06"
    if count <= 16:
        return "candidates-07-16"
    return "candidates-17-32"


def _stratum(record: Mapping[str, Any]) -> str:
    top32 = record["candidate_snapshots"]["training_top32"]["candidates"]
    local = "local-correct" if record["gold_index"] == 0 else "local-wrong"
    return "/".join((_reading_bucket(len(record["reading"])), _candidate_bucket(len(top32)), local))


def _selection_order(seed: int, stable_id: str) -> bytes:
    return hashlib.sha256(f"{seed}\0{stable_id}".encode("utf-8")).digest()


def select_audit_records(
    records: Sequence[Mapping[str, Any]], *, seed: int, minimum_sample_size: int
) -> list[dict[str, Any]]:
    """Select every final-holdout row plus a deterministic stratified sample."""

    normalized = validate_records(records, require_split=True)
    if type(seed) is not int:
        raise TierAError("audit seed must be an integer")
    if type(minimum_sample_size) is not int or not 1 <= minimum_sample_size <= MAX_QUEUE_RECORDS:
        raise TierAError("minimum_sample_size is outside the bound")
    if len(normalized) > MAX_QUEUE_RECORDS:
        raise TierAError("audit input exceeds the queue bound")

    selected_ids = {
        record["stable_id"] for record in normalized if record["split"] == "final-holdout"
    }
    needed = max(0, minimum_sample_size - len(selected_ids))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in normalized:
        if record["stable_id"] not in selected_ids:
            groups[_stratum(record)].append(record)
    for group in groups.values():
        group.sort(key=lambda record: (_selection_order(seed, record["stable_id"]), record["stable_id"]))
    names = sorted(groups)
    offsets = {name: 0 for name in names}
    while needed and names:
        next_names: list[str] = []
        for name in names:
            offset = offsets[name]
            group = groups[name]
            if offset < len(group) and needed:
                selected_ids.add(group[offset]["stable_id"])
                offsets[name] += 1
                needed -= 1
            if offsets[name] < len(group):
                next_names.append(name)
        names = next_names
    if needed:
        raise TierAError("audit input has fewer records than minimum_sample_size")

    selected = [record for record in normalized if record["stable_id"] in selected_ids]
    queue: list[dict[str, Any]] = []
    for record in selected:
        top6 = record["candidate_snapshots"]["production_top6"]["candidates"]
        gold = record["candidate_snapshots"]["training_top32"]["candidates"][
            record["gold_index"]
        ]
        queue.append(
            {
                "schema_version": QUEUE_SCHEMA_VERSION,
                "record_type": QUEUE_RECORD_TYPE,
                "stable_id": record["stable_id"],
                "split": record["split"],
                "stratum": _stratum(record),
                "source": {
                    "page_id": record["source"]["page_id"],
                    "revision_id": record["source"]["revision_id"],
                },
                "left_context": record["session"]["left_context"],
                "reading": record["reading"],
                "gold_surface": record["gold_surface"],
                "gold_index": record["gold_index"],
                "gold_segments": gold["segments"],
                "production_candidates": [
                    {"rank": candidate["rank"], "surface": candidate["surface"]}
                    for candidate in top6
                ],
            }
        )
    queue.sort(key=lambda item: item["stable_id"])
    return queue


def build_queue_manifest(
    records: Sequence[Mapping[str, Any]],
    queue: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    minimum_sample_size: int,
) -> dict[str, Any]:
    dataset_payload = canonical_jsonl_bytes(validate_records(records, require_split=True))
    queue_payload = canonical_jsonl_bytes(queue)
    strata = Counter(item["stratum"] for item in queue)
    split_counts = Counter(item["split"] for item in queue)
    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "manifest_kind": QUEUE_MANIFEST_KIND,
        "selection_algorithm": "final_holdout_plus_stratified_round_robin_sha256_v1",
        "seed": seed,
        "minimum_sample_size": minimum_sample_size,
        "dataset_record_count": len(records),
        "dataset_content_sha256": hashlib.sha256(dataset_payload).hexdigest(),
        "record_count": len(queue),
        "final_holdout_count": split_counts.get("final-holdout", 0),
        "split_counts": dict(sorted(split_counts.items())),
        "stratum_counts": dict(sorted(strata.items())),
        "content_sha256": hashlib.sha256(queue_payload).hexdigest(),
        "raw_text_in_queue": True,
        "raw_text_in_manifest": False,
    }


def publish_audit_queue(
    queue_path: str | Path,
    manifest_path: str | Path,
    queue: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> tuple[str, str]:
    queue_payload = canonical_jsonl_bytes(queue)
    queue_sha = hashlib.sha256(queue_payload).hexdigest()
    if manifest.get("content_sha256") != queue_sha or manifest.get("record_count") != len(queue):
        raise TierAError("audit queue manifest does not match the queue")
    if manifest.get("raw_text_in_manifest") is not False:
        raise TierAError("audit queue manifest must be text-free")
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    write_bytes_pair_atomic(queue_path, queue_payload, manifest_path, manifest_payload)
    return queue_sha, hashlib.sha256(manifest_payload).hexdigest()


def read_audit_queue(path: str | Path) -> list[dict[str, Any]]:
    queue_path = Path(path)
    try:
        payload = queue_path.read_bytes()
    except OSError as error:
        raise TierAError(f"audit queue: cannot read ({type(error).__name__})") from error
    if not payload or len(payload) > MAX_QUEUE_BYTES:
        raise TierAError("audit queue: empty or outside byte bound")
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise TierAError("audit queue: must be UTF-8") from error
    queue: list[dict[str, Any]] = []
    expected_fields = {
        "schema_version",
        "record_type",
        "stable_id",
        "split",
        "stratum",
        "source",
        "left_context",
        "reading",
        "gold_surface",
        "gold_index",
        "gold_segments",
        "production_candidates",
    }
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise TierAError(f"audit queue line {line_number}: invalid JSON") from error
        if not isinstance(value, Mapping) or set(value) != expected_fields:
            raise TierAError(f"audit queue line {line_number}: fields do not match schema")
        if value["schema_version"] != QUEUE_SCHEMA_VERSION or value["record_type"] != QUEUE_RECORD_TYPE:
            raise TierAError(f"audit queue line {line_number}: unsupported schema")
        stable_id = value["stable_id"]
        if not isinstance(stable_id, str) or _IDENTIFIER.fullmatch(stable_id) is None:
            raise TierAError(f"audit queue line {line_number}: invalid stable_id")
        if value["split"] not in {"train", "dev", "final-holdout"}:
            raise TierAError(f"audit queue line {line_number}: invalid split")
        if not isinstance(value["stratum"], str) or len(value["stratum"]) > 128:
            raise TierAError(f"audit queue line {line_number}: invalid stratum")
        source = value["source"]
        if not isinstance(source, Mapping) or set(source) != {"page_id", "revision_id"}:
            raise TierAError(f"audit queue line {line_number}: invalid source")
        for field in ("left_context", "reading", "gold_surface"):
            if not isinstance(value[field], str) or "\0" in value[field]:
                raise TierAError(f"audit queue line {line_number}: invalid {field}")
        if type(value["gold_index"]) is not int or value["gold_index"] < 0:
            raise TierAError(f"audit queue line {line_number}: invalid gold_index")
        candidates = value["production_candidates"]
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 6:
            raise TierAError(f"audit queue line {line_number}: invalid candidates")
        for rank, candidate in enumerate(candidates):
            if (
                not isinstance(candidate, Mapping)
                or set(candidate) != {"rank", "surface"}
                or candidate["rank"] != rank
                or not isinstance(candidate["surface"], str)
            ):
                raise TierAError(f"audit queue line {line_number}: invalid candidate")
        if not isinstance(value["gold_segments"], list) or not value["gold_segments"]:
            raise TierAError(f"audit queue line {line_number}: invalid gold_segments")
        queue.append(dict(value))
    stable_ids = [item["stable_id"] for item in queue]
    if stable_ids != sorted(stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise TierAError("audit queue stable IDs must be sorted and unique")
    return queue


def read_queue_manifest(path: str | Path) -> Mapping[str, Any]:
    manifest_path = Path(path)
    try:
        if manifest_path.stat().st_size > 1024 * 1024:
            raise TierAError("audit queue manifest exceeds byte bound")
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TierAError(f"audit queue manifest: cannot read ({type(error).__name__})") from error
    if not isinstance(value, Mapping):
        raise TierAError("audit queue manifest must be an object")
    return value


def validate_queue_manifest(
    manifest: Mapping[str, Any], queue: Sequence[Mapping[str, Any]]
) -> None:
    if set(manifest) != _QUEUE_MANIFEST_FIELDS:
        raise TierAError("audit queue manifest: fields do not match aggregate-only schema")
    if manifest.get("schema_version") != QUEUE_SCHEMA_VERSION:
        raise TierAError("audit queue manifest: unsupported schema")
    if manifest.get("manifest_kind") != QUEUE_MANIFEST_KIND:
        raise TierAError("audit queue manifest: unsupported kind")
    if manifest.get("selection_algorithm") != "final_holdout_plus_stratified_round_robin_sha256_v1":
        raise TierAError("audit queue manifest: unsupported selection algorithm")
    if type(manifest.get("seed")) is not int:
        raise TierAError("audit queue manifest: invalid seed")
    if (
        type(manifest.get("minimum_sample_size")) is not int
        or not 1 <= manifest["minimum_sample_size"] <= MAX_QUEUE_RECORDS
    ):
        raise TierAError("audit queue manifest: invalid minimum sample size")
    if type(manifest.get("dataset_record_count")) is not int or manifest["dataset_record_count"] < len(queue):
        raise TierAError("audit queue manifest: invalid dataset record count")
    if _SHA256.fullmatch(str(manifest.get("dataset_content_sha256"))) is None:
        raise TierAError("audit queue manifest: invalid dataset hash")
    if manifest.get("record_count") != len(queue):
        raise TierAError("audit queue manifest: record count mismatch")
    queue_sha = hashlib.sha256(canonical_jsonl_bytes(queue)).hexdigest()
    if manifest.get("content_sha256") != queue_sha:
        raise TierAError("audit queue manifest: content hash mismatch")
    if manifest.get("raw_text_in_queue") is not True or manifest.get("raw_text_in_manifest") is not False:
        raise TierAError("audit queue manifest: raw-text flags are invalid")
    split_counts = Counter(item["split"] for item in queue)
    expected_split_counts = dict(sorted(split_counts.items()))
    if manifest.get("split_counts") != expected_split_counts:
        raise TierAError("audit queue manifest: split counts mismatch")
    if manifest.get("final_holdout_count") != split_counts.get("final-holdout", 0):
        raise TierAError("audit queue manifest: final holdout count mismatch")
    strata = Counter(item["stratum"] for item in queue)
    if any(_STRATUM.fullmatch(name) is None for name in strata):
        raise TierAError("audit queue manifest: invalid stratum")
    if manifest.get("stratum_counts") != dict(sorted(strata.items())):
        raise TierAError("audit queue manifest: stratum counts mismatch")


def read_audit_responses(path: str | Path) -> list[dict[str, Any]]:
    response_path = Path(path)
    try:
        payload = response_path.read_bytes()
    except OSError as error:
        raise TierAError(f"audit responses: cannot read ({type(error).__name__})") from error
    if not payload or len(payload) > MAX_RESPONSE_BYTES:
        raise TierAError("audit responses: empty or outside byte bound")
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise TierAError("audit responses: must be UTF-8") from error
    parsed: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise TierAError(f"audit responses line {line_number}: invalid JSON") from error
        if not isinstance(value, Mapping):
            raise TierAError(f"audit responses line {line_number}: response must be an object")
        parsed.append(value)
    return validate_audit_responses(parsed)


def validate_audit_responses(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate response objects and return their canonical stable-ID order."""

    responses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, value in enumerate(values, start=1):
        if set(value) != {
            "schema_version",
            "record_type",
            "stable_id",
            "verdict",
            "reviewer_id",
            "reviewed_at",
            "note",
        }:
            raise TierAError(f"audit responses line {line_number}: fields do not match schema")
        if value["schema_version"] != RESPONSE_SCHEMA_VERSION or value["record_type"] != RESPONSE_RECORD_TYPE:
            raise TierAError(f"audit responses line {line_number}: unsupported schema")
        stable_id = value["stable_id"]
        reviewer_id = value["reviewer_id"]
        if not isinstance(stable_id, str) or _IDENTIFIER.fullmatch(stable_id) is None:
            raise TierAError(f"audit responses line {line_number}: invalid stable_id")
        if stable_id in seen:
            raise TierAError("audit responses: duplicate stable_id")
        seen.add(stable_id)
        if value["verdict"] not in VERDICTS:
            raise TierAError(f"audit responses line {line_number}: invalid verdict")
        if not isinstance(reviewer_id, str) or _IDENTIFIER.fullmatch(reviewer_id) is None:
            raise TierAError(f"audit responses line {line_number}: invalid reviewer_id")
        reviewed_at = value["reviewed_at"]
        try:
            timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise TierAError(f"audit responses line {line_number}: invalid reviewed_at") from error
        if timestamp.tzinfo is None:
            raise TierAError(f"audit responses line {line_number}: reviewed_at needs timezone")
        note = value["note"]
        if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS or "\0" in note:
            raise TierAError(f"audit responses line {line_number}: invalid note")
        responses.append(dict(value))
    responses.sort(key=lambda response: response["stable_id"])
    return responses


def publish_audit_responses(
    path: str | Path, responses: Sequence[Mapping[str, Any]]
) -> str:
    """Atomically publish validated responses without logging review text."""

    normalized = validate_audit_responses(responses)
    payload = canonical_jsonl_bytes(normalized)
    if not payload or len(payload) > MAX_RESPONSE_BYTES:
        raise TierAError("audit responses: empty or outside byte bound")
    write_bytes_atomic(path, payload)
    return hashlib.sha256(payload).hexdigest()


def wilson_lower_bound(successes: int, total: int, *, z: float = 1.959963984540054) -> float:
    if total <= 0 or not 0 <= successes <= total:
        return 0.0
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = proportion + z * z / (2.0 * total)
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    )
    return (centre - spread) / denominator


def build_quality_report(
    queue: Sequence[Mapping[str, Any]],
    responses: Sequence[Mapping[str, Any]],
    *,
    minimum_completed: int = 1_000,
    minimum_final_holdout_valid: int = 3_000,
) -> dict[str, Any]:
    if type(minimum_completed) is not int or not 1 <= minimum_completed <= MAX_QUEUE_RECORDS:
        raise TierAError("minimum_completed is outside the bound")
    if (
        type(minimum_final_holdout_valid) is not int
        or not 1 <= minimum_final_holdout_valid <= MAX_QUEUE_RECORDS
    ):
        raise TierAError("minimum_final_holdout_valid is outside the bound")
    queue_by_id = {item["stable_id"]: item for item in queue}
    if len(queue_by_id) != len(queue):
        raise TierAError("audit queue: duplicate stable_id")
    response_by_id = {response["stable_id"]: response for response in responses}
    if len(response_by_id) != len(responses):
        raise TierAError("audit responses: duplicate stable_id")
    unknown = set(response_by_id) - set(queue_by_id)
    if unknown:
        raise TierAError("audit responses: contains IDs outside the queue")
    verdict_counts = Counter(response["verdict"] for response in responses)
    completed = len(responses)
    valid = verdict_counts.get("valid", 0)
    precision = valid / completed if completed else 0.0
    lower = wilson_lower_bound(valid, completed)
    final_completed = sum(
        1 for stable_id in response_by_id if queue_by_id[stable_id]["split"] == "final-holdout"
    )
    final_valid = sum(
        1
        for stable_id, response in response_by_id.items()
        if queue_by_id[stable_id]["split"] == "final-holdout"
        and response["verdict"] == "valid"
    )
    final_valid_strata = Counter(
        queue_by_id[stable_id]["stratum"]
        for stable_id, response in response_by_id.items()
        if queue_by_id[stable_id]["split"] == "final-holdout"
        and response["verdict"] == "valid"
    )
    enough_completed = completed >= minimum_completed
    enough_holdout = final_valid >= minimum_final_holdout_valid
    precision_pass = precision >= 0.995 and lower >= 0.99
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_kind": REPORT_KIND,
        "selected_record_count": len(queue),
        "completed_record_count": completed,
        "pending_record_count": len(queue) - completed,
        "valid_record_count": valid,
        "invalid_record_count": completed - valid,
        "verdict_counts": {verdict: verdict_counts.get(verdict, 0) for verdict in VERDICTS},
        "final_holdout_completed_count": final_completed,
        "final_holdout_valid_count": final_valid,
        "final_holdout_valid_stratum_counts": dict(sorted(final_valid_strata.items())),
        "point_precision": precision,
        "wilson_95_lower_bound": lower,
        "thresholds": {
            "minimum_completed": minimum_completed,
            "minimum_final_holdout_valid": minimum_final_holdout_valid,
            "minimum_point_precision": 0.995,
            "minimum_wilson_95_lower_bound": 0.99,
        },
        "checks": {
            "minimum_completed": enough_completed,
            "minimum_final_holdout_valid": enough_holdout,
            "label_precision": precision_pass,
        },
        "gate_a_human_audit_pass": enough_completed and enough_holdout and precision_pass,
        "queue_content_sha256": hashlib.sha256(canonical_jsonl_bytes(queue)).hexdigest(),
        "response_content_sha256": hashlib.sha256(canonical_jsonl_bytes(responses)).hexdigest(),
        "raw_text_in_report": False,
    }


def apply_audit_responses(
    records: Sequence[Mapping[str, Any]],
    queue: Sequence[Mapping[str, Any]],
    responses: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply review outcomes without allowing pending or rejected rows into training."""

    normalized = validate_records(records, require_split=True)
    record_by_id = {record["stable_id"]: record for record in normalized}
    queue_by_id = {item["stable_id"]: item for item in queue}
    response_by_id = {response["stable_id"]: response for response in responses}
    if len(queue_by_id) != len(queue) or len(response_by_id) != len(responses):
        raise TierAError("audit application requires unique queue and response IDs")
    if set(queue_by_id) - set(record_by_id):
        raise TierAError("audit queue contains IDs outside the dataset")
    if set(response_by_id) - set(queue_by_id):
        raise TierAError("audit responses contain IDs outside the queue")

    output: list[dict[str, Any]] = []
    accepted = rejected = pending = 0
    for source_record in normalized:
        stable_id = source_record["stable_id"]
        record = copy.deepcopy(source_record)
        if stable_id not in queue_by_id:
            output.append(record)
            continue
        response = response_by_id.get(stable_id)
        if response is None:
            pending += 1
            record["sampled_human_audit"] = {
                "selection": "selected",
                "status": "pending",
                "noise_free": None,
                "reviewer_id": None,
                "reviewed_at": None,
            }
            record["training_eligible"] = False
            output.append(record)
            continue
        if response["verdict"] != "valid":
            rejected += 1
            continue
        accepted += 1
        record["sampled_human_audit"] = {
            "selection": "selected",
            "status": "accepted",
            "noise_free": True,
            "reviewer_id": response["reviewer_id"],
            "reviewed_at": response["reviewed_at"],
        }
        output.append(record)

    validated_output = validate_records(output, require_split=True)
    input_payload = canonical_jsonl_bytes(normalized)
    output_payload = canonical_jsonl_bytes(validated_output)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_kind": APPLICATION_REPORT_KIND,
        "input_record_count": len(normalized),
        "output_record_count": len(validated_output),
        "selected_record_count": len(queue),
        "accepted_record_count": accepted,
        "rejected_record_count": rejected,
        "pending_record_count": pending,
        "input_content_sha256": hashlib.sha256(input_payload).hexdigest(),
        "queue_content_sha256": hashlib.sha256(canonical_jsonl_bytes(queue)).hexdigest(),
        "response_content_sha256": hashlib.sha256(canonical_jsonl_bytes(responses)).hexdigest(),
        "output_content_sha256": hashlib.sha256(output_payload).hexdigest(),
        "raw_text_in_report": False,
    }
    return validated_output, report


def publish_audit_application(
    output_path: str | Path,
    report_path: str | Path,
    records: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> tuple[str, str]:
    output_payload = canonical_jsonl_bytes(records)
    output_sha = hashlib.sha256(output_payload).hexdigest()
    if report.get("output_content_sha256") != output_sha:
        raise TierAError("audit application report does not match the output")
    if report.get("raw_text_in_report") is not False:
        raise TierAError("audit application report must be text-free")
    report_payload = canonical_json_bytes(report) + b"\n"
    write_bytes_pair_atomic(output_path, output_payload, report_path, report_payload)
    return output_sha, hashlib.sha256(report_payload).hexdigest()


def publish_quality_report(path: str | Path, report: Mapping[str, Any]) -> str:
    if report.get("raw_text_in_report") is not False:
        raise TierAError("audit quality report must be text-free")
    payload = canonical_json_bytes(report) + b"\n"
    write_bytes_atomic(path, payload)
    return hashlib.sha256(payload).hexdigest()
