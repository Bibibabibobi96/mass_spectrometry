"""Portable synthetic published IP–MR field fixture; never native science."""
from __future__ import annotations
import copy
import json
import pathlib
import shutil
import struct
import sys
from contextlib import contextmanager
from dataclasses import asdict
from functools import partial
from unittest.mock import patch

from common.contracts import test_sfi_scalar_binding as sf, test_ip_mr_model as mf
from common.contracts.test_support import sfi_scalar_owner_fixture as owner_fixture
from msplatform.assembly.factory import assemble
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.ip_mr_scalar_basis import project_ip_mr_scalar_basis
from msplatform.backends.simion.model import compile_prepared_model, RF_IP_PHYSICS
from msplatform.backends.simion.mr_compiler import compile_complete_mr_geometry
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.components.catalog import resolve_component
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.run_session import RunSession
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact

def geometry_action(session, *, compiled):
    """One real owner with six inert children and canonical geometry outputs."""
    source=structural_seed_path(4)
    seed=session.declare_file(session.run_dir/'simion/geometry/iob_seed/4_instance_seed.iob','required_evidence')
    seed.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,seed)
    seed_record=file_record(session.canonical_path(seed),'required_evidence');session.add_input('structural_seed',seed_record)
    compiled_path=session.declare_file(session.input_dir/'compiled_geometry.json','required_evidence')
    compiled_path.write_text(json.dumps(asdict(compiled),allow_nan=False),encoding='utf8')
    compiled_record=file_record(session.canonical_path(compiled_path),'required_evidence');session.add_input('compiled_geometry',compiled_record)
    plan=plan_geometry_build(compiled,run_directory=session.run_dir,seed_record=seed_record,
                             native_path_resource=session.input_dir/'native_sources/native_run_path.lua')
    records={'compiled_geometry':compiled_record};native={};output_paths=[]
    for op in plan.operations:
        outputs=list(op['outputs'])
        optional=op.get('optional_surface')
        if optional is not None: outputs.append(optional)
        for output in outputs:
            path=pathlib.Path(output)
            session.declare_file(path,'required_evidence' if path.suffix in ('.csv','.fly2','.json') else 'solver_native_binary')
            path.parent.mkdir(parents=True,exist_ok=True)
        script='from pathlib import Path\n'
        for output in outputs:
            content=b"INERT_SYNTHETIC_NOT_NATIVE"
            if output.endswith('_surface_state.json'):
                role=op['operation_id'].removeprefix('geometry_')
                domain=compiled.frontend_geometry['numerical_domains'][role]
                state=dict(schema_version=1,mode='present',
                    grid=[domain['dimensions']['n'+axis] for axis in 'xyz'],
                    pitch=[domain['cell_mm_xyz'][axis] for axis in 'xyz'],
                    scanned_nodes=None,offset_nodes=None)
                content=json.dumps(state,allow_nan=False).encode('utf8')
            script+='Path('+repr(output)+').write_bytes('+repr(content)+')\n'
        script+='print('+repr(op['success_marker'])+')\n'
        session.run_process(op['operation_id'],executable=pathlib.Path(sys.executable),arguments=['-I','-B','-c',script],role='GATE',stage='inert_geometry',limits=None)
        if op['operation_id'].startswith('geometry_'):
            role=op['operation_id'].removeprefix('geometry_');native[role]={}
            labels=(('raw_geometry','surface_witnesses','surface_state','fractional_surface') if optional is not None
                    else ('raw_geometry','fractional_surface','surface_witnesses'))
            for label,path in zip(labels,outputs,strict=True):
                key=role+'_'+label;native[role][label]=key
                records[key]=file_record(session.canonical_path(path),'required_evidence' if label in {'surface_witnesses','surface_state'} else 'solver_native_binary')
        output_paths.extend(outputs)
    meta=dict(backend='simion',geometry_materialized=True,field_status='not_solved',source_status='not_requested',
              provider_content_identities=compiled.provider_content_identities,native_assets=native)
    return dict(status='success',summary={'fixture':'inert'},output_paths=output_paths,required_output_paths=output_paths,
                retention_preserve_paths=[],manifest_extra_fields={'products':{'geometry':dict(schema_version=1,kind='geometry_artifact',status='complete',metadata=meta,data=records)}})

