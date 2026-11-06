"""Execute in-memory synthetic ONNX graphs; no historic model or Test reads."""
import importlib.util
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.evaluation_worker import Adapter, WorkerError, execute_metrics, execute_model, gru_factory, validate_gru
from sakura_rerank.research_tiny import character_ids
from tests.test_evaluation_runner import request, descendant_factory, failing_factory, synthetic_validate


def artifacts(width):
    import onnx
    from onnx import helper as h, TensorProto as T
    names = ("context_ids", "context_lengths", "reading_ids", "reading_lengths", "candidate_ids", "candidate_lengths", "features", "candidate_mask")
    shapes = ((1, 64), (1,), (1, 32), (1,), (1, 6, 32), (1, 6), (1, 6, width), (1, 6))
    types = (T.INT64, T.INT64, T.INT64, T.INT64, T.INT64, T.INT64, T.FLOAT, T.BOOL)
    inputs = [h.make_tensor_value_info(name, typ, shape) for name, typ, shape in zip(names, types, shapes)]
    graph = h.make_graph([
        h.make_node("ReduceSum", ["context_ids", "axis"], ["context_sum"], keepdims=1),
        h.make_node("Cast", ["context_sum"], ["context_float"], to=T.FLOAT),
        h.make_node("Gather", ["features", "column"], ["cost"], axis=2),
        h.make_node("Add", ["cost", "context_float"], ["scores"]),
    ], "synthetic-cpu-contract", inputs, [h.make_tensor_value_info("scores", T.FLOAT, (1, 6))],
       [h.make_tensor("axis", T.INT64, (1,), [1]), h.make_tensor("column", T.INT64, (), [0])])
    model = h.make_model(graph, opset_imports=[h.make_opsetid("", 13)], ir_version=10)
    onnx.checker.check_model(model)
    return {"weights": model.SerializeToString(),
            "tokenizer": canonical_json_bytes({"kind": "tiny_character_hash", "version": 1, "vocab_size": 13312,
                "context_length": 64, "reading_length": 32, "surface_length": 32, "truncation": "prefix"}),
            "features": canonical_json_bytes({"kind": "tiny_candidate_features", "version": 1,
                "width": width, "cost_gap_scale": 1000 if width == 7 else None}), "gate": b"{}"}


@unittest.skipUnless(os.name == "nt" and importlib.util.find_spec("onnx") and importlib.util.find_spec("onnxruntime"), "Windows and optional ONNX test dependencies required")
class CpuAdapterTests(unittest.TestCase):
    def test_actual_cpu_ort_uses_bounded_session_context_and_frozen_feature_widths(self):
        limits = {"startup_seconds": 15., "request_seconds": 2., "model_seconds": 30., "shutdown_seconds": 1.}
        for width in (6, 7):
            with self.subTest(width=width):
                result = execute_model([request(), request(context="確定文脈")], artifacts(width), Adapter(gru_factory, validate_gru),
                                       width, limits, deadline=time.monotonic()+40)
                self.assertTrue(result["complete"])
                context_sum = sum(character_ids("確定文脈", 64)[0])
                self.assertEqual(result["scores"][0], (0., -.5, -1., 0., 0., 0.))
                self.assertEqual(result["scores"][1], tuple(context_sum + x for x in (0., -.5, -1., 0., 0., 0.)))
                self.assertTrue(result["process"]["exited"])

    def test_tokenizer_mismatch_and_duplicate_json_are_rejected(self):
        value = artifacts(6)
        value["tokenizer"] = b'{"kind":"legacy-deberta"}'
        with self.assertRaises(WorkerError):
            validate_gru(value, 6)
        value["tokenizer"] = b'{"kind":"a","kind":"b"}'
        with self.assertRaises(ValueError):
            validate_gru(value, 6)


