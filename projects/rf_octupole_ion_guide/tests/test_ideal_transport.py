import json
import math
import unittest
from pathlib import Path

from common.multipole.ideal_transport import (
    adiabaticity,
    electric_field_xy,
    evaluate_contract,
    potential_spatial,
    pseudopotential_ev,
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


if __name__ == "__main__":
    unittest.main()
