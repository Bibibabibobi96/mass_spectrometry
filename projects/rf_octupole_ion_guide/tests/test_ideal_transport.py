import json
import math
import unittest
from pathlib import Path

from common.multipole.analyze_round_rod_screen import analyze
from common.multipole.ideal_transport import (
    adiabaticity,
    electric_field_xy,
    evaluate_contract,
    evaluate_round_rod_contract,
    potential_spatial,
    pseudopotential_ev,
    source_particles,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OctupoleIdealTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8"))

    def test_identity_and_angular_symmetry(self):
        self.assertEqual(self.contract["multipole"], {"electrode_count": 8, "radial_order_n": 4, "orientation_rad": 0.0})
        radius = 0.001
        left = potential_spatial(4, 0.004, radius, 0.0)
        right = potential_spatial(4, 0.004, radius * math.cos(math.pi / 4), radius * math.sin(math.pi / 4))
        self.assertAlmostEqual(left, -right, places=14)

    def test_field_pseudopotential_and_adiabaticity_scaling(self):
        e1 = math.hypot(*electric_field_xy(4, 0.004, 1.0, 0.0005, 0.0))
        e2 = math.hypot(*electric_field_xy(4, 0.004, 1.0, 0.001, 0.0))
        self.assertAlmostEqual(e2 / e1, 8.0, places=12)
        args = (4, 0.004, 139.81792, 1.1e6, 100.0, 1)
        self.assertAlmostEqual(pseudopotential_ev(4, 0.002, *args[1:]) / pseudopotential_ev(4, 0.001, *args[1:]), 64.0, places=10)
        self.assertAlmostEqual(adiabaticity(4, 0.002, *args[1:]) / adiabaticity(4, 0.001, *args[1:]), 4.0, places=10)

    def test_l1_functional_gate(self):
        metrics, rows = evaluate_contract(self.contract)
        self.assertEqual(metrics["status"], "PASS")
        self.assertEqual(len(rows), 50)

    def test_round_rod_screen_recovers_boundary_normalized_harmonic(self):
        screen = json.loads((PROJECT_ROOT / "config" / "round_rod_field_screen.json").read_text(encoding="utf-8"))
        rows = []
        for ratio, parasitic in ((0.3, 0.025), (1 / 3, 0.008)):
            for radius_mm in (1.6, 2.4):
                for index in range(128):
                    theta = 2 * math.pi * index / 128
                    rho = radius_mm / 4.0
                    value = 100 * (rho**4 * math.cos(4 * theta) + parasitic * rho**12 * math.cos(12 * theta))
                    rows.append({"rod_radius_ratio": str(ratio), "sample_radius_mm": str(radius_mm), "theta_rad": str(theta), "potential_V": str(value)})
        result = analyze(rows, screen)
        self.assertAlmostEqual(result["selected_candidate"]["rod_radius_ratio"], 1 / 3)
        self.assertAlmostEqual(result["selected_candidate"]["harmonics"]["normalized_a12_over_a4"], 0.008, places=10)

    def test_round_rod_l2_functional_gate(self):
        screen = {
            "field_solve_drive_V": 100.0,
            "selected_candidate": {
                "rod_radius_ratio": 0.36, "rod_radius_mm": 1.44,
                "rod_center_radius_mm": 5.44, "minimum_adjacent_surface_gap_mm": 1.28,
                "parasitic_harmonic_score": 0.005,
                "boundary_cosine_coefficients_V": {"4": 100.0, "12": -0.3, "20": 0.2},
            },
        }
        metrics, rows = evaluate_round_rod_contract(self.contract, screen)
        self.assertEqual(metrics["status"], "PASS")
        self.assertEqual(len(rows), 50)

    def test_finite_3d_contract_preserves_baseline_source_and_length(self):
        l3 = json.loads((PROJECT_ROOT / "config" / "finite_3d_transport.json").read_text(encoding="utf-8"))
        self.assertEqual(l3["multipole"], {"radial_order_n": 4, "electrode_count": 8})
        self.assertEqual(l3["geometry_mm"]["rod_length"], self.contract["geometry_mm"]["effective_length"])
        self.assertLess(l3["geometry_mm"]["vacuum_z_min"], l3["geometry_mm"]["source_z"])
        self.assertEqual(len(source_particles(self.contract)), self.contract["particle_source"]["count"])


if __name__ == "__main__":
    unittest.main()
