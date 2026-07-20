from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
SCRIPT = PROJECT_ROOT / "analysis" / "quadrupole_l0.py"
SPEC = importlib.util.spec_from_file_location("quadrupole_l0", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class QuadrupoleL0TheoryTests(unittest.TestCase):
    def test_first_stability_region_vectors(self) -> None:
        apex = MODULE.first_stability_apex()
        self.assertAlmostEqual(apex["a"], 0.236994, delta=1e-6)
        self.assertAlmostEqual(apex["q"], 0.705996, delta=1e-6)
        self.assertAlmostEqual(MODULE.rf_only_cutoff(), 0.908046, delta=1e-6)

    def test_scanline_uv_0160_vector(self) -> None:
        result = MODULE.scanline_passband(0.1600)
        self.assertAlmostEqual(result["q_in"], 0.669866, delta=1e-6)
        self.assertAlmostEqual(result["q_out"], 0.713504, delta=1e-6)
        self.assertAlmostEqual(result["q_cal"], 0.690997, delta=1e-6)
        self.assertAlmostEqual(result["resolving_power_stability"], 15.9, delta=0.1)

    def test_mass_scale_example(self) -> None:
        mass = MODULE.mass_to_charge_th(
            q_cal=0.7036566,
            rf_amplitude_v_zero_to_peak_per_group=460.659,
            r0_mm=4.0,
            frequency_hz=2.0e6,
        )
        self.assertAlmostEqual(mass, 100.0, delta=2e-4)

    def test_mathieu_parameters_round_trip(self) -> None:
        q = 0.7060233009794091
        mass = MODULE.mass_to_charge_th(q, 139.81792, 4.0, 1.1e6)
        parameters = MODULE.mathieu_parameters(mass, 0.0, 139.81792, 4.0, 1.1e6)
        self.assertAlmostEqual(mass, 100.0, delta=1e-12)
        self.assertAlmostEqual(parameters["q"], q, delta=1e-12)
        self.assertEqual(parameters["a"], 0.0)


class MassFilterReferenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_json(PROJECT_ROOT / "config" / "baseline.json")
        cls.mode = load_json(PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json")

    def test_frozen_reference_uses_explicit_voltage_semantics(self) -> None:
        self.assertEqual(self.mode["schema_version"], 2)
        result = MODULE.validate_mass_filter_reference(self.baseline, self.mode)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["mode_status"], "frozen_future_mode_not_yet_validated")
        self.assertAlmostEqual(result["q_at_tune_mass"], 0.7060233, delta=1e-7)
        self.assertAlmostEqual(result["a_at_tune_mass"], 0.2298878, delta=1e-7)
        self.assertAlmostEqual(result["dc_differential_V"], 45.52602987935551, delta=1e-12)
        self.assertAlmostEqual(result["rf_differential_V_peak_to_peak"], 559.27168, delta=1e-12)

    def test_ambiguous_or_wrong_voltage_reference_is_rejected(self) -> None:
        changed = copy.deepcopy(self.mode)
        changed["theory_contract"]["voltage"]["reference"] = "unspecified"
        with self.assertRaisesRegex(ValueError, "voltage.reference"):
            MODULE.validate_mass_filter_reference(self.baseline, changed)

    def test_dc_value_cannot_be_mislabeled_as_differential(self) -> None:
        changed = copy.deepcopy(self.mode)
        changed["rf"]["dc_amplitude_V_per_group"] *= 2.0
        with self.assertRaisesRegex(ValueError, "DC amplitude"):
            MODULE.validate_mass_filter_reference(self.baseline, changed)


if __name__ == "__main__":
    unittest.main()
