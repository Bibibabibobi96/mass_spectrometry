"""Pure shape-query checks; no CAD kernel or commercial execution."""
import hashlib
import json
import copy
import itertools
import math
import unittest
from pathlib import Path

from msplatform.components import shape_query as query

class ShapeQueryTests(unittest.TestCase):
    def test_oa_witness_frozen_source_parity(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/oa_witness_parity.json').read_text(encoding='utf-8'))
        bits = fixture['expected_bits']
        self.assertEqual(fixture['source_sha256'], '1283c181707eef463e36df2edb3b932282624a23536d2c1629f3318c21ef611a')
        self.assertEqual(fixture['count'], 2160)
        self.assertEqual(len(bits), fixture['count'])
        self.assertEqual(hashlib.sha256(bits.encode('ascii')).hexdigest(), fixture['bits_sha256'])
        cases = itertools.product(fixture['shapes'], itertools.product(fixture['axis_values'], repeat=3), (False, True))
        for (shape, point, boundary), expected in zip(cases, bits, strict=True):
            self.assertEqual(query.oa_witness_contains(shape, point, boundary=boundary), expected == '1')
    def test_holes_solids_and_ideal_sheet(self):
        box={'kind':'box','center_mm':[0,0,0],'size_mm':[4,4,4]}
        hole={'kind':'cylinder','center_mm':[0,0,0],'radius_mm':1,'height_mm':4}
        cut={'kind':'difference','base':box,'tools':[hole]}
        self.assertEqual(query.shape_relation(cut,(1.5,0,0)),'interior')
        self.assertEqual(query.shape_relation(cut,(0,0,0)),'outside')
        self.assertEqual(query.shape_relation(cut,(1,0,0)),'boundary')
        self.assertEqual(query.shape_relation(cut,(2,0,0)),'boundary')
        sheet={'kind':'box','center_mm':[0,0,0],'size_mm':[4,4,0]}
        self.assertEqual(query.shape_relation(sheet,(0,0,0)),'boundary')
        self.assertEqual(query.shape_relation(sheet,(0,0,1)),'outside')
        ring={'kind':'annulus','center_xy_mm':[0,0],'z_min_mm':-1,'z_max_mm':1,'inner_radius_mm':1,'outer_radius_mm':2}
        self.assertEqual([query.shape_relation(ring,p) for p in [(0,0,0),(1,0,0),(1.5,0,0),(2,0,0)]],['outside','boundary','interior','boundary'])
        zero=dict(ring,inner_radius_mm=0);self.assertEqual(query.shape_relation(zero,(0,0,0)),'interior')
    def test_accepted_near_orthogonal_pose_retains_face_cut_and_sheet_ambiguity(self):
        from msplatform.contracts.rigid_transform import RigidTransform,FramedPosition
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[1-4e-13,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0]}
        transform=RigidTransform.from_contract(pose)
        shapes=[{'kind':'box','center_mm':[0,0,0],'size_mm':[2,2,2]},
                {'kind':'difference','base':{'kind':'box','center_mm':[0,0,0],'size_mm':[6,6,6]},
                 'tools':[{'kind':'box','center_mm':[0,0,0],'size_mm':[2,2,2]}]},
                {'kind':'box','center_mm':[1,0,0],'size_mm':[0,2,2]}]
        for index,shape in enumerate(shapes):
            member={'instance_id':'i','member_id':str(index),'electrode_group_id':'g','shape':shape,'transform':pose}
            for x in (math.nextafter(1.,-math.inf),1.,math.nextafter(1.,math.inf)):
                point=transform.transform_position(FramedPosition('local',(x,0,0))).coordinates_mm
                with self.subTest(shape=index,x=x):
                    self.assertEqual(query.query_members([member],point,frame_id='world')['status'],'boundary')
        member={'instance_id':'i','member_id':'box','electrode_group_id':'g','shape':shapes[0],'transform':pose}
        for x,status in ((1.-1e-8,'interior'),(1.+1e-8,'outside')):
            point=transform.transform_position(FramedPosition('local',(x,0,0))).coordinates_mm
            self.assertEqual(query.query_members([member],point,frame_id='world')['status'],status)

    def test_rotated_translated_surface_ulp_neighbors_are_ambiguous(self):
        from msplatform.contracts.rigid_transform import RigidTransform,FramedPosition
        c=math.sqrt(0.5)
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[c,-c,0],[c,c,0],[0,0,1]],'translation_mm':[101.25,-44.75,2.5]}
        member={'instance_id':'rf','member_id':'rod','electrode_group_id':'g','transform':pose,
                'shape':{'kind':'rod','center_xy_mm':[2,0],'z_min_mm':0,'z_max_mm':4,'radius_mm':1}}
        transform=RigidTransform.from_contract(pose)
        for x in (math.nextafter(3.,-math.inf),3.,math.nextafter(3.,math.inf)):
            world=transform.transform_position(FramedPosition('local',(x,0,2)))
            with self.subTest(local_x=x):
                self.assertEqual(query.query_members([member],world.coordinates_mm,frame_id='world')['status'],'boundary')
        for x,status in ((3.-1e-6,'interior'),(3.+1e-6,'outside')):
            world=transform.transform_position(FramedPosition('local',(x,0,2)))
            self.assertEqual(query.query_members([member],world.coordinates_mm,frame_id='world')['status'],status)

    def test_pose_conflict_unknown_and_perturbation(self):
        transform={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world','rotation':[[0,-1,0],[1,0,0],[0,0,1]],'translation_mm':[10,0,0]}
        shape={'kind':'rod','center_xy_mm':[2,0],'z_min_mm':0,'z_max_mm':4,'radius_mm':1}
        member={'instance_id':'rf','member_id':'rod','electrode_group_id':'g','shape':shape,'transform':transform}
        self.assertEqual(query.query_members([member],(10,2,2),frame_id='world'),{'status':'interior','group':('rf','g')})
        self.assertEqual(query.query_members([member],(10,3,2),frame_id='world')['status'],'boundary')
        changed=copy.deepcopy(member);changed['shape']['radius_mm']=0.25
        self.assertEqual(query.query_members([changed],(10,2.5,2),frame_id='world')['status'],'outside')
        other=copy.deepcopy(member);other['electrode_group_id']='different'
        with self.assertRaisesRegex(ValueError,'different electrode groups'):query.query_members([member,other],(10,2,2),frame_id='world')
        other['shape']={'kind':'unrecognised'}
        self.assertEqual(query.query_members([member,other],(10,2,2),frame_id='world')['status'],'unsupported')
        with self.assertRaises(ValueError):query.query_members([member],(10,2,2),frame_id='wrong')

if __name__=='__main__':unittest.main()
