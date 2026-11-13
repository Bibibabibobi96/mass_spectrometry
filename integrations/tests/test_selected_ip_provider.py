"""Pure selected-IP provider and actual assembly boundary tests."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.components.dual_pressure_rectilinear_ion_processor.assembly_interface import resolve_assembly_interface
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import select_legacy_physical_design
from msplatform.contracts.machine_contracts import ContractError

ROOT = Path(__file__).resolve().parents[2]


class SelectedIpProviderTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads((ROOT / "projects/dual_pressure_rectilinear_ion_processor/config/baseline.json").read_text(encoding="utf-8"))
        self.baseline["physical_design_selection"] = {"native_grid_mm": 0.1, "native_aux_segments": 60}
        self.request = {"provider_id": "dual_pressure_rectilinear_ion_processor", "design": {"baseline": self.baseline}}

    def test_selected_complete_authority_and_legacy_ports(self):
        before = copy.deepcopy(self.request)
        actual = resolve_component(self.request)
        expected = select_legacy_physical_design(self.baseline, selection_grid_mm=0.1, auxiliary_segments=60)
        self.assertEqual(actual.resolved_design, expected)
        self.assertEqual(self.request, before)
        old = resolve_assembly_interface(expected["projection"])
        self.assertEqual(actual.assembly_interface["ports"], old["ports"])
        self.assertEqual(len(actual.assembly_interface["component_electrodes"]), 15)
        self.assertEqual([x["electrode_group_id"] for x in actual.assembly_interface["component_electrodes"]],
                         [x["name"] for x in expected["projection"]["electrodes"]])
        self.assertEqual(old["schema_version"], 1)
        self.assertNotIn("grid_mm", expected["projection"])

    def test_explicit_selection_and_nondefault_are_enforced(self):
        missing = copy.deepcopy(self.request)
        del missing["design"]["baseline"]["physical_design_selection"]
        with self.assertRaisesRegex(ValueError, "explicit physical design selection"):
            resolve_component(missing)
        changed = copy.deepcopy(self.request)
        changed["design"]["baseline"]["physical_design_selection"] = {"native_grid_mm": 0.2, "native_aux_segments": 20}
        other = resolve_component(changed)
        self.assertEqual(other.resolved_design["selection"], {"native_grid_mm": 0.2, "native_aux_segments": 20})
        self.assertNotEqual(other.resolved_design, resolve_component(self.request).resolved_design)

    def test_real_assembly_revalidates_members_and_interface(self):
        example = json.loads((ROOT / "src/msplatform/examples/rf_oatof_functional_v1.json").read_text(encoding="utf-8"))
        rf = resolve_component(example["component_requests"]["multipole"])
        ip = resolve_component(self.request)
        recipe = copy.deepcopy(example["recipe"])
        recipe["instances"] = [recipe["instances"][0], recipe["instances"][1]]
        rf_instance, ip_instance = recipe["instances"]
        exit_z = rf.assembly_interface["ports"]["mechanical_exit"]["center_mm"][2]
        rf_instance["transform"]["translation_mm"] = [-exit_z, 0, 0]
        ip_instance.update(instance_id="ion_processor", project_id="dual_pressure_rectilinear_ion_processor")
        ip_instance["transform"]["from_frame_id"] = ip.assembly_interface["local_frame_id"]
        recipe["connections"] = [dict(connection_id="mp_ip", upstream=dict(instance_id="multipole", port_id="mechanical_exit"),
                                      downstream=dict(instance_id="ion_processor", port_id="guide_inlet"),
                                      gap_mm=0.0, coupling_mode="monolithic_joint_solve")]
        components = {"multipole": rf, "ion_processor": ip}
        before = copy.deepcopy(recipe)
        result = assemble(recipe, components)
        self.assertIsNotNone(result)
        self.assertEqual(recipe, before)
        for mutate in (lambda x: x._resolved_design["projection"]["electrodes"][0]["solids"].pop(),
                       lambda x: x._assembly_interface["ports"]["guide_inlet"]["center_mm"].__setitem__(0, 1),
                       lambda x: x._assembly_interface["component_electrodes"].pop(),
                       lambda x: x._assembly_interface["component_electrodes"][1].__setitem__("electrode_group_id", "guide_positive")):
            with self.subTest(mutation=mutate):
                bad = copy.deepcopy(ip)
                mutate(bad)
                with self.assertRaises((ContractError, ValueError)):
                    assemble(recipe, {"multipole": rf, "ion_processor": bad})


if __name__ == "__main__":
    unittest.main()
