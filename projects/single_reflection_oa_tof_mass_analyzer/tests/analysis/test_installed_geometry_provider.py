"""Real self-contained geometry authoring and installed provider provenance."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest

from msplatform.examples import load_example
from msplatform.components.single_reflection_oa_tof.provider import resolve_component
from msplatform.components.single_reflection_oa_tof.geometry_contract import resolve_electrode_geometry
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import apply_side_opening, resolve_accelerator_geometry
from msplatform.components.single_reflection_oa_tof.electrode_topology import build_electrode_topology


class InstalledGeometryProviderTests(unittest.TestCase):
    def test_real_example_resolves_complete_three_zone_tof_without_source_sampling(self):
        study = load_example("rf_oatof_functional_v1")
        original = copy.deepcopy(study)
        result = resolve_component(study["component_requests"]["oatof"]["design"])
        resolved, interface = result["resolved_design"], result["assembly_interface"]
        self.assertEqual(interface["schema_version"], 3)
        self.assertEqual(interface["variant_id"], "three_zone_square")
        self.assertEqual(interface["ports"]["side_entry"]["cross_section"]["width_mm"], 3.0)
        self.assertEqual(interface["ports"]["side_entry"]["cross_section"]["height_mm"], 2.8)
        self.assertEqual(resolved["rings"]["accelerator_count"], 20)
        self.assertEqual(resolved["accelerator_topology"]["potentials_v"]["repeller"], 2140.0)
        self.assertEqual(resolved["geometry_mm"]["L_accel"], 300.0)
        for forbidden in ("derived", "simion_runtime", "simion_geometry_build", "simion_detector_marker", "comsol_runtime"):
            self.assertNotIn(forbidden, resolved)
        projection = apply_side_opening(resolve_accelerator_geometry(resolved, variant_id="three_zone_square"), side_opening=resolved["mechanical_side_opening"])
        physical = resolve_electrode_geometry(resolved, accelerator_projection=projection)
        roles = {body["role"] for body in physical["electrodes"]}
        self.assertTrue({"flight_tube_shield", "reflectron_entry_grid", "reflectron_midgrid", "reflectron_backplate", "detector"} <= roles)
        topology = build_electrode_topology(resolved, projection=projection)
        self.assertEqual(len(topology["groups"]), 42)
        ground = next(row for row in topology["groups"] if row["electrode_group_id"] == "common_ground")
        self.assertEqual(len(ground["member_refs"]), 16)
        self.assertEqual({ref for ref in ground["member_refs"] if ref.startswith("/sources/downstream/")}, {"/sources/downstream/flight_tube_shield/geometry", "/sources/downstream/reflectron_entry_grid/geometry", "/sources/downstream/detector/geometry"})
        self.assertEqual(study, original)
        self.assertTrue(resolve_component.__module__.startswith("msplatform.components."))

    def test_tree_independent_pure_provider_does_not_import_backend_or_host(self):
        code = """import json,sys
from msplatform.examples import load_example
from msplatform.components.single_reflection_oa_tof.provider import resolve_component
x=resolve_component(load_example('rf_oatof_functional_v1')['component_requests']['oatof']['design'])
for prefix in ('projects','integrations','common','msplatform.backends','msplatform.execution'):
 assert not any(k==prefix or k.startswith(prefix+'.') for k in sys.modules), prefix
print(json.dumps({'schema':x['assembly_interface']['schema_version'],'module':resolve_component.__module__}))
"""
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, "-I", "-c", code], cwd=root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema"], 3)

    def test_unknown_example_and_conflicting_physical_input_rejected(self):
        with self.assertRaises(ValueError):
            load_example("../rf_oatof_functional_v1")
        design = load_example("rf_oatof_functional_v1")["component_requests"]["oatof"]["design"]
        for mutate in (lambda x: x.update(fake_source={}), lambda x: x["side_opening"].update(width_mm=-1), lambda x: x["three_zone_candidate"]["accelerator_topology"]["planes_global_z_mm"].update(exit=0)):
            bad = copy.deepcopy(design)
            mutate(bad)
            with self.assertRaises(ValueError):
                resolve_component(bad)


if __name__ == "__main__":
    unittest.main()
