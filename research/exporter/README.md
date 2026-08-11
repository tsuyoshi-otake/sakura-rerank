# Research-only Sakura top-32 exporter

This crate is a standalone research artifact. It is not a Sakura Input
production target and is never added to the Sakura Input installer or settings
path. The build script creates a detached worktree at the pinned Sakura Input
HEAD, applies [`research/patches/sakura-input-research-top32.patch`](../patches/sakura-input-research-top32.patch), copies this crate into that temporary worktree, and removes the worktree after the build.

The exporter accepts bounded JSONL containing only these fields per line:

```json
{"stable_id":"case-001","reading":"かな"}
```

It emits immutable `research_converter_snapshot` records with the converter's
full-reading top-32 N-best candidates, exact path-edge segment provenance,
candidate fingerprints, search terminal status, and a canonical top-6 prefix.
Input records are sorted by `stable_id`; duplicate IDs, malformed records,
oversized files, and path collisions fail before publication. The output and
report are published as a pair, and the report/stdout contain aggregate counts
and hashes rather than reading or candidate text.

Build from a clean pinned Sakura Input worktree and the exact pinned dictionary.
The output and manifest parent directories and `BuildRoot` must already exist;
the build refuses missing or unconfirmable path identities, aliases, source-tree
placement, containment, and any existing publication target:

```powershell
$exporterRoot = Join-Path $env:USERPROFILE "tmp\sakura-rerank-exporter"
New-Item -ItemType Directory -Force -Path $exporterRoot, (Join-Path $exporterRoot "build") | Out-Null
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_research_top32_exporter.ps1 `
  -SakuraInputRoot "$env:USERPROFILE\tmp\sakura-input-pinned" `
  -DictionaryPath "$env:USERPROFILE\tmp\sakura-input-dictionary\system.dic" `
  -OutputBinary (Join-Path $exporterRoot "sakura-research-top32-exporter.exe") `
  -IdentityManifest (Join-Path $exporterRoot "identity.json") `
  -BuildRoot (Join-Path $exporterRoot "build")
```

The generated identity manifest records the Sakura Input HEAD, dictionary,
instrumentation patch, the exact tracked Cargo.lock input, compiler, exact
`1.96.0-x86_64-pc-windows-msvc` toolchain selector, target, release profile, and
measured exporter binary hash. The exact patch and Cargo.lock build inputs are
tracked in Git; generated binaries, JSONL, and raw traces remain outside Git. A
`verified` manifest is accepted only when its measured
`(exporter_git_sha, exporter_binary_sha256)` pair and every trusted metadata field
are explicitly allowlisted in the Python contract.

To regenerate a trusted binary, first make a clean detached checkout at the
manifest's exact `exporter_git_sha`. Do not build from a moving branch, a dirty
checkout, or a different source tree. Rebuild that detached commit from two
independent build roots, compare the binary, patch, lock, and generated manifest
hashes, and only then update the single trusted identity.

Validate an allowlisted export with:

```powershell
$env:PYTHONPATH = "src"
python -m sakura_rerank.data contract exporter-validate `
  "$env:USERPROFILE\tmp\sakura-rerank-exporter\export.research-export.jsonl" `
  --manifest manifests\research-exporter-verified.json
```

The exporter is intentionally out of scope for Tier A verification, corpus
download, dataset construction, training, model export, ORT benchmarking, and
Sakura Input production integration.
