"""Synthetic parent evidence for the selected-point compiler; no solver claims."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    ideal_acceptance_300mm_simion_candidate as compiler,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class IdealAcceptanceCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.parent = self.workspace / "parent"
        self.configuration = self.parent / "inputs/experiment.json"
        self.reference = self.parent / "inputs/reference_config.json"
        self.live_reference = self.workspace / "author/reference.json"
        self.selected = self.parent / "results/selected.json"
        self.manifest_path = self.parent / "run_manifest.json"
        self.config = {
            "role": "ideal_acceptance_theory",
            "reference_config": str(self.live_reference),
            "design": {"total_acceleration_length_mm": 300},
            "numerics": {"coefficient_tolerance_ns": 1e-6},
        }
        self.reference_document = {
            "source": {"mass_to_charge_th": 100.0, "center_velocity_m_per_s": 0.0,
                       "velocity_slope_m_per_s_per_mm": 10.0},
            "outer": {"nominal_energy_per_charge_v": 2000.0},
            "reflectron": {"stage1_length_mm": 120.0, "stage2_length_mm": 100.0,
                           "upstream_drift_mm": 600.0, "downstream_drift_mm": 600.0},
        }
        self.selected_document = {
            "design_id": "synthetic_binding_fixture", "full_width_mm": 4,
            "theoretical_population_pass": True, "independent_particle_pass": True,
            "point": {
                "state": {"zone1_length_mm": 10.0, "zone2_length_mm": 100.0,
                          "zone3_length_mm": 190.0, "field1_v_per_mm": 20.0,
                          "field2_v_per_mm": 5.0, "field3_v_per_mm": 5.0,
                          "repeller_v": 2100.0, "grid1_v": 1900.0,
                          "grid2_v": 1400.0, "exit_v": 0.0},
                "inner": {"stage1_voltage_drop_v": 1000.0, "stage2_field_v_per_mm": 10.0},
                "design_source": {"center_x_mm": 5.0}, "focus_drift_mm": 40.0,
            },
        }
        for path, document in ((self.configuration, self.config),
                               (self.reference, self.reference_document),
                               (self.live_reference, self.reference_document),
                               (self.selected, self.selected_document)):
            _write_json(path, document)
        self.manifest = {
            "schema_version": 1, "role": "simulation_run_manifest", "status": "success",
            "project": compiler.PROJECT_ID, "mode": "ideal_acceptance_theory",
            "inputs": {"experiment": file_record(self.configuration),
                       "reference_config": file_record(self.reference)},
            "outputs": [file_record(self.selected)],
        }
        _write_json(self.manifest_path, self.manifest)

    def compile(self) -> dict:
        return compiler.compile_ideal_acceptance_300mm_candidate(
            self.configuration, self.manifest_path, self.selected,
        )

    def test_live_reference_change_does_not_change_frozen_source(self) -> None:
        first = self.compile()
        parent_before = self.manifest_path.read_bytes()
        selected_before = self.selected.read_bytes()
        changed = copy.deepcopy(self.reference_document)
        changed["source"]["mass_to_charge_th"] = 200.0
        changed["source"]["velocity_slope_m_per_s_per_mm"] = 20.0
        _write_json(self.live_reference, changed)
        self.assertEqual(self.compile(), first)
        self.live_reference.unlink()
        self.assertEqual(self.compile(), first)
        self.assertEqual(self.manifest_path.read_bytes(), parent_before)
        self.assertEqual(self.selected.read_bytes(), selected_before)

    def test_configuration_must_match_parent_frozen_input(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["numerics"]["coefficient_tolerance_ns"] = 1.0
        supplied = self.workspace / "different_configuration.json"
        _write_json(supplied, changed)
        with self.assertRaisesRegex((AssertionError, ValueError), "configuration|experiment"):
            compiler.compile_ideal_acceptance_300mm_candidate(
                supplied, self.manifest_path, self.selected,
            )

    def test_changed_parent_reference_is_rejected(self) -> None:
        changed = copy.deepcopy(self.reference_document)
        changed["source"]["mass_to_charge_th"] = 200.0
        _write_json(self.reference, changed)
        with self.assertRaisesRegex((AssertionError, ValueError), "reference_config"):
            self.compile()

    def test_equal_configuration_copy_uses_parent_records_and_relative_paths(self) -> None:
        supplied = self.workspace / "same_configuration.json"
        supplied.write_bytes(self.configuration.read_bytes())
        for record in [*self.manifest["inputs"].values(), *self.manifest["outputs"]]:
            record["path"] = Path(record["path"]).relative_to(self.parent).as_posix()
        _write_json(self.manifest_path, self.manifest)
        result = compiler.compile_ideal_acceptance_300mm_candidate(
            supplied, self.manifest_path, self.selected,
        )
        self.assertEqual(Path(result["campaign"]["file"]["path"]), self.configuration)
        self.assertEqual(result["qualification"], "CANDIDATE_ONLY")
        self.assertIn("remain unverified", result["claim_limit"])

    def test_missing_or_mismatched_parent_evidence_fails_before_compilation(self) -> None:
        original = copy.deepcopy(self.manifest)
        cases = []
        for field, value in (("status", "failed"), ("project", "other"), ("mode", "other")):
            changed = copy.deepcopy(original)
            changed[field] = value
            cases.append((field, changed))
        for name in ("experiment", "reference_config"):
            changed = copy.deepcopy(original)
            del changed["inputs"][name]
            cases.append((name, changed))
        for records in ([], original["outputs"] * 2):
            changed = copy.deepcopy(original)
            changed["outputs"] = records
            cases.append(("selected record count", changed))
        changed = copy.deepcopy(original)
        changed["outputs"][0]["sha256"] = "0" * 64
        cases.append(("selected SHA", changed))
        for name, document in cases:
            with self.subTest(name=name):
                _write_json(self.manifest_path, document)
                with self.assertRaises((AssertionError, ValueError)):
                    self.compile()

    def test_grid_branch_uses_the_same_frozen_reference(self) -> None:
        # This tests input transport, not a new numerical focus solution. The
        # existing independent theory tests own equation/solver accuracy.
        root_result = lambda function, initial, **kwargs: SimpleNamespace(success=True, x=initial)
        with (mock.patch.object(compiler, "root", side_effect=root_result),
              mock.patch.object(compiler, "axial_time_coefficients", return_value=np.zeros(5)),
              mock.patch.object(compiler, "ReflectronGeometry", wraps=compiler.ReflectronGeometry) as geometry):
            first = compiler.compile_grid_realized_ideal_acceptance_300mm_candidate(
                self.configuration, self.manifest_path, self.selected, axial_grid_z_mm=0.05,
            )
            changed = copy.deepcopy(self.reference_document)
            changed["reflectron"]["stage1_length_mm"] = 240.0
            changed["source"]["mass_to_charge_th"] = 200.0
            _write_json(self.live_reference, changed)
            second = compiler.compile_grid_realized_ideal_acceptance_300mm_candidate(
                self.configuration, self.manifest_path, self.selected, axial_grid_z_mm=0.05,
            )
        self.assertEqual(first, second)
        self.assertEqual(geometry.call_args_list,
                         [mock.call(**self.reference_document["reflectron"])] * 2)

    def test_real_cli_needs_no_live_reference_and_rejects_wrong_configuration(self) -> None:
        self.live_reference.unlink()
        output = self.workspace / "candidate.json"
        command = [sys.executable, "-B", "-m", compiler.__name__,
                   "--configuration", str(self.configuration), "--run-manifest", str(self.manifest_path),
                   "--selected-result", str(self.selected), "--output", str(output)]
        completed = subprocess.run(command, cwd=compiler.REPOSITORY_ROOT, capture_output=True,
                                   text=True, encoding="utf-8", timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.compile())
        output.unlink()
        self.config["numerics"]["coefficient_tolerance_ns"] = 1.0
        _write_json(self.configuration, self.config)
        rejected = subprocess.run(command, cwd=compiler.REPOSITORY_ROOT, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertFalse(output.exists())

    def test_publication_binds_frozen_reference_and_preserves_parent(self) -> None:
        repo = compiler.REPOSITORY_ROOT
        source = Path(compiler.__file__)
        code_root = self.workspace / "simulation_repo"
        copied_source = code_root / source.relative_to(repo)
        schema_relative = Path("common/contracts/schemas") / compiler.OUTPUT_SCHEMA
        for original, destination in ((source, copied_source),
                                      (repo / schema_relative, code_root / schema_relative)):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(original.read_bytes())
        run = (self.workspace / "artifacts/projects" / compiler.PROJECT_ID / "runs"
               / "20261029_080000__build__python__synthetic-300mm-candidate")
        before = {p: p.read_bytes() for p in self.parent.rglob("*") if p.is_file()}
        self.live_reference.unlink()
        with (mock.patch.object(compiler, "__file__", str(copied_source)),
              mock.patch.object(compiler, "REPOSITORY_ROOT", code_root),
              mock.patch.dict(os.environ, {"PYTHONPATH": str(repo)})):
            summary = compiler.publish_ideal_acceptance_300mm_candidate(
                self.configuration, self.manifest_path, self.selected, run,
                workspace_root=self.workspace,
            )
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        reference = manifest["inputs"]["ideal_acceptance_reference_source"]
        self.assertEqual(record_path(reference, base_dir=run), self.reference)
        verify_record("published frozen reference", reference, base_dir=run)
        self.assertFalse(summary["formal_gate_passed"])
        self.assertFalse(manifest["formal_eligible"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with self.assertRaises(FileExistsError):
            compiler.publish_ideal_acceptance_300mm_candidate(
                self.configuration, self.manifest_path, self.selected, run,
                workspace_root=self.workspace,
            )
        self.assertEqual(list(run.parent.glob(".*")), [])


if __name__ == "__main__":
    unittest.main()