def model_action(session, *, model, geometry_reference):
    source=open_artifact(geometry_reference,expected_kind='geometry_artifact')
    records={};native={};paths=[]
    def write(name,content,role='required_evidence'):
        path=session.declare_file(session.input_dir/name,role);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        record=file_record(session.canonical_path(path),role);session.add_input(name.replace('/','_'),record);return record
    records['compiled_model']=write('compiled_model.json',json.dumps(model.document).encode())
    from importlib.resources import files
    examples=files('msplatform.examples')
    for label,name in (('clock_authority','instrument_clock_authority_v1.json'),('instrument_epoch','instrument_epoch_v1.json')):
        records[label]=write('clock/'+name,(examples/name).read_bytes())
    records['source_manifest']=write('geometry_source_manifest.json',pathlib.Path(geometry_reference['manifest']['path']).read_bytes())
    for role,keys in source.metadata['native_assets'].items():
        native[role]={}
        for label,key in keys.items():
            suffix={'raw_geometry':'.pa#','fractional_surface':'.pa-surf','surface_witnesses':'_surface.csv','surface_state':'_surface_state.json'}[label]
            record=write('geometry/'+role+suffix,source.data_path(key).read_bytes(),'required_evidence' if label in {'surface_witnesses','surface_state'} else 'solver_native_binary')
            product_key=role+'_'+label;records[product_key]=record;native[role][label]=product_key
    meta=dict(backend='simion',drive_configured=True,geometry_materialized=True,field_status='not_solved',source_status='not_requested',native_assets=native)
    return dict(status='success',summary={'fixture':'inert'},output_paths=paths,required_output_paths=paths,retention_preserve_paths=[],
                manifest_extra_fields={'products':{'model':dict(schema_version=1,kind='prepared_model',status='complete',metadata=meta,data=records)}})

class RegisteredScalar(sf.SfiScalarAdmissionTests):
    def publish(self,name,kind,data,metadata,inputs=None,linked=None):
        return owner_fixture.publish_fixture(self.context,self.budget,self.retention,name=name.replace('_','-'),kind=kind,
                                              data=data,metadata=metadata,inputs=inputs,linked=linked)

