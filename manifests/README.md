# Reproducibility manifests

This directory stores small, reviewable metadata needed to reproduce research
inputs and outputs without committing heavyweight or licensed artifacts.

Each applicable manifest records:

- an immutable source identifier and exact download URL;
- official checksums and a locally calculated SHA-256;
- byte size and download timestamp;
- license and provenance;
- extraction/preprocessing tool names and versions;
- preprocessing repository Git SHA and normalization version;
- dictionary, dataset, tokenizer, model, environment, and checkpoint hashes;
- fixed seeds, hyperparameters, parameter counts, throughput, and peak VRAM for
  training runs;
- operating system, CPU model, runtime version, threading, and benchmark settings
  for production measurements.

Mutable aliases such as a Wikipedia `latest` URL may be recorded only as the
discovery source; they are never the reproducible snapshot identity.
