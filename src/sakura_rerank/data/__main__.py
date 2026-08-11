"""Command-line entry point for the data manifest and contract boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .contracts import ContractError, canonical_jsonl_bytes, read_jsonl
from .dictionary_index import build_dictionary_index, publish_dictionary_index
from .jawiki_acquisition import AcquisitionError, acquire_jawiki
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
    read_source_spans,
    require_preprocessing_manifest,
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

    if arguments.command == "tier-a":
        tier_a_paths = {
            "source_spans": arguments.source_spans,
            "exporter_jsonl": arguments.exporter_jsonl,
            "dictionary_index": arguments.dictionary_index,
            "dictionary_manifest": arguments.dictionary_manifest,
            "exporter_manifest": arguments.exporter_manifest,
            "jawiki_manifest": arguments.jawiki_manifest,
            "output": arguments.output,
            "report": arguments.report,
        }
        ensure_distinct_tier_a_paths(tier_a_paths)
        jawiki_manifest = validate_manifest_document(
            load_manifest_document(arguments.jawiki_manifest), arguments.allowed_root
        )
        require_preprocessing_manifest(jawiki_manifest)
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
    output, report = assign_splits(records, seed=arguments.seed)
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
        SplitError,
        TierAError,
        OSError,
    ) as error:
        print(f"data validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
