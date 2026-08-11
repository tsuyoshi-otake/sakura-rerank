"""Command-line entry point for the data manifest and contract boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .contracts import ContractError, canonical_jsonl_bytes, read_jsonl
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

    split = commands.add_parser("split", help="assign unassigned JSONL records")
    split.add_argument("input", type=Path)
    split.add_argument("output", type=Path)
    split.add_argument("--seed", type=int, required=True)
    split.add_argument("--report", type=Path, required=True)

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
    except ManifestBlockedError as error:
        print(
            json.dumps(error.report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        return 3
    except (ContractError, ManifestError, SplitError, OSError) as error:
        print(f"data validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
