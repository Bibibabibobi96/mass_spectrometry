"""Small real-file tests for the existing native owner consumption guard."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.native_source_guard import guard_native_source
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
class NativeSourceGuardTests(unittest.TestCase):
    def fixture(self, base):
        root = base / "owner"
        run = root / "projects" / "fixture" / "runs" / "20261127_010101__test__python__source"
        run.mkdir(parents=True)
        config = run / "run_config.json"
        config.write_text(json.dumps({"schema_version": 1, "run_id": run.name, "project": "fixture", "mode": "software",
            "inputs": {}, "capacity_ledger_lifecycle": {"schema_version": 1, "enabled": True,
                "artifact_root": str(root), "light_evidence_budget_bytes": 1024}}), encoding="utf-8")
        data = run / "payload.pa0"
        data.write_bytes(b"small native fixture")
        record = file_record(data)
        product = {"schema_version": 1, "kind": "geometry_artifact", "status": "complete",
                   "metadata": {}, "data": {"payload": record}}
        manifest = build_run_manifest(config, "success", output_paths=[data], extra_fields={"products": {"geometry": product}})
        path = run / "run_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return root, data, {"manifest": file_record(path), "product_id": "geometry"}

    def test_real_process_cannot_delete_or_write_guarded_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root, data, reference = self.fixture(Path(directory))
            probe = """import pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    p.unlink()
except OSError:
    print("DELETE_BLOCKED")
else:
    raise SystemExit(3)
try:
    p.open("ab").close()
except OSError:
    print("WRITE_BLOCKED")
else:
    raise SystemExit(4)
"""
            with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root) as artifact:
                self.assertEqual(artifact.data_path("payload"), data)
                with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root) as again:
                    self.assertEqual(again.data_path("payload"), data)
                for path in (data, Path(reference["manifest"]["path"]), data.parent / "run_config.json"):
                    result = subprocess.run([sys.executable, "-c", probe, str(path)], cwd=root,
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("DELETE_BLOCKED", result.stdout)
                    self.assertIn("WRITE_BLOCKED", result.stdout)
                retirement_probe = """import pathlib, sys
from msplatform.execution.recorded_file_removal import remove_recorded_files
p = pathlib.Path(sys.argv[1])
record = {"path": p.name, "bytes": p.stat().st_size}
try:
    list(remove_recorded_files(p.parent, [record], identities_verified=True))
except OSError:
    print("RETIREMENT_BLOCKED")
else:
    raise SystemExit(5)
"""
                result = subprocess.run([sys.executable, "-c", retirement_probe, str(data)],
                                        cwd=root, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RETIREMENT_BLOCKED", result.stdout)
            data.unlink()
            self.assertFalse(data.exists())

    def test_history_read_is_readonly_and_fails_closed_if_source_disappears(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        from msplatform.io.file_identity import guarded_file_identity
        with tempfile.TemporaryDirectory() as directory:
            root, data, reference = self.fixture(Path(directory))
            before = {item.relative_to(root).as_posix(): item.read_bytes() for item in root.rglob("*") if item.is_file()}
            with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root):
                pass
            after = {item.relative_to(root).as_posix(): item.read_bytes() for item in root.rglob("*") if item.is_file()}
            self.assertEqual(before, after)
            removed = False
            @contextmanager
            def race(path, **kwargs):
                nonlocal removed
                if Path(path).name == "run_config.json" and not removed:
                    data.unlink()
                    removed = True
                with guarded_file_identity(path, **kwargs) as guard:
                    yield guard
            with patch("msplatform.execution.native_source_guard.guarded_file_identity", race):
                with self.assertRaises((FileNotFoundError, OSError, ValueError)):
                    with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root):
                        pass
            self.assertTrue(removed)

    def test_rejects_wrong_root_wrong_kind_and_damaged_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root, data, reference = self.fixture(Path(directory))
            other = Path(directory) / "other"
            other.mkdir()
            with self.assertRaisesRegex(ValueError, "outside"):
                with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=other):
                    pass
            with self.assertRaises(ValueError):
                with guard_native_source(reference, expected_kind="field_bundle", expected_artifact_root=root):
                    pass
            data.write_bytes(b"different bytes")
            with self.assertRaises((ValueError, AssertionError, OSError)):
                with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root):
                    pass
