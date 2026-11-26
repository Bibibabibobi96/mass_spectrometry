"""Public native preparation contracts; no solver execution is claimed here."""
from contextlib import redirect_stdout, ExitStack, contextmanager
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from msplatform.cli import main
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import preflight_native
from msplatform.workflows.native_tracing import _native_reference
from msplatform.workflows.reference_tracing import run_recipe
from msplatform.storage import ArtifactStore

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "src/msplatform/examples"


class NativeWorkflowTests(unittest.TestCase):
    def test_large_executable_identity_has_an_explicit_evidence_role(self):
        from msplatform.workflows.native_tracing import _executable_records
        from msplatform.io.file_identity import file_sha256
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inert.exe"
            path.write_bytes(b"inert implementation bytes" * 400000)
            self.assertGreater(path.stat().st_size, 8 * 1024 * 1024)
            self.assertEqual(_executable_records({"simion": path}), {
                "simion": {"bytes": path.stat().st_size, "sha256": file_sha256(path)}})

    def test_reference_cache_second_call_verifies_kind_and_avoids_producer(self):
        artifact = SimpleNamespace(kind="geometry_artifact", reference={"manifest": {"path": "inert"}, "product_id": "geometry"})
        opened = []

        @contextmanager
        def guard(reference, *, expected_kind, expected_artifact_root):
            opened.append(expected_kind)
            self.assertEqual(expected_kind, "geometry_artifact")
            yield artifact

        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "store")
            calls = []
            with patch("msplatform.execution.native_source_guard.guard_native_source", guard):
                for expected_reuse in (False, True):
                    with ExitStack() as stack:
                        result, receipt = _native_reference(store, stack, "inert-test-key", lambda: artifact,
                            kind="geometry_artifact", raw_root=Path(directory), claims=[], calls=calls)
                        self.assertIs(result, artifact)
                        self.assertEqual(receipt["reused"], expected_reuse)
            self.assertEqual(len(calls), 1)
            self.assertEqual(opened, ["geometry_artifact", "geometry_artifact"])

    def test_mass_scan_author_and_native_only_controls_reach_real_planner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "oa_split_tof_native_small_v1"
            source = (EXAMPLES / (name + ".toml")).read_text(encoding="utf-8")
            study = json.loads((EXAMPLES / (name + ".json")).read_bytes())
            first = copy.deepcopy(study["release"])
            first.pop("particle_ids")
            second = copy.deepcopy(first)
            second["species_id"] = "same_mass_charge_2"
            second["release_spec"]["particle_count"] = 1
            second["release_spec"]["species"]["charge_state"] = 2
            study["release"] = {"schema_version": 1, "role": "canonical_mass_scan_request", "species_requests": [first, second]}
            def write():
                data = json.dumps(study).encode()
                (root / (name + ".json")).write_bytes(data)
                import re
                author = root / (name + ".toml")
                author.write_text(re.sub(r'sha256 = "[a-fA-F0-9]{64}"', 'sha256 = "' + hashlib.sha256(data).hexdigest() + '"', source), encoding="utf-8")
                return author
            self.assertTrue(preflight_native(load_recipe(write()).to_dict())["implemented"])
            study["numerics"]["tracing"]["simion"]["rf_steps_per_period"] = 32
            with self.assertRaisesRegex(ValueError, "tracking numerics"):
                preflight_native(load_recipe(write()).to_dict())

    def test_public_validate_compiles_both_real_split_examples_without_native_claim(self):
        for name in ("oa_split_tof", "rf_split_oatof"):
            output = io.StringIO()
            with self.subTest(name=name), redirect_stdout(output):
                self.assertEqual(main(["validate", str(EXAMPLES / (name + "_native_small_v1.toml"))]), 0)
            result = json.loads(output.getvalue())
            self.assertTrue(result["capabilities"]["implemented"])
            self.assertIsNone(result["capabilities"]["host_available"])
            self.assertFalse(result["capabilities"]["native_verified"])
            self.assertIn("single_reflection_tof", result["resolved"]["assembly"]["name"])

    def test_native_dispatch_reads_author_once_and_passes_same_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension in ("json", "toml"):
                name = "oa_split_tof_native_small_v1." + extension
                (root / name).write_bytes((EXAMPLES / name).read_bytes())
            author = root / "oa_split_tof_native_small_v1.toml"
            old = author.read_bytes()
            original_read = Path.read_bytes
            reads = []

            def mutate_after_read(path):
                data = original_read(path)
                if path == author:
                    reads.append(data)
                    author.write_bytes(data.replace(b"technical small N", b"later source version"))
                return data

            def execute(loaded, **kwargs):
                self.assertEqual(loaded.source_bytes, old)
                self.assertEqual(loaded.to_dict()["label"], "OA TOF split technical small N")
                return {"run_id": "inert_dispatch_test"}

            with patch.object(Path, "read_bytes", mutate_after_read), patch(
                    "msplatform.workflows.native_tracing.run_loaded_recipe", side_effect=execute):
                self.assertEqual(run_recipe(author, artifact_root=root / "store")["run_id"], "inert_dispatch_test")
            self.assertEqual(reads, [old])
            self.assertNotEqual(load_recipe(author).source_bytes, old)

    def test_unsupported_backend_combination_and_missing_context_fail_before_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "oa_split_tof_native_small_v1"
            (root / (name + ".json")).write_bytes((EXAMPLES / (name + ".json")).read_bytes())
            author = root / (name + ".toml")
            source = (EXAMPLES / (name + ".toml")).read_text(encoding="utf-8")
            author.write_text(source.replace("simion_native", "comsol_native"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not yet implemented"):
                preflight_native(load_recipe(author).to_dict())
            author.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ExecutionContext"):
                run_recipe(author, artifact_root=root / "store")
            self.assertFalse((root / "store").exists())


if __name__ == "__main__":
    unittest.main()
