from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from sakura_rerank import research_tiny as v1
from sakura_rerank import research_tiny_r2 as r2
from sakura_rerank.research_tiny_r2 import (
    COST_GAP_INDEX,
    COST_GAP_MANIFEST_KIND,
    EPOCHS,
    EXPERIMENT_REPORT_KIND,
    FEATURE_DIM,
    LABEL_SMOOTHING,
    MODEL_CONTRACT_VERSION,
    MODEL_NAME,
    SCHEMA_VERSION,
    SEED,
    STATUS,
    TIMING_SCOPE,
    ResearchTinyR2Error,
    _aggregate_json_bytes,
    _cost_gap_manifest,
    _hyperparameters,
    _recipe,
    _require_shape,
    _train_dev_row,
    build_model,
    candidate_features,
    check_experiment_adoption,
    cost_gap_features,
    export_onnx,
    load_inputs,
    main,
    prepare_cost_gap,
    publish_evidence,
    smoothed_listwise_loss,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> bytes:
    data = v1.canonical_json_bytes(value)
    path.write_bytes(data)
    return data


def _candidate(cost: float, surface: str = "候補") -> dict[str, Any]:
    return {
        "local_cost": cost,
        "segments": [{}],
        "surface": surface,
        "source_category": "system_dictionary",
    }


class CostGapFeatureTests(unittest.TestCase):
    def test_gap_is_absolute_log_compressed_and_zero_for_the_cheapest(self) -> None:
        values = cost_gap_features([_candidate(1010), _candidate(10), _candidate(30)])
        self.assertEqual(values[1], 0.0)
        self.assertAlmostEqual(values[0], -math.log1p(1.0))
        self.assertAlmostEqual(values[2], -math.log1p(0.02))
        shifted = cost_gap_features([_candidate(6010), _candidate(5010), _candidate(5030)])
        self.assertEqual(values, shifted)

    def test_gap_separates_rows_that_v1_normalization_merges(self) -> None:
        small = [_candidate(0), _candidate(10)]
        large = [_candidate(0), _candidate(1000)]
        self.assertEqual(
            [row[0] for row in v1.candidate_features("よみ", small)],
            [row[0] for row in v1.candidate_features("よみ", large)],
        )
        self.assertNotEqual(cost_gap_features(small), cost_gap_features(large))

    def test_features_are_v1_features_plus_one_gap_column(self) -> None:
        candidates = [_candidate(10, "東京"), _candidate(30, "東亰")]
        values = candidate_features("とうきょう", candidates)
        self.assertEqual(FEATURE_DIM, v1.FEATURE_DIM + 1)
        self.assertEqual(
            [row[:COST_GAP_INDEX] for row in values],
            v1.candidate_features("とうきょう", candidates),
        )
        self.assertEqual([row[COST_GAP_INDEX] for row in values], cost_gap_features(candidates))

    def test_non_finite_costs_fail_closed(self) -> None:
        with self.assertRaises(ResearchTinyR2Error):
            cost_gap_features([_candidate(math.nan), _candidate(1)])


@unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch is an optional training dependency")
class ModelAndLossTests(unittest.TestCase):
    @staticmethod
    def _inputs(batch: int = 2) -> tuple[Any, ...]:
        import torch

        mask = torch.ones((batch, v1.TOP_K), dtype=torch.bool)
        mask[:, 4:] = False
        return (
            torch.zeros((batch, v1.CONTEXT_LENGTH), dtype=torch.int64),
            torch.ones(batch, dtype=torch.int64),
            torch.zeros((batch, v1.READING_LENGTH), dtype=torch.int64),
            torch.ones(batch, dtype=torch.int64),
            torch.zeros((batch, v1.TOP_K, v1.SURFACE_LENGTH), dtype=torch.int64),
            torch.ones((batch, v1.TOP_K), dtype=torch.int64),
            torch.zeros((batch, v1.TOP_K, FEATURE_DIM), dtype=torch.float32),
            mask,
        )

    def test_model_adds_one_feature_column_and_masks_padding(self) -> None:
        import torch

        model = build_model()
        count = v1.model_parameter_count(model)
        self.assertEqual(count, v1.model_parameter_count(v1.build_model()) + v1.HIDDEN_DIM)
        self.assertGreaterEqual(count, 1_800_000)
        self.assertLessEqual(count, 2_100_000)
        model.eval()
        with torch.inference_mode():
            scores = model(*self._inputs())
        self.assertEqual(tuple(scores.shape), (2, v1.TOP_K))
        self.assertTrue(bool(torch.all(scores[:, 4:] == -10_000.0)))

    def test_dropout_is_active_only_in_training_mode(self) -> None:
        import torch

        torch.manual_seed(0)
        model = build_model()
        inputs = self._inputs()
        model.eval()
        with torch.inference_mode():
            self.assertTrue(torch.equal(model(*inputs), model(*inputs)))
        model.train()
        with torch.no_grad():
            samples = [model(*inputs) for _ in range(4)]
        self.assertTrue(any(not torch.equal(samples[0], other) for other in samples[1:]))

    def test_label_smoothing_spreads_mass_over_valid_candidates_only(self) -> None:
        import torch

        scores = torch.tensor([[2.0, 1.0, -10_000.0, -10_000.0, -10_000.0, -10_000.0]])
        mask = torch.tensor([[True, True, False, False, False, False]])
        log_probs = torch.log_softmax(scores, dim=1)
        expected = -(
            (1.0 - LABEL_SMOOTHING + LABEL_SMOOTHING / 2) * log_probs[0, 0]
            + (LABEL_SMOOTHING / 2) * log_probs[0, 1]
        )
        actual = smoothed_listwise_loss(scores, torch.tensor([0]), mask)
        self.assertAlmostEqual(float(actual), float(expected), places=6)


class FrozenSplitLineTests(unittest.TestCase):
    def test_holdout_lines_are_skipped_before_json_parsing(self) -> None:
        self.assertIsNone(_train_dev_row(b'{"split":"final-holdout", this is not JSON'))

    def test_train_and_dev_rows_parse(self) -> None:
        for split in ("train", "dev"):
            with self.subTest(split):
                line = b'{"split":"%s","value":1}\n' % split.encode()
                self.assertEqual(_train_dev_row(line), {"split": split, "value": 1})

    def test_other_spellings_and_splits_fail_closed(self) -> None:
        for line in (
            b'{"split": "final-holdout"}',
            b'{"split":"test"}',
            b"[]",
            b'{"split":"train"',
        ):
            with self.subTest(line=line), self.assertRaises(ResearchTinyR2Error):
                _train_dev_row(line)

    def test_prepare_checks_the_frozen_split_hash_before_anything_else(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "split.jsonl"
            source.write_bytes(b'{"split":"train"}\n')
            with self.assertRaises(ResearchTinyR2Error):
                prepare_cost_gap(
                    source,
                    root / "missing-cache.npz",
                    root / "missing-cache.json",
                    root / "gap.npz",
                    root / "gap.json",
                )
            self.assertEqual([path.name for path in root.iterdir()], ["split.jsonl"])

    def test_cli_reports_contract_failures_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "split.jsonl"
            source.write_bytes(b"{}\n")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "prepare-cost-gap",
                        str(source),
                        "--cache",
                        str(root / "cache.npz"),
                        "--cache-manifest",
                        str(root / "cache.json"),
                        "--output",
                        str(root / "gap.npz"),
                        "--manifest",
                        str(root / "gap.json"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("research tiny r2 failed", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


class ExperimentAdoptionTests(unittest.TestCase):
    KEY = f"C2-s{v1.SEED}"

    def _experiment(self) -> dict[str, Any]:
        return {
            "issue": 21,
            "final_holdout_used": False,
            "decision": {"adopted": "C2", "passing": ["C2"]},
            "selection": {self.KEY: {"epoch": EPOCHS}},
            "per_model": {self.KEY: {"dev": {"correct": 10, "harm": 2, "rescue": 3, "overrides": 5}}},
            "independent_recomputation": {"matches": True},
        }

    def test_adopted_experiment_returns_the_evaluated_dev_outcome(self) -> None:
        self.assertEqual(
            check_experiment_adoption(self._experiment()),
            {"correct": 10, "harm": 2, "rescue": 3},
        )

    def test_experiment_that_does_not_adopt_this_model_fails_closed(self) -> None:
        cases: dict[str, Callable[[dict[str, Any]], None]] = {
            "nothing adopted": lambda value: value["decision"].update(adopted=None),
            "other recipe": lambda value: value["decision"].update(adopted="C1"),
            "other epoch": lambda value: value["selection"][self.KEY].update(epoch=EPOCHS + 1),
            "holdout used": lambda value: value.update(final_holdout_used=True),
            "recomputation mismatch": lambda value: value["independent_recomputation"].update(
                matches=False
            ),
            "missing model": lambda value: value["per_model"].clear(),
        }
        for name, mutate in cases.items():
            experiment = self._experiment()
            mutate(experiment)
            with self.subTest(name), self.assertRaises(ResearchTinyR2Error):
                check_experiment_adoption(experiment)

    def test_dev_outcome_must_be_integer_counts(self) -> None:
        for value in ("10", 10.0, -1, True, None):
            experiment = self._experiment()
            experiment["per_model"][self.KEY]["dev"]["correct"] = value
            with self.subTest(value=value), self.assertRaises(ResearchTinyR2Error):
                check_experiment_adoption(experiment)


class OutputContractTests(unittest.TestCase):
    def test_dataset_text_fields_are_refused_at_any_depth(self) -> None:
        for document in (
            {"text": 1},
            {"a": {"b": [{"notes": "x"}]}},
            {"a": [[{"left_context": "x"}]]},
        ):
            with self.subTest(document=document), self.assertRaises(ResearchTinyR2Error):
                _aggregate_json_bytes(document)
        self.assertEqual(
            _aggregate_json_bytes({"reading_length": 1, "b": [0]}),
            b'{"b":[0],"reading_length":1}\n',
        )

    def test_copied_subtrees_must_have_exactly_their_fixed_fields(self) -> None:
        shape = {
            "name": (str,),
            "inner": {"count": (int,), "ratio": (float, type(None))},
            "providers": (list,),
        }
        valid = {
            "name": "x",
            "inner": {"count": 1, "ratio": None},
            "providers": ["CPUExecutionProvider"],
        }
        self.assertIs(_require_shape(valid, shape, "t"), valid)
        cases = {
            "missing field": {"name": "x", "inner": {"count": 1, "ratio": None}},
            "extra field": {**valid, "notes": "x"},
            "extra nested field": {**valid, "inner": {"count": 1, "ratio": None, "text": "x"}},
            "object leaf": {**valid, "name": {"x": 1}},
            "boolean as count": {**valid, "inner": {"count": False, "ratio": None}},
            "float as count": {**valid, "inner": {"count": 1.0, "ratio": None}},
            "string as count": {**valid, "inner": {"count": "1", "ratio": None}},
            "integer as ratio": {**valid, "inner": {"count": 1, "ratio": 1}},
            "non-string list": {**valid, "providers": [{"x": 1}]},
            "long string": {**valid, "name": "x" * (r2.MAX_COPIED_STRING_LENGTH + 1)},
            "long list string": {**valid, "providers": ["x" * (r2.MAX_COPIED_STRING_LENGTH + 1)]},
            "not an object": None,
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(ResearchTinyR2Error):
                _require_shape(value, shape, "t")


class _LoaderReached(Exception):
    pass


class CostGapManifestTests(unittest.TestCase):
    """load_inputs pins every sidecar manifest byte before reading any array."""

    def _paths(self, root: Path) -> tuple[Path, Path, Path, Path]:
        cache = root / "train-dev-cache.npz"
        cache.write_bytes(b"cache")
        cache_manifest = root / "train-dev-cache.manifest.json"
        cache_manifest.write_bytes(b"{}\n")
        gap = root / "cost-gap.npz"
        gap.write_bytes(b"gap")
        return cache, cache_manifest, gap, root / "cost-gap.manifest.json"

    @staticmethod
    def _manifest(cache: Path, cache_manifest: Path, gap: Path) -> dict[str, Any]:
        source = {"file": "frozen-split.jsonl", "bytes": 10, "sha256": v1.DATASET_CONTENT_SHA256}
        return _cost_gap_manifest(source, cache, cache_manifest, gap)

    def test_the_exact_manifest_reaches_the_v1_cache_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache, cache_manifest, gap, manifest_path = self._paths(Path(directory))
            _write_json(manifest_path, self._manifest(cache, cache_manifest, gap))
            with mock.patch.object(v1, "_load_cache", side_effect=_LoaderReached):
                with self.assertRaises(_LoaderReached):
                    load_inputs(cache, cache_manifest, gap, manifest_path)

    def test_every_manifest_field_is_pinned(self) -> None:
        cases: dict[str, Callable[[dict[str, Any]], None]] = {
            "schema version": lambda value: value.update(schema_version=2),
            "status": lambda value: value.update(status="gate_a_passed"),
            "source hash": lambda value: value["source"].update(sha256="0" * 64),
            "source extra field": lambda value: value["source"].update(rows=1),
            "cache file": lambda value: value["v1_numeric_cache"].update(file="other.npz"),
            "cache manifest hash": lambda value: value["v1_numeric_cache"].update(
                manifest_sha256="0" * 64
            ),
            "sidecar size": lambda value: value["cost_gap"].update(bytes=0),
            "feature index": lambda value: value["feature"].update(index=COST_GAP_INDEX - 1),
            "padding value": lambda value: value["feature"].update(padding_value=-1.0),
            "alignment": lambda value: value["alignment_with_v1_cache"].update(gold_equal=False),
            "split counts": lambda value: value["splits"].update(dev=v1.DEV_COUNT - 1),
            "holdout lines": lambda value: value["final_holdout"].update(
                source_lines_skipped_by_split_token=0
            ),
            "holdout flag as integer": lambda value: value["final_holdout"].update(
                used_for_training_or_selection=0
            ),
            "extra field": lambda value: value.update(notes="x"),
        }
        with tempfile.TemporaryDirectory() as directory:
            cache, cache_manifest, gap, manifest_path = self._paths(Path(directory))
            for name, mutate in cases.items():
                manifest = self._manifest(cache, cache_manifest, gap)
                mutate(manifest)
                _write_json(manifest_path, manifest)
                with (
                    self.subTest(name),
                    mock.patch.object(v1, "_load_cache", side_effect=_LoaderReached),
                    self.assertRaisesRegex(ResearchTinyR2Error, "cost-gap manifest"),
                ):
                    load_inputs(cache, cache_manifest, gap, manifest_path)

    def test_non_object_or_non_canonical_manifests_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache, cache_manifest, gap, manifest_path = self._paths(Path(directory))
            for raw in (b"[]\n", b'{"a": 1}\n'):
                manifest_path.write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(ResearchTinyR2Error):
                    load_inputs(cache, cache_manifest, gap, manifest_path)


class PublishEvidenceTests(unittest.TestCase):
    """publish_evidence binds consistent evidence and writes nothing otherwise."""

    KEY = f"C2-s{v1.SEED}"
    MANIFEST = "model.json"
    REPORT = "decision.json"

    @staticmethod
    def _header(kind: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "report_kind": kind,
            "status": STATUS,
            "model_name": MODEL_NAME,
            "raw_text_in_report": False,
            "raw_stable_ids_in_report": False,
        }

    def _benchmark(self, file: str, sha256: str) -> dict[str, Any]:
        return {
            **self._header("sakura_rerank_tiny_r2_onnx_dev_benchmark"),
            "model": {"file": file, "bytes": 1_000, "sha256": sha256},
            "quality": {
                "record_count": v1.DEV_COUNT,
                "oracle_count": 1_700,
                "top1_correct": 1_639,
                "top1_accuracy": 1_639 / v1.DEV_COUNT,
                "mrr": 0.9,
                "ndcg_at_6": 0.9,
                "baseline_top1_correct": 1_586,
                "baseline_top1_accuracy": 1_586 / v1.DEV_COUNT,
                "rescue_count": 91,
                "harm_count": 38,
                "rescue_harm_ratio": 91 / 38,
            },
            "latency_ms": {"mean": 0.6, "p50": 0.6, "p95": 0.7, "p99": 0.9, "max": 3.0},
            "contract": {
                "platform": "Windows",
                "processor": "CPU",
                "gpu_disabled": True,
                "provider": ["CPUExecutionProvider"],
                "batch_size": 1,
                "ort_intra_op_threads": 1,
                "ort_inter_op_threads": 1,
                "warmup_runs": 100,
                "measured_runs": 10_000,
                "failure_count": 0,
                "timing_scope": TIMING_SCOPE,
                "final_holdout_used": False,
            },
        }

    def _documents(self) -> dict[str, dict[str, Any]]:
        cache = {
            "cache": {"sha256": "c" * 64},
            "final_holdout": {"rows_in_cache": 0, "used_for_training_or_selection": False},
            "source": {"sha256": v1.DATASET_CONTENT_SHA256},
            "splits": {"dev": v1.DEV_COUNT, "train": v1.TRAIN_COUNT},
            "status": STATUS,
        }
        gap = {
            "manifest_kind": COST_GAP_MANIFEST_KIND,
            "status": STATUS,
            "v1_numeric_cache": {
                "sha256": "c" * 64,
                "manifest_sha256": _sha(v1.canonical_json_bytes(cache)),
            },
            "final_holdout": {"rows_in_sidecar": 0, "used_for_training_or_selection": False},
        }
        parity = {
            "fixture": {"max_absolute_error": 0.0, "top1_equal": True},
            "dev": {
                "record_count": v1.DEV_COUNT,
                "max_absolute_error": 0.0,
                "top1_mismatch_count": 0,
                "top1_equal": True,
            },
        }
        return {
            "cache": cache,
            "gap": gap,
            "experiment": {
                "schema_version": SCHEMA_VERSION,
                "report_kind": EXPERIMENT_REPORT_KIND,
                "status": STATUS,
                "raw_text_in_report": False,
                "raw_stable_ids_in_report": False,
                "issue": 21,
                "final_holdout_used": False,
                "decision": {"adopted": "C2"},
                "selection": {self.KEY: {"epoch": EPOCHS}},
                "per_model": {self.KEY: {"dev": {"correct": 1_639, "harm": 38, "rescue": 91}}},
                "independent_recomputation": {"matches": True},
            },
            "training": {
                **self._header("sakura_rerank_tiny_r2_training"),
                "gate_a_status": v1.EXPECTED_GATE_STATUS,
                "seed": SEED,
                "parameter_count": 1_900_000,
                "data": {
                    "final_holdout_used": False,
                    "cache_manifest_sha256": _sha(v1.canonical_json_bytes(cache)),
                    "cost_gap_manifest_sha256": _sha(v1.canonical_json_bytes(gap)),
                },
                "recipe": _recipe(),
                "hyperparameters": _hyperparameters(),
                "environment": {
                    "python": "3.13",
                    "torch": "2",
                    "cuda": "13",
                    "gpu": "GPU",
                    "gpu_total_memory_bytes": 1,
                    "peak_allocated_bytes": 1,
                    "deterministic_algorithms": True,
                },
                "checkpoint": {"file": "model.pt", "bytes": 1, "sha256": "d" * 64},
                "dev_single_evaluation": {"top1_correct": 1_639, "harm_count": 38, "rescue_count": 91},
            },
            "export": {
                **self._header("sakura_rerank_tiny_r2_onnx_export"),
                "checkpoint_sha256": "d" * 64,
                "parameter_count": 1_900_000,
                "artifacts": {
                    "fp32": {"file": "fp32.onnx", "bytes": 1_000, "sha256": "e" * 64, "parity": parity},
                    "int8": {"file": "int8.onnx", "bytes": 1_000, "sha256": "f" * 64, "parity": parity},
                },
            },
            "fp32": self._benchmark("fp32.onnx", "e" * 64),
            "int8": self._benchmark("int8.onnx", "f" * 64),
        }

    def _publish(self, root: Path, documents: dict[str, dict[str, Any]]) -> Any:
        paths = {name: root / f"{name}.json" for name in documents}
        for name, document in documents.items():
            _write_json(paths[name], document)
        return publish_evidence(
            paths["cache"],
            paths["gap"],
            paths["experiment"],
            paths["training"],
            paths["export"],
            paths["fp32"],
            paths["int8"],
            root / "out" / self.MANIFEST,
            root / "out" / self.REPORT,
            base_git_sha="a" * 40,
            nvidia_driver="610.47",
        )

    def test_consistent_evidence_is_bound_by_hash(self) -> None:
        documents = self._documents()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._publish(root, documents)
            manifest_raw = (root / "out" / self.MANIFEST).read_bytes()
            report_raw = (root / "out" / self.REPORT).read_bytes()
            manifest, report = json.loads(manifest_raw), json.loads(report_raw)
            self.assertEqual(manifest_raw, v1.canonical_json_bytes(manifest))
            self.assertEqual(report_raw, v1.canonical_json_bytes(report))
            self.assertEqual(
                report["model_manifest"],
                {"file": self.MANIFEST, "bytes": len(manifest_raw), "sha256": _sha(manifest_raw)},
            )
            self.assertEqual(
                manifest["implementation"]["sha256"], _sha(Path(r2.__file__).read_bytes())
            )
            self.assertEqual(
                manifest["implementation"]["v1_dependency"]["sha256"],
                _sha(Path(v1.__file__).read_bytes()),
            )
            for label, name in (
                ("issue_21_experiment_report", "experiment"),
                ("training_report", "training"),
                ("fp32_benchmark_report", "fp32"),
            ):
                self.assertEqual(
                    manifest["source_reports"][label]["sha256"],
                    _sha((root / f"{name}.json").read_bytes()),
                )
            self.assertEqual(manifest["exports"], documents["export"]["artifacts"])
            self.assertEqual(manifest["training"]["environment"]["nvidia_driver"], "610.47")
            self.assertEqual(
                report["issue_21_adoption"]["experiment_report_sha256"],
                _sha((root / "experiment.json").read_bytes()),
            )
            quality = report["quality_dev_only"]
            self.assertEqual(quality["relative_error_reduction"], round(53 / 202, 10))
            self.assertEqual(quality["baseline_correct_harm_rate"], round(38 / 1_586, 10))
            self.assertFalse(report["gates"]["gate_a_pass"])
            self.assertFalse(report["production_change_authorized"])
            self.assertIn("dev_harm_rate_at_most_0_25_percent", report["gates"]["unmet_checks"])

    def test_inconsistent_or_malformed_evidence_publishes_nothing(self) -> None:
        cases: dict[str, tuple[str, Callable[[dict[str, Any]], Any], str]] = {
            "extra field in a copied subtree": (
                "training",
                lambda value: value["environment"].update(notes="x"),
                "environment fields differ",
            ),
            "long string in a copied subtree": (
                "training",
                lambda value: value["environment"].update(gpu="x" * 200),
                "longer than the fixed contract",
            ),
            "benchmark of another model": (
                "fp32",
                lambda value: value["model"].update(sha256="0" * 64),
                "linkage is inconsistent",
            ),
            "missing benchmark contract": (
                "int8",
                lambda value: value.update(contract=None),
                "int8.contract fields differ",
            ),
            "failure count as false": (
                "fp32",
                lambda value: value["contract"].update(failure_count=False),
                "JSON type outside",
            ),
            "latency as true": (
                "fp32",
                lambda value: value["latency_ms"].update(p95=True),
                "JSON type outside",
            ),
            "measured runs as float": (
                "int8",
                lambda value: value["contract"].update(measured_runs=10_000.0),
                "JSON type outside",
            ),
            "null data section": ("training", lambda value: value.update(data=None), "malformed"),
            "no baseline-correct dev row": (
                "fp32",
                lambda value: value["quality"].update(baseline_top1_correct=0),
                "dev quality counts",
            ),
            "recipe flag as integer": (
                "training",
                lambda value: value["recipe"].update(dev_used_for_selection=0),
                "does not reproduce",
            ),
            "other dev outcome": (
                "training",
                lambda value: value["dev_single_evaluation"].update(harm_count=37),
                "does not reproduce",
            ),
            "stable-id flag missing": (
                "export",
                lambda value: value.pop("raw_stable_ids_in_report"),
                "unexpected report contract",
            ),
            "sidecar bound to another cache manifest": (
                "gap",
                lambda value: value["v1_numeric_cache"].update(manifest_sha256="0" * 64),
                "fixed split contract",
            ),
            "nothing adopted": (
                "experiment",
                lambda value: value["decision"].update(adopted=None),
                "does not adopt",
            ),
        }
        for name, (target, mutate, message) in cases.items():
            documents = copy.deepcopy(self._documents())
            mutate(documents[target])
            with tempfile.TemporaryDirectory() as directory, self.subTest(name):
                root = Path(directory)
                with self.assertRaisesRegex(ResearchTinyR2Error, message):
                    self._publish(root, documents)
                self.assertFalse((root / "out").exists())


@unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch is an optional training dependency")
class ExportIdentityTests(unittest.TestCase):
    def test_checkpoint_identity_is_checked_before_any_input_or_output(self) -> None:
        import torch

        model = build_model()
        count = v1.model_parameter_count(model)
        valid = {
            "schema_version": SCHEMA_VERSION,
            "model_contract_version": MODEL_CONTRACT_VERSION,
            "model_name": MODEL_NAME,
            "parameter_count": count,
            "epoch": EPOCHS,
            "state_dict": model.state_dict(),
        }
        cases: dict[str, tuple[Any, str]] = {
            "schema version": ({**valid, "schema_version": SCHEMA_VERSION + 1}, "int8.onnx"),
            "model name": ({**valid, "model_name": "other"}, "int8.onnx"),
            "epoch": ({**valid, "epoch": EPOCHS - 1}, "int8.onnx"),
            "recorded parameter count": ({**valid, "parameter_count": count + 1}, "int8.onnx"),
            "not a checkpoint object": (torch.zeros(1), "int8.onnx"),
            "one path for both exports": (valid, "fp32.onnx"),
        }
        for name, (payload, int8_name) in cases.items():
            with tempfile.TemporaryDirectory() as directory, self.subTest(name):
                root = Path(directory)
                checkpoint = root / "model.pt"
                torch.save(payload, checkpoint)
                with self.assertRaises(ResearchTinyR2Error):
                    export_onnx(
                        checkpoint,
                        root / "cache.npz",
                        root / "cache.json",
                        root / "gap.npz",
                        root / "gap.json",
                        root / "fp32.onnx",
                        root / int8_name,
                        root / "export.json",
                    )
                self.assertEqual([path.name for path in root.iterdir()], ["model.pt"])


if __name__ == "__main__":
    unittest.main()
