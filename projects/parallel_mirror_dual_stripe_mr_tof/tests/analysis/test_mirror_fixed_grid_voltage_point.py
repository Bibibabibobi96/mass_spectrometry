from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_grid_voltage_point import (
    build_fixed_grid_point_receipt,
    build_secant_point_receipt,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class FixedGridVoltagePointTests(unittest.TestCase):
    def test_secant_point_is_bounded_and_remains_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            family = root / "family.json"
            contract = root / "contract.json"
            correction = root / "correction.json"
            output = root / "point.json"
            family.write_text(json.dumps({
                "voltage_bounds_v": {
                    "mirror_B": [-10000, 10000], "mirror_C": [-5000, 5000],
                    "mirror_D": [-5000, 5000], "mirror_E": [-10000, 10000],
                },
                "energy_centers_ev": [3900, 4000, 4100],
                "period_slope_derivative_step_ev": 1.0,
            }))
            contract.write_text(json.dumps({
                "mirror": {"theory_requirements": {
                    "fixed_grid_multifidelity_correction_profile": {
                        "status": "local_proposal_only__independent_fixed_grid_validation_required"
                    }
                }}
            }))
            correction.write_text(json.dumps({
                "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
                "status": "no_local_gamma_bracket__additional_fixed_grid_secant_required",
                "source_root_index": 0,
                "inputs": {"family_sha256": file_sha256(family), "refinement_sha256": "A" * 64},
                "recommended_secant_fixed_grid_point": {
                    "purpose": "measure_fixed_minus_coarse_discrepancy_along_the_coarse_L0_family",
                    "mirror_voltages_v": [0, -5900, -2600, 4200, 6000],
                    "mirror_E_step_from_source_v": 0.5,
                    "coarse_normalized_period_slopes_per_v": [0, 0, 0],
                },
            }))
            result = build_secant_point_receipt(
                correction_path=correction, family_path=family,
                contract_path=contract, output_path=output,
            )
            self.assertEqual(result["role"], "mrtof_fixed_grid_mirror_voltage_point")
            self.assertIn("not_a_candidate", result["qualification"])

    def test_out_of_bounds_point_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            family = root / "family.json"
            contract = root / "contract.json"
            correction = root / "correction.json"
            family.write_text(json.dumps({
                "voltage_bounds_v": {group: [-1, 1] for group in (
                    "mirror_B", "mirror_C", "mirror_D", "mirror_E"
                )},
                "energy_centers_ev": [0.1, 0.2, 0.3],
                "period_slope_derivative_step_ev": 0.01,
            }))
            contract.write_text(json.dumps({"mirror": {"theory_requirements": {
                "fixed_grid_multifidelity_correction_profile": {
                    "status": "local_proposal_only__independent_fixed_grid_validation_required"
                }
            }}}))
            correction.write_text(json.dumps({
                "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
                "status": "no_local_gamma_bracket__additional_fixed_grid_secant_required",
                "source_root_index": 0,
                "inputs": {"family_sha256": file_sha256(family), "refinement_sha256": "A" * 64},
                "recommended_secant_fixed_grid_point": {
                    "purpose": "test", "mirror_voltages_v": [0, 2, 0, 0, 1],
                    "mirror_E_step_from_source_v": 0.5,
                    "coarse_normalized_period_slopes_per_v": [0, 0, 0],
                },
            }))
            with self.assertRaisesRegex(CandidateContractError, "out of bounds"):
                build_secant_point_receipt(
                    correction_path=correction, family_path=family,
                    contract_path=contract, output_path=root / "point.json",
                )

    def test_secant_model_proposal_becomes_an_independent_validation_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            family = root / "family.json"
            contract = root / "contract.json"
            correction = root / "correction.json"
            output = root / "point.json"
            family.write_text(json.dumps({
                "voltage_bounds_v": {
                    "mirror_B": [-10000, 10000], "mirror_C": [-5000, 5000],
                    "mirror_D": [-5000, 5000], "mirror_E": [-10000, 10000],
                },
                "energy_centers_ev": [3900, 4000, 4100],
                "period_slope_derivative_step_ev": 1.0,
            }))
            contract.write_text(json.dumps({"mirror": {"theory_requirements": {
                "fixed_grid_multifidelity_correction_profile": {
                    "status": "local_proposal_only__independent_fixed_grid_validation_required"
                }
            }}}))
            correction.write_text(json.dumps({
                "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
                "status": "secant_proposal_only__independent_fixed_grid_validation_required",
                "source_root_index": 0,
                "source_refinement_sha256": "A" * 64,
                "source_mirror_voltages_v": [0, -5900, -2600, 4200, 6000],
                "proposed_mirror_voltages_v": [0, -5910, -2590, 4201, 6002],
                "secant_diagnostics": {"independent_voltage_chord_count": 2},
                "inputs": {"family_sha256": file_sha256(family)},
            }))
            result = build_fixed_grid_point_receipt(
                correction_path=correction, family_path=family,
                contract_path=contract, output_path=output,
            )
            self.assertEqual(result["mirror_E_step_from_source_v"], 2.0)
            self.assertEqual(result["discrepancy_model_independent_voltage_chord_count"], 2)
            self.assertIn("multisecant", result["purpose"])
            self.assertIn("not_accepted", result["qualification"])



if __name__ == "__main__":
    unittest.main()
