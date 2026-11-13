"""Declared dual-cone physical members, explicit Assembly and STEP projection."""
import copy
import json
import math
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from msplatform import assembly, components
from msplatform.contracts.rigid_transform import RigidTransform, FramedPosition
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.exporters.step import step_member_names


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'projects/dual_cone_tandem_quadrupole_ion_interface/config'


def source():
    return json.loads((CONFIG / 'baseline.json').read_text(encoding='utf-8'))


def instrument():
    part = components.resolve_component(dict(provider_id='dual_cone_tandem_quadrupole', design=source()))
    pose = RigidTransform(part.assembly_interface['local_frame_id'], 'cad_lab',
                          ((0, 1, 0), (0, 0, -1), (-1, 0, 0)), (12, -7, 31))
    recipe = dict(schema_version=1, role='assembly_recipe', integration_id='instrument_assembly',
        recipe_id='declared_dual_cone_cad', assembly_frame_id='cad_lab',
        position_tolerance_mm=1e-9, angular_tolerance_rad=1e-12,
        instances=[dict(instance_id='interface', project_id=part.assembly_interface['project_id'],
                        transform=pose.to_contract())], connections=[])
    result = assembly.assemble(recipe, {'interface': part})
    return result


def snapshot():
    value = instrument()
    return dict(composition_plan=value.composition_plan, components_resolved=value.components_resolved,
                components_source=value.components_source)


