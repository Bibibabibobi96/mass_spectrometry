from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_square_cylindrical_axis_target import (
    analyze_square_cylindrical_axis_target,
)


class SquareCylindricalAxisTargetTest(unittest.TestCase):
    def _run(self, root: Path, name: str, realization: str, *, checkpoints: bool = False, axis_field: bool = True) -> Path:
        run = root / name
        (run / "inputs").mkdir(parents=True)
        (run / "results").mkdir()
        for filename in ("summary.json", "run_manifest.json"):
            (run / filename).write_text(json.dumps({"status": "success"}), encoding="utf-8")
        candidate = {
            "source_identity": {"frozen_source": {"mass_to_charge_th": 100.0, "charge_sign": 1}},
            "accelerator_topology": {
                "planes_global_z_mm": {"repeller": 0.0, "intermediate1": 1.0, "intermediate2": 3.0, "exit": 6.0},
                "potentials_v": {"repeller": 600.0, "intermediate1": 500.0, "intermediate2": 300.0, "exit": 0.0},
            },
        }
        candidate_path = run / "inputs" / "three_zone_t5_candidate_resolved.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        geometry = {
            "accelerator_topology": candidate["accelerator_topology"],
            "geometry_derivation": {"accelerator": {"realization_id": realization}},
            "single_flight_layout_derivation": {"design_compilation": {"candidate": {"sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest().upper()}}},
            "rings": {"accelerator_placement": {"ring_z_mm": [2.0, 4.0]}, "accelerator_count": 2},
        }
        (run / "inputs" / "oatof_resolved_geometry.json").write_text(json.dumps(geometry), encoding="utf-8")
        (run / "inputs" / "resolved_single_flight_execution_profile.json").write_text(json.dumps({"time_integration_profile_id": "dt40"}), encoding="utf-8")
        pulse = {"policy": {"policy_id": "test"}, "rf_period_us": 1.0, "pulse_base_time_us": 2.0, "pulse_offset_us": 0.0, "pulse_effective_time_us": 2.0, "source_state_sha256": "SOURCE", "selected_particle_ids": [1, 2]}
        (run / "inputs" / "resolved_single_flight_pulse_schedule.json").write_text(json.dumps(pulse), encoding="utf-8")
        source = {"source_branches": {"simion": {"source": {"state": {"sha256": "SOURCE"}, "manifest": {"sha256": "MANIFEST"}, "particle_count": 2}}}}
        (run / "inputs" / "resolved_source_contract.json").write_text(json.dumps(source), encoding="utf-8")
        if axis_field:
            with (run / "results" / "total_axis_field.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("z_mm", "Ez_V_per_mm"))
                writer.writeheader()
                for z in range(7):
                    writer.writerow({"z_mm": z, "Ez_V_per_mm": 100.0})
        if checkpoints:
            with (run / "results" / "single_flight_particle_checkpoints.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("particle_id", "event", "z_mm", "vz_mm_per_us"))
                writer.writeheader()
                for particle_id in (1, 2):
                    writer.writerow({"particle_id": particle_id, "event": "pre_pulse_state", "z_mm": 0.1, "vz_mm_per_us": 0.0})
                    writer.writerow({"particle_id": particle_id, "event": "local_accelerator_exit", "z_mm": 6.0, "vz_mm_per_us": 0.0})
        return run

    def test_reports_shared_target_drops_and_clean_integrator_interface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = analyze_square_cylindrical_axis_target(square_run=self._run(root, "square", "square_3d"), cylindrical_run=self._run(root, "cyl", "cylindrical_3d"))
        self.assertEqual(result["conclusion"], "PASS_CONTINUE")
        self.assertEqual(result["realizations"]["square"]["integrated_drops"]["whole_accelerator"]["exported_integral_ez_dz_v"], 600.0)
        self.assertEqual(result["independent_axis_integrator"]["square"]["status"], "NOT_RUN")
        self.assertEqual(result["square_minus_cylindrical_axis_field_diagnostic"]["ez_difference_max_abs_v_per_mm"], 0.0)

    def test_rejects_mismatched_numerics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            square, cylindrical = self._run(root, "square", "square_3d"), self._run(root, "cyl", "cylindrical_3d")
            (cylindrical / "inputs" / "resolved_single_flight_execution_profile.json").write_text(json.dumps({"time_integration_profile_id": "dt160"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "numerics differs"):
                analyze_square_cylindrical_axis_target(square_run=square, cylindrical_run=cylindrical)

    def test_uses_saved_trajectory_receipt_without_solver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            square, cylindrical = self._run(root, "square", "square_3d"), self._run(root, "cyl", "cylindrical_3d")
            square_trajectory = self._run(root, "square_trajectory", "square_3d", checkpoints=True, axis_field=False)
            cylindrical_trajectory = self._run(root, "cyl_trajectory", "cylindrical_3d", checkpoints=True, axis_field=False)
            result = analyze_square_cylindrical_axis_target(square_run=square, cylindrical_run=cylindrical, square_trajectory_run=square_trajectory, cylindrical_trajectory_run=cylindrical_trajectory)
        self.assertEqual(result["independent_axis_integrator"]["square"]["status"], "RUN")
        self.assertLess(result["independent_axis_integrator"]["square"]["finest_pair_relative_difference"], 0.01)


if __name__ == "__main__":
    unittest.main()
