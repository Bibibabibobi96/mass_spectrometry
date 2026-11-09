"""Direct request4 zero-gap authoring: scientific identity precedes native labels."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.write_run_manifest import file_record
from common.integration.resolve_assembly import compile_assembly_layout
from integrations.tests.test_single_reflection_geometry import candidate_300mm_fixture, reframe_parent
from msplatform.backends.simion.geometry import compile_frontend_geometry
from msplatform.workflows.single_reflection_flight.prepare import prepare
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.core.component_port import build_assembly_interface
from projects.rf_multipole_ion_optics.core.electrode_topology import build_electrode_topology
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import (
    project_side_opening, resolve_accelerator_geometry,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.assembly_interface import resolve_assembly_interface
from projects.single_reflection_oa_tof_mass_analyzer.analysis.electrode_topology import resolve_frontend_field_domain


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def direct_source(*, shell=False, r0=4., quadrupole=False):
    """Change the author version before compilation; never upgrade a resolved fixture."""
    path = Path(__file__).resolve().parents[2] / (
        "projects/rf_multipole_ion_optics/variants/octupole/config/requests/mechanical_base.json")
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


def direct_request(root, sources):
    oatof, options = direct_inputs(root / "author", sources)
    author = root / "author"
    plan = author / "plan.json"
    write_json(plan, options["composition_plan"])
    epoch = author / "epoch.json"
    write_json(epoch, dict(instrument_time_us=0.))
    clock = author / "clock.json"
    write_json(clock, dict(schema_version=1, role="canonical_clock_authority",
        clock_epoch_id="instrument_clock_epoch_v1", instrument_time_unit="us",
        canonical_time_basis="instrument_epoch_absolute_time",
        authority=dict(path="inputs/instrument_epoch.json", sha256=file_record(epoch)["sha256"], field="instrument_time_us"),
        solver_local_time_basis="elapsed_time_from_zero_us",
        adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
        handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False))
    release = author / "release.json"
    write_json(release, dict(schema_version=1, role="repository_ion_release", frame_id="oatof_global",
        particle_count=100, mother_particle_count=100, common_time_of_birth_s=42.125e-6,
        geometry=dict(shape="cylinder", center_mm=[3.5,1.25,
            oatof["accelerator_topology"]["planes_global_z_mm"]["repeller"]+2.75],
            axis="z", radius_mm=.05, height_mm=.1), species=dict(mass_amu=524., charge_state=1),
        sampling=dict(strategy="center_first_halton_cylinder_v1",
            kinetic_energy=dict(center_ev=2., full_width_ev=.2), nominal_direction=[1.,2.,3.], angular_full_width_deg=5.)))
    domains = copy.deepcopy(options["numerical_domains"])
    domains["parent"]["refine_convergence_v"] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
    request = dict(schema_version=10, role="instrument_assembly_single_reflection_preparation_request",
        pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1",
        numerics=dict(boundary_policy="native_zero_neumann", rf_reference_voltage_v=10000., frontend_domains=domains),
        composition_plan=file_record(plan), providers=dict(instances={
            name: dict(resolved_design=record, electrode_bindings=options["electrode_bindings"][name],
                **(dict(geometry=dict(accelerator_variant="three_zone_square")) if name=="oatof" else {}))
            for name, record in options["provider_inputs"].items()}),
        source=dict(kind="release_spec", instance_id="oatof", release_spec=file_record(release),
                    clock_authority=file_record(clock), instrument_epoch=file_record(epoch)))
    path = author / "request.json"
    write_json(path, request)
    run = root / "run"
    (run / "inputs").mkdir(parents=True)
    return path, run


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

    def test_actual_public_prepare_positive_and_negative_keep_full_birth_population(self):
        for shell in (True, False):
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as directory:
                path, run = direct_request(Path(directory), {"multipole":direct_source(shell=shell)})
                before = {p:p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
                if shell:
                    receipt = prepare(path, run)
                    self.assertEqual(receipt["particle_count"], 100)
                    with (run/"inputs/projected_source.csv").open(encoding="utf-8-sig", newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), 100)
                    self.assertEqual({float(r["instrument_time_us"]) for r in rows}, {42.125})
                else:
                    with self.assertRaisesRegex(ValueError, "contact"):
                        prepare(path, run)
                    self.assertFalse((run/"inputs/projected_source.csv").exists())
                self.assertEqual({p:p.read_bytes() for p in before}, before)


if __name__ == "__main__":
    unittest.main()