def sample(case,name,request):
    """Use the existing public-product fixture format on a small covering grid."""
    source_data=dict(projection=case.projection,request=request,geometry_validation={'position_mm':1e-6},
        reopen_geometry={'vacuum_domains':[1]},reopen_solution={'solution':sf.SOLUTION},model=b'INERT_NOT_MPH')
    meta=dict(backend='comsol',scope='single_stationary_workpoint',field_status='solved',native_reopen_verified=True,solution=sf.SOLUTION)
    source=case.publish('solution-'+name,'field_solution',source_data,meta)
    artifact=open_artifact(source,expected_kind='field_solution')
    grid=dict(frame_id=case.projection['assembly_frame_id'],origin_mm=[-400.]*3,pitch_mm=[500.]*3,dimensions=[3]*3,
              block_points=4,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',point_count=27,maximum_mm=[600.]*3,coordinate_sanity_mm=1e-6)
    header=PaHeader(-2,1,10000.,3,3,3,1<<28,500.,500.,500.).pack()
    pa=header+bytes(27*8)
    valid=header+struct.pack('<27d',*([1.]*27))
    report=dict(status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,
        filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(artifact.data_path('model')),
        vacuum_domains=[1],fem_valid=27,invalid_count=0,solution_readback=sf.SOLUTION,
        coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'},**grid)
    data=dict(projection=case.projection,grid=grid,request=request,reopen_solution={'solution':sf.SOLUTION},
        geometry_validation={'position_mm':1e-6},reopen_geometry={'vacuum_domains':[1]},report=report,field_v=pa,field_valid=valid)
    return case.publish(name,'scalar_field_samples',data,dict(backend='comsol',scope='assembly_world_scalar_samples',field_status='sampled',frame_id=grid['frame_id']),
        linked={'field_solution_manifest':source['manifest'],'field_solution_model':artifact.data_records['model']})



def _domain(bounds, pitch):
    return dict(cell_mm_xyz=dict(zip('xyz', pitch)),
                pa_bounds_mm={a+s:bounds[i][j] for i,a in enumerate('xyz') for j,s in enumerate(('_min','_max'))})


def _fixture_geometry():
    from importlib.resources import files
    from msplatform.backends.simion.model import scientific_multipole_drive
    fixture=json.loads((mf.ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
    example=json.loads(files('msplatform.examples').joinpath('rf_oatof_functional_v1.json').read_text(encoding='utf8'))
    components={name:resolve_component(req) for name,req in fixture['component_requests'].items()}
    rf=resolve_component(example['component_requests']['multipole']);components['multipole']=rf
    recipe=copy.deepcopy(fixture['recipe'])
    recipe['instances'].insert(0,dict(instance_id='multipole',project_id='rf_multipole_ion_optics',transform=dict(
        schema_version=1,role='rigid_transform',from_frame_id=rf.assembly_interface['local_frame_id'],
        to_frame_id=recipe['assembly_frame_id'],rotation=[[0,-1,0],[0,0,1],[-1,0,0]],translation_mm=[0,-305.6,3])))
    recipe['connections'].insert(0,dict(connection_id='rf_to_ip',upstream=dict(instance_id='multipole',port_id='mechanical_exit'),
        downstream=dict(instance_id='ion_processor',port_id='guide_inlet'),gap_mm=1.,coupling_mode='monolithic_joint_solve'))
    assembly=assemble(recipe,components)
    domains={'ip':_domain([[-.1,190.6],[-3.6,3.6],[-3.6,3.6]],[.1]*3),
        'analyzer':_domain([[-63,63],[-142.5,458.5],[-325.5,325.5]],[.5]*3),
        'detector':_domain([[-26,25.5],[-87.5,-36.5],[94.5,97.5]],[.5]*3),
        'multipole':{'cell_mm_xyz':dict.fromkeys('xyz',.1)}}
    compiled=compile_complete_mr_geometry(assembly,numerics={'domains':domains})
    mf.IpMrModelTests.setUpClass();drive=copy.deepcopy(mf.IpMrModelTests.drive)
    drive['groups']={'multipole':scientific_multipole_drive(compiled.components_resolved['multipole'],compiled.frontend_geometry['electrode_bindings']['multipole'])}
    model=compile_prepared_model(compiled,compiled.components_resolved,drive=drive,physics=RF_IP_PHYSICS)
    return assembly,compiled,model


def _priority_records(root, assembly, compiled):
    """Derive test-only broadphase records; never assert native/CAD qualification."""
    from msplatform.components.geometry_members import assembly_geometry_members
    snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
    geometry=compiled.frontend_geometry
    boxes={'role':'test_only_numerical_boxes','assets':{}}
    for role in geometry['asset_components']:
        d=geometry['numerical_domains'][role];b=d['bounds_mm']
        boxes['assets'][role]=dict(bounds=[[b[a+'_min'],b[a+'_max']] for a in 'xyz'],pitch=[d['cell_mm_xyz'][a] for a in 'xyz'],pose=geometry['asset_poses'][role])
    def store(name,data):
        path=root/name;path.write_text(json.dumps(data,allow_nan=False),encoding='utf8');return file_record(path)
    source=store('test_source.json',{'assembly':snapshot});box_record=store('test_boxes.json',boxes)
    members=assembly_geometry_members(snapshot);assets=geometry['asset_components'];mr=assets['mrtof_analyzer'];detector=next(m for m in members if m['instance_id']==mr and m['electrode_group_id']=='detector')
    selected=[('ip_box_vs_mr',m) for m in members if m['instance_id']==mr]
    selected += [('detector_box_vs_analyzer',m) for m in members if m['instance_id']==mr and m['member_id']!=detector['member_id']]
    selected += [('ip_box_vs_rf',m) for m in members if m['instance_id']=='multipole']
    rows=[dict(comparison=tag,instance_id=m['instance_id'],member_id=m['member_id'],source_refs=m['source_refs'],electrode_group_id=m['electrode_group_id'],classification='broadphase_clear') for tag,m in selected]
    evidence={'role':'diagnostic_cad_numeric_box_foreign_metal','qualification':False,'boxes_sha256':box_record['sha256'],'source_sha256':source['sha256'],'cad_profile':{'length_error_bound_mm':1e-9},'rows':rows}
    # The production compiler independently computes every lower bound from these source shapes.
    return dict(source_record=source,boxes_record=box_record,clearance_record=store('test_clearance.json',evidence))


@contextmanager
def build_sampled_field_fixture(root):
    """Publish synthetic genuine artifacts; caller owns root and stage-policy changes."""
    from msplatform.backends.simion.ip_mr_field_execution import prepare_ip_mr_field_inputs
    root=pathlib.Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    assembly,compiled,model=_fixture_geometry();context,budget,retention=owner_fixture.make_context(root)
    evidence=_priority_records(root,assembly,compiled)
    plan=plan_geometry_build(compiled,run_directory=root/'geometry-plan',seed_record=file_record(structural_seed_path(4)),native_path_resource=root/'native_run_path.lua')
    ids=tuple(op['operation_id'] for op in plan.operations)
    result=run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='geometry_only',software=[]),run_id='20261114_000100__test__python__collision-geometry',payload={'action':'fixture_geometry'},committed_new_bytes=16777216,commitment_inputs=[budget],retention=retention,expected_operation_ids=ids,operation_dependencies={name:[ids[i-1]] for i,name in enumerate(ids) if i},action=partial(geometry_action,compiled=compiled),action_record=file_record(pathlib.Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
    geometry_ref={'manifest':result['manifest'],'product_id':'geometry'}
    result=run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='prepared_model',software=[]),run_id='20261114_000101__test__python__collision-model',payload={'action':'prepare_model','geometry':geometry_ref},committed_new_bytes=16777216,commitment_inputs=[budget],retention=retention,expected_operation_ids=(),operation_dependencies={},action=partial(model_action,model=model,geometry_reference=geometry_ref),action_record=file_record(pathlib.Path(__file__),'required_evidence'),source_references=[{'manifest_record':geometry_ref['manifest']}],completion_api=no_particle_batch_completion_api)
    model_ref={'manifest':result['manifest'],'product_id':'model'}
    snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
    projection=project_assembly_geometry(snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
    scalar=RegisteredScalar(methodName='runTest');scalar.context=context;scalar.budget=budget;scalar.retention=retention;scalar.snapshot=snapshot;scalar.projection=projection
    comsol_geometry=scalar.make_geometry();operator=dict(relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})
    bases=project_ip_mr_scalar_basis(model,assembly=assembly,projection=projection,operator=operator)
    vectors={'carrier':bases['carrier'],'rf_reference':bases['rf_reference']['request']};vectors.update({'ip_'+str(x['schedule_index']):x['request'] for x in bases['ip_unit_volt']})
    samples={name:sample(scalar,name,request) for name,request in vectors.items()};selection=dict(geometry_artifact=comsol_geometry,operator=operator,samples=samples)
    prepared=prepare_ip_mr_field_inputs(model_ref,scalar_field_basis=selection,priority_evidence=evidence,output_directory=root/'preflight')
    yield dict(context=context,budget=budget,retention=retention,model_reference=model_ref,scalar_field_basis=selection,priority_evidence=evidence,expected_operation_ids=prepared['expected_operation_ids'],prepared=prepared,stage_policy_path=context.stage_policy_path)


@contextmanager
def inert_native_leaf(observed, *, failure_operation=None, child_mutate=None, after_operation=None):
    """Preserve RunSession process guards and receipts while substituting only native executable."""
    original=RunSession.run_process
    def inert(session,operation_id,**kwargs):
        observed.append(operation_id);args=kwargs['arguments'];script='from pathlib import Path\n'
        if args.count('lua')!=1: raise ValueError('inert Lua transport arguments differ')
        lua_index=args.index('lua')
        if operation_id.startswith('collision_build_'):
            index=lua_index+2
            if len(args)-index not in (4,5) or args[index]!='build': raise ValueError('inert collision build arguments differ')
            out=pathlib.Path(args[index+2])
            if out.suffix!='.pa': raise ValueError('inert collision output is not a PA')
            script+=f'Path({str(out)!r}).write_bytes(b"INERT_PA")\nPath({str(out.with_suffix(".pa-surf"))!r}).write_bytes(b"INERT_SURFACE")\n';marker='RAW_COLLISION_BUILD=PASS nodes=27 metal_nodes=2 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False'
        elif operation_id.startswith('collision_verify_'):marker='RAW_COLLISION_VERIFY=PASS nodes=27 metal_nodes=2 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False'
        elif operation_id=='background_build':
            out=pathlib.Path(args[lua_index+2]);script+=f'Path({str(out)!r}).write_bytes(b"INERT_BACKGROUND")\n';marker='NUMERICAL_CARRIER_REOPEN=PASS'
        elif operation_id=='background_verify':marker='NUMERICAL_CARRIER_COLD_REOPEN=PASS'
        elif operation_id=='collision_iob_build':
            out=session.run_dir/'simion/collision/collision.iob';script+=f'Path({str(out)!r}).write_bytes(b"INERT_IOB")\nPath({str(out.with_suffix(".fly2"))!r}).write_text("particles{{coordinates=0,}}")\n';marker='IP_MR_COLLISION_IOB=PASS'
        else:marker='IP_MR_COLLISION_IOB_REOPEN=PASS'
        if child_mutate is not None and operation_id=='collision_build_01':
            script+=f'p=Path({str(child_mutate)!r});p.write_bytes(p.read_bytes()+b"X")\n'
        if operation_id==failure_operation:script+='raise SystemExit(7)\n'
        script+='print('+repr(marker)+')\n'
        receipt=original(session,operation_id,executable=pathlib.Path(sys.executable),arguments=['-I','-B','-c',script],role='GATE',stage='inert_field',limits=kwargs['limits'],immutable_input_records=kwargs.get('immutable_input_records',()))
        if after_operation is not None:after_operation(operation_id)
        return receipt
    with patch.object(RunSession,'run_process',new=inert):yield
