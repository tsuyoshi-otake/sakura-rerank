"""Synthetic orchestration evidence, never an independent Gold certificate."""
from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from sakura_rerank import evaluation_admission as admission
from sakura_rerank.data.contracts import canonical_json_bytes, candidate_fingerprint, validate_conversion_candidates
from sakura_rerank.evaluation_payload import REQUIRED_SLICES, RunnerError
from sakura_rerank.evaluation_runner import _observations, run_evaluation
from sakura_rerank.evaluation_worker import Adapter, StaleResult, execute_model, gru_factory, runtime_identity, validate_gru
from sakura_rerank.test_use_registry import TestUseError
from tests import test_evaluation_admission as admission_fixtures


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def candidate(reading, surface, rank):
    cost = 100 + rank
    return {"rank": rank, "surface": surface, "local_cost": cost, "source_category": "system_dictionary",
            "fingerprint": candidate_fingerprint(surface, cost), "system_entry_index": rank,
            "segments": [{"reading_start": 0, "reading_end": len(reading.encode()), "text_start": 0,
                          "text_end": len(surface.encode()), "left_id": 0, "right_id": 0, "flags": 0,
                          "source_category": "system_dictionary"}]}


def request(reading="あ", context=""):
    return {"reading": reading, "left_context": context, "context_policy": "sakura_input_committed_same_session",
            "candidates": [candidate(reading, surface, rank) for rank, surface in enumerate(("A", "B", "C"))]}


def synthetic_validate(artifacts, width):
    if set(artifacts) != {"weights", "tokenizer", "features", "gate"} or width != 0:
        raise ValueError("synthetic artifact contract")


def synthetic_factory(artifacts, width):
    synthetic_validate(artifacts, width)
    class Scorer:
        def score(self, value):
            assert set(value) == {"reading", "left_context", "context_policy", "candidates"}
            assert len(value["candidates"]) <= 6
            return (0., {"あ": 3., "い": 4., "う": 1., "え": -1.}.get(value["reading"], 0.), -2., -3., -4., -5.)

        def close(self):
            pass
    return Scorer()


def failing_factory(artifacts, width):
    mode = artifacts["weights"].decode()
    if mode == "startup_hang":
        time.sleep(60)
    if mode == "startup_error":
        raise ValueError("private startup details")
    class Scorer:
        def score(self, value):
            if value["reading"] == "あ":
                return [0., 1., 2., 3., 4., 5.]
            if mode == "hang":
                time.sleep(60)
            if mode == "exit":
                os._exit(0)
            if mode == "crash":
                os._exit(7)
            if mode == "stale":
                raise StaleResult("private fingerprint details")
            if mode == "nan":
                return [float("nan")] * 6
            if mode == "shape":
                return [1.]
            raise ValueError("private request details")

        def close(self):
            if mode == "cleanup_hang":
                time.sleep(60)
    return Scorer()


def descendant_factory(artifacts, width):
    mode, path = artifacts["weights"].decode().split("|", 1)
    child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    Path(path).write_text(str(child.pid), encoding="ascii")
    class Scorer:
        def score(self, value):
            if mode == "crash":
                os._exit(0)
            if mode == "hang":
                time.sleep(60)
            return [0., 1., 2., 3., 4., 5.]

        def close(self):
            pass  # Deliberately leak the descendant: the executor must own it.
    return Scorer()


def mock_complete(requests, artifacts, adapter, width, limits, *, deadline, expected_identity=None, expected_runtime=None):
    return {"states": ["complete"]*len(requests), "scores": [(1., 0., 0., 0., 0., 0.)]*len(requests),
            "complete": True, "terminal": "complete", "request_count": len(requests),
            "attempted": len(requests), "process": None}


