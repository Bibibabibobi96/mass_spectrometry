from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msplatform.io.file_identity import file_sha256
from msplatform.backends.simion.runtime_materialization import stage_verified_simion_runtime

PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


class StageFormalSimionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifact = Path(self.temp.name) / PROJECT_ID
        self.formal = self.artifact / "formal"
        simion = self.formal / "simion"
        simion.mkdir(parents=True)
        self.source = simion / "model.iob"
        self.source.write_bytes(b"formal model")
        record = {
            "path": "simion/model.iob",
            "bytes": self.source.stat().st_size,
            "sha256": file_sha256(self.source),
        }
        (self.formal / "asset_manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "role": "formal_asset_manifest",
                "project": PROJECT_ID,
                "release_id": "20260729_112246__sim__cross__vnext-n1000-r2",
                "assets": {"simion_iob": record},
            }),
            encoding="utf-8",
        )
        self.destination = self.artifact / "scratch/runtime"
        self.receipt = self.artifact / "runs/demo/inputs/runtime_receipt.json"

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_stages_verified_copy_and_receipt(self) -> None:
        result, _ = stage_verified_simion_runtime(artifact_project_root=self.artifact, destination=self.destination, receipt=self.receipt, project_id=PROJECT_ID)
        self.assertEqual((self.destination / "model.iob").read_bytes(), b"formal model")
        self.assertEqual(result["assets"][0]["role"], "simion_iob")
        self.assertTrue(self.receipt.is_file())

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_materialization_cli_runs_from_outside_checkout(self) -> None:
        result = subprocess.run([sys.executable, '-I', '-m', 'msplatform.backends.simion.runtime_materialization',
            '--artifact-root', str(self.artifact), '--destination', str(self.destination),
            '--receipt', str(self.receipt), '--project-id', PROJECT_ID],
            cwd=self.temp.name, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SIMION_RUNTIME_STAGE=PASS', result.stdout)
        self.assertEqual((self.destination/'model.iob').read_bytes(), b'formal model')
        self.assertEqual(json.loads(self.receipt.read_text(encoding='utf-8'))['project'], PROJECT_ID)

    def test_replaced_runtime_modules_are_not_importable(self) -> None:
        code = '''import importlib.util
for name in ("msplatform.backends.simion.formal_runtime", "msplatform.workflows.oa_formal.stage_formal_simion_runtime"):
    try:
        found = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        found = None
    assert found is None, name
'''
        result = subprocess.run([sys.executable, '-I', '-c', code], cwd=self.temp.name,
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_rejects_changed_formal_asset_without_partial_runtime(self) -> None:
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "byte count|identity differs"):
            stage_verified_simion_runtime(artifact_project_root=self.artifact, destination=self.destination, receipt=self.receipt, project_id=PROJECT_ID)
        self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_rejects_unlisted_formal_file(self) -> None:
        (self.formal / "simion/unlisted.pa0").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "file set differs"):
            stage_verified_simion_runtime(artifact_project_root=self.artifact, destination=self.destination, receipt=self.receipt, project_id=PROJECT_ID)

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_rejects_duplicate_asset_roles_for_one_path(self) -> None:
        manifest_path = self.formal/'asset_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['assets']['other_iob'] = dict(manifest['assets']['simion_iob'])
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'repeats an asset path'):
            stage_verified_simion_runtime(artifact_project_root=self.artifact, destination=self.destination,
                                          receipt=self.receipt, project_id=PROJECT_ID)
        self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_stages_to_explicit_external_store_path(self) -> None:
        destination = Path(self.temp.name)/'store/assets/native_stage/model'
        result, paths = stage_verified_simion_runtime(artifact_project_root=self.artifact,
            destination=destination, receipt=self.receipt, project_id=PROJECT_ID)
        self.assertEqual(paths, [destination/'model.iob'])
        self.assertEqual((destination/'model.iob').read_bytes(), b'formal model')
        self.assertEqual(result['project'], PROJECT_ID)

    @unittest.skipUnless(os.name == 'nt', 'Windows immutable handle semantics required')
    def test_source_and_manifest_remain_guarded_during_actual_copy(self) -> None:
        original_copy = shutil.copy2
        blocked = []

        def inspect_copy(source, destination):
            for path in (self.source, self.formal/'asset_manifest.json'):
                try:
                    path.unlink()
                except PermissionError:
                    blocked.append(path)
                else:
                    self.fail(f'guard did not protect {path}')
            return original_copy(source, destination)

        with mock.patch('msplatform.backends.simion.runtime_materialization.shutil.copy2', side_effect=inspect_copy):
            stage_verified_simion_runtime(artifact_project_root=self.artifact,
                destination=self.destination, receipt=self.receipt, project_id=PROJECT_ID)
        self.assertEqual(len(blocked), 2)
        self.assertTrue(self.source.exists())
        self.assertTrue((self.formal/'asset_manifest.json').exists())

    def test_activity_scripts_never_run_simion_from_formal(self) -> None:
        root = Path(__file__).resolve().parents[4]
        workflows = root / "src/msplatform/workflows/resources"
        scripts = {
            "ideal": root / "src/msplatform/backends/simion/resources/run_ideal_field_diagnostic.ps1",
            "geometry": workflows / "verify_geometry_contract.ps1",
            "stable": workflows / "verify_stable_entry.ps1",
            "diagnostics": workflows / "run_cross_solver_diagnostics.ps1",
        }
        combined = "\n".join(path.read_text(encoding="utf-8") for path in scripts.values())
        self.assertNotIn("-WorkingDirectory $formalSimion", combined)
        self.assertNotIn("-WorkingDirectory $formalDir", combined)
        self.assertNotIn("Push-Location $formalDir", combined)
        for name in ("ideal", "geometry", "stable", "diagnostics"):
            self.assertIn(
                "New-OaTofFormalSimionRuntime",
                scripts[name].read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
