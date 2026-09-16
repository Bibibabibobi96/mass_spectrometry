"""Unit contracts for system-level exact-K mirror energy selection."""

from __future__ import annotations

import copy
import math
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import dual_stripe_operating_seed
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    materialize_native_stripe_spatial_return_root,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point import (
    exact_k_contract_projection,
    EXACT_K_SELECTOR_STATUS,
    ManagedExactKOperatingPoint,
    _td_over_t0,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    reduced_period,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_shape_adapter import (
    NATIVE_SHAPE_BRANCH_STATUS,
    NATIVE_SHAPE_REFERENCE_AUTHORITY,
    build_native_stripe_shape_selection,
    load_native_stripe_shape_selection,
    native_stripe_geometry_projection_sha256,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


CONTRACT = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"


class MirrorExactKOperatingPointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.shape = build_native_stripe_shape_selection(cls.contract)

    def test_current_contract_uses_the_stripe_on_adiabatic_selector_status(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            contract["mirror"]["theory_requirements"]
            ["exact_k_operating_point_selection"]["status"],
            EXACT_K_SELECTOR_STATUS,
        )

    def test_exact_k_projection_excludes_downstream_prism_shooting_semantics(self) -> None:
        downstream = copy.deepcopy(self.contract)
        injection = downstream["prism_transport"]["two_prism_injection_l0"]
        injection["voltage_polarity_contract"] = {
            "positive_ion_prism_1_sign": "positive",
            "positive_ion_prism_2_sign": "negative",
        }
        injection["low_field_angle_and_positive_mirror_turn_authority"][
            "direction_condition"
        ] = {"reference_vz_sign": "positive", "reference_vy_sign": "positive"}
        voltage_initialization = downstream["dual_stripe_l0"][
            "current_fixed_hardware_l0_l1_problem"
        ]["voltage_initialization"]
        voltage_initialization["semantics"] = "corrected downstream topology wording"
        voltage_initialization["derivation_chain"] = ["P2 reference", "turn", "Stripe"]
        downstream["particle_source"]["full_mrtof_center"]["required_inputs"] = [
            "corrected downstream event sequence"
        ]

        self.assertEqual(
            exact_k_contract_projection(self.contract),
            exact_k_contract_projection(downstream),
        )

    def test_exact_k_projection_keeps_upstream_energy_and_stripe_authority(self) -> None:
        changed_energy = copy.deepcopy(self.contract)
        changed_energy["prism_transport"]["energy_partition"][
            "drift_kinetic_energy_ev"
        ] += 0.1
        self.assertNotEqual(
            exact_k_contract_projection(self.contract),
            exact_k_contract_projection(changed_energy),
        )

        changed_stripe = copy.deepcopy(self.contract)
        changed_stripe["dual_stripe_l0"][
            "manufactured_design_abs_drift_length_L_mm"
        ] += 1.0
        self.assertNotEqual(
            exact_k_contract_projection(self.contract),
            exact_k_contract_projection(changed_stripe),
        )

    def test_exact_k_projection_rejects_missing_prism_authority(self) -> None:
        malformed = copy.deepcopy(self.contract)
        del malformed["prism_transport"]["two_prism_injection_l0"][
            "low_field_angle_and_positive_mirror_turn_authority"
        ]
        with self.assertRaises(CandidateContractError):
            exact_k_contract_projection(malformed)

    def test_td_over_t0_uses_exact_orthogonal_energy_partition_with_axial_width(self) -> None:
        kappa = 1.4892272347854711
        ratio = _td_over_t0(4000.0, 586.9393396818346, kappa, 340.0, 5.0)
        theta = math.atan(math.sqrt(5.0 / 4000.0))
        self.assertAlmostEqual(theta, math.asin(math.sqrt(5.0 / 4005.0)))
        self.assertAlmostEqual(
            ratio,
            kappa * 340.0 / (586.9393396818346 * math.tan(theta)),
        )
        self.assertAlmostEqual(ratio, 24.400103096528568)

    def test_td_over_t0_does_not_mix_total_energy_with_an_axial_width(self) -> None:
        kappa = 1.4892272347854711
        ratio = _td_over_t0(4000.0, 586.9393396818346, kappa, 340.0, 5.0)
        mixed_convention = kappa * 340.0 / (
            586.9393396818346 * math.sqrt(5.0 / 4005.0)
        )
        self.assertGreater(mixed_convention, ratio)

    def test_td_over_t0_rejects_no_hidden_mass_dependence(self) -> None:
        first = _td_over_t0(4200.0, 586.9, 1.489, 340.0, 5.0)
        second = _td_over_t0(4200.0, 586.9, 1.489, 340.0, 5.0)
        self.assertTrue(math.isfinite(first))
        self.assertEqual(first, second)

    def test_native_shape_authority_comes_from_manufactured_geometry(self) -> None:
        root = self.shape.shape_root
        scales = self.shape.basis_path_scales
        self.assertEqual(
            root.reference_relative_action_weight_ratio,
            scales.high_order_response_scale_mm / scales.linear_response_scale_mm,
        )
        self.assertGreater(root.kappa_1, 0.0)
        self.assertLessEqual(
            abs(root.kappa_prime),
            self.shape.maximum_abs_kappa_prime_numerical_residual,
        )
        receipt = self.shape.receipt()
        self.assertEqual(
            receipt["geometry_projection_identity"]["sha256"],
            native_stripe_geometry_projection_sha256(self.contract),
        )
        self.assertEqual(receipt["status"], NATIVE_SHAPE_BRANCH_STATUS)
        self.assertEqual(
            receipt["branch_locator"]["authority"],
            NATIVE_SHAPE_REFERENCE_AUTHORITY,
        )
        self.assertIn("paper branch locates", receipt["branch_locator"]["semantics"])

    def test_native_shape_receipt_round_trips_without_resolving_a_second_root(self) -> None:
        serialized = json.loads(json.dumps(self.shape.receipt()))
        loaded = load_native_stripe_shape_selection(serialized, self.contract)
        self.assertEqual(loaded.shape_root, self.shape.shape_root)
        managed = ManagedExactKOperatingPoint(
            design=None,  # type: ignore[arg-type]
            axial_energy_per_charge_v=4000.0,
            axial_width_w_mm=1.0,
            native_stripe_spatial_shape_root=loaded.shape_root,
            stripe_biases_v=(0.0, 0.0),
            contract=self.contract,
            run_id="test",
            manifest_sha256="A",
            parent_mirror_manifest_sha256="B",
        )
        self.assertEqual(managed.kappa_1, loaded.shape_root.kappa_1)

    def test_native_shape_loader_rejects_old_or_changed_authority(self) -> None:
        old = copy.deepcopy(self.shape.receipt())
        old["schema_version"] = 0
        with self.assertRaises(CandidateContractError):
            load_native_stripe_shape_selection(old, self.contract)

        changed = copy.deepcopy(self.shape.receipt())
        changed["spatial_shape_root"]["kappa_1"] *= 1.01
        changed["kappa_prime_numerical_gate"]["actual_abs_residual"] = abs(
            changed["spatial_shape_root"]["kappa_prime"]
        )
        with self.assertRaises(CandidateContractError):
            load_native_stripe_shape_selection(changed, self.contract)

    def test_native_shape_contract_rejects_missing_or_invalid_controls(self) -> None:
        missing = copy.deepcopy(self.contract)
        del missing["dual_stripe_l0"]["native_spatial_shape_branch"][
            "root_absolute_tolerance"
        ]
        with self.assertRaises(CandidateContractError):
            build_native_stripe_shape_selection(missing)

        invalid = copy.deepcopy(self.contract)
        invalid["dual_stripe_l0"]["native_spatial_shape_branch"][
            "maximum_root_iterations"
        ] = True
        with self.assertRaises(CandidateContractError):
            build_native_stripe_shape_selection(invalid)

    def test_exact_k_downstream_seed_materializes_native_shape_without_paper_inverse(self) -> None:
        energy = 4050.0
        design = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 167.0, 229.0, 261.0, 291.0),
            electrode_voltages_v=(0.0, -2000.0, 3500.0, 5500.0, 8000.0),
            terminal_electrode_plane_z_mm=320.0,
            terminal_electrode_voltage_v=8000.0,
        )
        period = reduced_period(energy, design)
        managed = ManagedExactKOperatingPoint(
            design=design,
            axial_energy_per_charge_v=energy,
            axial_width_w_mm=period * math.sqrt(energy),
            native_stripe_spatial_shape_root=self.shape.shape_root,
            stripe_biases_v=(-25.0, 50.0),
            contract=self.contract,
            run_id="native-source-test",
            manifest_sha256="A" * 64,
            parent_mirror_manifest_sha256="B" * 64,
        )
        expected = materialize_native_stripe_spatial_return_root(
            self.shape.shape_root,
            source_slow_energy_per_charge_v=5.0,
            mirror_reduced_period_mm_per_sqrt_v=period,
            axial_energy_per_charge_v=energy,
        )
        consistency = {"status": "patched_same_point_evaluator"}
        forbidden = AssertionError("paper inverse must not be called")
        with (
            patch.object(
                dual_stripe_operating_seed,
                "load_managed_exact_k_operating_point",
                return_value=managed,
            ),
            patch.object(
                dual_stripe_operating_seed,
                "_evaluate_exact_k_seed_consistency",
                return_value=consistency,
            ),
            patch.object(
                dual_stripe_operating_seed,
                "solve_dimensionless_paper_target",
                side_effect=forbidden,
            ),
            patch.object(
                dual_stripe_operating_seed,
                "derive_manufactured_basis_voltage_seed",
                side_effect=forbidden,
            ),
        ):
            report = dual_stripe_operating_seed.build_operating_seed_report_from_exact_k(
                Path("unused-exact-k-manifest.json"),
                CONTRACT,
            )
        self.assertEqual(report["schema_version"], 5)
        self.assertEqual(
            report["selected_seed"]["stripe_biases_v"],
            list(expected.stripe_biases_v),
        )
        self.assertEqual(
            report["selected_seed"]["native_spatial_return_materialization"]
            ["source_slow_energy_per_charge_v"],
            5.0,
        )
        self.assertEqual(
            report["selected_exact_k_operating_point"]["kappa_1"],
            self.shape.shape_root.kappa_1,
        )
        self.assertIs(
            report["same_point_native_fixed_hardware_consistency"],
            consistency,
        )
        self.assertEqual(
            report["complete_fixed_hardware_consistency_search"]["status"],
            "not_solved__overdefined_diagnostic_system",
        )


if __name__ == "__main__":
    unittest.main()
