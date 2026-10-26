"""Pure contract tests for the OA-only paired static-field preparation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import (
    resolve_accelerator_geometry, project_side_opening,
)
from common.integration.resolve_assembly import compile_assembly_layout
from common.contracts.rigid_transform import RigidTransform
from projects.single_reflection_oa_tof_mass_analyzer.analysis.assembly_interface import resolve_assembly_interface
from integrations.tests.test_single_reflection_geometry import candidate_300mm_fixture as three_zone_fixture, reframe_parent
from integrations.workflows.paired_accelerator_static_field.prepare import (
    prepare,
)


def _record(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest().upper()}


class PairedAcceleratorStaticFieldPrepareTests(unittest.TestCase):
    def _request(self, root: Path) -> dict:
        oatof = three_zone_fixture()
        projection = resolve_accelerator_geometry(oatof, variant_id="three_zone_square").local_region
        outer_half = projection["shield_outer_width_mm"] / 2.0
        clearance = 0.2
        box = {
            "x_min": projection["axis_x_mm"] - outer_half - clearance - 10.0,
            "x_max": projection["axis_x_mm"] + outer_half + clearance + 10.0,
            "y_min": -outer_half - clearance - 10.0,
            "y_max": outer_half + clearance + 10.0,
            "z_min": projection["shield_back_z_mm"] - clearance - 10.0,
            "z_max": projection["grid2_z_mm"] + clearance + 10.0,
        }
        # A 0.1 mm grid preserves the explicitly declared box without rounding.
        box = {key: round(value, 1) for key, value in box.items()}
        provider = resolve_accelerator_geometry(oatof, variant_id="three_zone_square")
        opening = dict(center_mm=[projection["negative_x_face_mm"], 0., projection["repeller_front_z_mm"]+2.],
                       width_mm=1., height_mm=4.)
        cells = dict(x=.2,y=.2,z=.2)
        origin = {axis:box[f"{axis}_min"] for axis in "xyz"}
        project_side_opening(provider.local_region,side_opening=opening,cell_mm_xyz=cells,pa_origin_mm=origin)
        interface = resolve_assembly_interface(oatof,projection=provider,geometry_profile_id=None)
        # An explicit inert mechanical peer supplies the parent connection;
        # only the real oaTOF provider is selected for this field comparison.
        peer = copy.deepcopy(interface)
        peer["project_id"] = "test_upstream"
        pose = RigidTransform("oatof_global","oatof_global",((-1.,0.,0.),(0.,-1.,0.),(0.,0.,1.)),
                              (2*opening["center_mm"][0],0.,0.)).to_contract()
        recipe = dict(schema_version=1,role="assembly_recipe",integration_id="instrument_assembly",recipe_id="paired_test",
            assembly_frame_id="oatof_global",position_tolerance_mm=1e-8,angular_tolerance_rad=1e-8,
            instances=[dict(instance_id="peer",project_id="test_upstream",transform=pose),
                       dict(instance_id="oatof",project_id="single_reflection_oa_tof_mass_analyzer",transform=RigidTransform.identity("oatof_global").to_contract())],
            connections=[dict(connection_id="peer_oa",upstream=dict(instance_id="peer",port_id="side_entry"),
                downstream=dict(instance_id="oatof",port_id="side_entry"),gap_mm=0.,coupling_mode="state_handoff")])
        frontend = dict(composition_plan=compile_assembly_layout(recipe,dict(peer=peer,oatof=interface)),
            accelerator_projection=provider.local_region,numerical_domains=dict(parent=dict(cell_mm_xyz=cells,instance_origin_mm=origin)),
            electrode_bindings=dict(oatof=dict(grounded_shield_id=1,accelerator_repeller_id=2,accelerator_grid1_id=3,
                accelerator_intermediate2_id=4,accelerator_grid2_id=5,accelerator_ring_ids=list(range(6,26)))))
        paths = {
            "parent_manifest": root / "parent_manifest.json",
            "frontend_geometry": root / "frontend_geometry.json",
            "oatof_resolved": root / "oatof_resolved.json",
        }
        paths["frontend_geometry"].write_text(json.dumps(frontend) + "\n", encoding="utf-8", newline="\n")
        paths["oatof_resolved"].write_text(json.dumps(oatof) + "\n", encoding="utf-8", newline="\n")
        paths["parent_manifest"].write_text(json.dumps(dict(role="simulation_run_manifest",status="success",
            inputs={key:_record(paths[key]) for key in ("frontend_geometry","oatof_resolved")},outputs=[]))+"\n",encoding="utf-8")
        first_gap = (projection["grid1_z_mm"] + projection["ring_z_mm"][0]) / 2.0
        second_gap = (projection["ring_z_mm"][0] + projection["ring_z_mm"][1]) / 2.0
        return {
            "schema_version": 2,
            "role": "oatof_paired_accelerator_static_field_request",
            "source_records": {name: _record(path) for name, path in paths.items()},
            "accelerator_variant": "three_zone_square",
            "numerical_domain": {
                "pa_bounds_mm": box,
                "cell_mm_xyz": {"x": 0.1, "y": 0.1, "z": 0.1},
                "boundary_policy": "native_zero_neumann",
                "comsol_outer_boundary": "zero_charge",
                "comsol_mesh": {"global_automatic_level": 6,
                    "electrode_boundary_maximum_element_size_mm": 0.5, "electrode_boundary_growth_rate": 1.4},
            },
            "clearance_policy": {"metal_clearance_mm": clearance, "sheet_clearance_mm": clearance},
            "sample_points": [
                {"point_id": 11, "x_mm": projection["axis_x_mm"], "y_mm": 0.0, "z_mm": first_gap},
                {"point_id": 12, "x_mm": projection["axis_x_mm"], "y_mm": 0.0, "z_mm": second_gap},
            ],
        }

    def _write_request(self, root: Path, request: dict) -> Path:
        path = root / "request.json"
        path.write_text(json.dumps(request) + "\n", encoding="utf-8", newline="\n")
        return path

    def _rewrite_frontend(self, request, change):
        path=Path(request["source_records"]["frontend_geometry"]["path"])
        frontend=json.loads(path.read_text())
        change(frontend)
        path.write_text(json.dumps(frontend)+"\n",encoding="utf-8")
        request["source_records"]["frontend_geometry"]=_record(path)
        manifest_path=Path(request["source_records"]["parent_manifest"]["path"])
        manifest=json.loads(manifest_path.read_text())
        manifest["inputs"]["frontend_geometry"]=_record(path)
        manifest_path.write_text(json.dumps(manifest)+"\n",encoding="utf-8")
        request["source_records"]["parent_manifest"]=_record(manifest_path)

    def test_rejects_sources_not_bound_by_declared_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);request=self._request(root)
            path=Path(request["source_records"]["parent_manifest"]["path"])
            manifest=json.loads(path.read_text());manifest["inputs"].pop("oatof_resolved")
            path.write_text(json.dumps(manifest),encoding="utf-8");request["source_records"]["parent_manifest"]=_record(path)
            with self.assertRaisesRegex(ValueError,"does not bind oatof_resolved"):
                prepare(self._write_request(root,request),root/"output")

    def test_requires_explicit_current_boundary_mesh_contract(self):
        invalid = [{"maximum_element_size_mm": .5}]
        valid = dict(global_automatic_level=6, electrode_boundary_maximum_element_size_mm=.5,
                     electrode_boundary_growth_rate=1.4)
        for name, values in (
            ('global_automatic_level', (True, 0, 10, 6.0)),
            ('electrode_boundary_maximum_element_size_mm', (True, 0., -1., float('inf'))),
            ('electrode_boundary_growth_rate', (True, 0., .99, -1., float('nan'))),
        ):
            invalid.extend({**valid, name: value} for value in values)
        invalid.extend({name: value for name, value in valid.items() if name != missing} for missing in valid)
        invalid.append({**valid, 'undeclared': 1})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            for mesh in invalid:
                with self.subTest(mesh=mesh):
                    request['numerical_domain']['comsol_mesh'] = mesh
                    with self.assertRaisesRegex(ValueError, 'COMSOL|comsol_mesh'):
                        prepare(self._write_request(root, request), root/'output')
                    self.assertFalse((root/'output').exists())
            request['schema_version'] = 1
            request['numerical_domain']['comsol_mesh'] = valid
            with self.assertRaisesRegex(ValueError, 'schema'):
                prepare(self._write_request(root, request), root/'output')

    def test_keeps_mechanical_opening_when_new_numerical_grid_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);request=self._request(root)
            plan=prepare(self._write_request(root,request),root/"output")
            aperture=plan["accelerator_geometry"]["accelerator_port_aperture_discretization"]
            self.assertEqual(aperture["mechanical_width_mm"],1.)
            self.assertEqual(aperture["mechanical_height_mm"],4.)
            self.assertEqual(aperture["cell_mm_xyz"],request["numerical_domain"]["cell_mm_xyz"])
            self.assertEqual(plan["composition_plan"]["scope"]["instance_ids"],["oatof"])

    def test_rejects_missing_or_changed_frozen_projection(self):
        for kind in ("missing","changed"):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);request=self._request(root)
                def change(frontend):
                    if kind=="missing":
                        frontend["accelerator_projection"].pop("accelerator_port_aperture_discretization")
                    elif kind=="changed":
                        frontend["accelerator_projection"]["port_center_z_mm"]+=1.
                self._rewrite_frontend(request,change)
                with self.assertRaisesRegex(ValueError,"projection differs"):
                    prepare(self._write_request(root,request),root/"output")

    def test_parent_reference_keeps_paired_local_bodies_and_samples(self):
        results = []
        for change in ({}, dict(translation=(0.,64.,0.)),
                       dict(rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.))),
                       dict(rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)), translation=(35.,64.,-12.))):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                request = self._request(root)
                if change:
                    self._rewrite_frontend(request, lambda frontend: frontend.update(
                        composition_plan=reframe_parent(frontend['composition_plan'], **change)))
                plan = prepare(self._write_request(root,request),root/'output')
                compiled = json.loads(Path(plan['native_geometry_compilation']['geometry_record']['path']).read_text())
                results.append((plan['accelerator_geometry'], plan['static_on_electrode_voltages_v'],
                    Path(plan['sample_points']['path']).read_bytes(),
                    Path(plan['native_geometry_compilation']['gem_record']['path']).read_bytes(),
                    plan['coordinate_frame'], compiled['native_frame_id'], plan['numerical_domain'],
                    plan['composition_plan']['components']['oatof']['ports']['side_entry']))
                self.assertEqual(plan['composition_plan']['assembly_frame_id'], 'laboratory' if change else 'oatof_global')
                self.assertEqual(plan['coordinate_frame'], 'oatof_global')
                self.assertEqual(compiled['native_frame_id'], 'oatof_global')
                if change:
                    pose = next(row['transform'] for row in plan['composition_plan']['recipe']['instances']
                                if row['instance_id'] == 'oatof')
                    self.assertNotEqual(pose, RigidTransform.identity('oatof_global').to_contract())
        self.assertTrue(all(result == results[0] for result in results))

    def test_rejects_repeller_backshield_and_exit_sheet_as_vacuum_samples(self):
        for zone in ("repeller","backshield","exit"):
            with self.subTest(zone=zone),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);request=self._request(root)
                oatof=json.loads(Path(request["source_records"]["oatof_resolved"]["path"]).read_text())
                g=resolve_accelerator_geometry(oatof,variant_id="three_zone_square").local_region
                request["sample_points"][0]["z_mm"]={"repeller":g["repeller_front_z_mm"]-.5*g["repeller_thickness_mm"],
                    "backshield":g["shield_back_z_mm"]+.5*g["shield_wall_mm"],"exit":g["grid2_z_mm"]}[zone]
                with self.assertRaisesRegex(ValueError,"open bore"):
                    prepare(self._write_request(root,request),root/"output")

    def test_compiles_only_oa_provider_on_table_and_common_points_without_native_solver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            with patch("integrations.workflows.single_reflection_flight.geometry.render_physical_gem",
                       side_effect=AssertionError("OA-only GEM must not render an unselected multipole")):
                plan = prepare(self._write_request(root, request), root / "output")

            self.assertEqual(plan["oatof_instance_id"], "oatof")
            self.assertEqual(
                plan["native_geometry_compilation"]["status"], "compiled_gem"
            )
            native=plan["native_geometry_compilation"]
            gem=Path(native["gem_record"]["path"]).read_text()
            geometry=json.loads(Path(native["geometry_record"]["path"]).read_text())
            self.assertIn("pa_define(",gem)
            self.assertNotIn("cylinder(",gem)
            self.assertEqual(geometry["composition_plan"]["scope"]["instance_ids"],["oatof"])
            self.assertEqual(native["grid"]["bounds_mm"],request["numerical_domain"]["pa_bounds_mm"])
            self.assertEqual(geometry["accelerator_projection"],plan["accelerator_geometry"])
            self.assertEqual(native["electrode_bindings"],geometry["electrode_bindings"])
            self.assertEqual(plan["sample_points"]["count"], 2)
            self.assertEqual(len(plan["static_on_electrode_voltages_v"]), 25)
            self.assertEqual(plan["numerical_domain"]["boundary_policy"], "native_zero_neumann")
            self.assertEqual(plan["numerical_domain"]["comsol_outer_boundary"], "zero_charge")
            points = (root / "output" / "paired_accelerator_field_points.csv").read_text(encoding="utf-8")
            self.assertTrue(points.startswith("point_id,x_mm,y_mm,z_mm\n11,"))

    def test_rejects_point_on_ideal_grid_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            oatof = json.loads(Path(request["source_records"]["oatof_resolved"]["path"]).read_text())
            projection = resolve_accelerator_geometry(oatof, variant_id="three_zone_square").local_region
            request["sample_points"][0]["z_mm"] = projection["grid1_z_mm"]
            with self.assertRaisesRegex(ValueError, "ideal grid sheet"):
                prepare(self._write_request(root, request), root / "output")

    def test_rejects_box_that_clips_the_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            request["numerical_domain"]["pa_bounds_mm"]["x_min"] += 100.0
            with self.assertRaisesRegex(ValueError, "clips the OA provider"):
                prepare(self._write_request(root, request), root / "output")

    def test_rejects_changed_frozen_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            path = Path(request["source_records"]["frontend_geometry"]["path"])
            path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(ValueError, "byte count"):
                prepare(self._write_request(root, request), root / "output")


if __name__ == "__main__":
    unittest.main()
