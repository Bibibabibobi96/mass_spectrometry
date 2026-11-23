"""Compiler-only multi-domain tests through real registered RF providers."""
import copy
import unittest

from msplatform import assembly, components, examples
from msplatform.backends.simion.assembly_geometry import _pieces
from msplatform.backends.simion.operations import compile_geometry
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.components.shape_query import query_members
from msplatform.contracts.rigid_transform import RigidTransform


def product(names=('left', 'right'), *, reverse=False, radius=4.0):
    example=examples.load_example('rf_oatof_functional_v1')
    requests=[]
    for index in range(2):
        request=copy.deepcopy(example.component_requests['multipole'])
        if index==0: request['design']['geometry_mm']['inscribed_radius_r0']=radius
        requests.append(request)
    parts={name:components.resolve_component(requests[i]) for i,name in enumerate(names)}
    rows=[]
    for i,name in enumerate(names):
        rows.append(dict(instance_id=name,project_id='rf_multipole_ion_optics',transform=dict(
            schema_version=1,role='rigid_transform',from_frame_id='multipole.cartesian.z_axis.v1',
            to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[i*200,0,0])))
    if reverse: rows.reverse()
    recipe=dict(schema_version=1,role='assembly_recipe',integration_id='multi_rf',recipe_id='multi_rf',
        assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=rows,connections=[])
    return assembly.assemble(recipe,parts)


def declaration(value):
    snapshot=dict(composition_plan=value.composition_plan,components_resolved=value.components_resolved,components_source=value.components_source)
    members=assembly_geometry_members(snapshot); result=[]
    poses={x['instance_id']:x['transform']['translation_mm'][0] for x in value.composition_plan['recipe']['instances']}
    for name in sorted(poses):
        owned=[m for m in members if m['instance_id']==name]; origin=[poses[name]-25,-25,-5]
        groups=sorted({m['electrode_group_id'] for m in owned});witnesses=[]
        for group in groups:
            candidates=[m for m in owned if m['electrode_group_id']==group]; found=None
            for m in candidates:
                for _,_,lo,hi in _pieces(m['shape'],RigidTransform.from_contract(m['transform']),[]):
                    gu=[round((lo[i]+hi[i])/2-origin[i]) for i in range(3)]
                    pos=[origin[i]+gu[i] for i in range(3)]
                    if query_members(owned,pos,frame_id='world')=={'status':'interior','group':(name,group)}:
                        found=gu;break
                if found is not None:break
            if found is None: raise AssertionError('no grid witness for '+group)
            witnesses.append(dict(instance_id=name,electrode_group_id=group,gu=found))
        result.append(dict(domain_id=name,owner_instance_id=name,member_ids=sorted(m['member_id'] for m in owned),
            domain=dict(frame_id='world',minimum_mm=origin,maximum_mm=[origin[0]+50,25,85]),pitch_mm=1,
            boundary='native_zero_neumann',metal_witnesses=witnesses,void_witnesses=[[0,0,0]]))
    return dict(representation='neutral_multi_domain_collision',domains=result)


