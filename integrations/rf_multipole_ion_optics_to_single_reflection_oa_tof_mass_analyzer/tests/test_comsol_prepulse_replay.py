from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.build_comsol_prepulse_replay import (
    build_comsol_prepulse_replay,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.comsol_retrace_contract import (
    build_handoff_receipt,
    validate_retrace_arm,
)
from common.contracts.file_identity import file_sha256


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
STAGE_ROOT = INTEGRATION_ROOT / "stages" / "comsol"
WORKFLOW_ROOT = INTEGRATION_ROOT / "workflows" / "comsol_prepulse_replay"


class ComsolPrePulseReplayTests(unittest.TestCase):
    def _write_source(self, root: Path) -> tuple[Path, Path, Path, Path]:
        checkpoints = root / "checkpoints.csv"
        geometry = root / "geometry.json"
        release = root / "release.csv"
        metadata = root / "metadata.json"
        checkpoints.write_text(
            "particle_id,event,instrument_time_us,x_mm,y_mm,z_mm,"
            "vx_mm_per_us,vy_mm_per_us,vz_mm_per_us,kinetic_energy_eV,pulse_eligibility\n"
            "7,pre_pulse_state,45.5,-69,0.1,-65.5,4.392,0,0,9.99616396028,eligible\n"
            "8,pre_pulse_state,45.5,-69,0.2,-65.4,4.392,0,0,9.99616396028,outside_transverse_bore\n",
            encoding="utf-8",
        )
        geometry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "oa_tof_resolved_contract_do_not_edit",
                    "geometry_mm": {
                        "accelerator_repeller_z": -67.0,
                        "accelerator_grid1_z": -64.0,
                    },
                }
            ),
            encoding="utf-8",
        )
        build_comsol_prepulse_replay(
            checkpoints,
            geometry,
            release,
            metadata,
            mass_amu=100,
            charge_state=1,
        )
        return checkpoints, geometry, release, metadata

    def _write_receipt(self, root: Path) -> tuple[Path, Path, Path, Path]:
        _, geometry, release, metadata = self._write_source(root)
        manifest = root / "manifest.json"
        voltages = root / "voltages.json"
        acceptance = root / "acceptance.json"
        receipt = root / "receipt.json"
        model = root / "source.mph"
        model_metadata = root / "source_model_metadata.json"
        model.write_bytes(b"static-test-model")
        manifest.write_text(
            json.dumps({"status": "success", "run_id": "winner"}), encoding="utf-8"
        )
        voltages.write_text(json.dumps({"V_repeller": 1.0}), encoding="utf-8")
        model_metadata.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "rf_oatof_comsol_source_model_identity",
                    "source_model_sha256": file_sha256(model),
                    "geometry_sha256": file_sha256(geometry),
                    "voltages_sha256": file_sha256(voltages),
                    "field_mode": "real",
                    "baseline_field_mask": {
                        f"ideal_{region}_{component}": 0
                        for region in ("accel", "drift", "stage1", "stage2")
                        for component in ("ex", "ey", "ez")
                    },
                    "baseline_voltages_V": {"V_repeller": 1.0},
                }
            ),
            encoding="utf-8",
        )
        acceptance.write_text(
            json.dumps(
                {
                    "detector_blind": True,
                    "definition_method": "field_error_time_budget",
                }
            ),
            encoding="utf-8",
        )
        build_handoff_receipt(
            simion_manifest_path=manifest,
            geometry_path=geometry,
            voltage_path=voltages,
            source_model_path=model,
            source_model_metadata_path=model_metadata,
            release_path=release,
            source_metadata_path=metadata,
            acceptance_window_path=acceptance,
            output_path=receipt,
            field_mode="real",
        )
        return receipt, release, model, model_metadata

    def _arm_document(
        self,
        root: Path,
        receipt: Path,
        release: Path,
        model: Path,
        model_metadata: Path,
        change_class: str,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "role": "rf_oatof_comsol_retrace_arm",
            "arm_id": change_class,
            "change_class": change_class,
            "source_model": str(model),
            "source_model_sha256": file_sha256(model),
            "source_model_metadata": str(model_metadata),
            "handoff_receipt": str(receipt),
            "cartesian_release": str(release),
            "cartesian_release_metadata": str(root / "metadata.json"),
            "output_model": str(root / "output" / f"{change_class}.mph"),
            "output_root": str(root / "output"),
            "mass_amu": 100.0,
            "charge_state": 1,
            "pulse_effective_time_us": 45.5,
            "source_deviation": (
                {
                    "deviation_id": "test_source",
                    "method": "deterministic_test_mapping",
                    "detector_blind": True,
                    "preserves_particle_ids": True,
                }
                if change_class == "source"
                else {}
            ),
            "baseline_field_mask": {
                f"ideal_{region}_{component}": 0
                for region in ("accel", "drift", "stage1", "stage2")
                for component in ("ex", "ey", "ez")
            },
            "baseline_voltages_V": {"V_repeller": 1.0},
            "field_mask": {"ideal_accel_ez": 1} if change_class == "field_mask" else {},
            "voltage_overrides_V": {"V_repeller": 1000.0} if change_class == "voltage" else {},
        }

    def _write_run_local_arm_fixture(
        self, root: Path, *, run_id: str = "20260812_120000__test__comsol__retrace__n100"
    ) -> tuple[Path, Path, Path]:
        root.mkdir(parents=True)
        receipt, release, model, model_metadata = self._write_receipt(root)
        run_root = (
            root
            / "artifacts"
            / "projects"
            / "single_reflection_oa_tof_mass_analyzer"
            / "runs"
            / run_id
        )
        input_root = run_root / "inputs"
        input_root.mkdir(parents=True)
        arm = input_root / "retrace_arm.json"
        document = self._arm_document(
            root, receipt, release, model, model_metadata, "voltage"
        )
        document["output_root"] = str(run_root / "results")
        document["output_model"] = str(run_root / "comsol" / "retrace.mph")
        arm.write_text(json.dumps(document), encoding="utf-8")
        return arm, release, model

    def test_cartesian_release_preserves_global_velocity_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, release, metadata = self._write_source(Path(directory))
            with release.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["particle_id"], "7")
            self.assertEqual(
                [float(rows[0][name]) for name in ("x_mm", "y_mm", "z_mm")],
                [-69, 0.1, -65.5],
            )
            self.assertEqual(float(rows[0]["vx_m_per_s"]), 4392.0)
            self.assertEqual(float(rows[0]["vy_m_per_s"]), 0.0)
            self.assertEqual(float(rows[0]["vz_m_per_s"]), 0.0)
            self.assertNotIn("azimuth_deg", rows[0])
            document = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(document["coordinate_frame"], "shared_global_cartesian")
            self.assertLess(document["maximum_velocity_serialization_error_m_per_s"], 1e-6)

    def test_handoff_receipt_freezes_winner_clock_window_and_particle_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, _, _, _ = self._write_receipt(root)
            document = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(document["role"], "simion_winner_to_comsol_handoff_receipt")
            self.assertEqual(document["source"]["particle_ids"], [7])
            self.assertEqual(
                document["clock"]["tof_definition"],
                "t_detector_minus_t_pulse_effective",
            )
            self.assertFalse(document["clock"]["instrument_clock_peak_is_resolution_claim"])
            self.assertLess(document["source"]["maximum_velocity_error_m_per_s"], 1e-6)

    def test_retrace_change_class_maps_to_minimum_required_solver_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, release, model, model_metadata = self._write_receipt(root)
            output = root / "output"
            output.mkdir()
            cases = {
                "source": (False, False, {}),
                "field_mask": (False, False, {"ideal_accel_ez": 1}),
                "voltage": (False, True, {}),
            }
            for change_class, (mesh, electrostatics, mask) in cases.items():
                arm = root / f"{change_class}.json"
                document = self._arm_document(
                    root, receipt, release, model, model_metadata, change_class
                )
                arm.write_text(json.dumps(document), encoding="utf-8")
                plan = validate_retrace_arm(arm)
                self.assertEqual(plan["mesh_rebuild"], mesh)
                self.assertEqual(plan["electrostatics"], electrostatics)
                self.assertTrue(plan["particles"])

    def test_geometry_and_mesh_retrace_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, release, model, model_metadata = self._write_receipt(root)
            for change_class in ("geometry", "mesh"):
                arm = root / f"{change_class}.json"
                document = self._arm_document(
                    root, receipt, release, model, model_metadata, change_class
                )
                document["change_class"] = change_class
                arm.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "governed model builder"):
                    validate_retrace_arm(arm)

    def test_receipt_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, release, model, model_metadata = self._write_receipt(root)
            release.write_text(release.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            arm = root / "arm.json"
            document = self._arm_document(
                root, receipt, release, model, model_metadata, "source"
            )
            arm.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity changed"):
                validate_retrace_arm(arm)

    def test_minimal_receipt_arm_run_local_fixture_closes_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arm, release, _ = self._write_run_local_arm_fixture(root / "source_case")
            document = json.loads(arm.read_text(encoding="utf-8"))
            run_root = arm.parents[1]
            self.assertEqual(Path(document["output_root"]), run_root / "results")
            self.assertEqual(
                Path(document["output_model"]), run_root / "comsol" / "retrace.mph"
            )
            plan = validate_retrace_arm(arm)
            self.assertEqual(plan["change_class"], "voltage")
            self.assertFalse(plan["mesh_rebuild"])
            self.assertTrue(plan["electrostatics"])
            self.assertTrue(plan["particles"])

            release.write_text(
                release.read_text(encoding="utf-8").replace("4392", "4393", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "release identity changed"):
                validate_retrace_arm(arm)

            model_root = root / "model_case"
            model_arm, _, model = self._write_run_local_arm_fixture(model_root)
            model.write_bytes(model.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "source model identity differs"):
                validate_retrace_arm(model_arm)

    def test_single_matlab_core_owns_solver_and_census_contract(self) -> None:
        core = (STAGE_ROOT / "run_retrace_arm.m").read_text(encoding="utf-8")
        for token in ("model.study('std1').run", "model.study('std2').run"):
            self.assertIn(token, core)
        for status in ("hit", "wall", "escape", "timeout", "solver_failure"):
            self.assertIn(f'"{status}"', core)
        self.assertIn("maximumVelocityResidual < 1e-6", core)
        self.assertIn("receipt.source_model.mph.sha256", core)
        self.assertIn("arm.baseline_field_mask", core)
        self.assertIn("arm.baseline_voltages_V", core)
        self.assertIn('status(particle) = "solver_failure"', core)
    def test_powershell_core_and_recovery_own_run_lifecycle(self) -> None:
        recovery = (WORKFLOW_ROOT / "recover_completed_solver_run.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("--require-status failed", recovery)
        self.assertIn("solver_reexecuted=$false", recovery)
        self.assertNotIn("run_comsol_r2025b.ps1", recovery)

        core = (WORKFLOW_ROOT / "execute_retrace_arm.ps1").read_text(encoding="utf-8")
        self.assertIn("artifact_naming.py", core)
        self.assertIn("Write-VerifiedRunManifest", core)
        self.assertIn("-Status interrupted", core)
        self.assertIn("Complete-FailedRun", core)
        self.assertIn("expectedOutputRoot", core)

    def test_rejects_particle_outside_stage1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = root / "checkpoints.csv"
            checkpoints.write_text(
                "particle_id,event,instrument_time_us,x_mm,y_mm,z_mm,vx_mm_per_us,"
                "vy_mm_per_us,vz_mm_per_us,kinetic_energy_eV,pulse_eligibility\n"
                "1,pre_pulse_state,1,-69,0,-63,4.392,0,0,9.99616396028,eligible\n",
                encoding="utf-8",
            )
            geometry = root / "geometry.json"
            geometry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "oa_tof_resolved_contract_do_not_edit",
                        "geometry_mm": {
                            "accelerator_repeller_z": -67,
                            "accelerator_grid1_z": -64,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "outside accelerator stage 1"):
                build_comsol_prepulse_replay(
                    checkpoints,
                    geometry,
                    root / "out.csv",
                    root / "metadata.json",
                    mass_amu=100,
                    charge_state=1,
                )


if __name__ == "__main__":
    unittest.main()
