from __future__ import annotations

import math
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
    AxisFieldResponseBasis,
    AxisResponseBasis,
    analyze_preserved_basis,
    load_numerical_profile,
    normalized_slopes,
    reduced_period_from_basis,
    solve_l0_family,
)


class MirrorRealFieldVoltageFamilyTest(unittest.TestCase):
    def test_runner_qualifies_reusable_basis_and_allows_native_check_to_follow(self) -> None:
        project = Path(__file__).resolve().parents[2]
        source = (project / "simion" / "run_mirror_real_field_voltage_family.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("[string]$BaselinePeriodRunPath=''", source)
        self.assertIn("[string]$ResponseBasisRunPath=''", source)
        self.assertIn("-RetentionClass qualification", source)
        self.assertIn("Real-3-D mirror response basis or derived voltage-family", source)
        self.assertNotIn("-PreservePaths @($basisPath)", source)
        self.assertIn("if($baselinePeriod){$analyzeArguments+=", source)
        self.assertIn("','reuse',", source)
        self.assertIn("'--basis-run',$basisRun", source)
        self.assertIn("'--contract',$frozenContract", source)
        self.assertIn("axis_basis_schema_version", source)
        self.assertIn("axis_period_authority", source)

    def test_loads_numerics_from_baseline_contract(self) -> None:
        project = Path(__file__).resolve().parents[2]

        profile = load_numerical_profile(
            project / "config" / "simion_candidate_two_zone.json"
        )

        self.assertEqual(profile["response_grid_spacing_mm"], 0.5)
        self.assertEqual(profile["axis_probe_y_mm"], 280.0)
        self.assertEqual(profile["e_voltage_slice_count"], 65)
        self.assertEqual(profile["voltage_jacobian_scheme"], "three_point_central")
        self.assertEqual(profile["voltage_jacobian_relative_step"], 1e-4)
        self.assertEqual(profile["least_squares_relative_tolerance"], 1e-12)
        self.assertEqual(
            profile["continuation_predictor"],
            "implicit_tangent_from_three_slope_jacobian",
        )
        self.assertEqual(profile["maximum_function_evaluations_per_e_slice"], 120)

    def test_harmonic_response_has_energy_independent_period(self) -> None:
        z = np.linspace(-10.0, 10.0, 401)
        responses = np.zeros((len(z), 4))
        responses[:, 0] = 10000.0 * z * z
        basis = AxisResponseBasis(z, responses, 10000.0)

        period, turns = reduced_period_from_basis(basis, 25.0, (1.0, 0.0, 0.0, 0.0))

        self.assertAlmostEqual(period, math.pi, places=5)
        self.assertAlmostEqual(turns[0], -5.0, places=9)
        self.assertAlmostEqual(turns[1], 5.0, places=9)
        slopes = normalized_slopes(basis, (1.0, 0.0, 0.0, 0.0), (20.0, 25.0, 30.0), 0.1)
        self.assertLess(max(abs(value) for value in slopes), 1e-8)

    def test_linearly_interpolated_axis_field_integrates_to_piecewise_quadratic_potential(self) -> None:
        z = np.linspace(-10.0, 10.0, 41)
        ez_responses = np.zeros((len(z), 4))
        ez_responses[:, 0] = -20000.0 * z
        basis = AxisFieldResponseBasis(z, ez_responses, 10000.0)

        potential = basis.potential((1.0, 0.0, 0.0, 0.0))

        np.testing.assert_allclose(potential(z), z * z, rtol=0.0, atol=1.0e-12)
        np.testing.assert_allclose(potential.derivative()(z), 2.0 * z, rtol=0.0, atol=1.0e-12)
        period, turns = reduced_period_from_basis(
            basis, 25.0, (1.0, 0.0, 0.0, 0.0),
        )
        self.assertAlmostEqual(period, math.pi, places=5)
        self.assertEqual(turns, (-5.0, 5.0))

    def test_rejects_voltage_vector_with_wrong_dimension(self) -> None:
        z = np.linspace(-10.0, 10.0, 41)
        basis = AxisResponseBasis(z, np.zeros((len(z), 4)), 10000.0)
        with self.assertRaises(Exception):
            basis.potential((1.0, 2.0, 3.0))

    def test_family_report_is_strict_json(self) -> None:
        z = np.linspace(-10.0, 10.0, 401)
        responses = np.zeros((len(z), 4))
        responses[:, 0] = 10000.0 * z * z
        basis = AxisResponseBasis(z, responses, 10000.0)
        bounds = {
            "mirror_B": (0.5, 2.0),
            "mirror_C": (-1.0, 1.0),
            "mirror_D": (-1.0, 1.0),
            "mirror_E": (-1.0, 1.0),
        }

        result = solve_l0_family(
            basis, (20.0, 25.0, 30.0), 0.1, (1.0, 0.0, 0.0, 0.0), bounds, 1e-7,
            {
                "e_voltage_slice_count": 3,
                "voltage_jacobian_scheme": "three_point_central",
                "voltage_jacobian_relative_step": 1e-4,
                "least_squares_relative_tolerance": 1e-12,
                "continuation_predictor": "implicit_tangent_from_three_slope_jacobian",
                "maximum_function_evaluations_per_e_slice": 120,
            },
        )

        json.dumps(result, allow_nan=False)
        self.assertEqual(result["numerics"]["voltage_jacobian_scheme"], "three_point_central")
        self.assertEqual(result["numerics"]["voltage_jacobian_relative_step"], 1e-4)
        self.assertEqual(result["axis_period_authority"], "cubic_spline_sampled_potential_nodes")
        self.assertEqual(result["actual_e_slice_count"], 3)
        self.assertEqual(len(result["e_voltage_slices_v"]), result["member_count"])
        self.assertEqual(
            {member["predictor_status"] for member in result["members"]},
            {
                "not_applicable_seed_slice",
                "rank_deficient_fallback_to_previous_solution",
            },
        )

    def test_reuses_only_manifest_bound_half_mm_basis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            basis_run = root / "basis"
            exact_run = root / "exact"
            results = basis_run / "results"
            results.mkdir(parents=True)
            exact_run.mkdir()
            basis = results / "real_3d_mirror_axis_response_basis.csv"
            rows = [
                "z_mm,mirror_B_potential_v,mirror_B_ez_v_per_mm,"
                "mirror_C_potential_v,mirror_C_ez_v_per_mm,"
                "mirror_D_potential_v,mirror_D_ez_v_per_mm,"
                "mirror_E_potential_v,mirror_E_ez_v_per_mm"
            ]
            for z in np.linspace(-10.0, 10.0, 41):
                rows.append(
                    f"{z:.17g},{10000.0*z*z:.17g},{-20000.0*z:.17g},0,0,0,0,0,0"
                )
            basis.write_text("\n".join(rows) + "\n", encoding="utf-8")
            receipt = results / "mirror_response_sampling_receipt.json"
            receipt.write_text(json.dumps({
                "role": "mrtof_real_3d_mirror_axis_response_sampling_plan",
                "status": "sampled",
                "sample_step_mm": 0.5,
                "probe_y_mm": 280.0,
                "basis_normalization_v": 10000.0,
                "axis_basis_schema_version": 2,
                "axis_period_authority": "integrated_piecewise_linear_sampled_Ez",
                "sampled_axis_quantities": ["potential_v", "ez_v_per_mm"],
                "source_contract_sha256": "TEST",
                "cache_generations": [],
            }), encoding="utf-8")
            basis_manifest = {
                "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "real_3d_mirror_l0_voltage_family",
                "status": "success",
                "run_id": "basis-test",
                "outputs": [
                    {"path": str(path.resolve()), "sha256": file_sha256(path)}
                    for path in (basis, receipt)
                ],
            }
            (basis_run / "run_manifest.json").write_text(
                json.dumps(basis_manifest), encoding="utf-8"
            )
            point = {"mirror_voltages_v": [0.0, 1.0, 0.0, 0.0, 31.0]}
            summary = exact_run / "summary.json"
            summary.write_text(json.dumps({
                "selected_root_index": 0,
                "selected_operating_point": point,
                "roots": [{
                    "point": point,
                    "refined_mirror_receipt": {"l0_receipt": {
                        "electrode_voltages_v": point["mirror_voltages_v"],
                        "three_point": {"energies_v": [20.0, 25.0, 30.0]},
                        "period_slope_derivative_step_v": 0.1,
                        "maximum_abs_normalized_period_slope_per_v": 1e-7,
                    }},
                }],
            }), encoding="utf-8")
            (exact_run / "run_manifest.json").write_text(json.dumps({
                "project": "parallel_mirror_dual_stripe_mr_tof",
                "status": "success",
                "run_id": "exact-test",
                "outputs": [{"path": str(summary.resolve())}],
            }), encoding="utf-8")
            contract = root / "contract.json"
            contract.write_text(json.dumps({
                "mirror": {"theory_requirements": {
                    "real_3d_l0_voltage_family_profile": {
                        "response_grid_spacing_mm": 0.5,
                        "axis_probe_y_mm": 280.0,
                        "e_voltage_slice_count": 3,
                        "voltage_jacobian_scheme": "three_point_central",
                        "voltage_jacobian_relative_step": 1e-4,
                        "least_squares_relative_tolerance": 1e-12,
                        "continuation_predictor": "implicit_tangent_from_three_slope_jacobian",
                        "maximum_function_evaluations_per_e_slice": 20,
                    }
                }}
            }), encoding="utf-8")

            report = analyze_preserved_basis(
                basis_run, exact_run, contract, root / "family.json"
            )

        self.assertEqual(report["source_response_basis_run_id"], "basis-test")
        self.assertEqual(report["source_exact_k_run_id"], "exact-test")
        self.assertEqual(report["feasible_member_count"], 0)
        self.assertTrue(all(
            max(abs(value) for value in member["normalized_period_slopes_per_v"])
            <= report["maximum_abs_normalized_period_slope_per_v"]
            for member in report["members"]
        ))
        self.assertEqual(report["numerics"]["requested_e_slice_count"], 3)
        self.assertEqual(report["actual_e_slice_count"], 4)
        self.assertEqual(report["axis_basis_schema_version"], 2)
        self.assertEqual(
            report["axis_period_authority"], "integrated_piecewise_linear_sampled_Ez",
        )
        self.assertEqual(
            {member["predictor_status"] for member in report["members"]},
            {
                "not_applicable_seed_slice",
                "rank_deficient_fallback_to_previous_solution",
            },
        )

    def test_reuse_rejects_legacy_potential_only_axis_basis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            basis_run = root / "basis"
            results = basis_run / "results"
            results.mkdir(parents=True)
            basis = results / "real_3d_mirror_axis_response_basis.csv"
            basis.write_text("z_mm,mirror_B,mirror_C,mirror_D,mirror_E\n0,0,0,0,0\n", encoding="utf-8")
            receipt = results / "mirror_response_sampling_receipt.json"
            receipt.write_text(json.dumps({
                "role": "mrtof_real_3d_mirror_axis_response_sampling_plan",
                "status": "sampled", "sample_step_mm": 0.5,
            }), encoding="utf-8")
            (basis_run / "run_manifest.json").write_text(json.dumps({
                "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "real_3d_mirror_l0_voltage_family", "status": "success",
                "run_id": "legacy", "outputs": [
                    {"path": str(path.resolve()), "sha256": file_sha256(path)}
                    for path in (basis, receipt)
                ],
            }), encoding="utf-8")
            contract = root / "contract.json"
            contract.write_text(json.dumps({"mirror": {"theory_requirements": {
                "real_3d_l0_voltage_family_profile": {
                    "response_grid_spacing_mm": 0.5, "axis_probe_y_mm": 280.0,
                    "e_voltage_slice_count": 3, "voltage_jacobian_scheme": "three_point_central",
                    "voltage_jacobian_relative_step": 1e-4,
                    "least_squares_relative_tolerance": 1e-12,
                    "continuation_predictor": "implicit_tangent_from_three_slope_jacobian",
                    "maximum_function_evaluations_per_e_slice": 20,
                }
            }}}), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "field-consistent schema"):
                analyze_preserved_basis(basis_run, root / "missing", contract, root / "out.json")


if __name__ == "__main__":
    unittest.main()
