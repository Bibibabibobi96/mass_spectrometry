from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from common.ion_release.numpy_box_cone import sample_numpy_box_cone_phase_space
from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    run_finite_length as MODULE,
)

PROJECT_ROOT = Path(__file__).parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MassFilterL1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json")
        cls.resolved = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_mass_filter.json")
        cls.mode = load_json(PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json")
        cls.source = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json")

    def test_contract_brackets_theory_passband(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        self.assertAlmostEqual(derived["theory_low_mass_Th"], 99.3275, delta=0.001)
        self.assertAlmostEqual(derived["theory_high_mass_Th"], 103.4120, delta=0.001)
        self.assertAlmostEqual(derived["calibration_mass_Th"], 101.3707, delta=0.001)

    def test_l1_charge_is_exactly_positive_one_without_integer_truncation(self) -> None:
        for charge in (True, 1.5, -1, 0, float("nan"), float("inf")):
            with self.subTest(charge=charge), self.assertRaisesRegex(ValueError, "singly charged"):
                MODULE.validate_l1_contract(self.baseline, self.mode, {**self.source, "charge_state": charge})

    def test_sample_envelope_and_existing_functional_values_are_preserved(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        rows = [{"mass_Th": mass, "transmission_fraction": float(99.5 <= mass <= 103.5)}
                for mass in derived["masses_Th"]]
        result = MODULE.evaluate_response(rows, derived, self.mode)
        self.assertEqual({key: value for key, value in result.items() if key != "sampled_response_analysis"}, {
            "status": "PASS", "checks": {name: True for name in (
                "peak_transmission", "inside_band_transmission", "outside_endpoint_rejection",
                "low_boundary_alignment", "high_boundary_alignment")},
            "peak_mass_Th": 99.5, "peak_transmission": 1.0,
            "minimum_inside_theory_band_transmission": 1.0, "maximum_scan_endpoint_transmission": 0.0,
            "theory_passband_Th": [derived["theory_low_mass_Th"], derived["theory_high_mass_Th"]],
            "observed_half_maximum_band_Th": [99.5, 103.5], "mass_step_Th": 0.5,
        })
        self.assertEqual(result["sampled_response_analysis"]["interpolated_main_peak_fwhm_Th"], 4.5)
        for row in rows:
            row["transmission_fraction"] = 0.0
        zero = MODULE.evaluate_response(rows, derived, self.mode)
        self.assertEqual(zero["status"], "FAIL")
        self.assertIsNone(zero["observed_half_maximum_band_Th"])
        self.assertFalse(zero["checks"]["low_boundary_alignment"])
        self.assertFalse(zero["checks"]["high_boundary_alignment"])

    def test_frozen_l1_analysis_runs_from_snapshot_and_rejects_changed_peak_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, results = root / "inputs", root / "results"
            inputs.mkdir()
            results.mkdir()
            for filename, value in (("baseline.json", self.baseline), ("mass_filter_reference.json", self.mode),
                                    ("official_particle_source.json", self.source)):
                (inputs / filename).write_text(json.dumps(value), encoding="utf-8")
            derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
            count = int(self.mode["functional_screen"]["particle_count"])
            rows = [{"mass_Th": float(mass), "particles": count,
                     "transmitted": count if 99.5 <= mass <= 103.5 else 0,
                     "transmission_fraction": float(99.5 <= mass <= 103.5)}
                    for mass in derived["masses_Th"]]
            MODULE.write_response_csv(inputs / "mass_response_for_analysis.csv", rows)
            request, _ = MODULE._prepare_analysis_request(inputs, results)
            package = MODULE._invoke_analysis_stage(request, prepare_only=True)
            execution = MODULE._invoke_analysis_stage(request, prepare_only=False)
            self.assertTrue(execution["module_invoked"])
            origins = {entry["name"]: Path(entry["origin"]) for entry in execution["frozen_modules"]}
            for name in ("common.analysis.peak_metrics", "projects.rf_multipole_ion_optics.core.mass_response"):
                self.assertTrue(origins[name].is_relative_to(inputs / "analysis_code"))
            actual = load_json(results / "mass-filter__functional-metrics.json")
            self.assertEqual(actual["status"], "PASS")
            self.assertEqual(actual["sampled_response_analysis"], MODULE.evaluate_response(rows, derived, self.mode)["sampled_response_analysis"])
            self.assertTrue((results / "mass-response__passband.png").is_file())
            peak = origins["common.analysis.peak_metrics"]
            original = peak.read_bytes()
            peak.write_bytes(original + b"\n# changed frozen source\n")
            with self.assertRaisesRegex(RuntimeError, "hash differs"):
                MODULE._invoke_analysis_stage(request, prepare_only=False)
            peak.write_bytes(original)
            peak.unlink()
            with self.assertRaisesRegex(RuntimeError, "missing"):
                MODULE._invoke_analysis_stage(request, prepare_only=False)
            self.assertEqual(len(package["package"]["files"]), 11)

    def test_finite_length_screen_transmits_tuned_and_rejects_outer_masses(self) -> None:
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        transmissions = {}
        for mass in (96.0, 101.5, 106.0):
            result = MODULE.simulate_mass(mass, particles, self.resolved, 80)
            transmissions[mass] = result["transmission_fraction"]
        self.assertGreaterEqual(transmissions[101.5], 0.9)
        self.assertLessEqual(transmissions[96.0], 0.1)
        self.assertLessEqual(transmissions[106.0], 0.1)

    def test_l1_projection_preserves_common_box_cone_release(self) -> None:
        release = sample_numpy_box_cone_phase_space(
            source=self.source, seed=20260722, particle_count=64,
        )
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        self.assertTrue(np.array_equal(particles["x_m"], release["transverse_1_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["y_m"], release["transverse_2_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["energy_j"], release["energy_eV"] * MODULE.electron_volt))
        self.assertTrue(np.array_equal(particles["direction_x"], release["direction_transverse_1"]))
        self.assertTrue(np.array_equal(particles["direction_y"], release["direction_transverse_2"]))
        self.assertTrue(np.array_equal(particles["direction_z"], release["direction_axial"]))
        self.assertTrue(np.array_equal(particles["rf_phase_rad"], release["phase_rad"]))


if __name__ == "__main__":
    unittest.main()
