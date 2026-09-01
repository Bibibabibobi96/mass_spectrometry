from __future__ import annotations

import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_total_axis_field import (
    analyze,
)


class TotalAxisFieldAnalysisTests(unittest.TestCase):
    def test_reports_zonewise_error_against_piecewise_uniform_candidate(self) -> None:
        geometry = {
            "accelerator_topology": {
                "planes_global_z_mm": {
                    "repeller": 0.0,
                    "intermediate1": 1.0,
                    "intermediate2": 3.0,
                    "exit": 6.0,
                },
                "potentials_v": {
                    "repeller": 12.0,
                    "intermediate1": 10.0,
                    "intermediate2": 4.0,
                    "exit": 1.0,
                },
            }
        }
        rows = [
            {"z_mm": 0.5, "potential_V": 11.0, "Ez_V_per_mm": 2.0},
            {"z_mm": 1.5, "potential_V": 8.5, "Ez_V_per_mm": 2.0},
            {"z_mm": 2.5, "potential_V": 5.5, "Ez_V_per_mm": 4.0},
            {"z_mm": 4.0, "potential_V": 3.0, "Ez_V_per_mm": 1.0},
            {"z_mm": 5.0, "potential_V": 2.0, "Ez_V_per_mm": 1.0},
        ]
        result = analyze(rows, geometry)
        self.assertEqual(result["claim_status"], "DIAGNOSTIC_ONLY")
        self.assertEqual([zone["sample_count"] for zone in result["zones"]], [1, 2, 2])
        self.assertEqual([zone["expected_Ez_V_per_mm"] for zone in result["zones"]], [2.0, 3.0, 1.0])
        self.assertAlmostEqual(result["zones"][1]["mean_Ez_V_per_mm"], 3.0)
        self.assertAlmostEqual(result["zones"][1]["rms_error_V_per_mm"], 1.0)

    def test_rejects_missing_interior_zone_samples(self) -> None:
        geometry = {
            "accelerator_topology": {
                "planes_global_z_mm": {
                    "repeller": 0.0,
                    "intermediate1": 1.0,
                    "intermediate2": 2.0,
                    "exit": 3.0,
                },
                "potentials_v": {
                    "repeller": 3.0,
                    "intermediate1": 2.0,
                    "intermediate2": 1.0,
                    "exit": 0.0,
                },
            }
        }
        with self.assertRaisesRegex(ValueError, "no interior samples"):
            analyze([
                {"z_mm": 0.5, "potential_V": 2.5, "Ez_V_per_mm": 1.0},
                {"z_mm": 1.5, "potential_V": 1.5, "Ez_V_per_mm": 1.0},
            ], geometry)
