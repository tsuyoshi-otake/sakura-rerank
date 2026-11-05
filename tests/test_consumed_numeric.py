import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sakura_rerank.data import consumed_numeric as numeric
from sakura_rerank.data.annotation_first import extract_work
from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby
from sakura_rerank.data.consumed_source import PERMITTED,unit_key,verify_consumption
from sakura_rerank.data.contracts import canonical_json_bytes,canonical_json_hash
from sakura_rerank.data.growth_numeric import encode
from test_annotation_first import raw_source


class ConsumedNumericTests(unittest.TestCase):
    def fixture(self):
        raw=raw_source("これは数値入力の範囲を確認する原文です。｜学校《がっこう》へ行く。")
        revision=hashlib.sha256(raw).hexdigest()
        row=extract_work(raw,"1","2",revision)[0][0]
        paragraph=paragraphs_with_ruby(raw)[0][0]
        decision=dict(unit_id=unit_key(row["source"]),article_id=row["source"]["article_id"],paragraph_hash=row["source"]["paragraph_hash"],status=PERMITTED)
        receipt=verify_consumption(row,decision,paragraph,work_id="1",author_id="2",revision=revision,paragraph_index=0,consumer="source_verification")
        row["candidate_request_id"]="growth-reading-"+canonical_json_hash(row["reading"])
        candidates=[dict(surface=t,local_cost=i*100,source_category="system_dictionary",segments=[dict(source_category="system_dictionary",unused="not_a_feature")])
                    for i,t in enumerate(("学工",row["target"]))]
        snapshot=dict(stable_id=row["candidate_request_id"],reading=row["reading"],extra_metadata="not_a_feature",
            candidate_snapshots=dict(training_top32=dict(candidates=candidates),production_top6=dict(candidates=candidates)))
        return row,receipt,snapshot

    def prepared(self):
        row,receipt,snapshot=self.fixture()
        projected,candidates,seal=numeric.project(row,receipt,snapshot,"component","a"*64)
        arrays,_=encode([projected],{row["candidate_request_id"]:candidates})
        return arrays,seal

    def cache(self,root):
        import numpy as np
        arrays,seal=self.prepared()
        np.savez_compressed(root/"arrays.npz",**arrays)
        entry=numeric.chain_entry(0,"0"*64,seal,arrays)
        (root/"row-receipts.jsonl").write_bytes(canonical_json_bytes(entry)+b"\n")
        manifest=dict(kind="source_reconstruction_numeric_cache",status="prepared_unverified",rows=1,
            array_schema=numeric.schema(1),row_chain_head=entry["record_sha256"],policy_sha256="a"*64,
            training_eligible=False,independent_gold_eligible=False,allowed_consumer=numeric.PURPOSE,
            artifacts={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ("arrays.npz","row-receipts.jsonl")})
        (root/"manifest.json").write_bytes(canonical_json_bytes(manifest)+b"\n")
        return hashlib.sha256((root/"manifest.json").read_bytes()).hexdigest()

    def test_projection_excludes_source_right_context_and_candidate_metadata(self):
        row,receipt,snapshot=self.fixture(); row["right_context"]="未来の原文"
        before=copy.deepcopy((row,receipt,snapshot))
        projected,candidates,seal=numeric.project(row,receipt,snapshot,"component","a"*64)
        self.assertEqual(set(projected),{"stable_id","component_id","corpus","left_context","reading","target","candidate_request_id"})
        self.assertEqual(set(candidates),{"candidate_snapshots"})
        self.assertEqual(set(candidates["candidate_snapshots"]["training_top32"]["candidates"][0]),{"surface","local_cost","source_category","segments"})
        self.assertNotIn("未来の原文",json.dumps([projected,candidates,seal],ensure_ascii=False))
        self.assertEqual((row,receipt,snapshot),before)
        self.assertFalse(seal["training_eligible"])

    def test_source_receipt_mutation_is_rejected(self):
        row,receipt,snapshot=self.fixture()
        for key in ("left_context","reading","target","source_revision"):
            changed=copy.deepcopy(row);changed[key]+="変"
            with self.subTest(field=key),self.assertRaises(ValueError):
                numeric.project(changed,receipt,snapshot,"component","a"*64)
        with self.assertRaises(ValueError):
            numeric.project(row,dict(receipt,consumer="training"),snapshot,"component","a"*64)

    def test_missing_wrong_reading_or_unsupported_candidate_is_rejected(self):
        row,receipt,snapshot=self.fixture()
        changed=copy.deepcopy(snapshot);changed["reading"]="べつ"
        unsupported=copy.deepcopy(snapshot)
        unsupported["candidate_snapshots"]["training_top32"]["candidates"][1]["segments"][0]["source_category"]="reading"
        for value in (None,changed,unsupported):
            with self.assertRaises(ValueError):
                numeric.project(row,receipt,value,"component","a"*64)

    def test_evaluation_or_label_promotion_is_rejected(self):
        row,receipt,snapshot=self.fixture()
        for key,value in (("population","evaluation"),("training_eligible",True),("independent_gold_eligible",True)):
            changed=dict(row);changed[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):
                numeric.project(changed,receipt,snapshot,"component","a"*64)

    def test_exact_arrays_load_read_only_under_numeric_purpose(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); digest=self.cache(root)
            arrays,records,manifest=numeric.load_prepared_cache(root,digest,purpose=numeric.PURPOSE)
            self.assertEqual(arrays["gold"].tolist(),[1])
            self.assertEqual(len(records),manifest["rows"])
            self.assertTrue(all(not a.flags.writeable for a in arrays.values()))

    def test_training_gold_and_model_consumers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); digest=self.cache(root)
            for purpose in ("training","gold_evaluation","model_inference","body_pretraining"):
                with self.subTest(purpose=purpose),self.assertRaises(ValueError):
                    numeric.load_prepared_cache(root,digest,purpose=purpose)

    def test_wrong_manifest_or_changed_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); digest=self.cache(root)
            with self.assertRaises(ValueError):
                numeric.load_prepared_cache(root,"0"*64,purpose=numeric.PURPOSE)
            (root/"arrays.npz").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                numeric.load_prepared_cache(root,digest,purpose=numeric.PURPOSE)

    def test_missing_manifest_is_not_a_completed_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                numeric.load_prepared_cache(Path(directory),"0"*64,purpose=numeric.PURPOSE)

    def test_tail_drop_reorder_and_row_mutation_fail_chain(self):
        arrays,seal=self.prepared();record=numeric.chain_entry(0,"0"*64,seal,arrays)
        raw=canonical_json_bytes(record)+b"\n"
        self.assertEqual(len(numeric.verify_chain(raw,1,record["record_sha256"])),1)
        for value in (b"",raw+raw,canonical_json_bytes(dict(record,index=1))+b"\n"):
            with self.assertRaises(ValueError):
                numeric.verify_chain(value,1,record["record_sha256"])

    def test_mask_label_padding_nonfinite_and_shape_changes_are_rejected(self):
        arrays,_=self.prepared();numeric.validate_arrays(arrays,1)
        for field,index,value in (("candidate_mask",(0,4),True),("correct_mask",(0,0),True),
            ("context_ids",(0,63),5),("features",(0,0,0),float("nan"))):
            changed={k:a.copy() for k,a in arrays.items()};changed[field][index]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                numeric.validate_arrays(changed,1)
        changed=dict(arrays);changed["features"]=changed["features"][:,:,:6]
        with self.assertRaises(ValueError):
            numeric.validate_arrays(changed,1)

    def test_byte_authentication_retains_loaded_bytes_across_path_change(self):
        original=numeric._bounded_bytes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);digest=self.cache(root)
            def changing(path,limit):
                raw=original(path,limit)
                if path.name=="arrays.npz":
                    path.write_bytes(b"replaced_after_authentication")
                return raw
            with patch.object(numeric,"_bounded_bytes",side_effect=changing):
                arrays,_,_=numeric.load_prepared_cache(root,digest,purpose=numeric.PURPOSE)
            self.assertEqual(arrays["gold"].tolist(),[1])


if __name__=="__main__":
    unittest.main()
