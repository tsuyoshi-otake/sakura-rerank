"""The archive patch must be byte-stable even on a CRLF-default Git host."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ReferenceBuildPatchTests(unittest.TestCase):
    def test_identity_patch_preserves_frozen_lf_bytes_with_crlf_host_default(self):
        repo = Path(__file__).resolve().parents[1]
        folder = repo / "research/issue-31-quality"
        with patch.object(sys, "path", [str(folder), *sys.path]):
            spec = importlib.util.spec_from_file_location("reference_build_recipe_test", folder / "build_reference_exporter.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        original = subprocess.check_output(["git", "-C", str(repo), "show",
            "06ff8c34417fb7dbc24e41d786dfb6434cdd6aa1:research/exporter/src/main.rs"], timeout=30)
        profile = json.loads((repo / "manifests/reference-probe-build-profile-v1.json").read_bytes())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "research/exporter/src/main.rs"
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "true"}):
                module.apply_identity_patch(root, repo / "research/patches/research-exporter-probe-identity.patch",
                                            profile["patched_exporter_main_sha256"])
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), profile["patched_exporter_main_sha256"])
            self.assertNotIn(b"\r\n", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