@unittest.skipUnless(os.name == "nt", "evaluation process containment targets Windows")
class RunnerTests(unittest.TestCase):
    # Reuse fixture construction, not the original28 tests via inheritance.
    put = admission_fixtures.EvaluationAdmissionTests.put
    seal_evidence = admission_fixtures.EvaluationAdmissionTests.seal_evidence
    seal_plan = admission_fixtures.EvaluationAdmissionTests.seal_plan
    trusted_fixture = admission_fixtures.EvaluationAdmissionTests.trusted_fixture
    ledger = admission_fixtures.EvaluationAdmissionTests.ledger
    assert_terminal = admission_fixtures.EvaluationAdmissionTests.assert_terminal

    def setUp(self):
        admission_fixtures.EvaluationAdmissionTests.setUp(self)
        self.adapters = {"synthetic": Adapter(synthetic_factory, synthetic_validate)}
        rows = []
        for i in range(3000):
            reading = "あいうえ"[i % 4]
            rows.append({"case_key": key(i), "component_key": key("component" + str(i % 2)), "input": request(reading),
                         "gold": "A" if i % 4 in (0, 3) else "B" if i % 4 == 1 else "C",
                         "tags": ["context-empty", "reading-short"]})
        rows[-1]["gold"] = "missing-synthetic-target"
        self.rows = rows
        self.evidence["oracle6_present"] = 2999
        self.put("test", "test", canonical_json_bytes({"kind": "evaluation_cohort", "version": 1, "cases": rows}))
        self.put("sampling", "sampling", canonical_json_bytes({"kind": "evaluation_sampling", "version": 1,
            "test_count": 3000, "component_count": 2, "independent_unit": "source_component", "dependence_evidence_sha256": key("synthetic-only")}))
        gate = json.loads((self.root / "gate.bin").read_bytes())
        gate["configuration"] = {"kind": "score_margin", "threshold": 3., "operator": ">"}
        self.put("gate", "gate", canonical_json_bytes(gate))
        models = [{"model": name, "adapter": "synthetic", "adapter_identity": self.adapters["synthetic"].identity(),
                   "feature_width": 0, "runs": {"ungated": name.replace("_", "-") + "-ungated", "gated": name.replace("_", "-") + "-gated"}}
                  for name in self.plan["models"]]
        self.experiment = {"kind": "evaluation_execution_plan", "version": 1, "runtime": runtime_identity(),
            "models": models, "primary": "r2-gated", "comparisons": [[name, "baseline"] for m in models for name in m["runs"].values()] + [["r2-gated", "current-tiny-gated"]],
            "slices": sorted(REQUIRED_SLICES), "limits": {"startup_seconds": 15., "request_seconds": 2., "model_seconds": 60.,
                "job_seconds": 180., "metrics_seconds": 30., "shutdown_seconds": 1.}}
        self.seal_execution()

    def seal_execution(self):
        self.put("experiment", "experiment", canonical_json_bytes(self.experiment))
        self.seal_evidence()

    def run_job(self):
        return run_evaluation(artifact_root=self.root, plan_path=self.plan_path, expected_plan_sha256=self.plan_sha,
                              registry=self.registry, anchor=self.anchor, adapters=self.adapters)

    def test_real_spawned_execution_seals_all_outputs_and_preserves_denominators(self):
        with self.trusted_fixture():
            result = self.run_job()
        self.assert_terminal("completed")
        self.assertEqual(result["status"], "complete")
        report = result["metrics"]["overall"]
        self.assertEqual((report["record_count"], report["baseline_correct"], report["baseline_errors"]), (3000, 1499, 1501))
        ungated, gated = [report["models"]["r2-" + name] for name in ("ungated", "gated")]
        self.assertEqual([ungated[k] for k in ("correction_success", "baseline_correct_destroyed", "wrong_to_different_wrong")], [750, 750, 750])
        self.assertEqual([gated[k] for k in ("correction_success", "baseline_correct_destroyed", "wrong_to_different_wrong")], [750, 0, 0])
        self.assertEqual(report["observed_candidate_oracle"]["6"]["numerator"], 2999)
        self.assertEqual(result["metrics"]["slices"]["unseen-dictionary"], {"record_count": 0, "metrics": None})
        self.assertEqual(result["metrics"]["slices"]["context-empty"]["record_count"], 3000)
        self.assertEqual(sum(m["attempted"] for m in result["models"]), 12000)
        self.assertTrue(all(m["process"]["exited"] for m in result["models"]))
        self.assertFalse(multiprocessing.active_children())
        persisted = next(self.registry.glob("observations-*.json")).read_bytes()
        self.assertEqual(hashlib.sha256(persisted).hexdigest(), result["sealed_observations_sha256"])
        self.assertNotIn(b'"gold"', persisted)
        sealed = json.loads(persisted)
        self.assertEqual(len(sealed["model_proposals"]), 4)
        self.assertEqual(len(sealed["case_order"]), 3000)
        # Recompute all sealed margin decisions directly, without model/Test reruns.
        for model in self.experiment["models"]:
            proposals = sealed["model_proposals"][model["model"]]
            for case_key, scores, count in zip(sealed["case_order"], proposals["scores"], sealed["candidate_counts"], strict=True):
                best = max(range(count), key=lambda i: (scores[i], -i))
                applied = best != 0 and scores[best]-scores[0] > 3.
                got = sealed["runs"][model["runs"]["gated"]]["observations"][case_key]
                self.assertEqual(got["status"], "applied" if applied else "abstained")
        public = canonical_json_bytes(result)
        self.assertNotIn(key(0).encode(), public)
        self.assertNotIn(b"missing-synthetic-target", public)
        self.assertFalse(result["release_eligible"])
        with self.trusted_fixture(), self.assertRaises(TestUseError):
            self.run_job()

    def test_empty_gold_trust_set_blocks_before_factory_or_test(self):
        with patch.object(admission._Artifact, "authenticate", side_effect=AssertionError("payload opened")):
            with self.assertRaises(admission.AdmissionError):
                self.run_job()
        self.assertEqual(self.ledger(), [])

    def test_research_gru_cannot_impersonate_current_product_through_an_alias(self):
        for alias in ("tiny-gru-onnx-v1", "renamed-adapter"):
            adapter = Adapter(gru_factory, validate_gru)
            self.adapters[alias] = adapter
            next(m for m in self.experiment["models"] if m["model"] == "current_tiny").update(
                adapter=alias, adapter_identity=adapter.identity(), feature_width=6)
            self.seal_execution()
            authenticate = admission._Artifact.authenticate
            def forbid_test(artifact, *, retain):
                self.assertNotEqual(artifact.role, "test")
                return authenticate(artifact, retain=retain)
            with self.trusted_fixture(), patch.object(admission._Artifact, "authenticate", forbid_test):
                with self.assertRaises(RunnerError):
                    self.run_job()
            self.assertEqual(self.ledger(), [])

    def test_unsupported_or_changed_execution_fails_before_test(self):
        mutations = [lambda e: e["models"][0].update(adapter="unsupported"),
                     lambda e: e["runtime"].update(python="different"),
                     lambda e: e["models"][0]["adapter_identity"]["factory"].update(source_sha256=key("changed")),
                     lambda e: e.update(comparisons=e["comparisons"][:-1]),
                     lambda e: e["limits"].update(request_seconds=0),
                     lambda e: e.update(slices=[]),
                     lambda e: e["models"][1].update(runs=e["models"][0]["runs"])]
        original = copy.deepcopy(self.experiment)
        authenticate = admission._Artifact.authenticate
        def forbid_test(artifact, *, retain):
            self.assertNotEqual(artifact.role, "test")
            return authenticate(artifact, retain=retain)
        for mutate in mutations:
            self.experiment = copy.deepcopy(original)
            mutate(self.experiment)
            self.seal_execution()
            with self.trusted_fixture(), patch.object(admission._Artifact, "authenticate", forbid_test):
                with self.assertRaises(RunnerError):
                    self.run_job()
            self.assertEqual(self.ledger(), [])

    def test_path_replacement_after_authentication_cannot_change_executed_plan(self):
        original = admission.access_test
        from contextlib import contextmanager
        @contextmanager
        def replace_paths(**kwargs):
            with original(**kwargs) as access:
                self.plan_path.write_bytes(b"changed after authentication")
                (self.root / "test.bin").write_bytes(b"changed after authentication")
                yield access
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.access_test", replace_paths), patch("sakura_rerank.evaluation_runner.execute_model", mock_complete):
            result = self.run_job()
        self.assertEqual(result["metrics"]["overall"]["record_count"], 3000)
        self.assert_terminal("completed")

    def test_invalid_cohort_is_consumed_failed_without_model_calls(self):
        self.rows[0]["input"]["candidates"][0]["fingerprint"] = "0"*16
        self.put("test", "test", canonical_json_bytes({"kind": "evaluation_cohort", "version": 1, "cases": self.rows}))
        self.seal_execution()
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", side_effect=AssertionError("model called")):
            with self.assertRaises(RunnerError):
                self.run_job()
        self.assert_terminal("failed")
        with self.trusted_fixture(), self.assertRaises(TestUseError):
            self.run_job()

    def test_metric_failure_preserves_sealed_predictions_and_consumption(self):
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", mock_complete), patch("sakura_rerank.evaluation_runner.execute_metrics", side_effect=RuntimeError("metric failed")):
            with self.assertRaises(RuntimeError):
                self.run_job()
        self.assert_terminal("failed")
        self.assertEqual(len(list(self.registry.glob("observations-*.json"))), 1)
        self.assertEqual(list(self.registry.glob("result-*.json")), [])

    def test_prediction_write_failure_does_not_score_or_complete(self):
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", mock_complete), patch("sakura_rerank.evaluation_runner._seal", side_effect=OSError("write failed")), patch("sakura_rerank.evaluation_runner.execute_metrics") as metrics:
            with self.assertRaises(OSError):
                self.run_job()
        self.assert_terminal("failed")
        metrics.assert_not_called()

    def test_incomplete_model_keeps_all_fallback_rows_and_explicit_result(self):
        def failure(*args, **kwargs):
            value = mock_complete(*args, **kwargs)
            value.update(complete=False, terminal="worker_failure", attempted=1,
                         states=["error"]+["unavailable"]*2999, scores=[None]*3000)
            return value
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", failure):
            result = self.run_job()
        self.assert_terminal("completed")  # Access result persisted; model comparison incomplete.
        self.assertEqual(result["status"], "incomplete")
        model = result["metrics"]["overall"]["models"]["r2-gated"]
        self.assertFalse(model["complete"])
        self.assertEqual(model["record_count"], 3000)
        self.assertEqual(model["effective_changes"], 0)
        self.assertEqual(model["terminal_counts"]["unavailable"], 2999)


