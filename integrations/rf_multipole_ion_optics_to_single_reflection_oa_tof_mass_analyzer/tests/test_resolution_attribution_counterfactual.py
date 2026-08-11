from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual import (
    _checkpoint_detector_times,
    _remove_linear_covariance,
    _collapse_linear_residual,
    _project_observed_linear_slope,
    _quantile_match_centered,
    _state_summary,
    _validate_profile,
    prepare,
)


PROFILE = Path(__file__).parents[1] / "config" / "resolution_attribution_counterfactual.json"
WORKFLOW = Path(__file__).parents[1] / "workflows" / "resolution_attribution" / "execute.ps1"


class ResolutionAttributionCounterfactualTests(unittest.TestCase):
    def test_checkpoint_detector_time_is_not_offset_by_release_time_twice(self) -> None:
        rows = [
            {"particle_id": "1", "event": "source_release", "instrument_time_us": "0.4"},
            {"particle_id": "1", "event": "detector_crossing", "instrument_time_us": "76.7"},
        ]
        self.assertEqual(_checkpoint_detector_times(rows), {1: 76.7})

    def test_n1000_workflow_uses_governed_process_parallel_batches(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("Start-Job", workflow)
        self.assertNotIn("Start-ThreadJob", workflow)

    def test_workflow_can_pair_a_frozen_source_with_a_selected_frontend(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("$FrontendRunId", workflow)
        self.assertIn("Frontend source run changes frozen physical input", workflow)
        self.assertIn("PSObject.Properties.Remove('sources')", workflow)
        self.assertIn("$prepareArguments += @('--arm-id',$selectedArmId)", workflow)
        self.assertIn("Reference arm was not prepared", workflow)
        self.assertIn("$currentArmId = [string]$arm.arm_id", workflow)
        self.assertNotIn("$armId = [string]$arm.arm_id", workflow)

    def test_centered_quantile_match_preserves_current_geometry_center(self) -> None:
        values = np.asarray([-70.0, -69.0, -68.0])
        reference = np.asarray([-49.3, -48.8, -48.3])
        matched = _quantile_match_centered(values, reference)
        self.assertAlmostEqual(float(np.mean(matched)), -69.0, places=12)
        self.assertAlmostEqual(float(np.ptp(matched)), 2.0 / 3.0, places=12)

    def test_remove_covariance_preserves_velocity_mean_and_sample_sigma(self) -> None:
        z = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0])
        vz = np.asarray([-4.0, -0.5, 1.0, 2.5, 6.0])
        adjusted = _remove_linear_covariance(z, vz)
        self.assertAlmostEqual(float(np.mean(adjusted)), float(np.mean(vz)), places=12)
        self.assertAlmostEqual(float(np.std(adjusted, ddof=1)), float(np.std(vz, ddof=1)), places=12)
        self.assertAlmostEqual(float(np.cov(z, adjusted, ddof=1)[0, 1]), 0.0, places=12)

    def test_collapse_residual_preserves_observed_linear_relation(self) -> None:
        z = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0])
        vz = np.asarray([-4.0, -0.5, 1.0, 2.5, 6.0])
        adjusted = _collapse_linear_residual(z, vz)
        self.assertAlmostEqual(float(np.mean(adjusted)), float(np.mean(vz)), places=12)
        self.assertAlmostEqual(float(np.corrcoef(z, adjusted)[0, 1]), 1.0, places=12)

    def test_project_observed_slope_scales_velocity_with_target_width(self) -> None:
        observed_z = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0])
        observed_vz = np.asarray([-4.0, -0.5, 1.0, 2.5, 6.0])
        target_z = observed_z / 2.0
        adjusted = _project_observed_linear_slope(
            observed_z, observed_vz, target_z
        )
        observed_slope = np.cov(observed_z, observed_vz, ddof=1)[0, 1] / np.var(
            observed_z, ddof=1
        )
        target_slope = np.cov(target_z, adjusted, ddof=1)[0, 1] / np.var(
            target_z, ddof=1
        )
        self.assertAlmostEqual(float(target_slope), float(observed_slope), places=12)
        self.assertAlmostEqual(
            float(np.mean(adjusted)), float(np.mean(observed_vz)), places=12
        )

    def test_prepare_uses_fixed_common_particle_identity_for_every_arm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = root / "checkpoints.csv"
            ideal = root / "ideal.csv"
            with checkpoints.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(
                    [
                        "particle_id",
                        "event",
                        "instrument_time_us",
                        "x_mm",
                        "y_mm",
                        "z_mm",
                        "vx_mm_per_us",
                        "vy_mm_per_us",
                        "vz_mm_per_us",
                    ]
                )
                for particle_id in range(1, 5):
                    vz = [0.01, 0.04, 0.02, 0.08][particle_id - 1]
                    writer.writerow(
                        [particle_id, "pre_pulse_state", 10, particle_id, particle_id / 2, particle_id / 3, 2, 0.1, vz]
                    )
                    writer.writerow([particle_id, "detector_crossing", 20 + particle_id / 1000, 0, 0, 0, "", "", ""])
            with ideal.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "initial_x_mm", "initial_y_mm",
                    "initial_z_mm", "initial_energy_eV"
                ])
                for particle_id, value in enumerate((-0.5, -0.1, 0.1, 0.5), 1):
                    writer.writerow([particle_id, value, value / 2, value / 3, 4 + particle_id / 10])
            formal_geometry = root / "formal_geometry.json"
            formal_geometry.write_text(json.dumps({"particle_source": {
                "center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": 0.0,
                "size_x_mm": 1.0, "size_y_mm": 1.0, "size_z_mm": 1.0
            }}), encoding="utf-8")
            target_geometry = root / "target_geometry.json"
            target_geometry.write_text(json.dumps({"particle_source": {
                "center_x_mm": 10.0, "center_y_mm": 20.0, "center_z_mm": 30.0,
                "size_x_mm": 2.0, "size_y_mm": 3.0, "size_z_mm": 4.0
            }}), encoding="utf-8")
            result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared", 100.0, 1,
                1.1e6, 4,
            )
            self.assertEqual(result["paired_cohort_particles"], 4)
            self.assertEqual(len(result["arms"]), 20)
            for arm in result["arms"]:
                state = root / "prepared" / arm["state_file"]
                with state.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual([int(row["source_particle_id"]) for row in rows], [1, 2, 3, 4])
                self.assertEqual({row["arm_id"] for row in rows}, {arm["arm_id"]})
                self.assertEqual(len(arm["execution_batches"]), 4)
                self.assertEqual(
                    sum(batch["particles"] for batch in arm["execution_batches"]), 4
                )
            manifest = json.loads((root / "prepared" / "prepared_arms.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["profile_id"], "pre_pulse_phase_space_attribution_v4")
            formal_state = root / "prepared" / "formal_ideal_source__source_state.csv"
            with formal_state.open(encoding="utf-8", newline="") as handle:
                formal_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [float(row["x_mm"]) for row in formal_rows],
                [9.5, 9.9, 10.1, 10.5],
            )
            self.assertEqual(
                [float(row["y_mm"]) for row in formal_rows],
                [19.75, 19.95, 20.05, 20.25],
            )
            np.testing.assert_allclose(
                [float(row["kinetic_energy_eV"]) for row in formal_rows],
                [4.1, 4.2, 4.3, 4.4],
                rtol=0.0,
                atol=1e-12,
            )
            self.assertTrue(all(float(row["vx_m_s"]) > 0 for row in formal_rows))
            self.assertTrue(all(float(row["vy_m_s"]) == 0 for row in formal_rows))
            self.assertTrue(all(float(row["vz_m_s"]) == 0 for row in formal_rows))
            layout_state = root / "prepared" / "current_layout_ideal_source__source_state.csv"
            with layout_state.open(encoding="utf-8", newline="") as handle:
                layout_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [float(row["x_mm"]) for row in layout_rows],
                [9.0, 9.8, 10.2, 11.0],
            )
            self.assertEqual(
                [float(row["z_mm"]) for row in layout_rows],
                [29.333333333333332, 29.866666666666667,
                 30.133333333333333, 30.666666666666668],
            )
            self.assertTrue(all(float(row["vy_m_s"]) == 0 for row in layout_rows))
            self.assertTrue(all(float(row["vz_m_s"]) == 0 for row in layout_rows))
            prepared_arm = next(
                arm for arm in result["arms"]
                if arm["arm_id"] == "formal_focus_mapped_layout_source"
            )
            self.assertEqual(prepared_arm["solver_profile_id"], "formal_reflectron")
            exact_arm = next(
                arm for arm in result["arms"]
                if arm["arm_id"] == "exact_formal_field_mapped_layout_source"
            )
            self.assertEqual(exact_arm["frontend_profile_id"], "formal_accelerator")

    def test_prepare_can_select_a_small_ordered_arm_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = root / "checkpoints.csv"
            ideal = root / "ideal.csv"
            with checkpoints.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm",
                    "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
                ])
                for particle_id in range(1, 4):
                    writer.writerow([
                        particle_id, "pre_pulse_state", 10, particle_id, 0, 0,
                        2, 0, 0,
                    ])
                    writer.writerow([
                        particle_id, "detector_crossing", 20, 0, 0, 0, "", "", "",
                    ])
            with ideal.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "initial_x_mm", "initial_y_mm",
                    "initial_z_mm", "initial_energy_eV",
                ])
                for particle_id in range(1, 4):
                    writer.writerow([particle_id, 0, 0, 0, 5])
            geometry = {
                "particle_source": {
                    "center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": 0.0,
                    "size_x_mm": 1.0, "size_y_mm": 1.0, "size_z_mm": 1.0,
                }
            }
            formal_geometry = root / "formal_geometry.json"
            target_geometry = root / "target_geometry.json"
            formal_geometry.write_text(json.dumps(geometry), encoding="utf-8")
            target_geometry.write_text(json.dumps(geometry), encoding="utf-8")
            arm_ids = [
                "formal_focus_mapped_layout_source",
                "exact_formal_field_mapped_layout_source",
            ]
            result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared", 100.0, 1, 1.1e6, 3,
                selected_arm_ids=arm_ids,
            )
            self.assertEqual([arm["arm_id"] for arm in result["arms"]], arm_ids)
            with self.assertRaisesRegex(ValueError, "unique"):
                prepare(
                    PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                    root / "duplicate", 100.0, 1, 1.1e6, 3,
                    selected_arm_ids=[arm_ids[0], arm_ids[0]],
                )
            with self.assertRaisesRegex(ValueError, "unknown"):
                prepare(
                    PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                    root / "unknown", 100.0, 1, 1.1e6, 3,
                    selected_arm_ids=["not_an_arm"],
                )

    def test_state_summary_uses_null_for_undefined_correlation(self) -> None:
        rows = [
            {
                "x_mm": str(index),
                "y_mm": "0",
                "z_mm": "1",
                "vx_m_s": "2000",
                "vy_m_s": "0",
                "vz_m_s": "3",
                "kinetic_energy_eV": "5",
            }
            for index in range(3)
        ]
        self.assertIsNone(_state_summary(rows)["z_vz_pearson"])

    def test_profile_rejects_unknown_fields(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        profile["unregistered_override"] = True
        with self.assertRaisesRegex(ValueError, "profile identity differs"):
            _validate_profile(profile)


if __name__ == "__main__":
    unittest.main()
