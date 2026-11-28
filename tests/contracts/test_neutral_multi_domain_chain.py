"""Synthetic public two-RF consumer; native leaves inert, no physical qualification."""
import copy
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.contracts import test_neutral_multi_domain as two_rf
from tests.contracts.test_sfi_scalar_binding import SOLUTION
from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(os.name=='nt','Windows owner process guard required')
class NeutralMultiDomainChainTests(unittest.TestCase):
    def test_public_two_rf_geometry_model_field_and_tracking(self):
        from tests.contracts import test_execution_runtime as owner_fixture
        from tests.contracts.test_simion_rf_tracking import rf_tracking_case
        from msplatform.execution.owner import run_managed_stage
        from msplatform.execution.completion import no_particle_batch_completion_api
        from msplatform.results.artifacts import open_artifact
        product=two_rf.product();compiled=operations.compile_geometry(product,numerics=two_rf.declaration(product));geo=compiled.frontend_geometry
        snapshot=dict(composition_plan=product.composition_plan,components_resolved=product.components_resolved,components_source=product.components_source)
        projection=project_assembly_geometry(snapshot,outer_box_mm={'min':[-50,-50,-20],'max':[250,50,100]})
        operator=dict(relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})
        groups={}; voltages=[]; weights=[]
        for name in geo['domain_order']:
            groups[name]={}
            for i,group in enumerate(geo['domains'][name]['electrode_groups']):
                sign=1 if i%2==0 else -1
                groups[name][group]=dict(kind='rf',waveform='cosine',frequency_hz=1e6,phase_rad=0.,rf_amplitude_v=1.,polarity=sign,common_mode_v=0.,dc_v=0.)
                voltages.append(dict(instance_id=name,electrode_group_id=group,voltage_v=float(sign)))
                weights.append(dict(instance_id=name,electrode_group_id=group,weight=float(sign)))
        for row in weights:row['weight']/=len(weights)
        request=validate_request(projection,dict(group_voltages=voltages,**operator))
        dims=[29,11,13];pitch=[10.,10.,10.];origin=[-40.,-50.,-20.];count=dims[0]*dims[1]*dims[2]
        grid=dict(frame_id='world',origin_mm=origin,pitch_mm=pitch,dimensions=dims,block_points=100,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',point_count=count,maximum_mm=[origin[i]+(dims[i]-1)*pitch[i] for i in range(3)],coordinate_sanity_mm=1e-6)
        header=PaHeader(-2,1,10000.,*dims,1<<28,*pitch).pack();field=header+struct.pack('<'+str(count)+'d',*([0.]*count));mask=header+struct.pack('<'+str(count)+'d',*([1.]*count))
        calls=[];guards=[]
        with tempfile.TemporaryDirectory(prefix='multi-rf-chain-') as directory,patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''}):
            context,_,_=make_context(Path(directory))
            from msplatform.storage import ArtifactStore
            store = ArtifactStore(Path(directory)/'store')
            policy=json.loads(context.stage_policy_path.read_text(encoding='utf8'))
            for name in ('build_geometry','prepare_model','solve_fields'):policy['stages'][name]=copy.deepcopy(policy['stages']['track'])
            policy['stages']['solve_fields']['limits']['reserved_run_payload_bytes']=20*1024*1024;policy['stages']['solve_fields']['limits']['transient_run_directory_bytes']=20*1024*1024
            context.stage_policy_path.write_text(json.dumps(policy),encoding='utf8')
            helper=owner_fixture.NormalOwnerTests();counter=[0]
            def publish(kind,data,metadata,*,payload,linked=None,sources=()):
                counter[0]+=1
                def action(session):
                    records={};outputs=[]
                    for name,value in data.items():
                        suffix='.pa' if name in ('field_v','field_valid') else '.bin' if isinstance(value,bytes) else '.json'
                        target=session.declare_file(session.result_dir/(name+suffix),'required_evidence');target.write_bytes(value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode());records[name]=file_record(session.canonical_path(target),'required_evidence');outputs.append(str(target))
                    for name,record in (linked or {}).items():
                        session.add_input(name,record)
                        if name in {'field_solution_manifest','prepared_manifest'}:records[name]=record
                    product_id={'field_solution':'solution','prepared_model':'model'}.get(kind,'product')
                    return dict(status='success',summary={'fixture':'INERT_ONLY'},output_paths=outputs,required_output_paths=outputs,retention_preserve_paths=[],manifest_extra_fields={'products':{product_id:dict(schema_version=1,kind=kind,status='complete',metadata=metadata,data=records)}})
                args=helper._arguments(Path(directory),action);args.update(run_id=f'20261116_1200{counter[0]:02d}__analysis__python__fixture',payload=payload,action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api,source_references=[{'manifest_record':ref['manifest']} for ref in sources]);result=run_managed_stage(context,**args)
                return open_artifact({'manifest':result['manifest'],'product_id':{'field_solution':'solution','prepared_model':'model'}.get(kind,'product')},expected_kind=kind)
            geometry_sample=publish('geometry_artifact',{'projection':projection},dict(backend='comsol',scope='geometry_only',native_reopen_verified=True),payload={'action':'build_comsol_geometry','assembly':snapshot,'projection':projection})
            prepared=publish('prepared_model',{'geometry_manifest':geometry_sample.reference['manifest']},
                dict(backend='comsol',scope='assembly_electrostatic_unsolved',geometry_source_reference=geometry_sample.reference),payload={'action':'fixture_model'})
            solution_data={'projection':projection,'request':request,'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'reopen_solution':{'solution':SOLUTION},'model':b'inert model'}
            solution=publish('field_solution',solution_data,dict(backend='comsol',scope='single_stationary_workpoint',field_status='solved',native_reopen_verified=True,solution=SOLUTION,
                stationary_source={'reference':prepared.reference,'kind':'prepared_model'}),payload={'action':'fixture_stationary'},linked={'prepared_manifest':prepared.reference['manifest']})
            report=dict(status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(solution.data_path('model')),vacuum_domains=[1],fem_valid=count,invalid_count=0,solution_readback=SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'},**grid)
            sample=publish('scalar_field_samples',dict(projection=projection,grid=grid,request=request,reopen_solution={'solution':SOLUTION},geometry_validation={'position_mm':1e-6},reopen_geometry={'vacuum_domains':[1]},report=report,field_v=field,field_valid=mask),dict(backend='comsol',scope='assembly_world_scalar_samples',field_status='sampled',frame_id='world'),payload={'action':'fixture_scalar'},linked={'field_solution_manifest':solution.reference['manifest'],'field_solution_model':solution.data_records['model']},sources=(solution.reference,))
            selection=dict(geometry_artifact=geometry_sample.reference,operator=operator,samples={'rf':dict(reference=sample.reference,request=request,weights=weights)})
            original=RunSession.run_process
            def inert(session,operation_id,*,immutable_input_records=(),**kwargs):
                if kwargs['role']!='SIMION':return original(session,operation_id,immutable_input_records=immutable_input_records,**kwargs)
                calls.append(operation_id);guards.append((operation_id,{str(Path(row['path']).resolve()) for row in immutable_input_records}));run=session.run_dir;code='from pathlib import Path\nimport json\n'
                if operation_id.startswith('geometry_domain_'):
                    seed=file_record(structural_seed_path(2),'required_evidence');plan=plan_geometry_build(compiled,run_directory=run,seed_record=seed,native_path_resource=session.input_dir/'native_sources/native_run_path.lua');op=next(row for row in plan.operations if row['operation_id']==operation_id);domain=geo['domains'][op['asset_id']];d=domain['dimensions'];p=domain['pitch_mm'];state=dict(schema_version=1,mode='present',grid=d,pitch=[p]*3,scanned_nodes=None,offset_nodes=None)
                    for path in op['outputs']:
                        code+=f'p=Path({path!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes('+repr(json.dumps(state).encode() if path.endswith('_surface_state.json') else b'INERT')+')\n'
                    code+=f'Path({op["optional_surface"]!r}).write_bytes(b"INERT")\nprint({op["success_marker"]!r})\n'
                elif operation_id in ('build_geometry','verify_geometry','build_model','verify_model'):
                    if operation_id.startswith('build_'):
                        for path in (run/'simion/geometry/geometry.iob',run/'simion/geometry/geometry.fly2'):code+=f'p=Path({str(path)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                    if operation_id=='verify_model':code+=f'm=json.loads(Path({str(session.input_dir/"compiled_model.json")!r}).read_text());p=Path({str(run/"results/model_drive_readback.txt")!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(m))\n'
                    markers={'build_geometry':'NEUTRAL_MULTI_GEOMETRY_IOB=PASS','verify_geometry':'NEUTRAL_MULTI_GEOMETRY_IOB_REOPEN=PASS','build_model':'NEUTRAL_MULTI_MODEL_BUILD=PASS','verify_model':'NEUTRAL_MULTI_MODEL_READBACK=PASS'};code+=f'print({markers[operation_id]!r})\n'
                elif operation_id.startswith('collision_build_') or operation_id.startswith('collision_verify_'):
                    index=int(operation_id.rsplit('_',1)[1]);target=run/'simion/collision'/f'collision_{index:02d}.pa';d=geo['domains'][geo['domain_order'][index-1]]['dimensions'];nodes=d[0]*d[1]*d[2]
                    if operation_id.startswith('collision_build_'):code+=f'p=Path({str(target)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT");p.with_suffix(".pa-surf").write_bytes(b"INERT")\n'
                    mode='BUILD' if operation_id.startswith('collision_build_') else 'VERIFY';code+=f'print("RAW_COLLISION_{mode}=PASS nodes={nodes} metal_nodes=1 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False")\n'
                elif operation_id in ('background_build','background_verify','collision_iob_build','collision_iob_verify'):
                    if operation_id=='background_build':code+=f'p=Path({str(run/"simion/collision/background.pa")!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                    if operation_id=='collision_iob_build':
                        for p in (run/'simion/collision/collision.iob',run/'simion/collision/collision.fly2'):code+=f'p=Path({str(p)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                    markers={'background_build':'NUMERICAL_CARRIER_REOPEN=PASS','background_verify':'NUMERICAL_CARRIER_COLD_REOPEN=PASS','collision_iob_build':'NEUTRAL_SAMPLED_COLLISION_IOB=PASS','collision_iob_verify':'NEUTRAL_SAMPLED_COLLISION_IOB_REOPEN=PASS'};code+=f'print({markers[operation_id]!r})\n'
                elif operation_id in ('build_tracking_iob','verify_tracking_iob'):
                    if operation_id=='build_tracking_iob':
                        for p in [run/'simion/tracking/instrument.iob',*[run/'inputs/structural_seed'/f'iob_seed_placeholder_{i:02d}.pa0' for i in range(1,4)]]:code+=f'p=Path({str(p)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
                    code+=f'print({("NEUTRAL_SAMPLED_TRACKING_IOB=PASS" if operation_id=="build_tracking_iob" else "NEUTRAL_SAMPLED_TRACKING_IOB_REOPEN=PASS")!r})\n'
                elif operation_id=='track_fly':
                    code+='rows=json.loads(Path('+repr(str(session.input_dir/'canonical_source_states.json'))+').read_text(encoding="utf8"));print(\'RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}\')\n'
                    from tests.contracts.test_support.terminal_evidence_fixture import native_run_from_program, inert_wire_source
                    code += inert_wire_source()+"native_run="+repr(native_run_from_program(run/"simion/tracking/instrument.lua"))+"\n"
                    code+='for ion,row in enumerate(rows,1):\n state=dict(event="source_release",reason="none",particle_id=row["particle_id"],ion=ion,instrument_time_us=row["instrument_time_us"],mass_amu=row["mass_amu"],charge_state=row["charge_state"],instance=1);state.update({a+"_mm":row["position_"+a+"_mm"] for a in "xyz"});state.update({"v"+a+"_mm_per_us":row["velocity_"+a+"_m_s"]/1000 for a in "xyz"});print("RF_NATIVE_STATE_V1: "+json.dumps(state));state.update(event="terminal",reason="unknown",instrument_time_us=2.);print("RF_NATIVE_STATE_V1: "+json.dumps(state));print("\\n".join(terminal_wire_lines(row,ion,native_run,2.,1)))\nprint("status,Fly completed. 2 splats")\n'
                else:raise AssertionError('unexpected inert operation '+operation_id)
                return original(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_model',limits=kwargs['limits'],immutable_input_records=immutable_input_records)
            drive=dict(groups=groups,clock={'phase_reference_instrument_time_us':0.},clock_authority={'example_resource':'instrument_clock_authority_v1.json'})
            with patch.object(RunSession,'run_process',new=inert):
                geometry=operations.build_geometry(compiled,context=context,artifact_store=store);model=operations.prepare_model(geometry,drive=drive,physics=RF_PHYSICS,context=context,artifact_store=store)
                prior=len(calls)
                with self.assertRaisesRegex(ValueError,'explicit sampled scalar basis'):
                    operations.solve_fields(model,numerics={},context=context,artifact_store=store)
                self.assertEqual(len(calls),prior)
                field_result=operations.solve_fields(model,numerics={},context=context,artifact_store=store,scalar_field_basis=selection)
                self.assertEqual(field_result.metadata['field_representation'],'neutral_multi_sampled_basis_with_collision_geometry');self.assertEqual(set(field_result.metadata['collision_assets']),{'left','right'})
                _,_,packet,_,propagation,numerics=rf_tracking_case()
                document=json.loads(model.data_path('compiled_model').read_text());packet['clock']={k:document['drive']['clock'][k] for k in ('clock_epoch_id','authority_sha256')}
                for row,name in zip(packet['rows'],('left','right'),strict=True):
                    for item in (row,packet['mother']['records'][row['particle_id']]):item.update(clock_epoch_id=packet['clock']['clock_epoch_id'],source_component_id=name,target_component_id=name,frame_id='multipole.cartesian.z_axis.v1')
                outside=copy.deepcopy(packet)
                outside['rows'][0]['position_x_mm']=10000.
                outside['mother']['records'][outside['rows'][0]['particle_id']]['position_x_mm']=10000.
                prior=len(calls)
                with self.assertRaisesRegex(ValueError,'outside the explicit field domain'):
                    operations.track(field_result,outside,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context,artifact_store=store)
                self.assertEqual(len(calls),prior)
                mask_path=sample.data_path('field_valid'); original_mask=mask_path.read_bytes(); prior=len(calls)
                try:
                    mask_path.write_bytes(original_mask+b'tamper')
                    with self.assertRaisesRegex(AssertionError,'byte count changed'):
                        operations.track(field_result,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context,artifact_store=store)
                    self.assertEqual(len(calls),prior)
                finally:mask_path.write_bytes(original_mask)
                result=operations.track(field_result,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context,artifact_store=store)
                collection=json.loads(result.data_path('collection').read_text());self.assertEqual([r['particle_id'] for r in collection['native_terminals']],[7,91]);self.assertEqual(collection['clock_epoch_id'],packet['clock']['clock_epoch_id'])
                self.assertEqual(collection['terminal_evidence']['status'],'recorded_v1')
                self.assertEqual([row['particle_id'] for row in collection['terminal_evidence']['particle_evidence']],[7,91])
                self.assertFalse(collection['terminal_evidence']['classification_changed'])
            self.assertEqual(calls[:4],['geometry_domain_01','geometry_domain_02','build_geometry','verify_geometry'])
            self.assertIn('collision_build_02',calls);self.assertIn('track_fly',calls)
            sample_paths={str(sample.data_path(key).resolve()) for key in ('field_v','field_valid','grid')}
            for operation,guarded in guards:
                if operation.startswith(('collision_','background_')) or operation in {'build_tracking_iob','verify_tracking_iob','track_fly'}:
                    self.assertTrue(sample_paths <= guarded,operation)
