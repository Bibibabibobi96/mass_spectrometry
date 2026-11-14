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
        self.assembly=SimpleNamespace(composition_plan=dict(recipe=dict(assembly_frame_id='world'),scope=dict(instance_ids=['item']),components=dict(item={'project_id':'example'})),components_resolved={'item':{'size':2}},components_source={'item':{'size':2}})
        self.numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-5,-5,-5],maximum_mm=[5,5,5]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[5,5,5])],void_witnesses=[[0,0,0]])
    def compile(self, numerics=None):
        with patch('msplatform.backends.simion.assembly_geometry.assembly_geometry_members',return_value=[copy.deepcopy(self.member)]), patch('msplatform.backends.simion.generic_geometry.assembly_geometry_members',return_value=[copy.deepcopy(self.member)]):
            return generic_geometry.compile_generic_collision_geometry(self.assembly,numerics=numerics or self.numerics)
    def test_snapshot_plan_and_immutable_input(self):
        before=copy.deepcopy(self.assembly); result=self.compile(); self.assertEqual(before,self.assembly)
        self.assembly.components_source['item']['size']=7
        self.assertEqual(result.frontend_geometry['source_snapshot']['components_source']['item']['size'],2)
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
    def test_vacuum_and_boundary_refusals(self):
        with self.assertRaisesRegex(ValueError,'outside'): self.compile(dict(self.numerics,void_witnesses=[[5,5,5]]))
        with self.assertRaisesRegex(ValueError,'integer'): self.compile(dict(self.numerics,void_witnesses=[[-1,0,0]]))
        with self.assertRaisesRegex(ValueError,'native_zero_neumann'): self.compile(dict(self.numerics,boundary='grounded_faces'))

    def test_explicit_cut_void_and_metal_witnesses(self):
        self.member['shape']=dict(kind='difference',base=dict(kind='box',center_mm=[0,0,0],size_mm=[4,4,4]),tools=[dict(kind='cylinder',center_mm=[0,0,0],radius_mm=0.5,height_mm=6)])
        request=dict(self.numerics,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[6,5,5])],void_witnesses=[[5,5,5]])
        result=self.compile(request)
        self.assertEqual([row['metal'] for row in result.frontend_geometry['physical_samples']],[True,False])
        with self.assertRaisesRegex(ValueError,'outside'): self.compile(dict(request,void_witnesses=[[6,5,5]]))
        with self.assertRaisesRegex(ValueError,'inside'): self.compile(dict(request,metal_witnesses=[dict(instance_id='item',electrode_group_id='body',gu=[5,5,5])]))
