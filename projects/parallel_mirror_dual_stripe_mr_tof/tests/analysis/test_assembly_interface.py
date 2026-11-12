from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import pure_geometry_inputs
"""Complete MR electrode ownership and independent entry-face vectors."""
import copy
import unittest
from functools import lru_cache
from pathlib import Path

from msplatform.contracts.machine_contracts import validate_schema

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface import resolve_assembly_interface
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry import resolve_geometry
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract


@lru_cache(maxsize=1)
def complete_geometry():
    return resolve_geometry(load_contract(Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"), **pure_geometry_inputs(load_contract(Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json")))


def geometry():
    polygon = [[-33, -100], [-77, -100], [-77, 5.3], [-33, 5.3]]
    source = copy.deepcopy(complete_geometry())
    source["prism_ground_shields"][0] = dict(
            id=18, station="accelerator_exit", mechanical_component="grounded_1_single_frame",
            topology="single_continuous_frame_with_rectangular_slots", x=[-12, 12],
            outer_polygon_yz_mm=polygon, body_sections=[dict(x=[-12, 12], polygon_yz_mm=copy.deepcopy(polygon))],
            prism_clearance_polygon_yz_mm=[[-40, -65], [-70, -95], [-70, -35]],
            rectangular_slots_mm=[[-2, -75, -100, 2, -35, 5.3]],
        )
    return source


