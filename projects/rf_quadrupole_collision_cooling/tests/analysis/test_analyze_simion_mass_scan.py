from __future__ import annotations

import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import analyze_simion_mass_scan as MODULE


PROJECT_ROOT = Path(__file__).parents[2]


class AnalyzeSimionMassScanTests(unittest.TestCase):
    def test_functional_response_passes_center_and_endpoint_contrast(self) -> None:
        response = [
            {"mass_Th": 96.0, "particles": 25, "transmitted": 0, "transmission_fraction": 0.0},
            {"mass_Th": 101.5, "particles": 25, "transmitted": 25, "transmission_fraction": 1.0},
            {"mass_Th": 106.0, "particles": 25, "transmitted": 1, "transmission_fraction": 0.04},
        ]
        baseline = MODULE.json.loads((PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8"))
        mode = MODULE.json.loads(
            (PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json").read_text(encoding="utf-8")
        )
        metrics = MODULE.evaluate(response, baseline, mode)
        self.assertEqual(metrics["status"], "PASS")
        self.assertAlmostEqual(metrics["center_to_endpoint_contrast"], 0.96)

    def test_particle_identity_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "particle IDs differ"):
            MODULE.aggregate_response({1: 100.0}, {2: "transmitted"})


if __name__ == "__main__":
    unittest.main()
