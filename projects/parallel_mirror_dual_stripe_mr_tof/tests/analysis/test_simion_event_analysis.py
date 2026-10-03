"""Cohort-integrity regression tests; no commercial solver or historical run writes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import _particle_source_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    SOURCE_COUNT_KEYS, _mirrored_branch_turn_diagnostics, analyze_log,
    collision_diagnostics, load_particle_source, parse_events, summarize_events, peak_time_metrics,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROGRAM = REPOSITORY_ROOT / "projects" / "parallel_mirror_dual_stripe_mr_tof" / "simion" / "mrtof_candidate.lua"
PEAK_CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "config/simion_candidate_two_zone.json").read_text())["peak_analysis"]


def terminal(ion: int, **changes: object) -> dict[str, object]:
    return {"kind": "terminal", "ion": ion, "splat": -1, "turns": 2,
            "t_us": 100 + ion * .01, **changes}


def detector(ion: int) -> dict[str, object]:
    return {"kind": "detector", "ion": ion, "t_us": 100 + ion * .01,
            "x_mm": 0, "y_mm": 0, "z_mm": 96, "direction_z": -1}


def static_return_chain(ion: int) -> list[dict[str, object]]:
    common = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0}
    outward = {**common, "vy_mm_us": 1, "vz_mm_us": -1}
    returned = {**common, "vy_mm_us": -1, "vz_mm_us": -1}
    return_p2 = {**returned, "vz_mm_us": 1}
    outbound_turns = [
        {"kind": "fast_turn", "ion": ion, "n": index,
         "t_us": 3.1 + 0.1 * index, "x_mm": 0.001 * index,
         "y_mm": 10.0 * (index + 1),
         "z_mm": -280.0 if index % 2 == 0 else 280.0,
         "vx_mm_us": 0.01, "vy_mm_us": 1.0, "vz_mm_us": 0.0}
        for index in range(25)
    ]
    return_turns = [
        {"kind": "fast_turn", "ion": ion, "n": 25 + index,
         "t_us": 5.7 + 0.1 * index,
         "x_mm": float(outbound_turns[24 - index]["x_mm"]),
         "y_mm": float(outbound_turns[24 - index]["y_mm"]),
         "z_mm": -float(outbound_turns[24 - index]["z_mm"]),
         "vx_mm_us": -0.01, "vy_mm_us": -1.0, "vz_mm_us": 0.0}
        for index in range(25)
    ]
    return [
        {"kind": "prism_pass", "ion": ion, "n": 1, "t_us": 1,
         **{**outward, "vz_mm_us": -1}},
        {"kind": "prism_pass", "ion": ion, "n": 2, "t_us": 2,
         **{**outward, "vz_mm_us": 1}},
        {"kind": "drift_phase_origin", "ion": ion, "t_us": 3,
         **{**outward, "z_mm": 280, "vz_mm_us": 0}},
        *outbound_turns,
        *return_turns,
        {"kind": "drift_phase_return", "ion": ion, "k": 25.5,
         "half_cycles": 51, "slow_coordinate_residual_mm": 0,
         "t_us": 9.5, **{**returned, "z_mm": -280, "vz_mm_us": 0}},
        {"kind": "target_k_phase_sample", "ion": ion, "k": 25.5,
         "half_cycles": 51, "t_us": 9.5,
         **{**returned, "z_mm": -280, "vz_mm_us": 0}},
        {"kind": "target_k", "ion": ion, "k": 25.5, "half_cycles": 51,
         "t_us": 9.5, "x_mm": 0, "y_mm": 0, "z_mm": -280},
        {"kind": "return_p2_entry", "ion": ion, "t_us": 11, **return_p2},
        {"kind": "return_p2_pass", "ion": ion, "t_us": 12, **return_p2},
        {"kind": "return_positive_mirror_turn", "ion": ion, "t_us": 13,
         **{**returned, "z_mm": 280, "vz_mm_us": 0}},
        detector(ion),
    ]


def fixture_manifest(root: Path) -> Path:
    contract = {"particle_source": {"center_particle_count": 1, "candidate_bunch_particle_count": 8},
                "nominal": {"target_drift_period_ratio": 25.5,
                            "fast_path_symmetry": "opposite_mirror_turn__z_reflected_nonoverlapping"}}
    contract_path = root / "simion_prototype_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    manifest = {"schema_version": 2, "derived_contract": {
        "filename": contract_path.name, "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest()}}
    for key, count_key in SOURCE_COUNT_KEYS.items():
        source = root / f"{key}.fly2"
        source.write_text(f"particles {{ standard_beam {{ n = {contract['particle_source'][count_key]} }} }}\n",
                          encoding="utf-8")
        manifest[key] = _particle_source_record(source, contract["particle_source"], count_key)
    path = root / "prototype_input_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def current_fixture_manifest(root: Path) -> Path:
    """Create a schema-3 fixture whose diagnostic and full-center roles differ."""
    particle_source = {
        "species": {"mass_th": 524, "charge_e": 1},
        "center_particle_count": 1,
        "candidate_bunch_particle_count": 8,
        "mirror_internal_diagnostic": {"axial_kinetic_energy_ev": 4000},
        "full_mrtof_center": {"publishable": False},
    }
    contract = {
        "particle_source": particle_source,
        "nominal": {"target_drift_period_ratio": 25.5,
                    "fast_path_symmetry": "opposite_mirror_turn__z_reflected_nonoverlapping"},
        "prism_transport": {"energy_partition": {"fast_reflection_kinetic_energy_ev": 4000}},
    }
    contract_path = root / "simion_prototype_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    manifest = {
        "schema_version": 3,
        "derived_contract": {
            "filename": contract_path.name,
            "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        },
    }
    for source_key, profile_id in (
        ("mirror_internal_diagnostic_center_fly2", "mirror_internal_diagnostic"),
        ("full_mrtof_center_fly2", "full_mrtof_center"),
    ):
        source = root / f"{source_key}.fly2"
        source.write_text("particles { standard_beam { n = 1 } }\n", encoding="utf-8")
        manifest[source_key] = _particle_source_record(
            source, particle_source, "center_particle_count", profile_id,
        )
    path = root / "prototype_input_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class SimionEventAnalysisTest(unittest.TestCase):
    def test_peak_metrics_match_common_units_and_mean_resolution(self):
        from common.analysis.peak_metrics import AnalysisSettings, compute_peak_metrics
        times = [700.0 + index * .001 for index in range(12)]
        actual = peak_time_metrics(times, mass_th=524, analysis_contract=PEAK_CONTRACT, cohort_role="formal_volume")
        expected, _ = compute_peak_metrics(times, 524, AnalysisSettings(**PEAK_CONTRACT["settings"]))
        self.assertEqual(actual["fwhm"] * 1000, expected["direct_fwhm_tof_ns"])
        self.assertEqual(actual["time_equivalent_resolution"], expected["time_equivalent_resolution"])
        self.assertEqual(actual["analysis_contract"], PEAK_CONTRACT)

    def test_peak_metrics_unavailable_for_diagnostics_or_degenerate_samples(self):
        for times, role in (([], "formal_volume"), ([1.0, 2.0], "formal_volume"), ([1.0] * 13, "formal_volume"), ([1.0, 2.0, 3.0], "controlled_diagnostic")):
            with self.subTest(times=times, role=role):
                result = peak_time_metrics(times, mass_th=524, analysis_contract=PEAK_CONTRACT, cohort_role=role)
                self.assertIsNone(result["time_equivalent_resolution"])
                self.assertIsNone(result["fwhm"])

    def test_peak_metrics_reject_missing_settings_and_invalid_times(self):
        contract = copy.deepcopy(PEAK_CONTRACT)
        del contract["settings"]["bandwidth_multiplier"]
        with self.assertRaises(ValueError):
            peak_time_metrics([1., 2., 3.], mass_th=524, analysis_contract=contract, cohort_role="formal_volume")
        with self.assertRaises(ValueError):
            peak_time_metrics([1., 2., float("nan")], mass_th=524, analysis_contract=PEAK_CONTRACT, cohort_role="formal_volume")

    def test_mirrored_nonretracing_turn_pairs_use_z_reflection_not_retrace(self):
        common = {"ion": 1, "vx_mm_us": 0.0, "vz_mm_us": 0.0}
        events = [
            {"kind": "drift_phase_origin", "t_us": 0.0, **common,
             "x_mm": 0.0, "y_mm": 0.0, "z_mm": 280.0, "vy_mm_us": 1.0},
            {"kind": "fast_turn", "n": 0, "t_us": 1.0, "x_mm": 0.1,
             "y_mm": 10.0, "z_mm": -280.0, "vy_mm_us": 1.0, **common},
            {"kind": "fast_turn", "n": 1, "t_us": 2.0, "x_mm": 0.2,
             "y_mm": 20.0, "z_mm": 280.0, "vy_mm_us": 1.0, **common},
            {"kind": "fast_turn", "n": 2, "t_us": 3.0, "x_mm": 0.2,
             "y_mm": 20.0, "z_mm": -280.0, "vy_mm_us": -1.0, **common},
            {"kind": "fast_turn", "n": 3, "t_us": 4.0, "x_mm": 0.1,
             "y_mm": 10.0, "z_mm": 280.0, "vy_mm_us": -1.0, **common},
            {"kind": "drift_phase_return", "k": 2.5, "t_us": 5.0, **common,
             "x_mm": 0.0, "y_mm": 0.0, "z_mm": -280.0, "vy_mm_us": -1.0},
        ]
        result = _mirrored_branch_turn_diagnostics(events, 2.5)[0]
        self.assertEqual(result["status"], "evaluated__tolerance_not_assigned")
        self.assertEqual(result["paired_turn_count"], 2)
        self.assertEqual(result["opposite_mirror_side_pair_count"], 2)
        self.assertTrue(all(value == 0.0 for value in
                            result["maximum_absolute_residuals"].values()))

        events[-1]["k"] = 3
        unavailable = _mirrored_branch_turn_diagnostics(events, 2.5)[0]
        self.assertEqual(
            unavailable["status"],
            "not_evaluated__exact_target_k_phase_return_required",
        )

    def test_single_particle_program_emits_the_required_topology_events(self):
        source = PROGRAM.read_text(encoding="utf-8-sig")
        for token in (
            "MRTOF_EVENT fast_turn", "MRTOF_EVENT slow_turn", "MRTOF_EVENT slow_coordinate_y0",
            "MRTOF_EVENT central_plane_directional", "MRTOF_EVENT p1_plane",
            "MRTOF_EVENT prism_pass", "MRTOF_EVENT pre_injection_mirror_turn",
            "MRTOF_EVENT p2_low_field_crossing",
            "MRTOF_EVENT p2_low_field_reference",
            "MRTOF_EVENT drift_phase_origin", "MRTOF_EVENT drift_phase_return",
            "MRTOF_EVENT drift_phase_candidate", "MRTOF_EVENT drift_coordinate_return",
            "MRTOF_EVENT target_k_phase_sample",
            "MRTOF_EVENT return_p2_entry", "MRTOF_EVENT return_p2_pass",
            "MRTOF_EVENT return_positive_mirror_turn",
            "MRTOF_EVENT detector_plane",
            "MRTOF_EVENT instance_transition",
            "MRTOF_EVENT accelerator_pulse_off",
            "MRTOF_EVENT accelerator_reentry",
            "direction_y=", "direction_z=",
        ):
            self.assertIn(token, source)
        self.assertNotIn("MRTOF_EVENT prism_voltage_switch", source)
        self.assertIn("active MR-TOF Candidate forbids all P1/P2 voltage switching", source)

    def test_p2_low_field_reference_event_preserves_phase_space(self):
        events = parse_events(
            "MRTOF_EVENT p2_low_field_reference ion=1 t_us=4.5 "
            "x_mm=0 y_mm=-0.4 z_mm=33 "
            "vx_mm_us=0 vy_mm_us=1.2 vz_mm_us=34.8\n"
        )
        self.assertEqual(events, [{
            "kind": "p2_low_field_reference",
            "ion": 1,
            "t_us": 4.5,
            "x_mm": 0,
            "y_mm": -0.4,
            "z_mm": 33,
            "vx_mm_us": 0,
            "vy_mm_us": 1.2,
            "vz_mm_us": 34.8,
        }])
        raw = parse_events(
            "MRTOF_EVENT p2_low_field_crossing ion=2 t_us=4.6 "
            "x_mm=0.1 y_mm=-0.3 z_mm=33 "
            "vx_mm_us=0.2 vy_mm_us=1.3 vz_mm_us=-34.7 "
            "inside_aperture=0 direction_ok=0\n"
        )[0]
        self.assertEqual(raw["inside_aperture"], 0)
        self.assertEqual(raw["direction_ok"], 0)
        self.assertEqual(raw["vz_mm_us"], -34.7)

    def test_prism_phase_space_uses_all_surface_arrivals_not_detector_survivors(self):
        def phase_event(
            kind: str, ion: int, time: float, x: float, y: float,
            vx: float, vy: float, vz: float, **extra: object,
        ) -> dict[str, object]:
            return {
                "kind": kind, "ion": ion, "t_us": time,
                "x_mm": x, "y_mm": y, "z_mm": 33.0,
                "vx_mm_us": vx, "vy_mm_us": vy, "vz_mm_us": vz,
                **extra,
            }

        events = [
            terminal(1, splat=1, x_mm=0.0, y_mm=-50.0, z_mm=97.0),
            terminal(2, splat=-1, x_mm=0.2, y_mm=-5.5, z_mm=-97.0),
            terminal(3, splat=2, x_mm=0.3, y_mm=100.0, z_mm=200.0),
            terminal(4, splat=3, x_mm=0.4, y_mm=150.0, z_mm=-250.0),
            phase_event("p2_low_field_crossing", 1, 1.0, -1.0, -2.0,
                        -1.0, 1.0, 10.0, inside_aperture=1, direction_ok=1),
            phase_event("p2_low_field_crossing", 2, 1.1, 0.0, 0.0,
                        0.0, 2.0, 10.0, inside_aperture=0, direction_ok=1),
            phase_event("p2_low_field_crossing", 3, 1.2, 1.0, 2.0,
                        1.0, 3.0, -10.0, inside_aperture=1, direction_ok=0),
            # The legacy event exists only for the accepted centre ray.  Its
            # presence must not hide the two rejected raw crossings above.
            phase_event("p2_low_field_reference", 1, 1.0, -1.0, -2.0,
                        -1.0, 1.0, 10.0),
        ]
        result = summarize_events(
            events, 25.5, 4, expected_particle_ids=(1, 2, 3, 4),
            mass_th=524.0, charge_e=1.0,
            source_transverse_reference={
                "center_particle_id": 1,
                "center_x_mm": 0.0, "center_vx_mm_per_us": 1.0,
                "mean_x_mm": 0.0, "mean_vx_mm_per_us": 1.0,
            },
        )
        diagnostic = result["prism_phase_space_diagnostic"]
        self.assertEqual(
            diagnostic["scope"],
            "all_source_particles_at_each_logged_surface__not_detector_survivors",
        )
        surface = diagnostic["surfaces"]["p2_fixed_observation_plane"]
        self.assertEqual(
            surface["observation_semantics"],
            "raw_plane_crossing_with_aperture_and_direction_flags",
        )
        self.assertEqual(surface["reached_particle_ids"], [1, 2, 3])
        self.assertEqual(surface["missing_particle_ids"], [4])
        self.assertEqual(surface["outside_declared_aperture_particle_ids"], [2])
        self.assertEqual(surface["failed_declared_direction_particle_ids"], [3])
        self.assertEqual(surface["wrong_axial_direction_particle_ids"], [3])
        self.assertEqual(surface["terminal_code_histogram_reached"], {
            "-1": 1, "1": 1, "2": 1,
        })
        self.assertEqual(surface["terminal_code_histogram_missing"], {"3": 1})
        self.assertEqual(
            surface["terminal_locations_reached"]["-1"]["location_event_count"], 1,
        )
        self.assertEqual(surface["terminal_locations_reached"]["-1"]["y"]["mean"], -5.5)
        self.assertEqual(
            surface["terminal_locations_missing"]["3"]["z"]["mean"], -250.0,
        )
        self.assertEqual(surface["slow_plane_angle"]["sample_count"], 3)
        self.assertEqual(surface["transverse_plane_angle"]["sample_count"], 3)
        components = surface["kinetic_energy_per_charge"]
        self.assertEqual(components["status"], "evaluated")
        self.assertEqual(components["Ex"]["sample_count"], 3)
        self.assertEqual(components["Ey"]["sample_count"], 3)
        self.assertEqual(components["Ez"]["sample_count"], 3)
        self.assertEqual(components["center_particle_id"], 1)
        self.assertGreater(components["center"]["Ez"], components["center"]["Ey"])
        target = components["fixed_observation_plane_target_diagnostic"]
        self.assertEqual(target["qualification"],
                         "diagnostic_only__low_field_plateau_not_formally_validated")
        self.assertEqual(
            target["axial_energy_acceptance"]["status"],
            "not_applicable__downstream_fields_intentionally_change_component_energies",
        )
        self.assertEqual(
            target["slow_energy_acceptance"]["status"],
            "not_applicable__downstream_fields_intentionally_change_component_energies",
        )
        self.assertIsNone(target["slow_energy_acceptance"]["absolute_tolerance_per_charge_v"])
        self.assertIsNone(target["axial_energy_acceptance"]["absolute_tolerance_per_charge_v"])
        for name in (
            "y_vs_slow_angle", "x_vs_transverse_angle",
            "slow_angle_vs_energy", "transverse_angle_vs_energy",
        ):
            with self.subTest(correlation=name):
                self.assertGreater(surface["correlations"][name], 0.9)
        self.assertEqual(result["detector_hit_count"], 0)

    def test_p2_energy_targets_and_downstream_drift_use_full_source_cohort(self):
        mass = 524.0
        component = lambda speed: 0.5 * mass * 1.66053906660e-27 * speed**2 * 1.0e6 / 1.602176634e-19
        events = [
            terminal(1, splat=1, x_mm=0.0, y_mm=1.0, z_mm=2.0),
            terminal(2, splat=-1, x_mm=3.0, y_mm=4.0, z_mm=5.0),
            terminal(3, splat=2, x_mm=6.0, y_mm=7.0, z_mm=8.0),
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 0.5,
             "x_mm": 0.0, "y_mm": -53.0, "z_mm": -6.0,
             "vx_mm_us": 1.0, "vy_mm_us": 2.0, "vz_mm_us": -10.0,
             "from_instance": 3, "to_instance": 2},
            {"kind": "p2_low_field_crossing", "ion": 1, "t_us": 1.0,
             "x_mm": 0.0, "y_mm": 0.0, "z_mm": 33.0,
             "vx_mm_us": 1.0, "vy_mm_us": 2.0, "vz_mm_us": 10.0,
             "inside_aperture": 1, "direction_ok": 1},
            {"kind": "drift_phase_origin", "ion": 1, "t_us": 2.0,
             "x_mm": 0.0, "y_mm": 5.0, "z_mm": 280.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 0.0},
            {"kind": "central_plane_directional", "ion": 1, "n": 1, "direction_z": -1,
             "t_us": 3.0, "x_mm": 0.0, "y_mm": 6.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -10.0},
            {"kind": "slow_turn", "ion": 1, "n": 1, "t_us": 4.0,
             "x_mm": 0.0, "y_mm": 105.0, "z_mm": -280.0},
            {"kind": "target_k", "ion": 1, "k": 25.5, "t_us": 5.0,
             "x_mm": 0.0, "y_mm": 5.0, "z_mm": -280.0},
            {"kind": "drift_phase_origin", "ion": 2, "t_us": 2.1,
             "x_mm": 0.0, "y_mm": -2.0, "z_mm": 280.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": 0.0},
            {"kind": "central_plane_directional", "ion": 2, "n": 1, "direction_z": -1,
             "t_us": 3.1, "x_mm": 0.0, "y_mm": -1.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -10.0},
            {"kind": "slow_turn", "ion": 2, "n": 1, "t_us": 4.1,
             "x_mm": 0.0, "y_mm": 98.0, "z_mm": -280.0},
        ]
        result = summarize_events(
            events, 25.5, 3, expected_particle_ids=(1, 2, 3),
            mass_th=mass, charge_e=1.0,
            theoretical_transverse_energy_per_charge_v=component(1.0),
            theoretical_axial_energy_per_charge_v=component(10.0),
            theoretical_release_slow_energy_per_charge_v=component(2.0),
            transverse_energy_tolerance_per_charge_v=0.05,
            slow_energy_tolerance_per_charge_v=0.05,
            axial_energy_tolerance_per_charge_v=0.05,
            source_transverse_reference={
                "center_particle_id": 1,
                "center_x_mm": 0.0, "center_vx_mm_per_us": 1.0,
                "mean_x_mm": 0.0, "mean_vx_mm_per_us": 1.0,
            },
        )
        diagnostic = result["prism_phase_space_diagnostic"]["surfaces"][
            "p2_fixed_observation_plane"
        ]["kinetic_energy_per_charge"]["fixed_observation_plane_target_diagnostic"]
        self.assertEqual(diagnostic["status"], "evaluated__diagnostic_only")
        self.assertAlmostEqual(diagnostic["measured_minus_theoretical_axial_energy_per_charge_v"], 0.0)
        self.assertAlmostEqual(diagnostic["measured_minus_theoretical_release_slow_energy_per_charge_v"], 0.0)
        self.assertEqual(
            diagnostic["slow_energy_acceptance"]["status"],
            "not_applicable__downstream_fields_intentionally_change_component_energies",
        )
        self.assertIsNone(diagnostic["slow_energy_acceptance"]["within_tolerance"])
        self.assertIsNone(diagnostic["axial_energy_acceptance"]["within_tolerance"])
        component_targets = result["prism_phase_space_diagnostic"]["surfaces"][
            "p2_fixed_observation_plane"
        ]["kinetic_energy_per_charge"]["component_target_diagnostic"]["components"]
        self.assertEqual(
            component_targets["Ex"]["acceptance"]["status"],
            "not_applicable__downstream_fields_intentionally_change_component_energies",
        )
        self.assertAlmostEqual(component_targets["Ey"]["measured_minus_theoretical_per_charge_v"], 0.0)
        self.assertAlmostEqual(component_targets["Ez"]["measured_minus_theoretical_per_charge_v"], 0.0)
        safe_exit = result["prism_phase_space_diagnostic"]["surfaces"][
            "accelerator_safe_exit"
        ]["kinetic_energy_per_charge"]["component_target_diagnostic"]
        self.assertEqual(safe_exit["comparison_scope"], "center_particle_only")
        for component_name in ("Ex", "Ey", "Ez"):
            acceptance = safe_exit["components"][component_name]["acceptance"]
            self.assertEqual(acceptance["status"], "evaluated__center_particle_only")
            self.assertTrue(acceptance["within_tolerance"])

        drift = result["downstream_drift_capability"]
        self.assertEqual(drift["scope"], "all_source_particles__not_detector_survivors")
        self.assertEqual(drift["first_main_drift"]["reached_particle_ids"], [1, 2])
        self.assertAlmostEqual(drift["first_main_drift"]["arrival_fraction"], 2 / 3)
        self.assertEqual(drift["target_k"]["reached_particle_ids"], [1])
        self.assertAlmostEqual(drift["target_k"]["fraction"], 1 / 3)
        self.assertEqual(drift["main_slow_turn"]["drift_length"]["mean"], 100.0)
        missing = drift["missing_first_main_drift_terminal_attribution"]
        self.assertEqual(missing["terminal_code_histogram"], {"2": 1})
        self.assertEqual(missing["particle_rows"][0]["z_mm"], 8.0)

    def test_safe_exit_signed_bias_uses_source_to_exit_delta(self):
        events = [
            terminal(1), terminal(2),
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 0.5,
             "x_mm": 0.11, "y_mm": -53.0, "z_mm": -6.0,
             "vx_mm_us": 0.01005, "vy_mm_us": 2.0, "vz_mm_us": -10.0,
             "from_instance": 3, "to_instance": 2},
            {"kind": "accelerator_safe_exit", "ion": 2, "t_us": 0.6,
             "x_mm": 0.31, "y_mm": -53.0, "z_mm": -6.0,
             "vx_mm_us": 0.03005, "vy_mm_us": 2.0, "vz_mm_us": -10.0,
             "from_instance": 3, "to_instance": 2},
        ]
        result = summarize_events(
            events, 25.5, 2, expected_particle_ids=(1, 2), mass_th=524.0,
            charge_e=1.0,
            source_transverse_reference={
                "particle_count": 2, "center_particle_id": 1,
                "center_x_mm": 0.1, "center_vx_mm_per_us": 0.01,
                "mean_x_mm": 0.2, "mean_vx_mm_per_us": 0.02,
            },
            transverse_velocity_bias_tolerance_mm_per_us=0.0001,
        )
        bias = result["prism_phase_space_diagnostic"]["surfaces"][
            "accelerator_safe_exit"
        ]["signed_transverse_bias"]
        self.assertAlmostEqual(bias["center_delta_vx_mm_per_us"], 0.00005)
        self.assertAlmostEqual(bias["mean_delta_vx_mm_per_us"], 0.00005)
        self.assertAlmostEqual(bias["center_delta_x_mm"], 0.01)
        self.assertAlmostEqual(bias["mean_delta_x_mm"], 0.01)
        self.assertTrue(bias["passed"])

    def test_phase_space_center_requires_explicit_source_identity(self):
        events = [
            terminal(1), terminal(2),
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 0.5,
             "x_mm": 0.1, "y_mm": -53.0, "z_mm": -6.0,
             "vx_mm_us": 1.0, "vy_mm_us": 2.0, "vz_mm_us": -10.0,
             "from_instance": 3, "to_instance": 2},
            {"kind": "accelerator_safe_exit", "ion": 2, "t_us": 0.6,
             "x_mm": 0.2, "y_mm": -53.0, "z_mm": -6.0,
             "vx_mm_us": 2.0, "vy_mm_us": 3.0, "vz_mm_us": -10.0,
             "from_instance": 3, "to_instance": 2},
        ]
        formal = summarize_events(
            events, 25.5, 2, expected_particle_ids=(1, 2), mass_th=524.0,
            charge_e=1.0,
            source_transverse_reference={
                "center_particle_id": None,
                "center_x_mm": None, "center_vx_mm_per_us": None,
                "mean_x_mm": 0.15, "mean_vx_mm_per_us": 1.5,
            },
        )["prism_phase_space_diagnostic"]["surfaces"]["accelerator_safe_exit"]
        self.assertIsNone(formal["center_state"])
        self.assertIsNone(formal["kinetic_energy_per_charge"]["center_particle_id"])
        self.assertIsNone(formal["kinetic_energy_per_charge"]["center"])
        self.assertEqual(
            formal["kinetic_energy_per_charge"]["component_target_diagnostic"][
                "comparison_scope"
            ],
            "unavailable__source_has_no_declared_center",
        )

        controlled = summarize_events(
            events, 25.5, 2, expected_particle_ids=(1, 2), mass_th=524.0,
            charge_e=1.0,
            source_transverse_reference={
                "center_particle_id": 2,
                "center_x_mm": 0.2, "center_vx_mm_per_us": 2.0,
                "mean_x_mm": 0.15, "mean_vx_mm_per_us": 1.5,
            },
        )["prism_phase_space_diagnostic"]["surfaces"]["accelerator_safe_exit"]
        self.assertEqual(controlled["center_state"]["ion"], 2)
        self.assertEqual(controlled["kinetic_energy_per_charge"]["center_particle_id"], 2)

    def test_prism_phase_space_pairs_p2_entry_and_exit_by_particle_id(self):
        def p2_event(kind: str, ion: int, time: float, vx: float, vy: float,
                     vz: float) -> dict[str, object]:
            return {
                "kind": kind, "ion": ion, "n": 2, "t_us": time,
                "x_mm": float(ion), "y_mm": 2.0 * ion, "z_mm": 33.0,
                "vx_mm_us": vx, "vy_mm_us": vy, "vz_mm_us": vz,
            }

        events = [
            terminal(1), terminal(2), terminal(3),
            p2_event("prism_entry", 1, 1.0, 0.0, 0.0, 10.0),
            p2_event("prism_pass", 1, 2.0, 1.0, 10.0, 10.0),
            p2_event("prism_entry", 2, 1.1, 0.0, 2.0, 10.0),
            p2_event("prism_pass", 3, 2.1, 0.0, 3.0, 10.0),
        ]
        result = summarize_events(
            events, 25.5, 3, expected_particle_ids=(1, 2, 3),
            mass_th=524.0, charge_e=1.0,
        )
        diagnostic = result["prism_phase_space_diagnostic"]
        self.assertEqual(
            diagnostic["surfaces"]["p2_entry"]["reached_particle_ids"], [1, 2],
        )
        self.assertEqual(
            diagnostic["surfaces"]["p2_exit"]["reached_particle_ids"], [1, 3],
        )
        for surface_name in ("p2_entry", "p2_exit"):
            components = diagnostic["surfaces"][surface_name]["kinetic_energy_per_charge"]
            self.assertEqual(components["status"], "evaluated")
            self.assertEqual(components["Ex"]["sample_count"], 2)
            self.assertEqual(components["Ey"]["sample_count"], 2)
            self.assertEqual(components["Ez"]["sample_count"], 2)
        paired = diagnostic["p2_entry_to_exit"]
        self.assertEqual(paired["common_particle_ids"], [1])
        self.assertAlmostEqual(paired["slow_angle_change"]["mean"], 45.0)
        self.assertAlmostEqual(
            paired["transverse_angle_change"]["mean"],
            math.degrees(math.atan2(1.0, 10.0)),
        )
        expected_energy_change = (
            0.5 * 524.0 * 1.66053906660e-27 * 101.0e6 / 1.602176634e-19
        )
        self.assertAlmostEqual(
            paired["kinetic_energy_change"]["mean"], expected_energy_change,
        )

    def test_paired_segment_angle_attribution_uses_same_particles_and_linear_residuals(self):
        def event(kind: str, ion: int, time: float, vx: float, vy: float,
                  vz: float, **extra: object) -> dict[str, object]:
            return {
                "kind": kind, "ion": ion, "t_us": time,
                "x_mm": float(ion), "y_mm": 2.0 * ion, "z_mm": 33.0,
                "vx_mm_us": vx, "vy_mm_us": vy, "vz_mm_us": vz,
                **extra,
            }

        events = [terminal(1), terminal(2), terminal(3)]
        for ion, scale in ((1, 1.0), (2, 2.0)):
            events.extend([
                event("accelerator_safe_exit", ion, 1.0, scale, scale, -10.0,
                      from_instance=7, to_instance=1),
                event("prism_entry", ion, 2.0, 2 * scale, 2 * scale, -10.0, n=1),
                event("prism_pass", ion, 3.0, 3 * scale, 3 * scale, -10.0, n=1),
                event("prism_entry", ion, 4.0, 4 * scale, 4 * scale, 10.0, n=2),
                event("prism_pass", ion, 5.0, 5 * scale, 5 * scale, 10.0, n=2),
            ])
        # Ion 3 reaches only P1 entry; the paired sets must expose its missing endpoints.
        events.append(event("prism_entry", 3, 2.2, 3.0, 3.0, -10.0, n=1))
        result = summarize_events(
            events, 25.5, 3, expected_particle_ids=(1, 2, 3),
            mass_th=524.0, charge_e=1.0,
        )
        paired = result["prism_phase_space_diagnostic"]["paired_angle_attribution"]
        direct = paired["accelerator_safe_exit_to_p1_exit"]
        self.assertEqual(direct["common_particle_ids"], [1, 2])
        self.assertIn("includes_intervening_drift_and_p1", direct["segment_semantics"])
        for surface_name in ("accelerator_safe_exit", "p1_exit", "p2_exit"):
            energy = result["prism_phase_space_diagnostic"]["surfaces"][surface_name][
                "kinetic_energy_per_charge"
            ]
            self.assertEqual(energy["Ex"]["sample_count"], 2)
            self.assertEqual(energy["Ey"]["sample_count"], 2)
            self.assertEqual(energy["Ez"]["sample_count"], 2)
            self.assertIn("component_target_diagnostic", energy)
        accelerator = paired["accelerator_safe_exit_to_p1_entry"]
        self.assertEqual(accelerator["common_particle_ids"], [1, 2])
        self.assertEqual(accelerator["missing_input_particle_ids"], [3])
        self.assertEqual(accelerator["missing_output_particle_ids"], [])
        self.assertEqual(accelerator["slow_plane"]["output_minus_input"]["sample_count"], 2)
        self.assertIsNotNone(accelerator["slow_plane"]["linear_output_vs_input"]["slope"])
        self.assertAlmostEqual(
            accelerator["slow_plane"]["linear_output_vs_input"]["residual"]["standard_deviation"],
            0.0, places=12,
        )
        self.assertIn("must_not_be_subtracted", accelerator["spread_semantics"])
        p1 = paired["p1_entry_to_p1_exit"]
        self.assertEqual(p1["common_particle_ids"], [1, 2])
        self.assertEqual(p1["missing_output_particle_ids"], [3])
        between = paired["p1_exit_to_p2_exit"]
        self.assertEqual(between["common_particle_ids"], [1, 2])
        self.assertIn("includes_intervening_transport_and_p2", between["segment_semantics"])
        self.assertEqual(paired["p2_entry_to_p2_exit"]["common_particle_ids"], [1, 2])

    def test_retired_patch_interface_event_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown_event_or_missing_fields"):
            parse_events(
                "MRTOF_EVENT patch_interface ion=1 name=obsolete region=obsolete "
                "face=z_max n=2 direction=-1 t_us=29 x_mm=0.1 y_mm=6 z_mm=102 "
                "vx_mm_us=0 vy_mm_us=1 vz_mm_us=-39\n"
            )

    def test_instance_transition_event_is_strict_and_numeric(self):
        line = (
            "MRTOF_EVENT instance_transition ion=1 t_us=29 instance=4 "
            "x_mm=0.1 y_mm=6 z_mm=0\n"
        )
        event = parse_events(line)[0]
        self.assertEqual(event["kind"], "instance_transition")
        self.assertEqual(event["instance"], 4)
        with self.assertRaisesRegex(ValueError, "invalid_instance_number"):
            parse_events(line.replace("instance=4", "instance=4.5"))

    def test_accelerator_pulse_off_event_preserves_instance_transition(self):
        line = (
            "MRTOF_EVENT accelerator_pulse_off ion=1 t_us=1.8675 "
            "from_instance=7 to_instance=1 x_mm=0 y_mm=-53 z_mm=-5.7\n"
        )
        event = parse_events(line)[0]
        self.assertEqual(event["from_instance"], 7)
        self.assertEqual(event["to_instance"], 1)
        with self.assertRaisesRegex(ValueError, "invalid_instance_number"):
            parse_events(line.replace("from_instance=7", "from_instance=3.5"))

    def test_accelerator_launch_vz_zero_is_diagnostic_not_nonmirror_reversal(self):
        line = (
            "MRTOF_EVENT accelerator_launch_vz_zero ion=2 "
            "direction_before=1 direction_after=-1 t_us=0.000062 "
            "x_mm=0 y_mm=-55.2 z_mm=36.8 "
            "vx_mm_us=0 vy_mm_us=1.35 vz_mm_us=0\n"
        )
        event = parse_events(line)[0]
        self.assertEqual(event["kind"], "accelerator_launch_vz_zero")
        self.assertEqual(event["direction_before"], 1)
        self.assertEqual(event["direction_after"], -1)
        result = summarize_events(
            [event, terminal(2)], 25.5, 1, expected_particle_ids=(2,),
        )
        self.assertNotIn("nonmirror_vz_reversal_observed", result["integrity_errors"])

    def assert_invalid(self, events, expected, splats, error):
        result = summarize_events(events, 25.5, splats, expected_particle_ids=expected)
        self.assertFalse(result["event_integrity_passed"])
        self.assertIn(error, result["integrity_errors"])
        for key in ("detection_rate", "target_k_fraction", "detector_tof_fwhm_us",
                    "mass_resolution_t_over_2fwhm", "target_k_handoff_tof_fwhm_us"):
            self.assertIsNone(result[key], key)
        return result

    def test_complete_cohort_keeps_actual_losses_and_detector_metrics(self):
        events = ([terminal(i, splat=1) for i in range(1, 9)] + [terminal(9)]
                  + [event for ion in range(1, 9) for event in static_return_chain(ion)])
        result = summarize_events(events, 25.5, 9, expected_particle_ids=tuple(range(1, 10)),
                                  peak_analysis_contract=PEAK_CONTRACT, cohort_role="formal_volume", mass_th=524)
        self.assertTrue(result["all_losses_retained"])
        self.assertEqual(result["electrode_collision_count"], 1)
        self.assertEqual(result["detection_rate"], 8 / 9)
        self.assertGreater(result["mass_resolution_t_over_2fwhm"], 0)

    def test_volume_only_metrics_are_supplemental_to_all_particle_metrics(self):
        expected = tuple(range(1, 23))
        events = (
            [terminal(ion, splat=1) for ion in expected]
            + [event for ion in expected for event in static_return_chain(ion)]
        )
        result = summarize_events(
            events, 25.5, len(expected), expected_particle_ids=expected,
            volume_particle_id_min=14,
        )
        volume = result["volume_only"]
        self.assertEqual(result["detector_hit_count"], 22)
        self.assertEqual(volume["status"], "supplemental_not_formal_replacement")
        self.assertEqual(volume["particle_id_min"], 14)
        self.assertEqual(volume["expected_particle_count"], 9)
        self.assertEqual(volume["detector_hit_count"], 9)
        self.assertEqual(volume["detection_rate"], 1.0)
        self.assertIsNone(volume["detector_tof_fwhm_us"])
        self.assertIsNone(volume["mass_resolution_t_over_2fwhm"])

    def test_single_particle_topology_events_preserve_y0_and_full_period(self):
        events = [
            {"kind": "fast_turn", "ion": 1, "n": 1, "t_us": 1, "x_mm": 0, "y_mm": -1, "z_mm": -10, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": 0},
            {"kind": "slow_turn", "ion": 1, "n": 1, "t_us": 2, "x_mm": 0, "y_mm": -100, "z_mm": 0},
            {"kind": "p1_plane", "ion": 1, "n": 1, "t_us": 2.5, "x_mm": 0, "y_mm": 10, "z_mm": -101, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -2},
            {"kind": "slow_coordinate_y0", "ion": 1, "n": 1, "direction_y": 1, "t_us": 3, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": 1, "vz_mm_us": -2},
            {"kind": "drift_phase_origin", "ion": 1, "t_us": 3.5, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": 1, "vz_mm_us": -2},
            {"kind": "drift_phase_candidate", "ion": 1, "k": 25.5, "t_us": 6.5, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -2},
            {"kind": "target_k_phase_sample", "ion": 1, "k": 25.5, "t_us": 6.5, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -2},
            {"kind": "drift_phase_return", "ion": 1, "k": 25.5, "t_us": 6.5, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -2},
            {"kind": "slow_coordinate_y0", "ion": 1, "n": 2, "direction_y": -1, "t_us": 7, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": 2},
            {"kind": "drift_coordinate_return", "ion": 1, "k_before": 25, "fractional_k": 25.25, "phase_crossing_t_us": 6.5, "phase_crossing_y_mm": 0, "phase_time_residual_us": 0.5, "phase_period_us": 2.0, "t_us": 7, "x_mm": 0, "y_mm": 0, "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": 2},
            {"kind": "central_plane_directional", "ion": 1, "n": 1, "direction_z": -1, "t_us": 4, "x_mm": 0, "y_mm": -2, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -2},
            {"kind": "central_plane_directional", "ion": 1, "n": 3, "direction_z": -1, "t_us": 6, "x_mm": 0, "y_mm": -2, "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -2},
            terminal(1),
        ]
        result = summarize_events(
            events, 25.5, 1, expected_particle_ids=(1,), kinetic_energy_ev=4000.0, mass_th=524.0,
        )
        self.assertEqual(result["fast_z_turn_count"], 1)
        self.assertEqual(result["slow_y_turn_count"], 1)
        self.assertEqual(result["slow_coordinate_y0_inbound_crossing_count"], 1)
        self.assertEqual(result["slow_coordinate_y0_outbound_crossing_count"], 1)
        self.assertEqual(result["P1_plane_crossing_count"], 1)
        self.assertEqual(result["drift_phase_origin_count"], 1)
        self.assertEqual(result["drift_phase_return_count"], 1)
        self.assertEqual(result["drift_phase_candidate_count"], 1)
        self.assertEqual(result["target_k_phase_sample_count"], 1)
        self.assertEqual(result["target_k_phase_y_residuals_mm"], [0.0])
        self.assertEqual(result["drift_coordinate_return_count"], 1)
        self.assertEqual(result["drift_coordinate_return_diagnostics"][0]["k_before"], 25)
        self.assertEqual(result["drift_coordinate_return_diagnostics"][0]["fractional_k"], 25.25)
        self.assertEqual(result["same_direction_central_plane_periods_us"], [2.0])
        self.assertEqual(result["slow_drift_abs_lengths_from_y0_mm"], [100.0])
        self.assertEqual(len(result["effective_axial_width_W_mm"]), 1)
        self.assertGreater(result["effective_axial_width_W_median_mm"], 0.0)

    def test_prism_voltage_switch_event_is_strict_and_numeric(self):
        line = (
            "MRTOF_EVENT prism_voltage_switch ion=1 electrode=17 t_us=773.5 "
            "from_v=-179.1 to_v=0"
        )
        event = parse_events(line)[0]
        self.assertEqual(event["kind"], "prism_voltage_switch")
        self.assertEqual(event["electrode"], 17)
        self.assert_invalid(
            [event, terminal(1)], (1,), 1, "prism_voltage_switch_forbidden",
        )
        with self.assertRaisesRegex(ValueError, "invalid_event_counter"):
            parse_events(line.replace("electrode=17", "electrode=17.5"))

    def test_integer_target_is_rejected_for_opposite_mirror_return(self):
        with self.assertRaisesRegex(ValueError, "odd half-integer"):
            summarize_events([], 25, 0, expected_particle_ids=(1,))

    def test_return_p1_event_is_forbidden_after_positive_mirror_turn(self):
        event = {
            "kind": "return_p1_pass", "ion": 1, "t_us": 14,
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": -1,
        }
        self.assert_invalid(
            [terminal(1, splat=1), *static_return_chain(1), event], (1,), 1,
            "return_p1_forbidden__p1_is_injection_only",
        )

    def test_detector_without_static_return_chain_fails_closed(self):
        self.assert_invalid(
            [terminal(1, splat=1), detector(1)], (1,), 1,
            "invalid_static_detector_event_chain",
        )

    def test_static_return_rejects_wrong_prism_direction_and_nonmirror_reversal(self):
        wrong_direction = static_return_chain(1)
        next(event for event in wrong_direction if event["kind"] == "return_p2_pass")["vz_mm_us"] = -1
        self.assert_invalid(
            [terminal(1, splat=1), *wrong_direction], (1,), 1,
            "invalid_static_detector_event_chain",
        )
        reversal = {
            "kind": "nonmirror_reversal", "ion": 1,
            "direction_before": 1, "direction_after": -1, "t_us": 10,
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "vx_mm_us": 0, "vy_mm_us": -1, "vz_mm_us": 0,
        }
        self.assert_invalid(
            [terminal(1), reversal], (1,), 1, "nonmirror_vz_reversal_observed",
        )

    def test_detector_requires_complete_nonretracing_mirror_pair_evidence(self):
        chain = [event for event in static_return_chain(1)
                 if event["kind"] != "fast_turn"]
        self.assert_invalid(
            [terminal(1, splat=1), *chain], (1,), 1,
            "mirrored_nonretracing_branch_turn_evidence_incomplete",
        )

    def test_no_completion_or_source_never_infers_population_from_events(self):
        result = self.assert_invalid([terminal(1)], (1,), None, "missing_or_multiple_fly_completion")
        self.assertEqual(result["particle_terminal_count"], 1)
        result = self.assert_invalid([], None, None, "missing_frozen_particle_source")
        self.assertIsNone(result["expected_particle_count"])
        self.assertFalse(result["all_losses_retained"])

    def test_missing_identity_blocks_metrics_even_with_usable_peak(self):
        events = [terminal(i) for i in range(1, 9)] + [detector(i) for i in range(1, 9)]
        result = self.assert_invalid(events, tuple(range(1, 11)), 10, "missing_particle_terminal_events")
        self.assertEqual(result["missing_terminal_particle_ids"], [9, 10])
        self.assertEqual(result["detector_hit_count"], 8)
        self.assertEqual(len(result["detector_tof_us"]), 8)

    def test_duplicate_and_unknown_ids_cannot_replace_missing_particle(self):
        result = self.assert_invalid([terminal(1), terminal(1)], (1, 2), 2, "duplicate_particle_events")
        self.assertEqual(result["duplicate_event_particle_ids"]["terminal"], [1])
        self.assertEqual(result["unique_particle_terminal_count"], 1)
        result = self.assert_invalid([terminal(1), terminal(9)], (1, 2), 2, "unknown_particle_ids")
        self.assertEqual(result["unknown_particle_ids"], [9])
        for kind in ("detector", "target_k", "splat"):
            event = ({**detector(1), "kind": kind, **({"k": 25} if kind == "target_k" else {})}
                     if kind != "splat" else {"kind": kind, "ion": 1, "code": -1, "turns": 2, "t_us": 100})
            with self.subTest(kind=kind):
                self.assert_invalid([terminal(1), event, event], (1,), 1, "duplicate_particle_events")

    def test_splat_fallback_is_counted_once_and_conflicts_are_rejected(self):
        splat = {"kind": "splat", "ion": 1, "code": -1, "t_us": 100, "turns": 2}
        result = summarize_events([splat], 25.5, 1, expected_particle_ids=(1,))
        self.assertTrue(result["event_integrity_passed"])
        self.assertEqual(result["splat_code_missing_count"], 0)
        result = summarize_events([splat, terminal(1)], 25.5, 1, expected_particle_ids=(1,))
        self.assertEqual(result["particle_terminal_count"], 1)
        self.assertEqual(result["splat_fallback_event_count"], 0)
        self.assert_invalid([splat, terminal(1, splat=1)], (1,), 1, "splat_terminal_reason_conflict")

    def test_solver_count_must_equal_frozen_source_count(self):
        self.assert_invalid([terminal(1)], (1,), 2, "fly_splat_count_differs_from_source")
        result = summarize_events([terminal(1)], 25.5, 1, expected_particle_ids=(1,), completion_count=2)
        self.assertFalse(result["event_integrity_passed"])

    def test_strict_event_anchor_never_salvages_prefixed_or_malformed_events(self):
        line = ("MRTOF_EVENT terminal ion=1 splat=-1 t_us=100 turns=2 x_mm=0 y_mm=0 z_mm=0 "
                "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=2")
        self.assertEqual(parse_events("status," + line + "\n"), [])
        for malformed in (line + " broken", line + " ion=2", line.replace("turns=2", "turns="),
                          line.replace("t_us=100", "t_us=nan"), line.replace("ion=1", "ion=1.5")):
            with self.subTest(line=malformed), self.assertRaises(ValueError):
                parse_events(malformed)
        self.assertEqual(len(parse_events(line + "\n")), 1)
        with self.assertRaisesRegex(ValueError, "incomplete_log_event"):
            parse_events(line.rsplit(" ", 1)[0] + "\n")

    def test_all_four_sources_have_contract_derived_ids_counts_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture_manifest(Path(directory))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for key in SOURCE_COUNT_KEYS:
                source = load_particle_source(path, key)
                record = manifest[key]
                self.assertEqual(list(source["expected_particle_ids"]), record["expected_particle_ids"])
                self.assertEqual(len(source["expected_particle_ids"]), record["particle_count"])
                self.assertEqual(source["target_k"], 25.5)
                self.assertEqual(source["provenance"]["fly2_sha256"], record["sha256"])

    def test_modified_source_contract_or_id_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = fixture_manifest(root)
            original = json.loads(path.read_text(encoding="utf-8"))
            for key, value in (("particle_count", 2), ("expected_particle_ids", [2]),
                               ("expected_particle_ids_sha256", "0" * 64),
                               ("particle_count_contract_key", "candidate_bunch_particle_count")):
                changed = copy.deepcopy(original)
                changed["center_fly2"][key] = value
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_particle_source(path, "center_fly2")
            path.write_text(json.dumps(original), encoding="utf-8")
            for filename in ("center_fly2.fly2", "simion_prototype_contract.json"):
                target = root / filename
                payload = target.read_bytes()
                target.write_bytes(payload + b" ")
                with self.subTest(filename=filename), self.assertRaises(ValueError):
                    load_particle_source(path, "center_fly2")
                target.write_bytes(payload)

    def test_current_manifest_keeps_mirror_diagnostic_out_of_full_center(self):
        with tempfile.TemporaryDirectory() as directory:
            path = current_fixture_manifest(Path(directory))
            diagnostic = load_particle_source(path, "mirror_internal_diagnostic_center_fly2")
            self.assertEqual(diagnostic["axial_kinetic_energy_ev"], 4000.0)
            self.assertEqual(diagnostic["provenance"]["source_key"], "mirror_internal_diagnostic_center_fly2")
            with self.assertRaisesRegex(ValueError, "full MR-TOF center remains unpublished"):
                load_particle_source(path, "full_mrtof_center_fly2")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["mirror_internal_diagnostic_center_fly2"]["source_profile_id"] = "full_mrtof_center"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not bind its named source profile"):
                load_particle_source(path, "mirror_internal_diagnostic_center_fly2")

    def test_legacy_manifest_has_no_executable_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture_manifest(Path(directory))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_particle_source(path, "center_fly2")

    def test_cli_exit_code_tracks_integrity_and_selected_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = fixture_manifest(root)
            log = root / "stdout.log"
            output = root / "summary.json"
            event = ("MRTOF_EVENT terminal ion=1 splat=-1 t_us=100 turns=2 x_mm=0 y_mm=0 z_mm=0 "
                     "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=2\n")
            for suffix, expected_code in (("status,Fly completed. 1 splats, 1 seconds\n", 0), ("", 1)):
                log.write_text(event + suffix, encoding="utf-8")
                result = subprocess.run([sys.executable, "-m",
                    "projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis",
                    str(log), str(output), "--input-manifest", str(manifest), "--source-key", "center_fly2"],
                    cwd=REPOSITORY_ROOT, capture_output=True, text=True,
                    timeout=30, check=False)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertIn("=PASS" if expected_code == 0 else "=FAIL", result.stdout)
                summary = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(summary["event_integrity_passed"], expected_code == 0)
            log.write_text(event + "status,Fly completed. 1 splats\n" * 2, encoding="utf-8")
            summary = analyze_log(log, output, input_manifest=manifest, source_key="center_fly2")
            self.assertFalse(summary["event_integrity_passed"])
            self.assertEqual(summary["fly_completion_count"], 2)

    def test_terminal_instance_and_voltage_are_optional_backward_compatible_fields(self):
        legacy = ("MRTOF_EVENT terminal ion=1 splat=-1 t_us=100 x_mm=0 y_mm=0 z_mm=0 "
                  "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 turns=2 central_crossings=2")
        current = legacy.replace("splat=-1", "splat=-1 instance=2 volts=0")
        self.assertNotIn("instance", parse_events(legacy)[0])
        self.assertEqual(parse_events(current)[0]["instance"], 2)
        self.assertEqual(parse_events(current)[0]["volts"], 0)

    def test_geometric_exit_event_parses_as_a_complete_velocity_state(self):
        event = parse_events(
            "MRTOF_EVENT accelerator_geometric_exit ion=7 localization=linear_bracket "
            "t_us=1.25 x_mm=0.1 y_mm=-55 z_mm=0 "
            "vx_mm_us=0.2 vy_mm_us=1.3 vz_mm_us=-34.7\n"
        )[0]
        self.assertEqual(event["kind"], "accelerator_geometric_exit")
        self.assertEqual(event["ion"], 7)
        self.assertEqual(event["vz_mm_us"], -34.7)

    def test_collision_geometry_names_shared_id_and_refuses_ambiguous_overlap(self):
        geometry = {
            "mesh_mm_per_gu": 0.25,
            "mirror_electrodes": [], "mirror_slot": [-1, -1, -1, 1, 1, 1],
            "mirror_inner_shield_slot": [-1, -1, -1, 1, 1, 1],
            "mirror_ground_shields": [{"box": [-5, 20, -10, 5, 30, -9]}],
            "mirror_e_closures": [],
            "stripe_electrodes": [{
                "id": 12, "x": [-2, 2],
                "polygon_yz_mm": [[-1, -10], [1, -10], [1, -9], [-1, -9]],
                "terminal_polygon_yz_mm": [[40, 40], [41, 40], [41, 41], [40, 41]],
            }],
            "stripe_slot": [-1, 50, 50, 1, 51, 51],
            "central_ground_electrodes": [{
                "x": [-2, 2],
                "polygon_yz_mm": [[-1, -10], [1, -10], [1, -9], [-1, -9]],
            }],
            "central_ground_slots": [],
            "prism_electrodes": [],
            "prism_ground_shields": [{
                "id": 20, "x": [-5, 5],
                "outer_polygon_yz_mm": [[-10, -10], [-3, -10], [-3, 10], [-10, 10]],
                "body_sections": [{
                    "x": [-5, 5],
                    "polygon_yz_mm": [[-10, -10], [-3, -10], [-3, 10], [-10, 10]],
                }],
                "rectangular_slots_mm": [],
                "prism_clearance_polygon_yz_mm": [[-9, 0], [-8, -1], [-8, 1]],
                "cross_aperture": {},
            }],
        }
        events = [
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1},
            {"kind": "terminal", "ion": 1, "splat": -1, "t_us": 2,
             "x_mm": 0, "y_mm": -5, "z_mm": -10},
            {"kind": "terminal", "ion": 2, "splat": -1, "t_us": 3,
             "x_mm": 3, "y_mm": 25, "z_mm": -9.5},
            {"kind": "terminal", "ion": 3, "splat": -1, "t_us": 4,
             "x_mm": 0, "y_mm": 0, "z_mm": -9.5},
        ]
        result = collision_diagnostics(events, geometry)
        self.assertEqual(result["collision_component_histogram"], {
            "mirror_inner_ground_shields": 1,
            "p2_central_prism_ground_shield": 1,
            "unclassified": 1,
        })
        self.assertEqual(result["electrode_id_histogram"], {"15": 1, "20": 1})
        self.assertEqual(result["dominant_collision_component"], "p2_central_prism_ground_shield")
        first = result["collision_particles"][0]
        self.assertEqual(first["component"], "p2_central_prism_ground_shield")
        self.assertEqual(first["last_completed_stage"], "accelerator_safe_exit")
        ambiguous = result["collision_particles"][2]
        self.assertEqual(ambiguous["component"], "unclassified")
        self.assertEqual({item["component"] for item in ambiguous["candidate_components"]}, {
            "central_ion_foil_2_ground", "stripe_set_1",
        })


if __name__ == "__main__":
    unittest.main()
