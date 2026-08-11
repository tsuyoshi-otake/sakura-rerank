"""Collect a content-addressed snapshot of the current Sakura Input baseline.

The audit intentionally records metadata, counts, and hashes rather than raw
candidate or corpus text. It has no third-party dependencies and does not modify
the inspected Sakura Input checkout.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .atomic_io import write_bytes_atomic


SCHEMA_VERSION = "sakura-rerank.current-state-audit.v1"
DICTIONARY_MAGIC = b"SKRADIC\0"
DICTIONARY_HEADER = struct.Struct("<8sHHHHIIII")
DICTIONARY_HEADER_LENGTH = 32
SOURCE_PATHS = (
    "crates/sakura-engine/src/long_conversion.rs",
    "crates/sakura-engine/src/dispatch.rs",
    "crates/sakura-neural-worker/src/protocol.rs",
    "crates/sakura-neural-worker/src/scorer.rs",
    "crates/sakura-neural-worker/src/runtime.rs",
    "crates/sakura-neural-worker/src/tokenizer.rs",
    "scripts/build-neural-reranker.ps1",
    "scripts/export-neural-model.py",
)


class AuditError(RuntimeError):
    """The inspected baseline is missing or internally inconsistent."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, *, display_path: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise AuditError(f"required file is missing: {path}")
    return {
        "path": display_path or path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def parse_dictionary_header(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise AuditError(f"compiled dictionary is missing: {path}")
    file_bytes = path.stat().st_size
    with path.open("rb") as source:
        header = source.read(DICTIONARY_HEADER.size)
    if len(header) != DICTIONARY_HEADER.size:
        raise AuditError("compiled dictionary header is truncated")
    (
        magic,
        version,
        header_bytes,
        table_count,
        class_count,
        entry_count,
        node_count,
        image_bytes,
        reserved,
    ) = DICTIONARY_HEADER.unpack(header)
    if magic != DICTIONARY_MAGIC:
        raise AuditError("compiled dictionary has the wrong magic")
    if header_bytes != DICTIONARY_HEADER_LENGTH:
        raise AuditError(f"unexpected dictionary header length: {header_bytes}")
    if image_bytes != file_bytes:
        raise AuditError(
            f"dictionary header/file length mismatch: {image_bytes} != {file_bytes}"
        )
    if reserved != 0:
        raise AuditError("compiled dictionary reserved header field is not zero")
    return {
        "format_version": version,
        "header_bytes": header_bytes,
        "table_count": table_count,
        "class_count": class_count,
        "entry_count": entry_count,
        "node_count": node_count,
        "image_bytes": image_bytes,
    }


def _category_rows(path: Path) -> Iterable[tuple[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = csv.reader(source, delimiter="\t")
        try:
            header = next(rows)
        except StopIteration as error:
            raise AuditError(f"empty category dictionary: {path}") from error
        if header[:2] != ["reading", "surface"]:
            raise AuditError(f"unexpected category header in {path}: {header[:2]}")
        for line_number, row in enumerate(rows, start=2):
            if not row:
                continue
            if len(row) < 2 or not row[0] or not row[1]:
                raise AuditError(f"invalid category row at {path}:{line_number}")
            yield row[0], row[1]


def collect_category_statistics(directory: Path) -> dict[str, Any]:
    files = sorted(directory.glob("*.tsv"), key=lambda path: path.name)
    if not files:
        raise AuditError(f"category dictionaries are missing: {directory}")

    readings: set[str] = set()
    surfaces: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    total_entries = 0
    records: list[dict[str, Any]] = []
    for path in files:
        category_entries = 0
        for reading, surface in _category_rows(path):
            total_entries += 1
            category_entries += 1
            readings.add(reading)
            surfaces.add(surface)
            pairs.add((reading, surface))
        record = file_record(path, display_path=path.name)
        record["entry_count"] = category_entries
        records.append(record)

    return {
        "category_count": len(files),
        "entry_count": total_entries,
        "unique_reading_count": len(readings),
        "unique_surface_count": len(surfaces),
        "unique_reading_surface_pair_count": len(pairs),
        "files": records,
    }


def _run_git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AuditError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    return _run_git(root, *arguments).decode("utf-8", errors="strict").strip()


def collect_git_identity(root: Path) -> dict[str, Any]:
    head = _git_text(root, "rev-parse", "HEAD")
    modified = _git_text(root, "diff", "--name-only", "HEAD").splitlines()
    untracked = _git_text(
        root, "ls-files", "--others", "--exclude-standard"
    ).splitlines()
    remote = _git_text(root, "config", "--get", "remote.origin.url")
    dirty_paths = sorted(set(filter(None, [*modified, *untracked])))
    return {
        "head": head,
        "remote_origin": remote,
        "dirty": bool(dirty_paths),
        "dirty_path_count": len(dirty_paths),
        "dirty_paths": dirty_paths,
    }


def collect_source_fingerprints(root: Path) -> list[dict[str, Any]]:
    records = []
    for relative in SOURCE_PATHS:
        head_bytes = _run_git(root, "show", f"HEAD:{relative}")
        worktree = root / relative
        worktree_record = file_record(worktree, display_path=relative)
        records.append(
            {
                "path": relative,
                "head_bytes": len(head_bytes),
                "head_sha256": sha256_bytes(head_bytes),
                "worktree_bytes": worktree_record["bytes"],
                "worktree_sha256": worktree_record["sha256"],
                "worktree_matches_head": worktree_record["sha256"]
                == sha256_bytes(head_bytes),
            }
        )
    return records


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"expected a JSON object in {path}")
    return value


def _records_match(
    actual: Iterable[dict[str, Any]], expected: Iterable[dict[str, Any]]
) -> bool:
    keys = ("path", "bytes", "sha256")
    normalized_actual = sorted(
        [{key: record.get(key) for key in keys} for record in actual],
        key=lambda record: str(record["path"]),
    )
    normalized_expected = sorted(
        [{key: record.get(key) for key in keys} for record in expected],
        key=lambda record: str(record["path"]),
    )
    return normalized_actual == normalized_expected


def collect_dictionary(root: Path) -> tuple[dict[str, Any], dict[str, bool]]:
    release = root / "artifacts" / "release"
    dictionary_path = release / "system.dic"
    checked_report_path = root / "data" / "dictionary-build.report.json"
    release_report_path = release / "dictionary-build.report.json"
    checked_report = _read_json(checked_report_path)
    expected_artifacts = checked_report.get("artifacts")
    if not isinstance(expected_artifacts, dict):
        raise AuditError("dictionary build report has no artifacts object")
    expected_dictionary = expected_artifacts.get("dictionary")
    expected_categories = expected_artifacts.get("category_dictionaries")
    if not isinstance(expected_dictionary, dict) or not isinstance(expected_categories, list):
        raise AuditError("dictionary build report is missing dictionary records")

    compiled_record = file_record(dictionary_path, display_path="system.dic")
    header = parse_dictionary_header(dictionary_path)
    categories = collect_category_statistics(release / "カテゴリ辞書")
    expected_category_records = [
        {
            "path": record.get("file"),
            "bytes": record.get("bytes"),
            "sha256": record.get("sha256"),
        }
        for record in expected_categories
        if isinstance(record, dict)
    ]

    checks = {
        "dictionary_matches_checked_report": compiled_record["bytes"]
        == expected_dictionary.get("bytes")
        and compiled_record["sha256"] == expected_dictionary.get("sha256"),
        "release_report_matches_checked_report": file_record(release_report_path)["sha256"]
        == file_record(checked_report_path)["sha256"],
        "category_files_match_checked_report": _records_match(
            categories["files"], expected_category_records
        ),
        "category_entry_count_matches_compiled_header": categories["entry_count"]
        == header["entry_count"],
    }
    return (
        {
            "compiled": compiled_record,
            "header": header,
            "categories": categories,
            "checked_build_report": file_record(
                checked_report_path, display_path="data/dictionary-build.report.json"
            ),
            "release_build_report": file_record(
                release_report_path,
                display_path="artifacts/release/dictionary-build.report.json",
            ),
        },
        checks,
    )


def collect_neural_artifacts(root: Path) -> tuple[dict[str, Any], dict[str, bool]]:
    release = root / "artifacts" / "release"
    model_relative = Path("neural") / "deberta-v2-tiny-japanese-char-wwm"
    model_directory = release / model_relative
    manifest_path = model_directory / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        raise AuditError("neural model manifest has no files array")

    model_records = [
        file_record(model_directory / name, display_path=name)
        for name in ("model.onnx", "vocab.txt")
    ]
    payload_records = [
        file_record(release / "sakura_neural_worker.exe", display_path="sakura_neural_worker.exe"),
        file_record(release / "onnxruntime.dll", display_path="onnxruntime.dll"),
        *[
            file_record(
                model_directory / name,
                display_path=(model_relative / name).as_posix(),
            )
            for name in ("model.onnx", "vocab.txt", "manifest.json")
        ],
    ]
    expected_model_records = [
        {
            "path": record.get("path"),
            "bytes": record.get("bytes"),
            "sha256": record.get("sha256"),
        }
        for record in manifest_files
        if isinstance(record, dict)
    ]
    vocabulary_path = model_directory / "vocab.txt"
    with vocabulary_path.open("r", encoding="utf-8-sig") as vocabulary:
        vocabulary_size = sum(1 for _ in vocabulary)
    checks = {
        "model_files_match_manifest": _records_match(
            model_records, expected_model_records
        )
    }
    return (
        {
            "manifest": manifest,
            "manifest_record": file_record(
                manifest_path, display_path=(model_relative / "manifest.json").as_posix()
            ),
            "vocabulary_size": vocabulary_size,
            "payload_files": payload_records,
        },
        checks,
    )


def collect_corpus_statistics(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AuditError(f"corpus is missing: {path}")
    rows = 0
    slices: Counter[str] = Counter()
    lengths: Counter[str] = Counter()
    header_seen = False
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for line_number, raw_line in enumerate(source, start=1):
            if raw_line.startswith("#") or not raw_line.strip():
                continue
            row = next(csv.reader([raw_line], delimiter="\t"))
            if not header_seen:
                if row != ["id", "slice", "reading", "expected"]:
                    raise AuditError(f"unexpected corpus header at {path}:{line_number}")
                header_seen = True
                continue
            if len(row) != 4 or not all(row):
                raise AuditError(f"invalid corpus row at {path}:{line_number}")
            rows += 1
            slices[row[1]] += 1
            length = len(row[2])
            if length < 3:
                lengths["under_3"] += 1
            elif length <= 9:
                lengths["3_to_9"] += 1
            elif length <= 30:
                lengths["10_to_30"] += 1
            elif length <= 128:
                lengths["31_to_128"] += 1
            else:
                lengths["over_128"] += 1
    if not header_seen:
        raise AuditError(f"corpus header is missing: {path}")
    return {
        **file_record(path, display_path=path.name),
        "row_count": rows,
        "slice_counts": dict(sorted(slices.items())),
        "reading_length_counts": {
            name: lengths.get(name, 0)
            for name in ("under_3", "3_to_9", "10_to_30", "31_to_128", "over_128")
        },
        "reading_at_least_10_count": sum(
            lengths.get(name, 0) for name in ("10_to_30", "31_to_128", "over_128")
        ),
    }


def collect_environment() -> dict[str, Any]:
    processor = platform.processor()
    machine = (
        platform.machine()
        or os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or ("x86_64" if sys.platform == "win32" and sys.maxsize > 2**32 else "")
    )
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                processor = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return {
        "operating_system": platform.platform(),
        "machine": machine,
        "processor": processor,
        "python": platform.python_version(),
    }


def collect_audit(root: Path, *, expected_head: str | None = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    if not (root / "Cargo.toml").is_file() or not (root / ".git").exists():
        raise AuditError(f"not a Sakura Input Git checkout: {root}")

    git = collect_git_identity(root)
    if expected_head is not None and git["head"] != expected_head:
        raise AuditError(f"Sakura Input HEAD mismatch: {git['head']} != {expected_head}")

    dictionary, dictionary_checks = collect_dictionary(root)
    neural, neural_checks = collect_neural_artifacts(root)
    checks = {**dictionary_checks, **neural_checks}
    return {
        "schema_version": SCHEMA_VERSION,
        "sakura_input": git,
        "environment": collect_environment(),
        "source_fingerprints": collect_source_fingerprints(root),
        "dictionary": dictionary,
        "neural": neural,
        "corpora": {
            "held_out": collect_corpus_statistics(root / "corpus" / "held-out.tsv"),
            "tuning": collect_corpus_statistics(root / "corpus" / "tuning.tsv"),
        },
        "checks": checks,
        "all_artifact_checks_passed": all(checks.values()),
    }


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_bytes_atomic(path, payload, create_parent=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sakura-input-root", required=True, type=Path)
    parser.add_argument("--expect-head")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        audit = collect_audit(
            arguments.sakura_input_root, expected_head=arguments.expect_head
        )
        if arguments.output is None:
            json.dump(audit, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            write_json_atomic(arguments.output, audit)
            print(
                f"wrote {arguments.output}: head={audit['sakura_input']['head']} "
                f"entries={audit['dictionary']['header']['entry_count']} "
                f"checks={audit['all_artifact_checks_passed']}"
            )
        return 0 if audit["all_artifact_checks_passed"] else 1
    except (AuditError, OSError) as error:
        print(f"audit failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
