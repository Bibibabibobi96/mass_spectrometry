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