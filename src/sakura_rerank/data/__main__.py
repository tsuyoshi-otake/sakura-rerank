"""Command-line entry point for the data manifest and contract boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from ..atomic_io import write_bytes_atomic
from .contracts import ContractError, canonical_json_bytes, canonical_jsonl_bytes, read_jsonl
from .corpus_v4 import (
    ADJUDICATION_REVIEWER_ID,
    CALIBRATION_SEED,
    GATE_A_REVIEWER_ID,
    SCREEN_REVIEWER_ID,
    analyze_stage0_dev_rules,
    audit_response_verdict_map,
    build_gate_a_teacher_batches,
    build_stage2_batches,
    build_teacher_batches,
    discover_teacher_disagreements,
    finalize_gate_a_teacher_responses,
    flatten_handoff_verdicts,
    flatten_teacher_verdicts,
    merge_external_verdict_maps,
    partition_stage2,
    preflight_v4_inputs,
    publish_partition_directory,
    publish_gate_a_teacher_evidence,
    publish_stage3_calibration_queue,
    publish_teacher_queue_directory,
    read_handoff_batches,
    read_handoff_verdict_directory,
    read_teacher_queue_directory,
    scan_verdict_directory,
    stage0_deterministic_hit_ids,
    stage0_probe_report,
    teacher_verdict_state_sha256,
    validate_gate_a_teacher_queue_binding,
)
from .corpus_v5 import (
    PASS_NAMES,
    V5_GATE_A_QUEUE_MANIFEST_KIND,
    V5_VERDICT_RECORD_TYPE,
    partition_blind_teacher_passes,
    publish_admissibility_partition_directory,
    publish_blind_teacher_queue_directory,
    publish_v5_gate_a_teacher_queue_directory,
    read_admissibility_partition_report,
    read_blind_teacher_queue_directory,
    read_v5_split_report,
    scan_blind_verdict_directory,
    validate_v5_gate_a_teacher_queue_binding,
)
from .dictionary_index import build_dictionary_index, publish_dictionary_index
from .exporter_requests import (
    ensure_paths_under_root,
    generate_exporter_request_shards,
    generate_exporter_requests,
    publish_exporter_request_shards,
    publish_exporter_requests,
    verify_builder_checkout,
)
from .exporter_shards import read_exporter_output_shards, read_request_shard_directory
from .jawiki_acquisition import AcquisitionError, acquire_jawiki
from .jawiki_preprocess import (
    ExtractorConfig,
    PreprocessingError,
    extract_source_spans,
    load_dictionary_inputs,
)
from .human_audit import (
    apply_audit_responses,
    build_quality_report,
    build_queue_manifest,
    publish_audit_queue,
    publish_audit_application,
    publish_quality_report,
    read_audit_queue,
    read_audit_responses,
    read_queue_manifest,
    select_audit_records,
    validate_queue_manifest,
)
from .manifest import (
    ManifestBlockedError,
    ManifestError,
    load_manifest_document,
    validate_manifest_document,
)
from .splitter import (
    SplitError,
    assign_splits,
    ensure_distinct_paths,
    publish_historical_exclusion_directory,
    publish_split_artifacts,
)
from .research_exporter import validate_export_file
from .reviewer import run_review_server
from .tier_a import (
    TierABlockedError,
    TierAError,
    ensure_distinct_tier_a_paths,
    generate_tier_a_records,
    publish_tier_a_artifacts,
    read_dictionary_index,
    read_dictionary_index_manifest,
    read_source_span_manifest,
    read_source_spans,
    validate_dictionary_index_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate fixed-source metadata and deterministic dataset contracts."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest", help="validate a snapshot manifest")
    manifest_commands = manifest.add_subparsers(dest="manifest_command", required=True)
    validate_manifest_parser = manifest_commands.add_parser("validate")
    validate_manifest_parser.add_argument("path", type=Path)
    validate_manifest_parser.add_argument("--allowed-root", type=Path, required=True)

    contract = commands.add_parser("contract", help="validate versioned JSONL records")
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    validate_contract_parser = contract_commands.add_parser("validate")
    validate_contract_parser.add_argument("path", type=Path)
    validate_export_parser = contract_commands.add_parser(
        "exporter-validate", help="validate research-only converter snapshots"
    )
    validate_export_parser.add_argument("path", type=Path)
    validate_export_parser.add_argument("--manifest", type=Path)

    split = commands.add_parser("split", help="assign unassigned JSONL records")
    split.add_argument("input", type=Path)
    split.add_argument("output", type=Path)
    split.add_argument("--seed", type=int, required=True)
    split.add_argument("--report", type=Path, required=True)
    split.add_argument("--train-ratio", type=float, default=0.8)
    split.add_argument("--dev-ratio", type=float, default=0.1)
    split.add_argument("--final-holdout-ratio", type=float, default=0.1)

    tier_a = commands.add_parser(
        "tier-a", help="assemble verified Tier A records from immutable inputs"
    )
    tier_a.add_argument("source_spans", type=Path)
    tier_a.add_argument("exporter_jsonl", type=Path)
    tier_a.add_argument("output", type=Path)
    tier_a.add_argument("--dictionary-index", type=Path, required=True)
    tier_a.add_argument("--dictionary-manifest", type=Path, required=True)
    tier_a.add_argument("--exporter-manifest", type=Path, required=True)
    tier_a.add_argument("--jawiki-manifest", type=Path, required=True)
    tier_a.add_argument("--source-span-manifest", type=Path, required=True)
    tier_a.add_argument("--allowed-root", type=Path, required=True)
    tier_a.add_argument("--report", type=Path, required=True)

    tier_a_shards = commands.add_parser(
        "tier-a-shards", help="assemble Tier A from a verified sharded top-32 export"
    )
    tier_a_shards.add_argument("source_spans", type=Path)
    tier_a_shards.add_argument("request_directory", type=Path)
    tier_a_shards.add_argument("exporter_directory", type=Path)
    tier_a_shards.add_argument("output", type=Path)
    tier_a_shards.add_argument("--dictionary-index", type=Path, required=True)
    tier_a_shards.add_argument("--dictionary-manifest", type=Path, required=True)
    tier_a_shards.add_argument("--exporter-manifest", type=Path, required=True)
    tier_a_shards.add_argument("--jawiki-manifest", type=Path, required=True)
    tier_a_shards.add_argument("--source-span-manifest", type=Path, required=True)
    tier_a_shards.add_argument("--allowed-root", type=Path, required=True)
    tier_a_shards.add_argument("--report", type=Path, required=True)

    dictionary_index = commands.add_parser(
        "dictionary-index", help="build an exact index from audited category TSVs"
    )
    dictionary_index.add_argument("category_directory", type=Path)
    dictionary_index.add_argument("output", type=Path)
    dictionary_index.add_argument("--audit-report", type=Path, required=True)
    dictionary_index.add_argument("--manifest", type=Path, required=True)
    dictionary_index.add_argument("--indexer-git-sha", required=True)

    acquire = commands.add_parser(
        "jawiki-acquire", help="resume and verify the pinned jawiki artifact"
    )
    acquire.add_argument("manifest", type=Path)
    acquire.add_argument("--allowed-root", type=Path, required=True)
    acquire.add_argument("--output", type=Path, required=True)
    acquire.add_argument("--local-manifest", type=Path, required=True)
    acquire.add_argument("--max-attempts", type=int, default=5)
    acquire.add_argument("--timeout-seconds", type=float, default=60.0)

    preprocess = commands.add_parser(
        "jawiki-preprocess", help="extract deterministic Tier A source spans"
    )
    preprocess.add_argument("dump", type=Path)
    preprocess.add_argument("output", type=Path)
    preprocess.add_argument("--jawiki-manifest", type=Path, required=True)
    preprocess.add_argument("--allowed-root", type=Path, required=True)
    preprocess.add_argument("--dictionary-index", type=Path, required=True)
    preprocess.add_argument("--dictionary-manifest", type=Path, required=True)
    preprocess.add_argument("--report", type=Path, required=True)
    preprocess.add_argument("--extractor-git-sha", required=True)
    preprocess.add_argument("--sample-modulus", type=int, default=1_000)
    preprocess.add_argument("--sample-slots", type=int, default=10)
    preprocess.add_argument("--sample-slot-start", type=int, default=0)
    preprocess.add_argument("--max-records", type=int, default=200_000)
    preprocess.add_argument("--max-records-per-page", type=int, default=32)
    preprocess.add_argument("--max-output-bytes", type=int, default=240 * 1024 * 1024)
    preprocess.add_argument("--min-reading-chars", type=int, default=3)
    preprocess.add_argument("--max-reading-chars", type=int, default=128)
    preprocess.add_argument(
        "--stable-id-exclusion",
        type=Path,
        help="canonical sorted stable-ID JSONL exclusion commitment for Stage 4",
    )

    exporter_requests = commands.add_parser(
        "exporter-requests", help="build a verified research top-32 request batch"
    )
    exporter_requests.add_argument("source_spans", type=Path)
    exporter_requests.add_argument("output", type=Path)
    exporter_requests.add_argument("--dictionary-index", type=Path, required=True)
    exporter_requests.add_argument("--dictionary-manifest", type=Path, required=True)
    exporter_requests.add_argument("--jawiki-manifest", type=Path, required=True)
    exporter_requests.add_argument("--source-span-manifest", type=Path, required=True)
    exporter_requests.add_argument("--allowed-root", type=Path, required=True)
    exporter_requests.add_argument("--report", type=Path, required=True)
    exporter_requests.add_argument("--builder-git-sha", required=True)

    exporter_request_shards = commands.add_parser(
        "exporter-request-shards",
        help="build a verified directory of bounded research top-32 request shards",
    )
    exporter_request_shards.add_argument("source_spans", type=Path)
    exporter_request_shards.add_argument("output_directory", type=Path)
    exporter_request_shards.add_argument("--dictionary-index", type=Path, required=True)
    exporter_request_shards.add_argument("--dictionary-manifest", type=Path, required=True)
    exporter_request_shards.add_argument("--jawiki-manifest", type=Path, required=True)
    exporter_request_shards.add_argument("--source-span-manifest", type=Path, required=True)
    exporter_request_shards.add_argument("--allowed-root", type=Path, required=True)
    exporter_request_shards.add_argument("--builder-git-sha", required=True)
    exporter_request_shards.add_argument("--shard-size", type=int, default=4096)

    human_audit = commands.add_parser("human-audit", help="create and evaluate Tier A reviews")
    human_audit_commands = human_audit.add_subparsers(
        dest="human_audit_command", required=True
    )
    audit_queue = human_audit_commands.add_parser("queue", help="create a review queue")
    audit_queue.add_argument("input", type=Path)
    audit_queue.add_argument("output", type=Path)
    audit_queue.add_argument("--manifest", type=Path, required=True)
    audit_queue.add_argument("--seed", type=int, required=True)
    audit_queue.add_argument("--minimum-sample-size", type=int, default=1000)
    audit_serve = human_audit_commands.add_parser(
        "serve", help="run the loopback-only human review interface"
    )
    audit_serve.add_argument("queue", type=Path)
    audit_serve.add_argument("responses", type=Path)
    audit_serve.add_argument("--queue-manifest", type=Path, required=True)
    audit_serve.add_argument("--reviewer-id", required=True)
    audit_serve.add_argument(
        "--reviewer-kind", choices=("human", "ai_teacher"), required=True
    )
    audit_serve.add_argument("--port", type=int, default=8765)
    audit_report = human_audit_commands.add_parser(
        "report", help="calculate the provenance-aware Wilson quality gate"
    )
    audit_report.add_argument("queue", type=Path)
    audit_report.add_argument("responses", type=Path)
    audit_report.add_argument("output", type=Path)
    audit_report.add_argument("--queue-manifest", type=Path, required=True)
    audit_report.add_argument("--minimum-completed", type=int, default=1000)
    audit_report.add_argument("--minimum-final-holdout-valid", type=int, default=3000)
    audit_report.add_argument(
        "--allow-ai-teacher",
        action="store_true",
        help="owner-authorized policy override; remains distinct from a human audit",
    )
    audit_apply = human_audit_commands.add_parser(
        "apply", help="apply review outcomes to a fail-closed training dataset"
    )
    audit_apply.add_argument("input", type=Path)
    audit_apply.add_argument("queue", type=Path)
    audit_apply.add_argument("responses", type=Path)
    audit_apply.add_argument("output", type=Path)
    audit_apply.add_argument("--queue-manifest", type=Path, required=True)
    audit_apply.add_argument("--report", type=Path, required=True)

    corpus_v4 = commands.add_parser(
        "corpus-v4", help="run the fail-closed corpus-v4 teacher cascade"
    )
    corpus_v4_commands = corpus_v4.add_subparsers(
        dest="corpus_v4_command", required=True
    )
    v4_preflight = corpus_v4_commands.add_parser(
        "preflight", help="validate every pinned v4 input before screening"
    )
    v4_preflight.add_argument("dataset", type=Path)
    v4_preflight.add_argument("--source-spans", type=Path, required=True)
    v4_preflight.add_argument("--source-span-manifest", type=Path, required=True)
    v4_preflight.add_argument("--jawiki-manifest", type=Path, required=True)
    v4_preflight.add_argument("--dictionary-index", type=Path, required=True)
    v4_preflight.add_argument("--dictionary-manifest", type=Path, required=True)
    v4_preflight.add_argument("--exporter-manifest", type=Path, required=True)
    v4_preflight.add_argument("--v3-audit-queue", type=Path, required=True)
    v4_preflight.add_argument("--v3-audit-manifest", type=Path, required=True)
    v4_preflight.add_argument("--v3-audit-responses", type=Path, required=True)
    v4_preflight.add_argument("--handoff-directory", type=Path, required=True)
    v4_preflight.add_argument("--allowed-root", type=Path, required=True)

    v4_stage0 = corpus_v4_commands.add_parser(
        "stage0-analyze", help="measure cleaner probes and the adopted v4 rule"
    )
    v4_stage0.add_argument("dataset", type=Path)
    v4_stage0.add_argument("output", type=Path)
    v4_stage0.add_argument("--dev-batches", type=Path, required=True)
    v4_stage0.add_argument("--sol-verdicts", type=Path, required=True)

    v4_stage1 = corpus_v4_commands.add_parser(
        "stage1-queue", help="publish the immutable full-corpus screening queue"
    )
    v4_stage1.add_argument("dataset", type=Path)
    v4_stage1.add_argument("output_directory", type=Path)
    v4_stage1.add_argument("--batch-size", type=int, default=40)

    v4_gate_a_queue = corpus_v4_commands.add_parser(
        "gate-a-queue", help="publish the owner-authorized Gate-A teacher queue"
    )
    v4_gate_a_queue.add_argument("queue", type=Path)
    v4_gate_a_queue.add_argument("output_directory", type=Path)
    v4_gate_a_queue.add_argument("--queue-manifest", type=Path, required=True)
    v4_gate_a_queue.add_argument("--batch-size", type=int, default=40)

    v4_gate_a_finalize = corpus_v4_commands.add_parser(
        "gate-a-finalize", help="finalize complete Gate-A teacher evidence"
    )
    v4_gate_a_finalize.add_argument("queue", type=Path)
    v4_gate_a_finalize.add_argument("teacher_queue_directory", type=Path)
    v4_gate_a_finalize.add_argument("verdict_directory", type=Path)
    v4_gate_a_finalize.add_argument("responses", type=Path)
    v4_gate_a_finalize.add_argument("report", type=Path)
    v4_gate_a_finalize.add_argument("--queue-manifest", type=Path, required=True)
    v4_gate_a_finalize.add_argument("--reviewed-at", required=True)
    v4_gate_a_finalize.add_argument("--allow-ai-teacher", action="store_true")

    v4_status = corpus_v4_commands.add_parser(
        "verdict-status", help="validate completed verdict batches and report pending counts"
    )
    v4_status.add_argument("queue_directory", type=Path)
    v4_status.add_argument("verdict_directory", type=Path)

    v4_stage2 = corpus_v4_commands.add_parser(
        "stage2-queue", help="publish the fresh note-free adjudication queue"
    )
    v4_stage2.add_argument("stage1_queue_directory", type=Path)
    v4_stage2.add_argument("stage1_verdict_directory", type=Path)
    v4_stage2.add_argument("output_directory", type=Path)
    v4_stage2.add_argument("--batch-size", type=int, default=40)

    v4_partition = corpus_v4_commands.add_parser(
        "partition", help="publish retained, excluded, and ambiguous stable-ID buckets"
    )
    v4_partition.add_argument("dataset", type=Path)
    v4_partition.add_argument("stage1_queue_directory", type=Path)
    v4_partition.add_argument("stage1_verdict_directory", type=Path)
    v4_partition.add_argument("stage2_queue_directory", type=Path)
    v4_partition.add_argument("stage2_verdict_directory", type=Path)
    v4_partition.add_argument("output_directory", type=Path)
    v4_partition.add_argument("--opus-dev-batches", type=Path, required=True)
    v4_partition.add_argument("--opus-dev-verdicts", type=Path, required=True)
    v4_partition.add_argument("--v3-audit-responses", type=Path, required=True)

    v4_calibration = corpus_v4_commands.add_parser(
        "calibration-queue", help="prepare only the owner calibration queue"
    )
    v4_calibration.add_argument("dataset", type=Path)
    v4_calibration.add_argument("stage1_queue_directory", type=Path)
    v4_calibration.add_argument("stage1_verdict_directory", type=Path)
    v4_calibration.add_argument("stage2_queue_directory", type=Path)
    v4_calibration.add_argument("stage2_verdict_directory", type=Path)
    v4_calibration.add_argument("output", type=Path)
    v4_calibration.add_argument("--manifest", type=Path, required=True)
    v4_calibration.add_argument("--handoff-directory", type=Path, required=True)
    v4_calibration.add_argument("--seed", type=int, default=CALIBRATION_SEED)

    corpus_v5 = commands.add_parser(
        "corpus-v5", help="run the fail-closed symmetric blind teacher screen"
    )
    corpus_v5_commands = corpus_v5.add_subparsers(
        dest="corpus_v5_command", required=True
    )
    v5_queue = corpus_v5_commands.add_parser(
        "queue", help="publish one immutable full-corpus blind-pass queue"
    )
    v5_queue.add_argument("dataset", type=Path)
    v5_queue.add_argument("output_directory", type=Path)
    v5_queue.add_argument("--pass-name", choices=PASS_NAMES, required=True)
    v5_queue.add_argument("--reviewer-id", required=True)
    v5_queue.add_argument("--batch-size", type=int, default=40)

    v5_status = corpus_v5_commands.add_parser(
        "verdict-status", help="validate verdict batches and report aggregate progress"
    )
    v5_status.add_argument("queue_directory", type=Path)
    v5_status.add_argument("verdict_directory", type=Path)

    v5_partition = corpus_v5_commands.add_parser(
        "partition", help="publish immutable buckets after two complete blind passes"
    )
    v5_partition.add_argument("dataset", type=Path)
    v5_partition.add_argument("first_queue_directory", type=Path)
    v5_partition.add_argument("first_verdict_directory", type=Path)
    v5_partition.add_argument("confirmation_queue_directory", type=Path)
    v5_partition.add_argument("confirmation_verdict_directory", type=Path)
    v5_partition.add_argument("output_directory", type=Path)

    v5_gate_a_queue = corpus_v5_commands.add_parser(
        "gate-a-queue", help="publish a fresh partition-bound Gate-A teacher queue"
    )
    v5_gate_a_queue.add_argument("queue", type=Path)
    v5_gate_a_queue.add_argument("output_directory", type=Path)
    v5_gate_a_queue.add_argument("--partition-report", type=Path, required=True)
    v5_gate_a_queue.add_argument("--partition-eligible", type=Path, required=True)
    v5_gate_a_queue.add_argument("--split-dataset", type=Path, required=True)
    v5_gate_a_queue.add_argument("--split-report", type=Path, required=True)
    v5_gate_a_queue.add_argument("--queue-manifest", type=Path, required=True)
    v5_gate_a_queue.add_argument("--reviewer-id", required=True)
    v5_gate_a_queue.add_argument("--batch-size", type=int, default=40)

    v5_gate_a_finalize = corpus_v5_commands.add_parser(
        "gate-a-finalize", help="finalize complete partition-bound Gate-A evidence"
    )
    v5_gate_a_finalize.add_argument("queue", type=Path)
    v5_gate_a_finalize.add_argument("teacher_queue_directory", type=Path)
    v5_gate_a_finalize.add_argument("verdict_directory", type=Path)
    v5_gate_a_finalize.add_argument("responses", type=Path)
    v5_gate_a_finalize.add_argument("report", type=Path)
    v5_gate_a_finalize.add_argument("--partition-report", type=Path, required=True)
    v5_gate_a_finalize.add_argument("--partition-eligible", type=Path, required=True)
    v5_gate_a_finalize.add_argument("--split-dataset", type=Path, required=True)
    v5_gate_a_finalize.add_argument("--split-report", type=Path, required=True)
    v5_gate_a_finalize.add_argument("--queue-manifest", type=Path, required=True)
    v5_gate_a_finalize.add_argument("--reviewed-at", required=True)
    v5_gate_a_finalize.add_argument("--allow-ai-teacher", action="store_true")

    v5_historical_exclude = corpus_v5_commands.add_parser(
        "historical-exclude",
        help="publish immutable historical-component exclusion evidence",
    )
    v5_historical_exclude.add_argument("historical_dataset", type=Path)
    v5_historical_exclude.add_argument("candidate_dataset", type=Path)
    v5_historical_exclude.add_argument("output_directory", type=Path)
    v5_historical_exclude.add_argument(
        "--expected-historical-record-count", type=int, required=True
    )
    v5_historical_exclude.add_argument(
        "--expected-historical-content-sha256", required=True
    )
    v5_historical_exclude.add_argument(
        "--expected-candidate-record-count", type=int, required=True
    )
    v5_historical_exclude.add_argument(
        "--expected-candidate-content-sha256", required=True
    )
    v5_historical_exclude.add_argument("--near-duplicate-threshold", type=float, default=0.8)

    return parser


def _run(arguments: argparse.Namespace) -> int:
    if arguments.command == "manifest":
        document = load_manifest_document(arguments.path)
        validated = validate_manifest_document(document, arguments.allowed_root)
        print(
            json.dumps(
                {
                    "status": validated["status"],
                    "manifest_kind": validated["manifest_kind"],
                    "snapshot_date": validated["snapshot_date"],
                    "local_sha256": validated["local_sha256"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "contract":
        if arguments.contract_command == "exporter-validate":
            records, content_sha256 = validate_export_file(
                arguments.path,
                manifest_path=arguments.manifest,
            )
            print(
                json.dumps(
                    {
                        "status": "validated",
                        "record_count": len(records),
                        "content_sha256": content_sha256,
                    },
                    sort_keys=True,
                )
            )
            return 0
        records = read_jsonl(arguments.path)
        payload = canonical_jsonl_bytes(records)
        print(
            json.dumps(
                {
                    "status": "validated",
                    "record_count": len(records),
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "corpus-v4":
        if arguments.corpus_v4_command == "preflight":
            report = preflight_v4_inputs(
                dataset_path=arguments.dataset,
                source_spans_path=arguments.source_spans,
                source_span_manifest_path=arguments.source_span_manifest,
                jawiki_manifest_path=arguments.jawiki_manifest,
                dictionary_index_path=arguments.dictionary_index,
                dictionary_manifest_path=arguments.dictionary_manifest,
                exporter_manifest_path=arguments.exporter_manifest,
                v3_audit_queue_path=arguments.v3_audit_queue,
                v3_audit_manifest_path=arguments.v3_audit_manifest,
                v3_audit_responses_path=arguments.v3_audit_responses,
                handoff_directory=arguments.handoff_directory,
                allowed_root=arguments.allowed_root,
            )
            print(json.dumps(report, sort_keys=True))
            return 0

        if arguments.corpus_v4_command == "stage0-analyze":
            if arguments.output.exists():
                raise TierAError("corpus v4: Stage 0 report already exists and is immutable")
            if not arguments.output.parent.is_dir():
                raise TierAError("corpus v4: Stage 0 report parent directory is missing")
            records = read_jsonl(arguments.dataset)
            dev_batches = read_handoff_batches(arguments.dev_batches)
            sol_payloads, pending = read_handoff_verdict_directory(
                dev_batches, arguments.sol_verdicts
            )
            if pending:
                raise TierAError("corpus v4: Stage 0 requires complete Sol dev verdicts")
            dev_items = [item for batch in dev_batches for item in batch["items"]]
            dev_report = analyze_stage0_dev_rules(
                dev_items, flatten_handoff_verdicts(dev_batches, sol_payloads)
            )
            corpus_report = stage0_probe_report(records)
            report = {
                "schema_version": 1,
                "report_kind": "tier_a_v4_stage0",
                "dev_rule_analysis": dev_report,
                "corpus_probe_analysis": corpus_report,
                "adopted_rule_hit_count": len(stage0_deterministic_hit_ids(records)),
                "raw_text_in_report": False,
            }
            write_bytes_atomic(
                arguments.output, canonical_json_bytes(report) + b"\n"
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": corpus_report["input_record_count"],
                        "adopted_rule_hit_count": report["adopted_rule_hit_count"],
                        "report_sha256": hashlib.sha256(
                            canonical_json_bytes(report) + b"\n"
                        ).hexdigest(),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v4_command == "stage1-queue":
            batches = build_teacher_batches(
                read_jsonl(arguments.dataset), batch_size=arguments.batch_size
            )
            manifest = publish_teacher_queue_directory(
                arguments.output_directory,
                batches,
                stage="stage1",
                reviewer_kind="ai_teacher",
                reviewer_id=SCREEN_REVIEWER_ID,
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": manifest["record_count"],
                        "batch_count": manifest["batch_count"],
                        "content_sha256": manifest["content_sha256"],
                        "reviewer_kind": manifest["reviewer_kind"],
                        "reviewer_id": manifest["reviewer_id"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v4_command == "gate-a-queue":
            ensure_distinct_tier_a_paths(
                {
                    "queue": arguments.queue,
                    "queue_manifest": arguments.queue_manifest,
                    "output_directory": arguments.output_directory,
                }
            )
            queue = read_audit_queue(arguments.queue)
            queue_manifest = read_queue_manifest(arguments.queue_manifest)
            validate_queue_manifest(queue_manifest, queue)
            batches = build_gate_a_teacher_batches(
                queue, batch_size=arguments.batch_size
            )
            manifest = publish_teacher_queue_directory(
                arguments.output_directory,
                batches,
                stage="gate_a",
                reviewer_kind="ai_teacher",
                reviewer_id=GATE_A_REVIEWER_ID,
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": manifest["record_count"],
                        "batch_count": manifest["batch_count"],
                        "content_sha256": manifest["content_sha256"],
                        "reviewer_kind": manifest["reviewer_kind"],
                        "reviewer_id": manifest["reviewer_id"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v4_command == "gate-a-finalize":
            ensure_distinct_tier_a_paths(
                {
                    "queue": arguments.queue,
                    "queue_manifest": arguments.queue_manifest,
                    "teacher_queue_directory": arguments.teacher_queue_directory,
                    "verdict_directory": arguments.verdict_directory,
                    "responses": arguments.responses,
                    "report": arguments.report,
                }
            )
            if not arguments.allow_ai_teacher:
                raise TierAError(
                    "corpus v4: Gate-A AI teacher finalization requires explicit owner authorization"
                )
            queue = read_audit_queue(arguments.queue)
            queue_manifest = read_queue_manifest(arguments.queue_manifest)
            validate_queue_manifest(queue_manifest, queue)
            teacher_batches, teacher_manifest = read_teacher_queue_directory(
                arguments.teacher_queue_directory
            )
            teacher_batches = validate_gate_a_teacher_queue_binding(
                queue, teacher_batches, teacher_manifest
            )
            verdicts, pending = scan_verdict_directory(
                arguments.teacher_queue_directory, arguments.verdict_directory
            )
            if pending:
                raise TierAError("corpus v4: Gate-A teacher verdicts are incomplete")
            responses = finalize_gate_a_teacher_responses(
                teacher_batches, verdicts, reviewed_at=arguments.reviewed_at
            )
            response_sha, report_sha, report = publish_gate_a_teacher_evidence(
                arguments.responses,
                arguments.report,
                queue,
                responses,
            )
            print(
                json.dumps(
                    {
                        "status": "finalized",
                        "completed_record_count": report["completed_record_count"],
                        "pending_record_count": report["pending_record_count"],
                        "valid_record_count": report["valid_record_count"],
                        "invalid_record_count": report["invalid_record_count"],
                        "point_precision": report["point_precision"],
                        "wilson_95_lower_bound": report["wilson_95_lower_bound"],
                        "gate_a_human_audit_pass": report["gate_a_human_audit_pass"],
                        "gate_a_owner_authorized_audit_pass": report[
                            "gate_a_owner_authorized_audit_pass"
                        ],
                        "response_sha256": response_sha,
                        "report_sha256": report_sha,
                        "reviewer_kind": "ai_teacher",
                        "reviewer_id": GATE_A_REVIEWER_ID,
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v4_command == "verdict-status":
            completed, pending = scan_verdict_directory(
                arguments.queue_directory, arguments.verdict_directory
            )
            verdict_counts: dict[str, int] = {}
            for payload in completed.values():
                for entry in payload["verdicts"]:
                    verdict_counts[entry["verdict"]] = (
                        verdict_counts.get(entry["verdict"], 0) + 1
                    )
            print(
                json.dumps(
                    {
                        "status": "complete" if not pending else "resumable",
                        "completed_batch_count": len(completed),
                        "pending_batch_count": len(pending),
                        "verdict_counts": dict(sorted(verdict_counts.items())),
                        "verdict_state_content_sha256": teacher_verdict_state_sha256(
                            completed
                        ),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v4_command == "stage2-queue":
            stage1_batches, stage1_manifest = read_teacher_queue_directory(
                arguments.stage1_queue_directory
            )
            if (
                stage1_manifest["stage"] != "stage1"
                or stage1_manifest["reviewer_kind"] != "ai_teacher"
                or stage1_manifest["reviewer_id"] != SCREEN_REVIEWER_ID
            ):
                raise TierAError("corpus v4: Stage 1 queue provenance is invalid")
            stage1_verdicts, pending = scan_verdict_directory(
                arguments.stage1_queue_directory,
                arguments.stage1_verdict_directory,
            )
            if pending:
                raise TierAError("corpus v4: Stage 1 verdicts are incomplete")
            stage2_batches = build_stage2_batches(
                stage1_batches,
                stage1_verdicts,
                batch_size=arguments.batch_size,
            )
            manifest = publish_teacher_queue_directory(
                arguments.output_directory,
                stage2_batches,
                stage="stage2",
                reviewer_kind="ai_teacher",
                reviewer_id=ADJUDICATION_REVIEWER_ID,
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": manifest["record_count"],
                        "batch_count": manifest["batch_count"],
                        "content_sha256": manifest["content_sha256"],
                        "reviewer_kind": manifest["reviewer_kind"],
                        "reviewer_id": manifest["reviewer_id"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        stage1_batches, stage1_manifest = read_teacher_queue_directory(
            arguments.stage1_queue_directory
        )
        stage2_batches, stage2_manifest = read_teacher_queue_directory(
            arguments.stage2_queue_directory
        )
        if (
            stage1_manifest["stage"] != "stage1"
            or stage1_manifest["reviewer_id"] != SCREEN_REVIEWER_ID
            or stage2_manifest["stage"] != "stage2"
            or stage2_manifest["reviewer_id"] != ADJUDICATION_REVIEWER_ID
        ):
            raise TierAError("corpus v4: teacher queue provenance is invalid")
        stage1_payloads, stage1_pending = scan_verdict_directory(
            arguments.stage1_queue_directory, arguments.stage1_verdict_directory
        )
        stage2_payloads, stage2_pending = scan_verdict_directory(
            arguments.stage2_queue_directory, arguments.stage2_verdict_directory
        )
        if stage1_pending or stage2_pending:
            raise TierAError("corpus v4: teacher verdicts are incomplete")
        records = read_jsonl(arguments.dataset)

        if arguments.corpus_v4_command == "partition":
            opus_batches = read_handoff_batches(arguments.opus_dev_batches)
            missing = (
                (15,)
                if not (arguments.opus_dev_verdicts / "verdicts-015.json").exists()
                else ()
            )
            opus_payloads, _ = read_handoff_verdict_directory(
                opus_batches,
                arguments.opus_dev_verdicts,
                allowed_missing_indexes=missing,
            )
            opus_verdicts: dict[str, str] = {}
            for index, payload in opus_payloads.items():
                for item, entry in zip(
                    opus_batches[index]["items"], payload["verdicts"], strict=True
                ):
                    opus_verdicts[item["stable_id"]] = entry["verdict"]
            external = merge_external_verdict_maps(
                opus_verdicts,
                audit_response_verdict_map(
                    read_audit_responses(arguments.v3_audit_responses)
                ),
            )
            partition, report = partition_stage2(
                records,
                stage1_batches,
                stage1_payloads,
                stage2_batches,
                stage2_payloads,
                external_verdicts=external,
                stage0_hit_ids=stage0_deterministic_hit_ids(records),
            )
            published = publish_partition_directory(
                arguments.output_directory, partition, report
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "input_record_count": published["input_record_count"],
                        "retained_record_count": published["retained_record_count"],
                        "excluded_record_count": published["excluded_record_count"],
                        "ambiguous_quarantine_record_count": published[
                            "ambiguous_quarantine_record_count"
                        ],
                        "stage4_exclusion_count": published[
                            "stage4_stable_id_exclusion"
                        ]["count"],
                        "stage4_exclusion_sha256": published[
                            "stage4_stable_id_exclusion"
                        ]["content_sha256"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v4_command == "calibration-queue":
            disagreements = discover_teacher_disagreements(
                arguments.handoff_directory
            )
            stage1_by_id = flatten_teacher_verdicts(
                stage1_batches,
                stage1_payloads,
                reviewer_id=SCREEN_REVIEWER_ID,
            )
            stage2_by_id = flatten_teacher_verdicts(
                stage2_batches,
                stage2_payloads,
                reviewer_id=ADJUDICATION_REVIEWER_ID,
            )
            manifest, queue_sha, manifest_sha = publish_stage3_calibration_queue(
                arguments.output,
                arguments.manifest,
                records,
                disagreements,
                stage1_by_id,
                stage2_by_id,
                seed=arguments.seed,
            )
            print(
                json.dumps(
                    {
                        "status": "prepared_for_owner",
                        "record_count": manifest["record_count"],
                        "disagreement_record_count": manifest[
                            "disagreement_record_count"
                        ],
                        "one_pass_eligible_record_count": manifest[
                            "one_pass_eligible_record_count"
                        ],
                        "one_pass_selected_record_count": manifest[
                            "one_pass_selected_record_count"
                        ],
                        "content_sha256": queue_sha,
                        "manifest_sha256": manifest_sha,
                    },
                    sort_keys=True,
                )
            )
            return 0

        raise TierAError("corpus v4: unsupported subcommand")

    if arguments.command == "corpus-v5":
        if arguments.corpus_v5_command == "queue":
            manifest = publish_blind_teacher_queue_directory(
                arguments.output_directory,
                read_jsonl(arguments.dataset, require_split=False),
                pass_name=arguments.pass_name,
                reviewer_id=arguments.reviewer_id,
                batch_size=arguments.batch_size,
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": manifest["record_count"],
                        "batch_count": manifest["batch_count"],
                        "content_sha256": manifest["content_sha256"],
                        "source_dataset_content_sha256": manifest[
                            "source_dataset_content_sha256"
                        ],
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v5_command == "verdict-status":
            completed, pending = scan_blind_verdict_directory(
                arguments.queue_directory, arguments.verdict_directory
            )
            verdict_counts: dict[str, int] = {}
            for payload in completed.values():
                for entry in payload["verdicts"]:
                    verdict_counts[entry["verdict"]] = (
                        verdict_counts.get(entry["verdict"], 0) + 1
                    )
            print(
                json.dumps(
                    {
                        "status": "complete" if not pending else "resumable",
                        "completed_batch_count": len(completed),
                        "pending_batch_count": len(pending),
                        "completed_record_count": sum(
                            len(payload["verdicts"]) for payload in completed.values()
                        ),
                        "verdict_counts": dict(sorted(verdict_counts.items())),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v5_command == "partition":
            first_batches, first_manifest = read_blind_teacher_queue_directory(
                arguments.first_queue_directory
            )
            (
                confirmation_batches,
                confirmation_manifest,
            ) = read_blind_teacher_queue_directory(arguments.confirmation_queue_directory)
            first_verdicts, first_pending = scan_blind_verdict_directory(
                arguments.first_queue_directory, arguments.first_verdict_directory
            )
            confirmation_verdicts, confirmation_pending = scan_blind_verdict_directory(
                arguments.confirmation_queue_directory,
                arguments.confirmation_verdict_directory,
            )
            if first_pending or confirmation_pending:
                raise TierAError("corpus v5: blind teacher verdicts are incomplete")
            buckets, report = partition_blind_teacher_passes(
                read_jsonl(arguments.dataset, require_split=False),
                first_batches,
                first_manifest,
                first_verdicts,
                confirmation_batches,
                confirmation_manifest,
                confirmation_verdicts,
            )
            publish_admissibility_partition_directory(
                arguments.output_directory, buckets, report
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "input_record_count": report["source_dataset_record_count"],
                        "bucket_record_counts": {
                            name: summary["record_count"]
                            for name, summary in sorted(report["buckets"].items())
                        },
                        "report_content_sha256": hashlib.sha256(
                            canonical_json_bytes(report) + b"\n"
                        ).hexdigest(),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v5_command == "gate-a-queue":
            ensure_distinct_tier_a_paths(
                {
                    "queue": arguments.queue,
                    "queue_manifest": arguments.queue_manifest,
                    "partition_report": arguments.partition_report,
                    "partition_eligible": arguments.partition_eligible,
                    "split_dataset": arguments.split_dataset,
                    "split_report": arguments.split_report,
                    "output_directory": arguments.output_directory,
                }
            )
            queue = read_audit_queue(arguments.queue)
            queue_manifest = read_queue_manifest(arguments.queue_manifest)
            validate_queue_manifest(queue_manifest, queue)
            partition_report = read_admissibility_partition_report(
                arguments.partition_report
            )
            partition_eligible = read_jsonl(
                arguments.partition_eligible, require_split=False
            )
            split_dataset = read_jsonl(arguments.split_dataset, require_split=True)
            split_report = read_v5_split_report(arguments.split_report)
            manifest = publish_v5_gate_a_teacher_queue_directory(
                arguments.output_directory,
                partition_eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                partition_report,
                reviewer_id=arguments.reviewer_id,
                batch_size=arguments.batch_size,
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": manifest["record_count"],
                        "batch_count": manifest["batch_count"],
                        "content_sha256": manifest["content_sha256"],
                        "reviewer_kind": manifest["reviewer_kind"],
                        "reviewer_id": manifest["reviewer_id"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v5_command == "gate-a-finalize":
            ensure_distinct_tier_a_paths(
                {
                    "queue": arguments.queue,
                    "queue_manifest": arguments.queue_manifest,
                    "partition_report": arguments.partition_report,
                    "partition_eligible": arguments.partition_eligible,
                    "split_dataset": arguments.split_dataset,
                    "split_report": arguments.split_report,
                    "teacher_queue_directory": arguments.teacher_queue_directory,
                    "verdict_directory": arguments.verdict_directory,
                    "responses": arguments.responses,
                    "report": arguments.report,
                }
            )
            if not arguments.allow_ai_teacher:
                raise TierAError(
                    "corpus v5: Gate-A AI teacher finalization requires explicit owner authorization"
                )
            queue = read_audit_queue(arguments.queue)
            queue_manifest = read_queue_manifest(arguments.queue_manifest)
            validate_queue_manifest(queue_manifest, queue)
            partition_report = read_admissibility_partition_report(
                arguments.partition_report
            )
            partition_eligible = read_jsonl(
                arguments.partition_eligible, require_split=False
            )
            split_dataset = read_jsonl(arguments.split_dataset, require_split=True)
            split_report = read_v5_split_report(arguments.split_report)
            teacher_batches, teacher_manifest = read_teacher_queue_directory(
                arguments.teacher_queue_directory,
                expected_manifest_kind=V5_GATE_A_QUEUE_MANIFEST_KIND,
                require_source_provenance=True,
                require_canonical_bytes=True,
            )
            teacher_batches, reviewer_id = validate_v5_gate_a_teacher_queue_binding(
                partition_eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                teacher_batches,
                teacher_manifest,
                partition_report,
            )
            verdicts, pending = scan_verdict_directory(
                arguments.teacher_queue_directory,
                arguments.verdict_directory,
                expected_manifest_kind=V5_GATE_A_QUEUE_MANIFEST_KIND,
                require_source_provenance=True,
                require_canonical_bytes=True,
                expected_verdict_record_type=V5_VERDICT_RECORD_TYPE,
            )
            if pending:
                raise TierAError("corpus v5: Gate-A teacher verdicts are incomplete")
            responses = finalize_gate_a_teacher_responses(
                teacher_batches,
                verdicts,
                reviewed_at=arguments.reviewed_at,
                reviewer_id=reviewer_id,
                verdict_record_type=V5_VERDICT_RECORD_TYPE,
            )
            response_sha, report_sha, report = publish_gate_a_teacher_evidence(
                arguments.responses,
                arguments.report,
                queue,
                responses,
                reviewer_id=reviewer_id,
            )
            print(
                json.dumps(
                    {
                        "status": "finalized",
                        "completed_record_count": report["completed_record_count"],
                        "pending_record_count": report["pending_record_count"],
                        "valid_record_count": report["valid_record_count"],
                        "invalid_record_count": report["invalid_record_count"],
                        "point_precision": report["point_precision"],
                        "wilson_95_lower_bound": report["wilson_95_lower_bound"],
                        "gate_a_human_audit_pass": report["gate_a_human_audit_pass"],
                        "gate_a_owner_authorized_audit_pass": report[
                            "gate_a_owner_authorized_audit_pass"
                        ],
                        "response_sha256": response_sha,
                        "report_sha256": report_sha,
                        "reviewer_kind": "ai_teacher",
                        "reviewer_id": reviewer_id,
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.corpus_v5_command == "historical-exclude":
            report = publish_historical_exclusion_directory(
                arguments.output_directory,
                read_jsonl(arguments.historical_dataset, require_split=False),
                read_jsonl(arguments.candidate_dataset, require_split=False),
                expected_historical_record_count=arguments.expected_historical_record_count,
                expected_historical_content_sha256=arguments.expected_historical_content_sha256,
                expected_candidate_record_count=arguments.expected_candidate_record_count,
                expected_candidate_content_sha256=arguments.expected_candidate_content_sha256,
                near_duplicate_threshold=arguments.near_duplicate_threshold,
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "historical_record_count": report["historical_input"]["count"],
                        "candidate_record_count": report["candidate_input"]["count"],
                        "eligible_record_count": report["eligible"]["count"],
                        "excluded_record_count": report["excluded"]["count"],
                        "report_content_sha256": hashlib.sha256(
                            canonical_json_bytes(report) + b"\n"
                        ).hexdigest(),
                    },
                    sort_keys=True,
                )
            )
            return 0

        raise TierAError("corpus v5: unsupported subcommand")

    if arguments.command == "human-audit":
        if arguments.human_audit_command == "serve":
            ensure_distinct_tier_a_paths(
                {
                    "queue": arguments.queue,
                    "responses": arguments.responses,
                    "queue_manifest": arguments.queue_manifest,
                }
            )
            run_review_server(
                arguments.queue,
                arguments.queue_manifest,
                arguments.responses,
                arguments.reviewer_id,
                arguments.reviewer_kind,
                port=arguments.port,
            )
            return 0
        if arguments.human_audit_command == "queue":
            ensure_distinct_tier_a_paths(
                {
                    "input": arguments.input,
                    "output": arguments.output,
                    "manifest": arguments.manifest,
                }
            )
            records = read_jsonl(arguments.input)
            queue = select_audit_records(
                records,
                seed=arguments.seed,
                minimum_sample_size=arguments.minimum_sample_size,
            )
            manifest = build_queue_manifest(
                records,
                queue,
                seed=arguments.seed,
                minimum_sample_size=arguments.minimum_sample_size,
            )
            queue_hash, manifest_hash = publish_audit_queue(
                arguments.output, arguments.manifest, queue, manifest
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": len(queue),
                        "final_holdout_count": manifest["final_holdout_count"],
                        "content_sha256": queue_hash,
                        "manifest_sha256": manifest_hash,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if arguments.human_audit_command == "apply":
            ensure_distinct_tier_a_paths(
                {
                    "input": arguments.input,
                    "queue": arguments.queue,
                    "responses": arguments.responses,
                    "queue_manifest": arguments.queue_manifest,
                    "output": arguments.output,
                    "report": arguments.report,
                }
            )
            queue = read_audit_queue(arguments.queue)
            validate_queue_manifest(read_queue_manifest(arguments.queue_manifest), queue)
            responses = read_audit_responses(arguments.responses)
            records, report = apply_audit_responses(
                read_jsonl(arguments.input), queue, responses
            )
            output_hash, report_hash = publish_audit_application(
                arguments.output, arguments.report, records, report
            )
            print(
                json.dumps(
                    {
                        "status": "applied",
                        "record_count": len(records),
                        "output_sha256": output_hash,
                        "report_sha256": report_hash,
                    },
                    sort_keys=True,
                )
            )
            return 0
        ensure_distinct_tier_a_paths(
            {
                "queue": arguments.queue,
                "responses": arguments.responses,
                "queue_manifest": arguments.queue_manifest,
                "output": arguments.output,
            }
        )
        queue = read_audit_queue(arguments.queue)
        validate_queue_manifest(read_queue_manifest(arguments.queue_manifest), queue)
        responses = read_audit_responses(arguments.responses)
        report = build_quality_report(
            queue,
            responses,
            minimum_completed=arguments.minimum_completed,
            minimum_final_holdout_valid=arguments.minimum_final_holdout_valid,
            allow_ai_teacher=arguments.allow_ai_teacher,
        )
        report_hash = publish_quality_report(arguments.output, report)
        print(
            json.dumps(
                {
                    "status": "evaluated",
                    "completed_record_count": report["completed_record_count"],
                    "gate_a_human_audit_pass": report["gate_a_human_audit_pass"],
                    "gate_a_owner_authorized_audit_pass": report[
                        "gate_a_owner_authorized_audit_pass"
                    ],
                    "report_sha256": report_hash,
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "dictionary-index":
        ensure_distinct_tier_a_paths(
            {
                "audit_report": arguments.audit_report,
                "output": arguments.output,
                "manifest": arguments.manifest,
            }
        )
        category_root = arguments.category_directory.resolve(strict=True)
        for destination in (arguments.output, arguments.manifest):
            if destination.resolve(strict=False).is_relative_to(category_root):
                raise TierAError(
                    "paths: index output and manifest must be outside category sources"
                )
        records, manifest = build_dictionary_index(
            arguments.category_directory,
            arguments.audit_report,
            indexer_git_sha=arguments.indexer_git_sha,
        )
        output_hash, manifest_hash = publish_dictionary_index(
            arguments.output, arguments.manifest, records, manifest
        )
        print(
            json.dumps(
                {
                    "status": "measured",
                    "record_count": len(records),
                    "content_sha256": output_hash,
                    "manifest_sha256": manifest_hash,
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "jawiki-acquire":
        last_reported = -1

        def report_progress(observed: int, expected: int) -> None:
            nonlocal last_reported
            bucket = observed // (256 * 1024 * 1024)
            if bucket != last_reported or observed == expected:
                last_reported = bucket
                print(
                    json.dumps(
                        {"status": "downloading", "bytes": observed, "total_bytes": expected},
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )

        acquired = acquire_jawiki(
            arguments.manifest,
            allowed_root=arguments.allowed_root,
            destination=arguments.output,
            local_manifest_output=arguments.local_manifest,
            max_attempts=arguments.max_attempts,
            timeout_seconds=arguments.timeout_seconds,
            progress=report_progress,
        )
        print(
            json.dumps(
                {
                    "status": acquired["status"],
                    "downloaded": acquired["downloaded"],
                    "byte_size": acquired["byte_size"],
                    "local_sha256": acquired["local_sha256"],
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "jawiki-preprocess":
        root = arguments.allowed_root.resolve(strict=True)
        jawiki_manifest = validate_manifest_document(
            load_manifest_document(arguments.jawiki_manifest), root
        )
        if (
            jawiki_manifest.get("status") != "local_artifact_verified"
            or not isinstance(jawiki_manifest.get("local_path"), str)
        ):
            raise PreprocessingError(
                "a local_artifact_verified jawiki manifest with local_path is required"
            )
        expected_dump = (root / jawiki_manifest["local_path"]).resolve(strict=True)
        supplied_dump = arguments.dump.resolve(strict=True)
        try:
            if not supplied_dump.samefile(expected_dump):
                raise PreprocessingError("dump does not match the local jawiki manifest")
        except OSError as error:
            raise PreprocessingError("dump path identity could not be verified") from error
        dictionary, dictionary_manifest = load_dictionary_inputs(
            arguments.dictionary_index, arguments.dictionary_manifest
        )
        preprocess_paths = {
            "dump": supplied_dump,
            "jawiki_manifest": arguments.jawiki_manifest,
            "dictionary_index": arguments.dictionary_index,
            "dictionary_manifest": arguments.dictionary_manifest,
            "output": arguments.output,
            "report": arguments.report,
        }
        if arguments.stable_id_exclusion is not None:
            preprocess_paths["stable_id_exclusion"] = arguments.stable_id_exclusion
        ensure_distinct_tier_a_paths(preprocess_paths)
        output_hash, report_hash, count = extract_source_spans(
            supplied_dump,
            arguments.output,
            arguments.report,
            jawiki_manifest=jawiki_manifest,
            dictionary_records=dictionary,
            dictionary_manifest=dictionary_manifest,
            extractor_git_sha=arguments.extractor_git_sha,
            config=ExtractorConfig(
                sample_modulus=arguments.sample_modulus,
                sample_slots=arguments.sample_slots,
                sample_slot_start=arguments.sample_slot_start,
                max_records=arguments.max_records,
                max_records_per_page=arguments.max_records_per_page,
                max_output_bytes=arguments.max_output_bytes,
                min_reading_chars=arguments.min_reading_chars,
                max_reading_chars=arguments.max_reading_chars,
            ),
            stable_id_exclusion_path=arguments.stable_id_exclusion,
        )
        print(
            json.dumps(
                {
                    "status": "measured",
                    "record_count": count,
                    "content_sha256": output_hash,
                    "report_sha256": report_hash,
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.command in {"exporter-requests", "exporter-request-shards"}:
        verify_builder_checkout(arguments.builder_git_sha, Path(__file__).resolve().parents[3])
        output_name = (
            "output" if arguments.command == "exporter-requests" else "output_directory"
        )
        output_path = getattr(arguments, output_name)
        request_paths = {
            "source_spans": arguments.source_spans,
            "dictionary_index": arguments.dictionary_index,
            "dictionary_manifest": arguments.dictionary_manifest,
            "jawiki_manifest": arguments.jawiki_manifest,
            "source_span_manifest": arguments.source_span_manifest,
            output_name: output_path,
        }
        if arguments.command == "exporter-requests":
            request_paths["report"] = arguments.report
        ensure_distinct_tier_a_paths(request_paths)
        ensure_paths_under_root(request_paths, arguments.allowed_root)
        jawiki_manifest = validate_manifest_document(
            load_manifest_document(arguments.jawiki_manifest), arguments.allowed_root
        )
        dictionary = read_dictionary_index(arguments.dictionary_index)
        dictionary_manifest = read_dictionary_index_manifest(arguments.dictionary_manifest)
        source_records = read_source_spans(arguments.source_spans)
        source_span_manifest = read_source_span_manifest(arguments.source_span_manifest)
        if arguments.command == "exporter-request-shards":
            shards, manifest = generate_exporter_request_shards(
                source_records,
                dictionary,
                jawiki_manifest=jawiki_manifest,
                dictionary_manifest=dictionary_manifest,
                source_span_manifest=source_span_manifest,
                builder_git_sha=arguments.builder_git_sha,
                shard_size=arguments.shard_size,
            )
            content_hash, manifest_hash = publish_exporter_request_shards(
                arguments.output_directory, shards, manifest
            )
            print(
                json.dumps(
                    {
                        "status": "generated",
                        "record_count": manifest["record_count"],
                        "shard_count": len(shards),
                        "content_sha256": content_hash,
                        "manifest_sha256": manifest_hash,
                    },
                    sort_keys=True,
                )
            )
            return 0
        requests, report = generate_exporter_requests(
            source_records,
            dictionary,
            jawiki_manifest=jawiki_manifest,
            dictionary_manifest=dictionary_manifest,
            source_span_manifest=source_span_manifest,
            builder_git_sha=arguments.builder_git_sha,
        )
        output_hash, report_hash = publish_exporter_requests(
            arguments.output, arguments.report, requests, report
        )
        print(
            json.dumps(
                {
                    "status": "generated",
                    "record_count": len(requests),
                    "content_sha256": output_hash,
                    "report_sha256": report_hash,
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.command in {"tier-a", "tier-a-shards"}:
        tier_a_paths = {
            "source_spans": arguments.source_spans,
            "dictionary_index": arguments.dictionary_index,
            "dictionary_manifest": arguments.dictionary_manifest,
            "exporter_manifest": arguments.exporter_manifest,
            "jawiki_manifest": arguments.jawiki_manifest,
            "source_span_manifest": arguments.source_span_manifest,
            "output": arguments.output,
            "report": arguments.report,
        }
        if arguments.command == "tier-a":
            tier_a_paths["exporter_jsonl"] = arguments.exporter_jsonl
        else:
            tier_a_paths["request_directory"] = arguments.request_directory
            tier_a_paths["exporter_directory"] = arguments.exporter_directory
        ensure_distinct_tier_a_paths(tier_a_paths)
        jawiki_manifest = validate_manifest_document(
            load_manifest_document(arguments.jawiki_manifest), arguments.allowed_root
        )
        if jawiki_manifest.get("status") not in {
            "local_artifact_verified",
            "preprocessing_verified",
        }:
            raise TierABlockedError(
                "jawiki_artifact", "a verified local jawiki artifact is required"
            )
        dictionary = read_dictionary_index(arguments.dictionary_index)
        dictionary_manifest = read_dictionary_index_manifest(
            arguments.dictionary_manifest
        )
        validate_dictionary_index_manifest(dictionary_manifest, dictionary)
        if arguments.command == "tier-a":
            exporter_records, _ = validate_export_file(
                arguments.exporter_jsonl,
                manifest_path=arguments.exporter_manifest,
                require_verified=True,
            )
        else:
            request_shards, _ = read_request_shard_directory(arguments.request_directory)
            exporter_shards, _ = read_exporter_output_shards(
                arguments.exporter_directory,
                request_shards,
                exporter_manifest_path=arguments.exporter_manifest,
            )
            exporter_records = [record for shard in exporter_shards for record in shard]
        records, report = generate_tier_a_records(
            read_source_spans(arguments.source_spans),
            dictionary,
            exporter_records,
            jawiki_manifest=jawiki_manifest,
            dictionary_manifest=dictionary_manifest,
            source_span_manifest=read_source_span_manifest(
                arguments.source_span_manifest
            ),
        )
        output_hash, report_hash = publish_tier_a_artifacts(
            arguments.output, arguments.report, records, report
        )
        print(
            json.dumps(
                {
                    "status": "generated",
                    "record_count": len(records),
                    "content_sha256": output_hash,
                    "report_sha256": report_hash,
                },
                sort_keys=True,
            )
        )
        return 0

    ensure_distinct_paths(arguments.input, arguments.output, arguments.report)
    records = read_jsonl(arguments.input, require_split=False)
    output, report = assign_splits(
        records,
        seed=arguments.seed,
        split_ratios={
            "train": arguments.train_ratio,
            "dev": arguments.dev_ratio,
            "final-holdout": arguments.final_holdout_ratio,
        },
    )
    output_hash, report_hash = publish_split_artifacts(
        arguments.output, arguments.report, output, report
    )
    print(
        json.dumps(
            {
                "status": "split",
                "record_count": len(output),
                "content_sha256": output_hash,
                "report_sha256": report_hash,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(_parser().parse_args(argv))
    except (ManifestBlockedError, TierABlockedError) as error:
        print(
            json.dumps(error.report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        return 3
    except (
        AcquisitionError,
        ContractError,
        ManifestError,
        PreprocessingError,
        SplitError,
        TierAError,
        OSError,
    ) as error:
        print(f"data validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