@unittest.skipUnless(os.name == "nt", "evaluation process containment targets Windows")
class SharedMemoryCleanupTests(unittest.TestCase):
    def test_containment_failure_never_starts_adapter_or_descendant(self):
        limits = {"startup_seconds": 5., "request_seconds": .2, "model_seconds": 10., "shutdown_seconds": 1.}
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory)/'must-not-exist.pid'
            with patch("sakura_rerank.evaluation_worker._WindowsJob", side_effect=WorkerError("containment refused")):
                with self.assertRaises(WorkerError):
                    execute_model([request()], {"weights": ('normal|'+str(pid_path)).encode()},
                        Adapter(descendant_factory, synthetic_validate), 0, limits, deadline=time.monotonic()+12)
            self.assertFalse(pid_path.exists())

    def test_native_descendants_terminate_on_normal_exit_crash_and_timeout(self):
        limits = {"startup_seconds": 5., "request_seconds": .2, "model_seconds": 10., "shutdown_seconds": 1.}
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("normal", "crash", "hang"):
                with self.subTest(mode=mode):
                    pid_path = Path(directory)/(mode+'.pid')
                    result = execute_model([request()], {"weights": (mode+'|'+str(pid_path)).encode()},
                        Adapter(descendant_factory, synthetic_validate), 0, limits, deadline=time.monotonic()+12)
                    self.assertTrue(pid_path.exists())
                    self.assertEqual(result["process"]["job"]["active_remaining"], 0)
                    self.assertGreaterEqual(result["process"]["job"]["terminated_processes"], 1)
                    self.assertEqual(result["complete"], mode == "normal")
                    self.assertEqual(result["states"], [{"normal": "complete", "crash": "error", "hang": "timeout"}[mode]])

    def test_metrics_timeout_releases_memory_and_process(self):
        created = []
        def track(*args, **kwargs):
            memory = SharedMemory(*args, **kwargs)
            if kwargs.get("create"):
                created.append(memory.name)
            return memory
        with patch("sakura_rerank.evaluation_worker.SharedMemory", side_effect=track):
            with self.assertRaises(WorkerError):
                execute_metrics({}, .01, .2)
        self.assertEqual(len(created), 2)
        for name in created:
            with self.assertRaises(FileNotFoundError):
                SharedMemory(name)

    def test_second_allocation_failure_still_releases_first_block(self):
        created = []
        def track(*args, **kwargs):
            if kwargs.get("create") and created:
                raise OSError("synthetic allocation failure")
            memory = SharedMemory(*args, **kwargs)
            created.append(memory.name)
            return memory
        limits = {"startup_seconds": 2., "request_seconds": .1, "model_seconds": 5., "shutdown_seconds": .2}
        with patch("sakura_rerank.evaluation_worker.SharedMemory", side_effect=track):
            with self.assertRaises(OSError):
                execute_model([request()], {"weights": b"hang"}, Adapter(failing_factory, synthetic_validate),
                              0, limits, deadline=time.monotonic()+8)
        self.assertEqual(len(created), 1)
        with self.assertRaises(FileNotFoundError):
            SharedMemory(created[0])

    def test_changed_adapter_identity_never_starts_or_allocates(self):
        with patch("sakura_rerank.evaluation_worker.SharedMemory", side_effect=AssertionError("allocated")):
            with self.assertRaises(WorkerError):
                execute_model([request()], {"weights": b"hang"}, Adapter(failing_factory, synthetic_validate),
                              0, {}, deadline=time.monotonic()+8, expected_identity={})

    def test_forced_termination_releases_both_owned_memory_blocks(self):
        created = []
        def track(*args, **kwargs):
            memory = SharedMemory(*args, **kwargs)
            if kwargs.get("create"):
                created.append(memory.name)
            return memory
        limits = {"startup_seconds": 2., "request_seconds": .1, "model_seconds": 5., "shutdown_seconds": .2}
        with patch("sakura_rerank.evaluation_worker.SharedMemory", side_effect=track):
            result = execute_model([request("い")], {"weights": b"hang"}, Adapter(failing_factory, synthetic_validate),
                                   0, limits, deadline=time.monotonic()+8)
        self.assertTrue(result["process"]["exited"])
        self.assertEqual(len(created), 2)
        for name in created:
            with self.assertRaises(FileNotFoundError):
                SharedMemory(name)


if __name__ == "__main__":
    unittest.main()
