from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_simion_analysis import analyze
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import (
    accelerator_geometry_contract,
    derive_focus_calibration_proposal,
    derive_voltage_trial,
    derive_zero_extraction_energy_focus_seed,
    materialize as materialize_voltage_trial,
    require_reviewed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_accelerator_focus_source import (
    materialize as materialize_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    derive_stage_2_ring_layout,
    derive_stage_2_ring_voltages,
    derive_two_zone_focus,
    derive_two_zone_placement,
    load_contract,
)

PROJECT = Path(__file__).parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AcceleratorFocusSimionAnalysisTest(unittest.TestCase):
    def test_voltage_trial_derives_endpoints_without_changing_geometry(self) -> None:
        baseline = load_contract(CONTRACT)
        trial, receipt = derive_voltage_trial(baseline, baseline, 958.0)
        self.assertEqual(trial["accelerator"]["repeller_v"], 4479.0)
        self.assertEqual(trial["accelerator"]["intermediate_grid_v"], 3521.0)
        self.assertEqual(trial["accelerator"]["exit_grid_v"], 0.0)
        self.assertEqual(
            accelerator_geometry_contract(trial["accelerator"]),
            accelerator_geometry_contract(baseline["accelerator"]),
        )
        for actual, expected in zip(
            receipt["ring_voltages_v"],
            [2934.1666666666665, 2347.3333333333335, 1760.5, 1173.6666666666667, 586.8333333333335],
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(derive_two_zone_placement(trial).focus_z_mm, 0.0)

    def test_voltage_trial_accepts_selected_exact_k_net_gain(self) -> None:
        baseline = load_contract(CONTRACT)
        selected = 4165.847974123505
        drop = 999.8035284876823
        trial, receipt = derive_voltage_trial(
            baseline, baseline, drop, selected_net_gain_center_v=selected,
        )
        self.assertAlmostEqual(trial["nominal"]["energy_per_charge_v"], selected)
        self.assertAlmostEqual(
            trial["accelerator_energy_contract"]["net_gain_reference_center_per_charge_v"],
            selected,
        )
        self.assertAlmostEqual(receipt["energy_per_charge_v"], selected)
        self.assertEqual(receipt["energy_selection"], "explicit_selected_net_gain_center")
        self.assertAlmostEqual(derive_two_zone_focus(trial).energy_per_charge_v, selected)
        self.assertEqual(
            accelerator_geometry_contract(trial["accelerator"]),
            accelerator_geometry_contract(baseline["accelerator"]),
        )

    def test_voltage_trial_materializes_selected_slow_energy_partition(self) -> None:
        baseline = load_contract(CONTRACT)
        axial = 4372.010347796059
        slow = 4.961131691875478

        trial, receipt = derive_voltage_trial(
            baseline, baseline, 958.0,
            selected_net_gain_center_v=axial,
            selected_slow_energy_per_charge_v=slow,
        )

        partition = trial["prism_transport"]["energy_partition"]
        self.assertEqual(partition["fast_reflection_kinetic_energy_ev"], axial)
        self.assertEqual(partition["drift_kinetic_energy_ev"], slow)
        self.assertEqual(partition["total_kinetic_energy_ev"], axial + slow)
        self.assertEqual(receipt["selected_slow_energy_per_charge_v"], slow)

    def test_finite_3d_gain_correction_preserves_target_but_offsets_voltage_command(self) -> None:
        baseline = load_contract(CONTRACT)
        selected = 4198.824969860909
        correction = 0.7536110122964601
        drop = 1009.9868476198334
        uncorrected, _ = derive_voltage_trial(
            baseline, baseline, drop, selected_net_gain_center_v=selected,
        )
        corrected, receipt = derive_voltage_trial(
            baseline, baseline, drop, selected_net_gain_center_v=selected,
            finite_3d_gain_correction_v=correction,
        )
        self.assertEqual(
            corrected["candidate_derivation"]["target_axial_energy_per_charge_v"],
            selected,
        )
        self.assertAlmostEqual(
            corrected["nominal"]["energy_per_charge_v"], selected + correction,
        )
        self.assertAlmostEqual(
            corrected["accelerator"]["repeller_v"]
            - uncorrected["accelerator"]["repeller_v"], correction,
        )
        self.assertAlmostEqual(
            corrected["accelerator"]["intermediate_grid_v"]
            - uncorrected["accelerator"]["intermediate_grid_v"], correction,
        )
        self.assertEqual(receipt["target_axial_energy_per_charge_v"], selected)
        self.assertEqual(receipt["finite_3d_gain_correction_v"], correction)

    def test_finite_3d_gain_correction_must_be_finite_and_keep_positive_command(self) -> None:
        baseline = load_contract(CONTRACT)
        with self.assertRaisesRegex(ValueError, "gain correction must be finite"):
            derive_voltage_trial(
                baseline, baseline, 958.0,
                finite_3d_gain_correction_v=float("nan"),
            )
        with self.assertRaisesRegex(ValueError, "commanded accelerator gain"):
            derive_voltage_trial(
                baseline, baseline, 958.0,
                finite_3d_gain_correction_v=-5000.0,
            )

    def test_fixed_geometry_trial_reports_signed_upstream_ideal_reference(self) -> None:
        baseline = load_contract(CONTRACT)
        source = json.loads(json.dumps(baseline["particle_source"]))
        trial, receipt = derive_voltage_trial(baseline, baseline, 964.0)
        self.assertLess(receipt["analytic_focus_after_exit_mm"], 0.0)
        self.assertFalse(receipt["analytic_focus_is_downstream"])
        self.assertEqual(
            receipt["analytic_focus_reference"],
            "signed_ideal_uniform_field_extrapolation_only",
        )
        self.assertEqual(trial["particle_source"], source)
        with self.assertRaisesRegex(ValueError, "upstream"):
            derive_two_zone_placement(trial)
        self.assertEqual(
            receipt["ring_voltages_v"],
            list(derive_stage_2_ring_voltages(
                trial, placement_contract=baseline,
            )),
        )
        self.assertEqual(
            derive_stage_2_ring_layout(
                trial, placement_contract=baseline,
            ).centers_mm,
            derive_stage_2_ring_layout(baseline).centers_mm,
        )
        with self.assertRaisesRegex(ValueError, "upstream"):
            derive_stage_2_ring_voltages(trial)

    def test_fixed_geometry_trial_still_rejects_an_invalid_field_state(self) -> None:
        baseline = load_contract(CONTRACT)
        with self.assertRaises(ValueError):
            derive_voltage_trial(baseline, baseline, 9000.0)

    def test_focus_calibration_proposal_uses_selected_energy_and_reviewed_geometry(self) -> None:
        baseline = load_contract(CONTRACT)
        selected = 4198.879726494095
        old_drop = 1007.731134358583
        previous_trial, _ = derive_voltage_trial(
            baseline, baseline, old_drop,
            selected_net_gain_center_v=selected,
        )
        previous_analysis = {
            "status": "complete",
            "expected_particle_count": 100,
            "focus_particle_count": 100,
            "target_plane_project_z_mm": 0.0,
            "timing": {"first_order_focus_plane_residual_z_mm": -0.283533331604},
        }
        source = json.loads(json.dumps(baseline["particle_source"]))
        proposal, receipt = derive_focus_calibration_proposal(
            baseline,
            baseline,
            previous_trial,
            previous_analysis,
            selected_net_gain_center_v=selected,
        )
        self.assertEqual(receipt["qualification"], "3d_focus_calibration_proposal_only")
        self.assertEqual(receipt["old_first_gap_drop_v"], old_drop)
        self.assertAlmostEqual(receipt["new_first_gap_drop_v"], 1010.0, places=3)
        self.assertEqual(receipt["first_gap_drop_v"], receipt["new_first_gap_drop_v"])
        self.assertEqual(
            receipt["endpoint_voltages_v"],
            [
                proposal["accelerator"]["repeller_v"],
                proposal["accelerator"]["intermediate_grid_v"],
                proposal["accelerator"]["exit_grid_v"],
            ],
        )
        self.assertEqual(
            receipt["ring_voltages_v"],
            list(derive_stage_2_ring_voltages(proposal, placement_contract=baseline)),
        )
        self.assertNotIn("proposed_trial", receipt)
        self.assertGreater(receipt["project_focus_z_derivative_mm_per_v"], 0.0)
        self.assertEqual(
            receipt["residual_estimator"],
            "finite_release_interval_quadratic_fit__not_strict_local_derivative",
        )
        self.assertEqual(proposal["particle_source"], source)
        self.assertLess(
            derive_two_zone_focus(
                proposal, require_downstream_focus=False,
            ).focus_after_exit_mm,
            0.0,
        )
        with self.assertRaisesRegex(ValueError, "upstream"):
            derive_two_zone_placement(proposal)

    def test_focus_calibration_proposal_rejects_incomplete_or_invalid_evidence(self) -> None:
        baseline = load_contract(CONTRACT)
        selected = 4198.879726494095
        previous_trial, _ = derive_voltage_trial(
            baseline, baseline, 1007.731134358583,
            selected_net_gain_center_v=selected,
        )
        valid = {
            "status": "complete",
            "expected_particle_count": 100,
            "focus_particle_count": 100,
            "target_plane_project_z_mm": 0.0,
            "timing": {"first_order_focus_plane_residual_z_mm": -0.283533331604},
        }
        invalid_cases = (
            ({**valid, "status": "incomplete"}, "complete for every expected particle"),
            ({**valid, "focus_particle_count": 99}, "complete for every expected particle"),
            ({**valid, "timing": {}}, "finite number"),
            ({**valid, "target_plane_project_z_mm": 1.0}, "reviewed geometry"),
        )
        for analysis, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    derive_focus_calibration_proposal(
                        baseline,
                        baseline,
                        previous_trial,
                        analysis,
                        selected_net_gain_center_v=selected,
                    )

    def test_focus_calibration_proposal_rejects_previous_trial_energy_mismatch(self) -> None:
        baseline = load_contract(CONTRACT)
        previous_trial, _ = derive_voltage_trial(
            baseline, baseline, 960.0, selected_net_gain_center_v=4000.0,
        )
        analysis = {
            "status": "complete",
            "expected_particle_count": 100,
            "focus_particle_count": 100,
            "target_plane_project_z_mm": 0.0,
            "timing": {"first_order_focus_plane_residual_z_mm": -0.28},
        }
        with self.assertRaisesRegex(ValueError, "selected run centre"):
            derive_focus_calibration_proposal(
                baseline,
                baseline,
                previous_trial,
                analysis,
                selected_net_gain_center_v=4198.879726494095,
            )

    def test_focus_calibration_proposal_rejects_zero_or_nonfinite_derivative(self) -> None:
        baseline = load_contract(CONTRACT)
        selected = 4198.879726494095
        previous_trial, _ = derive_voltage_trial(
            baseline, baseline, 1007.731134358583,
            selected_net_gain_center_v=selected,
        )
        analysis = {
            "status": "complete",
            "expected_particle_count": 100,
            "focus_particle_count": 100,
            "target_plane_project_z_mm": 0.0,
            "timing": {"first_order_focus_plane_residual_z_mm": -0.28},
        }
        for derivative in (0.0, math.inf):
            with self.subTest(derivative=derivative), patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
                "accelerator_focus_voltage_trial.fixed_energy_gap1_focus_sensitivity",
                return_value=SimpleNamespace(
                    focus_drift_derivative_mm_per_v=derivative,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "finite and nonzero"):
                    derive_focus_calibration_proposal(
                        baseline,
                        baseline,
                        previous_trial,
                        analysis,
                        selected_net_gain_center_v=selected,
                    )

    def test_zero_extraction_energy_seed_reproduces_reviewed_reference(self) -> None:
        baseline = load_contract(CONTRACT)
        trial, receipt = derive_zero_extraction_energy_focus_seed(
            baseline, baseline, 4000.0,
        )
        self.assertEqual(trial["accelerator"]["repeller_v"], 4480.0)
        self.assertEqual(trial["accelerator"]["intermediate_grid_v"], 3520.0)
        self.assertEqual(receipt["first_gap_drop_v"], 960.0)
        self.assertEqual(receipt["qualification"], "ideal_uniform_field_seed_only")
        self.assertEqual(receipt["three_dimensional_field_match"], "not_evaluated")
        self.assertAlmostEqual(
            receipt["forward_focus_after_exit_mm"],
            receipt["reviewed_focus_after_exit_mm"],
            places=12,
        )

    def test_zero_extraction_energy_seed_scales_selected_gain_about_exit(self) -> None:
        baseline = load_contract(CONTRACT)
        selected = 4198.879726494095
        trial, receipt = derive_zero_extraction_energy_focus_seed(
            baseline, baseline, selected,
        )
        scale = selected / 4000.0
        self.assertAlmostEqual(receipt["selected_to_reviewed_energy_scale"], scale)
        self.assertAlmostEqual(receipt["first_gap_drop_v"], 960.0 * scale)
        self.assertAlmostEqual(trial["accelerator"]["repeller_v"], 4480.0 * scale)
        self.assertAlmostEqual(
            trial["accelerator"]["intermediate_grid_v"], 3520.0 * scale,
        )
        self.assertEqual(trial["accelerator"]["exit_grid_v"], 0.0)
        self.assertAlmostEqual(
            derive_two_zone_focus(trial).focus_after_exit_mm,
            derive_two_zone_focus(baseline).focus_after_exit_mm,
            places=12,
        )

    def test_zero_extraction_energy_seed_does_not_require_source_metadata_in_review(self) -> None:
        baseline = load_contract(CONTRACT)
        reviewed = json.loads(json.dumps(baseline))
        reviewed.pop("particle_source")
        reviewed.pop("prism_transport")
        trial, receipt = derive_zero_extraction_energy_focus_seed(
            baseline, reviewed, 4000.0,
        )
        self.assertEqual(trial["accelerator"]["repeller_v"], 4480.0)
        self.assertEqual(receipt["reviewed_first_gap_drop_v"], 960.0)

    def test_reviewed_geometry_accepts_return_policy_and_prose_metadata_changes(self) -> None:
        baseline = load_contract(CONTRACT)
        reviewed = json.loads(json.dumps(baseline))
        reviewed["accelerator"].pop("detector_return_path")
        reviewed["accelerator"]["coaxial_return_path"] = {
            "status": "historical_policy_only",
            "semantics": "not a current trajectory authority",
        }
        reviewed["accelerator"]["shape_semantics"] = "historical prose"
        require_reviewed_geometry(baseline, reviewed)

    def test_reviewed_geometry_rejects_physical_accelerator_changes(self) -> None:
        baseline = load_contract(CONTRACT)
        changes = (
            (("accelerator", "gap_1_mm"), 6.1),
            (("accelerator", "aperture_width_x_mm"), 26.0),
            (("accelerator", "stage_2_rings", "thickness_z_mm"), 1.1),
        )
        for path, value in changes:
            with self.subTest(path=path):
                reviewed = json.loads(json.dumps(baseline))
                target = reviewed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(ValueError, "accelerator geometry"):
                    require_reviewed_geometry(baseline, reviewed)

    def test_reviewed_geometry_rejects_accelerator_mesh_or_span_changes(self) -> None:
        baseline = load_contract(CONTRACT)
        for field, value in (
            ("component_mesh_mm_per_gu", [0.5, 0.25, 0.1]),
            ("accelerator_pa_span_mm", [66, 64, 64]),
        ):
            with self.subTest(field=field):
                reviewed = json.loads(json.dumps(baseline))
                if field == "component_mesh_mm_per_gu":
                    reviewed["simion"][field]["accelerator"] = value
                else:
                    reviewed["simion"][field] = value
                with self.assertRaisesRegex(ValueError, "PA mesh or span"):
                    require_reviewed_geometry(baseline, reviewed)

    def test_voltage_trial_materializer_inherits_current_detector_return_policy(self) -> None:
        baseline = load_contract(CONTRACT)
        reviewed = json.loads(json.dumps(baseline))
        reviewed["accelerator"].pop("detector_return_path")
        reviewed["accelerator"]["coaxial_return_path"] = {
            "status": "historical_policy_only",
        }
        reviewed["accelerator"]["shape_semantics"] = "historical prose"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current_path = root / "current.json"
            reviewed_path = root / "reviewed.json"
            current_path.write_text(json.dumps(baseline), encoding="utf-8")
            reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
            receipt = materialize_voltage_trial(
                current_path,
                reviewed_path,
                960.0,
                root / "trial.json",
                root / "receipt.json",
            )
        self.assertEqual(receipt["first_gap_drop_v"], 960.0)

    def test_voltage_trial_materializer_rejects_invalid_current_return_policy(self) -> None:
        baseline = load_contract(CONTRACT)
        changed = json.loads(json.dumps(baseline))
        changed["accelerator"]["detector_return_path"][
            "accelerator_reentry_after_safe_exit"
        ] = "allowed"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current_path = root / "current.json"
            reviewed_path = root / "reviewed.json"
            current_path.write_text(json.dumps(changed), encoding="utf-8")
            reviewed_path.write_text(json.dumps(baseline), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbid accelerator re-entry"):
                materialize_voltage_trial(
                    current_path,
                    reviewed_path,
                    960.0,
                    root / "trial.json",
                    root / "receipt.json",
                )

    def test_zero_extraction_energy_seed_rejects_wrong_release_state(self) -> None:
        baseline = load_contract(CONTRACT)
        for field, value, message in (
            ("direction_project", [0, 0, 1], "negative project z"),
            ("initial_kinetic_energy_ev", 1.0, "zero extraction energy"),
        ):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(baseline))
                changed["particle_source"]["accelerator_focus_diagnostic"][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    derive_zero_extraction_energy_focus_seed(changed, changed, 4000.0)

    def test_zero_extraction_energy_seed_rejects_illegal_reviewed_voltage_state(self) -> None:
        baseline = load_contract(CONTRACT)
        changed = json.loads(json.dumps(baseline))
        changed["accelerator"]["repeller_v"] += 1.0
        with self.assertRaisesRegex(ValueError, "declared net-gain reference centre"):
            derive_zero_extraction_energy_focus_seed(changed, changed, 4000.0)

    def test_source_materializer_reuses_reviewed_geometry_but_generates_axial_family(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "focus.fly2"
            receipt_path = root / "source.json"
            receipt = materialize_source(
                CONTRACT, CONTRACT, "accelerator_focus_bunch_fly2", output, receipt_path,
            )
            text = output.read_text(encoding="utf-8")
        self.assertEqual(receipt["particle_count"], 100)
        self.assertEqual(receipt["release_interval_in_gap_1_mm"], [2.9, 3.1])
        self.assertEqual(text.count("standard_beam {"), 100)
        self.assertNotIn("circle_distribution", text)

    def test_source_materializer_inherits_current_policy_for_old_reviewed_contract(self) -> None:
        reviewed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        reviewed["accelerator"].pop("detector_return_path")
        reviewed["accelerator"]["coaxial_return_path"] = {
            "status": "required_for_static_nonretracing_detection",
            "semantics": "historical trajectory policy; not a current authority",
        }
        reviewed["accelerator"]["shape_semantics"] = "historical geometry prose"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reviewed_path = root / "old_reviewed.json"
            reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
            receipt = materialize_source(
                CONTRACT,
                reviewed_path,
                "accelerator_focus_center_fly2",
                root / "focus.fly2",
                root / "source.json",
            )
        self.assertEqual(receipt["particle_count"], 1)

    def test_source_materializer_rejects_geometry_drift(self) -> None:
        reviewed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        reviewed["accelerator"]["gap_1_mm"] += 0.1
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reviewed_path = root / "reviewed.json"
            reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewed PA/IOB"):
                materialize_source(
                    CONTRACT, reviewed_path, "accelerator_focus_center_fly2",
                    root / "focus.fly2", root / "source.json",
                )

    def test_source_materializer_accepts_voltage_trial_but_keeps_reviewed_positions(self) -> None:
        baseline = load_contract(CONTRACT)
        trial, _ = derive_voltage_trial(baseline, baseline, 958.0)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trial_path = root / "trial.json"
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            baseline_output = root / "baseline.fly2"
            trial_output = root / "trial.fly2"
            materialize_source(
                CONTRACT, CONTRACT, "accelerator_focus_bunch_fly2",
                baseline_output, root / "baseline_source.json",
            )
            materialize_source(
                trial_path, CONTRACT, "accelerator_focus_bunch_fly2",
                trial_output, root / "trial_source.json",
            )
            self.assertEqual(baseline_output.read_text(), trial_output.read_text())

    def test_source_materializer_reuses_legacy_reviewed_species_energy(self) -> None:
        reviewed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        reviewed["particle_source"]["species"]["kinetic_energy_ev"] = 4000
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reviewed_path = root / "reviewed.json"
            reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
            receipt = materialize_source(
                CONTRACT,
                reviewed_path,
                "accelerator_focus_center_fly2",
                root / "focus.fly2",
                root / "source.json",
            )
            self.assertEqual(receipt["particle_count"], 1)

    def test_complete_axial_family_matches_analytic_reference(self) -> None:
        contract = load_contract(CONTRACT)
        placement = derive_two_zone_placement(contract)
        focus = derive_two_zone_focus(contract)
        accelerator = contract["accelerator"]
        mass = contract["particle_source"]["species"]["mass_th"]
        releases = [2.9, 3.0, 3.1]
        lines = ["MRTOF_ACCELERATOR_FOCUS: status=prototype target_plane_z_mm=0"]
        for ion, release in enumerate(releases, start=1):
            z = placement.repeller_z_mm - release
            time_us = 1.0e6 * time_to_fixed_plane_s(
                accelerator["repeller_v"], accelerator["intermediate_grid_v"],
                accelerator["gap_1_mm"], accelerator["gap_2_mm"], release, 0.0,
                focus.focus_after_exit_mm, mass, exit_v=accelerator["exit_grid_v"],
            )
            lines.extend([
                f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion={ion} t_us=0 x_mm=0 y_mm={placement.focus_y_mm} z_mm={z}",
                f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion={ion} t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1",
                f"MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion={ion} code=1 reached_focus=1 t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0",
            ])
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = analyze(log, CONTRACT, 3)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["focus_particle_count"], 3)
        self.assertLess(result["timing"]["analytic_max_abs_time_error_ns"], 1.0e-8)
        # The exact first derivative is zero at the centre.  A finite symmetric
        # secant over +/-0.1 mm retains a small higher-order odd contribution.
        self.assertLess(abs(result["timing"]["linear_slope_ps_per_mm"]), 10.0)
        self.assertGreater(result["timing"]["quadratic_coefficient_ps_per_mm2"], 0.0)

    def test_trial_analysis_uses_reviewed_physical_plane(self) -> None:
        baseline = load_contract(CONTRACT)
        trial, _ = derive_voltage_trial(baseline, baseline, 964.0)
        placement = derive_two_zone_placement(baseline)
        accelerator = trial["accelerator"]
        mass = trial["particle_source"]["species"]["mass_th"]
        release = accelerator["release_position_in_gap_1_mm"]
        physical_post_exit = placement.exit_grid_z_mm - placement.focus_z_mm
        time_us = 1.0e6 * time_to_fixed_plane_s(
            accelerator["repeller_v"], accelerator["intermediate_grid_v"],
            accelerator["gap_1_mm"], accelerator["gap_2_mm"], release, 0.0,
            physical_post_exit, mass, exit_v=accelerator["exit_grid_v"],
        )
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 y_mm={placement.focus_y_mm} z_mm={placement.repeller_z_mm-release}\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=1 t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=1 reached_focus=1 t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "focus.log"
            trial_path = root / "trial.json"
            log.write_text(text, encoding="utf-8")
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            result = analyze(log, trial_path, 1, CONTRACT)
        self.assertLess(result["timing"]["analytic_max_abs_time_error_ns"], 1.0e-8)
        self.assertGreater(result["analytic_trial_focus_plane_residual_z_mm"], 0.0)
        state = result["single_center_focus_state"]
        self.assertEqual(state["event"], "negative_going_project_z_focus_plane_crossing")
        self.assertEqual(state["position_project_mm"], [0.0, placement.focus_y_mm, 0.0])
        self.assertEqual(state["velocity_project_mm_per_us"], [0.0, 0.0, -1.0])
        self.assertEqual(state["species"], {"mass_th": 524.0, "charge_e": 1.0})
        self.assertAlmostEqual(state["selected_net_gain_center_per_charge_v"], 4000.0)
        self.assertEqual(state["recorded_kinetic_energy_components_ev"]["y"], 0.0)
        self.assertGreater(state["recorded_kinetic_energy_components_ev"]["z"], 0.0)
        self.assertEqual(len(state["input_identity"]["focus_log_sha256"]), 64)
        self.assertEqual(len(state["input_identity"]["contract_sha256"]), 64)
        self.assertEqual(len(state["input_identity"]["reviewed_geometry_contract_sha256"]), 64)

    def test_analysis_inherits_current_policy_for_old_reviewed_contract(self) -> None:
        contract = load_contract(CONTRACT)
        reviewed = json.loads(json.dumps(contract))
        reviewed["accelerator"].pop("detector_return_path")
        reviewed["accelerator"]["coaxial_return_path"] = {
            "status": "required_for_static_nonretracing_detection",
        }
        reviewed["accelerator"]["shape_semantics"] = "historical geometry prose"
        placement = derive_two_zone_placement(contract)
        focus = derive_two_zone_focus(contract)
        accelerator = contract["accelerator"]
        release = accelerator["release_position_in_gap_1_mm"]
        time_us = 1.0e6 * time_to_fixed_plane_s(
            accelerator["repeller_v"],
            accelerator["intermediate_grid_v"],
            accelerator["gap_1_mm"],
            accelerator["gap_2_mm"],
            release,
            0.0,
            focus.focus_after_exit_mm,
            contract["particle_source"]["species"]["mass_th"],
            exit_v=accelerator["exit_grid_v"],
        )
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 "
            f"y_mm={placement.focus_y_mm} z_mm={placement.repeller_z_mm - release}\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=1 t_us={time_us} x_mm=0 "
            f"y_mm={placement.focus_y_mm} z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=1 reached_focus=1 "
            f"t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "focus.log"
            reviewed_path = root / "old_reviewed.json"
            log_path.write_text(text, encoding="utf-8")
            reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
            result = analyze(log_path, CONTRACT, 1, reviewed_path)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["focus_particle_count"], 1)

    def test_missing_focus_is_reported_without_fabricating_timing(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        placement = derive_two_zone_placement(contract)
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 y_mm=0 z_mm={placement.repeller_z_mm - 3}\n"
            "MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=2 reached_focus=0 t_us=3 x_mm=0 y_mm=0 z_mm=1\n"
        )
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text(text, encoding="utf-8")
            result = analyze(log, CONTRACT, 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["focus_particle_count"], 0)
        self.assertIsNone(result["timing"])
        self.assertIsNone(result["single_center_focus_state"])

    def test_one_particle_does_not_fabricate_derivatives(self) -> None:
        contract = load_contract(CONTRACT)
        placement = derive_two_zone_placement(contract)
        focus = derive_two_zone_focus(contract)
        accelerator = contract["accelerator"]
        mass = contract["particle_source"]["species"]["mass_th"]
        release = accelerator["release_position_in_gap_1_mm"]
        time_us = 1.0e6 * time_to_fixed_plane_s(
            accelerator["repeller_v"], accelerator["intermediate_grid_v"],
            accelerator["gap_1_mm"], accelerator["gap_2_mm"], release, 0.0,
            focus.focus_after_exit_mm, mass, exit_v=accelerator["exit_grid_v"],
        )
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 y_mm=0 z_mm={placement.repeller_z_mm-release}\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=1 t_us={time_us} x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=1 reached_focus=1 t_us={time_us} x_mm=0 y_mm=0 z_mm=0\n"
        )
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text(text, encoding="utf-8")
            result = analyze(log, CONTRACT, 1)
        self.assertIsNone(result["timing"]["linear_slope_ps_per_mm"])
        self.assertIsNone(result["timing"]["quadratic_coefficient_ps_per_mm2"])
        self.assertIsNone(result["timing"]["derived_first_order_focus_project_z_mm"])
        self.assertTrue(math.isfinite(result["single_center_focus_state"]["time_us"]))

    def test_single_center_focus_state_rejects_missing_recorded_velocity(self) -> None:
        contract = load_contract(CONTRACT)
        placement = derive_two_zone_placement(contract)
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 "
            f"y_mm={placement.focus_y_mm} z_mm={placement.repeller_z_mm - 3}\n"
            "MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=1 t_us=1 x_mm=0 y_mm=0 "
            "z_mm=0 vz_mm_us=-1\n"
            "MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=1 reached_focus=1 "
            "t_us=1 x_mm=0 y_mm=0 z_mm=0\n"
        )
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complete recorded position or velocity"):
                analyze(log, CONTRACT, 1)

    def test_single_center_focus_state_rejects_wrong_direction_or_plane(self) -> None:
        contract = load_contract(CONTRACT)
        placement = derive_two_zone_placement(contract)
        for vz, focus_z, message in (
            (0, 0, "negative project z"),
            (1, 0, "negative project z"),
            (-1, 0.01, "negative project z|declared focus plane"),
        ):
            with self.subTest(vz=vz, focus_z=focus_z):
                text = (
                    f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 "
                    f"y_mm={placement.focus_y_mm} z_mm={placement.repeller_z_mm - 3}\n"
                    f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=1 t_us=1 x_mm=0 "
                    f"y_mm={placement.focus_y_mm} z_mm={focus_z} vx_mm_us=0 "
                    f"vy_mm_us=0 vz_mm_us={vz}\n"
                    "MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=1 reached_focus=1 "
                    "t_us=1 x_mm=0 y_mm=0 z_mm=0\n"
                )
                with TemporaryDirectory() as directory:
                    log = Path(directory) / "focus.log"
                    log.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        analyze(log, CONTRACT, 1)


if __name__ == "__main__":
    unittest.main()
