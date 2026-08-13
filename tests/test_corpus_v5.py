from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sakura_rerank.data import corpus_v5
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.corpus_v4 import (
    GATE_A_REVIEWER_ID,
    V4_SCHEMA_VERSION,
    V4_VERDICT_RECORD_TYPE,
    read_teacher_queue_directory,
    scan_verdict_directory,
)
from sakura_rerank.data.corpus_v5 import (
    AMBIGUOUS_BUCKET,
    CONFIRMATION_PASS,
    ELIGIBLE_BUCKET,
    FIRST_PASS,
    MAX_BATCH_ITEMS,
    NOISE_BUCKET,
    REPAIRABLE_BUCKET,
    UNRESOLVED_BUCKET,
    V5_GATE_A_AUDIT_SEED,
    V5_GATE_A_QUEUE_MANIFEST_KIND,
    V5_SCHEMA_VERSION,
    V5_SPLIT_RATIOS,
    V5_SPLIT_SEED,
    V5_VERDICT_RECORD_TYPE,
    build_blind_queue_manifest,
    build_blind_teacher_batches,
    partition_blind_teacher_passes,
    publish_admissibility_partition_directory,
    publish_blind_teacher_queue_directory,
    publish_v5_gate_a_teacher_queue_directory,
    read_blind_teacher_queue_directory,
    scan_blind_verdict_directory,
    validate_blind_teacher_queue_binding,
    validate_blind_teacher_verdict_batch,
    validate_partition_report_intrinsic,
    validate_v5_gate_a_teacher_queue_binding,
)
from sakura_rerank.data.human_audit import build_queue_manifest, select_audit_records
from sakura_rerank.data.splitter import assign_splits
from sakura_rerank.data.tier_a import TierAError
from tests.test_data_contracts import _rehash_snapshots, production_record


FIRST_REVIEWER = "teacher-first"
CONFIRMATION_REVIEWER = "teacher-confirm"


def records(count: int = 45) -> list[dict[str, object]]:
    """Produce verified, non-fixture Tier-A rows before any split is assigned."""

    result = []
    for index in range(count):
        item = production_record()
        item["stable_id"] = f"v5-{index:04d}"
        item["split"] = None
        source = item["source"]
        source["article_id"] = f"v5-article-{index:04d}"
        source["page_id"] = f"v5-page-{index:04d}"
        source["revision_id"] = f"v5-revision-{index:04d}"
        source["paragraph_hash"] = hashlib.sha256(
            f"v5-paragraph-{index:04d}".encode("utf-8")
        ).hexdigest()
        source["sentence_hash"] = hashlib.sha256(
            f"v5-sentence-{index:04d}".encode("utf-8")
        ).hexdigest()
        source["sentence_shingle_hashes"] = [
            hashlib.sha256(f"v5-shingle-{index:04d}".encode("utf-8")).hexdigest()
        ]
        source["template_cluster_id"] = None
        exporter = item["candidate_snapshots"]["training_top32"]["exporter_run"]
        exporter["verification_status"] = "verified"
        exporter["exporter_git_sha"] = "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1"
        exporter["exporter_binary_sha256"] = "0b26990a153df06c8e870b7e44abca386ada2ffd6f649c0232cea6a79960acbf"
        _rehash_snapshots(item)
        result.append(item)
    return result


def verdict(
    batch: dict[str, object],
    *,
    reviewer: str,
    decisions: dict[str, str] | None = None,
) -> dict[str, object]:
    decisions = decisions or {}
    return {
        "schema_version": V5_SCHEMA_VERSION,
        "record_type": V5_VERDICT_RECORD_TYPE,
        "batch_index": batch["batch_index"],
        "reviewer_kind": "ai_teacher",
        "reviewer_id": reviewer,
        "verdicts": [
            {
                "stable_id": item["stable_id"],
                "verdict": decisions.get(item["stable_id"], "valid"),
                "note": "",
            }
            for item in batch["items"]
        ],
    }


def verdict_set(
    batches: list[dict[str, object]], *, reviewer: str, decisions: dict[str, str] | None = None
) -> dict[int, dict[str, object]]:
    return {
        batch["batch_index"]: verdict(batch, reviewer=reviewer, decisions=decisions)
        for batch in batches
    }


def write_canonical_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