class NeutralMultiDomainCompilerTests(unittest.TestCase):
    def test_real_rf_partition_identity_and_fail_closed(self):
        source=product(); request=declaration(source); original=copy.deepcopy(request)
        compiled=compile_geometry(source,numerics=request)
        geo=compiled.frontend_geometry
        self.assertEqual(request,original)
        self.assertEqual(geo['domain_order'],['left','right'])
        self.assertEqual(set(compiled.frontend_gems),{'left','right'})
        from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
        drive=dict(groups={name:{group:dict(kind='static',voltage_v=float(i)) for group in geo['domains'][name]['electrode_groups']} for i,name in enumerate(geo['domain_order'])},clock=dict(clock_epoch_id='test',authority_sha256='0'*64,phase_reference_instrument_time_us=0))
        model=compile_prepared_model(compiled,source.components_resolved,drive=drive,physics=RF_PHYSICS)
        for row in model.document['native_drive_rows']:
            self.assertEqual(row['native_targets'][0]['domain'], 'domain_01' if row['instance_id']=='left' else 'domain_02')
        self.assertEqual(len(model.document['native_drive_rows']),16)
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        with self.assertRaisesRegex(ValueError,'published sampled FieldBundle'):
            plan_tracking_execution(model,particles=None,clock_records={},propagation={},observations={},numerics={})
        from types import SimpleNamespace
        from pathlib import Path
        from msplatform.backends.simion.neutral_sampled_field import neutral_multi_background_grid
        from msplatform.backends.simion.rf_tracking_execution import plan_neutral_sampled_tracking_workbench
        grid=dict(frame_id='world',origin_mm=[-30,-30,-10],dimensions=[261,61,101],pitch_mm=[1,1,1])
        binding=dict(grid=grid);self.assertEqual(neutral_multi_background_grid(model,binding),grid)
        bad_grid=copy.deepcopy(binding);bad_grid['grid']['dimensions'][0]=100
        with self.assertRaisesRegex(ValueError,'enclose'):neutral_multi_background_grid(model,bad_grid)
        root=Path.cwd()/'multi-track-plan'
        tasks=[dict(role=name,source_records={'surface_witnesses':{'path':str(root/(name+'.csv'))},'surface_state':{'path':str(root/(name+'.json'))}}) for name in geo['domain_order']]
        keys=['background','collision_01','collision_02'];records={key:dict(path=str(root/(key+'.pa')),bytes=1,sha256='a'*64) for key in keys}
        source=SimpleNamespace(data_records=records,data_path=lambda key:Path(records[key]['path']),metadata={'collision_assets':{'left':{'collision':'collision_01'},'right':{'collision':'collision_02'}}})
        admission=dict(source=source,basis=binding,plan={'geometry_plan':{'tasks':tasks}},model=model)
        birth=dict(position_x_mm='0',position_y_mm='0',position_z_mm='0',velocity_x_m_s='0',velocity_y_m_s='0',velocity_z_m_s='0',mass_amu='1',charge_state='1')
        workbench=plan_neutral_sampled_tracking_workbench(compiled,admission=admission,run_directory=root,program='-- inert',native_source_rows=[birth],native_path_resource=root/'native.lua')
        spec=workbench.materializations[str(root/'inputs/tracking_iob.lua')]
        self.assertIn('neutral_multi_sampled_tracking_iob',spec);self.assertIn('3_instance_seed.iob',spec)
        self.assertIn('domain_01',spec);self.assertIn('domain_02',spec)
        from pathlib import Path
        from msplatform.backends.simion.native_plans import plan_model_preparation
        from msplatform.backends.simion.resources import STRUCTURAL_SEEDS
        root=Path.cwd()/'multi-model-plan'; seed=dict(path=str(root/'seed.iob'),bytes=STRUCTURAL_SEEDS[2][0],sha256=STRUCTURAL_SEEDS[2][1])
        def record(name):return dict(path=str(root/name),bytes=1,sha256='a'*64)
        assets={name:dict(raw_record=record(name+'.pa#'),surface_records=[],witness_record=record(name+'.csv'),state_record=record(name+'.json')) for name in geo['domain_order']}
        model_plan=plan_model_preparation(model,geometry_assets=assets,run_directory=root,seed_record=seed,native_path_resource=root/'native.lua')
        self.assertEqual([x['operation_id'] for x in model_plan.operations],['materialize_geometry','build_model','verify_model'])
        self.assertIn('neutral_multi_model_iob_build',model_plan.materializations[str(root/'inputs/geometry_iob.lua')])
        self.assertEqual(model_plan.operations[1]['success_marker'],'NEUTRAL_MULTI_MODEL_BUILD=PASS')
        with self.assertRaises(ValueError):plan_model_preparation(model,geometry_assets={'left':assets['left']},run_directory=root,seed_record=seed,native_path_resource=root/'native.lua')
        from pathlib import Path
        from msplatform.backends.simion.generic_geometry import seal_multi_domain_geometry_for_publication, validate_published_multi_domain_geometry, multi_domain_source_paths
        from msplatform.backends.simion.native_plans import plan_geometry_build
        from msplatform.backends.simion.resources import STRUCTURAL_SEEDS
        sealed=seal_multi_domain_geometry_for_publication(compiled); validate_published_multi_domain_geometry(sealed)
        paths=multi_domain_source_paths(sealed)
        self.assertIn('msplatform.components.cad_geometry',paths)
        seed=dict(path=str(Path.cwd()/'seed.iob'),bytes=STRUCTURAL_SEEDS[2][0],sha256=STRUCTURAL_SEEDS[2][1])
        root=Path.cwd()/'multi-domain-plan'
        def plan(value,seed_value=seed):return plan_geometry_build(value,run_directory=root,seed_record=seed_value,native_path_resource=root/'native.lua')
        planned=plan(sealed)
        self.assertEqual([x['operation_id'] for x in planned.operations],['geometry_domain_01','geometry_domain_02','build_geometry','verify_geometry'])
        self.assertEqual([x['asset_id'] for x in planned.operations[:2]],['left','right'])
        self.assertIn('2_instance_seed.iob',planned.input_copies[0]['destination'])
        self.assertNotIn('background',str(planned.materializations))
        for mutation in ('gem','domain','proof'):
            bad=copy.deepcopy(sealed)
            if mutation=='gem':bad.frontend_gems['left']+='\n; altered'
            elif mutation=='domain':bad.frontend_geometry['domains']['left']['dimensions'][0]+=1
            else:bad.frontend_geometry['producer_validated_members']['members'].pop()
            with self.subTest(producer_tamper=mutation),self.assertRaises(ValueError):plan(bad)
        with self.assertRaises(ValueError):plan(sealed,dict(seed,sha256='0'*64))
        for name in geo['domain_order']:
            row=geo['domains'][name]
            self.assertEqual(len(row['member_ids']),32)
            self.assertEqual(len(row['electrode_groups']),8)
            self.assertEqual(len(row['electrode_mapping']),8)
            self.assertEqual({m['instance_id'] for m in row['members']},{name})
        reordered=product(reverse=True); other=compile_geometry(reordered,numerics=list_reversed(request))
        self.assertEqual(compiled.frontend_gems,other.frontend_gems)
        for name in geo['domain_order']:
            for key in ('member_ids','electrode_groups','electrode_mapping','physical_samples','domain','dimensions'):
                self.assertEqual(geo['domains'][name][key],other.frontend_geometry['domains'][name][key])
        self.assertEqual(geo['domain_order'],other.frontend_geometry['domain_order'])
        changed=product(radius=4.5); changed_geo=compile_geometry(changed,numerics=declaration(changed))
        self.assertNotEqual(compiled.frontend_gems['left'],changed_geo.frontend_gems['left'])
        self.assertEqual(compiled.frontend_gems['right'],changed_geo.frontend_gems['right'])
        renamed=product(('alpha','beta')); ren=compile_geometry(renamed,numerics=declaration(renamed))
        self.assertEqual(ren.frontend_geometry['domain_order'],['alpha','beta'])
        for mutation in ('instance','member','duplicate','foreign','overlap'):
            bad=copy.deepcopy(request)
            if mutation=='instance':bad['domains'].pop()
            elif mutation=='member':bad['domains'][0]['member_ids'].pop()
            elif mutation=='duplicate':bad['domains'][0]['member_ids'].append(bad['domains'][0]['member_ids'][0])
            elif mutation=='foreign':bad['domains'][0]['metal_witnesses'][0]['instance_id']='right'
            else:bad['domains'][0]['domain']['maximum_mm'][0]=200
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):compile_geometry(source,numerics=bad)

    def test_one_group_spans_two_complete_member_domains(self):
        from msplatform.components.registry import ProviderDescriptor, register_provider
        from tests.contracts.test_support import registered_component as toy
        from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
        def resolve(source,profile):
            resolved,interface=toy.resolve(source,profile);interface['project_id']='toy_split_member';return resolved,interface
        def validate(source,resolved,interface):
            if resolve(source,interface.get('geometry_profile_id')) != (resolved,interface):raise ValueError('split source differs')
        def members(resolved,interface):
            return [dict(member_id=name,electrode_group_id='body',shape=dict(kind='box',center_mm=[x,0,0],size_mm=[2,2,2]),source_refs=['/width_mm'],local_frame_id='toy_local',length_unit='mm',representation_role='physical_solid') for name,x in [('first',-5),('second',5)]]
        register_provider(ProviderDescriptor('toy_split_member','toy_split_member',resolve,validate,members,('tests.contracts.test_neutral_multi_domain',)))
        part=components.resolve_component({'provider_id':'toy_split_member','design':{'width_mm':2}})
        pose=dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='split',recipe_id='split',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='component',project_id='toy_split_member',transform=pose)],connections=[])
        design=assembly.assemble(recipe,{'component':part})
        def entry(name,member,lo,hi):return dict(domain_id=name,owner_instance_id='component',member_ids=[member],domain=dict(frame_id='world',minimum_mm=[lo,-3,-3],maximum_mm=[hi,3,3]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='component',electrode_group_id='body',gu=[4,3,3])],void_witnesses=[[0,0,0]])
        request=dict(representation='neutral_multi_domain_collision',domains=[entry('alpha','first',-9,-1),entry('beta','second',1,9)])
        compiled=compile_geometry(design,numerics=request)
        self.assertEqual([compiled.frontend_geometry['domains'][name]['electrode_groups'] for name in ('alpha','beta')],[['body'],['body']])
        drive=dict(groups={'component':{'body':dict(kind='static',voltage_v=0.)}},clock=dict(clock_epoch_id='test',authority_sha256='0'*64,phase_reference_instrument_time_us=0))
        model=compile_prepared_model(compiled,design.components_resolved,drive=drive,physics=RF_PHYSICS)
        self.assertEqual(model.document['native_drive_rows'][0]['native_targets'],[dict(domain='domain_01',electrode_id=1),dict(domain='domain_02',electrode_id=1)])
        reversed_request=copy.deepcopy(request);reversed_request['domains'].reverse()
        self.assertEqual(compiled,compile_geometry(design,numerics=reversed_request))
        from pathlib import Path
        from msplatform.backends.simion.generic_geometry import seal_multi_domain_geometry_for_publication, validate_published_multi_domain_geometry
        from msplatform.backends.simion.native_plans import plan_geometry_build
        from msplatform.backends.simion.resources import STRUCTURAL_SEEDS, structural_seed_path
        sealed=seal_multi_domain_geometry_for_publication(compiled);validate_published_multi_domain_geometry(sealed)
        root=Path.cwd()/'split-plan';seed=dict(path=str(root/'seed.iob'),bytes=STRUCTURAL_SEEDS[2][0],sha256=STRUCTURAL_SEEDS[2][1])
        plan=plan_geometry_build(sealed,run_directory=root,seed_record=seed,native_path_resource=root/'native.lua')
        self.assertEqual([row['asset_id'] for row in plan.operations[:2]],['alpha','beta'])
        self.assertTrue(structural_seed_path(10).is_file())
        with self.assertRaisesRegex(ValueError,'structural seed count'):structural_seed_path(11)
        for mutate in ('missing','duplicate','foreign','owner','overlap'):
            bad=copy.deepcopy(request)
            if mutate=='missing':bad['domains'].pop()
            elif mutate=='duplicate':bad['domains'][1]['member_ids']=['first']
            elif mutate=='foreign':bad['domains'][1]['member_ids']=['unknown']
            elif mutate=='owner':bad['domains'][1]['owner_instance_id']='foreign'
            else:bad['domains'][0]['domain']['maximum_mm'][0]=1
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):compile_geometry(design,numerics=bad)

    def test_mixed_solid_and_ideal_surface_refuses_without_omission(self):
        from msplatform.components.registry import ProviderDescriptor, register_provider
        from tests.contracts.test_support import registered_component as toy
        def resolve(source,profile):
            resolved,interface=toy.resolve(source,profile);interface['project_id']='toy_mixed_surface';return resolved,interface
        def validate(source,resolved,interface):
            if resolve(source,interface.get('geometry_profile_id')) != (resolved,interface):raise ValueError('mixed source differs')
        def members(resolved,interface):
            solid=toy.members(resolved,interface)[0]
            sheet=dict(member_id='sheet',electrode_group_id='body',shape=dict(kind='box',center_mm=[0,0,3],size_mm=[2,2,0]),source_refs=['/width_mm'],local_frame_id='toy_local',length_unit='mm',representation_role='ideal_surface')
            return [solid,sheet]
        register_provider(ProviderDescriptor('toy_mixed_surface','toy_mixed_surface',resolve,validate,members,('tests.contracts.test_neutral_multi_domain',)))
        part=components.resolve_component({'provider_id':'toy_mixed_surface','design':{'width_mm':2}})
        pose=dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='mixed',recipe_id='mixed',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='component',project_id='toy_mixed_surface',transform=pose)],connections=[])
        design=assembly.assemble(recipe,{'component':part})
        snapshot=dict(composition_plan=design.composition_plan,components_resolved=design.components_resolved,components_source=design.components_source)
        self.assertEqual({m['representation_role'] for m in assembly_geometry_members(snapshot)},{'physical_solid','ideal_surface'})
        domain=dict(frame_id='world',minimum_mm=[-5,-5,-5],maximum_mm=[8,5,5]);witness=[dict(instance_id='component',electrode_group_id='body',gu=[5,5,5])]
        multi=dict(representation='neutral_multi_domain_collision',domains=[dict(domain_id='whole',owner_instance_id='component',member_ids=['body'],domain=domain,pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=witness,void_witnesses=[[0,0,0]])])
        world=dict(representation='neutral_world_collision',domain=domain,pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=witness,void_witnesses=[[0,0,0]])
        for numerics in (multi,world):
            with self.subTest(representation=numerics['representation']),self.assertRaisesRegex(ValueError,'unsupported GEM representation: ideal_surface'):
                compile_geometry(design,numerics=numerics)

    def test_generated_program_preserves_three_slots_and_sample_grid(self):
        from tests.contracts.test_simion_rf_tracking import plan_case
        from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
        from msplatform.backends.simion.rf_tracking_program import render_rf_controls
        from msplatform.backends.simion.resources import native_resource_path
        source=product();compiled=compile_geometry(source,numerics=declaration(source));geo=compiled.frontend_geometry
        drive=dict(groups={name:{group:dict(kind='static',voltage_v=0.) for group in geo['domains'][name]['electrode_groups']} for name in geo['domain_order']},clock=dict(clock_epoch_id='test',authority_sha256='0'*64,phase_reference_instrument_time_us=0))
        model=compile_prepared_model(compiled,source.components_resolved,drive=drive,physics=RF_PHYSICS)
        _,_,_,plan=plan_case();plan['flight']['tracking_kind']='neutral_sampled'
        grid=dict(frame_id='world',origin_mm=[-30,-30,-10],dimensions=[261,61,101],pitch_mm=[1,1,1]);records={'field_v':{'path':'field.pa'},'field_valid':{'path':'mask.pa'}}
        basis=dict(role='generic_linear_scalar_admission',model_identity_sha256=model.document['model_identity_sha256'],grid=grid,bases={'one':dict(grid=grid,records=records,ideal_sheet_projection=[])},weights={'one':[]})
        resources={name:native_resource_path(name).read_text(encoding='utf8') for name in ('scalar_field_adapter.lua','generic_scalar_field.lua')}
        result=render_rf_controls(model,plan,assets={},native_sources=resources,scalar_bindings=basis,slot_domains=[None,'domain_01','domain_02'])
        self.assertIn('ion_instance==3',result['program']);self.assertIn('domain_01',result['program']);self.assertIn('domain_02',result['program'])
        self.assertIn('static_world_min={-30,-30,-10}',result['program']);self.assertIn('static_world_max={230,30,90}',result['program'])
        with self.assertRaisesRegex(ValueError,'collision slots'):
            render_rf_controls(model,plan,assets={},native_sources=resources,scalar_bindings=basis,slot_domains=[None,'domain_02','domain_01'])

    def test_public_build_owner_publishes_each_domain(self):
        import json
        import os
        import sys
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context
        from msplatform.backends.simion.generic_geometry import multi_domain_source_paths
        from msplatform.backends.simion.native_plans import plan_geometry_build
        from msplatform.backends.simion.operations import build_geometry
        from msplatform.backends.simion.resources import structural_seed_path
        from msplatform.execution.run_session import RunSession
        from msplatform.io.manifest_records import file_record, verify_record
        source=product();compiled=compile_geometry(source,numerics=declaration(source));observed=[];guards=[]
        provider_paths={str(p.resolve()) for p in multi_domain_source_paths(compiled).values()}
        with tempfile.TemporaryDirectory(prefix='multi-geometry-owner-') as directory, patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''}):
            context,_,_=make_context(Path(directory));policy=json.loads(context.stage_policy_path.read_text(encoding='utf8'))
            policy['stages']['build_geometry']=copy.deepcopy(policy['stages']['track']);context.stage_policy_path.write_text(json.dumps(policy),encoding='utf8')
            original=RunSession.run_process
            def inert(session,operation_id,**kwargs):
                observed.append(operation_id);guards.append({str(Path(row['path']).resolve()) for row in kwargs.get('immutable_input_records',())})
                seed=file_record(structural_seed_path(2),'required_evidence')
                plan=plan_geometry_build(compiled,run_directory=session.run_dir,seed_record=seed,native_path_resource=session.input_dir/'native_sources/native_run_path.lua')
                op=next(row for row in plan.operations if row['operation_id']==operation_id)
                code='from pathlib import Path\n'
                for path in op['outputs']:
                    if path.endswith('_surface_state.json'):
                        geometry=compiled.frontend_geometry['domains'][op['asset_id']];dims=geometry['dimensions'];pitch=geometry['pitch_mm']
                        state=dict(schema_version=1,mode='empty',grid=dims,pitch=[pitch]*3,scanned_nodes=dims[0]*dims[1]*dims[2],offset_nodes=0)
                        code+=f'Path({path!r}).write_text({json.dumps(state)!r},encoding="utf8")\n'
                    else:code+=f'Path({path!r}).write_bytes(b"INERT TEST BYTES")\n'
                code+='print('+repr(op['success_marker'])+')\n'
                return original(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_geometry',limits=kwargs['limits'],immutable_input_records=kwargs.get('immutable_input_records',()))
            with patch.object(RunSession,'run_process',new=inert):result=build_geometry(compiled,context=context)
            self.assertEqual(observed,['geometry_domain_01','geometry_domain_02','build_geometry','verify_geometry'])
            self.assertEqual(set(result.metadata['native_assets']),{'left','right'})
            self.assertEqual((result.metadata['refine_calls'],result.metadata['fly_calls']),(0,0))
            for guarded in guards:
                self.assertTrue(provider_paths <= guarded)
                for name in multi_domain_source_paths(compiled):
                    self.assertTrue(any(Path(path).name=='provider_'+name.replace('.','_')+'.py' for path in guarded))
            for record in result.data_records.values():verify_record('inert geometry product',record)


def list_reversed(request):
    value=copy.deepcopy(request);value['domains'].reverse();return value
