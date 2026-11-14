"""Source-only IP–MR model plans and inert Lua readback; no native solve."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts.test_dual_cone_iob import HARNESS
from common.contracts import test_ip_mr_model as fixture_models
from common.contracts.test_simion_rf_prepared_model import assets_at
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model, render_model_configuration, require_prepared_model
from msplatform.backends.simion.native_plans import plan_model_preparation
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.backends.simion.source import lua_value
from msplatform.io.manifest_records import file_record


class IpMrNativeModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_models.RfIpMrModelTests.setUpClass()
        cls.fixtures = (fixture_models.IpMrModelTests, fixture_models.RfIpMrModelTests)

    def test_actual_model_plans_use_all_assets_and_seed(self):
        for fixture in self.fixtures:
            with self.subTest(count=len(fixture.compiled.frontend_gems)), tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();geometry=fixture.compiled
                model=compile_prepared_model(geometry,geometry.components_resolved,drive=fixture.drive,physics=RF_IP_PHYSICS)
                assets=assets_at(root/'source',geometry);count=len(geometry.frontend_gems)
                plan=plan_model_preparation(model,geometry_assets=assets,run_directory=root/'run',
                    seed_record=file_record(structural_seed_path(count),'required_evidence'),
                    native_path_resource=root/'run/inputs/native_run_path.lua')
                self.assertEqual([x['operation_id'] for x in plan.operations],['materialize_geometry','build_model','verify_model'])
                self.assertEqual(plan.operations[1]['success_marker'],'IP_MR_MODEL_BUILD=PASS')
                self.assertEqual(plan.operations[2]['success_marker'],'IP_MR_MODEL_READBACK=PASS')
                self.assertIn(f'{count}_instance_seed.iob',plan.input_copies[0]['source_record']['path'])
                text=plan.materializations[str(root/'run/inputs/model_drive_configuration.lua')]
                self.assertIn('ip_schedule',text)
                for row in require_prepared_model(model)['native_drive_rows']:
                    self.assertIn(row['electrode_group_id'],text)
                spec=plan.materializations[str(root/'run/inputs/geometry_iob.lua')]
                self.assertIn('native_drive.lua',spec)
                self.assertIn('ip_mr_geometry_iob_build',spec)
                del assets[next(iter(assets))]['witness_record']
                with self.assertRaisesRegex(ValueError,'raw and surface'):
                    plan_model_preparation(model,geometry_assets=assets,run_directory=root/'run',
                        seed_record=file_record(structural_seed_path(count),'required_evidence'),
                        native_path_resource=root/'run/inputs/native_run_path.lua')

    def test_actual_lua_consumer_reads_every_group_and_domain(self):
        selected=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not selected: self.skipTest('plain Lua unavailable')
        resources=native_resource_path('iob_core.lua').parent
        for fixture in self.fixtures:
            with self.subTest(count=len(fixture.compiled.frontend_gems)), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); geometry=fixture.compiled
                model=compile_prepared_model(geometry,geometry.components_resolved,drive=fixture.drive,physics=RF_IP_PHYSICS)
                config=root/'model.lua';config.write_text(render_model_configuration(model),encoding='utf8')
                seed=root/'seed.iob';seed.write_bytes(b'INERT_SEED')
                control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
                output=root/'instrument.iob';report=root/'model_readback.txt';instances=[]
                for i,domain in enumerate(geometry.frontend_gems,1):
                    raw=root/f'body{i}.pa#';raw.write_bytes(b'INERT_RAW')
                    surface=root/f'body{i}.pa-surf';surface.write_bytes(b'INERT_SURFACE')
                    witness=root/f'surface{i}.csv';witness.write_text('0,0,0,.25,nil,nil\n')
                    instances.append(dict(role=domain,instance_index=i,priority_number=i,path=str(raw),fractional_surface=str(surface),
                        surface_witnesses=str(witness),response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),
                        rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),
                        physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)]))
                spec=dict(schema_version=1,role='ip_mr_geometry_iob_build',instances=instances,seed_iob=str(seed),output_iob=str(output),
                    bootstrap_paths=[str(root/f'iob_seed_placeholder_{i:02}.pa0') for i in range(1,len(instances)+1)],
                    empty_particle_control=str(control),model=dict(configuration=str(config),report=str(report),
                        consumer=str(resources/'model_drive.lua'),rf_drive=str(resources/'rf_drive.lua'),
                        pulse_hook=str(resources/'single_flight_pulse_hook.lua'),waveforms=str(resources/'voltage_waveforms.lua'),
                        native_drive=str(resources/'native_drive.lua')))
                request=root/'spec.lua';request.write_text('return '+lua_value(spec),encoding='utf8')
                native_path=root/'path.lua';native_path.write_text('return function(path)return path end')
                code=(HARNESS.replace('getmetatable(instances).__len=function()return 1 end','getmetatable(instances).__len=function()return #spec.instances end')
                    .replace(" local row=spec.instances[1]\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[1]", " for i,row in ipairs(spec.instances) do\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[i]")
                    .replace(' slots[1]=item\nend',' slots[i]=item\n end\nend')
                    .replace('arg={arg[1],mode,arg[5]}',"local resources=arg[5];arg={arg[1],mode,arg[4]}")
                    .replace("arg[3]..'/build_model_iob.lua'","resources..'/build_model_iob.lua'"))
                script=root/'harness.lua';script.write_text(code,encoding='utf8')
                def call(mode):
                    return subprocess.run([selected,str(script),str(request),mode,'valid',str(native_path),str(resources)],
                        cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
                for mode,marker in [('build_model','IP_MR_MODEL_BUILD=PASS'),('verify_model','IP_MR_MODEL_READBACK=PASS')]:
                    result=call(mode);self.assertEqual(result.returncode,0,result.stderr);self.assertIn(marker,result.stdout)
                text=report.read_text(encoding='utf8')
                for row in require_prepared_model(model)['native_drive_rows']:
                    target=row['native_targets'][0]
                    self.assertIn(f'group="{row["electrode_group_id"]}" instance="{row["instance_id"]}" domain="{target["domain"]}" native_label={target["electrode_id"]} ',text)
                raw=config.read_text(encoding='utf8');domain=next(iter(geometry.frontend_gems))
                config.write_text(raw.replace('domain="'+domain+'"','domain="wrong_domain"',1),encoding='utf8')
                result=call('verify_model');self.assertNotEqual(result.returncode,0)
                self.assertIn('model target domain is not in the saved geometry',result.stderr)

    def test_public_prepare_uses_explicit_authorities_and_matching_seed(self):
        import copy
        import json
        from dataclasses import asdict
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion import operations
        for fixture in self.fixtures:
            with self.subTest(count=len(fixture.compiled.frontend_gems)), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/'geometry.json'
                path.write_text(json.dumps(asdict(fixture.compiled)),encoding='utf8')
                source=SimpleNamespace(data_path=lambda key:path,reference={'manifest':{}})
                context=SimpleNamespace(tools={'simion':Path(__file__).resolve()},execution_root=root)
                request={key:copy.deepcopy(value) for key,value in fixture.drive.items() if key!='clock'}
                request['clock']={'phase_reference_instrument_time_us':0.}
                request['clock_authority']={'example_resource':'instrument_clock_authority_v1.json'}
                stage=dict(limits={'transient_run_directory_bytes':1},artifact_retention={})
                with patch('msplatform.results.artifacts.open_artifact',side_effect=[source,'OPENED']), \
                     patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), \
                     patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':{}}) as owner:
                    self.assertEqual(operations.prepare_model({},drive=request,physics=RF_IP_PHYSICS,context=context),'OPENED')
                self.assertEqual(len(owner.call_args.kwargs['payload']['model']['native_drive_rows']),
                    len(fixture.compiled.frontend_geometry['electrode_bindings']['ion_processor'])+
                    len(fixture.compiled.frontend_geometry['electrode_bindings']['mrtof'])+
                    len(fixture.compiled.frontend_geometry['electrode_bindings'].get('multipole',{})))
                count=len(fixture.compiled.frontend_gems)
                self.assertEqual(Path(owner.call_args.kwargs['action'].keywords['seed_record']['path']).name,f'{count}_instance_seed.iob')
                bad=copy.deepcopy(request);bad['ip_schedule']['clock']['authority_sha256']='0'*64
                with patch('msplatform.results.artifacts.open_artifact',return_value=source), \
                     patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), \
                     patch('msplatform.execution.owner.run_managed_stage') as refused_owner:
                    with self.assertRaises(ValueError):
                        operations.prepare_model({},drive=bad,physics=RF_IP_PHYSICS,context=context)
                    refused_owner.assert_not_called()
