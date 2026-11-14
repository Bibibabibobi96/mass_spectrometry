"""Complete source-free OA–MR model from real providers; no SIMION."""
import copy
import tempfile
import unittest
from pathlib import Path

from msplatform.assembly.factory import assemble
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_PHYSICS, compile_prepared_model, model_geometry, require_prepared_model
from msplatform.backends.simion.native_plans import plan_model_preparation
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.components.catalog import resolve_component
from msplatform.io.manifest_records import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_mr_provider_trial_transport import _plans
from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority
from common.contracts.test_simion_rf_prepared_model import assets_at


class OaMrModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, plan, contract = _plans()
        a = geometry_authority(contract)
        oa = resolve_component(dict(provider_id='orthogonal_accelerator', geometry_profile_id=a['geometry_profile_id'],
            design=dict(requirements=a['accelerator_requirements'], geometry_profile=a['geometry_profile'])))
        mr = resolve_component(dict(provider_id='parallel_mirror_dual_stripe_mr_tof', geometry_profile_id=a['geometry_profile_id'],
            design=dict(contract=contract, accelerator_requirements=a['accelerator_requirements'], geometry_profile=a['geometry_profile'])))
        components = {name: oa if row['project_id'] == 'orthogonal_accelerator' else mr for name, row in plan['components'].items()}
        cls.oa = next(k for k,v in plan['components'].items() if v['project_id'] == 'orthogonal_accelerator')
        cls.mr = next(k for k,v in plan['components'].items() if v['project_id'] == 'parallel_mirror_dual_stripe_mr_tof')
        assembly = assemble(plan['recipe'], components)
        d = dict(cell_mm_xyz=dict.fromkeys('xyz', .1), pa_bounds_mm={axis+suffix: (-1000. if suffix == '_min' else 1000.) for axis in 'xyz' for suffix in ('_min','_max')})
        names = [r['electrode_group_id'] for r in mr.assembly_interface['component_electrodes']]
        permutation = dict(zip(names, reversed(range(1, len(names)+1)), strict=True))
        cls.compiled = operations.compile_geometry(assembly, numerics=dict(domains=dict.fromkeys(('oa','analyzer','detector'),d), electrode_group_native_ids={cls.mr:permutation}))
        groups = {name:dict(kind='static',voltage_v=0.) for name in cls.compiled.frontend_geometry['electrode_bindings'][cls.oa]}
        groups['repeller'] = dict(kind='pulse',off_voltage_v=0.,on_voltage_v=100.)
        cls.drive = dict(clock=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256='6a035131b2bdba6f7f20cbf6b6fd20edaa5dcb3d7ec8eb7349f74f7ac35238a0',phase_reference_instrument_time_us=0.), oa_groups=groups,
            pulse=dict(mode='timed',time_us=10.,width_us=1.), mr_authority=dict(source=dict(analyzer_electrode_voltages_v=list(range(1,21))), candidate=dict(s1=31.,s2=32.,p1=41.,p2=42.), mirror_voltages_v=[11.,12.,13.,14.,15.], detector_voltage_v=50., mirror_shield_voltages_v=dict(positive_mirror_ground_shield=51.,negative_mirror_ground_shield=52.)))

    def compiled_model(self, drive=None, geometry=None):
        geometry = geometry or self.compiled
        return compile_prepared_model(geometry, geometry.components_resolved, drive=self.drive if drive is None else drive, physics=RF_PHYSICS)

    def test_saved_model_recompiles_with_identical_rows_and_identity(self):
        saved=require_prepared_model(self.compiled_model())
        geometry=model_geometry(self.compiled_model())
        rebuilt=compile_prepared_model(geometry,geometry.components_resolved,
            drive=saved['drive'],physics=saved['physics'])
        self.assertEqual(require_prepared_model(rebuilt),saved)

    def test_complete_binding_and_permuted_targets(self):
        doc = require_prepared_model(self.compiled_model())
        self.assertEqual(doc['source_status'], 'not_requested')
        self.assertEqual(doc['field_status'], 'not_solved')
        rows = {row['electrode_group_id']:row for row in doc['native_drive_rows'] if row['instance_id']==self.mr}
        self.assertEqual(len(rows),22)
        for name, value in [('positive_mirror_layer_1',11.),('negative_mirror_layer_5',15.),('positive_stripe_set_1',31.),('negative_stripe_set_2',32.),('accelerator_exit_prism',41.),('central_ground_left_prism',42.),('detector',50.),('positive_mirror_ground_shield',51.),('negative_mirror_ground_shield',52.)]:
            self.assertEqual(rows[name]['voltage_v'],value)
            target = rows[name]['native_targets'][0]
            self.assertEqual(target['electrode_id'],self.compiled.frontend_geometry['electrode_bindings'][self.mr][name])
            self.assertEqual(target['domain'],self.mr+('_detector' if name=='detector' else '_analyzer'))
        with self.assertRaisesRegex(ValueError,'tracking is not supported'):
            model_geometry(self.compiled_model(), downstream_drive=True)

    def test_missing_and_changed_authorities_refuse(self):
        for change in ('detector','shield','clock','oa_group','mapping','source'):
            with self.subTest(change=change):
                drive=copy.deepcopy(self.drive); geometry=copy.deepcopy(self.compiled)
                if change=='detector': del drive['mr_authority']['detector_voltage_v']
                elif change=='shield': del drive['mr_authority']['mirror_shield_voltages_v']['positive_mirror_ground_shield']
                elif change=='clock': drive['clock']['phase_reference_instrument_time_us']=1.
                elif change=='oa_group': del drive['oa_groups']['repeller']
                elif change=='mapping': del geometry.frontend_geometry['electrode_bindings'][self.mr]['detector']
                else: geometry.components_resolved[self.mr]['detector']['box'][0] += 1.
                with self.assertRaises(ValueError): self.compiled_model(drive,geometry)

    def test_existing_model_plan_three_assets_and_missing_witness(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); assets=assets_at(root/'source',self.compiled)
            seed=file_record(structural_seed_path(3),'required_evidence')
            args=dict(geometry_assets=assets,run_directory=root/'run',seed_record=seed,native_path_resource=root/'run/inputs/native_run_path.lua')
            plan=plan_model_preparation(self.compiled_model(),**args)
            self.assertEqual([r['operation_id'] for r in plan.operations],['materialize_geometry','build_model','verify_model'])
            self.assertEqual(plan.operations[1]['success_marker'],'OA_MR_MODEL_BUILD=PASS')
            self.assertEqual(plan.operations[2]['success_marker'],'OA_MR_MODEL_READBACK=PASS')
            self.assertIn('oa_mr_geometry_iob_build',plan.materializations[str(root/'run/inputs/geometry_iob.lua')])
            del assets[self.mr+'_detector']['witness_record']
            with self.assertRaisesRegex(ValueError,'raw and surface'): plan_model_preparation(self.compiled_model(),**args)

    def test_actual_model_lua_build_readback_and_wrong_domain(self):
        import os
        import shutil
        import subprocess
        from common.contracts.test_dual_cone_iob import HARNESS
        from msplatform.backends.simion.model import render_model_configuration
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value
        selected = os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not selected: self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); resources = native_resource_path('iob_core.lua').parent
            seed=root/'seed.iob';seed.write_bytes(b'INERT_SEED');control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
            config=root/'model.lua';config.write_text(render_model_configuration(self.compiled_model()),encoding='utf-8')
            output=root/'instrument.iob';report=root/'model_readback.txt'; rows=[]
            for i,domain in enumerate(self.compiled.frontend_gems,1):
                raw=root/f'body{i}.pa#';raw.write_bytes(b'INERT_RAW');surface=root/f'body{i}.pa-surf';surface.write_bytes(b'INERT_SURFACE')
                witness=root/f'surface{i}.csv';witness.write_text('0,0,0,.25,nil,nil\n')
                rows.append(dict(role=domain,instance_index=i,priority_number=i,path=str(raw),fractional_surface=str(surface),surface_witnesses=str(witness),response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)]))
            spec=dict(schema_version=1,role='oa_mr_geometry_iob_build',instances=rows,seed_iob=str(seed),output_iob=str(output),bootstrap_paths=[str(root/f'iob_seed_placeholder_{i:02}.pa0') for i in range(1,4)],empty_particle_control=str(control),model=dict(configuration=str(config),report=str(report),consumer=str(resources/'model_drive.lua'),rf_drive=str(resources/'rf_drive.lua'),pulse_hook=str(resources/'single_flight_pulse_hook.lua'),waveforms=str(resources/'voltage_waveforms.lua')))
            request=root/'spec.lua';request.write_text('return '+lua_value(spec),encoding='utf-8');native_path=root/'path.lua';native_path.write_text('return function(path)return path end')
            code=(HARNESS.replace('getmetatable(instances).__len=function()return 1 end','getmetatable(instances).__len=function()return #spec.instances end')
                  .replace(" local row=spec.instances[1]\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[1]", " for i,row in ipairs(spec.instances) do\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[i]")
                  .replace(' slots[1]=item\nend',' slots[i]=item\n end\nend')
                  .replace('arg={arg[1],mode,arg[5]}',"local resources=arg[5];arg={arg[1],mode,arg[4]}")
                  .replace("arg[3]..'/build_model_iob.lua'","resources..'/build_model_iob.lua'"))
            script=root/'harness.lua';script.write_text(code,encoding='utf-8')
            def call(mode):
                return subprocess.run([selected,str(script),str(request),mode,'valid',str(native_path),str(resources)],cwd=root,capture_output=True,text=True,encoding="utf-8",timeout=30)
            for mode,marker in [('build_model','OA_MR_MODEL_BUILD=PASS'),('verify_model','OA_MR_MODEL_READBACK=PASS')]:
                result=call(mode);self.assertEqual(result.returncode,0,result.stderr);self.assertIn(marker,result.stdout)
            text=report.read_text(encoding='utf-8');self.assertIn('field_status=not_solved source_status=not_requested',text);self.assertIn('group="detector"',text)
            rawconfig=config.read_text(encoding='utf-8');config.write_text(rawconfig.replace('domain="'+self.mr+'_detector"','domain="wrong_domain"',1),encoding='utf-8')
            result=call('verify_model');self.assertNotEqual(result.returncode,0);self.assertIn('model target domain is not in the saved geometry',result.stderr)

    def test_public_prepare_model_uses_explicit_three_asset_authorities(self):
        import json
        from dataclasses import asdict
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'geometry.json';path.write_text(json.dumps(asdict(self.compiled)),encoding='utf-8')
            source=SimpleNamespace(data_path=lambda key:path,reference={'manifest':{}})
            context=SimpleNamespace(tools={'simion':Path(__file__).resolve()},execution_root=root)
            request=dict(oa_groups=copy.deepcopy(self.drive['oa_groups']),mr_authority=copy.deepcopy(self.drive['mr_authority']),pulse=copy.deepcopy(self.drive['pulse']),clock={'phase_reference_instrument_time_us':0.},clock_authority={'example_resource':'instrument_clock_authority_v1.json'})
            stage=dict(limits={'transient_run_directory_bytes':1},artifact_retention={})
            with patch('msplatform.results.artifacts.open_artifact',side_effect=[source,'OPENED']), patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':{}}) as owner:
                self.assertEqual(operations.prepare_model({},drive=request,physics=RF_PHYSICS,context=context),'OPENED')
            payload=owner.call_args.kwargs['payload'];self.assertEqual(len(payload['model']['native_drive_rows']),41)
            self.assertEqual(Path(owner.call_args.kwargs['action'].keywords['seed_record']['path']).name,'3_instance_seed.iob')

    def test_existing_field_consumer_refuses_oa_mr_before_assets(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion.field_closure import load_field_model
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.json';path.write_text(json.dumps(require_prepared_model(self.compiled_model())),encoding='utf-8')
            source=SimpleNamespace(kind='prepared_model',metadata=dict(backend='simion',drive_configured=True,geometry_materialized=True,field_status='not_solved',source_status='not_requested'),data_path=lambda key:path)
            with patch('msplatform.backends.simion.field_closure.open_artifact',return_value=source):
                with self.assertRaisesRegex(ValueError,'OA–MR field solve is not supported'):load_field_model({})