class DualConeCadTests(unittest.TestCase):
    def test_component_shell_profile_preserves_original_flat_c0_gem_bytes(self):
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
        from msplatform.backends.simion.dual_cone_geometry import render_gem

        numerics = json.loads((CONFIG/'simion_solver_numerics.json').read_text())
        goldens = [('default', '1fbcff566a2f2e0ca18fae896cc71a9836eea3b1a2ffdcc479aaf24faef49051'),
                   ('first_angle_130', '3fe65e54143d99c6d905c34e4171bcc2d480cc7db3e699ef6044f71ca3fc5b86'),
                   ('second_wall_0_7', '840c7d5d8d92c53b6a392ae2c6c799877a1bc3e8760a2e9dbb3e1b16a82e83f0')]
        for case, expected in goldens:
            baseline = source()
            if case == 'first_angle_130':
                baseline['geometry_mm']['first_cone']['included_angle_deg'] = 130
            if case == 'second_wall_0_7':
                baseline['geometry_mm']['second_cone']['wall_normal_thickness_mm'] = .7
            with self.subTest(case=case):
                self.assertEqual(hashlib.sha256(render_gem(resolve_geometry(baseline), numerics).encode()).hexdigest(), expected)

    def test_eleven_physical_members_seven_groups_and_only_real_aperture_ports(self):
        original = source()
        part = components.resolve_component(dict(provider_id='dual_cone_tandem_quadrupole', design=original))
        self.assertEqual(original, source())
        self.assertEqual(part.source_design, original)
        interface = part.assembly_interface
        self.assertEqual(len(interface['component_electrodes']), 7)
        self.assertEqual(set(interface['ports']), {'axial_entry', 'axial_exit'})
        self.assertEqual(interface['ports']['axial_entry']['center_mm'], [0, 0, 0])
        self.assertEqual(interface['ports']['axial_entry']['cross_section']['radius_mm'], 1)
        self.assertIsNone(interface['ports']['axial_entry']['wall_thickness_mm'])
        self.assertEqual(interface['ports']['axial_exit']['center_mm'][2], 110.72)
        value = snapshot()
        before = copy.deepcopy(value)
        members = assembly_geometry_members(value)
        self.assertEqual(len(members), 11)
        self.assertEqual(len({row['electrode_group_id'] for row in members}), 7)
        self.assertTrue(all(row['representation_role'] == 'physical_solid' for row in members))
        self.assertFalse(any('enclosure' in row['member_id'] or 'pump' in row['member_id'] for row in members))
        self.assertEqual(value, before)
        names = step_member_names(value, members)
        self.assertEqual(len(set(names.values())), 11)
        self.assertEqual(names[('interface', 'first_cone')], 'interface.first_cone')
        self.assertEqual(names[('interface', 'stage_1/rod_0001')], 'interface.stage_1.rod_0001')

    def test_cad_groups_match_existing_prepared_model_scientific_identity(self):
        from common.contracts.test_dual_cone_stages import CLOCK
        from msplatform.backends.simion.dual_cone_stages import plan_geometry_stage, plan_model_stage
        from msplatform.backends.simion.model import RF_PHYSICS

        part = instrument().components['interface']
        numerics = json.loads((CONFIG/'simion_solver_numerics.json').read_text())
        science = json.loads((CONFIG/'ion_transport_science.json').read_text())
        geometry = plan_geometry_stage(resolved=part.resolved_design, numerics=numerics)['projection']
        model = plan_model_stage(geometry, electric_field=science['electric_field'], clock=CLOCK, physics=RF_PHYSICS)['projection']
        expected = {row['electrode_group_id'] for row in model['native_drive_rows']}
        actual = {row['electrode_group_id'] for row in assembly_geometry_members(snapshot())}
        self.assertEqual(actual, expected)
        self.assertEqual({row['electrode_group_id'] for row in part.assembly_interface['component_electrodes']}, expected)

    def test_shell_normal_thickness_and_declared_cone_following_cut_are_independent_of_pa(self):
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry_members import cone_shell_profile, stage_1_cut_profile
        value = instrument().components_resolved['interface']
        geometry = value['geometry_mm']
        for name in ('first_cone', 'second_cone'):
            cone = geometry[name]
            points = cone_shell_profile(cone, 23.5)
            angle = math.radians(cone['half_angle_deg'])
            self.assertAlmostEqual((points[0][1] - points[-1][1]) * math.cos(angle), cone['wall_normal_thickness_mm'])
            self.assertEqual(points[1][1], 23.5)
            self.assertEqual(points[2][1], 23.5)
            self.assertLess(points[1][0], points[2][0])
        triangle = stage_1_cut_profile(value)
        base = geometry['second_cone']['aperture_reference_z_mm'] + 1.6
        slope = math.tan(math.radians(geometry['second_cone']['half_angle_deg']))
        self.assertEqual(triangle[0], (base, 0))
        self.assertAlmostEqual(triangle[2][1], (triangle[2][0] - base) * slope)
        members = assembly_geometry_members(snapshot())
        first_rod = next(row for row in members if row['member_id'] == 'stage_1/rod_0001')
        self.assertEqual(first_rod['shape']['kind'], 'intersection')
        self.assertEqual(first_rod['shape']['parts'][1]['points_zr_mm'], triangle)
        self.assertTrue(all('numerics' not in pointer and 'workbench' not in pointer for row in members for pointer in row['source_refs']))

    def test_single_proper_pose_is_retained_without_numerical_embedding(self):
        value = snapshot()
        for member in assembly_geometry_members(value):
            transform = RigidTransform.from_contract(member['transform'])
            point = transform.transform_position(FramedPosition(transform.from_frame_id, (1, 2, 3)))
            self.assertEqual(point.coordinates_mm, (14, -10, 30))
            self.assertEqual(transform.translation_mm, (12, -7, 31))
        before = copy.deepcopy(value)
        value['components_source']['interface']['geometry_mm']['first_cone']['aperture_diameter_mm'] += .1
        with self.assertRaisesRegex(ValueError, 'differs from its explicit source'):
            assembly_geometry_members(value)
        self.assertEqual(before['components_resolved'], value['components_resolved'])

    def test_unknown_profile_and_degenerate_revolved_shape_fail_without_engine(self):
        from msplatform.exporters.step import _validate_shape
        with self.assertRaisesRegex(ValueError, 'unknown dual-cone'):
            components.resolve_component(dict(provider_id='dual_cone_tandem_quadrupole', design=source(), geometry_profile_id='invented'))
        for shape in (dict(kind='revolved_profile', points_zr_mm=[(0, 0), (1, 0), (2, 0)]),
                      dict(kind='revolved_profile', points_zr_mm=[(0, -1), (1, 0), (2, 1)])):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                _validate_shape(shape)

    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional CadQuery engine unavailable')
    def test_actual_step_cold_eleven_bodies_labels_and_declared_cut_probe(self):
        from common.contracts.test_step_export import StepExportTests
        from msplatform.exporters.step import export_assembly_step, inspect_assembly_step

        value = snapshot()
        before = copy.deepcopy(value)
        transform = RigidTransform.from_contract(value['composition_plan']['recipe']['instances'][0]['transform'])
        local_probes = [('first_aperture', (0, 0, 0), False),
                        ('second_aperture', (0, 0, 3), False),
                        ('plate_aperture', (0, 0, 110.47), False),
                        ('plate_metal', (10, 0, 110.47), True),
                        ('flat_c0_is_not_declared_cut', (5.62, 0, 4.7), False)]
        probes = [dict(probe_id=name, point_mm=list(transform.transform_position(
            FramedPosition(transform.from_frame_id, point)).coordinates_mm)) for name, point, _ in local_probes]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'declared dual cone.step'
            report = export_assembly_step(value, destination=path, representation='physical_solids',
                                         options=dict(write_pcurves=True, precision_mode=0))
            cold = StepExportTests()._cold_product_names(path)
            self.assertEqual(cold['solid_count'], 11)
            self.assertEqual(len(cold['members']), 11)
            self.assertTrue(all(row['valid'] and row['solids'] == 1 for row in cold['members']))
            self.assertEqual({row['name'] for row in cold['members']},
                             {row['step_name'] for row in report['exported_members']})
            inspection = inspect_assembly_step(path, assembly=value, export_report=dict(
                schema_version=1, role='owned_assembly_step_export', projection=report), probes=probes)
            self.assertEqual(inspection['status'], 'consistent', inspection)
            self.assertEqual([row['actual_step_inside'] for row in inspection['probes']],
                             [inside for _, _, inside in local_probes])
            self.assertLessEqual(abs(inspection['volume_residual_mm3']), inspection['volume_serialization_bound_mm3'])
            self.assertEqual(value, before)
