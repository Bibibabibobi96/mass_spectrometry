"""SFI common-scalar tracking integration; no native solver execution."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from common.contracts import test_sfi_scalar_binding as fixture
from integrations.tests import test_single_reflection_program as programs
from msplatform.backends.simion import tracking_execution, tracking_program, tracking_units


class SfiScalarTrackingTests(unittest.TestCase):
    def setUp(self):
        self.basis_case = fixture.SfiScalarAdmissionTests(methodName='runTest')
        self.basis_case.setUp()
        self.addCleanup(self.basis_case.doCleanups)
        self.program_case = programs.SingleReflectionProgramTests(methodName='runTest')
        self.program_case.setUp()
        self.addCleanup(self.program_case.doCleanups)

    def test_real_admission_and_changed_source_refusal(self):
        c = self.basis_case
        design = c.root/'selected_field_design.json'
        design.write_text(json.dumps(c.design), encoding='utf-8')
        source = SimpleNamespace(data_path=lambda name: design)
        selection = dict(geometry_artifact=c.geometry_ref, samples=c.sample_refs)
        plan = dict(propagation={'scope':'continuous_assembly'}, rows=[1], flight=c.flight)
        actual = tracking_execution._resolve_scalar_basis(source, c.model, plan, selection)
        self.assertEqual(actual, c.resolve())
        bad = copy.deepcopy(selection)
        bad['samples']['carrier']['manifest']['sha256'] = '0'*64
        with self.assertRaises(AssertionError):
            tracking_execution._resolve_scalar_basis(source, c.model, plan, bad)
        with self.assertRaisesRegex(ValueError, 'nonempty continuous'):
            tracking_execution._resolve_scalar_basis(source, c.model, dict(plan, rows=[]), selection)

    def test_renderer_keeps_default_and_installs_final_scalar_after_region(self):
        c = self.program_case
        basis = self.basis_case.resolve()
        resources = Path(tracking_program.__file__).parent/'resources'
        adapter = (resources/'scalar_field_adapter.lua').read_text(encoding='utf-8-sig')
        composer = (resources/'sfi_scalar_field.lua').read_text(encoding='utf-8-sig')
        before = c.build(native_path_projection=False)
        actual = c.build(native_path_projection=False, scalar_field_basis=basis,
                         scalar_adapter_source=adapter, scalar_composer_source=composer)
        self.assertNotIn('single_flight_scalar_module', before)
        self.assertIn("assert(instance~=nil,'selected instance required')", actual)
        self.assertLess(actual.index('local result=single_flight_region_field.apply(base,state)'),
                        actual.index('ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=single_flight_scalar('))
        self.assertLess(actual.index('ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=single_flight_scalar('),
                        actual.index('function segment.instance_adjust()'))
        self.assertEqual(c.build(native_path_projection=False), before)

    def test_scalar_identity_changes_recovery_and_resources(self):
        basis = self.basis_case.resolve()
        plan = dict(source_realization={},field_manifest_identity={},model_identity_sha256='a',rows=[],
                    native_source_rows=[],source_provenance={'clock_records':{'clock_authority':{},'instrument_epoch':{}}},
                    absolute_deadlines_us_by_particle_id={},flight={},propagation={},observations={},numerics={},units=[],
                    scalar_field_basis=basis)
        with patch('msplatform.backends.simion.resources.native_resource_path',
                   side_effect=lambda name: Path(tracking_program.__file__).parent/'resources'/name):
            first = tracking_units.tracking_applicability(plan)
            changed = copy.deepcopy(plan)
            changed['scalar_field_basis']['bases']['carrier']['records']['field_v']['sha256'] = '0'*64
            self.assertNotEqual(first, tracking_units.tracking_applicability(changed))

    def test_scalar_observation_preserves_legacy_validation_boundary(self):
        from msplatform.backends.simion.tracking_field_observation import _validate_field_observation_row
        spec = dict(domain_id='detector', buckets=[dict(bucket_id='b',time_min_us=0,time_max_us=2)],deadline_us=2)
        sources = {name:{'field_v':{'path':'C:/fixture/'+name+'.pa'}}
                   for name in ('carrier','rf_reference','pulse_delta')}
        context = dict(observation_basis='native_entry_gradient_no_extra_query',
            static_carrier_record={'path':'C:/fixture/detector.pa'},eligible_batch_particle_ids=[7],
            instance_index=4,world_frame_id='world',scalar_sources=sources)
        row = dict(schema_version=1,role='single_reflection_applied_field_query',basis='common_scalar_query_v1',
            record_seq=1,callback_seq=1,bucket_id='b',instrument_time_us=1.,solver_elapsed_us=1.,particle_id=7,
            ion_number=1,instance_index=4,domain_id='detector',world_frame_id='world',world_position_mm=[0,0,0],
            grid_spacing_mm=[1,1,1],instance_scale=1,instance_rotation_deg=[0,0,0],entry_gradient_gu=[0,0,0],
            pulse_active_used=False,pulse_basis='not_applied_not_queried',after_dynamic_gradient_gu=[0,0,0],
            region_override={'replace_all':False},after_region_gradient_gu=[0,0,0],final_gradient_gu=[1,2,3],
            actual_rf_phase_rad=0.,rf_phase_basis='unwrapped_kernel_phase_at',carrier_native_path='C:/fixture/detector.pa',
            scalar_sources={name:record['field_v']['path'] for name,record in sources.items()},
            scalar_rf_coefficient=0.,scalar_pulse_coefficient=0,legacy_fields_intermediate_only=True)
        _validate_field_observation_row(row,spec,context,{'record_seq':0,'callback_seq':0},{'b':0})
        bad = copy.deepcopy(row)
        bad['scalar_sources']['carrier'] = 'C:/other.pa'
        with self.assertRaisesRegex(ValueError,'scalar observation'):
            _validate_field_observation_row(bad,spec,context,{'record_seq':0,'callback_seq':0},{'b':0})
        legacy_context = dict(context)
        legacy_context.pop('scalar_sources')
        legacy = {key:value for key,value in row.items() if key not in
                  {'scalar_sources','scalar_rf_coefficient','scalar_pulse_coefficient','legacy_fields_intermediate_only'}}
        legacy['basis'] = 'native_entry_gradient_no_extra_query'
        with self.assertRaisesRegex(ValueError,'final capture'):
            _validate_field_observation_row(legacy,spec,legacy_context,{'record_seq':0,'callback_seq':0},{'b':0})

    @unittest.skipUnless(programs.LUA.is_file(), 'plain Lua unavailable')
    def test_generated_callback_scalar_overrides_region_and_observer_reports_final(self):
        import re
        import subprocess
        c = self.program_case
        directory = c.root/'scalar-observer-fixture'
        directory.mkdir()
        request, run, _ = programs.scientific_preparation_fixture(directory, recorded_birth=True)
        programs.prepare(request, run)
        c.upstream, c.oatof = programs.read_designs(run)
        c.geometry = json.loads((run/'inputs/frontend_geometry.json').read_text(encoding='utf-8'))
        c.design = json.loads((run/'inputs/frontend_field_design.json').read_text(encoding='utf-8'))
        basis = self.basis_case.resolve()
        resources = Path(tracking_program.__file__).parent/'resources'
        composer = (resources/'sfi_scalar_field.lua').read_text(encoding='utf-8-sig')
        adapter = "return function(binding) return function(inst,x,y,z) if binding.scalar_pa:find('carrier',1,true) then return 1,2,3 elseif binding.scalar_pa:find('rf_reference',1,true) then return 4,5,6 else return 7,8,9 end end end"
        specification = programs.field_observation_spec()
        observation = dict(specification=specification, evidence_context=dict(
            phase='full_instrument', clock_epoch_id='test-clock', mother_particle_ids=[11,77],
            input_records={'fixture':'inert callback'}, scalar_sources={
                name:item['records'] for name,item in basis['bases'].items()}))
        program = c.build(native_path_projection=False, field_observation=observation,
            scalar_field_basis=basis, scalar_adapter_source=adapter, scalar_composer_source=composer)
        tail = r'''
segment.scalar_test_setup=function()
  local rf={path='C:/inert/rf.pa',field_vc=function() return 2,-3,5 end}
  local pulse={path='C:/inert/delta.pa',field_vc=function() return 7,11,-13 end}
  single_flight_standalone_dynamic_by_instance={[3]={role='accelerator_main',rf_differential_pas={rf},pulse_delta_pa=pulse,rf_reference_voltage_v=10000}}
  single_flight_initialize_rf_drives()
  single_flight_pulse=single_flight_pulse_component.new{canonical_clock=single_flight_instrument_time_us,
    voltage_waveforms=single_flight_voltage_waveforms,pulse_time_us=10,pulse_width_us=3,pulse_mode=function() return 1 end}
  single_flight_scalar=single_flight_scalar_module.new(single_flight_scalar_adapter,single_flight_rf_kernel,single_flight_pulse,
    {carrier={scalar_pa='carrier'},rf_reference={scalar_pa='rf_reference'},pulse_delta={scalar_pa='pulse_delta'}},
    {waveform='cosine',frequency_hz=250000,phase_rad=0,phase_reference_instrument_time_us=0})
  single_flight_scalar_rf=single_flight_rf_kernel.compile_physical{waveform='cosine',frequency_hz=250000,phase_rad=0,rf_amplitude_v=1,rf_scale=1}
  single_flight_analyzer={efield_adjust=function() return {} end}
  single_flight_region_field={apply=function() return {replace_all=true,dvoltsy_gu=5} end}
  single_flight_field_observer.start_run()
end
'''
        program_path = c.root/'scalar-observed.lua'
        program_path.write_text(re.sub(r'\badjustable\s+', '', program)+tail,encoding='utf-8',newline='\n')
        script = c.root/'scalar-callback.lua'
        script.write_text(r'''
segment={};simion={workbench_program=function() end,early_access=function() end,wb={instances={}}}
local carrier={path='C:/inert/front.pa',dx_mm=.3,dy_mm=.25,dz_mm=.1,field_vc=function() return -10,-20,-30 end}
simion.wb.instances[3]={pa=carrier,scale=1,az=0,el=0,rt=0,wb_to_pa_coords=function(self,x,y,z) return x,y,z end}
dofile(arg[1]);segment.scalar_test_setup()
ion_instance=3;ion_number=1;ion_time_of_flight=.75;ion_px_mm=4;ion_py_mm=5;ion_pz_mm=6
ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
segment.efield_adjust()
assert(math.abs(ion_dvoltsx_gu-1)<1e-12 and math.abs(ion_dvoltsy_gu-2)<1e-12 and math.abs(ion_dvoltsz_gu-3)<1e-12)
''',encoding='utf-8',newline='\n')
        result = subprocess.run([str(programs.LUA),str(script),str(program_path)],cwd=c.root,
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        rows = [json.loads(line.split(' ',2)[2]) for line in result.stdout.splitlines()
                if line.startswith('TRACE: applied_field_observation ')]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['basis'],'common_scalar_query_v1')
        self.assertEqual(rows[0]['after_region_gradient_gu'],[0,5,0])
        # cos(pi/2) and three-term binary64 arithmetic retain a few ulps.
        import math
        for actual, expected in zip(rows[0]['final_gradient_gu'], (1.,2.,3.), strict=True):
            self.assertLessEqual(abs(actual-expected), 8*math.ulp(expected))
        self.assertTrue(rows[0]['legacy_fields_intermediate_only'])
        from msplatform.backends.simion.tracking_field_observation import _validate_field_observation_row
        parser_context = dict(eligible_batch_particle_ids=[11,77],instance_index=3,world_frame_id='oatof_global',
            rf_sources=[{'instance_id':'multipole'}],field_records={'parent':{
                'carrier_off':{'path':'C:/inert/front.pa'},'rf_reference':{'path':'C:/inert/rf.pa'},
                'pulse_delta':{'path':'C:/inert/delta.pa'}}},
            scalar_sources={name:item['records'] for name,item in basis['bases'].items()})
        counts = {item['bucket_id']:0 for item in specification['buckets']}
        _validate_field_observation_row(rows[0],specification,parser_context,{'record_seq':0,'callback_seq':0},counts)

    def test_public_track_admits_basis_and_binds_owner_arguments(self):
        from common.contracts import test_simion_tracking_execution as tracking_fixture
        from msplatform.backends.simion import operations
        case = tracking_fixture.TrackingExecutionPlanTests(methodName='runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        public_root = self.basis_case.root/'public'
        public_root.mkdir()
        source, session_type, _ = tracking_fixture.tracking_action_fixture(case, public_root)
        session = session_type()
        selection = dict(geometry_artifact=self.basis_case.geometry_ref, samples=self.basis_case.sample_refs)
        stage = {'limits': {'transient_run_directory_bytes':1}, 'artifact_retention':{}}
        with patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
             patch('msplatform.execution.owner.run_managed_stage', return_value={'manifest':{}}) as owner, \
             patch('msplatform.results.artifacts.open_artifact', return_value='published'):
            result = operations.track(source, case.packet, propagation=case.policy,
                observations={'plane_observations':[]}, numerics=case.numerics, context=session.context,
                scalar_field_basis=selection)
        self.assertEqual(result,'published')
        args = owner.call_args.kwargs
        selected = args['payload']['scalar_field_basis']
        self.assertEqual(set(selected['bases']), {'carrier','rf_reference','pulse_delta'})
        self.assertEqual(args['action'].keywords['expected_scalar_basis'], selected)
        self.assertEqual(len(args['source_references']), 8)

    def test_real_recorded_birth_owner_guards_scalar_records_and_recovery(self):
        import os
        import shutil
        import sys
        from msplatform.execution import run_session
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.resources import resource_path
        from msplatform.results.artifacts import open_artifact
        from msplatform.workflows.single_reflection_flight.recorded_birth import track_recorded_birth
        from common.contracts.test_support.sfi_scalar_owner_fixture import make_fixture, inert_native_leaf, retained_owner_directory

        with retained_owner_directory() as directory:
            selected = make_fixture(Path(directory))
            values = selected['context']
            context = ExecutionContext(workspace=Path(values['workspace']), python_executable=Path(sys.executable),
                powershell_executable=Path(values['powershell_executable']),tools={'simion':Path(sys.executable)},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'),
                capacity_policy_path=Path(values['capacity_policy_path']),stage_policy_path=Path(values['stage_policy_path']))
            observed = []
            leaf = inert_native_leaf(run_session.run_observed_process, observed)
            args = dict(preparation_manifest=selected['preparation_manifest'],fields=selected['fields'],
                species_id=selected['species_id'],expected_particle_ids=selected['expected_particle_ids'],
                observations={'plane_observations':[]},context=context,scalar_field_basis=selected['scalar_field_basis'])
            inherited = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                             MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,inherited),patch.object(run_session,'run_observed_process',side_effect=leaf):
                result = track_recorded_birth(**args)
                self.assertEqual(len(observed),3)
                basis = selected['scalar_field_basis']['samples']
                expected = set()
                for reference in basis.values():
                    sample = open_artifact(reference,expected_kind='scalar_field_samples')
                    expected.update(sample.data_path(key).resolve() for key in ('field_v','field_valid'))
                for operation in observed:
                    actual = {Path(row['path']).resolve() for row in operation['immutable_input_records']}
                    self.assertTrue(expected <= actual)
                reused = track_recorded_birth(**args,recovery_reference=result.reference['manifest'])
                self.assertEqual(len(observed),3)
                self.assertEqual(reused.metadata['reused_unit_count'],1)
                from msplatform.backends.simion import resources as simion_resources
                package = Path(simion_resources.files('msplatform.backends.simion'))
                isolated = Path(directory)/'missing-composer-package'
                shutil.copytree(package/'resources',isolated/'resources',
                                ignore=shutil.ignore_patterns('sfi_scalar_field.lua'))
                with patch.object(simion_resources,'files',return_value=isolated):
                    with self.assertRaisesRegex(FileNotFoundError,'installed SIMION native resource is missing: sfi_scalar_field.lua'):
                        track_recorded_birth(**args)
                self.assertEqual(len(observed),3)
                sample = open_artifact(basis['carrier'],expected_kind='scalar_field_samples')
                path = sample.data_path('field_v')
                before = path.read_bytes()
                try:
                    path.write_bytes(bytes([before[0]^1])+before[1:])
                    with self.assertRaises((AssertionError,ValueError)):
                        track_recorded_birth(**args)
                    self.assertEqual(len(observed),3)
                finally:
                    path.write_bytes(before)
            collection = json.loads(result.data_path('collection').read_text(encoding='utf-8'))
            self.assertEqual(collection['original_mother']['mother_particle_ids'],selected['expected_particle_ids'])
