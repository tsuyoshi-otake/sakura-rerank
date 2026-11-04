# Separate research reference for the fixed annotation probe (#31 / #32)

This implements the preregistered
[reestablishment plan](issue-31-quality/exporter-reestablishment-plan-v1.json).
It does not restore the missing historical binary, change a legacy allowlist,
create Gold labels, train a model, or consume an independent final Test.

## Frozen inputs and ownership

The available Sakura Input source is commit
`5eefa2ffe15297e563da281432cece56049a1b09`, tree
`a975be54175b1c946ca06fb2571e7587f1bebb7f`. The existing research instrumentation,
Cargo.lock and base exporter are archived from their historical commits. A
separate patch changes exactly three string literals: the recorded source HEAD,
the manifest kind, and the output record type. Converter algorithms are unchanged
by this patch. This is not a claim of equivalence with the unavailable old tree.

[Build profile](../manifests/reference-probe-build-profile-v1.json) pins the Rust
and Cargo executable hashes, linker hash, SDK/toolset versions, and a 537-file
library inventory. The latter's full content stays local; its canonical hash is
tracked. Builds explicitly select the linker and limit `LIB` to the measured
MSVC, SDK UM and SDK UCRT x64 roots. Two fresh archive directories each use
offline/locked Cargo, two jobs, and a 600-second timeout. A failed or timed-out
build records failure and cannot supply a successful probe binding.

The `exporter_git_sha` in the new runtime manifest identifies the committed
recipe (base-source pointer plus identity patch), not an unchanged copy of the
old exporter tree. The binding separately records the base exporter/source
commits and complete build receipts. The inner runtime status stays `unverified`
under the legacy contract. Probe admission requires the externally committed
binding hash, two matched builds, and actual executable/dictionary hashes.

`reference_probe` owns probe admission, exact request/output coverage and the
candidate comparison. It reuses the existing segment/fingerprint/snapshot
validation rules without changing `contracts.py` or `research_exporter.py`.
The distinct `research_probe_converter_snapshot` type and actual source HEAD are
both rejected by the legacy reader, even with `require_verified=False`.

## Regression population selected before candidate access

[Selection commitment](../manifests/reference-probe-selection-v1.json) binds
100 IDs selected from all 12,516 train IDs using the registered seed/hash order.
The source SHA covers all 17,880 serialized rows, but non-train rows are excluded
by their canonical split marker before JSON parsing. Selection reads only train
ID markers, not candidate content. Dev 1,788 and holdout 3,576 rows are not parsed.

The plan's instruction to "commit IDs" is implemented as a public hash commitment
to the complete ordered ID file retained in ignored local storage, following the
repository's aggregate-only rule. No sampled candidate content was accessed
before this disclosure and commitment. There is no replacement or backfilling.

After that commitment, only selected train rows are parsed to recover the actual
old snapshots. The legacy validator authenticates their recorded identity. Every
rank, surface, cost, fingerprint, entry index, segment field, Top-6 prefix and
search terminal is compared. The only excluded comparison fields are the
explicitly declared provenance changes and the hashes that contain provenance.
Any population, feature or terminal disagreement prevents use on the 50 cases.
A matching 100-case regression does not prove global historical equivalence.

## Verification rubric

- Verify: `PYTHONPATH=src python -m unittest discover -s tests -p test_reference_probe.py -v`.
  Expect: nine contracts pass for blinded ID selection, changed source/hash,
  substituted identities, legacy rejection, malformed/rehashed features, prefix
  violations, missing/duplicate/reordered output and comparison differences.
- Verify: full `python -m unittest discover -s tests -v` with an outer 300-second
  timeout. Expect: 435 tests, five existing optional PyTorch skips, no failures.
- Verify: commit and push recipe/profile/selection before running
  `python research/issue-31-quality/build_reference_exporter.py --recipe-sha <commit> --build-id a --output <fresh-USERPROFILE/tmp-dir>`;
  repeat with build ID b and a different fresh directory. Expect: both build
  receipts succeed and executable hashes match; changed working recipes,
  toolchain/libraries and existing/outside output paths are refused.
- Verify: externally commit the measured binding before converter execution,
  then authenticate artifacts and compare the fixed 100 requests. Expect:
  100/100 exact candidate and terminal matches or an explicit stopped result.
- Verify: only after passing the regression, execute the existing 50 annotation
  requests twice with 120-second bounds. Expect: identical output bytes, complete
  50-case accounting and source-exact Top-1/5/6/10/32 presence counts. Missing
  targets and execution failures remain in the denominator; these are not Gold
  accuracy or model-comparison results.

PowerShell: set `$env:PYTHONPATH='src'`. All generated inputs/outputs, binaries,
source trees and dependency inventories stay outside Git. Each task owns its
temporary directories and audits runner exit before cleanup. Keep existing
datasets/models, the 0.25% threshold, and final-Test consumption unchanged.

## Scope and future reading (IRV)

A. Required: the old candidate/snapshot contract, exporter identity literals,
the recovery archive helpers, fixed source/selection/profile, the probe module
and its focused tests. B. Scope expanded to compiler/linker/library provenance
because old binary identity was not reproducible. C. Probe state is owned by
immutable selection/build/binding/run artifacts; legacy admission remains owned
by its unchanged module. D. Future probes can start from the binding and request
contract, without repeating artifact recovery or understanding model internals.
They still need explicit population, licensing, quality and leakage evidence.
