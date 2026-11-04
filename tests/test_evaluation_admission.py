from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank import evaluation_admission as admission
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.splitter import audit_evaluation_partitions
from sakura_rerank.test_use_registry import (
    EMPTY_HEAD, TestUseError, initialize_registry, inspect_registry,
)
from tests.test_evaluation_protocol import populations


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class EvaluationAdmissionTests(unittest.TestCase):
    """Synthetic attestations exercise access sequencing, never real Gold truth."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "artifacts"
        self.root.mkdir()
        self.registry = self.base / "registry"
        self.anchor = self.base / "head.json"
        initialize_registry(self.registry)
        admission.initialize_anchor(self.registry, self.anchor)
        self.plan_path = self.root / "plan.json"
        self.plan = {"kind": "evaluation_access_plan", "schema_version": 1,
                     "artifacts": {}, "data": {}, "models": {}}
        for role in admission.DATA_ROLES - {"partition", "tokens"}:
            self.put(role, role, canonical_json_bytes({"synthetic_role": role}))
            self.plan["data"][role] = role
        history, groups = populations()
        receipt, tokens = audit_evaluation_partitions(history, groups)
        # Counts are deliberately synthetic. No 3,000-case Gold population exists.
        receipt["populations"]["test"]["count"] = 3000
        for role, value in (("partition", receipt), ("tokens", tokens)):
            self.put(role, role, canonical_json_bytes(value))
            self.plan["data"][role] = role
        self.evidence = {
            "kind": "independent_gold_evidence", "schema_version": 1,
            "bindings": {}, "audit_completed": 1000, "audit_valid": 1000,
            "valid_test_count": 3000, "oracle6_present": 3000,
        }
        for role in admission.MODEL_ROLES - {"gate"}:
            self.put(role, role, ("synthetic-" + role).encode())
        gate = {
            "kind": "frozen_gate", "schema_version": 1,
            "bindings": {role: self.plan["artifacts"][role]["sha256"]
                         for role in {"weights", "tokenizer", "features", "calibration", "policy"}},
            "safety_threshold": .0025, "configuration": {"fixture_only": True},
        }
        self.put("gate", "gate", canonical_json_bytes(gate))
        for name in ("v1", "r2", "issue29", "current_tiny"):
            self.plan["models"][name] = {role: role for role in admission.MODEL_ROLES}
        self.seal_evidence()

    def put(self, key, role, raw):
        path = self.root / (key + ".bin")
        path.write_bytes(raw)
        self.plan["artifacts"][key] = {
            "path": path.name, "role": role, "sha256": digest(raw), "bytes": len(raw),
        }

    def seal_evidence(self):
        self.evidence["bindings"] = {
            role: self.plan["artifacts"][self.plan["data"][role]]["sha256"]
            for role in admission.DATA_ROLES
        }
        self.put("quality", "quality", canonical_json_bytes(self.evidence))
        self.plan["data"]["quality"] = "quality"
        self.seal_plan()

    def seal_plan(self):
        raw = canonical_json_bytes(self.plan)
        self.plan_path.write_bytes(raw)
        self.plan_sha = digest(raw)

    def trusted_fixture(self):
        return patch.object(admission, "VERIFIED_GOLD_CERTIFICATES",
                            frozenset({self.plan["artifacts"]["quality"]["sha256"]}))

    def access(self):
        return admission.access_test(artifact_root=self.root, plan_path=self.plan_path,
                                     expected_plan_sha256=self.plan_sha,
                                     registry=self.registry, anchor=self.anchor)

    def ledger(self):
        return [json.loads(line) for line in (self.registry / "events.jsonl").read_bytes().splitlines()]

    def assert_terminal(self, outcome):
        events = self.ledger()
        self.assertEqual([e["kind"] for e in events], ["reserved", outcome])
        head = json.loads(self.anchor.read_bytes())["head_sha256"]
        self.assertEqual(inspect_registry(self.registry, expected_head=head)["active"], 0)

    def assert_rejected_before_reservation(self):
        with self.assertRaises((admission.AdmissionError, TestUseError)):
            with self.access():
                self.fail("unexpected Test access")
        self.assertEqual(self.ledger(), [])

    def test_empty_trust_store_refuses_ai_or_self_reported_evidence_before_payloads(self):
        self.assertEqual(admission.VERIFIED_GOLD_CERTIFICATES, frozenset())
        with patch.object(admission._Artifact, "authenticate", side_effect=AssertionError("payload opened")):
            self.assert_rejected_before_reservation()

    def test_reservation_and_external_head_precede_test_open_and_result_is_durable(self):
        original = admission._Artifact.authenticate
        read_roles = []

        def observe(artifact, *, retain):
            read_roles.append(artifact.role)
            if artifact.role == "test":
                self.assertEqual([e["kind"] for e in self.ledger()], ["reserved"])
                head = json.loads(self.anchor.read_bytes())["head_sha256"]
                self.assertEqual(inspect_registry(self.registry, expected_head=head)["active"], 1)
            return original(artifact, retain=retain)

        with self.trusted_fixture(), patch.object(admission._Artifact, "authenticate", observe):
            with self.access() as access:
                self.assertEqual(access.artifacts["test"], (self.root / "test.bin").read_bytes())
                self.assertNotIn("train", access.artifacts)
                access.complete(b'{"synthetic":true}')
        self.assertEqual(read_roles[-1], "test")
        self.assert_terminal("completed")
        results = list(self.registry.glob("result-*.json"))
        self.assertEqual(len(results), 1)
        self.assertEqual(self.ledger()[-1]["result_sha256"], digest(results[0].read_bytes()))

    def test_plan_must_match_external_hash(self):
        self.plan_path.write_bytes(self.plan_path.read_bytes() + b" ")
        with self.trusted_fixture():
            self.assert_rejected_before_reservation()

    def test_catalog_rejects_traversal_aliases_unreferenced_and_missing_models(self):
        original = json.loads(json.dumps(self.plan))
        mutations = [
            lambda p: p["artifacts"]["train"].update(path="../artifacts/train.bin"),
            lambda p: p["artifacts"]["train"].update(path="test.bin"),
            lambda p: p["models"].pop("v1"),
            lambda p: p["data"].update(train="test"),
            lambda p: p["artifacts"]["train"].update(bytes=True),
            lambda p: p["artifacts"]["train"].update(bytes=admission.MAX_ARTIFACT_BYTES + 1),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.plan = json.loads(json.dumps(original))
                mutate(self.plan)
                self.seal_plan()
                with self.trusted_fixture():
                    self.assert_rejected_before_reservation()
        self.plan = original
        self.put("unused", "weights", b"unused")
        self.seal_plan()
        with self.trusted_fixture():
            self.assert_rejected_before_reservation()

    def test_hardlink_alias_rejected_before_any_payload(self):
        (self.root / "train.bin").unlink()
        os.link(self.root / "test.bin", self.root / "train.bin")
        self.plan["artifacts"]["train"].update(self.plan["artifacts"]["test"], path="train.bin", role="train")
        self.seal_plan()
        with self.trusted_fixture():
            self.assert_rejected_before_reservation()

    def test_non_test_hash_mismatch_does_not_consume_test(self):
        path = self.root / "weights.bin"
        path.write_bytes(b"X" * path.stat().st_size)
        with self.trusted_fixture():
            self.assert_rejected_before_reservation()

    def test_quality_counts_cannot_be_waived_even_for_recognized_fixture(self):
        original = dict(self.evidence)
        for fields in ({"audit_valid": 994}, {"audit_valid": 995, "audit_completed": 1000},
                       {"audit_completed": 999, "audit_valid": 999}, {"valid_test_count": 2999},
                       {"oracle6_present": 2909}, {"audit_valid": True}):
            with self.subTest(fields=fields):
                self.evidence = dict(original, **fields)
                self.seal_evidence()
                with self.trusted_fixture():
                    self.assert_rejected_before_reservation()

    def test_quality_binding_cannot_follow_changed_label_policy(self):
        self.put("policy", "policy", b"changed policy")
        self.seal_plan()  # Deliberately do not reissue the evidence.
        with self.trusted_fixture():
            self.assert_rejected_before_reservation()

    def test_gate_must_bind_calibration_model_and_unrelaxed_safety(self):
        original = json.loads((self.root / "gate.bin").read_bytes())
        for change in ("calibration", "weights", "safety"):
            with self.subTest(change=change):
                gate = json.loads(json.dumps(original))
                if change == "safety":
                    gate["safety_threshold"] = .003
                else:
                    gate["bindings"][change] = "f" * 64
                self.put("gate", "gate", canonical_json_bytes(gate))
                self.seal_plan()
                with self.trusted_fixture():
                    self.assert_rejected_before_reservation()

    def test_partition_leakage_or_token_mismatch_does_not_reserve(self):
        receipt = json.loads((self.root / "partition.bin").read_bytes())
        for change in ("leakage", "tokens", "count"):
            altered = json.loads(json.dumps(receipt))
            if change == "leakage":
                altered["cross_population_groups"]["bounded_input_exact"] = 1
            elif change == "tokens":
                altered["test_reuse_tokens_sha256"] = "f" * 64
            else:
                altered["populations"]["test"]["count"] = 2999
            self.put("partition", "partition", canonical_json_bytes(altered))
            self.seal_evidence()
            with self.trusted_fixture():
                self.assert_rejected_before_reservation()

    def test_test_hash_mismatch_is_failed_and_consumed(self):
        path = self.root / "test.bin"
        path.write_bytes(b"X" * path.stat().st_size)
        with self.trusted_fixture():
            with self.assertRaisesRegex(admission.AdmissionError, "bytes differ"):
                with self.access():
                    self.fail("changed Test was exposed")
            self.assert_terminal("failed")
            with self.assertRaisesRegex(TestUseError, "already consumed"):
                with self.access():
                    self.fail("reused consumed Test")

    def test_body_exception_records_failed_and_preserves_error(self):
        with self.trusted_fixture(), self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with self.access():
                raise RuntimeError("synthetic failure")
        self.assert_terminal("failed")

    def test_exit_without_explicit_completion_is_failed(self):
        with self.trusted_fixture(), self.assertRaisesRegex(admission.AdmissionError, "without an explicit"):
            with self.access():
                pass
        self.assert_terminal("failed")

    def test_completion_twice_is_failed(self):
        with self.trusted_fixture(), self.assertRaisesRegex(admission.AdmissionError, "already has"):
            with self.access() as access:
                access.complete(b"{}")
                access.complete(b"{}")
        self.assert_terminal("failed")

    def test_snapshot_bytes_do_not_change_when_files_change(self):
        with self.trusted_fixture(), self.access() as access:
            before = dict(access.artifacts)
            (self.root / "test.bin").write_bytes(b"changed test")
            (self.root / "weights.bin").write_bytes(b"changed weights")
            self.assertEqual(dict(access.artifacts), before)
            with self.assertRaises(TypeError):
                access.artifacts["test"] = b"change"
            access.complete(b"{}")
        self.assert_terminal("completed")
        with self.assertRaisesRegex(admission.AdmissionError, "closed"):
            access.complete(b"{}")

    def test_replaced_file_is_rejected_before_reading_its_bytes(self):
        original = admission._Artifact.authenticate

        def replace(artifact, *, retain):
            if artifact.role == "weights":
                replacement = self.root / "replacement.bin"
                replacement.write_bytes(artifact.path.read_bytes())
                os.replace(replacement, artifact.path)
            return original(artifact, retain=retain)

        with self.trusted_fixture(), patch.object(admission._Artifact, "authenticate", replace):
            self.assert_rejected_before_reservation()

    def test_anchor_failure_before_test_open_records_failure_without_opening_test(self):
        original = admission.write_bytes_atomic
        calls = 0

        def fail_once(path, raw):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("synthetic anchor write failure")
            original(path, raw)

        original_read = admission._Artifact.authenticate

        def no_test(artifact, *, retain):
            self.assertNotEqual(artifact.role, "test")
            return original_read(artifact, retain=retain)

        with self.trusted_fixture(), patch.object(admission, "write_bytes_atomic", fail_once), \
                patch.object(admission._Artifact, "authenticate", no_test), \
                self.assertRaisesRegex(OSError, "synthetic anchor"):
            with self.access():
                self.fail("Test exposed without external head")
        self.assert_terminal("failed")

    def test_persistent_anchor_failure_requires_reconciliation_and_blocks_retry(self):
        with self.trusted_fixture(), patch.object(admission, "write_bytes_atomic", side_effect=OSError("disk")), \
                self.assertRaisesRegex(admission.AdmissionError, "reconciliation"):
            with self.access():
                self.fail("Test exposed")
        self.assertEqual([e["kind"] for e in self.ledger()], ["reserved", "failed"])
        with self.trusted_fixture(), self.assertRaisesRegex(TestUseError, "external commitment"):
            with self.access():
                self.fail("stale anchor accepted")

    def test_terminal_failure_is_not_reported_as_success_or_followed_by_second_terminal(self):
        with self.trusted_fixture(), patch.object(admission, "finish_test", side_effect=OSError("disk")), \
                self.assertRaisesRegex(admission.AdmissionError, "completion needs reconciliation"):
            with self.access() as access:
                access.complete(b"{}")
        self.assertEqual([e["kind"] for e in self.ledger()], ["reserved"])
        self.assertEqual(len(list(self.registry.glob("result-*.json"))), 1)

    def test_completed_anchor_failure_keeps_only_one_terminal_and_blocks_retry(self):
        original = admission.write_bytes_atomic
        calls = 0

        def fail_terminal(path, raw):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("terminal anchor failed")
            original(path, raw)

        with self.trusted_fixture(), patch.object(admission, "write_bytes_atomic", fail_terminal), \
                self.assertRaisesRegex(admission.AdmissionError, "completion needs reconciliation"):
            with self.access() as access:
                access.complete(b"{}")
        self.assertEqual([e["kind"] for e in self.ledger()], ["reserved", "completed"])
        with self.assertRaisesRegex(admission.AdmissionError, "closed"):
            access.complete(b"{}")
        with self.trusted_fixture(), self.assertRaisesRegex(TestUseError, "external commitment"):
            with self.access():
                self.fail("stale anchor accepted")

    def test_result_write_failure_is_failed_and_never_claims_a_result(self):
        with self.trusted_fixture(), patch.object(admission, "_write_once", side_effect=OSError("result disk")), \
                self.assertRaisesRegex(OSError, "result disk"):
            with self.access() as access:
                access.complete(b"{}")
        self.assert_terminal("failed")
        self.assertIsNone(self.ledger()[-1]["result_sha256"])

    def test_reservation_fsync_failure_leaves_evidence_and_requires_reconciliation(self):
        with self.trusted_fixture(), patch("sakura_rerank.test_use_registry.os.fsync", side_effect=OSError("fsync")), \
                self.assertRaisesRegex(admission.AdmissionError, "reservation write needs"):
            with self.access():
                self.fail("Test exposed after failed reservation")
        self.assertEqual([e["kind"] for e in self.ledger()], ["reserved"])
        with self.trusted_fixture(), self.assertRaisesRegex(TestUseError, "external commitment"):
            with self.access():
                self.fail("retry after uncertain reservation")

    def test_truncated_ledger_detected_by_external_head(self):
        with self.trusted_fixture(), self.access() as access:
            access.complete(b"{}")
        (self.registry / "events.jsonl").write_bytes(b"")
        with self.trusted_fixture(), self.assertRaisesRegex(TestUseError, "external commitment"):
            with self.access():
                self.fail("truncated ledger accepted")

    def test_anchor_cannot_be_reused_for_another_registry(self):
        other = self.base / "other-registry"
        initialize_registry(other)
        self.registry = other
        with self.trusted_fixture(), self.assertRaisesRegex(admission.AdmissionError, "different registry"):
            with self.access():
                self.fail("foreign anchor accepted")

    def test_all_byte_budget_limits_reject_before_reservation(self):
        for constant in ("MAX_PLAN_BYTES", "MAX_METADATA_BYTES", "MAX_TOTAL_BYTES", "MAX_SNAPSHOT_BYTES"):
            with self.subTest(constant=constant), self.trusted_fixture(), patch.object(admission, constant, 16):
                self.assert_rejected_before_reservation()

    def test_nested_access_rejected_without_a_second_reservation(self):
        with self.trusted_fixture(), self.access() as access:
            with self.assertRaisesRegex(admission.AdmissionError, "active or interrupted"):
                with self.access():
                    self.fail("concurrent access")
            access.complete(b"{}")
        self.assert_terminal("completed")

    def test_anchor_reinitialization_and_in_registry_anchor_are_rejected(self):
        with self.assertRaises(FileExistsError):
            admission.initialize_anchor(self.registry, self.anchor)
        with self.assertRaisesRegex(admission.AdmissionError, "outside the registry"):
            admission.initialize_anchor(self.registry, self.registry / "head.json")
        self.assertEqual(json.loads(self.anchor.read_bytes())["head_sha256"], EMPTY_HEAD)

    def test_json_duplicate_nonfinite_and_depth_are_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[' * 2000):
            with self.subTest(raw=raw[:30]), self.assertRaises(admission.AdmissionError):
                admission._json(raw)


if __name__ == "__main__":
    unittest.main()
