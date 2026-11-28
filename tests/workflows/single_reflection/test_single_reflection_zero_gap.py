"""Direct request4 zero-gap authoring: scientific identity precedes native labels."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.execution.retention import file_record
from msplatform.assembly.resolve_assembly import compile_assembly_layout
from tests.workflows.single_reflection.test_single_reflection_geometry import candidate_300mm_fixture, reframe_parent
from msplatform.backends.simion.geometry import compile_frontend_geometry
from msplatform.components.rf_multipole.design_request_files import compile_design_request
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.backends.simion.accelerator_projection import project_side_opening
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_accelerator_geometry
from msplatform.components.single_reflection_oa_tof.assembly_interface import resolve_assembly_interface
from msplatform.components.single_reflection_oa_tof.electrode_topology import resolve_frontend_field_domain


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def direct_source(*, shell=False, r0=4., quadrupole=False):
    """Change the author version before compilation; never upgrade a resolved fixture."""
    path = Path(__file__).resolve().parents[3] / (
        "src/msplatform/components/rf_multipole/variants/octupole/config/requests/mechanical_base.json")
    author = json.loads(path.read_text(encoding="utf-8"))
    author["schema_version"] = 4
    author["geometry_mm"]["inscribed_radius_r0"] = r0
    if quadrupole:
        author["identity"].update(radial_order_n=2, electrode_count=4)
    if shell:
        author["geometry_mm"]["enclosure"] = dict(model="cylindrical_grounded_shell",
            inner_radius_mm=20., wall_thickness_mm=1., z_min_mm=-2.5, z_max_mm=82.1,
            endcaps=dict(entrance=dict(aperture_radius_mm=3.6, thickness_mm=.5),
                         exit=dict(aperture_radius_mm=3.6, thickness_mm=.5)))
        author["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.)
    return compile_design_request(author, expected_identity=author["identity"])


def direct_inputs(root, sources, *, oa_gap=0., rf_gap=0.):
    """Build component3/plan5/binding2 directly, without native-v1 fixture readers."""
    oatof = candidate_300mm_fixture()
    projection = resolve_accelerator_geometry(oatof, variant_id="three_zone_square")
    repeller = oatof["accelerator_topology"]["planes_global_z_mm"]["repeller"]
    z = repeller + 2.
    domain = dict(cell_mm_xyz=dict(x=.3, y=.25, z=.1),
        pa_bounds_mm=dict(x_min=-999.9, x_max=60., y_min=-80., y_max=80.,
                          z_min=repeller-40., z_max=repeller+310.))
    project_side_opening(projection.local_region,
        side_opening=dict(center_mm=[-122.8, 0., z], width_mm=1., height_mm=4.),
        cell_mm_xyz=domain["cell_mm_xyz"],
        pa_origin_mm={axis: domain["pa_bounds_mm"][axis+"_min"] for axis in "xyz"})
    interfaces = {name: build_assembly_interface(value, geometry_profile_id=None)
                  for name, value in sources.items()}
    interfaces["oatof"] = resolve_assembly_interface(oatof, projection=projection,
        geometry_profile_id=None, schema_version=3)
    instances = [dict(instance_id="oatof", project_id="single_reflection_oa_tof_mass_analyzer",
        transform=dict(schema_version=1, role="rigid_transform", from_frame_id="oatof_global",
            to_frame_id="oatof_global", rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0,0,0]))]
    names = list(sources)
    downstream_x = -122.8
    for name in reversed(names):
        ports = interfaces[name]["ports"]
        gap = oa_gap if name == names[-1] else rf_gap
        tx = downstream_x - ports["mechanical_exit"]["center_mm"][2] - gap
        instances.append(dict(instance_id=name, project_id=sources[name]["identity"]["project_id"],
            transform=dict(schema_version=1, role="rigid_transform",
                from_frame_id=sources[name]["coordinate"]["coordinate_id"], to_frame_id="oatof_global",
                rotation=[[0,0,1],[1,0,0],[0,1,0]], translation_mm=[tx,0,z])))
        downstream_x = tx + ports["mechanical_entrance"]["center_mm"][2]
    connections = []
    for index, name in enumerate(names):
        target = names[index+1] if index+1 < len(names) else "oatof"
        connections.append(dict(connection_id="join_"+name,
            upstream=dict(instance_id=name, port_id="mechanical_exit"),
            downstream=dict(instance_id=target, port_id="side_entry" if target=="oatof" else "mechanical_entrance"),
            gap_mm=oa_gap if target=="oatof" else rf_gap, coupling_mode="monolithic_joint_solve"))
    recipe = dict(schema_version=1, role="assembly_recipe", integration_id="instrument_assembly",
        recipe_id="direct_request4_zero_gap", assembly_frame_id="oatof_global",
        position_tolerance_mm=1e-9, angular_tolerance_rad=1e-9,
        instances=instances, connections=connections)
    maps, records = {}, {}
    for number, (name, value) in enumerate({**sources, "oatof": oatof}.items()):
        keys = (resolve_frontend_field_domain(oatof, projection=projection)["electrode_group_ids"]
                if name=="oatof" else [row["electrode_group_id"] for row in build_electrode_topology(value)])
        maps[name] = {key: 1 + number*100 + index*2 for index, key in enumerate(keys)}
        path = root / name / "resolved_design.json"
        write_json(path, value)
        records[name] = file_record(path)
    return oatof, dict(composition_plan=compile_assembly_layout(recipe, interfaces),
        accelerator_variant="three_zone_square", numerical_domains=dict(parent=domain),
        electrode_bindings=maps, provider_inputs=records)


class DirectZeroGapTests(unittest.TestCase):
    def test_direct_version_chain_and_recessed_grounded_housing(self):
        source = direct_source(shell=True)
        self.assertEqual(source["schema_version"], 4)
        self.assertEqual(source["segmentation"]["axial_acceleration"]["schema_version"], 3)
        table = source["segmentation"]["segmented_rod_array"]
        self.assertEqual(table["schema_version"], 2)
        self.assertEqual(len(table["electrodes"]), 32)
        self.assertTrue(all("electrode_id" not in row for row in table["electrodes"]))
        # Independent author arithmetic: (79.6 - 3*.4)/4 = 19.6; metal ends before housing face.
        spans = sorted({(r["z_min_mm"], r["z_max_mm"]) for r in table["electrodes"]})
        self.assertEqual(len(spans), 4)
        for actual, expected in zip(spans, [(0.,19.6),(20.,39.6),(40.,59.6),(60.,79.6)], strict=True):
            for value, reference in zip(actual, expected, strict=True):
                # Decimal author arithmetic differs from repeated binary64 additions by a few ULPs.
                self.assertAlmostEqual(value, reference, places=12)
        with tempfile.TemporaryDirectory() as directory:
            oatof, options = direct_inputs(Path(directory), {"multipole":source})
            before = copy.deepcopy((source, oatof, options))
            _, geometry = compile_frontend_geometry({"multipole":source}, oatof, **options)
            self.assertEqual(geometry["composition_plan"]["schema_version"], 5)
            self.assertEqual(geometry["backend_electrode_bindings"]["schema_version"], 2)
            self.assertEqual((source, oatof, options), before)

    def test_bare_rod_contact_is_physical_value_error_not_missing_native_id(self):
        with tempfile.TemporaryDirectory() as directory:
            source = direct_source()
            oatof, options = direct_inputs(Path(directory), {"multipole":source})
            # radius2, center radius6: the first rod is outside the unchanged one-mm OA opening.
            for permuted in (False, True):
                changed = copy.deepcopy(options)
                if permuted:
                    changed["electrode_bindings"] = {
                        name:dict(zip(mapping, reversed(list(mapping.values())), strict=True))
                        for name,mapping in changed["electrode_bindings"].items()}
                before = copy.deepcopy(changed)
                with self.subTest(permuted=permuted), self.assertRaisesRegex(ValueError, "contact"):
                    compile_frontend_geometry({"multipole":source}, oatof, **changed)
                self.assertEqual(changed, before)

    def test_two_grounded_housings_join_at_zero_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = dict(first=direct_source(shell=True), second=direct_source(shell=True))
            oatof, options = direct_inputs(Path(directory), sources)
            original = copy.deepcopy((sources, oatof, options))
            # Both rods end2.5mm before their exit face; the entrance face is also recessed.
            # Only the static-ground shell and cap annuli meet at the RF/RF mechanical join.
            _, geometry = compile_frontend_geometry(sources, oatof, **options)
            self.assertEqual([row["gap_mm"] for row in geometry["composition_plan"]["recipe"]["connections"]],
                             [0., 0.])
            self.assertEqual((sources, oatof, options), original)

    def test_rf_to_rf_separation_and_contact(self):
        for second_r0, accepted in ((10., True), (4., False)):
            with self.subTest(second_r0=second_r0), tempfile.TemporaryDirectory() as directory:
                sources = dict(first=direct_source(quadrupole=True),
                               second=direct_source(quadrupole=True, r0=second_r0))
                oatof, options = direct_inputs(Path(directory), sources, oa_gap=1.)
                # Nearest same-angle centers differ9; radii2+5=7, while equal centers contact.
                if accepted:
                    compile_frontend_geometry(sources, oatof, **options)
                else:
                    with self.assertRaisesRegex(ValueError, "contact"):
                        compile_frontend_geometry(sources, oatof, **options)

    def test_native_labels_author_order_and_parent_frame_do_not_change_metal(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = {"multipole":direct_source(shell=True)}
            oatof, options = direct_inputs(Path(directory), sources)
            expected, _ = compile_frontend_geometry(sources, oatof, **options)
            for variation in ("native", "order", "frame", "rotated_frame"):
                changed = copy.deepcopy(options)
                if variation == "native":
                    changed["electrode_bindings"] = {name:dict(zip(mapping, reversed(list(mapping.values())), strict=True))
                                                      for name,mapping in changed["electrode_bindings"].items()}
                elif variation == "order":
                    plan = changed["composition_plan"]
                    plan["recipe"]["instances"].reverse()
                    changed["composition_plan"] = compile_assembly_layout(plan["recipe"], plan["components"])
                elif variation == "frame":
                    changed["composition_plan"] = reframe_parent(changed["composition_plan"], translation=(0.,64.,0.))
                else:
                    changed["composition_plan"] = reframe_parent(changed["composition_plan"],
                        rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)), translation=(0.,64.,0.))
                with self.subTest(variation=variation):
                    actual, _ = compile_frontend_geometry(sources, oatof, **changed)
                    if variation == "native":
                        # Remove only the explicitly transported native labels from the GEM oracle.
                        import re
                        normalize = lambda text: re.sub(r"\be\(\d+\)", "e(N)", text)
                        self.assertEqual({k:normalize(v) for k,v in actual.items()},
                                         {k:normalize(v) for k,v in expected.items()})
                    else:
                        self.assertEqual(actual, expected)

    def test_unknown_and_incomplete_bindings_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = {"multipole":direct_source(shell=True)}
            oatof, options = direct_inputs(Path(directory), sources)
            for kind in ("version", "missing", "boolean", "mixed_array"):
                changed, changed_sources = copy.deepcopy(options), copy.deepcopy(sources)
                if kind == "version": changed["composition_plan"]["schema_version"] = 99
                elif kind == "missing": changed["electrode_bindings"]["multipole"].pop(next(iter(changed["electrode_bindings"]["multipole"])))
                elif kind == "boolean": changed["electrode_bindings"]["multipole"]["grounded_shell"] = True
                else: changed_sources["multipole"]["segmentation"]["segmented_rod_array"]["schema_version"] = 1
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    compile_frontend_geometry(changed_sources, oatof, **changed)

if __name__ == "__main__":
    unittest.main()
