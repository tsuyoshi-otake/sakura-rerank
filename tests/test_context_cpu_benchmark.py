import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

from sakura_rerank.data.contracts import canonical_json_bytes

# The executable forces CPU-only environment at import. Restore it so this
# isolated serialization test cannot alter any other test's runtime policy.
with patch.dict(os.environ):
    sys.path.insert(0,"research/issue-40-context-contrast")
    try:
        spec=importlib.util.spec_from_file_location("context_benchmark_test","research/issue-40-context-contrast/benchmark_models.py")
        benchmark=importlib.util.module_from_spec(spec);spec.loader.exec_module(benchmark)
    finally:sys.path.pop(0)


class ContextCpuBenchmarkTests(unittest.TestCase):
    def test_numpy_timing_results_are_canonical_json_and_limits_stay_inclusive(self):
        result=benchmark.latency_summary(np.full(10000,2_000_000,dtype=np.int64),{})
        self.assertIs(result["latency_limits_passed"],True)
        self.assertIn(b'"p95_ms":2.0',canonical_json_bytes(result))

    def test_failures_or_limit_exceedance_do_not_pass(self):
        for samples,errors in (([1_000_000],{"RuntimeError":1}),([2_000_001],{})):
            result=benchmark.latency_summary(samples,errors)
            self.assertIs(result["latency_limits_passed"],False)
            canonical_json_bytes(result)


if __name__=="__main__":unittest.main()