class PayloadAndDecisionTests(unittest.TestCase):
    def test_strict_margin_ties_padding_and_all_failures(self):
        a, b = _observations((0., 3., 999., 999., 999., 999.), "complete", 2, 3.)
        self.assertEqual(a["ranking"], [1, 0])
        self.assertEqual(b["status"], "abstained")
        _, b = _observations((0., 3.00001, 0., 0., 0., 0.), "complete", 2, 3.)
        self.assertEqual(b["status"], "applied")
        a, _ = _observations((1., 1., 0., 0., 0., 0.), "complete", 2, 0.)
        self.assertEqual(a["ranking"], [0, 1])
        for state in ("timeout", "error", "stale", "malformed", "unavailable"):
            a, b = _observations(None, state, 2, 3.)
            self.assertEqual(a, b)
            self.assertIsNone(a["ranking"])
            self.assertEqual(a["attempted"], state != "unavailable")

    def test_native_candidate_contract_keeps_byte_offsets_and_unique_surfaces(self):
        value = request("はし")
        good = validate_conversion_candidates(value["reading"], value["candidates"])
        self.assertEqual(good, value["candidates"])
        for mode in ("rank", "offset", "fingerprint", "duplicate"):
            bad = copy.deepcopy(value["candidates"])
            if mode == "rank": bad[0]["rank"] = 1
            if mode == "offset": bad[0]["segments"][0]["reading_end"] = 2
            if mode == "fingerprint": bad[0]["fingerprint"] = "0"*16
            if mode == "duplicate": bad[1] = candidate("はし", "A", 1)
            with self.assertRaises(ValueError):
                validate_conversion_candidates("はし", bad)


