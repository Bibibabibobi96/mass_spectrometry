"""Actual test-owned registered component through public SIMION geometry compile."""
import copy
import unittest
from pathlib import Path
from common.contracts.test_support.registered_component import ensure_registered
from msplatform import assembly, components
from msplatform.backends.simion.operations import compile_geometry
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import STRUCTURAL_SEEDS

class RegisteredCollisionGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): ensure_registered()
    def test_two_instances_public_compile_and_source_tamper(self):
        a=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
        b=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':3}})
        def pose(x): return dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[x,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='second',project_id='toy_registered',transform=pose(10)),dict(instance_id='first',project_id='toy_registered',transform=pose(0))],connections=[])
        product=assembly.assemble(recipe,{'first':a,'second':b})
        numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-20,-20,-20],maximum_mm=[20,20,20]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='first',electrode_group_id='body',gu=[20,20,20]),dict(instance_id='second',electrode_group_id='body',gu=[30,20,20])],void_witnesses=[[0,0,0]])
        compiled=compile_geometry(product,numerics=numerics)
        self.assertEqual(len(compiled.frontend_geometry['physical_samples']),3)
        seed=dict(path=str(Path.cwd()/'seed.iob'),bytes=STRUCTURAL_SEEDS[1][0],sha256=STRUCTURAL_SEEDS[1][1]); root=Path.cwd()/'generic-plan-test'
        def plan(value):return plan_geometry_build(value,run_directory=root,seed_record=seed,native_path_resource=root/'native.lua')
        self.assertEqual([x['operation_id'] for x in plan(compiled).operations],['geometry_world','build_geometry','verify_geometry'])
        bad=copy.deepcopy(compiled);bad.frontend_geometry['source_snapshot']['components_source']['first']['width_mm']=9
        with self.assertRaises(ValueError):plan(bad)
        bad=copy.deepcopy(numerics);bad['metal_witnesses'][0]['gu']=[0,0,0]
        with self.assertRaises(ValueError):compile_geometry(product,numerics=bad)
        bad=copy.deepcopy(numerics);bad['metal_witnesses'].pop()
        with self.assertRaisesRegex(ValueError,'every canonical'):compile_geometry(product,numerics=bad)

    def test_real_owner_publication_with_inert_native_children(self):
        import json
        import os
        import sys
        import tempfile
        from unittest.mock import patch
        from common.contracts.test_support.sfi_scalar_owner_fixture import make_context
        from msplatform.backends.simion.operations import build_geometry
        from msplatform.backends.simion.resources import structural_seed_path
        from msplatform.execution.run_session import RunSession
        from msplatform.io.manifest_records import file_record, verify_record
        ensure_registered()
        component=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
        pose=dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='first',project_id='toy_registered',transform=pose)],connections=[])
        product=assembly.assemble(recipe,{'first':component})
        numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-5,-5,-5],maximum_mm=[5,5,5]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='first',electrode_group_id='body',gu=[5,5,5])],void_witnesses=[[0,0,0]])
        compiled=compile_geometry(product,numerics=numerics); observed=[]
        with tempfile.TemporaryDirectory(prefix='generic-geometry-owner-') as directory, patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''}):
            context,_,_=make_context(Path(directory)); policy=json.loads(context.stage_policy_path.read_text(encoding='utf-8'))
            policy['stages']['build_geometry']=copy.deepcopy(policy['stages']['track']);context.stage_policy_path.write_text(json.dumps(policy),encoding='utf-8')
            original=RunSession.run_process
            def inert(session,operation_id,**kwargs):
                observed.append(operation_id)
                seed=file_record(structural_seed_path(1),'required_evidence')
                plan=plan_geometry_build(compiled,run_directory=session.run_dir,seed_record=seed,native_path_resource=session.input_dir/'native_sources/native_run_path.lua')
                operation=next(row for row in plan.operations if row['operation_id']==operation_id)
                code='from pathlib import Path\n'
                for path in operation['outputs']:
                    if path.endswith('_surface_state.json'):
                        dimensions=compiled.frontend_geometry['dimensions']
                        pitch=compiled.frontend_geometry['pitch_mm']
                        state=dict(schema_version=1,mode='empty',grid=dimensions,pitch=[pitch]*3,
                                   scanned_nodes=dimensions[0]*dimensions[1]*dimensions[2],offset_nodes=0)
                        code+=f'Path({path!r}).write_text({json.dumps(state)!r},encoding="utf8")\n'
                    else:
                        code+=f'Path({path!r}).write_bytes(b"INERT TEST BYTES")\n'
                code+='print('+repr(operation['success_marker'])+')\n'
                return original(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_geometry',limits=kwargs['limits'],immutable_input_records=kwargs.get('immutable_input_records',()))
            with patch.object(RunSession,'run_process',new=inert):
                result=build_geometry(compiled,context=context)
            self.assertEqual(observed,['geometry_world','build_geometry','verify_geometry'])
            self.assertEqual(result.metadata['field_status'],'not_solved')
            for record in result.data_records.values():verify_record('inert geometry product',record)

    def test_fresh_process_explicit_registration_and_public_compile(self):
        import subprocess
        import sys
        import tempfile
        import msplatform
        src=str(Path(msplatform.__file__).resolve().parent.parent)
        tests=str(Path(__file__).resolve().parents[2])
        script=("import sys,unittest;sys.path[:0]=["+repr(src)+","+repr(tests)+"];"
            "from common.contracts.test_support.registered_component import ensure_registered;"
            "ensure_registered();ensure_registered();"
            "from common.contracts.test_generic_registered_collision import RegisteredCollisionGeometryTests;"
            "suite=unittest.TestSuite([RegisteredCollisionGeometryTests('test_two_instances_public_compile_and_source_tamper')]);"
            "r=unittest.TextTestRunner().run(suite);raise SystemExit(not r.wasSuccessful())")
        with tempfile.TemporaryDirectory(prefix='registered-geometry-cold-') as directory:
            result=subprocess.run([sys.executable,'-I','-B','-c',script],cwd=directory,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_rename_order_and_width_change_preserve_actual_bindings(self):
        def component(width):
            return components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':width}})
        def pose(x):
            return dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[x,0,0])
        def compile_case(left,right,width,reverse):
            rows=[dict(instance_id=left,project_id='toy_registered',transform=pose(0)),dict(instance_id=right,project_id='toy_registered',transform=pose(10))]
            if reverse: rows.reverse()
            recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=rows,connections=[])
            product=assembly.assemble(recipe,{left:component(width),right:component(3)})
            numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-20,-20,-20],maximum_mm=[20,20,20]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id=left,electrode_group_id='body',gu=[20,20,20]),dict(instance_id=right,electrode_group_id='body',gu=[30,20,20])],void_witnesses=[[0,0,0]])
            return compile_geometry(product,numerics=numerics)
        original=compile_case('first','second',2,False)
        reordered=compile_case('first','second',2,True)
        renamed=compile_case('renamed_first','renamed_second',2,True)
        reversed_names=compile_case('z_left','a_right',2,True)
        wider=compile_case('first','second',4,False)
        self.assertEqual(original.frontend_gems,reordered.frontend_gems)
        self.assertEqual(original.frontend_geometry['electrode_mapping'],reordered.frontend_geometry['electrode_mapping'])
        self.assertEqual(original.frontend_gems,renamed.frontend_gems)
        self.assertEqual([(row['instance_id'],row['electrode_group_id'],row['native_id']) for row in renamed.frontend_geometry['electrode_mapping']],[('renamed_first','body',1),('renamed_second','body',2)])
        def body(compiled, instance):
            mapping=compiled.frontend_geometry['electrode_mapping']
            native_id=next(row['native_id'] for row in mapping if row['instance_id']==instance and row['electrode_group_id']=='body')
            gem=compiled.frontend_gems['world']
            return gem.split('  e('+str(native_id)+') {\n',1)[1].split('\n  }\n',1)[0]
        self.assertEqual([(row['instance_id'],row['native_id']) for row in reversed_names.frontend_geometry['electrode_mapping']],[('a_right',1),('z_left',2)])
        self.assertEqual(body(original,'first'),body(reversed_names,'z_left'))
        self.assertEqual(body(original,'second'),body(reversed_names,'a_right'))
        self.assertNotEqual(original.frontend_gems,wider.frontend_gems)
        self.assertEqual(original.frontend_geometry['electrode_mapping'],wider.frontend_geometry['electrode_mapping'])
        self.assertNotEqual(original.frontend_geometry['source_snapshot']['components_resolved']['first'],wider.frontend_geometry['source_snapshot']['components_resolved']['first'])
