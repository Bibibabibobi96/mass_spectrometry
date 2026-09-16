from __future__ import annotations

from types import SimpleNamespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    TransportNumerics,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage import (
    deterministic_sobol_voltage_pairs,
    run_coverage,
    validate_accelerator_exit_source_binding,
)
from common.contracts.file_identity import file_sha256


class TwoPrismSegmentedCoverageTests(unittest.TestCase):
    def test_unscrambled_sobol_is_deterministic_and_domain_bound(self) -> None:
        first = deterministic_sobol_voltage_pairs(
            p1_bounds_v=(120.0, 280.0), p2_bounds_v=(-150.0, 400.0), sample_count=8,
        )
        second = deterministic_sobol_voltage_pairs(
            p1_bounds_v=(120.0, 280.0), p2_bounds_v=(-150.0, 400.0), sample_count=8,
        )
        self.assertEqual(first, second)
        self.assertEqual(first[0], (120.0, -150.0))
        self.assertTrue(all(120.0 <= p1 < 280.0 and -150.0 <= p2 < 400.0 for p1, p2 in first))

    def test_non_power_of_two_and_invalid_domain_fail_closed(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "power of two"):
            deterministic_sobol_voltage_pairs(
                p1_bounds_v=(0.0, 1.0), p2_bounds_v=(0.0, 1.0), sample_count=3,
            )
        with self.assertRaisesRegex(CandidateContractError, "positive width"):
            deterministic_sobol_voltage_pairs(
                p1_bounds_v=(1.0, 1.0), p2_bounds_v=(0.0, 1.0), sample_count=2,
            )

    @staticmethod
    def _context() -> dict:
        return {
            "contract": {}, "source": object(), "mass": 524.0, "charge": 1,
            "mirror_design": object(), "axial_energy": 4198.0, "slow_energy": 5.0,
            "target_tangent_ratio": 0.05,
            "stripe_biases": (-25.0, 50.0), "prism_ids": (16, 17),
            "numerics": TransportNumerics(1e-7, 1e-9, 0.1, 6, 1e-9, 1e-7, 1e-8, 1e-8, 30000),
            "stage_a": 10.0, "stage_b": 40.0, "residual_scales": (340.0, 0.05),
        }

    def test_branch_counts_ranges_and_independent_zero_enclosure(self) -> None:
        def evaluate(_contract, **kwargs):
            p1 = kwargs["prism_bias_v_by_electrode_id"][16]
            p2 = kwargs["prism_bias_v_by_electrode_id"][17]
            if p1 == 3.0:
                raise CandidateContractError("deliberate topology rejection")
            return SimpleNamespace(voltage_residuals=(
                ("P1_P2_positive_mirror_turn_y_mm", p1 - 1.5),
                ("P1_P2_P2_shield_low_field_signed_vy_over_vz", p2 - 1.5),
            ))

        with (
            patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage.evaluate_two_prism_segmented_voltage_pair", side_effect=evaluate),
            patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage.two_prism_topology_signature", return_value=("branch",)),
            patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage.two_prism_legacy_topology_signature", return_value=("legacy-branch",)),
            patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage.selected_positive_mirror_turn_identity", return_value=("turn-branch",)),
        ):
            result = run_coverage(
                context=self._context(),
                sobol_pairs=((1.0, 1.0), (2.0, 2.0), (3.0, 2.0)),
                local_pairs=((1.0, 2.0),), worker_count=1,
            )
        self.assertEqual(result["sobol"]["legal_topology_count"], 2)
        self.assertEqual(result["sobol"]["invalid_topology_count"], 1)
        self.assertEqual(result["combined"]["sample_count"], 4)
        branch = result["combined"]["branches"][0]
        self.assertTrue(branch["both_residual_ranges_enclose_zero"])
        self.assertEqual(
            branch["residual_ranges"]["P1_P2_positive_mirror_turn_y_mm"],
            [-0.5, 0.5],
        )
        self.assertEqual(
            result["sobol"]["failure_counts_by_message"],
            {"deliberate topology rejection": 1},
        )

    def test_unexpected_evaluator_failure_is_not_classified_as_topology(self) -> None:
        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage.evaluate_two_prism_segmented_voltage_pair",
            side_effect=RuntimeError("programming fault"),
        ):
            with self.assertRaisesRegex(RuntimeError, "programming fault"):
                run_coverage(
                    context=self._context(), sobol_pairs=((1.0, 1.0),),
                    local_pairs=(), worker_count=1,
                )

    def test_exit_source_receipt_is_bound_to_observation_and_exact_k_energy(self) -> None:
        value = {
            "schema_version": 1,
            "role": "mrtof_accelerator_exit_center_source",
            "status": "materialized",
            "qualification": "source_to_accelerator_exit_diagnostic_input_only",
            "particle_mass_th": 524.0,
            "charge_state": 1,
            "selected_axial_energy_per_charge_v": 4198.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accelerator_exit_source_receipt.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            handoff = {
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "position_mm": [0.0, 0.0, -5.0],
                "kinetic_energy_components_ev": {"z": 4197.5},
                "input": {"accelerator_exit_observation": {
                    "source_receipt_sha256": file_sha256(path).lower(),
                }},
            }
            with patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
                "two_prism_segmented_coverage.axial_potential_v",
                return_value=0.25,
            ):
                result = validate_accelerator_exit_source_binding(
                    source_receipt_path=path, source_handoff_receipt=handoff,
                    managed=SimpleNamespace(axial_energy_per_charge_v=4198.0, design=object()),
                )
            self.assertEqual(result["selected_axial_energy_per_charge_v"], 4198.0)
            self.assertEqual(result["measured_axial_hamiltonian_per_charge_v"], 4197.75)
            self.assertEqual(result["measured_minus_selected_axial_energy_v"], -0.25)
            with self.assertRaisesRegex(CandidateContractError, "differs from exact-K"):
                validate_accelerator_exit_source_binding(
                    source_receipt_path=path, source_handoff_receipt=handoff,
                    managed=SimpleNamespace(axial_energy_per_charge_v=4198.1, design=object()),
                )
            handoff["input"]["accelerator_exit_observation"]["source_receipt_sha256"] = "0" * 64
            with self.assertRaisesRegex(CandidateContractError, "does not identify"):
                validate_accelerator_exit_source_binding(
                    source_receipt_path=path, source_handoff_receipt=handoff,
                    managed=SimpleNamespace(axial_energy_per_charge_v=4198.0, design=object()),
                )


if __name__ == "__main__":
    unittest.main()
