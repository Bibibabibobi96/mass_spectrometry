"""Pure shape-query checks; no CAD kernel or commercial execution."""
import hashlib
import json
import copy
import itertools
import math
import unittest
from unittest import mock
from pathlib import Path

from msplatform.components import shape_query as query

class ShapeQueryTests(unittest.TestCase):
    def test_prepared_box_surface_culling_preserves_uncertainty_and_conflicts(self):
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[0,-1,0],[1,0,0],[0,0,1]],'translation_mm':[1000000,-2000000,3]}
        box=lambda lo,hi: {'kind':'ip_box','min_mm':lo,'max_mm':hi}
        shape={'kind':'difference','base':box([-2,-2,-2],[2,2,2]),
               'tools':[box([10,-1,-1],[12,1,1])]}
        member={'instance_id':'i','member_id':'a','electrode_group_id':'g','shape':shape,'transform':pose}
        sentinel=copy.deepcopy(member);sentinel['member_id']='sentinel';sentinel['electrode_group_id']='sentinel'
        sentinel['shape']=box([1000,1000,1000],[1001,1001,1001])
        members=[sentinel,member]
        prepared=query.prepare_member_query(members,frame_id='world')
        for local_x in (-20,-2,math.nextafter(2.,math.inf),2.,10.,math.nextafter(10.,math.inf),12.,30.,1e12):
            point=(1000000.,-2000000.+local_x,3.)
            with self.subTest(local_x=local_x):
                self.assertEqual(prepared(point),query.query_members(members,point,frame_id='world'))
        for direction in (-math.inf, math.inf):
            point=(1000000.,math.nextafter(-1999990.,direction),3.)
            self.assertEqual(prepared(point),query.query_members(members,point,frame_id='world'))
        unknown=copy.deepcopy(member);unknown['member_id']='unknown';unknown['shape']={'kind':'unknown'}
        q=query.prepare_member_query([member,unknown],frame_id='world')
        self.assertEqual(q((1000000.,-2000000.,3.))['status'],'unsupported')
        other=copy.deepcopy(member);other['member_id']='b';other['electrode_group_id']='other'
        q=query.prepare_member_query([member,other],frame_id='world')
        with self.assertRaisesRegex(ValueError,'different electrode groups'):
            q((1000000.,-2000000.,3.))

    def test_prepared_box_culling_skips_both_recursions_only_after_pose_error(self):
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0]}
        box=lambda x: {'kind':'ip_box','min_mm':[x,-1,-1],'max_mm':[x+1,1,1]}
        a={'instance_id':'i','member_id':'a','electrode_group_id':'a','shape':box(10),'transform':pose}
        b={'instance_id':'i','member_id':'b','electrode_group_id':'b',
           'shape':{'kind':'difference','base':box(20),'tools':[box(30)]},'transform':pose}
        expected=query.query_members([a,b],(0,0,0),frame_id='world')
        prepared=query.prepare_member_query([a,b],frame_id='world')
        with mock.patch.object(query,'_shape_relation',wraps=query._shape_relation) as relation:
            self.assertEqual(prepared((0,0,0)),expected)
            self.assertEqual(relation.call_count,1)
        del b['electrode_group_id']
        malformed=query.prepare_member_query([a,b],frame_id='world')
        with self.assertRaises(KeyError): malformed((0,0,0))

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

    def test_ip_box_and_concave_extrusion_relations(self):
        box={'kind':'ip_box','min_mm':[-1,-2,-3],'max_mm':[1,2,3]}
        for point,expected in [((0,0,0),'interior'),((1,0,0),'boundary'),((1.01,0,0),'outside')]:
            with self.subTest(point=point): self.assertEqual(query.shape_relation(box,point),expected)
        poly={'kind':'extruded_yz_polygon','x':[-1,1],'polygon_yz_mm':[[0,0],[4,0],[4,1],[1,1],[1,4],[0,4]]}
        for point,expected in [((0,.5,3),'interior'),((0,3,3),'outside'),((0,1,3),'boundary'),((1,.5,3),'boundary'),((2,.5,3),'outside')]:
            with self.subTest(point=point): self.assertEqual(query.shape_relation(poly,point),expected)
        for bad in ({'kind':'ip_box','min_mm':[1,0,0],'max_mm':[0,1,1]},
                    {'kind':'extruded_yz_polygon','x':[1,0],'polygon_yz_mm':[[0,0],[1,0],[0,1]]},
                    {'kind':'extruded_yz_polygon','x':[0,1],'polygon_yz_mm':[[0,0],[1,0],[1,float('nan')]]},
                    {'kind':'extruded_yz_polygon','x':[0,1],'polygon_yz_mm':[[0,0],[4,3],[0,4],[3,0]]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): query.shape_relation(bad,(0,0,0))

    def test_extrusion_pose_boundary_unknown_and_overlap(self):
        from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world','rotation':[[0,-1,0],[1,0,0],[0,0,1]],'translation_mm':[10,2,3]}
        shape={'kind':'extruded_yz_polygon','x':[-1,1],'polygon_yz_mm':[[0,0],[4,0],[4,1],[1,1],[1,4],[0,4]]}
        member={'instance_id':'mr','member_id':'p','electrode_group_id':'a','shape':shape,'transform':pose}
        transform=RigidTransform.from_contract(pose)
        for point,status in [((0,.5,3),'interior'),((0,1,3),'boundary'),((0,3,3),'outside')]:
            world=transform.transform_position(FramedPosition('local',point))
            self.assertEqual(query.query_members([member],world.coordinates_mm,frame_id='world')['status'],status)
        other=copy.deepcopy(member);other['electrode_group_id']='b'
        world=transform.transform_position(FramedPosition('local',(0,.5,3)))
        with self.assertRaisesRegex(ValueError,'different electrode groups'):query.query_members([member,other],world.coordinates_mm,frame_id='world')
        other['shape']={'kind':'unknown'}
        self.assertEqual(query.query_members([member,other],world.coordinates_mm,frame_id='world')['status'],'unsupported')

    def test_shared_mr_polygon_membership_preserves_existing_wrapper(self):
        from msplatform.backends.simion.mrtof_observations import _polygon_membership, _polygon_contains, _strict_polygon_hole
        poly=[[0,0],[4,0],[4,1],[1,1],[1,4],[0,4]]
        for point in ((.5,3),(3,3),(1,3),(0,0)):
            self.assertEqual(_polygon_membership(point,poly),query.polygon_membership(point,poly))
        self.assertTrue(_polygon_contains((1.01,3),poly,.02))
        self.assertFalse(_polygon_contains((1.01,3),poly,.005))
        self.assertTrue(_strict_polygon_hole((.5,3),poly,.01))
        self.assertFalse(_strict_polygon_hole((1,3),poly,.01))

    def test_ip_x_cylinder_endcaps_pose_and_bore(self):
        from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
        cyl={'kind':'ip_cylinder_x','x_min_mm':0,'x_max_mm':29,'center_y_mm':2.6,'center_z_mm':0.,'radius_mm':.6}
        for point,status in [((10,2.6,0),'interior'),((0,2.6,0),'boundary'),((10,2.6,.6),'boundary'),((10,0,0),'outside')]:
            with self.subTest(point=point): self.assertEqual(query.shape_relation(cyl,point),status)
        lens={'kind':'difference','base':{'kind':'ip_box','min_mm':[29.5,-3,-3],'max_mm':[30,3,3]},'tools':[{'kind':'ip_cylinder_x','x_min_mm':29.4,'x_max_mm':30.1,'center_y_mm':0,'center_z_mm':0,'radius_mm':1.0}]}
        self.assertEqual(query.shape_relation(lens,(29.75,0,0)),'outside')
        self.assertEqual(query.shape_relation(lens,(29.75,2,0)),'interior')
        self.assertEqual(query.shape_relation(lens,(29.75,1,0)),'boundary')
        for change in ({'radius_mm':0},{'x_min_mm':30},{'center_y_mm':float('nan')}):
            bad=dict(cyl,**change)
            with self.subTest(change=change),self.assertRaises(ValueError):query.shape_relation(bad,(10,0,0))
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world','rotation':[[0,0,-1],[1,0,0],[0,-1,0]],'translation_mm':[0,-225,3]}
        member={'instance_id':'ip','member_id':'guide','electrode_group_id':'g','shape':cyl,'transform':pose}
        transform=RigidTransform.from_contract(pose)
        for point,status in [((10,2.6,0),'interior'),((0,2.6,0),'boundary'),((10,0,0),'outside')]:
            world=transform.transform_position(FramedPosition('local',point));self.assertEqual(query.query_members([member],world.coordinates_mm,frame_id='world')['status'],status)

if __name__=='__main__':unittest.main()


class PreparedQueryTests(unittest.TestCase):
    def test_parity_pose_concavity_boundaries_and_snapshot(self):
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[0,-1,0],[1,0,0],[0,0,1]],'translation_mm':[10,2,-3]}
        shape={'kind':'extruded_yz_polygon','x':[-1,1],
               'polygon_yz_mm':[[0,0],[4,0],[4,1],[1,1],[1,4],[0,4]]}
        member={'instance_id':'i','member_id':'m','electrode_group_id':'g','shape':shape,'transform':pose}
        from msplatform.contracts.rigid_transform import RigidTransform, FramedPosition
        transform=RigidTransform.from_contract(pose); prepared=query.prepare_member_query([member],frame_id='world')
        points=[(0,.5,3),(0,3,3),(0,1,3),(1,.5,3),
                (math.nextafter(1.,-math.inf),.5,3),(math.nextafter(1.,math.inf),.5,3)]
        for p in points:
            world=transform.transform_position(FramedPosition('local',p)).coordinates_mm
            self.assertEqual(prepared(world),query.query_members([member],world,frame_id='world'))
        world=transform.transform_position(FramedPosition('local',points[0])).coordinates_mm
        expected=prepared(world); member['shape']['polygon_yz_mm'][0][0]=999
        member['transform']['translation_mm'][0]=999
        self.assertEqual(prepared(world),expected)

    def test_unsupported_overlap_and_invalid_geometry(self):
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0]}
        member={'instance_id':'i','member_id':'m','electrode_group_id':'g','transform':pose,
                'shape':{'kind':'ip_box','min_mm':[-1,-1,-1],'max_mm':[1,1,1]}}
        other=copy.deepcopy(member);other['member_id']='u';other['shape']={'kind':'unknown'}
        self.assertEqual(query.prepare_member_query([member,other],frame_id='world')((0,0,0)),
                         query.query_members([member,other],(0,0,0),frame_id='world'))
        other=copy.deepcopy(member);other['electrode_group_id']='other'
        with self.assertRaisesRegex(ValueError,'different electrode groups'):
            query.prepare_member_query([member,other],frame_id='world')((0,0,0))
        bad=copy.deepcopy(member);bad['shape']={'kind':'extruded_yz_polygon','x':[0,1],
                  'polygon_yz_mm':[[0,0],[4,3],[0,4],[3,0]]}
        with self.assertRaises(ValueError):query.prepare_member_query([bad],frame_id='world')

    def test_shared_pose_parity_orthogonal_defect_and_frame(self):
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[1-4e-13,0,0],[0,1,0],[0,0,1]],'translation_mm':[10,2,-3]}
        base={'instance_id':'i','member_id':'a','electrode_group_id':'g','transform':pose,
              'shape':{'kind':'ip_box','min_mm':[-1,-1,-1],'max_mm':[1,1,1]}}
        second=copy.deepcopy(base);second['member_id']='b';second['shape']['min_mm']=[5,5,5];second['shape']['max_mm']=[6,6,6]
        third=copy.deepcopy(second);third['member_id']='c';third['transform']['translation_mm'][1]=3
        members=[base,second,third];prepared=query.prepare_member_query(members,frame_id='world')
        for x in (math.nextafter(11.,-math.inf),11.,math.nextafter(11.,math.inf),10.,12.):
            point=(x,2.,-3.)
            self.assertEqual(prepared(point),query.query_members(members,point,frame_id='world'))
        self.assertEqual(prepared((10.,2.,-3.)),query.query_members(members,(10.,2.,-3.),frame_id='world'))
        self.assertEqual(prepared((100.,200.,300.)),query.query_members(members,(100.,200.,300.),frame_id='world'))
        with self.assertRaises(ValueError):query.prepare_member_query(members,frame_id='wrong')((10.,2.,-3.))

    def test_prepared_polygon_bounds_concave_hole_and_large_coordinates(self):
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0]}
        for offset in (0., 1e12):
            polygon={'kind':'extruded_yz_polygon','x':[-1,1],
                     'polygon_yz_mm':[[offset,offset],[offset+4,offset],[offset+4,offset+1],
                                      [offset+1,offset+1],[offset+1,offset+4],[offset,offset+4]]}
            base={'kind':'ip_box','min_mm':[-2,offset-2,offset-2],
                  'max_mm':[2,offset+2,offset+2]}
            for shape in (polygon,{'kind':'difference','base':base,'tools':[polygon]}):
                member={'instance_id':'i','member_id':'p','electrode_group_id':'g','transform':pose,'shape':shape}
                prepared=query.prepare_member_query([member],frame_id='world')
                vals=[offset-2,math.nextafter(offset,-math.inf),offset,math.nextafter(offset,math.inf),
                      offset+0.5,offset+1,offset+3,offset+4,math.nextafter(offset+4,math.inf),offset+20]
                for x in (-1.,0.,1.,2.):
                    for y in vals:
                        for z in vals:
                            point=(x,y,z)
                            self.assertEqual(prepared(point),query.query_members([member],point,frame_id='world'),point)

    def test_prepared_ip_nested_cached_validation_pose_and_snapshot(self):
        from unittest.mock import patch
        from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
        pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world',
              'rotation':[[0,0,-1],[1,0,0],[0,-1,0]],'translation_mm':[10,-225,3]}
        for offset in (0., 1e12):
            member_pose=copy.deepcopy(pose)
            transform=RigidTransform.from_contract(member_pose)
            box={'kind':'ip_box','min_mm':[-2,offset-2,-2],'max_mm':[2,offset+2,2]}
            cyl={'kind':'ip_cylinder_x','x_min_mm':-3,'x_max_mm':3,
                 'center_y_mm':offset,'center_z_mm':0.,'radius_mm':1.}
            shape={'kind':'difference','base':{'kind':'union','parts':[box,copy.deepcopy(box)]},'tools':[cyl]}
            member={'instance_id':'i','member_id':'nested','electrode_group_id':'g','transform':member_pose,'shape':shape}
            known=[((0.,offset+1.5,0.),'interior'),((0.,offset+2.,0.),'boundary'),((0.,offset+3.,0.),'outside')]
            for local,status in known:
                world=transform.transform_position(FramedPosition('local',local)).coordinates_mm
                self.assertEqual(query.query_members([member],world,frame_id='world')['status'],status)
            with patch.object(query,'_canonical_box_bounds',wraps=query._canonical_box_bounds) as boxes, \
                 patch.object(query,'_ip_x_cylinder_as_rod',wraps=query._ip_x_cylinder_as_rod) as cylinders:
                prepared=query.prepare_member_query([member],frame_id='world')
                self.assertEqual(boxes.call_count,2);self.assertEqual(cylinders.call_count,1)
                values=[offset-2,math.nextafter(offset-1,-math.inf),offset-1,
                        math.nextafter(offset-1,math.inf),offset,offset+1,offset+2,offset+3]
                worlds=[transform.transform_position(FramedPosition('local',(x,y,0.))).coordinates_mm
                        for x in (-2.,0.,2.) for y in values]
                observed=[prepared(point) for point in worlds]
                self.assertEqual(boxes.call_count,2);self.assertEqual(cylinders.call_count,1)
            expected=[query.query_members([member],point,frame_id='world') for point in worlds]
            self.assertEqual(observed,expected)
            member['shape']['base']['parts'][0]['min_mm'][0]=999
            member['shape']['tools'][0]['radius_mm']=999
            member['transform']['translation_mm'][0]=999
            self.assertEqual([prepared(point) for point in worlds],observed)
        for bad in ({'kind':'ip_box','min_mm':[1,0,0],'max_mm':[0,1,1]},
                    {'kind':'ip_cylinder_x','x_min_mm':0,'x_max_mm':1,'center_y_mm':0,'center_z_mm':0,'radius_mm':0}):
            member={'instance_id':'i','member_id':'bad','electrode_group_id':'g','transform':pose,'shape':bad}
            with self.assertRaises(ValueError):query.prepare_member_query([member],frame_id='world')
