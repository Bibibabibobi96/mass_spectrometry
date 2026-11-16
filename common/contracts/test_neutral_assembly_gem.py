"""Neutral GEM serializer contracts; no native SIMION execution."""
import copy
import importlib.util
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
        # Existing renderer follows limited native cut-parity evidence 390e85909ccf.
        self.assertEqual(result['gem'].count('notin {'),2);self.assertIn('centered_box3D(0,0,0,4,2,6)',result['gem'])
        self.assertNotIn('e(0)',result['gem'])

    def test_refuses_unrepresentable_shape_pose_domain_and_overlap(self):
        for invalid in ({'kind':'sphere','center_mm':[0,0,0]},{'kind':'box','center_mm':[0,0,0],'size_mm':[2,0,2]}):
            with self.subTest(shape=invalid),self.assertRaises(ValueError):self.render([member('a','g','m',invalid)])
        with self.assertRaisesRegex(ValueError,'axis-permutation'):
            self.render([member('a','g','m',self.box,rotation=((.6,-.8,0),(.8,.6,0),(0,0,1)))])
        with self.assertRaisesRegex((ValueError,RuntimeError), 'overlap' if importlib.util.find_spec('cadquery') else 'optional cad-step'):
            self.render([member('a','g','1',self.box),member('b','g','2',self.box)])
        bad=dict(self.domain,frame_id='foreign')
        with self.assertRaisesRegex(ValueError,'frame'):self.render(domain=bad)
        with self.assertRaisesRegex(ValueError,'alignment'):self.render(pitch_mm=3)
        with self.assertRaisesRegex(ValueError,'boundary'):self.render(boundary='implicit')
        nested={'kind':'difference','base':self.box,'tools':[{'kind':'difference','base':self.box,'tools':[self.box]}]}
        with self.assertRaisesRegex(ValueError,'nested difference'):self.render([member('a','g','m',nested)])

    def test_signed_axis_permuted_cylinders_keep_real_bounds_and_order(self):
        cylinder=dict(kind='cylinder',center_mm=[1,2,3],radius_mm=1,height_mm=4)
        cases=[(((0,0,1),(0,1,0),(-1,0,0)), 'locate(8,6,4) { rotate_y(90)',
                ((0,0,-1),(0,1,0),(1,0,0)), 'locate(2,6,6) { rotate_y(90)'),
               (((1,0,0),(0,0,1),(0,-1,0)), 'locate(4,9,3) { rotate_x(-90)',
                ((1,0,0),(0,0,-1),(0,1,0)), 'locate(4,3,7) { rotate_x(-90)')]
        for positive, expected_positive, negative, expected_negative in cases:
            with self.subTest(positive=positive):
                value=self.render([member('a','g','c',cylinder,(3,4,5),positive)])
                self.assertIn(expected_positive,value['gem'])
                self.assertEqual(value['members'][0]['source_refs'],['/shape'])
                self.assertIn(expected_negative,self.render([member('a','g','c',cylinder,(3,4,5),negative)])['gem'])
        changed=copy.deepcopy(cylinder);changed['height_mm']=6
        self.assertNotEqual(self.render([member('a','g','c',cylinder,rotation=cases[0][0])])['gem_sha256'],
                            self.render([member('a','g','c',changed,rotation=cases[0][0])])['gem_sha256'])
        invalid=((.6,-.8,0),(.8,.6,0),(0,0,1))
        with self.assertRaisesRegex(ValueError,'axis-permutation'):
            self.render([member('a','g','c',cylinder,rotation=invalid)])
        pair=[member('a','g','one',self.cylinder,rotation=cases[0][0]),
              member('b','g','two',self.cylinder,(0,1.5,0),rotation=cases[0][0])]
        with self.assertRaisesRegex((ValueError,RuntimeError), 'overlap' if importlib.util.find_spec('cadquery') else 'optional cad-step'):
            self.render(pair)

    def test_registered_cylinder_provider_through_real_assembly(self):
        from msplatform import assembly, components
        from msplatform.components.registry import ProviderDescriptor, register_provider
        from common.contracts.test_support import registered_component as toy
        def resolve(source, profile):
            resolved, interface=toy.resolve(source,profile);interface['project_id']='toy_axis_cylinder'
            return resolved, interface
        def validate(source,resolved,interface):
            if resolve(source,interface.get('geometry_profile_id')) != (resolved,interface):
                raise ValueError('source differs')
        def members(resolved,interface):
            return [dict(member_id='body',electrode_group_id='body',shape=dict(kind='cylinder',center_mm=[0,0,0],radius_mm=resolved['width_mm']/2,height_mm=4),
                         source_refs=['/width_mm'],local_frame_id='toy_local',length_unit='mm',representation_role='physical_solid')]
        register_provider(ProviderDescriptor('toy_axis_cylinder','toy_axis_cylinder',resolve,validate,members,('common.contracts.test_neutral_assembly_gem',)))
        component=components.resolve_component(dict(provider_id='toy_axis_cylinder',design={'width_mm':2}))
        pose=dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[0,0,1],[0,1,0],[-1,0,0]],translation_mm=[3,4,5])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='axis_test',recipe_id='axis_test',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='part',project_id='toy_axis_cylinder',transform=pose)],connections=[])
        product=assembly.assemble(recipe,{'part':component});snapshot=dict(composition_plan=product.composition_plan,components_resolved=product.components_resolved,components_source=product.components_source)
        result=render_assembly_gem(snapshot,domain=self.domain,pitch_mm=1,boundary='native_zero_neumann')
        self.assertIn('locate(5,4,5) { rotate_y(90)',result['gem'])
        self.assertEqual([(row['instance_id'],row['electrode_group_id']) for row in result['electrode_mapping']],[('part','body')])
        self.assertEqual(result['members'][0]['source_refs'],['/width_mm'])
        stale=copy.deepcopy(snapshot);stale['components_source']['part']['width_mm']=3
        with self.assertRaisesRegex(ValueError,'source differs'):
            render_assembly_gem(stale,domain=self.domain,pitch_mm=1,boundary='native_zero_neumann')
    def test_real_bare_rf_round_rods_keep_provider_identity_and_pose(self):
        from common.contracts.test_geometry_members import real_snapshot
        from msplatform.assembly.resolve_assembly import compile_assembly_layout
        snapshot=real_snapshot();plan=snapshot['composition_plan']
        snapshot['composition_plan']=compile_assembly_layout(plan['recipe'],plan['components'],local_scope=dict(instance_ids=['multipole'],research_scope='RF solids',boundary_assumptions='explicit selected scope'))
        domain=dict(frame_id=plan['recipe']['assembly_frame_id'],minimum_mm=[-1000]*3,maximum_mm=[1000]*3)
        before=copy.deepcopy(snapshot);result=render_assembly_gem(snapshot,domain=domain,pitch_mm=1,boundary='native_zero_neumann')
        self.assertEqual(snapshot,before);self.assertEqual(len(result['members']),32)
        self.assertEqual(len(result['electrode_mapping']),8);self.assertEqual(result['gem'].count('rotate_y(90)'),32)
        self.assertEqual({m['instance_id'] for m in result['members']},{'multipole'})
        self.assertEqual(len({m['member_id'] for m in result['members']}),32)
        self.assertTrue(all(m['source_refs']==[m['member_id']] for m in result['members']))
        changed=copy.deepcopy(snapshot);changed['components_source']['multipole']['geometry_mm']['inscribed_radius_r0']+=1
        with self.assertRaisesRegex(ValueError,'RF resolved design or interface differs'):
            render_assembly_gem(changed,domain=domain,pitch_mm=1,boundary='native_zero_neumann')

    def test_round_rod_rejects_elliptical_mixed_and_bad_extents(self):
        rod=dict(kind='rod',center_xy_mm=[1,2],z_min_mm=-2,z_max_mm=2,radius_mm=1)
        self.assertIn('rotate_y(90)',self.render([member('a','g','round',rod,rotation=((0,0,1),(0,1,0),(-1,0,0)))])['gem'])
        for changed in (dict(rod,semi_major_axis_mm=2),{k:v for k,v in rod.items() if k!='radius_mm'},dict(rod,z_max_mm=-2),dict(rod,z_min_mm=float('nan'))):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                self.render([member('a','g','invalid',changed)])
    def test_formatter_rounding_is_reported_without_refusing_input(self):
        precise=copy.deepcopy(self.box)
        precise['center_mm'][0]=0.123456789012345
        result=self.render([member('a','g','precise',precise)])
        self.assertIn('centered_box3D(0.123456789012,',result['gem'])
        self.assertIn({'input':0.123456789012345,'serialized':'0.123456789012'}, result['serialization']['rounded_values'])

    def test_overlapping_bounds_with_separate_cylinders_use_exact_proof(self):
        # The two radii sum to 2; diagonal center distance exceeds 2, despite overlapping AABBs.
        pair=[member('a','g','one',self.cylinder),member('b','g','two',self.cylinder,(1.9,1.9,0))]
        real_import=__import__
        def deny(name,*args,**kwargs):
            if name=='cadquery':raise ImportError('controlled missing optional CAD')
            return real_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=deny),self.assertRaisesRegex(RuntimeError,'optional cad-step'):
            self.render(pair)
        if importlib.util.find_spec('cadquery'):
            result=self.render(pair)
            self.assertEqual(len(result['electrode_mapping']),2)
            self.assertNotIn('contact_obligations',result)
        else:
            with self.assertRaisesRegex(RuntimeError,'optional cad-step'):self.render(pair)
