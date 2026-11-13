"""RF–IP selected drive and field-family software boundaries; no SIMION."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_ip_compiler import IpCompilerTests
from msplatform.backends.simion import operations
from msplatform.backends.simion.electrode_contract import scientific_multipole_drive
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model, require_prepared_model
from msplatform.backends.simion.rf_field_execution import _domain_labels, plan_rf_fields
from msplatform.io.file_identity import file_sha256

ROOT=Path(__file__).resolve().parents[2]


class JointIpModelTests(unittest.TestCase):
    def setUp(self):
        fixture=IpCompilerTests();fixture.setUp()
        self.compiled=operations.compile_geometry(fixture.assembly,numerics=fixture.numerics)
        self.baseline=fixture.assembly.components_source['ion_processor']['baseline']
        self.point=json.loads((ROOT/'projects/dual_pressure_rectilinear_ion_processor/config/native_operating_point.json').read_text(encoding='utf-8'))
        epoch=ROOT/'src/msplatform/examples/instrument_epoch_v1.json'
        self.identity=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256=file_sha256(epoch))
        self.clock=dict(self.identity,phase_reference_instrument_time_us=0.)
        groups=scientific_multipole_drive(self.compiled.components_resolved['multipole'],self.compiled.frontend_geometry['electrode_bindings']['multipole'])
        self.drive=dict(groups={'multipole':groups},clock=self.clock,ip_schedule=dict(baseline=self.baseline,native_operating_point=self.point,clock=self.identity))

    def test_real_provider_schedule_and_field_plan(self):
        before=copy.deepcopy((self.compiled,self.drive))
        model=compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=self.drive,physics=RF_IP_PHYSICS)
        doc=require_prepared_model(model)
        self.assertEqual(len([r for r in doc['native_drive_rows'] if r['kind']=='ip_schedule']),15)
        self.assertEqual(doc['drive']['ip_schedule']['native_timing']['primary_quench_us'],7500)
        self.assertEqual((self.compiled,self.drive),before)
        geometry=doc['geometry']['frontend_geometry']
        expected={v for mapping in geometry['electrode_bindings'].values() for v in mapping.values()}
        self.assertEqual(set(_domain_labels(geometry,'parent')),expected)
        bad_geometry=copy.deepcopy(geometry)
        ip_names=list(bad_geometry['electrode_bindings']['ion_processor'])
        bad_geometry['electrode_bindings']['ion_processor'][ip_names[0]]=bad_geometry['electrode_bindings']['multipole'][next(iter(bad_geometry['electrode_bindings']['multipole']))]
        with self.assertRaisesRegex(ValueError,'native labels'):
            _domain_labels(bad_geometry,'parent')
        plan=plan_rf_fields(model,numerics={'refine_policy':'explicit_convergence','convergence_v':{'parent':.1}})
        self.assertEqual(plan['numerical_domains'],['parent'])
        self.assertEqual(plan['expected_operation_ids'],['materialize_geometry','refine_parent','audit_fields'])
        self.assertEqual(doc['physics']['boundary_policy'],'grounded_pa_faces')
        from msplatform.contracts.clock import age_us, instrument_time_us
        # At a nonzero birth, schedule time is still the common instrument time;
        # the model remains source-free and receives no particle age or birth.
        self.assertEqual(instrument_time_us(1500.,instrument_origin_us=0.,native_origin_us=0.),1500.)
        self.assertEqual(age_us(1500.,birth_time_us=100.),1400.)
        self.assertNotIn('particles',doc)

    def test_existing_model_owner_plan_binds_actual_native_drive(self):
        from common.contracts.test_simion_rf_prepared_model import assets_at
        from msplatform.backends.simion.native_plans import plan_model_preparation
        from msplatform.backends.simion.resources import structural_seed_path
        from msplatform.io.manifest_records import file_record
        model=compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=self.drive,physics=RF_IP_PHYSICS)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();assets=assets_at(root/'source',self.compiled)
            seed=file_record(structural_seed_path(1),'required_evidence')
            plan=plan_model_preparation(model,geometry_assets=assets,run_directory=root/'run',seed_record=seed,
                                        native_path_resource=root/'run/inputs/native_sources/native_run_path.lua')
            self.assertEqual([row['operation_id'] for row in plan.operations],['materialize_geometry','build_model','verify_model'])
            self.assertEqual(plan.operations[1]['success_marker'],'RF_IP_MODEL_BUILD=PASS')
            self.assertEqual(plan.operations[2]['success_marker'],'RF_IP_MODEL_READBACK=PASS')
            spec=plan.materializations[str(root/'run/inputs/geometry_iob.lua')]
            self.assertIn('rf_ip_geometry_iob_build',spec)
            self.assertIn('native_drive.lua',spec)
            broken=copy.deepcopy(assets);del broken['parent']['witness_record']
            with self.assertRaisesRegex(ValueError,'raw and surface'):
                plan_model_preparation(model,geometry_assets=broken,run_directory=root/'run',seed_record=seed,
                                       native_path_resource=root/'run/inputs/native_sources/native_run_path.lua')

    def test_actual_lua_ip_schedule_preserves_independent_voltage_oracle(self):
        from msplatform.backends.simion.model import render_model_configuration
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value
        selected=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not selected: self.skipTest('plain Lua unavailable')
        self.assertTrue(Path(selected).is_file(),'selected Lua executable is unavailable')
        model=compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=self.drive,physics=RF_IP_PHYSICS)
        cases=[(0.,[500,-500,495,-505,500,500,-500,-500,-2,5,-1,0,50,0,-5]),
               (1500.,[500,-500,505,-495,500,500,-500,-500,25,5,-1,0,50,0,5]),
               (6750.,[500,-500,505,-495,2500,2500,1500,1500,25,2005,1999,0,2050,2000,5]),
               (7500.,[500,-500,505,-495,4000,4000,3500,3500,25,4005,3999,0,4050,4000,5]),
               (7500.+.5/3.7,[-500,500,-495,505,3100,4900,3100,4900,25,4005,3999,0,4050,3100,5])]
        resources={name:str(native_resource_path(name)).replace('\\','/') for name in ('model_drive.lua','rf_drive.lua','single_flight_pulse_hook.lua','voltage_waveforms.lua','native_drive.lua')}
        script='local config=(function() '+render_model_configuration(model)+' end)()\n'
        script+='local m=assert(loadfile('+json.dumps(resources['model_drive.lua'])+'))().new(config,'
        script+='assert(loadfile('+json.dumps(resources['rf_drive.lua'])+'))(),assert(loadfile('+json.dumps(resources['single_flight_pulse_hook.lua'])+'))(),'
        script+='assert(loadfile('+json.dumps(resources['voltage_waveforms.lua'])+'))(),assert(loadfile('+json.dumps(resources['native_drive.lua'])+')))\n'
        script+='local cases='+lua_value([list(case) for case in cases])+'\n'
        script+="for _,case in ipairs(cases) do local values=m.evaluate_at(case[1]);local seen=0;for i,row in ipairs(config.groups) do if row.kind=='ip_schedule' then seen=seen+1;assert(math.abs(values[i].voltage_v-case[2][row.schedule_index])<1e-6,'IP native drive mismatch '..row.schedule_index) end end;assert(seen==15) end\nprint('IP_MODEL_NATIVE_DRIVE=PASS')\n"
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.lua';path.write_text(script,encoding='utf-8')
            result=subprocess.run([selected,str(path)],cwd=directory,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('IP_MODEL_NATIVE_DRIVE=PASS',result.stdout)

    def test_real_field_owner_complete_and_missing_family_with_inert_process(self):
        from common.contracts.test_simion_rf_prepared_model import assets_at, clock_reference
        from common.contracts.test_simion_rf_fields import InertFieldSession, execute
        from msplatform.backends.simion import field_closure
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record

        model=compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=self.drive,physics=RF_IP_PHYSICS)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source_root=root/'source'; assets=assets_at(source_root,self.compiled)
            clock=clock_reference();records=dict(clock_authority=clock['contract'],instrument_epoch=clock['authority'])
            model_file=source_root/'model.json';model_file.write_text(json.dumps(model.document),encoding='utf-8')
            records['compiled_model']=file_record(model_file,'required_evidence');bindings={}
            for name,row in assets.items():
                bindings[name]={}
                for label,record in (('raw_geometry',row['raw_record']),('fractional_surface',row['surface_records'][0]),('surface_witnesses',row['witness_record'])):
                    key=name+'_'+label;records[key]=record;bindings[name][label]=key
            manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-joint-model',project='software_fixture',
                mode='explicit_inert_joint_model',status='success',inputs={},outputs=list(records.values()),
                products=dict(model=dict(schema_version=1,kind='prepared_model',status='complete',data=records,
                    metadata=dict(backend='simion',drive_configured=True,geometry_materialized=True,field_status='not_solved',source_status='not_requested',native_assets=bindings))))
            publish_terminal_state(source_root,{'status':'success'},manifest)
            source=field_closure.load_field_model(dict(manifest=file_record(source_root/'run_manifest.json'),product_id='model'))
            graph=plan_rf_fields(model,numerics={'refine_policy':'vendor_default'})
            for incomplete in (False,True):
                session=InertFieldSession(root/('missing' if incomplete else 'success'),source.artifact.data_path('compiled_model').parent,graph)
                session.labels={'parent':_domain_labels(model.document['geometry']['frontend_geometry'],'parent')};session.incomplete=incomplete
                with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(source_root))), \
                     patch('subprocess.Popen',side_effect=AssertionError('native process is forbidden')):
                    if incomplete:
                        with self.assertRaises((ValueError,FileNotFoundError)):execute(session,source,{'refine_policy':'vendor_default'})
                    else:
                        result=execute(session,source,{'refine_policy':'vendor_default'})
                        metadata=result['manifest_extra_fields']['products']['fields']['metadata']
                        self.assertEqual(metadata['field_representation'],'producer_owned_rf_ip_fractional_family')
                        self.assertEqual(metadata['refine_calls'],1)
                        self.assertEqual(metadata['fly_calls'],0)
                        self.assertEqual([name for name,_ in session.requests],['materialize_geometry','refine_parent','audit_fields'])
                        from msplatform.results.artifacts import open_artifact
                        product=result['manifest_extra_fields']['products']['fields']
                        fields_manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-joint-fields',
                            project='software_fixture',mode='inert_joint_fields',status='success',inputs=dict(session.inputs),
                            outputs=[row for row in product['data'].values() if Path(row['path']).is_relative_to(session.artifact_run_dir)],
                            products=dict(fields=product))
                        publish_terminal_state(session.run_dir,{'status':'success'},fields_manifest)
                        reference=dict(manifest=file_record(session.run_dir/'run_manifest.json'),product_id='fields')
                        opened=open_artifact(reference,expected_kind='field_bundle')
                        target=opened.data_path(metadata['native_assets']['parent']['family'][2])
                        original=target.read_bytes();target.write_bytes(bytes([original[0]^1])+original[1:])
                        with self.assertRaisesRegex(AssertionError,'SHA-256 changed'):
                            open_artifact(reference,expected_kind='field_bundle')

    def test_actual_model_iob_wrapper_uses_frozen_ip_law_with_inert_workbench(self):
        from common.contracts.test_dual_cone_iob import HARNESS
        from msplatform.backends.simion.model import render_model_configuration
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value
        selected=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not selected: self.skipTest('plain Lua unavailable')
        self.assertTrue(Path(selected).is_file(),'selected Lua executable is unavailable')
        model=compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=self.drive,physics=RF_IP_PHYSICS)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'body.pa#';raw.write_bytes(b'INERT_RAW')
            surface=root/'body.pa-surf';surface.write_bytes(b'INERT_SURFACE')
            witness=root/'surface.csv';witness.write_text('0,0,0,.25,nil,nil\n')
            seed=root/'seed.iob';seed.write_bytes(b'INERT_SEED');control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
            config=root/'model.lua';config.write_text(render_model_configuration(model),encoding='utf-8')
            output=root/'instrument.iob';report=root/'model_readback.txt'
            row=dict(role='parent',instance_index=1,priority_number=1,path=str(raw),fractional_surface=str(surface),surface_witnesses=str(witness),
                response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],
                placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),
                physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)])
            resources=native_resource_path('iob_core.lua').parent
            spec=dict(schema_version=1,role='rf_ip_geometry_iob_build',instances=[row],seed_iob=str(seed),output_iob=str(output),
                bootstrap_paths=[str(root/'iob_seed_placeholder_01.pa0')],empty_particle_control=str(control),model=dict(
                    configuration=str(config),report=str(report),consumer=str(resources/'model_drive.lua'),rf_drive=str(resources/'rf_drive.lua'),
                    pulse_hook=str(resources/'single_flight_pulse_hook.lua'),waveforms=str(resources/'voltage_waveforms.lua'),native_drive=str(resources/'native_drive.lua')))
            request=root/'spec.lua';request.write_text('return '+lua_value(spec),encoding='utf-8')
            native_path=root/'path.lua';native_path.write_text('return function(path)return path end')
            code=(HARNESS.replace('arg={arg[1],mode,arg[5]}',"local resources=arg[5];arg={arg[1],mode,arg[4]}")
                .replace("arg[3]..'/build_model_iob.lua'","resources..'/build_model_iob.lua'"))
            script=root/'harness.lua';script.write_text(code,encoding='utf-8')
            for mode,marker in [('build_model','RF_IP_MODEL_BUILD=PASS'),('verify_model','RF_IP_MODEL_READBACK=PASS')]:
                result=subprocess.run([selected,str(script),str(request),mode,'valid',str(native_path),str(resources)],cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn(marker,result.stdout)
            self.assertIn('kind="ip_schedule"',report.read_text(encoding='utf-8'))

    def test_wrong_clock_geometry_mapping_and_bvp_refused(self):
        for change in (lambda d:d['ip_schedule']['clock'].__setitem__('clock_epoch_id','other_epoch'),
                       lambda d:d['ip_schedule']['clock'].__setitem__('authority_sha256','0'*64),
                       lambda d:d['ip_schedule']['baseline']['clock'].__setitem__('epoch_us',1.),
                       lambda d:d['ip_schedule']['baseline']['native_geometry'].__setitem__('guide_rod_radius_mm',9.),
                       lambda d:d['groups']['multipole'].pop(next(iter(d['groups']['multipole'])))):
            with self.subTest(change=change):
                bad=copy.deepcopy(self.drive);change(bad)
                with self.assertRaises((ValueError,KeyError)):
                    compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=bad,physics=RF_IP_PHYSICS)
        with self.assertRaisesRegex(ValueError,'grounded-face'):
            compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=self.drive,
                                   physics=dict(field_model='external_electrostatic_linear',boundary_policy='native_zero_neumann'))

    def test_nonzero_verified_clock_authority_is_refused_before_owner(self):
        from msplatform.io.manifest_records import file_record
        from msplatform.contracts.machine_contracts import ContractError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);geometry=root/'geometry.json';geometry.write_text(json.dumps(asdict(self.compiled)),encoding='utf-8')
            epoch=root/'epoch.json';epoch.write_text(json.dumps({'instrument_time_us':1.}),encoding='utf-8')
            template=json.loads((ROOT/'src/msplatform/examples/instrument_clock_authority_v1.json').read_text(encoding='utf-8'))
            template['authority']=dict(path='epoch.json',sha256=file_sha256(epoch),field='instrument_time_us')
            contract=root/'clock.json';contract.write_text(json.dumps(template),encoding='utf-8')
            request=dict(groups=copy.deepcopy(self.drive['groups']),clock={'phase_reference_instrument_time_us':0.},
                clock_authority=dict(contract=file_record(contract,'required_evidence'),data_root=str(root)),ip_schedule=copy.deepcopy(self.drive['ip_schedule']))
            request['ip_schedule']['clock']['authority_sha256']=file_sha256(epoch)
            source=SimpleNamespace(data_path=lambda key:geometry,reference={'manifest':{}})
            context=SimpleNamespace(tools={'simion':Path(__file__).resolve()},execution_root=root)
            stage=dict(limits={'transient_run_directory_bytes':1},artifact_retention={})
            with patch('msplatform.results.artifacts.open_artifact',return_value=source), \
                 patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), \
                 patch('msplatform.execution.owner.run_managed_stage') as owner, \
                 self.assertRaisesRegex(ContractError,'zero instrument epoch'):
                operations.prepare_model({},drive=request,physics=RF_IP_PHYSICS,context=context)
            owner.assert_not_called()

    def test_public_prepare_consumes_shared_epoch_and_original_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'geometry.json';path.write_text(json.dumps(asdict(self.compiled)),encoding='utf-8')
            source=SimpleNamespace(data_path=lambda key:path, reference={'manifest':{}})
            context=SimpleNamespace(tools={'simion':Path(__file__).resolve()},execution_root=root)
            request=dict(groups=copy.deepcopy(self.drive['groups']),clock={'phase_reference_instrument_time_us':0.},
                         clock_authority={'example_resource':'instrument_clock_authority_v1.json'},ip_schedule=copy.deepcopy(self.drive['ip_schedule']))
            stage=dict(limits={'transient_run_directory_bytes':1},artifact_retention={})
            with patch('msplatform.results.artifacts.open_artifact',side_effect=[source,'OPENED']), \
                 patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), \
                 patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':{}}) as owner:
                self.assertEqual(operations.prepare_model({},drive=request,physics=RF_IP_PHYSICS,context=context),'OPENED')
            payload=owner.call_args.kwargs['payload'];self.assertEqual(payload['model']['drive']['ip_schedule']['clock'],self.identity)
            self.assertEqual(Path(owner.call_args.kwargs['action'].keywords['seed_record']['path']).name,'1_instance_seed.iob')


if __name__=='__main__': unittest.main()
