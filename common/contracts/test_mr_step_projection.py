"""Source-only MR STEP plan, with real canonical OA/MR providers and no CAD."""
from msplatform.components.geometry_members import assembly_geometry_members
import copy
import unittest
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.exporters import step
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_mr_provider_trial_transport as fixtures
from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority


def snapshot(a):
    return dict(composition_plan=a.composition_plan,components_resolved=a.components_resolved,components_source=a.components_source)


class MrStepProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,plan,contract=fixtures._plans();auth=geometry_authority(contract);profile=auth['geometry_profile_id']
        oa=resolve_component(dict(provider_id='orthogonal_accelerator',geometry_profile_id=profile,
            design=dict(requirements=auth['accelerator_requirements'],geometry_profile=auth['geometry_profile'])))
        mr=resolve_component(dict(provider_id='parallel_mirror_dual_stripe_mr_tof',geometry_profile_id=profile,
            design=dict(contract=contract,accelerator_requirements=auth['accelerator_requirements'],geometry_profile=auth['geometry_profile'])))
        cls.oa=next(n for n,v in plan['components'].items() if v['project_id']=='orthogonal_accelerator')
        cls.mr=next(n for n,v in plan['components'].items() if v['project_id']=='parallel_mirror_dual_stripe_mr_tof')
        cls.assembly=assemble(plan['recipe'],{cls.oa:oa,cls.mr:mr})

    def test_actual_combined_complete_source_and_exactly_one_oa(self):
        data=snapshot(self.assembly);before=copy.deepcopy(data);members=assembly_geometry_members(data)
        oa=[m for m in members if m['instance_id']==self.oa];mr=[m for m in members if m['instance_id']==self.mr]
        from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
        self.assertEqual(len(oa),len(iter_geometry_members(data['components_resolved'][self.oa])))
        self.assertEqual({m['electrode_group_id'] for m in mr},{x['electrode_group_id'] for x in data['composition_plan']['components'][self.mr]['component_electrodes']})
        source=data['components_resolved'][self.mr]
        for family in ('mirror_electrodes','mirror_e_closures','mirror_ground_shields','stripe_electrodes','prism_electrodes','prism_ground_shields'):
            self.assertEqual(sum(m['member_id'].startswith(family+'/') for m in mr),len(source[family]))
        self.assertEqual(sum(m['member_id']=='central_ground_electrodes' for m in mr),1)
        self.assertEqual(sum(m['member_id']=='detector' for m in mr),1)
        stripe=next(m for m in mr if m['member_id']=='stripe_electrodes/0')['shape']
        self.assertEqual(stripe['base']['parts'][0]['polygon_yz_mm'],source['stripe_electrodes'][0]['polygon_yz_mm'])
        self.assertEqual(stripe['base']['parts'][1]['polygon_yz_mm'],source['stripe_electrodes'][0]['terminal_polygon_yz_mm'])
        self.assertEqual(stripe['tools'][0]['size_mm'],[source['stripe_slot'][i+3]-source['stripe_slot'][i] for i in range(3)])
        self.assertEqual(len(step.step_member_names(data,members)),len(members));self.assertEqual(data,before)

    def test_analyzer_alone_remains_analyzer_only(self):
        a=self.assembly;recipe=copy.deepcopy(a.composition_plan['recipe']);recipe['instances']=[r for r in recipe['instances'] if r['instance_id']==self.mr];recipe['connections']=[]
        only=assemble(recipe,{self.mr:a.components[self.mr]});members=assembly_geometry_members(snapshot(only))
        self.assertTrue(members);self.assertEqual({m['instance_id'] for m in members},{self.mr})
        self.assertFalse(any('accelerator_component_geometry' in str(m['source_refs']) for m in members))

    def test_source_and_geometry_tamper_refuse(self):
        for change in ('source','geometry','plan'):
            data=copy.deepcopy(snapshot(self.assembly))
            if change=='source': data['components_source'][self.mr]['contract']['detector']['active_width_x_mm']+=1
            elif change=='geometry':data['components_resolved'][self.mr]['stripe_electrodes'][0]['x'][0]-=.1
            else:data['composition_plan']['scope']['instance_ids'].append(self.mr)
            with self.subTest(change=change),self.assertRaises(ValueError):assembly_geometry_members(data)

    def test_polygon_validation_rejects_unknown_and_zero_area(self):
        for shape in (dict(kind='unknown'),dict(kind='extruded_yz_polygon',x=[0,1],polygon_yz_mm=[[0,0],[1,1],[2,2]])):
            with self.subTest(shape=shape),self.assertRaises(ValueError):step._validate_shape(shape)
    def test_common_proper_pose_applies_once_without_rewriting_members(self):
        a=self.assembly;recipe=copy.deepcopy(a.composition_plan['recipe'])
        rotation=[[0,-1,0],[1,0,0],[0,0,1]];offset=[50,-20,7]
        for row in recipe['instances']:
            pose=row['transform'];old=copy.deepcopy(pose)
            pose['rotation']=[[sum(rotation[i][k]*old['rotation'][k][j] for k in range(3)) for j in range(3)] for i in range(3)]
            pose['translation_mm']=[sum(rotation[i][k]*old['translation_mm'][k] for k in range(3))+offset[i] for i in range(3)]
        moved=assemble(recipe,a.components)
        before=assembly_geometry_members(snapshot(a));after=assembly_geometry_members(snapshot(moved))
        self.assertEqual([(x['instance_id'],x['member_id'],x['shape']) for x in before],[(x['instance_id'],x['member_id'],x['shape']) for x in after])
        for m in after:
            self.assertEqual(m['transform'],next(r['transform'] for r in recipe['instances'] if r['instance_id']==m['instance_id']))

    def test_detector_parameter_propagates_from_provider(self):
        a=self.assembly;source=copy.deepcopy(a.components_source[self.mr]);source['contract']['detector']['active_width_x_mm']+=1
        profile=a.composition_plan['components'][self.mr]['geometry_profile_id']
        changed=resolve_component(dict(provider_id='parallel_mirror_dual_stripe_mr_tof',geometry_profile_id=profile,design=source))
        changed_assembly=assemble(a.composition_plan['recipe'],dict(a.components,**{self.mr:changed}))
        old=next(m for m in assembly_geometry_members(snapshot(a)) if m['instance_id']==self.mr and m['member_id']=='detector')
        new=next(m for m in assembly_geometry_members(snapshot(changed_assembly)) if m['instance_id']==self.mr and m['member_id']=='detector')
        self.assertEqual(new['shape']['size_mm'][0],old['shape']['size_mm'][0]+1)
    def test_real_connected_oa_with_different_ring_mechanics_refuses(self):
        a=self.assembly;source=copy.deepcopy(a.components_source[self.oa]);source['geometry_profile']['ring_thickness_z_mm']*=.9
        profile=a.composition_plan['components'][self.oa]['geometry_profile_id']
        other=resolve_component(dict(provider_id='orthogonal_accelerator',geometry_profile_id=profile,design=source))
        changed=assemble(a.composition_plan['recipe'],dict(a.components,**{self.oa:other}))
        with self.assertRaisesRegex(ValueError,'OA mechanics differ'):assembly_geometry_members(snapshot(changed))

    def test_explicit_mr_oa_pose_must_match_recipe(self):
        from msplatform.contracts.rigid_transform import RigidTransform
        a=self.assembly;poses={r['instance_id']:r['transform'] for r in a.composition_plan['recipe']['instances']}
        relative=RigidTransform.from_contract(poses[self.oa]).then(RigidTransform.from_contract(poses[self.mr]).inverse()).to_contract()
        source=copy.deepcopy(a.components_source[self.mr]);relative['translation_mm'][0]+=.25;source['accelerator_to_mr']=relative
        profile=a.composition_plan['components'][self.mr]['geometry_profile_id']
        changed=resolve_component(dict(provider_id='parallel_mirror_dual_stripe_mr_tof',geometry_profile_id=profile,design=source))
        altered=assemble(a.composition_plan['recipe'],dict(a.components,**{self.mr:changed}))
        with self.assertRaisesRegex(ValueError,'relative pose differs'):assembly_geometry_members(snapshot(altered))
    def test_missing_intended_source_members_refuse(self):
        for family in ('mirror_electrodes','mirror_e_closures','mirror_ground_shields','stripe_electrodes','central_ground_electrodes','prism_electrodes','prism_ground_shields'):
            data=copy.deepcopy(snapshot(self.assembly));data['components_resolved'][self.mr][family].pop()
            with self.subTest(family=family),self.assertRaises(ValueError):assembly_geometry_members(data)

    def test_exact_canonical_cutout_and_polygon_sources(self):
        data=snapshot(self.assembly);source=data['components_resolved'][self.mr]
        members={m['member_id']:m for m in assembly_geometry_members(data) if m['instance_id']==self.mr}
        for i,row in enumerate(source['mirror_electrodes']):
            shape=members[f'mirror_electrodes/{i}']['shape']
            if 'polygon_yz_mm' in row:
                base=shape['base'] if row.get('holes') else shape
                self.assertEqual(base['polygon_yz_mm'],row['polygon_yz_mm'])
                self.assertEqual([x['polygon_yz_mm'] for x in shape.get('tools',[])],[x['polygon_yz_mm'] for x in row.get('holes',[])])
            else:
                self.assertEqual(shape['tools'][0]['size_mm'],[row['beam_slot'][j+3]-row['beam_slot'][j] for j in range(3)])
        ground=members['central_ground_electrodes']['shape']
        self.assertEqual(len(ground['tools']),len(source['central_ground_slots']))
        for i,row in enumerate(source['prism_ground_shields']):
            shape=members[f'prism_ground_shields/{i}']['shape']
            self.assertEqual(shape['tools'][0]['polygon_yz_mm'],row['prism_clearance_polygon_yz_mm'])
            self.assertEqual(len(shape['tools']),1+len(row.get('rectangular_slots_mm',[])))