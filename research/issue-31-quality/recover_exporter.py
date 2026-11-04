"""Reproduce the measured recovery candidate; never enroll a new trusted identity.

Creates one fresh directory below ~/tmp. The caller owns cleanup after retaining
the receipt. Exit 3 means a successful build with bytes different from the old
trusted exporter; it is not permission to use that binary as the old exporter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

SOURCE_COMMIT = "5eefa2ffe15297e563da281432cece56049a1b09"
EXPORTER_COMMIT = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
MANIFEST_SHA256 = "2b99a6875f9cc374db13029f1f56cb0de6994168c7f1d4fbfb3cb3e5af3814b7"
TOOLCHAIN = "1.96.0-x86_64-pc-windows-msvc"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, timeout=60)


def archive(root: Path, commit: str, output: Path, paths: list[str]) -> dict:
    packed = output.with_suffix(".tar")
    git(root, "archive", "--format=tar", "--output=" + str(packed), commit, "--", *paths)
    output.mkdir()
    with tarfile.open(packed) as stream:
        members = stream.getmembers()
        if (sum(item.size for item in members) > 128 * 1024 * 1024
                or any(not (item.isfile() or item.isdir()) for item in members)):
            raise ValueError("source_archive_outside_contract")
        stream.extractall(output, filter="data")
    return dict(commit=commit, archive_sha256=sha(packed), files=sum(item.isfile() for item in members))


def run(output: Path, checkout_eol: str) -> int:
    repo = Path(__file__).resolve().parents[2]
    source = repo.parent / "sakura-input"
    temp = (Path.home() / "tmp").resolve()
    output = output.resolve()
    if temp not in output.parents or output.exists():
        raise ValueError("output_requires_fresh_directory_below_user_tmp")
    manifest_path = repo / "manifests/research-exporter-verified.json"
    if sha(manifest_path) != MANIFEST_SHA256:
        raise ValueError("trusted_manifest_changed")
    manifest = json.loads(manifest_path.read_bytes())
    if git(source, "status", "--porcelain=v1"):
        raise ValueError("source_checkout_is_not_clean")
    output.mkdir()
    result = dict(kind="exporter_recovery_attempt", schema_version=1,
                  source_commit=SOURCE_COMMIT, exporter_commit=EXPORTER_COMMIT,
                  observed_source_head=git(source, "rev-parse", "HEAD").decode().strip(),
                  checkout_eol=checkout_eol, trusted_manifest_sha256=MANIFEST_SHA256,
                  expected_binary_sha256=manifest["exporter_binary_sha256"],
                  trust_set_changed=False, production_checkout_modified=False,
                  worktrees_created=0, forward_executed=False, timeout_seconds=600)
    code = 2
    try:
        workspace, exporter = output / "source", output / "exporter"
        result["source_archive"] = archive(source, SOURCE_COMMIT, workspace,
            ["Cargo.toml", "Cargo.lock", ".cargo", "crates", "data/keymap-ms-ime.toml",
             "data/keymap-atok.toml", "data/romaji.toml"])
        result["exporter_archive"] = archive(repo, EXPORTER_COMMIT, exporter,
            ["research/exporter", "research/patches/sakura-input-research-top32.patch",
             "research/lock/sakura-input-research-top32.Cargo.lock"])
        if checkout_eol == "crlf":
            for path in workspace.rglob("*"):
                if path.is_file() and path.suffix in {".rs", ".toml"}:
                    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        patch = exporter / "research/patches/sakura-input-research-top32.patch"
        lock = exporter / "research/lock/sakura-input-research-top32.Cargo.lock"
        if sha(patch) != manifest["instrumentation_patch_sha256"] or sha(lock) != manifest["cargo_lock_sha256"]:
            raise ValueError("archived_build_inputs_changed")
        git(workspace, "-c", "core.autocrlf=true", "apply", "--unidiff-zero", str(patch))
        shutil.copytree(exporter / "research/exporter", workspace / "research/exporter")
        shutil.copyfile(lock, workspace / "Cargo.lock")
        cargo = workspace / "Cargo.toml"
        text = cargo.read_text(encoding="utf-8")
        anchor = '    "crates/sakura-neural-worker",'
        if text.count(anchor) != 1:
            raise ValueError("workspace_anchor_changed")
        cargo.write_text(text.replace(anchor, anchor + '\n    "research/exporter",'), encoding="utf-8", newline="\n")
        clear = {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                 "RUSTDOCFLAGS", "CARGO_TARGET_DIR", "CARGO_BUILD_TARGET", "CARGO_BUILD_RUSTC",
                 "RUSTC", "RUSTC_BOOTSTRAP", *manifest["build_environment"]}
        env = {key: value for key, value in os.environ.items()
               if key not in clear and not key.startswith("SAKURA_RERANK_")}
        env.update(manifest["build_environment"])
        env.update(TEMP=str(output), TMP=str(output),
            RUSTFLAGS=f"--remap-path-prefix={workspace.as_posix()}=/sakura-input -C link-arg=/Brepro",
            SAKURA_RERANK_EXPORTER_GIT_SHA=EXPORTER_COMMIT,
            SAKURA_RERANK_PATCH_SHA256=manifest["instrumentation_patch_sha256"],
            SAKURA_RERANK_CARGO_LOCK_SHA256=manifest["cargo_lock_sha256"],
            SAKURA_RERANK_RUSTC_VERSION=manifest["rustc_version"],
            SAKURA_RERANK_CARGO_VERSION=manifest["cargo_version"])
        for tool, expected in (("rustc", manifest["rustc_version"]), ("cargo", manifest["cargo_version"])):
            actual = subprocess.check_output([tool, "+" + TOOLCHAIN, "--version"], env=env, timeout=30).decode().strip()
            if actual != expected:
                raise ValueError("compiler_version_changed")
        command = ["cargo", "+" + TOOLCHAIN, "build", "--offline", "--locked", "--release", "--jobs", "2",
                   "--target", manifest["target_triple"], "--target-dir", str(output / "target"),
                   "--manifest-path", str(cargo), "--package", "sakura-research-top32-exporter"]
        start = time.monotonic()
        with (output / "build.log").open("xb") as log:
            process = subprocess.Popen(command, cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                result["build_exit_code"] = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30, check=True)
                process.wait(timeout=30)
                raise ValueError("build_timeout") from None
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        result["log_sha256"] = sha(output / "build.log")
        if result["build_exit_code"]:
            raise ValueError("build_failed")
        if sha(workspace / "Cargo.lock") != manifest["cargo_lock_sha256"]:
            raise ValueError("build_changed_lock")
        binary = output / "target" / manifest["target_triple"] / "release/sakura-research-top32-exporter.exe"
        result["binary_sha256"] = sha(binary)
        code = 0 if result["binary_sha256"] == manifest["exporter_binary_sha256"] else 3
        result["status"] = "restored_exact_binary" if code == 0 else "built_different_binary"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        result["status"] = "failed"
        result["error_type"] = type(error).__name__
        if type(error) is ValueError:
            result["failure_code"] = str(error)
    finally:
        result["exit_code"] = code
        with (output / "recovery.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkout-eol", choices=("lf", "crlf"), default="lf")
    args = parser.parse_args()
    sys.exit(run(args.output, args.checkout_eol))