class PrismEntryInterfaceTests(unittest.TestCase):
    def test_complete_resolved_analyzer_publishes_actual_shared_electrodes(self):
        source = copy.deepcopy(complete_geometry())
        before = copy.deepcopy(source)
        interface = resolve_assembly_interface(source)
        validate_schema(interface, "component_geometry_interface.schema.json")
        identities = [item["component_electrode_id"] for item in interface["component_electrodes"]]
        self.assertEqual(identities, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 25])
        self.assertEqual(source, before)
        self.assertEqual(set(interface["ports"]), {"accelerator_entry"})
        self.assertEqual({item["id"] for item in source["mirror_e_closures"]}, {5, 10})
        for identity in (5, 10, 15):
            self.assertEqual(identities.count(identity), 1)
        shield = next(item for item in source["prism_ground_shields"] if item["station"] == "accelerator_exit")
        slot = shield["rectangular_slots_mm"][0]
        self.assertEqual(interface["ports"]["accelerator_entry"]["center_mm"],
                         [(slot[0] + slot[3]) / 2, (slot[1] + slot[4]) / 2, slot[5]])

    def test_provider_emits_complete_current_groups_from_explicit_authority(self):
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider import resolve_component
        contract = load_contract(Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json")
        authority = pure_geometry_inputs(contract)
        design = {"contract": contract, "accelerator_requirements": authority["accelerator_requirements"],
                  "geometry_profile": authority["geometry_profile"]}
        before = copy.deepcopy(design)
        actual = resolve_component(design, geometry_profile_id=authority["geometry_profile_id"])
        self.assertEqual(design, before)
        self.assertEqual(actual["resolved_design"], complete_geometry())
        interface = actual["assembly_interface"]
        validate_schema(interface, "component_geometry_interface_v3.schema.json")
        self.assertEqual(interface["ports"], resolve_assembly_interface(complete_geometry())["ports"])
        groups = {item["electrode_group_id"] for item in interface["component_electrodes"]}
        self.assertEqual(len(groups), 22)
        self.assertTrue({"positive_stripe_set_1", "negative_stripe_set_1", "positive_stripe_set_2",
                         "negative_stripe_set_2", "positive_mirror_ground_shield",
                         "negative_mirror_ground_shield", "central_ground", "detector"} <= groups)
        for key in ("contract", "accelerator_requirements", "geometry_profile"):
            broken = dict(design)
            broken.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                resolve_component(broken, geometry_profile_id=authority["geometry_profile_id"])
        for profile_id in (None, "", "  ", " wrong "):
            with self.subTest(profile_id=profile_id), self.assertRaises(ValueError):
                resolve_component(design, geometry_profile_id=profile_id)
        missing_shield = copy.deepcopy(actual["resolved_design"])
        missing_shield["mirror_ground_shields"].pop()
        with self.assertRaisesRegex(ValueError, "mirror ground shield"):
            resolve_assembly_interface(missing_shield, geometry_profile_id=authority["geometry_profile_id"], schema_version=3)
        from msplatform.contracts.rigid_transform import RigidTransform
        transform = RigidTransform("orthogonal_accelerator_exit_origin_v1",
            "astral.xyz.reflection_z.drift_y.transverse_x.v2",
            ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), (0., 0., 0.)).to_contract()
        explicit = {**design, "inherited_dual_stripe_topology_contract": copy.deepcopy(contract),
                    "accelerator_to_mr": transform}
        explicit_before = copy.deepcopy(explicit)
        self.assertEqual(resolve_component(explicit, geometry_profile_id=authority["geometry_profile_id"]), actual)
        self.assertEqual(explicit, explicit_before)
        self.assertEqual(RigidTransform.from_contract(transform).to_contract(), transform)
        invalid = copy.deepcopy(explicit)
        invalid["accelerator_to_mr"]["rotation"][0][0] = 2
        with self.assertRaises(ValueError):
            resolve_component(invalid, geometry_profile_id=authority["geometry_profile_id"])

    def test_file_and_memory_contract_admission_agree_on_complete_and_invalid_inputs(self):
        import json
        from tempfile import TemporaryDirectory
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import validate_contract
        contract = load_contract(Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json")
        cases = {"valid": copy.deepcopy(contract)}
        for name in ("project", "count", "width", "energy", "voltage", "source_acceptance"):
            cases[name] = copy.deepcopy(contract)
        cases["project"]["project_id"] = "other"
        cases["count"]["dual_stripe"]["theoretical_response_count"] = 3
        cases["width"]["dual_stripe"]["minimum_width_mm"] = -1
        cases["energy"]["accelerator_energy_contract"]["net_gain_reference_center_per_charge_v"] = -1
        cases["voltage"]["mirror"]["theory_requirements"]["voltage_envelope_v"]["B"]["power_supply_limits_v"]["maximum_inclusive_v"] = -1e99
        cases["source_acceptance"]["accelerator"]["design_source_acceptance"]["axis"] = "invalid"
        with TemporaryDirectory() as temporary:
            for name, case in cases.items():
                with self.subTest(case=name):
                    path = Path(temporary) / f"{name}.json"
                    path.write_text(json.dumps(case), encoding="utf-8")
                    before = copy.deepcopy(case)
                    def outcome(function):
                        try:
                            return ("ok", function())
                        except Exception as error:
                            return (type(error).__name__, str(error))
                    actual = outcome(lambda: validate_contract(case))
                    self.assertEqual(actual, outcome(lambda: load_contract(path)))
                    self.assertEqual(case, before)
                    self.assertEqual(actual[0] == "ok", name == "valid")

    def test_missing_groups_and_invalid_electrical_identities_are_rejected(self):
        for kind in ("missing", "closure", "duplicate", "noninteger", "ground", "detector"):
            source = copy.deepcopy(complete_geometry())
            if kind == "missing":
                source["stripe_electrodes"] = []
            elif kind == "closure":
                source["mirror_e_closures"][0]["id"] = 25
            elif kind == "duplicate":
                source["stripe_electrodes"][0]["id"] = source["mirror_electrodes"][0]["id"]
            elif kind == "noninteger":
                source["stripe_electrodes"][0]["id"] = True
            elif kind == "ground":
                source["central_ground_electrodes"] = []
            else:
                source["detector"]["id"] = 15
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "MR"):
                resolve_assembly_interface(source)

    def test_actual_slot_face_identity_and_no_invented_wall_thickness(self):
        source = geometry()
        before = copy.deepcopy(source)
        interface = resolve_assembly_interface(source)
        validate_schema(interface, "component_geometry_interface.schema.json")
        self.assertEqual(source, before)
        self.assertEqual(interface["variant_id"], "complete_mr_analyzer")
        self.assertIn(dict(component_electrode_id=18, role="prism_ground_shield"), interface["component_electrodes"])
        port = interface["ports"]["accelerator_entry"]
        self.assertEqual(port["center_mm"], [0, -55, 5.3])
        self.assertEqual(port["outward_normal"], [0, 0, 1])
        self.assertIsNone(port["wall_thickness_mm"])
        self.assertEqual(port["cross_section"], dict(shape="rectangle", width_mm=4, height_mm=40,
            width_axis=[1, 0, 0], height_axis=[0, 1, 0]))

    def test_actual_nondefault_slot_width_and_position(self):
        source = geometry()
        slot = source["prism_ground_shields"][0]["rectangular_slots_mm"][0]
        slot[0], slot[3] = -1, 5
        port = resolve_assembly_interface(source)["ports"]["accelerator_entry"]
        self.assertEqual(port["center_mm"], [2, -55, 5.3])
        self.assertEqual(port["cross_section"]["width_mm"], 6)

    def test_nonpenetrating_slot_or_mismatched_body_is_rejected(self):
        for kind in ("front", "back", "body", "clearance"):
            source = geometry()
            shield = source["prism_ground_shields"][0]
            if kind == "front":
                shield["rectangular_slots_mm"][0][5] = 5.2
            elif kind == "back":
                shield["rectangular_slots_mm"][0][2] = -99
            elif kind == "body":
                shield["body_sections"][0]["polygon_yz_mm"][2][1] = 5.2
            else:
                shield["prism_clearance_polygon_yz_mm"][0][1] = 5.3
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "MR E18"):
                resolve_assembly_interface(source)

    def test_missing_ambiguous_and_wrong_frame_fail_at_provider(self):
        for kind in ("missing", "duplicate", "frame"):
            source = geometry()
            if kind == "missing":
                source["prism_ground_shields"] = []
            elif kind == "duplicate":
                source["prism_ground_shields"] *= 2
            else:
                source["frame_id"] = "ip_frame"
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "MR accelerator_exit"):
                resolve_assembly_interface(source)
