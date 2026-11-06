"""Version2 policy/fallback orchestration on synthetic fixtures only."""
import json
import os
import unittest
from unittest.mock import patch

from sakura_rerank import current_tiny as current
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_payload import RunnerError
from sakura_rerank.evaluation_worker import Adapter
from sakura_rerank.test_use_registry import TestUseError
from tests import test_evaluation_runner as fixtures
from tests.test_current_tiny import facts


@unittest.skipUnless(os.name == "nt", "evaluation process containment targets Windows")
class ProductEvaluationTests(unittest.TestCase):
    put = fixtures.RunnerTests.put
    seal_evidence = fixtures.RunnerTests.seal_evidence
    seal_plan = fixtures.RunnerTests.seal_plan
    trusted_fixture = fixtures.RunnerTests.trusted_fixture
    ledger = fixtures.RunnerTests.ledger
    assert_terminal = fixtures.RunnerTests.assert_terminal
    seal_execution = fixtures.RunnerTests.seal_execution
    run_job = fixtures.RunnerTests.run_job

    def setUp(self):
        fixtures.RunnerTests.setUp(self)
        for i, row in enumerate(self.rows):
            row["product_state"] = facts(baseline_index=2 if i % 4 == 2 else 0,
                schedule_eligible=i % 4 != 3, selection_allowed=i % 4 != 2,
                evidence_tags=[1, 2, 1] if i % 4 == 1 else [1, 1, 1])
        self.experiment["version"] = 2
        model = next(m for m in self.experiment["models"] if m["model"] == "current_tiny")
        model["runs"] = {"shipped": "current-tiny"}
        self.experiment["comparisons"] = [[name, "baseline"] for m in self.experiment["models"] for name in m["runs"].values()]
        self.experiment["comparisons"].append(["r2-gated", "current-tiny"])
        self.put("policy", "policy", canonical_json_bytes(current.snapshot_policy(self.plan["artifacts"]["provenance"]["sha256"])))
        gate = json.loads((self.root / "gate.bin").read_bytes())
        gate["bindings"]["policy"] = self.plan["artifacts"]["policy"]["sha256"]
        self.put("gate", "gate", canonical_json_bytes(gate))
        gate["configuration"] = {"kind": current.POLICY, "source_head": current.HEAD}
        self.put("current-gate", "gate", canonical_json_bytes(gate))
        self.plan["models"]["current_tiny"]["gate"] = "current-gate"
        self.seal_all()

    def seal_all(self):
        self.put("test", "test", canonical_json_bytes({"kind": "evaluation_cohort", "version": 2, "cases": self.rows}))
        self.seal_execution()

    def test_actual_spawns_preserve_local_baseline_and_seven_run_family(self):
        with self.trusted_fixture():
            result = self.run_job()
        self.assert_terminal("completed")
        overall = result["metrics"]["overall"]
        self.assertEqual(result["baseline_contract"], "authenticated_local_selection")
        self.assertEqual((overall["record_count"], overall["baseline_correct"], overall["baseline_errors"]), (3000, 2249, 751))
        self.assertEqual(len(overall["models"]), 7)
        self.assertEqual(sum(m["attempted"] for m in result["models"]), 6000)
        self.assertTrue(all(m["process"]["exited"] for m in result["models"]))
        shipped, gated = overall["models"]["current-tiny"], overall["models"]["r2-gated"]
        self.assertEqual([shipped[k] for k in ("correction_success", "baseline_correct_destroyed", "wrong_to_different_wrong")], [750, 750, 0])
        self.assertEqual([gated[k] for k in ("correction_success", "baseline_correct_destroyed", "wrong_to_different_wrong")], [750, 0, 0])
        self.assertEqual(shipped["terminal_counts"]["not_eligible"], 1500)
        self.assertEqual(shipped["inference_attempts"], 1500)
        sealed = json.loads(next(self.registry.glob("observations-*.json")).read_bytes())
        self.assertEqual(len(sealed["product_policy_facts"]), 3000)
        self.assertEqual(len(sealed["candidate_counts"]), 3000)
        for i, case_key in enumerate(sealed["case_order"]):
            item = sealed["runs"]["current-tiny"]["observations"][case_key]
            if i % 4 < 2:
                self.assertEqual(item["ranking"], [1, 0, 2])
            else:
                self.assertEqual(item, {"status": "not_eligible", "ranking": None, "attempted": False})
        self.assertFalse(result["release_eligible"])
        self.rows[0]["product_state"]["baseline_index"] = 1
        self.seal_all()
        with self.trusted_fixture(), self.assertRaises(TestUseError):
            self.run_job()  # Changed policy facts cannot refresh consumed inputs.

    def test_all_ineligible_never_starts_model_but_keeps_every_case(self):
        for row in self.rows:
            row["product_state"]["schedule_eligible"] = False
        self.seal_all()
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", side_effect=AssertionError("model started")):
            result = self.run_job()
        self.assert_terminal("completed")
        self.assertEqual(result["status"], "complete")
        self.assertTrue(all(m["terminal"] == "all_ineligible" and m["process"] is None for m in result["models"]))
        model = result["metrics"]["overall"]["models"]["current-tiny"]
        self.assertEqual((model["record_count"], model["inference_attempts"], model["effective_changes"]), (3000, 0, 0))

    def test_failure_maps_filtered_subset_back_without_losing_policy_fallbacks(self):
        def failed(requests, *args, **kwargs):
            self.assertEqual(len(requests), 1500)
            self.assertTrue(all(set(r) == {"reading", "left_context", "context_policy", "candidates"} for r in requests))
            return {"states": ["error"]+["unavailable"]*1499, "scores": [None]*1500, "complete": False,
                    "terminal": "worker_failure", "process": None, "attempted": 1}
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", failed):
            result = self.run_job()
        self.assertEqual(result["status"], "incomplete")
        counts = result["metrics"]["overall"]["models"]["current-tiny"]["terminal_counts"]
        self.assertEqual((counts["not_eligible"], counts["error"], counts["unavailable"]), (1500, 1, 1499))
        self.assertEqual(sum(counts.values()), 3000)

    def test_missing_native_facts_consumes_test_before_any_model(self):
        del self.rows[0]["product_state"]["evidence_tags"]
        self.seal_all()
        with self.trusted_fixture(), patch("sakura_rerank.evaluation_runner.execute_model", side_effect=AssertionError("model started")):
            with self.assertRaises(ValueError):
                self.run_job()
        self.assert_terminal("failed")

    def test_current_baseline_cannot_be_replaced_with_margin_gate(self):
        gate = json.loads((self.root / "current-gate.bin").read_bytes())
        gate["configuration"] = {"kind": "score_margin", "threshold": 0., "operator": ">"}
        self.put("current-gate", "gate", canonical_json_bytes(gate))
        self.seal_execution()
        with self.trusted_fixture(), self.assertRaises(RunnerError):
            self.run_job()
        self.assertEqual(self.ledger(), [])

    def test_real_current_adapter_rejects_wrong_weights_before_test(self):
        adapter = Adapter(current.current_factory, current.validate_current)
        self.adapters["current"] = adapter
        model = next(m for m in self.experiment["models"] if m["model"] == "current_tiny")
        model.update(adapter="current", adapter_identity=adapter.identity(), feature_width=6)
        self.experiment["limits"]["request_seconds"] = .4
        self.seal_execution()
        with self.trusted_fixture(), self.assertRaises(RunnerError):
            self.run_job()
        self.assertEqual(self.ledger(), [])

    def test_legacy_policy_cannot_be_rebound_into_product_snapshot_evaluation(self):
        self.put("policy", "policy", canonical_json_bytes({"legacy_policy": True}))
        for name in ("gate", "current-gate"):
            gate = json.loads((self.root/(name+".bin")).read_bytes())
            gate["bindings"]["policy"] = self.plan["artifacts"]["policy"]["sha256"]
            self.put(name, "gate", canonical_json_bytes(gate))
        self.seal_execution()
        with self.trusted_fixture(), self.assertRaises(RunnerError):
            self.run_job()
        self.assertEqual(self.ledger(), [])


if __name__ == "__main__":
    unittest.main()
