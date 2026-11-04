"""Build a separately identified research probe from committed source and profile.

No legacy allowlist is changed. The caller owns the fresh ~/tmp build directory;
only two independently matched successful receipts can form a probe binding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from recover_exporter import archive, git, sha

RECIPE_FILES = (
    "research/issue-31-quality/build_reference_exporter.py",
    "research/issue-31-quality/recover_exporter.py",
    "research/patches/research-exporter-probe-identity.patch",
    "manifests/reference-probe-build-profile-v1.json",
)


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def apply_identity_patch(exporter: Path, patch: Path, expected_sha: str) -> None:
    # The archived exporter is LF; the historical core below contains CRLF blobs.
    git(exporter, "-c", "core.autocrlf=false", "apply", str(patch))
    if sha(exporter / "research/exporter/src/main.rs") != expected_sha:
        raise ValueError("patched_source_differs")


def apply_core_patch(workspace: Path, patch: Path, expected: dict[str, str]) -> None:
    git(workspace, "-c", "core.autocrlf=true", "apply", "--unidiff-zero", str(patch))
    if any(sha(workspace / name) != digest for name, digest in expected.items()):
        raise ValueError("instrumented_core_bytes_differ")


def run(output: Path, recipe_sha: str, build_id: str) -> int:
    repo = Path(__file__).resolve().parents[2]
    source = repo.parent / "sakura-input"
    output = output.resolve()
    if (Path.home() / "tmp").resolve() not in output.parents or output.exists():
        raise ValueError("fresh_output_below_tmp_required")
    if not re.fullmatch(r"[0-9a-f]{40}", recipe_sha) or build_id not in {"a", "b"}:
        raise ValueError("invalid_recipe_or_build_identity")
    for name in RECIPE_FILES:
        if (repo / name).read_bytes() != git(repo, "show", recipe_sha + ":" + name):
            raise ValueError("working_recipe_differs_from_commit")
    profile_path = repo / RECIPE_FILES[-1]
    profile = json.loads(profile_path.read_bytes())
    if git(source, "status", "--porcelain=v1"):
        raise ValueError("source_checkout_not_clean")
    if git(source, "rev-parse", profile["source_commit"] + "^{tree}").decode().strip() != profile["source_tree"]:
        raise ValueError("source_tree_differs")
    legacy_path = repo / "manifests/research-exporter-verified.json"
    if sha(legacy_path) != profile["legacy_manifest_sha256"]:
        raise ValueError("legacy_profile_changed")
    legacy = json.loads(legacy_path.read_bytes())
    inventory_path = repo / "data/generated/issue-31-reference-exporter-v1/library-inventory.json"
    if sha(inventory_path) != profile["library_inventory_file_sha256"]:
        raise ValueError("library_inventory_changed")
    inventory = json.loads(inventory_path.read_bytes())
    if hashlib.sha256(canonical(inventory)).hexdigest() != profile["library_inventory_sha256"]:
        raise ValueError("library_inventory_content_changed")
    # Absolute paths are local execution locations, not the portable identity.
    msvc = Path("C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC") / profile["msvc_toolset"]
    sdk = Path("C:/Program Files (x86)/Windows Kits/10/Lib") / profile["windows_sdk"]
    roots = {"msvc": msvc / "lib/x64", "sdk-um": sdk / "um/x64", "sdk-ucrt": sdk / "ucrt/x64"}
    actual_paths = {alias + "/" + p.name for alias, root in roots.items() for p in root.glob("*.lib")}
    if actual_paths != {item["path"] for item in inventory}:
        raise ValueError("library_search_population_changed")
    for item in inventory:
        alias, name = item["path"].split("/")
        path = roots[alias] / name
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("library_bytes_changed")
    linker = msvc / "bin/Hostx64/x64/link.exe"
    if sha(linker) != profile["linker_sha256"]:
        raise ValueError("linker_changed")
    for tool, expected in profile["tools"].items():
        path = Path(subprocess.check_output(["rustup", "which", "--toolchain", profile["rust_toolchain"], tool], timeout=30).decode().strip())
        if sha(path) != expected["sha256"]:
            raise ValueError("compiler_binary_changed")
        if subprocess.check_output([str(path), "--version"], timeout=30).decode().strip() != expected["version"]:
            raise ValueError("compiler_version_changed")
    output.mkdir()
    result = dict(kind="reference_probe_build", schema_version=1, build_id=build_id,
        recipe_git_sha=recipe_sha, build_profile_sha256=sha(profile_path), source_commit=profile["source_commit"],
        source_tree=profile["source_tree"], observed_source_head=git(source, "rev-parse", "HEAD").decode().strip(),
        linker_sha256=profile["linker_sha256"], library_inventory_sha256=profile["library_inventory_sha256"],
        identity_patch_sha256=profile["identity_patch_sha256"], worktrees_created=0, forward_executed=False)
    exit_code = 2
    try:
        workspace, exporter = output / "source", output / "exporter"
        result["source_archive"] = archive(source, profile["source_commit"], workspace,
            ["Cargo.toml", "Cargo.lock", ".cargo", "crates", "data/keymap-ms-ime.toml", "data/keymap-atok.toml", "data/romaji.toml"])
        result["exporter_archive"] = archive(repo, profile["base_exporter_commit"], exporter,
            ["research/exporter", "research/patches/sakura-input-research-top32.patch", "research/lock/sakura-input-research-top32.Cargo.lock"])
        core_patch = exporter / "research/patches/sakura-input-research-top32.patch"
        lock = exporter / "research/lock/sakura-input-research-top32.Cargo.lock"
        if sha(core_patch) != legacy["instrumentation_patch_sha256"] or sha(lock) != legacy["cargo_lock_sha256"]:
            raise ValueError("legacy_build_inputs_changed")
        main = exporter / "research/exporter/src/main.rs"
        if sha(main) != profile["original_exporter_main_sha256"]:
            raise ValueError("base_exporter_source_changed")
        patch = repo / "research/patches/research-exporter-probe-identity.patch"
        if sha(patch) != profile["identity_patch_sha256"]:
            raise ValueError("probe_patch_changed")
        apply_identity_patch(exporter, patch, profile["patched_exporter_main_sha256"])
        apply_core_patch(workspace, core_patch, profile["instrumented_source_sha256"])
        shutil.copytree(exporter / "research/exporter", workspace / "research/exporter")
        shutil.copyfile(lock, workspace / "Cargo.lock")
        cargo = workspace / "Cargo.toml"
        text = cargo.read_text(encoding="utf-8")
        anchor = '    "crates/sakura-neural-worker",'
        if text.count(anchor) != 1:
            raise ValueError("workspace_anchor_changed")
        cargo.write_text(text.replace(anchor, anchor + '\n    "research/exporter",'), encoding="utf-8", newline="\n")
        clear = {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                 "RUSTDOCFLAGS", "CARGO_TARGET_DIR", "CARGO_BUILD_TARGET", "CARGO_BUILD_RUSTC", "RUSTC",
                 "RUSTC_BOOTSTRAP", "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER", *legacy["build_environment"]}
        env = {key: value for key, value in os.environ.items() if key not in clear and not key.startswith("SAKURA_RERANK_")}
        env.update(legacy["build_environment"])
        env.update(TEMP=str(output), TMP=str(output), LIB=";".join(str(p) for p in roots.values()),
            CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER=str(linker),
            RUSTFLAGS=f"--remap-path-prefix={workspace.as_posix()}=/sakura-input -C link-arg=/Brepro",
            SAKURA_RERANK_EXPORTER_GIT_SHA=recipe_sha,
            SAKURA_RERANK_PATCH_SHA256=legacy["instrumentation_patch_sha256"],
            SAKURA_RERANK_CARGO_LOCK_SHA256=legacy["cargo_lock_sha256"],
            SAKURA_RERANK_RUSTC_VERSION=legacy["rustc_version"], SAKURA_RERANK_CARGO_VERSION=legacy["cargo_version"])
        command = ["cargo", "+" + profile["rust_toolchain"], "build", "--offline", "--locked", "--release", "--jobs", "2",
            "--target", legacy["target_triple"], "--target-dir", str(output / "target"), "--manifest-path", str(cargo),
            "--package", "sakura-research-top32-exporter"]
        start = time.monotonic()
        with (output / "build.log").open("xb") as log:
            process = subprocess.Popen(command, cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            print(json.dumps({"build_id": build_id, "pid": process.pid, "status": "building"}), flush=True)
            try:
                result["build_exit_code"] = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=True, timeout=30)
                process.wait(timeout=30)
                raise ValueError("build_timeout") from None
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        result["log_sha256"] = sha(output / "build.log")
        if result["build_exit_code"] or sha(workspace / "Cargo.lock") != legacy["cargo_lock_sha256"]:
            raise ValueError("build_failed_or_lock_changed")
        binary = output / "target" / legacy["target_triple"] / "release/sakura-research-top32-exporter.exe"
        result["binary_sha256"] = sha(binary)
        shutil.copyfile(binary, output / "probe-exporter.exe")
        runtime = dict(legacy, manifest_kind="research_probe_top32_exporter", verification_status="unverified",
            exporter_git_sha=recipe_sha, exporter_binary_sha256=result["binary_sha256"], sakura_input_head=profile["source_commit"])
        (output / "runtime-manifest.json").write_bytes(canonical(runtime) + b"\n")
        result["runtime_manifest_sha256"] = sha(output / "runtime-manifest.json")
        result["status"] = "built"
        exit_code = 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["status"] = "failed"
        result["error_type"] = type(error).__name__
        if type(error) is ValueError:
            result["failure_code"] = str(error)
    finally:
        with (output / "build-receipt.json").open("xb") as stream:
            stream.write(canonical(result) + b"\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(result, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recipe-sha", required=True)
    parser.add_argument("--build-id", choices=("a", "b"), required=True)
    args = parser.parse_args()
    sys.exit(run(args.output, args.recipe_sha, args.build_id))