class CorpusV5Tests(unittest.TestCase):
    def _all_valid_partition_report(
        self, source: list[dict[str, object]]
    ) -> dict[str, object]:
        batches = build_blind_teacher_batches(source)
        first_manifest = build_blind_queue_manifest(
            source, batches, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
        )
        confirmation_manifest = build_blind_queue_manifest(
            source,
            batches,
            pass_name=CONFIRMATION_PASS,
            reviewer_id=CONFIRMATION_REVIEWER,
        )
        _, report = partition_blind_teacher_passes(
            source,
            batches,
            first_manifest,
            verdict_set(batches, reviewer=FIRST_REVIEWER),
            batches,
            confirmation_manifest,
            verdict_set(batches, reviewer=CONFIRMATION_REVIEWER),
        )
        return report

    def _gate_a_inputs(
        self,
        source: list[dict[str, object]],
        *,
        minimum_sample_size: int = 2,
    ) -> tuple[
        dict[str, object],
        list[dict[str, object]],
        list[dict[str, object]],
        dict[str, object],
        list[dict[str, object]],
        dict[str, object],
    ]:
        report = self._all_valid_partition_report(source)
        eligible = copy.deepcopy(source)
        split_dataset, split_report = assign_splits(
            eligible,
            seed=V5_SPLIT_SEED,
            split_ratios=V5_SPLIT_RATIOS,
        )
        queue = select_audit_records(
            split_dataset,
            seed=V5_GATE_A_AUDIT_SEED,
            minimum_sample_size=minimum_sample_size,
        )
        queue_manifest = build_queue_manifest(
            split_dataset,
            queue,
            seed=V5_GATE_A_AUDIT_SEED,
            minimum_sample_size=minimum_sample_size,
        )
        return (
            report,
            eligible,
            split_dataset,
            split_report,
            queue,
            queue_manifest,
        )

    def test_v5_gate_a_queue_is_fresh_partition_bound_bounded_and_race_safe(self) -> None:
        source = records(205)
        (
            report,
            eligible,
            split_dataset,
            split_report,
            queue,
            queue_manifest,
        ) = self._gate_a_inputs(source)
        self.assertEqual(validate_partition_report_intrinsic(report), report)
        self.assertEqual(split_report["split_counts"]["final-holdout"], 41)
        self.assertEqual(len(queue), 41)
        reviewer_id = "fresh-v5-gate-a"
        with patch(
            "sakura_rerank.data.corpus_v5.V5_GATE_A_MINIMUM_SAMPLE_SIZE", 2
        ), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "gate-a"
            manifest = publish_v5_gate_a_teacher_queue_directory(
                target,
                eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                report,
                reviewer_id=reviewer_id,
            )
            self.assertEqual(manifest["reviewer_id"], reviewer_id)
            self.assertEqual(
                manifest["manifest_kind"], V5_GATE_A_QUEUE_MANIFEST_KIND
            )
            self.assertEqual(manifest["batch_count"], 2)
            self.assertEqual(
                [entry["item_count"] for entry in manifest["batch_files"]], [40, 1]
            )
            provenance = manifest["source_provenance"]
            self.assertFalse(provenance["raw_text_in_provenance"])
            self.assertFalse(provenance["raw_stable_ids_in_provenance"])
            self.assertFalse(provenance["raw_notes_in_provenance"])
            with self.assertRaisesRegex(TierAError, "manifest fields"):
                read_teacher_queue_directory(target)
            batches, loaded_manifest = read_teacher_queue_directory(
                target,
                expected_manifest_kind=V5_GATE_A_QUEUE_MANIFEST_KIND,
                require_source_provenance=True,
                require_canonical_bytes=True,
            )
            bound, inferred = validate_v5_gate_a_teacher_queue_binding(
                eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                batches,
                loaded_manifest,
                report,
            )
            self.assertEqual(bound, batches)
            self.assertEqual(inferred, reviewer_id)
            with self.assertRaisesRegex(TierAError, "immutable"):
                publish_v5_gate_a_teacher_queue_directory(
                    target,
                    eligible,
                    split_dataset,
                    split_report,
                    queue,
                    queue_manifest,
                    report,
                    reviewer_id=reviewer_id,
                )

            tampered_manifest = copy.deepcopy(loaded_manifest)
            tampered_manifest["source_provenance"][
                "audit_queue_content_sha256"
            ] = "0" * 64
            with self.assertRaisesRegex(TierAError, "source provenance"):
                validate_v5_gate_a_teacher_queue_binding(
                    eligible,
                    split_dataset,
                    split_report,
                    queue,
                    queue_manifest,
                    batches,
                    tampered_manifest,
                    report,
                )

            swapped_report = self._all_valid_partition_report(records(2))
            with self.assertRaisesRegex(TierAError, "partition eligible artifact"):
                validate_v5_gate_a_teacher_queue_binding(
                    eligible,
                    split_dataset,
                    split_report,
                    queue,
                    queue_manifest,
                    batches,
                    loaded_manifest,
                    swapped_report,
                )

            retry_target = root / "retry-gate-a"
            attempts = 0

            def transient_then_publish(source_path: Path, target_path: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    error = PermissionError("simulated directory lock")
                    error.winerror = 32
                    raise error
                os.rename(source_path, target_path)

            with (
                patch(
                    "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                    side_effect=transient_then_publish,
                ) as rename,
                patch("sakura_rerank.data.corpus_v5.random.uniform", return_value=0.0),
                patch("sakura_rerank.data.corpus_v5.time.sleep") as sleep,
            ):
                publish_v5_gate_a_teacher_queue_directory(
                    retry_target,
                    eligible,
                    split_dataset,
                    split_report,
                    queue,
                    queue_manifest,
                    report,
                    reviewer_id=reviewer_id,
                )
            self.assertEqual(rename.call_count, 2)
            sleep.assert_called_once_with(0.05)

        for forbidden in (
            GATE_A_REVIEWER_ID,
            FIRST_REVIEWER,
            CONFIRMATION_REVIEWER,
        ):
            with self.subTest(forbidden=forbidden), self.assertRaisesRegex(
                TierAError, "fresh and distinct"
            ):
                publish_v5_gate_a_teacher_queue_directory(
                    Path("unused"),
                    eligible,
                    split_dataset,
                    split_report,
                    queue,
                    queue_manifest,
                    report,
                    reviewer_id=forbidden,
                )
        with patch(
            "sakura_rerank.data.corpus_v5.V5_GATE_A_MINIMUM_SAMPLE_SIZE", 2
        ), self.assertRaisesRegex(TierAError, "batch_size"):
            publish_v5_gate_a_teacher_queue_directory(
                Path("unused"),
                eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                report,
                reviewer_id=reviewer_id,
                batch_size=41,
            )

    def test_v5_gate_a_rejects_unrelated_split_audit_and_partition_artifacts(self) -> None:
        source = records(10)
        (
            report,
            eligible,
            split_dataset,
            split_report,
            queue,
            queue_manifest,
        ) = self._gate_a_inputs(source)
        reviewer_id = "fresh-v5-gate-a"
        with patch(
            "sakura_rerank.data.corpus_v5.V5_GATE_A_MINIMUM_SAMPLE_SIZE", 2
        ):
            unrelated_eligible = records(11)
            with self.assertRaisesRegex(TierAError, "split dataset/report"):
                publish_v5_gate_a_teacher_queue_directory(
                    Path("unused"),
                    unrelated_eligible,
                    split_dataset,
                    split_report,
                    queue,
                    queue_manifest,
                    report,
                    reviewer_id=reviewer_id,
                )

            unrelated_split = copy.deepcopy(split_dataset)
            unrelated_split[0]["split"] = (
                "dev" if unrelated_split[0]["split"] != "dev" else "train"
            )
            with self.assertRaisesRegex(TierAError, "split dataset/report"):
                publish_v5_gate_a_teacher_queue_directory(
                    Path("unused"),
                    eligible,
                    unrelated_split,
                    split_report,
                    queue,
                    queue_manifest,
                    report,
                    reviewer_id=reviewer_id,
                )

            tampered_split_report = copy.deepcopy(split_report)
            tampered_split_report["seed"] += 1
            with self.assertRaisesRegex(TierAError, "split dataset/report"):
                publish_v5_gate_a_teacher_queue_directory(
                    Path("unused"),
                    eligible,
                    split_dataset,
                    tampered_split_report,
                    queue,
                    queue_manifest,
                    report,
                    reviewer_id=reviewer_id,
                )

            unrelated_queue = queue[:-1]
            unrelated_manifest = build_queue_manifest(
                split_dataset,
                unrelated_queue,
                seed=V5_GATE_A_AUDIT_SEED,
                minimum_sample_size=2,
            )
            with self.assertRaisesRegex(TierAError, "complete final holdout"):
                publish_v5_gate_a_teacher_queue_directory(
                    Path("unused"),
                    eligible,
                    split_dataset,
                    split_report,
                    unrelated_queue,
                    unrelated_manifest,
                    report,
                    reviewer_id=reviewer_id,
                )

        with self.assertRaisesRegex(TierAError, "fewer than 3000"):
            publish_v5_gate_a_teacher_queue_directory(
                Path("unused"),
                eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                report,
                reviewer_id=reviewer_id,
            )

    def test_v5_gate_a_reader_requires_canonical_queue_and_verdict_bytes(self) -> None:
        (
            report,
            eligible,
            split_dataset,
            split_report,
            queue,
            queue_manifest,
        ) = self._gate_a_inputs(records(10))
        reviewer_id = "fresh-v5-gate-a-canonical"
        with patch(
            "sakura_rerank.data.corpus_v5.V5_GATE_A_MINIMUM_SAMPLE_SIZE", 2
        ), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher_directory = root / "teacher"
            publish_v5_gate_a_teacher_queue_directory(
                teacher_directory,
                eligible,
                split_dataset,
                split_report,
                queue,
                queue_manifest,
                report,
                reviewer_id=reviewer_id,
            )
            read_options = {
                "expected_manifest_kind": V5_GATE_A_QUEUE_MANIFEST_KIND,
                "require_source_provenance": True,
                "require_canonical_bytes": True,
            }

            manifest_path = teacher_directory / "manifest.json"
            canonical_manifest = manifest_path.read_bytes()
            manifest_value = json.loads(canonical_manifest)
            manifest_path.write_text(
                json.dumps(manifest_value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(TierAError, "not canonical JSON with LF"):
                read_teacher_queue_directory(teacher_directory, **read_options)
            manifest_path.write_bytes(canonical_manifest)

            batch_path = teacher_directory / "batch-000.json"
            canonical_batch = batch_path.read_bytes()
            batch_value = json.loads(canonical_batch)
            batch_path.write_text(
                json.dumps(batch_value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(TierAError, "not canonical JSON with LF"):
                read_teacher_queue_directory(teacher_directory, **read_options)
            batch_path.write_bytes(canonical_batch)

            batches, _ = read_teacher_queue_directory(
                teacher_directory, **read_options
            )
            verdict_directory = root / "verdicts"
            verdict_directory.mkdir()
            payload = {
                "schema_version": V4_SCHEMA_VERSION,
                "record_type": V4_VERDICT_RECORD_TYPE,
                "batch_index": 0,
                "reviewer_kind": "ai_teacher",
                "reviewer_id": reviewer_id,
                "verdicts": [
                    {
                        "stable_id": item["stable_id"],
                        "verdict": "valid",
                        "note": "",
                    }
                    for item in batches[0]["items"]
                ],
            }
            (verdict_directory / "verdicts-000.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(TierAError, "not canonical JSON with LF"):
                scan_verdict_directory(
                    teacher_directory, verdict_directory, **read_options
                )

    def test_pre_split_queue_is_nonfixture_blind_stable_and_bounded(self) -> None:
        source = records(81)
        batches = build_blind_teacher_batches(list(reversed(source)))

        self.assertEqual([len(batch["items"]) for batch in batches], [40, 40, 1])
        self.assertTrue(all(len(batch["items"]) <= MAX_BATCH_ITEMS for batch in batches))
        flattened = [item for batch in batches for item in batch["items"]]
        self.assertEqual(
            [item["stable_id"] for item in flattened],
            sorted(item["stable_id"] for item in source),
        )
        forbidden = {"split", "verdict", "note", "history", "prior_verdict", "prior_notes"}
        self.assertTrue(all(forbidden.isdisjoint(item) for item in flattened))
        self.assertTrue(all(row["split"] is None for row in source))

        fixture = records(1)
        fixture[0]["is_fixture"] = True
        with self.assertRaisesRegex(TierAError, "fixture"):
            build_blind_teacher_batches(fixture)

    def test_manifest_binds_exact_dataset_and_two_passes_need_distinct_identities(self) -> None:
        source = records(2)
        batches = build_blind_teacher_batches(source)
        first_manifest = build_blind_queue_manifest(
            source, batches, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
        )
        confirmation_manifest = build_blind_queue_manifest(
            source, batches, pass_name=CONFIRMATION_PASS, reviewer_id=CONFIRMATION_REVIEWER
        )
        self.assertEqual(validate_blind_teacher_queue_binding(source, batches, first_manifest), batches)

        changed = copy.deepcopy(source)
        changed[0]["session"]["left_context"] = "different committed context"
        with self.assertRaisesRegex(TierAError, "bind"):
            validate_blind_teacher_queue_binding(changed, batches, first_manifest)

        same_reviewer = dict(confirmation_manifest)
        same_reviewer["reviewer_id"] = FIRST_REVIEWER
        first_verdicts = verdict_set(batches, reviewer=FIRST_REVIEWER)
        confirmation_verdicts = verdict_set(batches, reviewer=FIRST_REVIEWER)
        with self.assertRaisesRegex(TierAError, "distinct reviewer"):
            partition_blind_teacher_passes(
                source,
                batches,
                first_manifest,
                first_verdicts,
                batches,
                same_reviewer,
                confirmation_verdicts,
            )

    def test_queue_directory_is_canonical_immutable_and_detects_tampering_or_extras(self) -> None:
        source = records(41)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "first"
            manifest = publish_blind_teacher_queue_directory(
                queue, source, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
            )
            loaded, loaded_manifest = read_blind_teacher_queue_directory(queue)
            self.assertEqual(loaded, build_blind_teacher_batches(source))
            self.assertEqual(loaded_manifest, manifest)
            self.assertEqual(
                hashlib.sha256((queue / "manifest.json").read_bytes()).hexdigest(),
                hashlib.sha256(canonical_json_bytes(manifest) + b"\n").hexdigest(),
            )
            with self.assertRaisesRegex(TierAError, "immutable"):
                publish_blind_teacher_queue_directory(
                    queue, source, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
                )

            write_canonical_json(queue / "batch-000.json", {"batch_index": 0, "items": []})
            with self.assertRaisesRegex(TierAError, "hash mismatch"):
                read_blind_teacher_queue_directory(queue)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "first"
            publish_blind_teacher_queue_directory(
                queue, source, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
            )
            (queue / "foreign.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "unexpected"):
                read_blind_teacher_queue_directory(queue)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "first"
            publish_blind_teacher_queue_directory(
                queue, source, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
            )
            batch_path = queue / "batch-000.json"
            batch_path.write_text(
                json.dumps(json.loads(batch_path.read_text(encoding="utf-8"))), encoding="utf-8"
            )
            with self.assertRaisesRegex(TierAError, "canonical JSON"):
                read_blind_teacher_queue_directory(queue)

    def test_queue_publication_retries_transient_windows_rename_error(self) -> None:
        source = records(2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "retry-queue"
            attempts = 0

            def transient_then_replace(source_path: Path, target_path: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    error = PermissionError("simulated directory lock")
                    error.winerror = 5
                    raise error
                os.replace(source_path, target_path)

            with (
                patch(
                    "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                    side_effect=transient_then_replace,
                ) as replace_directory,
                patch("sakura_rerank.data.corpus_v5.random.uniform", return_value=0.002),
                patch("sakura_rerank.data.corpus_v5.time.sleep") as sleep,
            ):
                manifest = publish_blind_teacher_queue_directory(
                    target,
                    source,
                    pass_name=FIRST_PASS,
                    reviewer_id=FIRST_REVIEWER,
                )

            self.assertEqual(replace_directory.call_count, 2)
            sleep.assert_called_once()
            self.assertAlmostEqual(sleep.call_args.args[0], 0.052)
            loaded, loaded_manifest = read_blind_teacher_queue_directory(target)
            self.assertEqual(loaded, build_blind_teacher_batches(source))
            self.assertEqual(loaded_manifest, manifest)

    def test_queue_publication_exhausted_transient_retries_cleans_temporary_directory(self) -> None:
        source = records(2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "locked-queue"

            def transient_lock(_: Path, __: Path) -> None:
                error = PermissionError("simulated persistent directory lock")
                error.winerror = 32
                raise error

            with (
                patch(
                    "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                    side_effect=transient_lock,
                ) as replace_directory,
                patch("sakura_rerank.data.corpus_v5.random.uniform", return_value=0.0),
                patch("sakura_rerank.data.corpus_v5.time.sleep") as sleep,
            ):
                with self.assertRaisesRegex(PermissionError, "persistent"):
                    publish_blind_teacher_queue_directory(
                        target,
                        source,
                        pass_name=FIRST_PASS,
                        reviewer_id=FIRST_REVIEWER,
                    )

            self.assertEqual(replace_directory.call_count, 8)
            self.assertEqual(sleep.call_count, 7)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob(".locked-queue.*")), [])

    def test_queue_publication_does_not_retry_non_transient_rename_error(self) -> None:
        source = records(2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "invalid-queue"
            with (
                patch(
                    "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                    side_effect=OSError("simulated non-transient failure"),
                ) as replace_directory,
                patch("sakura_rerank.data.corpus_v5.time.sleep") as sleep,
            ):
                with self.assertRaisesRegex(OSError, "non-transient"):
                    publish_blind_teacher_queue_directory(
                        target,
                        source,
                        pass_name=FIRST_PASS,
                        reviewer_id=FIRST_REVIEWER,
                    )

            self.assertEqual(replace_directory.call_count, 1)
            sleep.assert_not_called()
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob(".invalid-queue.*")), [])

    def test_queue_publication_does_not_retry_permission_errors_without_transient_winerror(self) -> None:
        source = records(2)
        cases = (
            ("missing-winerror", PermissionError("simulated generic access failure")),
            ("other-winerror", PermissionError("simulated unrelated access failure")),
        )
        cases[1][1].winerror = 3
        for name, error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / name
                with (
                    patch(
                        "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                        side_effect=error,
                    ) as replace_directory,
                    patch("sakura_rerank.data.corpus_v5.time.sleep") as sleep,
                ):
                    with self.assertRaisesRegex(PermissionError, "simulated"):
                        publish_blind_teacher_queue_directory(
                            target,
                            source,
                            pass_name=FIRST_PASS,
                            reviewer_id=FIRST_REVIEWER,
                        )

                self.assertEqual(replace_directory.call_count, 1)
                sleep.assert_not_called()
                self.assertFalse(target.exists())
                self.assertEqual(list(root.glob(f".{name}.*")), [])

    def test_directory_publish_retry_delay_caps_jittered_value_at_one_second(self) -> None:
        with patch("sakura_rerank.data.corpus_v5.random.uniform", return_value=0.5):
            self.assertEqual(corpus_v5._directory_publish_retry_delay(5), 1.0)

    @unittest.skipUnless(os.name == "nt", "Windows os.rename supplies no-overwrite semantics")
    def test_queue_publication_preserves_target_created_after_precheck(self) -> None:
        source = records(2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "racing-queue"
            marker = target / "marker.txt"
            real_rename = os.rename

            def create_target_then_rename(source_path: Path, target_path: Path) -> None:
                target_path.mkdir()
                (target_path / "marker.txt").write_text("preserve", encoding="utf-8")
                real_rename(source_path, target_path)

            with patch(
                "sakura_rerank.data.corpus_v5.os.rename",
                side_effect=create_target_then_rename,
            ) as rename:
                with self.assertRaises(FileExistsError):
                    publish_blind_teacher_queue_directory(
                        target,
                        source,
                        pass_name=FIRST_PASS,
                        reviewer_id=FIRST_REVIEWER,
                    )

            self.assertEqual(rename.call_count, 1)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(list(root.glob(".racing-queue.*")), [])

    def test_resumable_verdict_scan_rejects_malformed_and_extra_files(self) -> None:
        source = records(41)
        batches = build_blind_teacher_batches(source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, outputs = root / "queue", root / "outputs"
            publish_blind_teacher_queue_directory(
                queue, source, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
            )
            completed, pending = scan_blind_verdict_directory(queue, outputs)
            self.assertEqual(completed, {})
            self.assertEqual(pending, [0, 1])

            outputs.mkdir()
            malformed = verdict(batches[0], reviewer=FIRST_REVIEWER)
            malformed["verdicts"] = list(reversed(malformed["verdicts"]))
            write_canonical_json(outputs / "verdicts-000.json", malformed)
            with self.assertRaisesRegex(TierAError, "queue order"):
                scan_blind_verdict_directory(queue, outputs)

            write_canonical_json(outputs / "verdicts-000.json", verdict(batches[0], reviewer=FIRST_REVIEWER))
            completed, pending = scan_blind_verdict_directory(queue, outputs)
            self.assertEqual(sorted(completed), [0])
            self.assertEqual(pending, [1])
            (outputs / "extra.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(TierAError, "unexpected"):
                scan_blind_verdict_directory(queue, outputs)

    def test_verdicts_require_exact_coverage_order_and_queue_provenance(self) -> None:
        batches = build_blind_teacher_batches(records(2))
        payload = verdict(batches[0], reviewer=FIRST_REVIEWER)
        self.assertEqual(
            validate_blind_teacher_verdict_batch(batches[0], payload, reviewer_id=FIRST_REVIEWER),
            payload,
        )
        wrong_reviewer = copy.deepcopy(payload)
        wrong_reviewer["reviewer_id"] = CONFIRMATION_REVIEWER
        with self.assertRaisesRegex(TierAError, "provenance"):
            validate_blind_teacher_verdict_batch(batches[0], wrong_reviewer, reviewer_id=FIRST_REVIEWER)
        short = copy.deepcopy(payload)
        short["verdicts"].pop()
        with self.assertRaisesRegex(TierAError, "coverage"):
            validate_blind_teacher_verdict_batch(batches[0], short, reviewer_id=FIRST_REVIEWER)
        reversed_order = copy.deepcopy(payload)
        reversed_order["verdicts"].reverse()
        with self.assertRaisesRegex(TierAError, "queue order"):
            validate_blind_teacher_verdict_batch(batches[0], reversed_order, reviewer_id=FIRST_REVIEWER)

    def test_partition_has_full_coverage_explicit_bucket_precedence_and_aggregate_report(self) -> None:
        source = records(5)
        batches = build_blind_teacher_batches(source)
        first_manifest = build_blind_queue_manifest(
            source, batches, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER
        )
        confirmation_manifest = build_blind_queue_manifest(
            source, batches, pass_name=CONFIRMATION_PASS, reviewer_id=CONFIRMATION_REVIEWER
        )
        identifiers = [row["stable_id"] for row in source]
        first_decisions = {
            identifiers[0]: "valid",
            identifiers[1]: "wrong_reading",
            identifiers[2]: "ambiguous",
            identifiers[3]: "extraction_noise",
            identifiers[4]: "valid",
        }
        confirmation_decisions = {
            identifiers[0]: "valid",
            identifiers[1]: "ambiguous",
            identifiers[2]: "valid",
            identifiers[3]: "wrong_segmentation",
            identifiers[4]: "wrong_gold_surface",
        }
        first_verdicts = verdict_set(batches, reviewer=FIRST_REVIEWER, decisions=first_decisions)
        confirmation_verdicts = verdict_set(
            batches, reviewer=CONFIRMATION_REVIEWER, decisions=confirmation_decisions
        )
        buckets, report = partition_blind_teacher_passes(
            list(reversed(source)),
            batches,
            first_manifest,
            first_verdicts,
            batches,
            confirmation_manifest,
            confirmation_verdicts,
        )
        self.assertEqual([row["stable_id"] for row in buckets[ELIGIBLE_BUCKET]], [identifiers[0]])
        self.assertEqual([row["stable_id"] for row in buckets[REPAIRABLE_BUCKET]], [identifiers[1], identifiers[4]])
        self.assertEqual([row["stable_id"] for row in buckets[AMBIGUOUS_BUCKET]], [identifiers[2]])
        self.assertEqual([row["stable_id"] for row in buckets[NOISE_BUCKET]], [identifiers[3]])
        self.assertEqual(buckets[UNRESOLVED_BUCKET], [])
        self.assertEqual(sum(summary["record_count"] for summary in report["buckets"].values()), 5)
        self.assertEqual(report["verdict_pair_counts"], dict(sorted(report["verdict_pair_counts"].items())))
        self.assertFalse(report["raw_text_in_report"])
        self.assertFalse(report["raw_stable_ids_in_report"])
        self.assertFalse(report["raw_notes_in_report"])
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertTrue(all(identifier not in rendered for identifier in identifiers))
        self.assertTrue(all(row["reading"] not in rendered for row in source))

        again, again_report = partition_blind_teacher_passes(
            source, batches, first_manifest, first_verdicts, batches, confirmation_manifest, confirmation_verdicts
        )
        self.assertEqual(again, buckets)
        self.assertEqual(again_report, report)

    def test_partition_rejects_incomplete_extra_and_same_queue_reviewer_verdicts(self) -> None:
        source = records(41)
        batches = build_blind_teacher_batches(source)
        first_manifest = build_blind_queue_manifest(source, batches, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER)
        confirmation_manifest = build_blind_queue_manifest(source, batches, pass_name=CONFIRMATION_PASS, reviewer_id=CONFIRMATION_REVIEWER)
        first = verdict_set(batches, reviewer=FIRST_REVIEWER)
        confirmation = verdict_set(batches, reviewer=CONFIRMATION_REVIEWER)

        missing = dict(first)
        del missing[1]
        with self.assertRaisesRegex(TierAError, "cover every batch exactly"):
            partition_blind_teacher_passes(source, batches, first_manifest, missing, batches, confirmation_manifest, confirmation)
        extra = dict(first)
        extra[99] = first[0]
        with self.assertRaisesRegex(TierAError, "cover every batch exactly"):
            partition_blind_teacher_passes(source, batches, first_manifest, extra, batches, confirmation_manifest, confirmation)
        wrong_identity = dict(confirmation)
        wrong_identity[0] = verdict(batches[0], reviewer=FIRST_REVIEWER)
        with self.assertRaisesRegex(TierAError, "provenance"):
            partition_blind_teacher_passes(source, batches, first_manifest, first, batches, confirmation_manifest, wrong_identity)

    def test_partition_publication_is_atomic_immutable_and_rejects_overlap_or_hash_mismatch(self) -> None:
        source = records(2)
        batches = build_blind_teacher_batches(source)
        first_manifest = build_blind_queue_manifest(source, batches, pass_name=FIRST_PASS, reviewer_id=FIRST_REVIEWER)
        confirmation_manifest = build_blind_queue_manifest(source, batches, pass_name=CONFIRMATION_PASS, reviewer_id=CONFIRMATION_REVIEWER)
        buckets, report = partition_blind_teacher_passes(
            source,
            batches,
            first_manifest,
            verdict_set(batches, reviewer=FIRST_REVIEWER),
            batches,
            confirmation_manifest,
            verdict_set(batches, reviewer=CONFIRMATION_REVIEWER),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "partition"
            publish_admissibility_partition_directory(target, buckets, report)
            self.assertEqual(json.loads((target / "report.json").read_text(encoding="utf-8")), report)
            self.assertTrue((target / "eligible-unanimous-valid.jsonl").is_file())
            with self.assertRaisesRegex(TierAError, "immutable"):
                publish_admissibility_partition_directory(target, buckets, report)

            overlap = copy.deepcopy(buckets)
            overlap[NOISE_BUCKET] = [buckets[ELIGIBLE_BUCKET][0]]
            with self.assertRaisesRegex(TierAError, "overlap"):
                publish_admissibility_partition_directory(root / "overlap", overlap, report)
            bad_hash = copy.deepcopy(report)
            bad_hash["buckets"][ELIGIBLE_BUCKET]["content_sha256"] = "0" * 64
            with self.assertRaisesRegex(TierAError, "aggregate commitment"):
                publish_admissibility_partition_directory(root / "bad-hash", buckets, bad_hash)

            bad_pass = copy.deepcopy(report)
            bad_pass["passes"][FIRST_PASS]["record_count"] = 1
            with self.assertRaisesRegex(TierAError, "pass entry"):
                publish_admissibility_partition_directory(root / "bad-pass", buckets, bad_pass)

            bad_pairs = copy.deepcopy(report)
            bad_pairs["verdict_pair_counts"] = {"ambiguous/valid": 2}
            with self.assertRaisesRegex(TierAError, "bucket counts"):
                publish_admissibility_partition_directory(root / "bad-pairs", buckets, bad_pairs)

            retry_partition = root / "retry-partition"
            attempts = 0

            def transient_then_publish(source_path: Path, target_path: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    error = PermissionError("simulated directory lock")
                    error.winerror = 5
                    raise error
                os.replace(source_path, target_path)

            with (
                patch(
                    "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                    side_effect=transient_then_publish,
                ) as replace_directory,
                patch("sakura_rerank.data.corpus_v5.random.uniform", return_value=0.0),
                patch("sakura_rerank.data.corpus_v5.time.sleep") as sleep,
            ):
                publish_admissibility_partition_directory(retry_partition, buckets, report)
            self.assertEqual(replace_directory.call_count, 2)
            sleep.assert_called_once_with(0.05)
            self.assertEqual(
                json.loads((retry_partition / "report.json").read_text(encoding="utf-8")), report
            )

            failed = root / "failed"
            with patch(
                "sakura_rerank.data.corpus_v5._rename_directory_without_overwrite",
                side_effect=OSError("injected"),
            ):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_admissibility_partition_directory(failed, buckets, report)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.*")), [])


if __name__ == "__main__":
    unittest.main()
