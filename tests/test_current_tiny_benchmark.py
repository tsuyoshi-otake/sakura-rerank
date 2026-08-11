from __future__ import annotations

import json
import math
import struct
import unittest

from sakura_rerank.current_tiny_benchmark import (
    BenchmarkError,
    Candidate,
    RESPONSE_MAGIC,
    benchmark_fixtures,
    decode_response,
    encode_request,
    fixture_hash,
    latency_summary,
)


class ProtocolTests(unittest.TestCase):
    def test_request_matches_v1_wire_contract(self) -> None:
        candidate = Candidate(9, 123, "候補")

        frame = encode_request(7, [candidate])

        payload_bytes = struct.unpack_from("<I", frame)[0]
        self.assertEqual(payload_bytes, len(frame) - 4)
        self.assertEqual(
            struct.unpack_from("<IHHQII", frame, 4),
            (0x524E_4B53, 1, 0, 7, 0, 1),
        )
        fingerprint, cost, text_bytes = struct.unpack_from("<QII", frame, 28)
        self.assertEqual((fingerprint, cost, text_bytes), (9, 123, 6))
        self.assertEqual(frame[-6:].decode("utf-8"), "候補")

    def test_request_rejects_duplicate_fingerprints_and_bounds(self) -> None:
        candidate = Candidate(9, 123, "候補")
        with self.assertRaisesRegex(BenchmarkError, "unique"):
            encode_request(1, [candidate, candidate])
        with self.assertRaisesRegex(BenchmarkError, "candidate count"):
            encode_request(1, [])
        with self.assertRaisesRegex(BenchmarkError, "candidate text"):
            encode_request(1, [Candidate(1, 1, "")])

    def test_decodes_success_and_failure_responses(self) -> None:
        success = struct.pack(
            "<IHHQHHIQf", RESPONSE_MAGIC, 1, 0, 7, 2, 0, 1, 9, -1.25
        )
        decoded = decode_response(success)
        self.assertEqual(decoded.request_id, 7)
        self.assertEqual(decoded.status, 0)
        self.assertEqual(decoded.tier, 2)
        self.assertEqual(decoded.scores, ((9, -1.25),))

        failure = struct.pack("<IHHQHHI", RESPONSE_MAGIC, 1, 2, 8, 2, 0, 0)
        self.assertEqual(decode_response(failure).status, 2)

    def test_response_rejects_nonfinite_and_trailing_bytes(self) -> None:
        nonfinite = struct.pack(
            "<IHHQHHIQf", RESPONSE_MAGIC, 1, 0, 7, 2, 0, 1, 9, math.nan
        )
        with self.assertRaisesRegex(BenchmarkError, "non-finite"):
            decode_response(nonfinite)
        failure_with_score = struct.pack(
            "<IHHQHHIQf", RESPONSE_MAGIC, 1, 2, 7, 2, 0, 1, 9, 0.0
        )
        with self.assertRaisesRegex(BenchmarkError, "unexpectedly"):
            decode_response(failure_with_score)


class FixtureTests(unittest.TestCase):
    def test_fixed_fixture_spans_buckets_without_public_text(self) -> None:
        fixtures = benchmark_fixtures()

        self.assertEqual([item.character_length for item in fixtures], [8, 16, 32])
        self.assertEqual([len(item.candidates) for item in fixtures], [6, 6, 6])
        self.assertEqual(
            [len(item.differing_positions) for item in fixtures], [1, 4, 8]
        )
        self.assertEqual(len({fixture_hash(fixtures)}), 1)
        public = json.dumps(
            [item.public_record() for item in fixtures], ensure_ascii=False
        )
        for fixture in fixtures:
            for candidate in fixture.candidates:
                self.assertNotIn(candidate.text, public)


class StatisticsTests(unittest.TestCase):
    def test_latency_summary_uses_nearest_rank(self) -> None:
        summary = latency_summary(range(1, 101))

        self.assertEqual(summary["count"], 100)
        self.assertEqual(summary["p50_ms"], 50)
        self.assertEqual(summary["p95_ms"], 95)
        self.assertEqual(summary["p99_ms"], 99)
        self.assertEqual(summary["max_ms"], 100)


if __name__ == "__main__":
    unittest.main()
