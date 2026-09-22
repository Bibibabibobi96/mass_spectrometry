from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_terminal_time_calibration import (
    derive_directions,
    materialize_variation,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class MirrorTerminalTimeCalibrationTests(unittest.TestCase):
    def _inputs(self, root: Path) -> tuple[Path, Path, Path]:
        jacobian = np.asarray((
            (2.0, 0.1, 0.0, 0.2),
            (0.2, 1.5, 0.1, 0.0),
            (0.0, 0.1, 1.2, 0.1),
        )) * 1e-8
        correction = root / "correction.json"
        correction.write_text(json.dumps({
            "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
            "updated_local_slope_jacobian_per_v2": jacobian.tolist(),
            "updated_fine_gamma_gradient_per_v": [1e-4, -2e-4, 3e-4, 4e-4],
            "energy_centers_ev": [3900, 4000, 4100],
            "proposed_mirror_voltages_v": [0, -6000, -2600, 3800, 6000],
        }), encoding="utf-8")
        point = root / "point.json"
        point.write_text(json.dumps({
            "role": "mrtof_fixed_grid_mirror_voltage_point",
            "mirror_voltages_v": [0, -6000, -2600, 3800, 6000],
        }), encoding="utf-8")
        contract = root / "contract.json"
        contract.write_text(json.dumps({"mirror": {"theory_requirements": {
            "voltage_envelope_v": {
                "B": {"power_supply_limits_v": {"minimum_inclusive_v": -10000,
                                                    "maximum_inclusive_v": 10000}},
                "C": {"power_supply_limits_v": {"minimum_inclusive_v": -5000,
                                                    "maximum_inclusive_v": 5000}},
                "D": {"power_supply_limits_v": {"minimum_inclusive_v": -5000,
                                                    "maximum_inclusive_v": 5000}},
                "E": {"power_supply_limits_v": {"minimum_inclusive_v": -10000,
                                                    "maximum_inclusive_v": 10000}},
            },
        }}}), encoding="utf-8")
        return correction, point, contract

    def test_derives_gamma_preserving_te1_te2_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            correction, point, contract = self._inputs(Path(directory))
            result = derive_directions(
                correction_path=correction, voltage_point_path=point,
                contract_path=contract, maximum_abs_seed_step_v=10,
            )
            self.assertEqual(result["status"], "screening_directions_derived")
            hierarchy = result["calibration_hierarchy"]
            self.assertIn("z=0", hierarchy["baseline"])
            self.assertIn("physical detector plane", hierarchy["primary_objective"])
            self.assertIn("target K and current return topology", hierarchy["preserved_constraints"])
            self.assertEqual(set(result["directions"]), {"TE1", "TE2"})
            for direction in result["directions"].values():
                self.assertAlmostEqual(max(map(abs, direction["positive_voltage_delta_v"])), 10)
                for candidate in direction["candidates"]:
                    self.assertAlmostEqual(candidate["predicted_gamma_trace_delta"], 0, places=14)
            te1 = result["directions"]["TE1"]["candidates"][1]
            self.assertTrue(np.allclose(
                te1["predicted_normalized_period_slope_delta_per_v"],
                [te1["predicted_normalized_period_slope_delta_per_v"][0]] * 3,
            ))

    def test_rejects_non_colocated_voltage_point(self):
        with tempfile.TemporaryDirectory() as directory:
            correction, point, contract = self._inputs(Path(directory))
            value = json.loads(point.read_text(encoding="utf-8"))
            value["mirror_voltages_v"][1] += 1
            point.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "not colocated"):
                derive_directions(
                    correction_path=correction, voltage_point_path=point,
                    contract_path=contract, maximum_abs_seed_step_v=10,
                )

    def test_materializes_identity_bound_variation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            correction, point, contract = self._inputs(root)
            seed_path = root / "seed.json"
            seed_path.write_text(json.dumps(derive_directions(
                correction_path=correction, voltage_point_path=point,
                contract_path=contract, maximum_abs_seed_step_v=10,
            )), encoding="utf-8")
            result = materialize_variation(
                seed_path=seed_path, mode="TE1", coordinate=1,
                output_path=root / "variation.json",
            )
            self.assertEqual(result["role"], "mrtof_terminal_time_mirror_voltage_variation")
            self.assertTrue(np.allclose(
                np.asarray(result["target_mirror_voltages_v"][1:])
                - np.asarray(result["base_mirror_voltages_v"][1:]),
                result["voltage_delta_v"],
            ))
            fractional = materialize_variation(
                seed_path=seed_path, mode="TE1", coordinate=0.25,
                output_path=root / "fractional_variation.json",
            )
            self.assertEqual(fractional["coordinate"], 0.25)
            self.assertTrue(np.allclose(
                fractional["voltage_delta_v"],
                0.25 * np.asarray(
                    json.loads(seed_path.read_text(encoding="utf-8"))
                    ["directions"]["TE1"]["positive_voltage_delta_v"]
                ),
            ))


if __name__ == "__main__":
    unittest.main()
