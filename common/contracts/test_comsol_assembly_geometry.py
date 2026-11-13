"""Pure COMSOL assembly projection, without native model or physics."""
import copy
import unittest
from unittest.mock import patch
from common.contracts.test_geometry_members import real_snapshot
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry


class ComsolAssemblyGeometryTests(unittest.TestCase):
    def test_real_complete_assembly_joins_neutral_members_without_mutation(self):
        snapshot=real_snapshot();before=copy.deepcopy(snapshot)
        projected=project_assembly_geometry(snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
        self.assertEqual(snapshot,before)
        self.assertEqual(projected['members'],list(assembly_geometry_members(snapshot)))
        self.assertEqual(projected['assembly_frame_id'],snapshot['composition_plan']['assembly_frame_id'])
        self.assertEqual(sum(len(row['member_ids']) for row in projected['electrode_groups']),len(projected['members']))
        self.assertNotIn('boundary_input',projected);self.assertNotIn('numerics_input',projected)

    def test_invalid_box_clipping_unsupported_shape_and_pose_fail(self):
        snapshot=real_snapshot();good={'min':[-10000]*3,'max':[10000]*3}
        for box in ({'min':[0,0,0],'max':[0,1,1]}, {'min':[0,0,0],'max':[1,1,1]}, {'min':[0,0],'max':[1,1,1]}):
            with self.subTest(box=box),self.assertRaises(ValueError):project_assembly_geometry(snapshot,outer_box_mm=box)
        members=list(assembly_geometry_members(snapshot));bad=copy.deepcopy(members);bad[0]['shape']['kind']='unsupported'
        with patch('msplatform.backends.comsol.assembly_geometry.assembly_geometry_members',return_value=bad):
            with self.assertRaisesRegex(ValueError,'unsupported COMSOL'):project_assembly_geometry(snapshot,outer_box_mm=good)
        bad=copy.deepcopy(members);bad[0]['transform']['rotation']=[[.5,.5,0],[.5,-.5,0],[0,0,1]]
        with patch('msplatform.backends.comsol.assembly_geometry.assembly_geometry_members',return_value=bad):
            with self.assertRaisesRegex(ValueError,'axis-permutation'):project_assembly_geometry(snapshot,outer_box_mm=good)

class ComsolOaMrPolygonTests(unittest.TestCase):
    """Use the complete canonical OA–MR consumer without a native solver."""

    def test_public_request_retains_complete_oa_mr_members_and_groups(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_mr_provider_trial_transport import _plans
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority
        from msplatform.assembly.factory import assemble
        from msplatform.backends.comsol.geometry_execution import resolve_geometry_request
        from msplatform.components.catalog import resolve_component

        _, plan, contract = _plans()
        authority = geometry_authority(contract)
        oa = resolve_component({'provider_id': 'orthogonal_accelerator',
            'design': {'requirements': authority['accelerator_requirements'], 'geometry_profile': authority['geometry_profile']},
            'geometry_profile_id': authority['geometry_profile_id']})
        mr = resolve_component({'provider_id': 'parallel_mirror_dual_stripe_mr_tof',
            'design': {'contract': contract, 'accelerator_requirements': authority['accelerator_requirements'],
                       'geometry_profile': authority['geometry_profile']},
            'geometry_profile_id': authority['geometry_profile_id']})
        instrument = assemble(plan['recipe'], {name: (oa if row['project_id'] == 'orthogonal_accelerator' else mr)
                                              for name, row in plan['components'].items()})
        before = copy.deepcopy(dict(composition_plan=instrument.composition_plan,
            components_resolved=instrument.components_resolved, components_source=instrument.components_source))
        expected_members = list(assembly_geometry_members(before))
        request = resolve_geometry_request(instrument, outer_box_mm={'min': [-10000]*3, 'max': [10000]*3},
                                           geometry_validation={'position_mm': 1e-6, 'normal_abs': 1e-9})
        self.assertEqual(request['assembly'], before)
        self.assertEqual(request['projection']['members'], expected_members)
        self.assertEqual(len(expected_members), 45)
        expected_groups = {(row['instance_id'], row['electrode_group_id']) for row in expected_members}
        actual_groups = {(row['instance_id'], row['electrode_group_id']) for row in request['projection']['electrode_groups']}
        self.assertEqual(actual_groups, expected_groups)
        self.assertEqual(len(actual_groups), 41)
        self.assertEqual(sum(len(row['member_ids']) for row in request['projection']['electrode_groups']), 45)
        self.assertEqual(dict(composition_plan=instrument.composition_plan, components_resolved=instrument.components_resolved,
                              components_source=instrument.components_source), before)
        poses = {row['instance_id']: row['transform'] for row in plan['recipe']['instances']}
        self.assertTrue(all(row['transform'] == poses[row['instance_id']] for row in expected_members))

    def test_exact_polygon_degeneracy_and_closure(self):
        from msplatform.backends.comsol.assembly_geometry import _supported
        shape = {'kind': 'extruded_yz_polygon', 'x': [-2, 3], 'polygon_yz_mm': [[0, 0], [1, 0], [0, 1]]}
        for points in ([[0, 0], [1, 1], [2, 2]], [[1, 1], [1, 1], [1, 1]], [[0, 0], [1, 0], [0, 0]]):
            with self.subTest(points=points), self.assertRaisesRegex(ValueError, 'degenerate'):
                _supported(dict(shape, polygon_yz_mm=points), ideal=False)
        for points in ([[0, 0], [1, 0], [0, 1], [0, 0]], [[0, 0], [1, 0], [0, 1e-20]]):
            with self.subTest(points=points):
                _supported(dict(shape, polygon_yz_mm=points), ideal=False)
        with self.assertRaises(ValueError):
            _supported(shape, ideal=True)

    def test_polygon_signed_pose_and_clipping_refusal(self):
        from msplatform.backends.comsol.assembly_geometry import _world_bounds
        shape = {'kind': 'extruded_yz_polygon', 'x': [-2, 3], 'polygon_yz_mm': [[-1, 2], [4, 2], [0, 7]]}
        member = {'shape': shape, 'transform': {'rotation': [[0, 0, 1], [1, 0, 0], [0, 1, 0]],
                                                 'translation_mm': [10, 20, 30]},
                  'representation_role': 'physical_solid', 'instance_id': 'mr',
                  'electrode_group_id': 'g', 'member_id': 'p'}
        before = copy.deepcopy(member)
        self.assertEqual(_world_bounds(member), ([12, 18, 29], [17, 23, 34]))
        self.assertEqual(member, before)
        snapshot = {'composition_plan': {'assembly_frame_id': 'world'}}
        with patch('msplatform.backends.comsol.assembly_geometry.assembly_geometry_members', return_value=[member]):
            accepted = project_assembly_geometry(snapshot, outer_box_mm={'min': [0, 0, 0], 'max': [40, 40, 40]})
            self.assertEqual(accepted['members'], [before])
            with self.assertRaisesRegex(ValueError, 'clips or touches'):
                project_assembly_geometry(snapshot, outer_box_mm={'min': [12, 0, 0], 'max': [40, 40, 40]})
            member['transform']['rotation'] = [[.5, .5, 0], [.5, -.5, 0], [0, 0, 1]]
            with self.assertRaisesRegex(ValueError, 'axis-permutation'):
                project_assembly_geometry(snapshot, outer_box_mm={'min': [0, 0, 0], 'max': [40, 40, 40]})
