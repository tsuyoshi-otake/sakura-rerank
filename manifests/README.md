# Reproducibility manifests

This directory stores small, reviewable metadata needed to reproduce research
inputs and outputs without committing heavyweight or licensed artifacts.

Each applicable manifest records:

- an immutable source identifier and exact download URL;
- official MD5 and SHA-1 values in fields that are distinct from a locally
  calculated SHA-256;
- byte size and download timestamp;
- license and provenance;
- extraction/preprocessing tool names and versions;
- preprocessing repository Git SHA and normalization version;
- dictionary, dataset, tokenizer, model, environment, and checkpoint hashes;
- fixed seeds, hyperparameters, parameter counts, throughput, and peak VRAM for
  training runs;
- operating system, CPU model, runtime version, threading, and benchmark settings
  for production measurements.

Mutable aliases such as Wikipedia `latest` are rejected anywhere in a
manifest URL, including encoded forms. The snapshot date must agree with the
URL directory, file-name date, and exact multistream artifact kind.

The fixed jawiki manifest contract is defined in
[`jawiki-snapshot.schema.json`](jawiki-snapshot.schema.json) and enforced by
`sakura_rerank.data.manifest`. It has explicit
`official_metadata_verified`, `local_artifact_verified`, and
`preprocessing_verified` stages, so fields that have not yet been observed
remain null instead of being guessed.

[`jawiki-20260801-pages-articles-multistream.json`](jawiki-20260801-pages-articles-multistream.json)
records the confirmed 2026-08-01
`pages-articles-multistream.xml.bz2` metadata: 4,827,732,824 bytes, official
MD5 `b51bab6d1cc23efddc4363e78b5526c6`, and official SHA-1
`6c917b51d6f6b53a34eaebcb2a675c0769054343`. The full dump has not been
downloaded, so its local path, retrieval timestamp, and local SHA-256 are
deliberately null. These confirmed values are constants in both the schema and
Python validator; a differently dated snapshot or altered official value does
not inherit the verified status.

The
[`jawiki-snapshot.blocked.example.json`](jawiki-snapshot.blocked.example.json)
file demonstrates how to report unconfirmed metadata without filling in
guesses. It is intentionally not a valid verified manifest.

Corpus v4 adds two aggregate-only commitments. Source-span manifest schema v3
requires a hash/count commitment to the canonical Stage 4 stable-ID exclusion
file; it does not expose the IDs and cannot claim `verified` until a reproduced
identity is explicitly allowlisted. The owner calibration queue uses
[`owner-calibration-queue-manifest.schema.json`](owner-calibration-queue-manifest.schema.json)
to bind the source dataset, complete teacher state, deduplicated disagreement
list, fixed-seed 100-row one-pass sample, and ordinary review queue content.

[`sakura-rerank-tiny-v1-research-prototype.json`](sakura-rerank-tiny-v1-research-prototype.json)
binds the research-only Tiny-v1 architecture, frozen train/dev data, GPU
training environment, ignored checkpoint and FP32/INT8 ONNX hashes, parity
measurements, and source reports. It explicitly records that Gate A failed and
the final holdout was unused; it is not a production model approval.
