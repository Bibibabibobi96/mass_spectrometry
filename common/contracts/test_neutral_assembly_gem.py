"""Neutral GEM serializer contracts; no native SIMION execution."""
import copy
import unittest
from unittest.mock import patch
from msplatform.backends.simion.assembly_geometry import render_assembly_gem


def member(instance, group, name, shape, translation=(0,0,0), rotation=((1,0,0),(0,1,0),(0,0,1))):
    return dict(instance_id=instance,electrode_group_id=group,member_id=name,source_refs=['/shape'],
        representation_role='physical_solid',shape=shape,transform=dict(schema_version=1,role='rigid_transform',
        from_frame_id='local',to_frame_id='world',rotation=[list(r) for r in rotation],translation_mm=list(translation)))


class NeutralAssemblyGemTests(unittest.TestCase):
    def setUp(self):
        self.assembly={'composition_plan':{'recipe':{'assembly_frame_id':'world'}}}
        self.domain={'frame_id':'world','minimum_mm':[-20,-20,-20],'maximum_mm':[20,20,20]}
        self.box={'kind':'box','center_mm':[0,0,0],'size_mm':[2,4,6]}
        self.cylinder={'kind':'cylinder','center_mm':[0,0,0],'radius_mm':1,'height_mm':4}
        self.members=[member('b','cylinder','rod',self.cylinder,(8,0,0)),member('a','box','solid',self.box,(-8,0,0))]

    def render(self, members=None, **kwargs):
        with patch('msplatform.backends.simion.assembly_geometry.assembly_geometry_members',return_value=copy.deepcopy(self.members if members is None else members)):
            return render_assembly_gem(self.assembly,domain=kwargs.get('domain',self.domain),pitch_mm=kwargs.get('pitch_mm',1),boundary=kwargs.get('boundary','grounded_faces'))

    def test_mapping_pose_header_and_source_witness(self):
        before=copy.deepcopy((self.assembly,self.members));result=self.render()
        self.assertEqual((self.assembly,self.members),before)
        self.assertEqual(result['dimensions'],[41,41,41]);self.assertEqual([r['instance_id'] for r in result['electrode_mapping']],['a','b'])
        self.assertIn('locate(20,20,20)',result['gem']);self.assertIn('centered_box3D(-8,0,0,2,4,6)',result['gem'])
        self.assertIn('locate(8,0,2) { cylinder(0,0,0,1,,4) }',result['gem']);self.assertIn('e(0)',result['gem'])
        self.assertEqual(result['members'][0]['source_refs'],['/shape']);self.assertEqual(result['members'][0]['member_id'],'rod')
        other=self.render(list(reversed(self.members)));self.assertEqual(result['gem'],other['gem']);self.assertEqual(result['electrode_mapping'],other['electrode_mapping'])
        changed=copy.deepcopy(self.members);changed[1]['shape']['size_mm'][0]=4;self.assertNotEqual(result['gem_sha256'],self.render(changed)['gem_sha256'])
        renamed=copy.deepcopy(self.members);renamed[0]['instance_id']='c';self.assertEqual(self.render(renamed)['members'][0]['instance_id'],'c')

    def test_union_difference_and_signed_permutation(self):
        rotation=((0,-1,0),(1,0,0),(0,0,1));shape={'kind':'difference','base':{'kind':'union','parts':[self.box,{'kind':'box','center_mm':[4,0,0],'size_mm':[2,2,2]}]},'tools':[self.cylinder]}
        result=self.render([member('x','group','complex',shape,rotation=rotation)],boundary='native_zero_neumann')
        self.assertEqual(result['gem'].count('notin_inside_or_on'),2);self.assertIn('centered_box3D(0,0,0,4,2,6)',result['gem'])
        self.assertNotIn('e(0)',result['gem'])

    def test_refuses_unrepresentable_shape_pose_domain_and_overlap(self):
        for invalid in ({'kind':'sphere','center_mm':[0,0,0]},{'kind':'box','center_mm':[0,0,0],'size_mm':[2,0,2]}):
            with self.subTest(shape=invalid),self.assertRaises(ValueError):self.render([member('a','g','m',invalid)])
        with self.assertRaisesRegex(ValueError,'world z axis'):
            self.render([member('a','g','m',self.cylinder,rotation=((0,0,1),(0,1,0),(-1,0,0)))])
        with self.assertRaisesRegex(ValueError,'axis-permutation'):
            self.render([member('a','g','m',self.box,rotation=((.6,-.8,0),(.8,.6,0),(0,0,1)))])
        with self.assertRaisesRegex(ValueError,'cannot verify.*bounding boxes overlap'):
            self.render([member('a','g','1',self.box),member('b','g','2',self.box)])
        bad=dict(self.domain,frame_id='foreign')
        with self.assertRaisesRegex(ValueError,'frame'):self.render(domain=bad)
        with self.assertRaisesRegex(ValueError,'alignment'):self.render(pitch_mm=3)
        with self.assertRaisesRegex(ValueError,'boundary'):self.render(boundary='implicit')
        nested={'kind':'difference','base':self.box,'tools':[{'kind':'difference','base':self.box,'tools':[self.box]}]}
        with self.assertRaisesRegex(ValueError,'nested difference'):self.render([member('a','g','m',nested)])

    def test_formatter_rounding_is_reported_without_refusing_input(self):
        precise=copy.deepcopy(self.box)
        precise['center_mm'][0]=0.123456789012345
        result=self.render([member('a','g','precise',precise)])
        self.assertIn('centered_box3D(0.123456789012,',result['gem'])
        self.assertIn({'input':0.123456789012345,'serialized':'0.123456789012'}, result['serialization']['rounded_values'])

    def test_ambiguous_overlapping_bounds_do_not_claim_collision(self):
        # Centers sqrt(1.9**2 + 1.9**2) apart: radii sum to 2, but AABBs overlap.
        pair=[member('a','g','one',self.cylinder),member('b','g','two',self.cylinder,(1.9,1.9,0))]
        with self.assertRaisesRegex(ValueError, 'cannot verify independent-conductor separation'):
            self.render(pair)
