from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_affine_axial_width_sweep import (
    compute_width_sweep_report,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.affine_axial_ideal_report import (
    resolve_bound_input_path,
    select_bound_source_profile,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    PhysicsContractError,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixtures" / "affine_axial_ideal_report"
CAMPAIGN = (
    ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "config"
    / "diagnostics"
    / "canonical_affine_axial_all_ideal_width_sweep_campaign.json"
)


def _write_fixture_sweep(root: Path) -> Path:
    fixture = root / "fixture"
    shutil.copytree(FIXTURE, fixture)
    geometry_path = fixture / "geometry.json"
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    reflectron = geometry["geometry_derivation"]["accelerator"]["finite_interval_theory"][
        "coupled_reflectron"
    ]
    reflectron.update(
        {
            "nominal_energy_per_charge_v": 2000.0,
            "upstream_from_accelerator_focus_mm": 600.0,
            "downstream_to_detector_mm": 600.0,
        }
    )
    geometry["geometry_mm"] = {"L_stage1": 120.0, "L_stage2": 100.0}
    geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
    base_campaign_path = fixture / "campaign.json"
    base_campaign = json.loads(base_campaign_path.read_text(encoding="utf-8"))
    base_campaign["source_profile_registry_path"] = "fixture/registry.json"
    base_campaign["cases"][0]["resolved_geometry"]["path"] = "fixture/geometry.json"
    base_campaign["cases"][0]["resolved_geometry"]["sha256"] = file_sha256(geometry_path)
    base_campaign["cases"][0]["source_materialization_receipt"]["path"] = (
        "fixture/source_receipt.json"
    )
    base_campaign["cases"][0]["source_release_csv"]["path"] = (
        "fixture/source_release.csv"
    )
    base_campaign_path.write_text(
        json.dumps(base_campaign, indent=2) + "\n", encoding="utf-8"
    )
    sweep = {
        "schema_version": 1,
        "role": "rf_oatof_affine_axial_all_ideal_width_sweep_campaign",
        "campaign_id": "fixture_affine_axial_width_sweep",
        "evidence_level": "EXPLORATORY_PROVISIONAL",
        "threshold_status": "declared_after_initial_observation_not_preregistered",
        "analysis_class": "solver_independent_analytic",
        "solver_execution_allowed": False,
        "base_analytic_campaign": {
            "path": "fixture/campaign.json",
            "sha256": file_sha256(base_campaign_path),
        },
        "base_case_id": "fixture",
        "fixed_architecture_id": "ARCH-SHORT-Z10-R100",
        "source_family_profile_id": "fixture_affine_n3",
        "full_widths_mm": [0.25, 0.5, 1.0],
        "sample_count": 101,
        "model_full_width_mm": 1.0,
        "cross_validation": {
            "method": "five_fold_particle_id_modulo",
            "particle_id_modulus": 5,
            "validation_offsets": [0, 1, 2, 3, 4],
            "selection_uses_detector_outcome": False,
        },
        "local_taylor_closure": {
            "coefficient_source": "linear_phase_space_timing_coefficients",
            "require_resolved_accelerator_coefficient_match": False,
            "maximum_accelerator_first_coefficient_difference_mm_per_v_pow_3_over_2": 1e-12,
            "maximum_accelerator_second_coefficient_difference_mm_per_v_pow_5_over_2": 1e-12,
            "maximum_abs_coupled_first_residual_mm_per_v_pow_3_over_2": 1e-10,
            "maximum_abs_coupled_second_residual_mm_per_v_pow_5_over_2": 1e-10,
            "detector_central_difference_step_mm": 0.002,
            "maximum_abs_detector_first_derivative_ns_per_mm": 0.1,
            "maximum_abs_detector_second_derivative_ns_per_mm2": 0.1,
        },
        "exploratory_target_checkpoint": "detector",
        "exploratory_declared_thresholds": {
            "minimum_full_model_validation_r_squared": 0.0,
            "maximum_full_model_validation_rmse_fraction_of_sigma": 10.0,
            "minimum_sigma_log_width_exponent": 0.0,
            "maximum_sigma_log_width_exponent": 10.0,
            "minimum_sigma_log_width_fit_r_squared": 0.0,
            "maximum_energy_envelope_outside_count": 0,
        },
        "exploratory_interpretation_policy": {
            "allowed_if_all_thresholds_pass": "affine_all_ideal_axial_n1001_higher_order_pattern_only",
            "not_preregistered": True,
            "local_taylor_global_reconstruction_and_width_scaling_are_separate": True,
            "legendre_variance_is_not_taylor_derivative_order_attribution": True,
            "specific_third_order_dominance_claim_allowed": False,
            "real_field_transverse_release_or_numerical_exclusion_claim_allowed": False,
            "simion_candidate_or_formal_claim_allowed": False,
        },
    }
    path = root / "sweep.json"
    path.write_text(json.dumps(sweep, indent=2) + "\n", encoding="utf-8")
    return path


class AffineAxialWidthSweepTests(unittest.TestCase):
    def test_fixture_sweep_has_five_folds_records_models_and_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = compute_width_sweep_report(
                _write_fixture_sweep(root), workspace_root=root
            )
        self.assertEqual(report["full_widths_mm"], [0.25, 0.5, 1.0])
        self.assertEqual(report["sample_count_per_width"], 101)
        self.assertEqual(report["source_family"]["profile_id"], "fixture_affine_n3")
        self.assertEqual(
            report["deterministic_quadrature_cohort"]["particle_count"], 101
        )
        self.assertIn("not_analysis_particle_cohort", report["source_family"]["identity_semantics"])
        self.assertEqual(
            [
                fold["validation_offset"]
                for fold in report["checkpoint_models"]["detector"][
                    "five_fold_particle_id_modulo"
                ]
            ],
            [0, 1, 2, 3, 4],
        )
        widest = report["width_results"][-1]
        self.assertEqual(len(widest["particle_timing_records"]), 101)
        first = widest["particle_timing_records"][0]
        last = widest["particle_timing_records"][-1]
        self.assertEqual(first["normalized_coordinate"], -1.0)
        self.assertEqual(last["normalized_coordinate"], 1.0)
        self.assertLess(first["accelerator_focus_tof_us"], first["reflectron_entrance_tof_us"])
        self.assertLess(first["reflectron_entrance_tof_us"], first["detector_tof_us"])
        for checkpoint in ("accelerator_focus", "reflectron_entrance", "detector"):
            for fold in report["checkpoint_models"][checkpoint][
                "five_fold_particle_id_modulo"
            ]:
                self.assertEqual(
                    [model["degree"] for model in fold["nested_polynomial_models"]],
                    [1, 2, 3, 4, 5, 6],
                )
            self.assertIn(
                "central_80_percent_width_ns", widest["checkpoint_summaries"][checkpoint]
            )
        self.assertEqual(
            report["exploratory_assessment"]["specific_dominant_order_claim"],
            "withheld_no_unique_order_identification",
        )
        self.assertEqual(report["status"], "EXPLORATORY_PROVISIONAL")
        self.assertTrue(
            report["local_taylor_closure"][
                "local_taylor_degree_3_or_higher_start_supported"
            ]
        )
        self.assertEqual(
            report["rederived_widest_source_coupled_reflectron"][
                "energy_extrema"
            ]["method"],
            "exact_quadratic_endpoints_plus_interval_stationary_point",
        )
        self.assertIsNone(
            report["third_and_higher_derivative_authority"][
                "existing_coupled_total_third_derivative"
            ]
        )
        self.assertFalse(
            report["third_and_higher_derivative_authority"][
                "current_report_uses_total_third_derivative_as_authority"
            ]
        )

    def test_even_sample_count_fails_before_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_path = _write_fixture_sweep(root)
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
            campaign["sample_count"] = 100
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with self.assertRaisesRegex(PhysicsContractError, "odd integer"):
                compute_width_sweep_report(campaign_path, workspace_root=root)

    def test_detector_time_path_closure_threshold_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_path = _write_fixture_sweep(root)
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
            campaign["local_taylor_closure"][
                "maximum_abs_detector_first_derivative_ns_per_mm"
            ] = 0.0
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with self.assertRaisesRegex(PhysicsContractError, "Taylor"):
                compute_width_sweep_report(campaign_path, workspace_root=root)

    def test_campaign_unknown_field_fails_schema_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_path = _write_fixture_sweep(root)
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
            campaign["unexpected_field"] = True
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "unexpected_field"):
                compute_width_sweep_report(campaign_path, workspace_root=root)

    def test_affine_report_exports_bound_input_and_profile_selection(self) -> None:
        campaign = json.loads((FIXTURE / "campaign.json").read_text(encoding="utf-8"))
        case = campaign["cases"][0]
        self.assertEqual(
            resolve_bound_input_path(FIXTURE, case["resolved_geometry"], "geometry"),
            (FIXTURE / "geometry.json").resolve(),
        )
        registry = json.loads((FIXTURE / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(
            select_bound_source_profile(registry, case)["profile_id"],
            "fixture_affine_n3",
        )

    def test_registered_campaign_freezes_long_architecture_and_exploratory_policy(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        self.assertEqual(campaign["fixed_architecture_id"], "ARCH-LONG-Z22-R100")
        self.assertEqual(
            campaign["full_widths_mm"], [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.8, 2.2]
        )
        self.assertEqual(campaign["sample_count"], 1001)
        self.assertFalse(campaign["solver_execution_allowed"])
        self.assertEqual(
            campaign["threshold_status"],
            "declared_after_initial_observation_not_preregistered",
        )
        self.assertFalse(
            campaign["exploratory_interpretation_policy"][
                "specific_third_order_dominance_claim_allowed"
            ]
        )
        self.assertEqual(
            campaign["exploratory_declared_thresholds"][
                "maximum_energy_envelope_outside_count"
            ],
            0,
        )
        self.assertEqual(
            campaign["cross_validation"]["validation_offsets"], [0, 1, 2, 3, 4]
        )
        self.assertTrue(
            campaign["local_taylor_closure"][
                "require_resolved_accelerator_coefficient_match"
            ]
        )


if __name__ == "__main__":
    unittest.main()
