from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import mirror_real_field_l1_refine


class RealFieldL1RefineTests(unittest.TestCase):
    def test_real_field_runners_use_one_capacity_session(self) -> None:
        project = Path(__file__).resolve().parents[2]
        for name in (
            "run_mirror_real_field_l1_refine.ps1",
        ):
            source = (project / "analysis" / name).read_text(encoding="utf-8-sig")
            for token in (
                "-CapacityLedgerLifecycleEnabled",
                "Enter-ArtifactWorkflowCapacitySession",
                "Update-ArtifactWorkflowCapacitySession",
                "Exit-ArtifactWorkflowCapacitySession",
                "-CommittedNewBytes 1000000000",
                "-RemainingCommittedNewBytes 0",
            ):
                self.assertIn(token, source, name)
            for forbidden in (
                "Invoke-ArtifactCapacityGate",
                "RequiredHeadroomBytes",
                "KnownMeasuredBytes",
                "MaximumNewArtifactBytes",
            ):
                self.assertNotIn(forbidden, source, name)

    def test_gamma_discovery_keeps_finite_unstable_endpoint_for_root_bracketing(self) -> None:
        records = iter([
            {
                "trace_half": -1.8,
                "stable": False,
                "gamma_degrees": None,
                "stability_margin": -0.8,
            },
            {
                "trace_half": -1.6,
                "stable": False,
                "gamma_degrees": None,
                "stability_margin": -0.6,
            },
        ])
        with (
            patch.object(mirror_real_field_l1_refine, "CombinedField", return_value=object()),
            patch.object(
                mirror_real_field_l1_refine,
                "l1_probe_at_energy",
                side_effect=lambda *_args, **_kwargs: next(records),
            ),
        ):
            result = mirror_real_field_l1_refine._gamma_sample(
                None,
                [0.0, 1.0, 2.0, 3.0, 4.0],
                nominal_energy_v=4000.0,
                position_probe_mm=0.004,
                angle_probe_rad=4.0e-5,
                probe_scale_factor=1.0,
                trace_controls={},
            )

        self.assertAlmostEqual(result["objective_mean_trace_half"], -1.7)
        self.assertEqual(result["directional_stable"], [False, False])
        self.assertEqual(result["directional_gamma_degrees"], [None, None])
        self.assertEqual(result["probe_scale_factor"], 1.0)

    def test_only_probe_convergence_failures_may_advance_to_fixed_grid(self) -> None:
        reports = {
            "members": [
                {
                    "status": "screen_fail_diagnostic_only",
                    "hard_gate_failures": [
                        "gamma_probe_not_converged:direction=-1:energy=4000",
                        "tbar_probe_not_converged:direction=1:energy=4000",
                    ],
                    "selection_metrics": {
                        "maximum_absolute_Tbar_xx_us_per_mm2": 0.02,
                        "minimum_transverse_stability_margin": 0.9,
                        "sampled_peak_field_v_per_mm": 1000.0,
                        "maximum_absolute_mirror_voltage_v": 6000.0,
                    },
                },
                {
                    "status": "screen_fail_diagnostic_only",
                    "hard_gate_failures": ["l0_period_slope_failed"],
                    "selection_metrics": {
                        "maximum_absolute_Tbar_xx_us_per_mm2": 0.01,
                        "minimum_transverse_stability_margin": 0.95,
                        "sampled_peak_field_v_per_mm": 900.0,
                        "maximum_absolute_mirror_voltage_v": 5900.0,
                    },
                },
            ]
        }

        result = mirror_real_field_l1_refine.rank_fixed_grid_validation_candidates(
            reports,
            metric_tolerances=(0.0, 0.0, 0.0, 0.0),
        )

        self.assertEqual(result["eligible_root_indices"], [0])
        self.assertEqual(result["selected_root_indices"], [0])
        self.assertEqual(result["primary_root_index"], 0)
        self.assertIn("0", result["deferred_hard_gate_failures_by_root"])

    def test_physical_gate_failure_cannot_be_deferred_to_fixed_grid(self) -> None:
        reports = {"members": [{
            "status": "screen_fail_diagnostic_only",
            "hard_gate_failures": ["gamma_target_failed:direction=1:energy=4000"],
            "selection_metrics": {
                "maximum_absolute_Tbar_xx_us_per_mm2": 0.01,
                "minimum_transverse_stability_margin": 0.9,
                "sampled_peak_field_v_per_mm": 1000.0,
                "maximum_absolute_mirror_voltage_v": 6000.0,
            },
        }]}

        result = mirror_real_field_l1_refine.rank_fixed_grid_validation_candidates(
            reports,
            metric_tolerances=(0.0, 0.0, 0.0, 0.0),
        )

        self.assertEqual(result["selected_root_indices"], [])

    def test_first_false_position_trial_may_legitimately_be_near_endpoint(self) -> None:
        left = {
            "source_index": 1,
            "mirror_voltages_v": [0.0, 1.0, 2.0, 3.0, 0.0],
            "gamma_objective": -0.01,
        }
        right = {
            "source_index": 2,
            "mirror_voltages_v": [0.0, 2.0, 3.0, 4.0, 10.0],
            "gamma_objective": 1.0,
        }
        evaluated_e = []

        def fake_l0(*_args, e_voltage_v: float, **_kwargs):
            evaluated_e.append(e_voltage_v)
            return {
                "mirror_voltages_v": [0.0, 1.0, 2.0, 3.0, e_voltage_v],
                "normalized_period_slopes_per_v": [0.0, 0.0, 0.0],
                "reduced_periods_mm_per_sqrt_v": [1.0, 1.0, 1.0],
                "turning_points_mm": [[-1.0, 1.0]] * 3,
                "l0_feasible": True,
            }

        def fake_gamma(*_args, **_kwargs):
            return {
                "objective_mean_trace_half": 0.0,
                "directional_trace_half": [0.0, 0.0],
                "directional_gamma_degrees": [90.0, 90.0],
                "directional_stability_margin": [1.0, 1.0],
            }

        with TemporaryDirectory() as directory:
            payload = (
                (left, right), None, None, (3900.0, 4000.0, 4100.0), 1.0,
                {
                    name: (-10_000.0, 10_000.0)
                    for name in ("mirror_B", "mirror_C", "mirror_D")
                },
                1.0e-7, 1.0e-4, 1.0e-12, 20, 0.004, 4.0e-5, 4.0, {}, 1.0e-6, 0.001, 10,
                Path(directory) / "root.json", {"contract_sha256": "test"},
            )
            with (
                patch.object(mirror_real_field_l1_refine, "_fixed_e_l0_solution", fake_l0),
                patch.object(mirror_real_field_l1_refine, "_gamma_sample", fake_gamma),
            ):
                mirror_real_field_l1_refine._root_job(payload)

        self.assertAlmostEqual(evaluated_e[0], 0.09900990099009901)

    def test_root_job_preserves_original_bracket_lineage(self) -> None:
        left = {
            "source_index": 11,
            "mirror_voltages_v": [0.0, 1.0, 2.0, 3.0, 0.0],
            "gamma_objective": -1.0,
        }
        right = {
            "source_index": 12,
            "mirror_voltages_v": [0.0, 2.0, 3.0, 4.0, 10.0],
            "gamma_objective": 1.0,
        }

        def fake_l0(*_args, e_voltage_v: float, **_kwargs):
            return {
                "mirror_voltages_v": [0.0, 1.5, 2.5, 3.5, e_voltage_v],
                "normalized_period_slopes_per_v": [0.0, 0.0, 0.0],
                "reduced_periods_mm_per_sqrt_v": [1.0, 1.0, 1.0],
                "turning_points_mm": [[-1.0, 1.0]] * 3,
                "l0_feasible": True,
            }

        def fake_gamma(_basis, voltages, **_kwargs):
            objective = float(voltages[-1]) - 5.0
            return {
                "objective_mean_trace_half": objective,
                "directional_trace_half": [objective, objective],
                "directional_gamma_degrees": [90.0, 90.0],
                "directional_stability_margin": [1.0, 1.0],
            }

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "root_11_12.checkpoint.json"
            payload = (
                (left, right), None, None, (3900.0, 4000.0, 4100.0), 1.0,
                {
                    name: (-10_000.0, 10_000.0)
                    for name in ("mirror_B", "mirror_C", "mirror_D")
                },
                1.0e-7, 1.0e-4, 1.0e-12, 20, 0.004, 4.0e-5, 4.0, {}, 1.0e-6, 0.001, 10,
                checkpoint, {"contract_sha256": "test"},
            )
            with (
                patch.object(mirror_real_field_l1_refine, "_fixed_e_l0_solution", fake_l0),
                patch.object(mirror_real_field_l1_refine, "_gamma_sample", fake_gamma),
            ):
                result = mirror_real_field_l1_refine._root_job(payload)
            self.assertTrue(checkpoint.is_file())

        self.assertEqual(result["source_bracket_member_indices"], [11, 12])
        self.assertTrue(result["l0_feasible"])
        self.assertEqual(result["mirror_voltages_v"][-1], 5.0)

    def test_unexpected_optimizer_error_is_not_hidden_as_infeasibility(self) -> None:
        with patch.object(
            mirror_real_field_l1_refine,
            "normalized_slopes",
            side_effect=RuntimeError("unexpected defect"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unexpected defect"):
                mirror_real_field_l1_refine._fixed_e_l0_solution(
                    None,
                    e_voltage_v=6000.0,
                    start_bcd_v=(1000.0, 2000.0, 3000.0),
                    energies_v=(3900.0, 4000.0, 4100.0),
                    derivative_step_v=1.0,
                    bounds={
                        "mirror_B": (-10_000.0, 3900.0),
                        "mirror_C": (-5000.0, 3900.0),
                        "mirror_D": (-5000.0, 3900.0),
                    },
                    slope_gate_per_v=5.0e-8,
                    jacobian_relative_step=1.0e-4,
                    least_squares_relative_tolerance=1.0e-12,
                    maximum_function_evaluations=20,
                )


if __name__ == "__main__":
    unittest.main()
