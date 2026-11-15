"""Source-only contract for the explicit generic one-world collision geometry."""
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from msplatform.backends.simion import generic_geometry
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import STRUCTURAL_SEEDS

class GenericCollisionGeometryTests(unittest.TestCase):
    def setUp(self):
        self.member=dict(instance_id='item', electrode_group_id='body', member_id='solid', source_refs=['/size'], representation_role='physical_solid',shape=dict(kind='box',center_mm=[0,0,0],size_mm=[2,2,2]), transform=dict(schema_version=1,role='rigid_transform',from_frame_id='local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0]))
        from common.contracts.test_support.registered_component import ensure_registered
        from msplatform import assembly, components
        ensure_registered()
        component=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
        pose=dict(self.member['transform'],from_frame_id='toy_local')
        self.member['transform']=pose
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='item',project_id='toy_registered',transform=pose)],connections=[])
        self.assembly=assembly.assemble(recipe,{'item':component})
        self.numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-5,-5,-5],maximum_mm=[5,5,5]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[5,5,5])],void_witnesses=[[0,0,0]])
    def compile(self, numerics=None):
        with patch('msplatform.backends.simion.assembly_geometry.assembly_geometry_members',return_value=[copy.deepcopy(self.member)]), patch('msplatform.backends.simion.generic_geometry.assembly_geometry_members',return_value=[copy.deepcopy(self.member)]):
            return generic_geometry.compile_generic_collision_geometry(self.assembly,numerics=numerics or self.numerics)
    def test_snapshot_plan_and_immutable_input(self):
        before=copy.deepcopy(self.assembly); result=self.compile(); self.assertEqual(before,self.assembly)
        self.assembly.components_source['item']['width_mm']=7
        self.assertEqual(result.frontend_geometry['source_snapshot']['components_source']['item']['width_mm'],2)
        seed=dict(path=str(Path.cwd()/'seed.iob'),bytes=STRUCTURAL_SEEDS[1][0],sha256=STRUCTURAL_SEEDS[1][1])
        root=Path.cwd()/'generic-plan-test'
        with patch('msplatform.backends.simion.assembly_geometry.assembly_geometry_members',return_value=[copy.deepcopy(self.member)]), patch('msplatform.backends.simion.generic_geometry.assembly_geometry_members',return_value=[copy.deepcopy(self.member)]):
            plan=plan_geometry_build(result,run_directory=root,seed_record=seed,native_path_resource=root/'native.lua')
            result.frontend_gems['world'] += '-- tamper'
            with self.assertRaisesRegex(ValueError, 'canonical source snapshot'):
                plan_geometry_build(result,run_directory=root,seed_record=seed,native_path_resource=root/'native.lua')
        self.assertEqual([item['operation_id'] for item in plan.operations],['geometry_world','build_geometry','verify_geometry'])
        self.assertTrue(any('electrode_witness_ids' in value for value in plan.materializations.values()))
        self.assertTrue(any('neutral_world_geometry_iob_build' in value for value in plan.materializations.values()))
        self.assertFalse(any('refine' in str(item).lower() or 'flym' in str(item).lower() for item in plan.operations))
    def test_rotated_cylinder_witnesses_remain_source_derived(self):
        self.member['shape']=dict(kind='cylinder',center_mm=[0,0,0],radius_mm=1.5,height_mm=6)
        self.member['transform']['rotation']=[[0,0,1],[0,1,0],[-1,0,0]]
        request=dict(self.numerics,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[7,5,5])],void_witnesses=[[5,7,5]])
        result=self.compile(request)
        self.assertIn('rotate_y(90)',result.frontend_gems['world'])
        self.assertEqual([row['metal'] for row in result.frontend_geometry['physical_samples']],[True,False])
        with self.assertRaisesRegex(ValueError,'inside'):
            self.compile(dict(request,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[5,7,5])]))
        with self.assertRaisesRegex(ValueError,'outside'):
            self.compile(dict(request,void_witnesses=[[7,5,5]]))
    def test_round_rod_queries_use_canonical_provider_shape(self):
        self.member['shape']=dict(kind='rod',center_xy_mm=[0,0],z_min_mm=-3,z_max_mm=3,radius_mm=1.5)
        self.member['transform']['rotation']=[[0,0,1],[0,1,0],[-1,0,0]]
        request=dict(self.numerics,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[7,5,5])],void_witnesses=[[5,7,5]])
        result=self.compile(request)
        self.assertIn('rotate_y(90)',result.frontend_gems['world'])
        self.assertEqual([r['metal'] for r in result.frontend_geometry['physical_samples']],[True,False])
        with self.assertRaisesRegex(ValueError,'inside'):
            self.compile(dict(request,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[5,7,5])]))
    def test_real_rf_all_scientific_groups_have_source_derived_witnesses(self):
        import itertools
        from common.contracts.test_geometry_members import real_snapshot
        from msplatform.assembly.resolve_assembly import compile_assembly_layout
        from msplatform.components.geometry_members import assembly_geometry_members
        from msplatform.components.shape_query import query_members
        from msplatform.contracts.rigid_transform import RigidTransform, FramedPosition
        snapshot=real_snapshot();plan=snapshot['composition_plan'];frame=plan['recipe']['assembly_frame_id']
        snapshot['composition_plan']=compile_assembly_layout(plan['recipe'],plan['components'],local_scope=dict(instance_ids=['multipole'],research_scope='RF solids',boundary_assumptions='explicit selected scope'))
        members=assembly_geometry_members(snapshot);self.assertEqual(len(members),32)
        groups={(m['instance_id'],m['electrode_group_id']) for m in members};self.assertEqual(len(groups),8)
        witnesses=[]
        for instance,group in sorted(groups):
            selected=next(m for m in members if (m['instance_id'],m['electrode_group_id'])==(instance,group))
            shape=selected['shape'];self.assertEqual(shape['kind'],'rod')
            transform=RigidTransform.from_contract(selected['transform'])
            local=FramedPosition(selected['local_frame_id'],(*shape['center_xy_mm'],(shape['z_min_mm']+shape['z_max_mm'])/2))
            world=transform.transform_position(local).coordinates_mm
            center=[round(v+1000) for v in world];found=None
            for delta in itertools.product((-1,0,1),repeat=3):
                gu=[center[i]+delta[i] for i in range(3)]
                point=[v-1000 for v in gu]
                if query_members(members,point,frame_id=frame)=={'status':'interior','group':(instance,group)}:
                    found=gu;break
            self.assertIsNotNone(found,group)
            witnesses.append(dict(instance_id=instance,electrode_group_id=group,gu=found))
        assembly=SimpleNamespace(composition_plan=snapshot['composition_plan'],components_resolved=snapshot['components_resolved'],components_source=snapshot['components_source'])
        numerics=dict(representation='neutral_world_collision',domain=dict(frame_id=frame,minimum_mm=[-1000]*3,maximum_mm=[1000]*3),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=witnesses,void_witnesses=[[0,0,0]])
        before=copy.deepcopy(snapshot);result=generic_geometry.compile_generic_collision_geometry(assembly,numerics=numerics)
        self.assertEqual(snapshot,before);self.assertEqual(len(result.frontend_geometry['members']),32)
        self.assertEqual(len(result.frontend_geometry['electrode_mapping']),8)
        self.assertEqual(sum(row['metal'] for row in result.frontend_geometry['physical_samples']),8)
        self.assertEqual({(w['instance_id'],w['electrode_group_id']) for w in result.frontend_geometry['metal_witnesses']},groups)
        self.assertEqual(result.frontend_geometry['physical_samples'][-1]['metal'],False)
    def test_vacuum_and_boundary_refusals(self):
        with self.assertRaisesRegex(ValueError,'outside'): self.compile(dict(self.numerics,void_witnesses=[[5,5,5]]))
        with self.assertRaisesRegex(ValueError,'integer'): self.compile(dict(self.numerics,void_witnesses=[[-1,0,0]]))
        with self.assertRaisesRegex(ValueError,'native_zero_neumann'): self.compile(dict(self.numerics,boundary='grounded_faces'))

    def test_explicit_cut_void_and_metal_witnesses(self):
        self.member['shape']=dict(kind='difference',base=dict(kind='box',center_mm=[0,0,0],size_mm=[4,4,4]),tools=[dict(kind='cylinder',center_mm=[0,0,0],radius_mm=0.5,height_mm=6)])
        request=dict(self.numerics,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[6,5,5])],void_witnesses=[[5,5,5]])
        result=self.compile(request)
        self.assertEqual([row['metal'] for row in result.frontend_geometry['physical_samples']],[True,False])
        self.assertIn('surface=fractional',result.frontend_gems['world'])
        self.assertIn('notin { ',result.frontend_gems['world'])
        self.assertNotIn('notin_inside_or_on',result.frontend_gems['world'])
        with self.assertRaisesRegex(ValueError,'outside'): self.compile(dict(request,void_witnesses=[[6,5,5]]))
        with self.assertRaisesRegex(ValueError,'inside'): self.compile(dict(request,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[5,5,5])]))
