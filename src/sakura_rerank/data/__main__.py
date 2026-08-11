"""Command-line entry point for the data manifest and contract boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .contracts import ContractError, canonical_jsonl_bytes, read_jsonl
from .dictionary_index import build_dictionary_index, publish_dictionary_index
from .exporter_requests import (
    ensure_paths_under_root,
    generate_exporter_request_shards,
    generate_exporter_requests,
    publish_exporter_request_shards,
    publish_exporter_requests,
)
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
    publish_split_artifacts,
)
from .research_exporter import validate_export_file
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
    preprocess.add_argument("--max-records", type=int, default=200_000)
    preprocess.add_argument("--max-records-per-page", type=int, default=32)
    preprocess.add_argument("--max-output-bytes", type=int, default=240 * 1024 * 1024)

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
    audit_report = human_audit_commands.add_parser(
        "report", help="calculate the human-audit Wilson quality gate"
    )
    audit_report.add_argument("queue", type=Path)
    audit_report.add_argument("responses", type=Path)
    audit_report.add_argument("output", type=Path)
    audit_report.add_argument("--queue-manifest", type=Path, required=True)
    audit_report.add_argument("--minimum-completed", type=int, default=1000)
    audit_report.add_argument("--minimum-final-holdout-valid", type=int, default=3000)
    audit_apply = human_audit_commands.add_parser(
        "apply", help="apply review outcomes to a fail-closed training dataset"
    )
    audit_apply.add_argument("input", type=Path)
    audit_apply.add_argument("queue", type=Path)
    audit_apply.add_argument("responses", type=Path)
    audit_apply.add_argument("output", type=Path)
    audit_apply.add_argument("--queue-manifest", type=Path, required=True)
    audit_apply.add_argument("--report", type=Path, required=True)

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

    if arguments.command == "human-audit":
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
        )
        report_hash = publish_quality_report(arguments.output, report)
        print(
            json.dumps(
                {
                    "status": "evaluated",
                    "completed_record_count": report["completed_record_count"],
                    "gate_a_human_audit_pass": report["gate_a_human_audit_pass"],
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
        ensure_distinct_tier_a_paths(
            {
                "dump": supplied_dump,
                "jawiki_manifest": arguments.jawiki_manifest,
                "dictionary_index": arguments.dictionary_index,
                "dictionary_manifest": arguments.dictionary_manifest,
                "output": arguments.output,
                "report": arguments.report,
            }
        )
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
                max_records=arguments.max_records,
                max_records_per_page=arguments.max_records_per_page,
                max_output_bytes=arguments.max_output_bytes,
            ),
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

    if arguments.command == "tier-a":
        tier_a_paths = {
            "source_spans": arguments.source_spans,
            "exporter_jsonl": arguments.exporter_jsonl,
            "dictionary_index": arguments.dictionary_index,
            "dictionary_manifest": arguments.dictionary_manifest,
            "exporter_manifest": arguments.exporter_manifest,
            "jawiki_manifest": arguments.jawiki_manifest,
            "source_span_manifest": arguments.source_span_manifest,
            "output": arguments.output,
            "report": arguments.report,
        }
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
        exporter_records, _ = validate_export_file(
            arguments.exporter_jsonl,
            manifest_path=arguments.exporter_manifest,
            require_verified=True,
        )
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
