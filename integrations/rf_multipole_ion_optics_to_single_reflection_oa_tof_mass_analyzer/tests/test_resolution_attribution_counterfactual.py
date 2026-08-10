from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual import (
    _remove_linear_covariance,
    _collapse_linear_residual,
    _quantile_match_centered,
    _state_summary,
    _validate_profile,
    prepare,
)


PROFILE = Path(__file__).parents[1] / "config" / "resolution_attribution_counterfactual.json"
WORKFLOW = Path(__file__).parents[1] / "workflows" / "resolution_attribution" / "execute.ps1"


class ResolutionAttributionCounterfactualTests(unittest.TestCase):
    def test_n1000_workflow_uses_governed_process_parallel_batches(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("Start-Job", workflow)
        self.assertNotIn("Start-ThreadJob", workflow)

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
                writer.writerow(["initial_x_mm", "initial_y_mm", "initial_z_mm"])
                for value in (-0.5, -0.1, 0.1, 0.5):
                    writer.writerow([value, value / 2, value / 3])
            result = prepare(
                PROFILE, checkpoints, ideal, root / "prepared", 100.0, 1,
                1.1e6, 4,
            )
            self.assertEqual(result["paired_cohort_particles"], 4)
            self.assertEqual(len(result["arms"]), 11)
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
            self.assertEqual(manifest["profile_id"], "pre_pulse_phase_space_attribution_v2")

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
