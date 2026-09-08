from __future__ import annotations

import hashlib
import json
import math
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, build_simion_gem, derive_mirror_voltage_bounds,
    derive_operating_energy_envelope, derive_two_zone_focus, derive_two_zone_placement,
    load_contract, write_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry import (
    ELECTRODE_IDS,
    build_full_candidate_gem,
    resolve_simion_iob_origin,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    build_accelerator_gem, build_analyzer_gem, build_detector_gem,
    resolve_split_iob_origins,
)
from projects.orthogonal_accelerator.analysis.two_zone_geometry import derive_shielded_rectangular_enclosure
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    geometry_fingerprint,
    geometry_receipt,
    resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
    summarize_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_run_manifest import build_manifest
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.cad_pose_contract import (
    load_cad_pose_contract,
    project_to_source,
    source_to_project,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolve_cad_geometry import resolve
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.compose_ion_foil_profile_pose import compose
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import analyze_dual_stripe_l0
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    axial_potential_v,
    derive_mirror_l0_slope_tolerance_per_v,
    effective_axial_width_mm,
    normalized_period_slope_per_v,
    optimize_fixed_geometry_voltages,
    parallel_global_l0_family_search,
    three_point_normalized_period_slopes_per_v,
    three_point_report,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l1 import (
    continue_fixed_e_l0_family_to_gamma,
    map_at_energy,
    screen_l1_fixed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0_l1_hardware_candidate import screen_l1_family
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    _candidate_voltages,
    materialize,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_operating_point_variation import (
    OperatingPointVariationError,
    materialize_variation,
)


PROJECT = Path(__file__).resolve().parents[2]


def _contains_polygon(polygon, y, z):
    """Independent ray-crossing test of the frozen physical contour."""
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > z) != (b[1] > z) and y < a[0] + (z - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            inside = not inside
    return inside


def _contains_csg(sections, slots, point, triangle=None):
    x, y, z = point
    inside = any(section["x"][0] <= x <= section["x"][1]
                 and _contains_polygon(section["polygon_yz_mm"], y, z) for section in sections)
    cut = any(all(slot[i] <= point[i] <= slot[i + 3] for i in range(3)) for slot in slots)
    return inside and not cut and (triangle is None or not _contains_polygon(triangle, y, z))


class SimionCandidateReferenceTest(unittest.TestCase):
    def test_analyzer_gem_mesh_defaults_follow_contract_without_geometry_changes(self) -> None:
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        contract["simion"]["component_mesh_mm_per_gu"]["analyzer"] = [2, 2, 2]
        before = geometry_fingerprint(resolve_geometry(contract))
        contract["simion"]["component_mesh_mm_per_gu"]["analyzer"] = [1, 1, 1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            gem = build_analyzer_gem(path)
        self.assertIn("# local contract_mmgu_x, contract_mmgu_y, contract_mmgu_z = 1, 1, 1", gem)
        self.assertIn("runtime mesh must equal frozen Candidate contract", gem)
        self.assertEqual(before, geometry_fingerprint(resolve_geometry(contract)))

    def test_analyzer_x_slots_keep_cad_faces_at_active_grid_nodes(self) -> None:
        """A 30/4-mm mechanical channel must not render as 32/6 mm at 1 mm/gu."""
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            gem = build_analyzer_gem(path)
        # Official ``notin_inside`` retains grid nodes on the exact CAD faces.
        self.assertIn("notin_inside { box3D(-15,-448,106,15,132,163) }", gem)
        self.assertIn("notin_inside { box3D(-2,-448,-108,2,132,108) }", gem)
        self.assertIn("notin_inside { box3D(-2,-385,-97.9962772744,2,0,97.9962772744) }", gem)

    def test_native_shield_sections_are_not_bounding_boxes_and_cross_is_a_union(self) -> None:
        resolved = resolve_geometry(load_contract(PROJECT / "config/simion_candidate_two_zone.json"))
        first, central = resolved["prism_ground_shields"]
        self.assertEqual(first["prism_clearance_polygon_yz_mm"], [[40, -65], [70, -95], [70, -35]])
        self.assertEqual(central["prism_clearance_polygon_yz_mm"], [[0, 0], [26, -26], [26, 26]])
        self.assertEqual(len(central["body_sections"]), 3)
        # Native face/sketch + STL sections, away from all numerical boundaries.
        for shield, point, material in (
            (central, (4, 0, 60), False), (central, (4, 0, 10), True),
            (central, (-18, 4, 30), False), (central, (-18, 4, 60), True),
            (central, (0, 4, 30), False), (central, (0, 10, 60), False),
            (central, (0, 4, 60), True), (central, (4, 25, 24), False),
            (first, (-18, 34, -65), False), (first, (-18, 34, -85), True),
            (first, (-18, 74, -98), False), (first, (4, 42, -68), True),
        ):
            with self.subTest(point=point, shield=shield["id"]):
                self.assertEqual(_contains_csg(shield["body_sections"], shield["rectangular_slots_mm"], point,
                                               shield["prism_clearance_polygon_yz_mm"]), material)

    def test_all_foil_ends_are_native_whole_bodies_minus_rectangular_slots(self) -> None:
        resolved = resolve_geometry(load_contract(PROJECT / "config/simion_candidate_two_zone.json"))
        for record in resolved["stripe_electrodes"]:
            self.assertEqual(sorted({p[0] for p in record["terminal_polygon_yz_mm"]}), [0, 2])
            self.assertEqual(min(p[0] for p in record["polygon_yz_mm"]), -390)
        for record_index, z_inside, z_outside in ((0, 90, 66), (2, 50, 46)):
            record = resolved["stripe_electrodes"][record_index]
            sections = [{"x": record["x"], "polygon_yz_mm": record[key]}
                        for key in ("polygon_yz_mm", "terminal_polygon_yz_mm")]
            self.assertTrue(_contains_csg(sections, [resolved["stripe_slot"]], (0, 1, z_inside)))
            self.assertFalse(_contains_csg(sections, [resolved["stripe_slot"]], (0, 1, z_outside)))
        ground = resolved["central_ground_electrodes"]
        cuts = resolved["central_ground_slots"]
        for point, material in (((0, 1, 30), True), ((0, 1, 0), False), ((0, 1, 38), False),
                                ((4, -2, 39), True), ((4, -2, 0), False), ((0, -2, 30), False)):
            with self.subTest(point=point):
                self.assertEqual(_contains_csg(ground, cuts, point), material)

    def test_whole_body_contract_rejects_missing_topology_and_intersection_cross(self) -> None:
        for field in ("body_sections", "cad_body_topology_identity"):
            contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
            contract["prisms"]["ground_shields"][1].pop(field)
            with self.assertRaises(CandidateContractError):
                resolve_geometry(contract)
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        contract["prisms"]["ground_shields"][1]["cross_aperture"]["boolean_operation"] = "intersection"
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract)
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        contract["dual_stripe"]["central_ground_profile"].pop("terminal_profile")
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract)

    def test_operating_point_variation_is_derived_and_rejects_ambiguous_overrides(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            base = temporary / "base.operating_point.lua"
            base.write_text(
                "return { mirror_voltages_v = { 0, -10, 20, 30, 50 }, stripe_biases_v = { -4, 6 }, prism_voltages_v = { 141, 0 }, "
                "accelerator_voltages_v = { 100, 50, 0 }, accelerator_ring_voltages_v = { 40, 30, 20, 10, 0 }, detector_box_mm = { -1, 2, -3, 4, 5, 6 }, "
                "trajectory_quality = 8, maximum_step_us = 0.002, full_path_timeout_us = 800, nonaccelerator_scale = 1, target_oscillation_count = 25 }\n",
                encoding="utf-8",
            )
            overrides = temporary / "overrides.json"
            overrides.write_text(json.dumps({
                "purpose": "test variation",
                "overrides": {
                    "mirror_voltage_multipliers": [1, 0.9, 1.1, 1, 1],
                    "stripe_biases_v": [0, 0],
                    "nonaccelerator_scale": 0.7,
                    "trajectory_quality": 2,
                    "maximum_step_us": 0.05,
                },
            }), encoding="utf-8")
            output, receipt = temporary / "variation.lua", temporary / "variation.json"
            result = materialize_variation(base, overrides, output, receipt)
            self.assertEqual(result["resolved_operating_point"]["mirror_voltages_v"], [0.0, -9.0, 22.0, 30.0, 50.0])
            self.assertEqual(result["resolved_operating_point"]["stripe_biases_v"], [0.0, 0.0])
            self.assertEqual(result["resolved_operating_point"]["prism_voltages_v"], [141.0, 0.0])
            self.assertEqual(result["resolved_operating_point"]["full_path_timeout_us"], 800.0)
            self.assertEqual(result["resolved_operating_point"]["nonaccelerator_scale"], 0.7)
            self.assertEqual(result["resolved_operating_point"]["trajectory_quality"], 2.0)
            self.assertEqual(result["resolved_operating_point"]["maximum_step_us"], 0.05)
            self.assertEqual(result["resolved_operating_point"]["target_oscillation_count"], 25.0)
            self.assertTrue(output.exists())
            invalid = temporary / "invalid.json"
            invalid.write_text(json.dumps({"overrides": {"unknown": 1}}), encoding="utf-8")
            with self.assertRaises(OperatingPointVariationError):
                materialize_variation(base, invalid, temporary / "invalid.lua", temporary / "invalid-receipt.json")

    def test_analytic_l0_l1_receipt_materializes_only_a_run_local_prototype(self) -> None:
        receipt = {
            "status": "l0_l1_voltage_candidate_not_3d_validated",
            "electrode_voltages_v": [0.0, -10.0, 20.0, 30.0, 50.0],
            "mapping": {"stable": True, "gamma_degrees": 90.0},
        }
        with TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            receipt_path = temporary / "l0_l1.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            outputs = materialize(
                PROJECT / "config" / "simion_candidate_two_zone.json", receipt_path, temporary / "run",
            )
            derived = load_contract(outputs["contract"])
            self.assertEqual(derived["mirror"]["design_status"], "analytic_l0_l1_candidate__3d_unvalidated__pa_build_allowed")
            self.assertIn("mirror_voltages_v = { 0, -10, 20, 30, 50 }", outputs["operating_point"].read_text(encoding="utf-8"))
            self.assertIn("detector_box_mm", outputs["operating_point"].read_text(encoding="utf-8"))
            self.assertIn("stripe_biases_v", outputs["operating_point"].read_text(encoding="utf-8"))
            self.assertIn("prism_voltages_v = { 141.42135623730948, 0 }", outputs["operating_point"].read_text(encoding="utf-8"))
            self.assertIn("accelerator_voltages_v", outputs["operating_point"].read_text(encoding="utf-8"))
            self.assertIn(
                "n = 1",
                outputs["mirror_internal_diagnostic_center_fly2"].read_text(encoding="utf-8"),
            )
            self.assertIn(
                "n = 100",
                outputs["mirror_internal_diagnostic_bunch_fly2"].read_text(encoding="utf-8"),
            )
            focus_center = outputs["accelerator_focus_center_fly2"].read_text(encoding="utf-8")
            focus_bunch = outputs["accelerator_focus_bunch_fly2"].read_text(encoding="utf-8")
            placement = derive_two_zone_placement(derived)
            self.assertIn("ke = 0", focus_center)
            self.assertIn("el = -90", focus_center)
            self.assertIn(f"{placement.focus_y_mm:.17g}", focus_center)
            self.assertEqual(focus_bunch.count("standard_beam {"), 100)
            self.assertEqual(focus_bunch.count("n = 1"), 100)
            release_center_z = placement.repeller_z_mm - derived["accelerator"]["release_position_in_gap_1_mm"]
            self.assertIn(f"z = {release_center_z + 0.1:.17g}", focus_bunch)
            self.assertIn(f"z = {release_center_z - 0.1:.17g}", focus_bunch)
            self.assertNotIn("circle_distribution", focus_bunch)
            species = derived["particle_source"]["species"]
            first_prism_entry = outputs["first_prism_entry_center_fly2"].read_text(encoding="utf-8")
            self.assertIn("ke = 4005", first_prism_entry)
            self.assertIn("position = circle_distribution", first_prism_entry)
            self.assertIn("direction = vector(0, 0, -1)", first_prism_entry)
            self.assertEqual(outputs["first_prism_iob_fly2"].read_bytes(), first_prism_entry.encode("utf-8"))
            for key in (
                "mirror_internal_diagnostic_center_fly2",
                "mirror_internal_diagnostic_bunch_fly2",
                "accelerator_focus_center_fly2",
                "accelerator_focus_bunch_fly2",
                "first_prism_entry_center_fly2",
            ):
                source_text = outputs[key].read_text(encoding="utf-8")
                self.assertIn(f"mass = {species['mass_th']:.17g},", source_text)
                self.assertIn(f"charge = {species['charge_e']:.17g},", source_text)
            input_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
            voltage_map = outputs["voltage_map"]
            self.assertEqual(input_manifest["voltage_map"]["filename"], voltage_map.name)
            self.assertEqual(input_manifest["voltage_map"]["sha256"], hashlib.sha256(voltage_map.read_bytes()).hexdigest())
            self.assertEqual(voltage_map.read_bytes(), (PROJECT / "simion" / "candidate_voltage_map.lua").read_bytes())
            cycle_counter = outputs["mirror_cycle_counter"]
            self.assertEqual(input_manifest["mirror_cycle_counter"]["filename"], cycle_counter.name)
            self.assertEqual(
                input_manifest["mirror_cycle_counter"]["sha256"],
                hashlib.sha256(cycle_counter.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                cycle_counter.read_bytes(),
                (PROJECT / "simion" / "mirror_cycle_counter.lua").read_bytes(),
            )
            operating_point = outputs["operating_point"].read_text(encoding="utf-8")
            self.assertIn(
                "mirror_regions_project = { negative = { z_min_mm = -325, z_max_mm = -102 }, "
                "positive = { z_min_mm = 102, z_max_mm = 325 } }, detector_box_mm = {",
                operating_point,
            )
            self.assertIn("source_receipt_sha256", outputs["operating_point"].read_text(encoding="utf-8"))
            self.assertIn(
                "qualification = 'geometry_review_only__unsolved_stripe_and_p2'",
                outputs["operating_point"].read_text(encoding="utf-8"),
            )
            self.assertEqual(
                input_manifest["status"],
                "geometry_review_only__named_diagnostics__full_center_unpublished",
            )
            self.assertEqual(input_manifest["schema_version"], 3)
            self.assertEqual(
                input_manifest["mirror_internal_diagnostic_center_fly2"]["source_profile_id"],
                "mirror_internal_diagnostic",
            )
            self.assertEqual(
                input_manifest["full_mrtof_center_source"],
                {
                    "status": "blocked_pending_coupled_stripe_phase_and_two_prism_finite_3d",
                    "publishable": False,
                    "fly2": None,
                },
            )
            self.assertEqual(outputs["program"].name, "mrtof_candidate.lua")
            program = outputs["program"].read_text(encoding="utf-8")
            self.assertIn("mirror_cycle_counter.new(mirror_regions)", program)
            self.assertNotIn("target_turns", program)
            self.assertNotIn("turns[ion_number] ==", program)
            self.assertTrue(outputs["first_prism_l0_receipt"].exists())
            self.assertIn("first_prism_l0_receipt", input_manifest)
            self.assertIn("first_prism_l0", outputs["operating_point"].read_text(encoding="utf-8"))
            first_prism_program = outputs["first_prism_program"].read_text(encoding="utf-8")
            self.assertIn("MRTOF_FIRST_PRISM_EVENT interface", first_prism_program)
            # The static diagnostic must use IOB-persisted PA0 fields: doing a
            # full PA-family Fast Adjust per integration segment is a severe
            # performance regression and cannot change this frozen point.
            self.assertIn("adjustable runtime_fast_adjust_enable = 0", first_prism_program)
            self.assertIn("if runtime_fast_adjust_enable == 0 then return end", first_prism_program)
            self.assertEqual(outputs["first_prism_operating_point"].read_bytes(), outputs["operating_point"].read_bytes())
            self.assertEqual(outputs["first_prism_voltage_map"].read_bytes(), voltage_map.read_bytes())
            for key in ("first_prism_program", "first_prism_operating_point", "first_prism_voltage_map", "first_prism_iob_fly2"):
                self.assertIn(key, input_manifest)
            derived["simion_geometry_release_status"] = "cad_topology_and_top_level_pose_qualified"
            outputs["contract"].write_text(json.dumps(derived), encoding="utf-8")
            self.assertIn("analytic_l0_l1_candidate__3d_unvalidated__pa_build_allowed", build_full_candidate_gem(outputs["contract"]))

    def test_cad_pose_contract_round_trips_and_places_mechanical_midplane_at_x_zero(self) -> None:
        contract = load_cad_pose_contract(PROJECT / "config" / "cad_to_theory_frame.json")
        # This is a top-level CAD point: its Y coordinate is the mirror
        # reflection axis and its Z=86 mm transverse centre maps to x=0.
        point = (-281.25, -64.416726, 86.0)
        mapped = source_to_project(point, contract)
        self.assertEqual(mapped, (0.0, 123.25, -64.416726))
        self.assertEqual(project_to_source(mapped, contract), point)

    def test_resolved_cad_envelope_applies_component_and_project_transforms(self) -> None:
        frame = load_cad_pose_contract(PROJECT / "config" / "cad_to_theory_frame.json")
        identities = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        names = ["ion foil 1-3", "ion foil 1-4", "ion foil 3-3", "ion foil 3-4"]
        evidence = {
            "assembly_path": "synthetic.SLDASM",
            "components": [
                {"instance_name": name, "part_path": f"{name}.SLDPRT", "suppressed": False,
                 "local_part_box_m": [0.0, 0.03, 0.0, 0.1, 0.04, 0.02],
                 "solidworks_transform_array": identities}
                for name in names
            ],
        }
        manifest = resolve(evidence, frame)
        self.assertEqual(manifest["components"][0]["project_box_mm"], [-86.0, -258.0, 30.0, -66.0, -158.0, 40.0])

    def test_ion_foil_profile_composition_keeps_assembly_and_project_frames_distinct(self) -> None:
        frame = load_cad_pose_contract(PROJECT / "config" / "cad_to_theory_frame.json")
        identity = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        edge = {"edge_index": 1, "bspline": {"order": 4, "periodic": False, "knots": [0.0] * 4 + [1.0] * 4, "control_points_component_m": [[0.0, 0.0, 0.0]] * 4}}
        component = {"instance_name": "set", "source_instance_name": "part-1", "long_bspline_edges": [edge]}
        profile = {"coordinate_frame": "opened Ion-Foil assembly, millimetres", "stripes": [component], "central_ground": component}
        top_level = {"ion_foil_component_poses": [{"local_instance": "part-1", "solidworks_transform_array": identity}]}
        result = compose(profile, top_level, frame)
        self.assertEqual(result["stripes"][0]["long_bspline_edges"][0]["control_points_project_mm"][0], [-86.0, -158.0, 0.0])

    def test_candidate_places_two_zone_focus_at_central_plane(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        energy = derive_operating_energy_envelope(contract)
        focus = derive_two_zone_focus(contract)
        placement = derive_two_zone_placement(contract)
        self.assertGreater(focus.focus_after_exit_mm, 0.0)
        self.assertAlmostEqual(placement.exit_grid_z_mm - focus.focus_after_exit_mm, placement.focus_z_mm)
        self.assertEqual(contract["accelerator"]["focus_project_position_mm"], [0.0, None, 0.0])
        self.assertAlmostEqual(placement.focus_y_mm, 55.328)
        self.assertGreater(placement.repeller_z_mm, placement.grid_1_z_mm)
        self.assertGreater(placement.grid_1_z_mm, placement.exit_grid_z_mm)
        self.assertEqual(energy.net_gain_center_minimum_v, 3500.0)
        self.assertEqual(energy.net_gain_center_maximum_v, 4500.0)
        self.assertEqual(energy.selected_net_gain_center_v, 4000.0)
        self.assertEqual(energy.mirror_energy_nodes_v, (3900.0, 4000.0, 4100.0))
        self.assertEqual(energy.mirror_b_through_d_maximum_v, 3900.0)
        self.assertEqual(energy.post_acceleration_total_energy_reference_v, 4005.0)
        self.assertEqual(focus.energy_per_charge_v, energy.net_gain_reference_center_v)
        lower, upper = derive_mirror_voltage_bounds(contract)
        self.assertEqual(upper, (3900.0, 3900.0, 3900.0, 10000.0))
        self.assertGreater(lower[-1], 4100.0)

    def test_selected_operating_energy_rederives_local_nodes_without_moving_search_bounds(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        energy = derive_operating_energy_envelope(contract, selected_center_v=4200.0)
        self.assertEqual(energy.net_gain_reference_center_v, 4000.0)
        self.assertEqual(energy.selected_net_gain_center_v, 4200.0)
        self.assertEqual((energy.net_gain_center_minimum_v, energy.net_gain_center_maximum_v), (3500.0, 4500.0))
        self.assertEqual(energy.mirror_energy_nodes_v, (4100.0, 4200.0, 4300.0))
        _lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=4200.0)
        self.assertEqual(upper[:3], (4100.0, 4100.0, 4100.0))
        with self.assertRaisesRegex(CandidateContractError, "outside the declared search range"):
            derive_operating_energy_envelope(contract, selected_center_v=4500.1)

    def test_operating_energy_changes_rederive_mirror_nodes_and_voltage_cap(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["accelerator_energy_contract"]["net_gain_reference_center_per_charge_v"] = 4200.0
        contract["nominal"]["energy_per_charge_v"] = 4200.0
        energy = derive_operating_energy_envelope(contract)
        self.assertEqual(energy.mirror_energy_nodes_v, (4100.0, 4200.0, 4300.0))
        _lower, upper = derive_mirror_voltage_bounds(contract)
        self.assertEqual(upper[:3], (4100.0, 4100.0, 4100.0))

    def test_mirror_voltage_cap_rejects_independent_numeric_duplicate(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["mirror"]["theory_requirements"]["voltage_envelope_v"]["D"][
            "maximum_inclusive_v"
        ] = 3900.0
        with self.assertRaisesRegex(CandidateContractError, "B--D maxima"):
            derive_mirror_voltage_bounds(contract)

    def test_split_accelerator_faces_negative_z_and_is_centered_on_declared_y_line(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["simion_geometry_release_status"] = "cad_topology_and_top_level_pose_qualified"
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            gem = build_accelerator_gem(path)
            detector_gem = build_detector_gem(path)
            origins = resolve_split_iob_origins(path)
        self.assertIn("local +z is project +z", gem)
        self.assertIn("global focus=(0,55.328,0)", gem)
        self.assertIn("box3D(-12.5,-12.5,6,12.5,12.5,6)", gem)
        self.assertIn("e(4) { box3D(-22,-20,5.5,22,20,6.5)", gem)
        self.assertIn("e(2) { box3D(-20,-18,45.6,20,18,47.6) }", gem)
        self.assertIn("rear acceleration gaps", gem)
        self.assertAlmostEqual(origins["accelerator"][1], 23.328)
        self.assertAlmostEqual(
            origins["accelerator"][2] + float(contract["accelerator"]["pa_local_margin_z_mm"]),
            derive_two_zone_placement(contract).exit_grid_z_mm,
        )
        self.assertIn("detector PA only", detector_gem)
        self.assertIn("e(25)", detector_gem)
        self.assertEqual(origins["detector"], (-32.0, 30.0, 92.0))

    def test_grid_supports_inherit_ring_thickness_and_both_gems_consume_resolved_frames(self) -> None:
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        contract["simion_geometry_release_status"] = "cad_topology_and_top_level_pose_qualified"
        contract["mirror"]["design_status"] = "analytic_l0_l1_candidate__3d_unvalidated__pa_build_allowed"
        mesh = contract["simion"]["component_mesh_mm_per_gu"]["accelerator"]
        self.assertEqual(mesh, [0.25, 0.25, 0.1])
        self.assertAlmostEqual(contract["accelerator"]["stage_2_rings"]["thickness_z_mm"] / mesh[2], 10.0)
        # Vary the authority, not the emitter: both frames must track every ring.
        for thickness in (1.0, 1.6):
            with self.subTest(thickness_mm=thickness):
                contract["accelerator"]["stage_2_rings"]["thickness_z_mm"] = thickness
                resolved = resolve_geometry(contract)
                placement = derive_two_zone_placement(contract)
                supports = resolved["accelerator_grid_support_frames"]
                self.assertEqual([item["id"] for item in supports], [23, 24])
                self.assertEqual([item["grid_z_mm"] for item in supports],
                                 [placement.grid_1_z_mm, placement.exit_grid_z_mm])
                self.assertEqual((supports[1]["outer_half_x_mm"], supports[1]["outer_half_y_mm"]),
                                 (22.0, 20.0))  # Exactly the grounded enclosure inner wall.
                for support in supports:
                    self.assertAlmostEqual(support["back_z_mm"] - support["front_z_mm"], thickness)
                    self.assertEqual(support["thickness_z_mm"], thickness)
                    self.assertEqual((support["aperture_half_x_mm"], support["aperture_half_y_mm"]),
                                     (12.5, 12.5))
                    self.assertTrue(all(abs(support["grid_z_mm"] - ring["center_z_mm"]) > thickness
                                        for ring in resolved["accelerator_stage_2_rings"]))
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    variants = ((build_full_candidate_gem(path), 0.0, 0),
                                (build_accelerator_gem(path),
                                 contract["accelerator"]["pa_local_margin_z_mm"] - placement.exit_grid_z_mm, 20))
                for gem, offset, id_offset in variants:
                    if id_offset:
                        self.assertIn("contract_mmgu_z = 0.25, 0.25, 0.1", gem)
                    for support in supports:
                        boxes = [list(map(float, match)) for match in re.findall(
                            rf"e\({support['id']-id_offset}\) \{{ box3D\(([^)]+)\)", gem
                        ) for match in [match.split(",")]]
                        self.assertEqual(len(boxes), 2)
                        frame, grid = boxes
                        expected = [-support["outer_half_x_mm"], -support["outer_half_y_mm"],
                                    support["front_z_mm"]+offset, support["outer_half_x_mm"],
                                    support["outer_half_y_mm"], support["back_z_mm"]+offset]
                        for actual, wanted in zip(frame, expected):
                            self.assertAlmostEqual(actual, wanted, places=9)
                        self.assertEqual(grid[0:2], [-12.5, -12.5])
                        self.assertEqual(grid[3:5], [12.5, 12.5])
                        self.assertAlmostEqual(grid[2], support["grid_z_mm"]+offset, places=9)
                        self.assertEqual(grid[2], grid[5])
                        if id_offset:
                            grid_node = (support["grid_z_mm"] + offset) / mesh[2]
                            self.assertAlmostEqual(grid_node, round(grid_node))

    def test_grid_support_rejects_aperture_without_material(self) -> None:
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        contract["accelerator"]["aperture_width_x_mm"] = contract["accelerator"]["electrode_outer_width_x_mm"]
        with self.assertRaisesRegex(CandidateContractError, "support requires positive material"):
            resolve_geometry(contract)

    def test_shared_shielded_accelerator_topology_keeps_exit_contact_and_repeller_gaps(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        placement = derive_two_zone_placement(contract)
        accelerator = contract["accelerator"]
        enclosure = derive_shielded_rectangular_enclosure(
            electrode_outer_width_x_mm=float(accelerator["electrode_outer_width_x_mm"]),
            electrode_outer_height_y_mm=float(accelerator["electrode_outer_height_y_mm"]),
            guard_outer_width_x_mm=float(accelerator["grounded_guard_outer_width_x_mm"]),
            guard_outer_height_y_mm=float(accelerator["grounded_guard_outer_height_y_mm"]),
            guard_wall_thickness_mm=float(accelerator["grounded_guard_wall_thickness_mm"]),
            lateral_clearance_mm=float(accelerator["repeller_to_guard_clearance_mm"]),
            repeller_z_mm=placement.repeller_z_mm,
            repeller_thickness_z_mm=float(accelerator["repeller_thickness_z_mm"]),
            rear_gap_mm=float(accelerator["repeller_to_rear_cap_gap_mm"]),
        )
        self.assertAlmostEqual(enclosure.guard_inner_half_x_mm, 22.0)
        self.assertAlmostEqual(enclosure.guard_inner_half_y_mm, 20.0)
        self.assertAlmostEqual(enclosure.guard_inner_half_x_mm - enclosure.electrode_half_x_mm, 2.0)
        self.assertAlmostEqual(enclosure.guard_inner_half_y_mm - enclosure.electrode_half_y_mm, 2.0)
        self.assertAlmostEqual(
            enclosure.rear_cap_inner_z_mm - (placement.repeller_z_mm + float(accelerator["repeller_thickness_z_mm"])),
            float(accelerator["repeller_to_rear_cap_gap_mm"]),
        )

    def test_mirror_analytic_boundaries_are_derived_from_mechanical_parameters(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        boundaries = derive_mirror_boundaries(contract["mirror"])
        self.assertEqual(boundaries["active_start_z_mm"], [107.0, 167.0, 229.0, 261.0, 291.0])
        self.assertEqual(boundaries["active_end_z_mm"], [162.0, 224.0, 256.0, 286.0, 320.0])
        self.assertEqual(boundaries["analytic_transition_z_mm"], [0.0, 164.5, 226.5, 258.5, 288.5])
        self.assertEqual(boundaries["physical_E_active_end_z_mm"], 320.0)
        self.assertEqual(boundaries["terminal_electrode_plane_z_mm"], 320.0)
        self.assertEqual(boundaries["E_midpoint_z_mm"], 305.5)

    def test_gem_has_five_mirrored_electrodes_and_two_stripe_voltage_pairs(self) -> None:
        gem = build_simion_gem(load_contract(PROJECT / "config" / "simion_candidate_two_zone.json"))
        for electrode_id in range(1, 15):
            self.assertIn(f"e({electrode_id})", gem)
        self.assertIn("surface=none", gem)

    def test_rejects_any_mirror_beam_slot_other_than_30_mm(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["mirror"]["beam_slot_width_mm"] = 31.0
        with self.assertRaises(CandidateContractError):
            build_simion_gem(contract)

    def test_rejects_any_ion_foil_beam_slot_other_than_4_mm(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["dual_stripe"]["beam_slot_width_mm"] = 5.0
        with self.assertRaises(CandidateContractError):
            build_simion_gem(contract)

    def test_resolved_geometry_rejects_a_through_or_missing_ion_foil_slot_bridge(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["dual_stripe"]["beam_slot_y_bridges_mm"]["from_min_y_mm"] = 0.0
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract)

    def test_dual_stripe_l0_has_independent_responses_and_positive_widths(self) -> None:
        result = analyze_dual_stripe_l0(
            load_contract(PROJECT / "config" / "simion_candidate_two_zone.json"),
            (-40.0, 60.0),
        )
        self.assertNotEqual(result["response_matrix_determinant"], 0.0)
        self.assertTrue(math.isfinite(result["response_matrix_condition_number_2"]))
        self.assertGreater(result["physical_width_bounds_mm"]["set_1"][0], 0.0)
        self.assertGreater(result["physical_width_bounds_mm"]["set_2"][0], 0.0)
        self.assertEqual(result["theory_cad_component_mapping"]["high_order_width_response"], "set_1")
        self.assertEqual(result["theory_cad_component_mapping"]["linear_width_response"], "set_2")
        self.assertLess(result["theory_cad_component_mapping"]["linear_width_fit"]["maximum_residual_mm"], 0.002)

    def test_mirror_l0_uses_theory_owned_axis_potential_and_reports_three_points(self) -> None:
        design = MirrorL0Design(
            transverse_half_gap_mm=62.5,
            transition_z_mm=(0.0, 280.405553, 343.405553, 376.405553, 407.405553),
            electrode_voltages_v=(0.0, -600.0, 1200.0, 3000.0, 5200.0),
        )
        # Finite-distance analytic step tails are small but nonzero at z=0.
        self.assertLess(abs(axial_potential_v(0.0, design)), 0.1)
        report = three_point_report(design, (3900.0, 4000.0, 4100.0))
        self.assertEqual(report["energies_v"], [3900.0, 4000.0, 4100.0])
        self.assertEqual(len(report["turning_points_mm"]), 3)
        self.assertEqual(len(report["effective_axial_widths_mm"]), 3)
        self.assertTrue(all(value > 0.0 for value in report["turning_points_mm"]))

    def test_mirror_effective_width_is_derived_from_period_not_terminal_spacing(self) -> None:
        self.assertAlmostEqual(effective_axial_width_mm(4000.0, 641.0 / 4000.0 ** 0.5), 641.0)
        with self.assertRaises(CandidateContractError):
            effective_axial_width_mm(4000.0, 0.0)

    def test_mirror_l0_evaluates_three_local_period_slopes_not_two_period_differences(self) -> None:
        design = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 167.0, 229.0, 261.0, 291.0),
            electrode_voltages_v=(0.0, -500.0, 2000.0, 3500.0, 7000.0),
            terminal_electrode_plane_z_mm=320.0,
            terminal_electrode_voltage_v=7000.0,
        )
        slopes = three_point_normalized_period_slopes_per_v(design, (3900.0, 4000.0, 4100.0), 1.0)
        self.assertEqual(len(slopes), 3)
        self.assertTrue(all(math.isfinite(value) for value in slopes))
        self.assertAlmostEqual(slopes[1], normalized_period_slope_per_v(design, 4000.0, 1.0))
        with self.assertRaises(CandidateContractError):
            normalized_period_slope_per_v(design, 4000.0, 0.0)

    def test_mirror_l0_resolution_budget_derives_50k_full_allocation_slope_gate(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        requirements = contract["mirror"]["theory_requirements"]
        budget = requirements["l0_acceptance_budget"]
        tolerance = derive_mirror_l0_slope_tolerance_per_v(
            budget["minimum_mass_resolution"],
            budget["mirror_time_width_fraction"],
            derive_operating_energy_envelope(contract).mirror_energy_nodes_v,
        )
        self.assertAlmostEqual(tolerance, 1e-7)
        with self.assertRaises(CandidateContractError):
            derive_mirror_l0_slope_tolerance_per_v(50_000, 1.0, (3900.0, 4000.0, 4200.0))

    def test_mirror_l0_does_not_add_an_unsupported_grounded_outer_transition(self) -> None:
        design = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 167.0, 229.0, 261.0, 291.0),
            electrode_voltages_v=(0.0, -500.0, 2000.0, 3500.0, 7000.0),
        )
        self.assertGreater(axial_potential_v(300.0, design), 1000.0)
        self.assertGreater(axial_potential_v(600.0, design), 6500.0)

    def test_mirror_l0_terminal_electrode_image_uses_e_voltage_not_ground(self) -> None:
        design = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 164.5, 226.5, 258.5, 288.5),
            electrode_voltages_v=(0.0, -500.0, 2000.0, 3500.0, 7000.0),
            terminal_electrode_plane_z_mm=320.0,
            terminal_electrode_voltage_v=7000.0,
        )
        self.assertAlmostEqual(axial_potential_v(320.0, design), 7000.0, places=9)

    def test_mirror_l0_voltage_search_never_changes_fixed_geometry(self) -> None:
        transitions = (0.0, 250.0, 300.0, 350.0, 400.0)
        result = optimize_fixed_geometry_voltages(
            62.5, transitions, (-500.0, 1000.0, 2500.0, 6000.0),
            (-2500.0, 1.0, 10.0, 4101.0), (-1.0, 5000.0, 8000.0, 12000.0), 1.0, 1e-3,
            energies_v=(3900.0, 4000.0, 4100.0),
        )
        self.assertTrue(result["geometry_fixed"])
        self.assertEqual(result["transition_z_mm"], list(transitions))
        self.assertIn(result["status"], {
            "l0_voltage_family_member_not_l1_validated",
            "l0_voltage_family_search_residual_above_tolerance",
        })
        self.assertGreater(result["terminal_e_voltage_v"], 4100.0)

    def test_mirror_l0_fixed_e_slice_keeps_the_continuation_coordinate_fixed(self) -> None:
        result = optimize_fixed_geometry_voltages(
            15.0,
            (0.0, 164.5, 226.5, 258.5, 288.5),
            (-4000.0, 4000.0, 6000.0, 8000.0),
            (-10000.0, -10000.0, -10000.0, 4100.001),
            (10000.0, 10000.0, 10000.0, 10000.0),
            1.0,
            1e-8,
            (3900.0, 4000.0, 4100.0),
            fixed_terminal_e_voltage_v=8000.0,
        )
        self.assertEqual(result["fixed_terminal_e_voltage_v"], 8000.0)
        self.assertEqual(result["terminal_e_voltage_v"], 8000.0)
        self.assertEqual(result["electrode_voltages_v"][-1], 8000.0)

    def test_parallel_l0_restarts_preserve_full_envelope_and_every_receipt(self) -> None:
        result = parallel_global_l0_family_search(
            15.0, (0.0, 164.5, 226.5, 258.5, 288.5),
            (-10_000.0, -10_000.0, -10_000.0, 4100.001),
            (10_000.0, 10_000.0, 10_000.0, 10_000.0),
            1.0, 1e-7, (3900.0, 4000.0, 4100.0),
            7, 1, 1, 1, 1, 1e-7, 320.0, 20,
        )
        search = result["parallel_restart_search"]
        self.assertEqual(search["actual_workers"], 1)
        self.assertEqual(search["restart_count"], 1)
        self.assertEqual(len(result["restart_receipts"]), 1)
        self.assertEqual(result["restart_receipts"][0]["transition_z_mm"], [0.0, 164.5, 226.5, 258.5, 288.5])
        json.dumps(result)

    def test_mirror_l0_requires_the_shared_outer_e_cover_voltage_to_retain_all_energy_points(self) -> None:
        with self.assertRaises(CandidateContractError):
            optimize_fixed_geometry_voltages(
                15.0, (0.0, 164.5, 226.5, 258.5, 288.5),
                (-4000.0, 4000.0, 6000.0, 8000.0),
                (-20000.0, 1.0, 2.0, 4000.0), (-1.0, 30000.0, 40000.0, 50000.0), 1.0, 1e-3,
                energies_v=(3900.0, 4000.0, 4100.0),
            )

    def test_mirror_l0_does_not_assume_turning_must_occur_in_e_electrode(self) -> None:
        result = optimize_fixed_geometry_voltages(
            15.0, (0.0, 164.5, 226.5, 258.5, 288.5),
            (-4000.0, 4000.0, 6000.0, 8000.0),
            (-20000.0, 1.0, 2.0, 4101.0), (-1.0, 30000.0, 40000.0, 50000.0), 1.0, 1e-3,
            energies_v=(3900.0, 4000.0, 4100.0),
        )
        self.assertIn(result["status"], {
            "l0_voltage_family_member_not_l1_validated",
            "l0_voltage_family_search_residual_above_tolerance",
        })
        self.assertLess(result["three_point"]["turning_points_mm"][1], 291.0)

    def test_l1_uses_same_direction_sections_and_does_not_fake_gamma_90(self) -> None:
        design = MirrorL0Design(
            transverse_half_gap_mm=62.5,
            transition_z_mm=(0.0, 167.0, 229.0, 261.0, 291.0),
            electrode_voltages_v=(0.0, -822.195161609036, 5462.4465311482, 1264.21580522642, 6994.22600471638),
        )
        mapping = map_at_energy(4000.0, design)
        self.assertAlmostEqual(mapping.determinant, 1.0, places=5)
        self.assertAlmostEqual(mapping.reversibility_difference, 0.0, places=5)
        self.assertFalse(mapping.stable)
        self.assertIsNone(mapping.gamma_degrees)

    def test_l1_screen_only_reports_a_supplied_l0_family_member(self) -> None:
        design = MirrorL0Design(
            transverse_half_gap_mm=62.5,
            transition_z_mm=(0.0, 167.0, 229.0, 261.0, 291.0),
            electrode_voltages_v=(0.0, -822.195161609036, 5462.4465311482, 1264.21580522642, 6994.22600471638),
        )
        result = screen_l1_fixed_geometry(design, (3900.0, 4000.0, 4100.0), 1e-3, 1e-5)
        self.assertEqual(result["electrode_voltages_v"], list(design.electrode_voltages_v))
        self.assertEqual(set(result["maps_by_energy_v"]), {"3900.0", "4000.0", "4100.0"})
        self.assertEqual(result["status"], "l1_screened_unstable")
        self.assertEqual(
            result["phase_averaged_time_aberration_by_energy_v"]["4000.0"]["status"],
            "undefined_unstable_map",
        )

    def test_l1_family_screen_preserves_l0_restart_identity(self) -> None:
        l0_member = {
            "status": "l0_voltage_family_member_not_l1_validated",
            "transverse_half_gap_mm": 15.0,
            "transition_z_mm": [0.0, 164.5, 226.5, 258.5, 288.5],
            "electrode_voltages_v": [0.0, -4666.58728861209, 3854.45058996759, 5570.63144691448, 6011.62494130469],
            "terminal_electrode_plane_z_mm": 320.0,
            "normalized_period_slopes_per_v": [-9.6e-11, 6.0e-11, 2.9e-11],
        }
        result = screen_l1_family(
            {"restart_receipts": [l0_member]}, (3900.0, 4000.0, 4100.0), 1e-3, 1e-5, 1,
        )
        self.assertEqual(result["l0_accepted_count"], 1)
        self.assertEqual(result["l1_stable_count"], 1)
        self.assertEqual(result["family_screens"][0]["l0_restart_index"], 0)
        self.assertEqual(result["provisional_selected_l0_restart_index"], 0)

    def test_l1_gamma_selection_refines_the_l0_family_intersection(self) -> None:
        transitions = (0.0, 164.5, 226.5, 258.5, 288.5)
        lower = MirrorL0Design(
            15.0, transitions,
            (0.0, -5023.59942586938, 3843.7443008434875, 5451.07760326715, 7389.047368771202),
            320.0, 7389.047368771202,
        )
        upper = MirrorL0Design(
            15.0, transitions,
            (0.0, -5085.381874617298, 3842.6593145704064, 5432.991152491298, 7602.996831370076),
            320.0, 7602.996831370076,
        )
        result = continue_fixed_e_l0_family_to_gamma(
            lower, upper,
            (-10_000.0, -10_000.0, -10_000.0, math.nextafter(4100.0, math.inf)),
            (10_000.0, 10_000.0, 10_000.0, 10_000.0),
            (3900.0, 4000.0, 4100.0), 90.0, 1.0, 1e-7,
            0.004, 4e-5, 3, 0.001, 0.001, 60, 500,
        )
        self.assertLessEqual(abs(result["gamma_residual_degrees"]), 0.001)
        self.assertLessEqual(
            max(abs(value) for value in result["l0_receipt"]["normalized_period_slopes_per_v"]),
            1e-7,
        )
        self.assertGreater(abs(result["scalar_brent_seed"]["gamma_residual_degrees"]), 0.001)

    def test_simion_materializer_accepts_only_converged_gamma_family_receipt(self) -> None:
        receipt = {
            "status": "l1_family_continued_to_gamma_target__peak_field_and_3d_validation_pending",
            "gamma_target_continuation": {
                "status": "gamma_target_selected_with_probe_convergence__peak_field_and_3d_validation_pending",
                "gamma_residual_degrees": 1e-8,
                "maximum_gamma_residual_degrees": 0.001,
                "l0_receipt": {"electrode_voltages_v": [0.0, -5000.0, 3800.0, 5400.0, 7500.0]},
                "l1_screen": {"nominal_mapping": {"stable": True, "gamma_degrees": 90.00000001}},
            },
            "gamma_target_probe_convergence": {"status": "pass"},
        }
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "mirror.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertEqual(_candidate_voltages(path), [0.0, -5000.0, 3800.0, 5400.0, 7500.0])
            receipt["gamma_target_probe_convergence"]["status"] = "fail"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                _candidate_voltages(path)

    def test_writer_emits_a_lf_gem_source(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "nested" / "candidate.gem"
            write_gem(PROJECT / "config" / "simion_candidate_two_zone.json", output)
            self.assertTrue(output.is_file())
            self.assertNotIn("\r\n", output.read_text(encoding="utf-8"))

    def test_rejects_wrong_coordinate_frame(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["coordinate_system"]["frame_id"] = "wrong"
        with self.assertRaises(CandidateContractError):
            derive_two_zone_focus(contract)

    def test_rejects_cad_as_the_geometry_authority(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["geometry_authority"]["model"] = "cad_import"
        with self.assertRaises(CandidateContractError):
            build_simion_gem(contract)

    def test_full_candidate_has_all_stable_electrodes_and_native_grids(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["mirror"]["design_status"] = "theory_l0_validated"
        contract["dual_stripe"]["central_ground_outline_status"] = "cad_outline_verified_for_candidate"
        contract["simion_geometry_release_status"] = "cad_topology_and_top_level_pose_qualified"
        contract["mirror"]["inner_face_z_mm"] = 220.405553
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            gem = build_full_candidate_gem(path)
        self.assertIn("surface=none", gem)
        for group in ELECTRODE_IDS.values():
            identifiers = (group,) if isinstance(group, int) else group
            for identifier in identifiers:
                self.assertIn(f"e({identifier})", gem)
        self.assertIn("e(23) { box3D", gem)
        self.assertIn("e(24) { box3D", gem)
        self.assertIn("Theory-derived -z two-zone accelerator", gem)
        self.assertIn("Four physical curved Stripe conductors", gem)
        self.assertIn("notin_inside { box3D(-15,-448,224.405553,15,132,281.405553) }", gem)
        self.assertIn("Stripe-facing 5-mm shields have 4-mm slots", gem)
        self.assertIn("box3D(-62.5,-458,220.405553,62.5,142,225.405553)", gem)
        self.assertIn("notin_inside { box3D(-2,-448,-226.405553,2,132,226.405553) }", gem)
        self.assertIn("box3D(-62.5,-458,438.405553,62.5,142,443.405553)", gem)
        placement = derive_two_zone_placement(contract)
        self.assertIn(f"box3D(-24,-22,{placement.exit_grid_z_mm:.12g}", gem)
        self.assertIn(f"box3D(-20,-18,{placement.repeller_z_mm:.12g}", gem)
        self.assertIn("Whole Ion-Foil-2 with native short cubic", gem)
        self.assertIn("no added bridges", gem)
        self.assertIn("extrude_yz(-12,-2)", gem)
        self.assertIn("extrude_yz(2,12)", gem)
        self.assertIn("Two triangular deflection prisms from the resolved CAD-constrained contract", gem)
        self.assertIn("polyline(3,-97,32,-97,32,97,3,97,3,21,-3,21,-3,-21,3,-21,3,-97)", gem)
        self.assertIn("polyline(42.828,-65,67.828,-90,67.828,-40,42.828,-65)", gem)
        self.assertIn("notin_inside { box3D(-2,6,-97,2,28,97) }", gem)
        self.assertIn("notin_inside { box3D(-2,-3,-40,2,32,40) }", gem)

    def test_default_hardware_contract_refuses_pa_geometry_until_pose_and_l0_are_closed(self) -> None:
        with self.assertRaises(CandidateContractError):
            build_full_candidate_gem(PROJECT / "config" / "simion_candidate_two_zone.json")

    def test_resolved_geometry_has_real_curves_nonoverlapping_stripes_and_bounded_slots(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        resolved = resolve_geometry(contract)
        self.assertEqual(resolved["metadata"]["mirror_slot_width_mm"], 30.0)
        self.assertEqual(resolved["metadata"]["ion_foil_slot_width_mm"], 4.0)
        self.assertEqual(resolved["metadata"]["ion_foil_slot_bridge_from_min_y_mm"], 5.0)
        self.assertEqual(resolved["metadata"]["ion_foil_slot_bridge_from_max_y_mm"], 2.0)
        self.assertGreater(resolved["metadata"]["central_ground_to_stripe_clearance_mm"], 0.0)
        self.assertGreaterEqual(
            resolved["metadata"]["resolved_minimum_interstripe_clearance_mm"],
            resolved["metadata"]["required_minimum_interstripe_clearance_mm"],
        )
        self.assertEqual(len(resolved["central_ground_electrodes"]), 4)
        self.assertEqual(resolved["central_ground_electrodes"][0]["x"], [0.0, 12.0])
        self.assertEqual(resolved["central_ground_electrodes"][1]["x"], [-12.0, 0.0])
        self.assertNotIn("central_ground_bridges", resolved)
        self.assertEqual(resolved["central_ground_slots"][0][:2], [-2.0, -385.0])
        self.assertEqual(resolved["central_ground_slots"][0][3:5], [2.0, 0.0])
        self.assertEqual(resolved["central_ground_slots"][1], [-12.0, -4.0, -22.0, 12.0, 2.0, 22.0])
        self.assertEqual([item["id"] for item in resolved["prism_electrodes"]], [16, 17])
        self.assertEqual([item["id"] for item in resolved["prism_ground_shields"]], [18, 20])
        exit_shield = resolved["prism_ground_shields"][0]
        self.assertEqual(exit_shield["topology"], "single_continuous_frame_with_rectangular_slots")
        self.assertEqual(exit_shield["rectangular_slots_mm"], [[-2.0, 35.0, -100.0, 2.0, 75.0, -30.0]])
        grounded_2 = resolved["prism_ground_shields"][-1]
        self.assertEqual(grounded_2["topology"], "single_continuous_frame_with_cross_aperture")
        self.assertEqual(grounded_2["cross_aperture"], {"x_mm": [-2.0, 2.0], "y_mm": [6.0, 28.0], "z_mm": [-40.0, 40.0], "boolean_operation": "union"})
        self.assertEqual(resolved["detector"]["normal_project"], "+z")
        self.assertEqual(resolved["detector"]["box"], [-25.0, 37.0, 95.0, 25.0, 87.0, 97.0])
        self.assertTrue(resolved["detector"]["separate_pa"])
        self.assertAlmostEqual(resolved["detector"]["box"][1], 37.0)
        self.assertAlmostEqual(resolved["detector"]["box"][3], 25.0)
        self.assertAlmostEqual(resolved["detector"]["box"][4], 87.0)
        self.assertAlmostEqual(resolved["detector"]["box"][5], 97.0)
        self.assertEqual(resolved["metadata"]["detector_to_positive_grounded_mirror_clearance_mm"], 5.0)
        self.assertEqual(resolved["metadata"]["detector_to_central_prism_ground_shield_clearance_y_mm"], 5.0)
        self.assertGreaterEqual(
            resolved["metadata"]["accelerator_guard_to_central_prism_ground_shield_clearance_y_mm"],
            resolved["metadata"]["required_accelerator_guard_to_central_prism_ground_shield_clearance_y_mm"],
        )
        contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        contract["accelerator"]["electrode_outer_height_y_mm"] = 40.0
        contract["accelerator"]["grounded_guard_outer_height_y_mm"] = 48.0
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract)
        self.assertEqual([item["id"] for item in resolved["accelerator_stage_2_rings"]], [26, 27, 28, 29, 30])
        self.assertAlmostEqual(resolved["metadata"]["accelerator_stage_2_ring_pitch_mm"], 5.6)
        self.assertEqual(
            resolved["metadata"]["stripe_curve_pose_model"],
            "theory_bspline_parameterization__native_knot_control_contract",
        )
        self.assertEqual(len(resolved["stripe_electrodes"]), 4)
        self.assertGreater(len(resolved["stripe_electrodes"][0]["polygon_yz_mm"]), 4)
        positive_set_1 = resolved["stripe_electrodes"][0]["polygon_yz_mm"]
        positive_set_2 = resolved["stripe_electrodes"][2]["polygon_yz_mm"]
        self.assertAlmostEqual(max(point[1] for point in positive_set_1), 96.99627727439764)
        self.assertAlmostEqual(max(point[1] for point in positive_set_2), 81.69299032983183)
        # The CAD Ion-Foil aperture is a finite central cut, not two
        # disconnected x-side conductors: 5 mm and 2 mm bridges remain at
        # the respective drift-direction ends of the -390..2 mm body.
        self.assertEqual(resolved["stripe_slot"][1], -385.0)
        self.assertEqual(resolved["stripe_slot"][4], 0.0)
        slot = resolved["mirror_slot"]
        # The physical mirror is 600 mm long along project y, while the
        # mechanically measured active aperture is a bounded 580 mm slot.
        self.assertEqual(contract["mirror"]["length_y_mm"], 600.0)
        self.assertEqual(contract["mirror"]["beam_slot"]["length_y_mm"], 580.0)
        self.assertEqual(slot[:2], [-15.0, -448.0])
        self.assertEqual(slot[3:5], [15.0, 132.0])
        self.assertEqual(resolved["mirror_electrodes"][0]["beam_slot"], [-15.0, -448.0, 106.0, 15.0, 132.0, 163.0])
        # The 30-mm active-electrode aperture ends at the end plates; only
        # the Stripe-facing grounded plate has the narrower 4-mm slot.
        inner_shield_slot = resolved["mirror_inner_shield_slot"]
        self.assertEqual(inner_shield_slot, [-2.0, -448.0, -108.0, 2.0, 132.0, 108.0])
        self.assertEqual(resolved["mirror_electrodes"][0]["box"][2:], [107.0, 62.5, 142.0, 162.0])
        self.assertEqual(len(resolved["mirror_ground_shields"]), 2)
        self.assertEqual(
            [item["role"] for item in resolved["mirror_ground_shields"]],
            ["inner_stripe_facing_4mm_slot", "inner_stripe_facing_4mm_slot"],
        )
        self.assertEqual([item["id"] for item in resolved["mirror_e_closures"]], [5, 10])
        self.assertTrue(resolved["metadata"]["mirror_stripe_clearance_pass"])

    def test_resolved_geometry_rejects_crossing_or_unsampled_stripe_edges(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["dual_stripe"]["theory_profile"]["set_1"]["upper_edge"]["z_mm"] = 40.0
        with self.assertRaises(CandidateContractError):
            resolve_geometry(contract)

    def test_simion_iob_origin_maps_the_node_aligned_physical_frame(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        origin = resolve_simion_iob_origin(contract)
        span_x, span_y, span_z = contract["simion"]["pa_span_mm"]
        placement = derive_two_zone_placement(contract)
        self.assertEqual(origin[:2], (-span_x / 2, -span_y / 2))
        self.assertAlmostEqual(origin[2], -span_z / 2 + placement.exit_grid_z_mm)

    def test_geometry_receipt_fingerprints_only_the_resolved_cross_solver_geometry(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        resolved = resolve_geometry(contract)
        receipt = geometry_receipt(contract)
        self.assertEqual(receipt["resolved_geometry_sha256"], geometry_fingerprint(resolved))
        self.assertEqual(receipt["electrode_ids"]["mirrors"], list(range(1, 11)))
        self.assertEqual(receipt["electrode_ids"]["stripes"], [11, 12, 13, 14])

    def test_run_manifest_binds_pa0_family_to_the_resolved_geometry(self) -> None:
        source_contract_path = PROJECT / "config" / "simion_candidate_two_zone.json"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            receipt_path = root / "resolved_geometry_receipt.json"
            contract = load_contract(source_contract_path)
            contract_path = root / "verified_contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            receipt_path.write_text(json.dumps(geometry_receipt(contract)), encoding="utf-8")
            pa0 = root / "candidate.pa0"
            physical_ids = sorted({
                electrode_id
                for group in ELECTRODE_IDS.values()
                for electrode_id in (group if isinstance(group, tuple) else (group,))
            })
            for suffix in [".pa#", ".pa0", *[f".pa{index}" for index in physical_ids]]:
                pa0.with_suffix(suffix).write_bytes(suffix.encode("ascii"))
            program = root / "candidate.lua"; program.write_text("-- program\n", encoding="utf-8")
            fly2 = root / "candidate.fly2"; fly2.write_text("particles\n", encoding="utf-8")
            manifest = build_manifest(contract_path, receipt_path, pa0, program, fly2, None)
        self.assertEqual(manifest["iob_status"], "not_generated")
        self.assertEqual(manifest["workbench_instance"]["must_load"], "candidate.pa0")
        self.assertEqual(len(manifest["artifacts"]["basis_arrays"]), len(physical_ids))

    def test_active_pa_builder_uses_simion_default_refinement(self) -> None:
        builder = (PROJECT / "simion" / "build_full_candidate_pa.lua").read_text(encoding="utf-8")
        split_iob_builder = (PROJECT / "simion" / "build_split_candidate_iob.lua").read_text(encoding="utf-8")
        split_iob_inspector = (PROJECT / "simion" / "inspect_split_candidate_iob.lua").read_text(encoding="utf-8")
        program = (PROJECT / "simion" / "mrtof_candidate.lua").read_text(encoding="utf-8")
        bunch = (PROJECT / "simion" / "mrtof_candidate.fly2").read_text(encoding="utf-8")
        launcher = (PROJECT / "simion" / "run_iob_flight.lua").read_text(encoding="utf-8")
        self.assertIn("refine{solutions={0}}", builder)
        self.assertIn("refine{solutions={solution}}", builder)
        self.assertNotIn("convergence=", builder)
        self.assertIn("MRTOF_EVENT detector", program)
        self.assertNotIn("adj_elect25", program)
        self.assertNotIn("adjustable V_repeller = 4480", program)
        self.assertIn("wb:load(seed)", split_iob_builder)
        self.assertIn("iob_seed_placeholder_%02d.pa0", split_iob_builder)
        self.assertIn("wb:load(iob)", split_iob_inspector)
        self.assertIn("PARTICLE_FLY_EXECUTED=false", split_iob_inspector)
        self.assertIn("n = 100", bunch)
        self.assertIn("simion.command('fly", launcher)

    def test_event_analysis_retains_losses_and_refuses_small_sample_fwhm(self) -> None:
        events = parse_events(
            "MRTOF_EVENT central_plane ion=1 n=1 t_us=1 x_mm=0 y_mm=0\n"
            "MRTOF_EVENT detector ion=1 t_us=5 x_mm=0 y_mm=285 z_mm=0\n"
            "MRTOF_EVENT terminal ion=1 splat=0 t_us=5 x_mm=0 y_mm=285 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 turns=50 central_crossings=2\n"
            "MRTOF_EVENT terminal ion=2 splat=-1 t_us=5.1 x_mm=0 y_mm=3 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 turns=48 central_crossings=1\n"
        )
        summary = summarize_events(events, target_k=25, reported_splat_count=2, expected_particle_ids=(1, 2))
        self.assertEqual(summary["particle_terminal_count"], 2)
        self.assertEqual(summary["detector_hit_count"], 1)
        self.assertEqual(summary["target_k_count"], 1)
        self.assertEqual(summary["electrode_collision_count"], 1)
        self.assertEqual(summary["splat_code_histogram"], {"-1": 1, "0": 1})
        self.assertTrue(summary["all_losses_retained"])
        self.assertIsNone(summary["detector_tof_fwhm_us"])

    def test_event_analysis_fails_closed_when_simion_reports_unrecorded_splats(self) -> None:
        events = parse_events("MRTOF_EVENT terminal ion=1 splat=-1 t_us=1 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 turns=0 central_crossings=0\n")
        summary = summarize_events(events, target_k=25, reported_splat_count=2, expected_particle_ids=(1, 2))
        self.assertEqual(summary["unrecorded_splat_count"], 1)
        self.assertFalse(summary["all_losses_retained"])
        self.assertEqual(summary["status"], "candidate_not_formal__invalid_event_receipt")


if __name__ == "__main__":
    unittest.main()
