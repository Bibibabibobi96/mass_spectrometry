"""Real provider/model/field consumers, with no solver or particle fabrication."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_simion_geometry_compiler import compiler_inputs
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.model import (
    PHYSICS, compile_prepared_model, project_resolved_drive, render_model_configuration, require_prepared_model,
)
from msplatform.backends.simion.native_plans import plan_solve_fields, plan_downstream_solve
from msplatform.backends.simion.resources import native_resource_path


LUA = Path('C:/Program Files/SIMION-2020/lua.exe')


def model_inputs(root):
    assembly, numerics, _ = compiler_inputs(root)
    compiled = compile_geometry(assembly, numerics=numerics)
    clock = dict(clock_epoch_id='model_fixture_epoch', authority_sha256='A' * 64,
                 phase_reference_instrument_time_us=0.)
    drive = project_resolved_drive(compiled, assembly['components_resolved'],
        pulse=dict(mode='timed', time_us=10., width_us=2.), clock=clock)
    return assembly, numerics, compiled, drive


def oa_model_inputs():
    from common.contracts.test_oa_geometry_compiler import oa_inputs
    from msplatform.backends.simion import compile_geometry as compile_independent_geometry
    assembly, numerics = oa_inputs()
    compiled = compile_independent_geometry(assembly, numerics=numerics)
    groups = {instance: {group: dict(kind='static', voltage_v=0. if group == 'grounded_shield' else 100.+index)
        for index, group in enumerate(mapping)}
        for instance, mapping in compiled.frontend_geometry['electrode_bindings'].items()}
    for index, instance in enumerate(groups):
        groups[instance]['repeller'] = dict(kind='pulse', off_voltage_v=-5.-index, on_voltage_v=2000.+index)
    drive = dict(groups=groups, pulse=dict(mode='timed', time_us=10., width_us=2.),
        clock=dict(clock_epoch_id='model_fixture_epoch', authority_sha256='A'*64,
                   phase_reference_instrument_time_us=0.))
    return assembly, numerics, compiled, drive


class PreparedModelTests(unittest.TestCase):
    def test_independent_oa_both_variants_bind_explicit_drive_without_tof_or_source(self):
        from msplatform.backends.simion.model import RF_PHYSICS
        assembly, _, compiled, drive = oa_model_inputs()
        before = copy.deepcopy(compiled)
        model = compile_prepared_model(compiled, assembly.components_resolved, drive=drive, physics=RF_PHYSICS)
        document = require_prepared_model(model)
        self.assertEqual(compiled, before)
        self.assertEqual(document['field_status'], 'not_solved')
        self.assertEqual(document['source_status'], 'not_requested')
        self.assertEqual(set(document['drive']['groups']), set(assembly.components_resolved))
        self.assertEqual({row['variant_id'] for row in compiled.frontend_geometry['composition_plan']['components'].values()},
                         {'two_zone', 'three_zone'})
        self.assertNotIn('downstream_geometry', document)
        self.assertEqual(document['geometry']['downstream_specs'], [])
        for row in document['native_drive_rows']:
            self.assertEqual(row['native_targets'], [dict(domain=row['instance_id'],
                electrode_id=compiled.frontend_geometry['electrode_bindings'][row['instance_id']][row['electrode_group_id']])])
        with self.assertRaisesRegex(ValueError, 'explicit caller-authored'):
            project_resolved_drive(compiled, assembly.components_resolved, clock=drive['clock'])
        with self.assertRaises(ValueError):
            plan_solve_fields(model, numerics={})

    def test_independent_oa_rejects_missing_group_bad_drive_and_changed_geometry(self):
        from msplatform.backends.simion.model import RF_PHYSICS
        assembly, _, compiled, drive = oa_model_inputs()
        instance = next(iter(drive['groups']))
        for mode in ('missing', 'extra', 'nonfinite', 'ground', 'waveform', 'clock', 'timing'):
            invalid = copy.deepcopy(drive)
            if mode == 'missing': del invalid['groups'][instance]['repeller']
            elif mode == 'extra': invalid['groups'][instance]['invented'] = dict(kind='static', voltage_v=1.)
            elif mode == 'nonfinite': invalid['groups'][instance]['repeller']['on_voltage_v'] = float('nan')
            elif mode == 'ground': invalid['groups'][instance]['grounded_shield']['voltage_v'] = 1.
            elif mode == 'waveform': invalid['groups'][instance]['repeller']['kind'] = 'rf'
            elif mode == 'clock': invalid['clock']['authority_sha256'] = 'missing'
            else: del invalid['pulse']
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                compile_prepared_model(compiled, assembly.components_resolved, drive=invalid, physics=RF_PHYSICS)
        changed = copy.deepcopy(compiled)
        changed.frontend_gems[instance] += '\n# stale geometry'
        with self.assertRaisesRegex(ValueError, 'canonical providers'):
            compile_prepared_model(changed, assembly.components_resolved, drive=drive, physics=RF_PHYSICS)
        static = copy.deepcopy(drive)
        del static['pulse']
        for rows in static['groups'].values(): rows['repeller'] = dict(kind='static', voltage_v=1234.)
        self.assertNotIn('pulse', compile_prepared_model(compiled, assembly.components_resolved,
            drive=static, physics=RF_PHYSICS).document['drive'])

    def test_real_public_example_keeps_backend_numerics_out_of_provider_model_inputs(self):
        from msplatform import assembly as assembly_api, components as component_api, examples as example_api
        from msplatform.backends import simion as simion_api

        case = example_api.load_example('rf_oatof_functional_v1')
        parts = {name: component_api.resolve_component(request) for name, request in case.component_requests.items()}
        assembly = assembly_api.assemble(case.recipe, parts)
        compiled = simion_api.compile_geometry(assembly, numerics=case.geometry_numerics)
        original = copy.deepcopy(compiled)
        components = {name: compiled.components_resolved[name]
                      for name in compiled.frontend_geometry['composition_plan']['scope']['instance_ids']}
        self.assertNotIn('simion_detector_marker', components['oatof'])
        self.assertNotIn('simion_geometry_build', components['oatof'])
        drive = project_resolved_drive(compiled, components, pulse=dict(mode='held_off'),
            clock=dict(clock_epoch_id='pure-public-example-fixture', authority_sha256='A'*64,
                       phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(compiled, components, drive=drive, physics=PHYSICS)
        document = require_prepared_model(model)
        self.assertIn(document['model_identity_sha256'], render_model_configuration(model))
        self.assertEqual(compiled, original)
        self.assertNotIn('simion_detector_marker', model.document['components_resolved']['oatof'])
        self.assertNotIn('simion_detector_marker', model.document['geometry']['components_resolved']['oatof'])
        self.assertTrue(any(row['electrode_group_id']=='reflectron_midgrid'
                            for row in model.document['native_drive_rows']))
        expected = {str(key) for key in compiled.frontend_geometry['electrode_bindings']['oatof'].values()}
        self.assertEqual(set(document['electrical_projection']['accelerator_on']), expected)

    def test_default_model_matches_existing_field_contract_and_native_permutation(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, compiled, drive = model_inputs(Path(directory))
            # Preserve scientific identity while actually changing native labels.
            changed = copy.deepcopy(numerics)
            changed['electrode_group_native_ids'] = {
                instance: {group: 500 - eid for group, eid in mapping.items()}
                for instance, mapping in compiled.frontend_geometry['electrode_bindings'].items()}
            permuted = compile_geometry(assembly, numerics=changed)
            domains = copy.deepcopy(numerics['frontend_domains'])
            domains['parent']['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
            for geometry in (compiled, permuted):
                with self.subTest(permuted=geometry is permuted):
                    explicit = project_resolved_drive(geometry, assembly['components_resolved'],
                        pulse=drive['pulse'], clock=drive['clock'])
                    model = compile_prepared_model(geometry, assembly['components_resolved'], drive=explicit, physics=PHYSICS)
                    current = plan_solve_fields(model, numerics=dict(frontend_domains=domains, rf_reference_voltage_v=10000.))
                    legacy = plan_solve_fields(geometry, assembly['components_resolved'],
                        drive=dict(pulse_voltage_policy_id=PHYSICS['pulse_voltage_policy_id'], rf_reference_voltage_v=10000.),
                        numerics=dict(boundary_policy='native_zero_neumann', frontend_domains=domains))
                    self.assertEqual(current['field_design'], legacy['field_design'])
                    self.assertEqual(current['downstream_specs'], legacy['downstream_specs'])
                    self.assertEqual(set(model.document['drive']['groups']['multipole']), set(drive['groups']['multipole']))
            held = copy.deepcopy(drive)
            held['pulse'] = dict(mode='held_off')
            model = compile_prepared_model(compiled, assembly['components_resolved'], drive=held, physics=PHYSICS)
            plan = plan_solve_fields(model, numerics=dict(frontend_domains=domains, rf_reference_voltage_v=10000.))
            self.assertEqual([row['kind'] for row in plan['field_design']['working_points']], ['carrier_off', 'rf_reference'])

    def test_real_complete_provider_snapshot_and_no_source_or_numeric_dt(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, _, compiled, drive = model_inputs(Path(directory))
            before = copy.deepcopy((assembly, compiled, drive))
            model = compile_prepared_model(compiled, assembly['components_resolved'], drive=drive, physics=PHYSICS)
            document = require_prepared_model(model)
            self.assertEqual((assembly, compiled, drive), before)
            self.assertEqual(document['source_status'], 'not_requested')
            self.assertEqual(document['field_status'], 'not_solved')
            self.assertNotIn('particle_source', document['components_resolved']['oatof'])
            self.assertNotIn('rf_steps_per_period', render_model_configuration(model))
            self.assertNotIn('birth', render_model_configuration(model))
            self.assertEqual(set(document['drive']['groups']), {'multipole', 'oatof'})
            self.assertIn('reflectron_midgrid', document['drive']['groups']['oatof'])
            self.assertIn('reflectron_backplate', document['drive']['groups']['oatof'])
            ground = next(row for row in document['native_drive_rows'] if row['electrode_group_id'] == 'common_ground')
            self.assertEqual({row['domain'] for row in ground['native_targets']},
                             {'parent', 'flight_tube', 'reflectron', 'detector'})
            document['drive']['groups'].clear()
            self.assertTrue(model.document['drive']['groups'])
            tampered = model.document
            tampered['drive']['pulse']['time_us'] += 1
            with self.assertRaisesRegex(ValueError, 'identity'):
                require_prepared_model(replace(model, _document_json=json.dumps(tampered)))

    def test_model_drive_reaches_actual_frontend_and_downstream_field_plans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, numerics, compiled, drive = model_inputs(root)
            rf_group = next(key for key, row in drive['groups']['multipole'].items() if row['kind'] == 'rf')
            drive['groups']['multipole'][rf_group]['common_mode_v'] = 123.25
            drive['groups']['multipole'][rf_group]['dc_v'] = -7.5
            drive['groups']['oatof']['accelerator_repeller']['on_voltage_v'] = 4321.
            drive['groups']['oatof']['reflectron_midgrid']['voltage_v'] = 5678.
            model = compile_prepared_model(compiled, assembly['components_resolved'], drive=drive, physics=PHYSICS)
            domains = copy.deepcopy(numerics['frontend_domains'])
            domains['parent']['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
            plan = plan_solve_fields(model, numerics=dict(frontend_domains=domains, rf_reference_voltage_v=10000.))
            points = {row['kind']: row for row in plan['field_design']['working_points']}
            rf_native = compiled.frontend_geometry['electrode_bindings']['multipole'][rf_group]
            repeller = compiled.frontend_geometry['electrode_bindings']['oatof']['accelerator_repeller']
            self.assertEqual(points['carrier_off']['electrode_voltages_v'][str(rf_native)], 115.75)
            self.assertEqual(points['pulse_delta']['electrode_voltages_v'][str(repeller)], 4321.)
            self.assertEqual(plan['model_identity_sha256'], model.document['model_identity_sha256'])
            records = {role: dict(raw_record=dict(path=str(root / (role + '.pa#')), bytes=123, sha256='B'*64),
                                 surface_records=[] if role == 'reflectron' else
                                 [dict(path=str(root / (role + '.pa-surf')), bytes=5, sha256='C'*64)])
                       for role in ('flight_tube', 'reflectron', 'detector')}
            downstream = plan_downstream_solve(model, raw_geometry_assets=records, working_directory=root/'solve',
                convergence_v=dict(flight_tube=.001, reflectron=.001, detector=.001),
                exporter_resource=native_resource_path('export_standalone_pa.lua'),
                verifier_resource=native_resource_path('audit_downstream_fields.lua'))
            projection = next(text for path, text in downstream.materializations.items() if path.endswith('projection.lua'))
            self.assertIn('5678', projection)
            self.assertEqual(downstream.operations[0]['stage'], 'pa_refine')
            with self.assertRaisesRegex(ValueError, 'competing'):
                plan_solve_fields(model, drive={}, numerics={})
            # A drive edit creates a new model, leaving source geometry unchanged.
            changed = copy.deepcopy(drive)
            changed['pulse']['time_us'] += 1
            other = compile_prepared_model(compiled, assembly['components_resolved'], drive=changed, physics=PHYSICS)
            self.assertNotEqual(other.document['model_identity_sha256'], model.document['model_identity_sha256'])
            self.assertEqual(other.document['geometry'], model.document['geometry'])

    def test_missing_extra_stale_alias_clock_ground_and_waveform_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, _, compiled, drive = model_inputs(Path(directory))
            rf_group = next(key for key, row in drive['groups']['multipole'].items() if row['kind'] == 'rf')
            for case in ('missing', 'extra', 'alias', 'clock', 'phase_anchor', 'ground', 'waveform', 'bool', 'off', 'phase'):
                invalid = copy.deepcopy(drive)
                if case == 'missing': invalid['groups']['multipole'].pop(rf_group)
                elif case == 'extra': invalid['groups']['oatof']['unknown'] = dict(kind='static', voltage_v=0.)
                elif case == 'alias': invalid['groups']['multipole']['1'] = invalid['groups']['multipole'].pop(rf_group)
                elif case == 'clock': invalid['clock']['authority_sha256'] = 'bad'
                elif case == 'phase_anchor': invalid['clock']['phase_reference_instrument_time_us'] = 1.
                elif case == 'ground': invalid['groups']['oatof']['common_ground']['voltage_v'] = 1.
                elif case == 'waveform': invalid['groups']['multipole'][rf_group]['waveform'] = 'square'
                elif case == 'bool': invalid['groups']['multipole'][rf_group]['frequency_hz'] = True
                elif case == 'off': invalid['groups']['oatof']['accelerator_repeller']['off_voltage_v'] = 1.
                else: invalid['groups']['multipole'][rf_group].pop('phase_rad')
                with self.subTest(case=case), self.assertRaises(ValueError):
                    compile_prepared_model(compiled, assembly['components_resolved'], drive=invalid, physics=PHYSICS)
            stale = copy.deepcopy(assembly['components_resolved'])
            stale['multipole']['drive']['phase_rad'] += .1
            with self.assertRaisesRegex(ValueError, 'stale'):
                compile_prepared_model(compiled, stale, drive=drive, physics=PHYSICS)
            with self.assertRaisesRegex(ValueError, 'physics'):
                compile_prepared_model(compiled, assembly['components_resolved'], drive=drive, physics={**PHYSICS, 'material':'unknown'})

    @unittest.skipUnless(LUA.is_file(), 'standalone Lua interpreter unavailable')
    def test_actual_saved_consumer_rf_phase_dc_and_half_open_pulse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, compiled, drive = model_inputs(root)
            for row in drive['groups']['multipole'].values():
                if row['kind'] == 'rf':
                    row.update(waveform='sine', frequency_hz=1e6, phase_rad=0., rf_amplitude_v=100., common_mode_v=7., dc_v=3.)
            drive['groups']['oatof']['accelerator_repeller']['on_voltage_v'] = 4321.
            model = compile_prepared_model(compiled, assembly['components_resolved'], drive=drive, physics=PHYSICS)
            config = root/'model.lua'
            config.write_text(render_model_configuration(model), encoding='utf-8')
            paths = [native_resource_path(name).as_posix() for name in
                     ('model_drive.lua', 'rf_drive.lua', 'single_flight_pulse_hook.lua', 'voltage_waveforms.lua')]
            script = root/'readback.lua'
            script.write_text('local config=dofile('+json.dumps(config.as_posix())+')\n'+
                '\n'.join(f'local m{i}=dofile({json.dumps(path)})' for i, path in enumerate(paths)) + '''
local consumer=m0.new(config,m1,m2,m3)
local function group_at(t,instance,group)
  for _,row in ipairs(consumer.evaluate_at(t)) do
    if row.instance_id==instance and row.electrode_group_id==group then return row.voltage_v end
  end
  error('missing consumer group')
end
for _,row in ipairs(config.groups) do
  if row.kind=='rf' then
    assert(group_at(0,row.instance_id,row.electrode_group_id)==10)
    assert(math.abs(group_at(.25,row.instance_id,row.electrode_group_id)-(10+row.polarity*100))<1e-12)
  end
end
assert(group_at(9.999,'oatof','accelerator_repeller')==0)
assert(group_at(10,'oatof','accelerator_repeller')==4321)
assert(group_at(12,'oatof','accelerator_repeller')==0)
assert(consumer.describe().model_identity_sha256==config.model_identity_sha256)
print('MODEL_CONSUMER=PASS NOT_SOLVED=True SOURCE=False')
''', encoding='utf-8')
            result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=30, check=False, cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('MODEL_CONSUMER=PASS', result.stdout)

    @unittest.skipUnless(LUA.is_file(), 'standalone Lua interpreter unavailable')
    def test_physical_kernels_retain_runtime_clock_step_and_setter_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = [native_resource_path(name).as_posix() for name in
                         ('rf_drive.lua', 'single_flight_pulse_hook.lua', 'voltage_waveforms.lua')]
            script = root/'kernel.lua'
            script.write_text('\n'.join(f'local m{i}=dofile({json.dumps(path)})' for i, path in enumerate(resources)) + '''
for _,wave in ipairs{'sine','cosine'} do
  local config={waveform=wave,frequency_hz=1100000,phase_rad=.37,rf_amplitude_v=82,rf_scale=.5}
  local physical=m0.compile_physical(config)
  config.rf_steps_per_period=40
  local runtime=m0.new_differential(config)
  assert(runtime.timestep_cap_us==1e6/1100000/40)
  for _,t in ipairs{-1,0,.25,10,12} do
    assert(physical.phase_at(t)==runtime.phase_at(t))
    assert(physical.differential_at(t)==runtime.differential_at(t))
  end
  config.common_mode_scale=1;config.group_dc_v={3,-3}
  config.electrodes={{electrode_id=91,electrode_group=1,polarity=1,common_mode_v=7},
                     {electrode_id=12,electrode_group=2,polarity=-1,common_mode_v=-9}}
  local rods=m0.new(config);local ids,values={},{}
  rods.apply_at(.25,function(id,value) ids[#ids+1]=id;values[#values+1]=value end)
  assert(ids[1]==91 and ids[2]==12)
  assert(values[1]==10+physical.differential_at(.25))
  assert(values[2]==-12-physical.differential_at(.25))
end
local now,queries=10,0
local args={canonical_clock=function() queries=queries+1;return now end,
  voltage_waveforms=m2,pulse_time_us=10,pulse_width_us=2,pulse_mode=function() return 1 end}
local runtime=m1.new(args)
local physical_args={}
for key,value in pairs(args) do if key~='canonical_clock' then physical_args[key]=value end end
local physical=m1.compile_physical(physical_args)
assert(queries==0)
for _,t in ipairs{12,9,10,11,9.999,12.001} do
  local a,b=runtime.state_at(t),physical.state_at(t)
  assert(a.active==b.active and a.next_edge_us==b.next_edge_us)
  assert(runtime.cap_timestep_at(t,.5)==physical.cap_timestep_at(t,.5))
end
assert(queries==0)
assert(runtime.instrument_time_us()==10 and queries==1)
local okay=pcall(function() m0.new_differential{waveform='sine',frequency_hz=1e6,
  phase_rad=0,rf_amplitude_v=1,rf_scale=1,rf_steps_per_period=0} end)
assert(not okay)
print('PHYSICAL_RUNTIME_PARITY=PASS CLOCK_QUERIES=1 SETTER_ORDER=91,12')
''', encoding='utf-8')
            result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=30, check=False, cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PHYSICAL_RUNTIME_PARITY=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