@unittest.skipUnless(os.name == "nt", "evaluation process containment targets Windows")
class BoundedWorkerTests(unittest.TestCase):
    def test_fail_stop_lifecycle_uses_real_spawned_processes(self):
        limits = {"startup_seconds": 2., "request_seconds": .15, "model_seconds": 8., "shutdown_seconds": .2}
        for mode, expected in (("hang", "timeout"), ("exit", "error"), ("crash", "error"),
                               ("nan", "malformed"), ("shape", "malformed"), ("stale", "stale"), ("error", "error")):
            with self.subTest(mode=mode):
                result = execute_model([request(), request("い"), request("う")], {"weights": mode.encode()},
                                       Adapter(failing_factory, synthetic_validate), 0, limits, deadline=time.monotonic()+12)
                self.assertEqual(result["states"], ["complete", expected, "unavailable"])
                self.assertEqual(result["attempted"], 2)
                self.assertFalse(result["complete"])
                self.assertTrue(result["process"]["exited"])
        self.assertFalse(multiprocessing.active_children())

    def test_startup_and_cleanup_are_bounded_without_restarting(self):
        limits = {"startup_seconds": .2, "request_seconds": .2, "model_seconds": 4., "shutdown_seconds": .1}
        for mode in ("startup_hang", "startup_error", "cleanup_hang"):
            with self.subTest(mode=mode):
                # Give imports enough time while still bounding the intentionally stuck factory.
                limits["startup_seconds"] = 1.
                result = execute_model([request()], {"weights": mode.encode()}, Adapter(failing_factory, synthetic_validate),
                                       0, limits, deadline=time.monotonic()+6)
                self.assertFalse(result["complete"])
                self.assertTrue(result["process"]["exited"])
                self.assertEqual(result["request_count"], 1)
        self.assertFalse(multiprocessing.active_children())


if __name__ == "__main__":
    unittest.main()
