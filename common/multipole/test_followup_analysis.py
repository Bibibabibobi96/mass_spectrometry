import unittest

from common.multipole.followup_analysis import (
    factorial_interaction,
    fixed_bin_index,
    normalized_cell_xyz,
)


class FollowupAnalysisTests(unittest.TestCase):
    def test_legacy_and_anisotropic_cells_normalize(self) -> None:
        self.assertEqual(
            normalized_cell_xyz({"cell_mm": 0.3}),
            (0.3, 0.3, 0.3),
        )
        self.assertEqual(
            normalized_cell_xyz(
                {"cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.3}}
            ),
            (0.2, 0.2, 0.3),
        )

    def test_fixed_bin_edges_are_closed_at_upper_bound(self) -> None:
        specification = {"minimum": 0.0, "maximum": 4.0, "count": 4}
        self.assertEqual(fixed_bin_index(0.0, specification), 0)
        self.assertEqual(fixed_bin_index(3.999, specification), 3)
        self.assertEqual(fixed_bin_index(4.0, specification), 3)
        with self.assertRaisesRegex(ValueError, "outside"):
            fixed_bin_index(4.1, specification)

    def test_factorial_interaction_reports_signed_and_particle_rms(self) -> None:
        def run(value: float) -> dict:
            observables = {
                "rms_radius": value,
                "rms_divergence": value,
                "mean_energy": value,
                "mean_tof": value,
            }
            row = {
                "transverse_x_mm": value,
                "transverse_y_mm": value,
                "velocity_x_m_s": value,
                "velocity_y_m_s": value,
                "elapsed_time_us": value,
                "kinetic_energy_eV": value,
            }
            return {
                "observables": observables,
                "handoff_particle_ids": [1],
                "_handoff": {1: row},
            }

        result = factorial_interaction(
            {"A": run(1.0), "R": run(2.0), "Z": run(3.0), "I": run(7.0)}
        )
        self.assertEqual(
            result["summary_observable_signed_interaction"]["rms_radius"], 3.0
        )
        self.assertEqual(
            result["paired_particle_interaction_rms"]["kinetic_energy_eV"], 3.0
        )


if __name__ == "__main__":
    unittest.main()
