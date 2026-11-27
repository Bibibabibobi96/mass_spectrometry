"""Real Store/owner SDS path with inert observed processes, never vendor execution."""
import csv
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.io.manifest_records import file_record
from tests.contracts.test_support.dual_cone_native_recipe import CONFIG, write_dual_cone_recipe_fixture


class PublicSdsStoreTests(unittest.TestCase):
    @patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": ""})
    def test_real_store_four_owner_stages_and_canonical_si(self):
        from msplatform.backends.comsol.gas_flow import resolve_gas_flow_request
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger, record_capacity_object
        from msplatform.recipes import load_recipe
        from msplatform.workflows.native_tracing import run_loaded_recipe
        from tests.components.dual_cone_tandem_quadrupole.test_gas_flow_contract import _write_fixture
        from tests.contracts.test_execution_runtime import NormalOwnerTests
        from tests.contracts.test_terminal_evidence import row, wire
        from msplatform.backends.simion.dual_cone_transport import source_placement
        from msplatform.backends.simion.source import transform_source_rows

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); helper = NormalOwnerTests(); context = helper._context(root)
            capacity = root / 'capacity.json'; capacity.write_text(json.dumps(helper._policy()), encoding='utf8')
            executable = root/'inert-simion.exe'; executable.write_bytes(b'INERT_NOT_A_SOLVER')
            stage = dict(limits=dict(wall_clock_seconds=120, transient_run_directory_bytes=128*1024**2,
                process_tree_working_set_bytes=1024**3, minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=128*1024**2, automatic_retry_count=0),
                artifact_retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert test'))
            policy = root/'stages.json'; policy.write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy',
                stages={name:stage for name in ('dual_cone_geometry','dual_cone_model','dual_cone_fields','dual_cone_saved_fly')})), encoding='utf8')
            context = replace(context, capacity_policy_path=capacity, stage_policy_path=policy, tools={'simion':executable})
            artifact_root=context.workspace/'artifacts';artifact_root.mkdir(parents=True);initialize_capacity_ledger(artifact_root,objects=[])
            source=artifact_root/'projects/dual_cone_tandem_quadrupole/runs/inert-gas';source.mkdir(parents=True)
            request=resolve_gas_flow_request(*(CONFIG/name for name in ('baseline.json','resolved_geometry.json','gas_flow_science.json','comsol_solver_numerics.json','gas_environment.json')))
            science=source/'science_resolved.json';science.write_text(json.dumps(request['projected_science'],ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
            csv_path, metadata = _write_fixture(source, science_path=science, numerics_path=CONFIG/'comsol_solver_numerics.json', geometry_path=CONFIG/'resolved_geometry.json')
            with csv_path.open(newline='',encoding='utf8') as stream:
                reader=csv.DictReader(stream);names=reader.fieldnames; rows=list(reader)
            domain=json.loads((CONFIG/'gas_field_interface.json').read_text())['runtime_artifact_contract']['domain']
            radii=[domain['minimum_radius_mm']+(domain['maximum_radius_mm']-domain['minimum_radius_mm'])*i/9 for i in range(10)]
            axial=[domain['minimum_z_mm']+(domain['maximum_z_mm']-domain['minimum_z_mm'])*i/9 for i in range(10)]
            for item in rows:item.update(r_mm=radii[int(item['r_index'])],z_mm=axial[int(item['z_index'])])
            with csv_path.open('w',newline='',encoding='utf8') as stream:
                writer=csv.DictWriter(stream,fieldnames=names);writer.writeheader();writer.writerows(rows)
            meta=json.loads(metadata.read_text());meta['grid']={'r_values_mm':radii,'z_values_mm':axial}
            meta['field_csv_sha256']=hashlib.sha256(csv_path.read_bytes()).hexdigest();metadata.write_text(json.dumps(meta))
            inputs={}
            for name, record in request['inputs'].items():
                target=source/('input_'+name+Path(record['path']).suffix)
                target.write_bytes(Path(record['path']).read_bytes())
                inputs[name]=file_record(target)
            records=dict(science=file_record(science),science_author=inputs['science'],
                numerics=inputs['numerics'],geometry=inputs['geometry'],environment=inputs['environment'],
                species_data=inputs['species_data'],constants_data=inputs['constants_data'],transport_data=inputs['transport_data'],
                field_csv=file_record(csv_path),field_metadata=file_record(metadata))
            inputs['science_resolved']=records['science']
            identity=dict(project='dual_cone_tandem_quadrupole',run_id=source.name,mode='axisymmetric_gas_flow_screening')
            config=source/'run_config.json';config.write_text(json.dumps(identity))
            manifest=source/'run_manifest.json';manifest.write_text(json.dumps(dict(schema_version=2,role='simulation_run_manifest',
                status='success',run_config=file_record(config),inputs=inputs,outputs=[records['field_csv'],records['field_metadata']],
                products={'gas_field':dict(schema_version=1,kind='gas_field',status='complete',metadata={'backend':'comsol',
                    'claim_scope':'inert_test_not_native'},data=records)},**identity)))
            record_capacity_object(artifact_root,path=source,object_class='light_evidence',bytes_count=sum(p.stat().st_size for p in source.iterdir()),status='ready',owner='inert-gas')
            author=write_dual_cone_recipe_fixture(root/'author');request_path=author.parent/'sds_request.json'
            sds_request=json.loads(request_path.read_text());sds_request['gas_field_reference']=dict(
                path=os.path.relpath(manifest,author.parent).replace('\\','/'),sha256=file_record(manifest)['sha256'],product_id='gas_field')
            request_bytes=json.dumps(sds_request).encode();request_path.write_bytes(request_bytes)
            text=author.read_text(); old=text.split('sha256 = "')[-1].split('"')[0]
            author.write_text(text.replace(old,hashlib.sha256(request_bytes).hexdigest().upper()),encoding='utf8')
            loaded=load_recipe(author);calls=[]
            from contextlib import ExitStack
            from types import SimpleNamespace
            from msplatform.backends.simion.dual_cone_stage_execution import _protect_product
            from msplatform.execution.owner import managed_native_store
            from msplatform.results.artifacts import open_artifact
            from msplatform.storage import ArtifactStore
            store=ArtifactStore(root/'store')
            reference=dict(manifest=file_record(manifest),product_id='gas_field')
            product=open_artifact(reference,expected_kind='gas_field')
            with ExitStack() as scope, managed_native_store(store,task_key='inert-guard-check',lifetime=scope,account=lambda _:None):
                session=SimpleNamespace(context=context)
                with self.assertRaisesRegex(ValueError,'not bound'):
                    _protect_product(session,product,required_paths=[source/'unlisted'])
                bad=SimpleNamespace(reference=dict(reference,manifest=dict(reference['manifest'],sha256='0'*64)),kind='gas_field')
                with self.assertRaises((ValueError,AssertionError)):
                    _protect_product(session,bad,required_paths=[csv_path])
            def observed(_context,**kw):
                args=kw['arguments'];run=kw['working_directory'];solver=run/'simion';solver.mkdir(exist_ok=True);out='INERT_NOT_SIMION\n'
                if '-RequestPath' in args:
                    selected=json.loads(Path(args[args.index('-RequestPath')+1]).read_text(encoding='utf-8-sig')); outputs=[]; releases={}
                    for item in selected['copies']:
                        original=item['source_record'];target=Path(item['destination']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(Path(original['path']).read_bytes())
                        actual=file_record(target,original['retention_role']);outputs.append(actual)
                        for rec in (original,actual):releases[rec['path']]=dict(rec,write_delete_guarded=False)
                    Path(selected['receipt_path']).write_text(json.dumps(dict(schema_version=1,role='payload_materialization',status='success',primary=None,secondary_errors=[],outputs=outputs,source_and_destination_releases=list(releases.values()))))
                elif 'build_frontend_geometry.lua' in ' '.join(args):
                    (solver/'dual_cone_tandem.pa#').write_bytes(b'inert');(solver/'dual_cone_tandem.pa-surf').write_bytes(b'inert');(solver/'dual_cone_surface.csv').write_text('0,0,0,0.25,nil,nil\n');out+='BUILD_GEOMETRY=PASS\n'
                elif 'refine_rf_field_family.lua' in ' '.join(args):
                    for eid in (0,1,2,3,11,12,21,22):(solver/('dual_cone_tandem.pa'+str(eid))).write_bytes(b'inert')
                    out+='INDEPENDENT_RF_REFINE=PASS\n'
                elif 'audit_rf_field_family.lua' in ' '.join(args):
                    (run/'results/field_audit.json').write_text('{"status":"success","checked_domains":["dual_cone"]}');out+='INDEPENDENT_RF_FIELDS_READBACK=PASS\n'
                elif 'build_tracking_iob.lua' in ' '.join(args):
                    tracking=run/'transport/solver/simion'
                    if 'verify' not in args:(tracking/'transport.iob').write_bytes(b'inert')
                    out+='DUAL_CONE_TRACKING_IOB=PASS\nDUAL_CONE_TRACKING_IOB_REOPEN=PASS\n'
                elif 'fly' in args:
                    from msplatform.workflows.native_tracing import compile_sds_inputs, _assembly
                    plan=compile_sds_inputs(loaded.to_dict(),_assembly(loaded.to_dict()))
                    with (run/'transport/input/cylindrical_particle_source.csv').open(newline='') as stream:source_rows=list(csv.DictReader(stream))
                    world,_=source_placement(plan['resolved'],plan['numerics'],plan['source'],placement=plan['placement'],source_to_device=plan['source_to_device'])
                    projected=transform_source_rows(source_rows,world);output=run/'transport/results';lines=[]; samples=[];finals=[]
                    for index,item in enumerate(projected,1):
                        xyz={axis+'_mm':float(item['position_'+axis+'_mm']) for axis in 'xyz'}
                        xyz.update({'v'+axis+'_mm_per_us':float(item['velocity_'+axis+'_m_s'])/1000 for axis in 'xyz'})
                        common=dict(particle_id=int(item['particle_id']),ion=index,native_run=kw['run_id']+':dual-cone',ion_run=1,raw_birth_us=0.,source_origin_us=0.,raw_step_us=None,**xyz)
                        lines.extend([wire(row('initialize',1,**common,raw_tof_us=0.,pipeline_clock_us=0.,instrument_time_us=0.)),wire(row('terminate',2,**common,raw_tof_us=2.,pipeline_clock_us=2.,instrument_time_us=2.))])
                        serialized={key:format(value,'.9g') for key,value in xyz.items()}
                        samples.append(dict(ion_number=item['particle_id'],time_us=1.,**serialized));finals.append(dict(ion_number=item['particle_id'],time_us=2.,splat=2,**serialized))
                    for path,items in ((output/'trajectory_samples.csv',samples),(output/'particle_final_state.csv',finals)):
                        with path.open('w',newline='') as stream:
                            writer=csv.DictWriter(stream,fieldnames=list(items[0]));writer.writeheader();writer.writerows(items)
                    out+='\n'.join(lines)+f'\nstatus,Fly completed. {len(source_rows)} splats, 0.1 seconds\n'
                else:
                    build='verify_geometry' not in args and 'verify_model' not in args; model='build_model_iob.lua' in ' '.join(args)
                    if build:(solver/'model.iob').write_bytes(b'inert');(solver/'model.fly2').write_text('particles{coordinates=0,}\n')
                    if model:
                        if not build:(run/'results/model_readback.txt').write_text('INERT_NOT_NATIVE')
                        out+='DUAL_CONE_MODEL_BUILD=PASS\nDUAL_CONE_MODEL_READBACK=PASS\n'
                    else:out+='DUAL_CONE_GEOMETRY_IOB=PASS\nDUAL_CONE_GEOMETRY_IOB_REOPEN=PASS\n'
                calls.append(args)
                for name in ('stdout_path','stderr_path','usage_path'):kw[name].write_text(out if name=='stdout_path' else '{}')
                return dict(observation=dict(exit_code=0,root_process_id=os.getpid(),root_process_started_at_utc_ticks=12345),host_release=dict(inherited=False,token='inert',error=None,result=dict(status='released',token='inert')))
            with patch('msplatform.execution.run_session.run_observed_process',side_effect=observed), \
                    patch('msplatform.execution.executable_identity.windows_binary_version',return_value='inert'):
                result=run_loaded_recipe(loaded,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
                first_calls=len(calls)
                repeated=run_loaded_recipe(loaded,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
            self.assertEqual(result['run_state']['execution_status'],'succeeded')
            self.assertEqual(result['run_state']['publication_status'],'ready')
            self.assertEqual(set(result['provenance']['stages']),{'geometry','model','fields','track'})
            self.assertEqual(result['summary']['data_integrity']['detector_observation']['status'],'not_requested')
            self.assertEqual(len(calls),first_calls)
            self.assertTrue(all(stage['reused'] for stage in repeated['provenance']['stages'].values()))
            self.assertEqual(sum('fly' in args for args in calls),1)
