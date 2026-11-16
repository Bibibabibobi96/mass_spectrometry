import copy
import importlib.util
import json
import unittest
from pathlib import Path

from msplatform.backends.simion import assembly_geometry as subject
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.backends.simion.mr_geometry import _extrude_polygon_bands

ROOT = Path(__file__).resolve().parents[2]

class NeutralMrPrimitivesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = json.loads((ROOT / 'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        assembly = assemble(fixture['recipe'], {k: resolve_component(v) for k, v in fixture['component_requests'].items()})
        cls.members = [m for m in assembly_geometry_members(dict(composition_plan=assembly.composition_plan,
            components_resolved=assembly.components_resolved, components_source=assembly.components_source)) if m['instance_id'] == 'mrtof']

    def test_actual_all_members_emit_and_keep_identities(self):
        self.assertEqual(len(self.members), 24)
        self.assertEqual(len({m['member_id'] for m in self.members}), 24)
        for member in self.members:
            self.assertTrue(member['source_refs'])
            self.assertTrue(subject._pieces(member['shape'], RigidTransform.from_contract(member['transform']), []))

    def test_all_canonical_polygon_emission_and_bounds(self):
        polygons = []
        def visit(shape, transform):
            kind = shape['kind']
            if kind == 'extruded_yz_polygon':
                polygons.append(shape)
                term, low, high = subject._world_primitive(shape, transform, [])
                self.assertEqual(term, ' '.join(_extrude_polygon_bands(shape['x'], shape['polygon_yz_mm'])))
                ys = [point[0] for point in shape['polygon_yz_mm']]
                zs = [point[1] for point in shape['polygon_yz_mm']]
                self.assertEqual(low, [shape['x'][0], min(ys), min(zs)])
                self.assertEqual(high, [shape['x'][1], max(ys), max(zs)])
            elif kind == 'union':
                for child in shape['parts']:
                    visit(child, transform)
            elif kind == 'difference':
                visit(shape['base'], transform)
                for child in shape['tools']:
                    visit(child, transform)
        for member in self.members:
            visit(member['shape'], RigidTransform.from_contract(member['transform']))
        self.assertEqual(len(polygons), 46)

    def test_canonical_polygon_parity_and_pose(self):
        shape = dict(kind='extruded_yz_polygon', x=[-1, 2], polygon_yz_mm=[[0,0],[2,0],[2,3],[0,3]])
        pose = RigidTransform.from_contract(dict(schema_version=1,role='rigid_transform',from_frame_id='a',to_frame_id='b',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0]))
        term, lo, hi = subject._world_primitive(shape, pose, [])
        self.assertEqual(term, ' '.join(_extrude_polygon_bands(shape['x'], shape['polygon_yz_mm'])))
        self.assertEqual((lo,hi), ([-1,0,0],[2,2,3]))
        shifted=RigidTransform.from_contract(dict(schema_version=1,role='rigid_transform',from_frame_id='a',to_frame_id='b',rotation=[[1,0,0],[0,0,-1],[0,1,0]],translation_mm=[4,5,6]))
        _, shifted_lo, shifted_hi = subject._world_primitive(shape, shifted, [])
        self.assertEqual((shifted_lo, shifted_hi), ([3,2,6],[6,5,8]))
        bad=copy.deepcopy(shape);bad['polygon_yz_mm']=[[0,0],[1,1],[2,2]]
        with self.assertRaises(ValueError): subject._world_primitive(bad,pose,[])
        bad=copy.deepcopy(shape);bad['other']=1
        with self.assertRaises(ValueError): subject._world_primitive(bad,pose,[])
        rotated=RigidTransform.from_contract(dict(schema_version=1,role='rigid_transform',from_frame_id='a',to_frame_id='b',rotation=[[0,1,0],[1,0,0],[0,0,-1]],translation_mm=[0,0,0]))
        with self.assertRaisesRegex(ValueError,'x axis'): subject._world_primitive(shape,rotated,[])


    def test_overlapping_groups_remain_refused(self):
        members = [copy.deepcopy(self.members[0]), copy.deepcopy(self.members[0])]
        members[1]['electrode_group_id'] = 'different_group'
        with self.assertRaisesRegex((ValueError,RuntimeError), 'overlap' if importlib.util.find_spec('cadquery') else 'optional cad-step'):
            subject._render_assembly_members_gem({'composition_plan': {'recipe': {'assembly_frame_id': 'world'}}}, members,
                domain={'frame_id': 'world', 'minimum_mm': [-2000]*3, 'maximum_mm': [2000]*3},
                pitch_mm=1, boundary='native_zero_neumann')

if __name__ == '__main__': unittest.main()
