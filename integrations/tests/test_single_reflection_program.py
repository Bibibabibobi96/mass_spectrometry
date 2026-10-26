"""Native field design feeds the existing full-flight builder and callbacks."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from integrations.runtime.build_single_flight_program import (
    build_successor_program, _upstream_rod_drive, validate_native_flight,
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE, STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    DOWNSTREAM_STATIC_ASSET_ROLE, DOWNSTREAM_STATIC_ASSET_REPRESENTATION,
)
from integrations.runtime.single_flight_source import lua_value as _lua_value
from integrations.tests.test_single_reflection_preparation import fixture, release_fixture, rename_recipe_instances, rename_author_instances
from integrations.tests.test_single_reflection_fields import multipole_source
from integrations.workflows.single_reflection_flight.prepare import prepare
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import derive_simion_geometry
from integrations.runtime.single_flight_frontend import native_frontend_instances

ROOT = Path(__file__).resolve().parents[2]
LUA = Path("C:/Program Files/SIMION-2020/lua.exe")


def read_designs(run):
    geometry = json.loads((run/'inputs/frontend_geometry.json').read_text())
    multipole, oatof = native_frontend_instances(geometry['composition_plan'])
    def load(instance):
        return json.loads((run/'inputs/components'/instance/'resolved_design.json').read_text()) if instance else None
    if len(multipole) > 1:
        raise ValueError('this fixture reads one multipole provider')
    return load(multipole[0]) if multipole else None, load(oatof)


def response_paths(bank, directory):
    """Explicit inert paths; tests open fake PA objects without field payloads."""
    return {row['role']: dict(
        rf_differential_pa_paths=[(directory/name).as_posix()
            for name in row.get('rf_differential_pa_basenames', [])],
        **({'pulse_delta_pa_path': (directory/row['pulse_delta_pa_basename']).as_posix()}
           if row.get('pulse_delta_pa_basename') else {}))
        for row in bank['dynamic_roles']}


class SingleReflectionProgramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        request,run,_ = fixture(self.root)
        prepare(request,run)
        self.upstream, self.oatof = read_designs(run)
        self.design = json.loads((run/"inputs/frontend_field_design.json").read_text())
        self.geometry = json.loads((run/"inputs/frontend_geometry.json").read_text())
        # Explicit pure-test numerics; these do not qualify a physical flight.
        self.flight = dict(pulse=dict(mode="timed", time_us=10., width_us=3.), maximum_flight_us=200.,
                           maximum_step_us=.001, trajectory_quality=17, rf_steps_per_period=80)
        self.dynamic = dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
            runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
            dynamic_roles=[dict(role="accelerator_main",instance_index=3,carrier_pa_basename="front.pa",
                rf_differential_pa_basenames=["rf.pa"],pulse_delta_pa_basename="delta.pa",
                rf_reference_voltage_v=self.design["rf_reference_voltage_v"])])
        # Pure builder fixture only: runtime tests must validate an actual
        # downstream producer receipt before deriving this in-memory contract.
        self.static = dict(schema_version=1,role=DOWNSTREAM_STATIC_ASSET_ROLE,
            runtime_representation=DOWNSTREAM_STATIC_ASSET_REPRESENTATION,
            receipt=dict(path="downstream_assets.json",bytes=123,sha256="A"*64),
            static_roles=[dict(role=name,instance_index=index,
                representation="standalone_voltageized_static_pa" if name=="reflectron" else "run_private_native_static_family",
                carrier_pa_basename=name+(".pa" if name=="reflectron" else ".pa0"),
                **({} if name=="reflectron" else dict(family_members=[name+suffix for suffix in (".pa#", ".pa0", ".pa1", ".pa-surf")])))
                for index,name in ((1,"flight_tube"),(2,"reflectron"),(4,"detector"))])
        self.sources = dict(
            analyzer_component_source=(ROOT/"projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_analyzer_component.lua").read_text(),
            pulse_hook_source=(ROOT/"integrations/runtime/single_flight_pulse_hook.lua").read_text(),
            voltage_waveforms_source=(ROOT/"common/simion/voltage_waveforms.lua").read_text(),
            frontend_hook_source=(ROOT/"integrations/runtime/single_flight_frontend_hook.lua").read_text(),
            rf_drive_kernel_source=(ROOT/"common/simion/rf_drive.lua").read_text())

    def build(self, **updates):
        kwargs = dict(frontend_geometry=self.geometry,birth_times_us=[.25,2.5],particle_ids=[11,77],
            flight=self.flight,initial_velocities_mm_per_us=[[0.,0.,1.],[0.,0.,1.]],
            standalone_dynamic_field_bank=self.dynamic,downstream_static_fields=self.static,
            **self.sources)
        kwargs.update(updates)
        if 'standalone_dynamic_field_paths' not in kwargs:
            bank = kwargs['standalone_dynamic_field_bank']
            kwargs['standalone_dynamic_field_paths'] = response_paths(
                bank if isinstance(bank, dict) else self.dynamic, self.root)
        instances, _ = native_frontend_instances(kwargs['frontend_geometry']['composition_plan'])
        providers = {instances[0]: self.upstream} if instances else {}
        return build_successor_program(providers,self.design,self.oatof,**kwargs)

    def test_native_requires_complete_finite_explicit_source_velocity(self):
        for velocities in (None, [], [[1.,2.,3.]], [[1.,2.],[3.,4.,5.]],
                           [[float('nan'),0.,0.],[0.,0.,0.]], [[True,0.,0.],[0.,0.,0.]],
                           [[float('inf'),0.,0.],[0.,0.,0.]], [["1",0.,0.],[0.,0.,0.]]):
            with self.subTest(velocities=velocities),self.assertRaisesRegex(ValueError,"finite initial velocity vector"):
                self.build(initial_velocities_mm_per_us=velocities)

    def test_public_voltage_math_source_is_required_and_validated(self):
        for source in ('', 'simion.workbench_program()\nreturn {}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.build(voltage_waveforms_source=source)
        kwargs = dict(frontend_geometry=self.geometry, flight=self.flight, birth_times_us=[0.],
            initial_velocities_mm_per_us=[[1., 0., 0.]], standalone_dynamic_field_bank=self.dynamic,
            standalone_dynamic_field_paths=response_paths(self.dynamic, self.root),
            downstream_static_fields=self.static,
            **{key: value for key, value in self.sources.items() if key!='voltage_waveforms_source'})
        instances, _ = native_frontend_instances(self.geometry['composition_plan'])
        with self.assertRaisesRegex(TypeError, 'voltage_waveforms_source'):
            build_successor_program({instances[0]: self.upstream}, self.design, self.oatof, **kwargs)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua interpreter unavailable')
    def test_pulse_hook_delegates_edge_caps_to_injected_public_math(self):
        """Pure hooks and math only; no solver callbacks or native PA fields."""
        script = self.root/'pulse_edge.lua'
        script.write_text("""
local public=assert(dofile(arg[1]))
local pulse=assert(dofile(arg[2]))
local calls=0
local shared={cap_before_edge=function(time,dt,edge)
 calls=calls+1;return public.cap_before_edge(time,dt,edge)
end,rectangular_gate=public.rectangular_gate}
local mode,time=1,-2
local cfg={canonical_clock=function() return time end,voltage_waveforms=shared,
 pulse_mode=function() return mode end,pulse_time_us=-1,pulse_width_us=2}
local hook=pulse.new(cfg)
for _,row in ipairs({{-2,1,false,-1},{-1,2,true,1},{0,1,true,1},
                    {1,3,false},{2,3,false}}) do
 time=row[1]
 local state=hook.state_at(time)
 assert(state.active==row[3] and state.next_edge_us==row[4])
 assert(hook.cap_timestep_at(time,3)==row[2])
 assert(hook.instrument_time_us()==time)
end
assert(calls==3,'timed hook did not delegate only its actual future edges')
time=-1-1e-12
assert(hook.cap_timestep_at(time,3)==-1-time,'edge cap gained a numerical cutoff')
assert(calls==4)
for _,selected in ipairs({0,2}) do
 mode=selected
 assert(hook.is_active_at(-100)==(mode==0))
 assert(hook.cap_timestep_at(-100,3)==3 and calls==4,'held mode requested a fictitious edge')
end
local off=pulse.new{canonical_clock=function() return -100 end,voltage_waveforms=shared,
 pulse_mode=function() return mode end}
assert(not off.is_active_at(-100) and off.cap_timestep_at(-100,3)==3)
mode=1;assert(not pcall(off.state_at,-100),'timing-free pulse left held OFF')
cfg.voltage_waveforms=nil
assert(not pcall(pulse.new,cfg),'missing mandatory public module accepted')
cfg.voltage_waveforms={}
assert(not pcall(pulse.new,cfg),'module without cap_before_edge accepted')
cfg.voltage_waveforms=shared;cfg.other=true
assert(not pcall(pulse.new,cfg),'unknown hook input accepted')
assert(not pcall(hook.cap_timestep_at,0,-1),'negative native step accepted')
print('INJECTED_PUBLIC_EDGE_CAP=PASS')
""", encoding='utf-8', newline='\n')
        result = subprocess.run([str(LUA),str(script),str(ROOT/'common/simion/voltage_waveforms.lua'),
            str(ROOT/'integrations/runtime/single_flight_pulse_hook.lua')], cwd=self.root,
            capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('INJECTED_PUBLIC_EDGE_CAP=PASS',result.stdout)

    def test_independent_response_paths_preserve_scientific_bank_and_validation(self):
        before = copy.deepcopy(self.dynamic)
        paths = response_paths(self.dynamic, self.root)
        paths['accelerator_main']['rf_differential_pa_paths'] = [(self.root/'rf_generation'/'rf.pa').as_posix()]
        paths['accelerator_main']['pulse_delta_pa_path'] = (self.root/'pulse_generation'/'delta.pa').as_posix()
        program = self.build(standalone_dynamic_field_paths=paths)
        self.assertEqual(self.dynamic, before)
        for path in (*paths['accelerator_main']['rf_differential_pa_paths'], paths['accelerator_main']['pulse_delta_pa_path']):
            self.assertIn(json.dumps(path), program)
        self.assertNotIn('response_directory', program)
        self.assertIn('simion.pas:open(path)', program)
        self.assertIn("standalone dynamic field carrier path differs", program)
        self.assertIn("label..' symmetry differs from carrier'", program)
        invalid = [{}, {'other': paths['accelerator_main']}, {'accelerator_main': 'relative'},
                   {'accelerator_main': None}]
        for change in ({'rf_differential_pa_paths': []}, {'rf_differential_pa_paths': ['relative/rf.pa']},
                       {'rf_differential_pa_paths': [(self.root/'wrong.pa').as_posix()]},
                       {'pulse_delta_pa_path': 'relative/delta.pa'}, {'extra': 'unused'}):
            invalid.append({'accelerator_main': {**paths['accelerator_main'], **change}})
        for mapping in invalid:
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.build(standalone_dynamic_field_paths=mapping)

    def test_recipe_instance_rename_and_order_do_not_change_program(self):
        original = self.build()
        plan = self.geometry['composition_plan']
        names = rename_recipe_instances(plan['recipe'])
        plan['components'] = {names[key]:value for key,value in plan['components'].items()}
        plan['scope']['instance_ids'] = ['tof_b','guide_a']
        self.geometry['electrode_bindings'] = {names[key]: value
            for key,value in self.geometry['electrode_bindings'].items()}
        # Compiler mechanical checks are unchanged physical values, not role names.
        renamed = self.build()
        self.assertEqual(renamed,original)

    def test_unselected_parent_connection_before_native_edge_does_not_change_program(self):
        from common.integration.resolve_assembly import compile_assembly_layout

        original_metadata = {}
        original = self.build(build_metadata=original_metadata)
        parent = self.geometry['composition_plan']
        recipe, components = copy.deepcopy(parent['recipe']), copy.deepcopy(parent['components'])
        selected = list(parent['scope']['instance_ids'])
        names = {instance: 'spare_' + instance for instance in selected}
        for instance in list(recipe['instances']):
            extra = copy.deepcopy(instance)
            extra['instance_id'] = names[instance['instance_id']]
            extra['transform']['translation_mm'][0] += 500.
            recipe['instances'].append(extra)
            components[extra['instance_id']] = copy.deepcopy(components[instance['instance_id']])
        extra_edge = copy.deepcopy(recipe['connections'][0])
        extra_edge['connection_id'] = 'a_unselected_parent_connection'
        for endpoint in ('upstream', 'downstream'):
            extra_edge[endpoint]['instance_id'] = names[extra_edge[endpoint]['instance_id']]
        recipe['connections'].append(extra_edge)
        self.geometry['composition_plan'] = compile_assembly_layout(recipe, components, local_scope=dict(
            instance_ids=selected, research_scope='original native frontend',
            boundary_assumptions='translated spare pair is excluded'))
        self.assertEqual(self.geometry['composition_plan']['connection_checks'][0]['connection_id'],
                         extra_edge['connection_id'])
        actual_metadata = {}
        self.assertEqual(self.build(build_metadata=actual_metadata), original)
        self.assertEqual(actual_metadata, original_metadata)

    def test_actual_design_no_legacy_namespace_or_position_overwrite(self):
        before = copy.deepcopy((self.upstream,self.design,self.geometry,self.oatof))
        metadata = {}
        program = self.build(build_metadata=metadata)
        self.assertEqual((self.upstream,self.design,self.geometry,self.oatof),before)
        self.assertEqual(metadata["physical_rod_piece_count"],32)
        self.assertEqual(metadata["physical_frontend_topology_id"],"three_zone_frontend_contract_derived_v1")
        self.assertEqual(metadata["instance_roles"],dict(flight_tube=1,reflectron=2,accelerator=3,detector=4))
        self.assertIn("sim_segment_global=1",program)
        self.assertNotIn("single_flight_apply_placement",program)
        self.assertNotIn("ai.x,ai.y,ai.z=",program)
        self.assertNotIn("entrance_reference_sleeve",program)
        self.assertIn("single_flight_source_particle_id={[1]=11,[2]=77}",program)
        self.assertIn("single_flight_time_origin_us={[1]=0.25,[2]=2.5}",program)
        carrier = self.design['working_points'][0]['electrode_voltages_v']
        self.assertEqual([carrier[str(electrode)] for electrode in (9, 10, 11)], [0., 0., 0.])
        self.assertNotIn('single_flight_rf.apply_static', program)
        drive = _upstream_rod_drive(self.upstream)
        self.assertEqual(len(drive["electrodes"]),8)
        self.assertEqual([row["electrode_group"] for row in drive["electrodes"]],[1,2]*4)
        self.assertEqual(program.count("function segment.initialize_run()"),1)
        self.assertNotIn("single_flight_pa_plus_", program)
        self.assertIn("adjustable trajectory_quality=17", program)
        self.assertIn("adjustable handoff_pulse_time_us=10", program)
        self.assertIn("adjustable handoff_pulse_width_us=3", program)
        self.assertNotIn("adjustable diagnostic_post_pulse_window_us=", program)
        self.assertNotIn("local observation_remaining=", program)
        self.assertIn("diagnostics={post_pulse_observation_window_us=false", program)
        for transport in ("OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET", "OATOF_ACCELERATOR_PA_OVERRIDE",
                          "OATOF_PRE_PULSE_RAW_TRACE_PATH", "OATOF_SIMION_PROGRAM_LOAD_REPORT"):
            self.assertNotIn(transport,program)

    def test_four_six_eight_provider_program_preserves_eight_electrical_groups(self):
        for project, rod_count in [('quadrupole', 4), ('hexapole', 6),
                                   ('octupole', 8)]:
            with self.subTest(project=project), tempfile.TemporaryDirectory() as directory:
                path, run, _ = fixture(Path(directory), source=multipole_source(project))
                prepare(path, run)
                self.upstream, self.oatof = read_designs(run)
                self.design = json.loads((run / 'inputs/frontend_field_design.json').read_text())
                self.geometry = json.loads((run / 'inputs/frontend_geometry.json').read_text())
                metadata = {}
                program = self.build(build_metadata=metadata)
                self.assertEqual(metadata['physical_rod_piece_count'], 4 * rod_count)
                self.assertEqual(len(_upstream_rod_drive(self.upstream)['electrodes']), 8)
                self.assertIn('single_flight_source_particle_id={[1]=11,[2]=77}', program)
                original = copy.deepcopy(self.upstream)
                for change in ('missing', 'duplicate', 'wrong_group'):
                    self.upstream = copy.deepcopy(original)
                    pieces = self.upstream['segmentation']['segmented_rod_array']['electrodes']
                    if change == 'missing': pieces.pop()
                    elif change == 'duplicate': pieces[-1] = copy.deepcopy(pieces[0])
                    else: pieces[0]['electrode_group'] = 2
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        self.build()


    def multiple_provider_inputs(self, count):
        """Compile real provider geometry/voltages; never construct physical PAs."""
        from integrations.tests.test_single_reflection_geometry import (
            multi_inputs, quadrupole_source, candidate_300mm_fixture,
        )
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        from integrations.workflows.single_reflection_flight.fields import prepare_field_design, POLICY

        parameters = ((4., 1., 1_000_000., .1), (4.5, 2., 1_100_000., .7),
                      (5., 3., 1_200_000., 1.3))[:count]
        sources = [quadrupole_source(r0=r0, dc=dc, frequency_hz=frequency, phase_rad=phase)
                   for r0, dc, frequency, phase in parameters]
        # Deliberately disagree with lexical instance/basename order: physical
        # global electrode bindings determine each response's drive ordinal.
        names = ['q_z', 'q_a', 'q_m'][:count]
        providers = dict(reversed(list(zip(names, sources, strict=True))))
        oatof = candidate_300mm_fixture()
        _, geometry = compile_frontend_geometry(providers, oatof,
            **multi_inputs(sources, oatof, names=names))
        design = prepare_field_design(providers, oatof, geometry,
            variant_id='three_zone_square', pulse_voltage_policy_id=POLICY,
            boundary_policy='native_zero_neumann', rf_reference_voltage_v=10000.,
            frontend_domains={'parent': {'refine_convergence_v':
                dict(carrier_off=.1, rf_reference=.1, pulse_delta=.1)}})
        dynamic = copy.deepcopy(self.dynamic)
        dynamic['dynamic_roles'][0]['rf_differential_pa_basenames'] = [
            'rf_z.pa', 'rf_a.pa', 'rf_m.pa'][:count]
        dynamic['dynamic_roles'][0]['rf_reference_voltage_v'] = design['rf_reference_voltage_v']
        kwargs = dict(frontend_geometry=geometry, birth_times_us=[-8.125, 2.5],
            particle_ids=[11, 77], initial_velocities_mm_per_us=[[1., 0., 0.]]*2,
            flight={**self.flight, 'maximum_step_us': .1},
            standalone_dynamic_field_bank=dynamic, downstream_static_fields=self.static, **self.sources)
        paths = response_paths(dynamic, self.root)['accelerator_main']
        paths['rf_differential_pa_paths'] = [(self.root/f'rf_generation_{index}'/name).as_posix()
            for index, name in enumerate(dynamic['dynamic_roles'][0]['rf_differential_pa_basenames'])]
        paths['pulse_delta_pa_path'] = (self.root/'pulse_generation'/'delta.pa').as_posix()
        kwargs['standalone_dynamic_field_paths'] = {'accelerator_main': paths}
        return providers, design, oatof, kwargs, names

    @unittest.skipUnless(LUA.is_file(), 'plain Lua interpreter unavailable')
    def test_two_and_three_independent_rf_programs_weight_real_ordered_responses(self):
        """Fake PA vectors test actual generated callbacks, not fields or Fly."""
        from integrations.workflows.single_reflection_flight.runtime import _instance_rows

        for count in (2, 3):
            with self.subTest(multipoles=count):
                providers, design, oatof, kwargs, names = self.multiple_provider_inputs(count)
                metadata = {}
                program = build_successor_program(providers, design, oatof, **kwargs, build_metadata=metadata)
                self.assertEqual(metadata['rf_instance_order'], names)
                self.assertEqual(program, build_successor_program(dict(reversed(list(providers.items()))),
                    design, oatof, **kwargs))
                geometry = kwargs['frontend_geometry']
                for index, name in enumerate(names, 1):
                    ids = geometry['electrode_bindings'][name].values()
                    values = {design['working_points'][0]['electrode_voltages_v'][str(eid)] for eid in ids}
                    self.assertTrue({float(index), -float(index)} <= values)
                carrier_names = dict(flight_tube='flight_tube.pa0', reflectron='reflectron.pa',
                                     accelerator='front.pa', detector='detector.pa0')
                rows = _instance_rows(geometry, metadata,
                    {role: dict(path='/inert/'+name) for role, name in carrier_names.items()})
                instances = []
                for row in rows:
                    place = row['placement']
                    instances.append(dict(filename=Path(row['path']).name,
                        **{axis: place[axis+'_mm'] for axis in 'xyz'}, az=place['az_deg'],
                        el=place['el_deg'], rt=place['rt_deg'], scale=place['scale'],
                        pa=dict(row['grid'], path=row['path'], symmetry='test', potential_type='electrostatic')))
                inspect = """
segment.inspect_drives=function() return single_flight_rf_drives end
segment.inspect_field=function(time)
  single_flight_apply_standalone_dynamic_field(simion.wb.instances[3],time)
end
segment.inspect_clock=function() return single_flight_instrument_time_us() end
"""
                program_path = self.root/f'multiple_{count}.lua'
                program_path.write_text(re.sub(r'\badjustable\s+', '', program+inspect),
                                        encoding='utf-8', newline='\n')
                script = self.root/f'check_multiple_{count}.lua'
                expected = [providers[name]['drive'] for name in names]
                basenames = kwargs['standalone_dynamic_field_bank']['dynamic_roles'][0]['rf_differential_pa_basenames']
                script.write_text("""segment={}
simion={workbench_program=function() end,early_access=function() end,pas={},wb={}}
simion.wb.instances="""+_lua_value(instances)+"""
local expected="""+_lua_value(expected)+"""
local basenames="""+_lua_value(basenames)+"""
local expected_paths="""+_lua_value([*kwargs['standalone_dynamic_field_paths']['accelerator_main']['rf_differential_pa_paths'],
                    kwargs['standalone_dynamic_field_paths']['accelerator_main']['pulse_delta_pa_path']])+"""
local vectors={{1,2,3},{5,-7,11},{-2,13,-17}}
local reference=10000
for _,instance in ipairs(simion.wb.instances) do
 function instance:wb_to_pa_coords(x,y,z) return x,y,z end
 function instance:inside_wc() return false end
 function instance.pa:fast_adjust() error('DC/carrier must not be adjusted twice') end
end
local opens={}
function simion.pas:open(path)
 local name=assert(path:match('([^/]+)$'))
 opens[#opens+1]=path
 local ordinal
 for index,value in ipairs(basenames) do if value==name then ordinal=index end end
 assert(ordinal or name=='delta.pa','unexpected response path '..path)
 local pa={};for key,value in pairs(simion.wb.instances[3].pa) do pa[key]=value end
 function pa:field_vc()
  if not ordinal then return 4,5,6 end
  local v=vectors[ordinal];return reference*v[1],reference*v[2],reference*v[3]
 end
 return pa
end
dofile(arg[1]);segment.load();segment.initialize_run()
assert(segment.fast_adjust==nil,'full ordinary fields must not expose a voltage setter')
assert(#opens==#expected+1)
for index,path in ipairs(expected_paths) do
 assert(opens[index]==path,'response generation path or RF ordering changed')
end
local drives=segment.inspect_drives();assert(#drives==#expected)
ion_number=1;ion_instance=3;ion_time_of_flight=0;ion_splat=0
ion_px_mm=0;ion_py_mm=0;ion_pz_mm=-340
ion_vx_mm=1;ion_vy_mm=0;ion_vz_mm=0;ion_mass=100;ion_charge=1;ion_ke=2
segment.initialize()
local minimum_cap=math.huge
for index,drive in ipairs(drives) do
 assert(drive.apply_static==nil and drive.apply_at==nil and drive.apply_differential_at==nil)
 local cap=1e6/expected[index].frequency_Hz/80
 assert(drive.timestep_cap_us==cap)
 minimum_cap=math.min(minimum_cap,cap)
end
for _,time in ipairs({-5.125,-.5,0,10,12.5,13,17.25}) do
 ion_time_of_flight=time+8.125
 assert(segment.inspect_clock()==time,'birth epoch was reapplied or lost')
 local target={10,20,30}
 for index,drive in ipairs(drives) do
  local p=expected[index]
  local phase=2*math.pi*p.frequency_Hz*time*1e-6+p.phase_rad
  local voltage=p.rf_amplitude_V_zero_to_peak_per_group*math.cos(phase)
  assert(math.abs(drive.differential_at(time)-voltage)<1e-8,'instance frequency/phase changed')
  for axis=1,3 do target[axis]=target[axis]-voltage*vectors[index][axis] end
 end
 if time>=10 and time<13 then for axis=1,3 do target[axis]=target[axis]-(axis+3) end end
 ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
 segment.inspect_field(segment.inspect_clock())
 for axis,value in ipairs({ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu}) do
  assert(math.abs(value-target[axis])<1e-8,'RF response weight/pulse/DC double addition differs axis '..axis)
 end
end
for _,probe in ipairs({{17.25,minimum_cap},{12.9998,13-12.9998}}) do
 ion_time_of_flight=probe[1]+8.125;ion_time_step=1;segment.tstep_adjust()
 assert(math.abs(ion_time_step-probe[2])<1e-10,'multi-drive/edge timestep cap changed: '..ion_time_step)
end
print('MULTIPLE_INDEPENDENT_RF_PROGRAM=PASS COUNT='..#drives)
""", encoding='utf-8', newline='\n')
                result = subprocess.run([str(LUA), str(script), str(program_path)], cwd=self.root,
                                        capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn(f'MULTIPLE_INDEPENDENT_RF_PROGRAM=PASS COUNT={count}', result.stdout)

    def test_multiple_rf_program_rejects_missing_extra_and_unreferenced_responses(self):
        providers, design, oatof, kwargs, _ = self.multiple_provider_inputs(3)
        for mutation in ('missing', 'extra', 'duplicate', 'missing_pulse', 'missing_reference'):
            with self.subTest(mutation=mutation):
                actual = copy.deepcopy(kwargs)
                row = actual['standalone_dynamic_field_bank']['dynamic_roles'][0]
                if mutation=='missing': row['rf_differential_pa_basenames'].pop()
                elif mutation=='extra': row['rf_differential_pa_basenames'].append('extra.pa')
                elif mutation=='duplicate': row['rf_differential_pa_basenames'][1]=row['rf_differential_pa_basenames'][0]
                elif mutation=='missing_pulse': row.pop('pulse_delta_pa_basename')
                else: row.pop('rf_reference_voltage_v')
                with self.assertRaises(ValueError):
                    build_successor_program(providers, design, oatof, **actual)

    @unittest.skipUnless(LUA.is_file(),"plain Lua interpreter unavailable")
    def test_local_oatof_uses_real_two_field_callbacks_without_any_rod_drive(self):
        from integrations.workflows.single_reflection_flight.runtime import _instance_rows
        folder=self.root/"local_oatof"
        folder.mkdir()
        request,run,author,_=release_fixture(folder,local=True)
        rename_author_instances(request,author)
        prepare(request,run)
        self.geometry=json.loads((run/"inputs/frontend_geometry.json").read_text())
        self.design=json.loads((run/"inputs/frontend_field_design.json").read_text())
        self.upstream,self.oatof=read_designs(run)
        # The excluded provider cannot supply a drive or even a PA+ input.
        self.assertIsNone(self.upstream)
        self.flight={key:value for key,value in self.flight.items() if key!="rf_steps_per_period"}
        self.flight["pulse"]=dict(mode="timed",time_us=43.,width_us=.5)
        self.dynamic["dynamic_roles"]=[dict(role="accelerator_main",instance_index=3,
            carrier_pa_basename="frontend.carrier_off.pa",pulse_delta_pa_basename="frontend.pulse_delta.pa")]
        from integrations.runtime.build_single_flight_program import _resolve_standalone_dynamic_field_bank
        # Existing three-field consumers must still fail closed on missing RF.
        with self.assertRaisesRegex(ValueError,"RF response"):
            _resolve_standalone_dynamic_field_bank(self.dynamic,{"accelerator_main":3})
        metadata={}
        program=self.build(birth_times_us=[40.,42.125],initial_velocities_mm_per_us=[[1.,2.,3.]]*2,build_metadata=metadata)
        self.assertEqual(metadata["physical_rod_piece_count"],0)
        self.assertEqual(metadata["physical_frontend_topology_id"],"three_zone_frontend_contract_derived_v1")
        self.assertNotIn("single_flight_rf_kernel",program)
        self.assertNotIn("adjustable single_flight_frequency_hz",program)
        self.assertNotIn("single_flight_continuous_rf_grid_step_us=",program)
        for mutation in ("flight_rf","bank_rf","model"):
            kwargs={}
            if mutation=="flight_rf": kwargs["flight"]={**self.flight,"rf_steps_per_period":80}
            elif mutation=="bank_rf":
                bank=copy.deepcopy(self.dynamic)
                bank["dynamic_roles"][0].update(rf_differential_pa_basename="rf.pa",rf_reference_voltage_v=10000.)
                kwargs["standalone_dynamic_field_bank"]=bank
            else:
                geometry=copy.deepcopy(self.geometry);geometry["pa_plus_solution_model"]={}
                kwargs["frontend_geometry"]=geometry
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): self.build(**kwargs)
        carriers={role:dict(path="/inert/"+name) for role,name in dict(flight_tube="flight_tube.pa0",
            reflectron="reflectron.pa",accelerator="frontend.carrier_off.pa",detector="detector.pa0").items()}
        rows=_instance_rows(self.geometry,metadata,carriers)
        instances=[]
        for row in rows:
            place=row["placement"]
            instances.append(dict(filename=Path(row["path"]).name,
                **{a:place[a+"_mm"] for a in "xyz"},az=place["az_deg"],el=0.,rt=0.,scale=1.,
                pa=dict(row["grid"],path=row["path"],symmetry="test",potential_type="electrostatic")))
        path=self.root/"local.lua"
        inspect="\nsegment.inspect=function() return single_flight_instrument_time_us(),single_flight_canonical_particle_id(),single_flight_rf end\n"
        script=self.root/"local_test.lua"
        script.write_text("""segment={}
simion={workbench_program=function() end,early_access=function() end,pas={},wb={}}
simion.wb.instances="""+_lua_value(instances)+"""
for _,instance in ipairs(simion.wb.instances) do
 function instance:wb_to_pa_coords(x,y,z) return x,y,z end
 function instance.pa:fast_adjust() error('published static field was adjusted') end
end
local opens=0
function simion.pas:open(path)
 assert(path:match('frontend%.pulse_delta%.pa$'),'local view opened an RF/other response: '..path)
 opens=opens+1
 local pa={};for key,value in pairs(simion.wb.instances[3].pa) do pa[key]=value end
 function pa:field_vc() return 1,2,3 end
 return pa
end
os.getenv=function() error('local native Program consulted a legacy environment') end
dofile(arg[1]);segment.load();segment.initialize_run();assert(opens==1)
ion_number=2;ion_instance=3;ion_time_of_flight=0;ion_splat=0
ion_px_mm=3.5;ion_py_mm=1.25;ion_pz_mm=-340
ion_vx_mm=.99999;ion_vy_mm=1.99999;ion_vz_mm=2.99999;ion_mass=524;ion_ke=2
segment.initialize()
assert(ion_vx_mm==1 and ion_vy_mm==2 and ion_vz_mm==3)
ion_vx_mm=7;ion_vy_mm=8;ion_vz_mm=9
for _,probe in ipairs({{age=0,delta=0},{age=1,delta=arg[2]=='held' and 0 or 1},{age=2,delta=0}}) do
 ion_time_of_flight=probe.age
 local time,id,rf=segment.inspect()
 assert(time==42.125+probe.age and id==77 and rf==false,'local original clock/ID or no-RF state changed')
 ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
 segment.efield_adjust()
 assert(ion_dvoltsx_gu==10-probe.delta and ion_dvoltsy_gu==20-2*probe.delta and ion_dvoltsz_gu==30-3*probe.delta)
 segment.other_actions();assert(ion_splat==0)
 assert(ion_vx_mm==7 and ion_vy_mm==8 and ion_vz_mm==9)
end
for slot=1,4 do
 ion_instance=slot;ion_time_of_flight=199.9997;ion_time_step=1;segment.tstep_adjust()
 assert(math.abs(ion_time_step-.0003)<1e-10,'local downstream age/step cap lost')
end
ion_time_of_flight=200;segment.other_actions();assert(ion_splat==1)
segment.terminate()
print('LOCAL_OATOF_NO_RF=PASS')
""",encoding="utf-8",newline="\n")
        for mode,pulse in (("timed",dict(mode="timed",time_us=43.,width_us=.5)),("held",dict(mode="held_off"))):
            actual={**self.flight,"pulse":pulse}
            if mode=="held": actual["observation_times_us"]=[42.,42.125,43.125,44.125]
            source = dict(birth_times_us=[40.,42.125],initial_velocities_mm_per_us=[[1.,2.,3.]]*2,flight=actual)
            program=self.build(**source)+inspect
            path.write_text(re.sub(r"\badjustable\s+","",program),encoding="utf-8",newline="\n")
            result=subprocess.run([str(LUA),str(script),str(path),mode],cwd=self.root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn("LOCAL_OATOF_NO_RF=PASS",result.stdout)
            if mode=="held":
                self.assertNotIn("handoff_pulse_on",result.stdout)
                self.assertEqual(result.stdout.count("TRACE: native_shared_time "),3)
                self.assertNotIn("candidate_time_us=42 ",result.stdout)
                self.assertIn("particle_id=77 candidate_time_us=42.125 instrument_time_us=42.125",result.stdout)

    def test_discovery_is_explicit_author_only_and_candidates_are_finite_increasing(self):
        author = {**self.flight, "pulse":dict(mode="discover", width_us=.25, candidate_times_us=[-3.,-2.,2.5,3.])}
        self.assertEqual(validate_native_flight(author,allow_discovery=True),author)
        with self.assertRaises(ValueError): self.build(flight=author)
        with self.assertRaisesRegex(ValueError,"derived observation"):
            validate_native_flight({**self.flight,'observation_times_us':[1.]},allow_discovery=True)
        for times in ([],[-2.,-2.],[-1.,-2.],[True],[float('nan')],[float('inf')],[1e300]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                validate_native_flight({**author,"pulse":{**author['pulse'],'candidate_times_us':times}},allow_discovery=True)
        for times in ([],[False],[2.,1.],[float('nan')]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                self.build(flight={**self.flight,'observation_times_us':times})

    def test_native_flight_requires_each_explicit_value_without_rf_dual_authority(self):
        with self.assertRaises(ValueError): self.build(flight=None)
        for key in self.flight:
            for value in (None, True, float("nan"), float("inf"), "1"):
                with self.subTest(key=key, value=value):
                    flight = dict(self.flight)
                    if value is None: flight.pop(key)
                    else: flight[key] = value
                    with self.assertRaises(ValueError): self.build(flight=flight)
        for key in set(self.flight)-{"pulse"}:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.build(flight={**self.flight, key:0})
        with self.assertRaises(ValueError): self.build(flight={**self.flight, "trajectory_quality":501})
        # Negative absolute clocks and births after the pulse are valid; age
        # remains solver elapsed time, with no additional epoch adjustment.
        flight = {**self.flight, "pulse":dict(mode="timed", time_us=-3., width_us=3.)}
        program = self.build(flight=flight, birth_times_us=[-5., 20.])
        self.assertIn("single_flight_time_origin_us={[1]=-5,[2]=20}", program)
        self.assertIn("adjustable handoff_pulse_time_us=-3", program)

    def test_native_pulse_object_rejects_stale_or_invalid_timing(self):
        for pulse in ({"mode":"held_off", "time_us":0}, {"mode":"timed"},
                      {"mode":"other"}, {"mode":"timed","time_us":True,"width_us":1},
                      {"mode":"timed","time_us":0,"width_us":0},
                      {"mode":"timed","time_us":float("nan"),"width_us":1},
                      {"mode":"timed","time_us":1e300,"width_us":1},
                      {"mode":"timed","time_us":1e308,"width_us":1e308}):
            with self.subTest(pulse=pulse), self.assertRaises(ValueError):
                self.build(flight={**self.flight,"pulse":pulse})
        held = self.build(flight={**self.flight,"pulse":{"mode":"held_off"}})
        self.assertNotIn("handoff_pulse_time_us", held)
        self.assertNotIn("handoff_pulse_width_us", held)
        self.assertNotIn("instrument_time_us=%.12g tof_since_pulse_us=", held)
        self.assertNotIn("TRACE: handoff_pulse_on ", held)
        self.assertNotIn("TRACE: pre_pulse_state ", held)
        self.assertIn("pulse_elapsed_us=false", held)

    def test_native_reference_and_working_voltage_contract_is_explicit(self):
        original_design = copy.deepcopy(self.design)
        original_bank = copy.deepcopy(self.dynamic)
        for mutation in ("old_schema", "missing_reference", "zero_reference", "wrong_reference",
                         "infinite_reference", "missing_pulse", "missing_group", "wrong_rf", "wrong_carrier", "wrong_delta"):
            with self.subTest(mutation=mutation):
                self.design = copy.deepcopy(original_design)
                self.dynamic = copy.deepcopy(original_bank)
                row = self.dynamic["dynamic_roles"][0]
                if mutation == "old_schema": self.design["schema_version"] = 1
                elif mutation == "missing_reference": row.pop("rf_reference_voltage_v")
                elif mutation == "zero_reference": row["rf_reference_voltage_v"] = 0.
                elif mutation == "wrong_reference": row["rf_reference_voltage_v"] *= 2
                elif mutation == "infinite_reference": row["rf_reference_voltage_v"] = float("inf")
                elif mutation == "missing_pulse": row.pop("pulse_delta_pa_basename")
                else:
                    index = {"missing_group": 1, "wrong_rf": 1, "wrong_carrier": 0, "wrong_delta": 2}[mutation]
                    voltages = self.design["working_points"][index]["electrode_voltages_v"]
                    if mutation == "missing_group": voltages.pop("1")
                    else: voltages["1"] += 1.
                with self.assertRaises(ValueError):
                    self.build()
        self.design, self.dynamic = original_design, original_bank

    def test_native_scope_and_real_inputs_reject_incompatible_contracts(self):
        with self.assertRaisesRegex(ValueError, "explicit frontend and downstream"):
            self.build(standalone_dynamic_field_bank=None)
        for label in ("rod", "ground", "placement", "voltage"):
            with self.subTest(label=label):
                upstream,design,geometry=copy.deepcopy(self.upstream),copy.deepcopy(self.design),copy.deepcopy(self.geometry)
                if label=="rod": self.upstream["segmentation"]["segmented_rod_array"]["electrodes"].pop()
                elif label=="ground":
                    instance=self.geometry['composition_plan']['recipe']['connections'][0]['upstream']['instance_id']
                    self.geometry['electrode_bindings'][instance]['10']=9
                elif label=="placement": self.geometry["downstream_pa_instances"][0]["x_mm"]+=1
                else: self.design["accelerator_voltage_states"]["operating_voltages_v"]["12"]+=1
                with self.assertRaises(ValueError): self.build()
                self.upstream,self.design,self.geometry=upstream,design,geometry

    def test_native_static_assets_require_receipt_and_complete_surface_families(self):
        for mutation in ("receipt", "surface", "basis", "origin", "reflectron", "slot", "ordinary_role"):
            with self.subTest(mutation=mutation):
                contract=copy.deepcopy(self.static)
                if mutation=="receipt": contract.pop("receipt")
                elif mutation=="surface": contract["static_roles"][0]["family_members"].pop()
                elif mutation=="basis": contract["static_roles"][0]["family_members"][2]="foreign.pa1"
                elif mutation=="origin": contract["static_roles"][0]["representation"]="published_cache_family_copy"
                elif mutation=="reflectron": contract["static_roles"][1]["carrier_pa_basename"]="reflectron.pa0"
                elif mutation=="slot": contract["static_roles"][2]["instance_index"]=2
                else: contract["role"]="unrelated_static_assets"
                with self.assertRaises(ValueError): self.build(downstream_static_fields=contract)
        metadata={}
        self.build(build_metadata=metadata)
        self.assertEqual(metadata["downstream_static_asset_receipt"],self.static["receipt"])
        self.assertEqual(metadata["downstream_static_runtime_representation"],DOWNSTREAM_STATIC_ASSET_REPRESENTATION)

    @unittest.skipUnless(LUA.is_file(),"plain Lua interpreter unavailable")
    def test_plain_lua_callbacks_preserve_provider_pose_ids_birth_and_rf(self):
        self.check_plain_lua_callbacks(False)

    @unittest.skipUnless(LUA.is_file(),"plain Lua interpreter unavailable")
    def test_fine_domain_callbacks_select_one_field_and_preserve_clock(self):
        self.check_plain_lua_callbacks(True)

    def check_plain_lua_callbacks(self, entrance_refinement):
        if entrance_refinement:
            folder = self.root / "fine"
            folder.mkdir()
            request, run, _ = fixture(folder, source=self.upstream, entrance_refinement=True)
            prepare(request,run)
            self.design = json.loads((run/"inputs/frontend_field_design.json").read_text())
            self.geometry = json.loads((run/"inputs/frontend_geometry.json").read_text())
            self.dynamic["dynamic_roles"].append(dict(role="entrance_refinement",instance_index=5,
                carrier_pa_basename="frontend_entrance_refinement.carrier_off.pa",
                rf_differential_pa_basenames=["frontend_entrance_refinement.rf_reference.pa"],
                pulse_delta_pa_basename="frontend_entrance_refinement.pulse_delta.pa",
                rf_reference_voltage_v=self.design["rf_reference_voltage_v"]))

        self.upstream["drive"]["phase_rad"] = .37
        self.assertEqual(self.upstream["drive"]["rf_amplitude_V_zero_to_peak_per_group"], 139.81792)
        self.oatof["coordinate_convention"]["reflectron_axis"]=[7.,-9.]
        self.oatof["coordinate_convention"]["detector_x"]=81.
        self.oatof["simion_detector_marker"]["active_plane_z_mm"]=12.5
        provider=derive_simion_geometry(geometry=self.oatof["geometry_mm"],coordinate=self.oatof["coordinate_convention"],
            build=self.oatof["simion_geometry_build"],marker=self.oatof["simion_detector_marker"],source=self.oatof["particle_source"])
        for row in self.geometry["downstream_pa_instances"]:
            row.update(next(p for p in provider["simion_instances"] if p["role"]==row["role"]))
        metadata = {}
        program = self.build(build_metadata=metadata)
        self.assertEqual(metadata["provider_placements"]["reflectron"]["x_mm"],7.)
        self.assertEqual(metadata["provider_placements"]["flight_tube"]["y_mm"],-9.)
        self.assertEqual(metadata["provider_placements"]["detector"]["z_mm"],12.35)
        inspect = "\nsegment.inspect=function() return single_flight_instrument_time_us(),single_flight_canonical_particle_id(),single_flight_rf_drives[1].differential_at(single_flight_instrument_time_us()) end\n"
        inspect += "segment.inspect_lifecycle=function() return single_flight_particle_state,single_flight_analyzer_initialized,single_flight_previous,single_flight_reported,single_flight_standalone_dynamic_by_instance end\n"
        program += inspect
        path = self.root/"program.lua"
        path.write_text(re.sub(r"\badjustable\s+","",program),encoding="utf-8")
        g = self.geometry
        rows = {"flight_tube":1,"reflectron":2,"accelerator":3,"detector":4}
        filenames = {"flight_tube":"flight_tube.pa0","reflectron":"reflectron.pa","accelerator":"front.pa","detector":"detector.pa0"}
        if entrance_refinement:
            rows["entrance_refinement"] = 5
            filenames["entrance_refinement"] = "frontend_entrance_refinement.carrier_off.pa"
        instances = []
        downstream = {"flight_tube" if r["role"]=="flight_tube_shield" else r["role"]:r for r in g["downstream_pa_instances"]}
        for role,index in rows.items():
            if role in {"accelerator","entrance_refinement"}:
                domain = g["numerical_domains"]["parent" if role=="accelerator" else role]
                dims=domain["dimensions"];pitch=[domain["cell_mm_xyz"][a] for a in "xyz"]
            else:
                r=downstream[role];dims=r
                b=r["grid_numerics"]
                pitch=([b["cell_xy_mm"],b["cell_xy_mm"],b["cell_z_mm"]] if role=="detector"
                       else [b["cell_axial_mm"],b["cell_radial_mm"],b["cell_radial_mm"]])
            place=(dict(**{f"{a}_mm":domain["instance_origin_mm"][a] for a in "xyz"},az_deg=0.)
                   if role=="entrance_refinement" else metadata["provider_placements"][role])
            instances.append(dict(filename=filenames[role],x=place["x_mm"],y=place["y_mm"],z=place["z_mm"],
                az=place["az_deg"],el=0.,rt=0.,scale=1.,pa=dict(nx=dims["nx"],ny=dims["ny"],nz=dims["nz"],
                    dx_mm=pitch[0],dy_mm=pitch[1],dz_mm=pitch[2],symmetry="test",potential_type="electrostatic",
                    path="/test/"+filenames[role])))
        script = self.root/"test.lua"
        script.write_text("""segment={}
simion={workbench_program=function() end,early_access=function() end,pas={},wb={}}
simion.wb.instances="""+_lua_value(instances)+"""
for _,instance in ipairs(simion.wb.instances) do
 function instance:wb_to_pa_coords(x,y,z) return x,y,z end
 function instance:inside_wc() return self.inside_override==true end
 function instance.pa:fast_adjust() error("static asset was Fast Adjusted") end
end
local query_counts={}
local opened={}
function simion.pas:open(path)
 assert(not path:find('/unexpected/'),'native Program replaced its frozen field path')
 local carrier=path:find('frontend_entrance_refinement',1,true) and 5 or 3
 local p={};for k,v in pairs(simion.wb.instances[carrier].pa) do p[k]=v end
 opened[#opened+1]=p
 function p:field_vc()
  query_counts[carrier]=(query_counts[carrier] or 0)+1
  local scale=(path:match('/rf.pa$') or path:match('%.rf_reference.pa$')) and tonumber(arg[3]) or 1
  return scale,2*scale,3*scale
 end
 return p
end
local legacy_env={
 OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET='999',
 OATOF_ACCELERATOR_PA_OVERRIDE='/unexpected/external.pa',
 OATOF_PRE_PULSE_RAW_TRACE_PATH='/unexpected/external_trace.txt',
 OATOF_SIMION_PROGRAM_LOAD_REPORT='/unexpected/load_report.txt'}
local getenv=os.getenv
os.getenv=function(key) return legacy_env[key] or getenv(key) end
local original_open=io.open
io.open=function(path,...)
 assert(not tostring(path):find('/unexpected/'),'native Program wrote a legacy environment output')
 return original_open(path,...)
end
assert(dofile(arg[1])==nil)
segment.load()
assert(sim_trajectory_quality==17)
if arg[2]=='held' or arg[2]=='planes' or arg[2]=='precision' or arg[2]=='snapshots' then
 assert(handoff_pulse_time_us==nil and handoff_pulse_width_us==nil)
elseif arg[2]=='precision_timed' then assert(handoff_pulse_time_us==42.48966792789)
else assert(handoff_pulse_time_us==10 and handoff_pulse_width_us==3) end
if arg[2]=='wrong_fine' then
 assert(#simion.wb.instances==5)
 simion.wb.instances[5].x=simion.wb.instances[5].x+1
 local ok,err=pcall(segment.initialize_run)
 assert(not ok and tostring(err):find('native refinement placement differs'),'fine placement was silently repaired: '..tostring(err))
 print('WRONG_FINE_PLACEMENT_REJECTED=PASS')
 return
end
if arg[2]=='wrong' then
 simion.wb.instances[2].x=simion.wb.instances[2].x+1
 local ok,err=pcall(segment.initialize_run)
 assert(not ok and tostring(err):find('native provider placement differs'),'wrong placement was silently repaired: '..tostring(err))
 print('WRONG_PLACEMENT_REJECTED=PASS')
 return
end
segment.initialize_run()
assert(segment.fast_adjust==nil)
if arg[2]=='velocity' then
 local expected={{1.959568200662977,-0.12345678901234567,1.2345678901234567},{-4.25,5.125,-6.0625}}
 for index,vector in ipairs(expected) do
  ion_number=index;ion_instance=3;ion_time_of_flight=0;ion_splat=0
  ion_px_mm=0;ion_py_mm=0;ion_pz_mm=-340;ion_mass=100;ion_ke=2
  ion_vx_mm=vector[1]*.99999999998;ion_vy_mm=vector[2]*.99999999998;ion_vz_mm=vector[3]*.99999999998
  segment.initialize()
  assert(ion_vx_mm==vector[1] and ion_vy_mm==vector[2] and ion_vz_mm==vector[3],'explicit source velocity lost precision')
  ion_vx_mm=7;ion_vy_mm=8;ion_vz_mm=9;ion_time_step=.001
  segment.tstep_adjust();assert(segment.fast_adjust==nil)
  ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
  segment.efield_adjust();segment.other_actions();segment.initialize()
  assert(ion_vx_mm==7 and ion_vy_mm==8 and ion_vz_mm==9,'later callback reset integrated velocity')
 end
 print('NATIVE_SOURCE_VELOCITY=PASS')
 return
end
if arg[2]=='births' then
 local births={9,10,11,14}
 local events={}
 local original_print=print
 print=function(line)
  local id,t,x,vx=tostring(line):match('TRACE: handoff_pulse_on ion=(%d+) instrument_time_us=([^ ]+) x_mm=([^ ]+).* vx_mm_per_us=([^ ]+)')
  if id then
   id=tonumber(id);t=tonumber(t)
   assert(t>=births[id],'pulse event predates the actual birth')
   assert(events[id]==nil,'duplicate pulse observation')
   events[id]={t=t,x=tonumber(x),vx=tonumber(vx)}
  end
  original_print(line)
 end
 for index,birth in ipairs(births) do
  ion_number=index;ion_instance=3;ion_time_of_flight=0;ion_splat=0
  ion_px_mm=100*index;ion_py_mm=0;ion_pz_mm=-340
  ion_vx_mm=2;ion_vy_mm=0;ion_vz_mm=1;ion_ke=2;ion_mass=100
  segment.initialize()
  local function check_field()
   local t,_,rf=segment.inspect()
   assert(t==birth+ion_time_of_flight,'birth clock was reset for pulse observation')
   local delta=(t>=10 and t<13) and 1 or 0
   ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
   segment.efield_adjust()
   assert(math.abs(ion_dvoltsx_gu-(10-rf-delta))<1e-8,'late birth changed the actual pulse/RF drive')
  end
  check_field()
  ion_time_of_flight=index==1 and 1.5 or .5
  ion_px_mm=100*index+3;ion_vx_mm=8
  check_field();segment.other_actions()
  ion_time_of_flight=ion_time_of_flight+.5;ion_px_mm=ion_px_mm+1
  check_field();segment.other_actions()
 end
 assert(events[1] and events[1].t==10 and math.abs(events[1].x-102)<1e-10,'pre-pulse birth lost its actual bracket')
 assert(events[2] and events[2].t==10 and events[2].x==200 and events[2].vx==2,'equal-time birth used a later step state')
 assert(events[3]==nil and events[4]==nil,'late birth invented a pre-birth pulse observation')
 print('CAUSAL_PULSE_BIRTH_OBSERVATIONS=PASS')
 return
end
if arg[2]=='snapshots' then
 local snapshots={}
 local original_print=print
 print=function(line)
  if tostring(line):find('TRACE: native_shared_time ',1,true) then snapshots[#snapshots+1]=line end
  original_print(line)
 end
 ion_number=1;ion_instance=3;ion_time_of_flight=0;ion_splat=0;ion_mass=100;ion_ke=2
 ion_px_mm=101;ion_py_mm=-7;ion_pz_mm=-340;ion_vx_mm=2;ion_vy_mm=3;ion_vz_mm=4
 segment.initialize()
 assert(#snapshots==1 and snapshots[1]:find('candidate_time_us=-2 instrument_time_us=-2',1,true))
 ion_number=2;ion_instance=3;ion_time_of_flight=0
 ion_px_mm=111;ion_py_mm=-8;ion_pz_mm=-339;ion_vx_mm=5;ion_vy_mm=6;ion_vz_mm=7
 segment.initialize()
 assert(#snapshots==2 and snapshots[2]:find('candidate_time_us=2.5 instrument_time_us=2.5',1,true))
 ion_time_step=1;segment.tstep_adjust()
 assert(math.abs(ion_time_step-.001)<1e-12,'candidate did not cap the native step')
 ion_instance=2;ion_time_of_flight=.001-1e-15
 ion_px_mm=112;ion_py_mm=-9;ion_pz_mm=-338;ion_vx_mm=8;ion_vy_mm=9;ion_vz_mm=10
 segment.other_actions()
 assert(#snapshots==3,'early accepted native time within 32 ULP was omitted')
 segment.other_actions();assert(#snapshots==3,'same callback duplicated a candidate')
 ion_instance=1;ion_time_of_flight=.5
 ion_px_mm=113;ion_py_mm=-10;ion_pz_mm=-337;ion_vx_mm=11;ion_vy_mm=12;ion_vz_mm=13
 segment.other_actions();assert(#snapshots==4,'downstream actual snapshot was omitted')
 assert(ion_splat==0,'passive snapshot changed terminal state')
 ion_time_of_flight=2;segment.other_actions()
 assert(ion_splat==0 and #snapshots==4,'a skipped candidate aborted flight or invented a state')
 ion_time_of_flight=200;segment.other_actions();assert(ion_splat==1)
 segment.terminate()
 assert(#snapshots==4,'terminal callback fabricated a missing candidate')
 print('NATIVE_ACTUAL_SNAPSHOTS=PASS')
 return
end
ion_number=2;ion_instance=3;ion_time_of_flight=.125
ion_px_mm=0;ion_py_mm=0;ion_pz_mm=-340
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=1;ion_ke=2;ion_mass=100;ion_splat=0
segment.initialize()
if #simion.wb.instances==5 then
 local bounds="""+_lua_value(self.geometry["numerical_domains"].get("entrance_refinement",{}).get("active_bounds_mm",{}))+"""
 local x,y,z=ion_px_mm,ion_py_mm,ion_pz_mm
 ion_px_mm=(bounds.x_min+bounds.x_max)/2
 ion_py_mm=(bounds.y_min+bounds.y_max)/2
 ion_pz_mm=(bounds.z_min+bounds.z_max)/2
 ion_instance=5;segment.instance_adjust();assert(ion_instance==5,'active refinement was skipped')
 ion_px_mm=bounds.x_min;ion_instance=5;segment.instance_adjust()
 assert(ion_instance==0,'guard boundary did not fall back to parent selection')
 ion_px_mm=x;ion_py_mm=y;ion_pz_mm=z;ion_instance=5
 local _,id,rf=segment.inspect();assert(id==77)
 local parent_queries=query_counts[3] or 0
 ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
 segment.efield_adjust()
 assert(math.abs(ion_dvoltsx_gu-(10-rf))<1e-8,'fine field did not use the same actual drive')
 assert((query_counts[3] or 0)==parent_queries and (query_counts[5] or 0)>0,'parent and fine fields were added together')
 -- The same native observer arms the existing detector role; the numerical
 -- refinement must yield to that role even though slot 5 has higher priority.
 ion_number=1;ion_instance=3;ion_time_of_flight=0
 segment.initialize()
 ion_time_of_flight=.5;ion_pz_mm=700;segment.other_actions()
 ion_px_mm=(bounds.x_min+bounds.x_max)/2
 ion_py_mm=(bounds.y_min+bounds.y_max)/2
 ion_pz_mm=(bounds.z_min+bounds.z_max)/2
 simion.wb.instances[4].inside_override=true
 ion_instance=5;segment.instance_adjust()
 assert(ion_instance==0,'fine domain shadowed an armed detector')
 simion.wb.instances[4].inside_override=false
 ion_number=2;ion_px_mm=x;ion_py_mm=y;ion_pz_mm=z;ion_time_of_flight=.125;ion_instance=3
end
if arg[2]=='precision' or arg[2]=='precision_timed' then
 local terminal=42.48966792789
 assert(tonumber(string.format('%.12g',terminal))>terminal,'regression vector no longer exposes rounding')
 local planes="""+_lua_value([
            dict(event=event,z=self.geometry['accelerator_projection'][key]) for event,key in (
                ('accelerator_grid1_forward','grid1_z_mm'),
                ('accelerator_intermediate2_forward','intermediate2_z_mm'),
                ('local_accelerator_exit','grid2_z_mm'))]+[
            dict(event='accelerator_focus_forward',z=self.geometry['accelerator_projection']['grid2_z_mm']
                 +self.oatof['geometry_derivation']['accelerator']['focus_drift_after_grid2_mm'])])+"""
 local captured={};local original_print=print
 print=function(line) captured[#captured+1]=tostring(line);original_print(line) end
 for _,plane in ipairs(planes) do
  captured={}
  ion_number=2;ion_instance=3;ion_time_of_flight=0;ion_pz_mm=plane.z-1;ion_splat=0
  segment.initialize()
  ion_time_of_flight=terminal-2.5;ion_pz_mm=plane.z;ion_splat=1
  segment.other_actions();segment.terminate()
  local seen={}
  for _,line in ipairs(captured) do
   local event=line:match('TRACE: ([^ ]+) ')
   if event==plane.event or event=='handoff_terminal_raw' or event=='non_detector_splat'
      or event=='pre_pulse_state' or event=='handoff_pulse_on' then
    local value=line:match('instrument_time_us=([^ ]+)') or line:match(' t=([^ ]+)')
    assert(tonumber(value)==terminal,'serialized observation/terminal changed time: '..line)
    seen[event]=true
   end
  end
  assert(seen[plane.event] and seen.handoff_terminal_raw and seen.non_detector_splat,'missing real plane/terminal')
  if arg[2]=='precision_timed' then assert(seen.pre_pulse_state and seen.handoff_pulse_on) end
 end
 print('NATIVE_TERMINAL_TIME_ROUNDTRIP=PASS')
 return
end
if arg[2]=='planes' then
 local outer,inner,axis="""+",".join(str(v) for v in (self.geometry["composition_plan"]["connection_checks"][0]["upstream_center_mm"][0],self.geometry["accelerator_projection"]["accelerator_port_aperture_discretization"]["flange_max_mm"],self.geometry["accelerator_projection"]["axis_x_mm"]))+"""
 local start_x,end_x=outer-1,axis+1
 local captured={}
 local base_print=print
 print=function(line) captured[#captured+1]=tostring(line);base_print(line) end
 ion_instance=3;ion_time_of_flight=0;ion_px_mm=start_x;ion_py_mm=2;ion_pz_mm=-340
 ion_vx_mm=4;ion_vy_mm=6;ion_vz_mm=8;ion_splat=0
 segment.initialize()
 ion_time_of_flight=200;ion_splat=1;ion_px_mm=end_x;ion_py_mm=12;ion_pz_mm=-320
 ion_vx_mm=14;ion_vy_mm=16;ion_vz_mm=18
 segment.other_actions()
 assert(ion_splat==1,'X observation replaced a native terminal at the age deadline')
 -- Repeat and reverse accepted steps cannot duplicate first-forward events.
 segment.other_actions()
 ion_time_of_flight=201;ion_px_mm=start_x;ion_vx_mm=-2;segment.other_actions()
 ion_time_of_flight=202;ion_px_mm=end_x;ion_vx_mm=3;segment.other_actions()
 -- An independently born particle already downstream gets no invented arrival.
 ion_number=1;ion_time_of_flight=0;ion_px_mm=end_x;ion_vx_mm=3;ion_splat=0
 segment.initialize()
 ion_time_of_flight=1;ion_px_mm=end_x+1;segment.other_actions()
 for _,event in ipairs({'single_flight_handoff','accelerator_sidewall_inner_forward','accelerator_axis_forward'}) do
  local count=0
  for _,line in ipairs(captured) do if line:find('TRACE: '..event..' ',1,true) then
   count=count+1;assert(line:find('ion=2 particle_id=77 ',1,true),'invented downstream-birth crossing')
  end end
  assert(count==1,'duplicate or missing X plane '..event..': '..count)
 end
 print('NATIVE_X_PLANES=PASS')
 return
end
if arg[2]=='held' then
 for _,age in ipairs({.125,7.5,8,10.5,11.5,100}) do
  ion_time_of_flight=age
  local time,id,rf=segment.inspect()
  assert(time==2.5+age and id==77)
  ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
  segment.efield_adjust()
  assert(math.abs(ion_dvoltsx_gu-(10-rf))<1e-8,'held OFF applied pulse delta or changed RF')
  if #simion.wb.instances==5 then
   ion_instance=5;ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
   segment.efield_adjust()
   assert(math.abs(ion_dvoltsx_gu-(10-rf))<1e-8,'fine held OFF applied a pulse delta')
   ion_instance=3
  end
  ion_time_step=1;segment.tstep_adjust()
  assert(ion_time_step>0 and ion_time_step<=.001)
  segment.other_actions();assert(ion_splat==0)
 end
 for _,slot in ipairs({1,2,3,4}) do
  ion_instance=slot;ion_time_of_flight=199.9997;ion_time_step=1
  segment.tstep_adjust();assert(math.abs(ion_time_step-.0003)<1e-10)
 end
 ion_time_of_flight=200;segment.other_actions();assert(ion_splat==1)
 segment.terminate()
 print('GENUINE_HELD_OFF=PASS')
 return
end
if arg[2]=='detector' then
 ion_time_of_flight=1;ion_pz_mm=700
 segment.other_actions()
 ion_instance=4;ion_time_of_flight=200;ion_px_mm=81;ion_py_mm=0;ion_pz_mm=12.5;ion_vz_mm=-1;ion_splat=1
 segment.other_actions()
 segment.terminate()
 print('EXISTING_DETECTOR_TERMINAL=PASS')
 return
end
local t,id,rf=segment.inspect()
assert(t==2.625 and id==77,'original ID/birth plus elapsed changed')
assert(math.abs(rf-"""+str(self.upstream["drive"]["rf_amplitude_V_zero_to_peak_per_group"])+"""*math.cos(2*math.pi*"""+str(self.upstream["drive"]["frequency_Hz"])+"""*t*1e-6+"""+str(self.upstream["drive"]["phase_rad"])+"""))<1e-8,'RF canonical clock changed')
ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
segment.efield_adjust()
assert(math.abs(ion_dvoltsx_gu-(10-rf))<1e-8,'OFF RF response was not applied')
ion_time_of_flight=8
local on_t,on_id,on_rf=segment.inspect()
assert(on_t==10.5 and on_id==77)
ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
segment.efield_adjust()
assert(math.abs(ion_dvoltsx_gu-(10-on_rf-1))<1e-8,'ON pulse delta was not applied')
if #simion.wb.instances==5 then
 ion_instance=5;ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
 segment.efield_adjust()
 assert(math.abs(ion_dvoltsx_gu-(10-on_rf-1))<1e-8,'fine pulse/RF response differs')
 ion_instance=3
end
assert(math.abs(ion_dvoltsy_gu-(20-2*on_rf-2))<1e-8,'field vector axis changed')
ion_time_of_flight=11.5
local after_t,after_id,after_rf=segment.inspect()
assert(after_t==14 and after_id==77)
ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
segment.efield_adjust()
assert(math.abs(ion_dvoltsx_gu-(10-after_rf))<1e-8,'pulse delta remained active after the explicit end')
for _,probe in ipairs({{elapsed=7.49975,expected=.00025},{elapsed=8,expected=.001},
                        {elapsed=10.4998,expected=.0002},{elapsed=199.9997,expected=.0003}}) do
 ion_time_of_flight=probe.elapsed;ion_time_step=1
 segment.tstep_adjust()
 assert(math.abs(ion_time_step-probe.expected)<1e-10,'explicit step/edge/age cap differs: '..ion_time_step)
end
ion_time_of_flight=100
segment.other_actions()
assert(ion_splat==0,'legacy post-pulse window pre-empted the explicit maximum age')
for index=1,#simion.wb.instances do
 ion_instance=index;ion_time_of_flight=199.9997;ion_time_step=.5
 segment.tstep_adjust()
 assert(math.abs(ion_time_step-.0003)<1e-10,'downstream instance lost its remaining-age cap')
 local switched_time,switched_id=segment.inspect()
 assert(math.abs(switched_time-202.4997)<1e-10 and switched_id==77,'instance switch reset the original birth clock')
end
ion_instance=2
ion_time_of_flight=200;ion_time_step=.5
segment.tstep_adjust()
assert(ion_time_step>0,'expired age produced a nonpositive native step')
segment.other_actions()
assert(ion_splat==1,'maximum particle age did not terminate the flight')
segment.terminate()
segment.terminate()
if arg[2]=='repeat' then
 local before={segment.inspect_lifecycle()}
 assert(next(before[1]) and next(before[2]) and next(before[3]) and next(before[4]),'first run did not populate lifecycle state')
 local count=#opened
 segment.initialize_run()
 local after={segment.inspect_lifecycle()}
 assert(#opened==count,'repeat initialize reopened response PAs')
 for i=1,4 do assert(after[i]~=before[i] and next(after[i])==nil,'per-run particle/diagnostic state was retained') end
 for index,spec in pairs(before[5]) do
  assert(after[5][index]==spec,'response spec changed between runs')
  for _,pa in ipairs(spec.rf_differential_pas) do
   local found=false;for _,original in ipairs(opened) do if pa==original then found=true end end
   assert(found,'RF PA reference was replaced')
  end
  local found=false;for _,original in ipairs(opened) do if spec.pulse_delta_pa==original then found=true end end
  assert(found,'pulse PA reference was replaced')
 end
 ion_number=2;ion_instance=3;ion_time_of_flight=0;ion_splat=0
 ion_px_mm=0;ion_py_mm=0;ion_pz_mm=-340;ion_vx_mm=7;ion_vy_mm=8;ion_vz_mm=9
 segment.initialize()
 local t,id,rf=segment.inspect()
 assert(t==2.5 and id==77,'repeat run changed original ID or instrument birth clock')
 assert(ion_vx_mm==0 and ion_vy_mm==0 and ion_vz_mm==1,'repeat run did not restore the original source velocity')
 ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
 segment.efield_adjust()
 assert(math.abs(ion_dvoltsx_gu-(10-rf))<1e-8,'repeat run changed RF drive')
 ion_time_of_flight=200;segment.other_actions();segment.terminate();segment.terminate()
 assert(ion_splat==1,'repeat run retained a terminal gate or lost its age limit')
 opened[1].nx=opened[1].nx+1
 local okay,reason=pcall(segment.initialize_run)
 assert(not okay and tostring(reason):find('dimensions differ'),'cached response skipped RAM shape validation')
 assert(#opened==count,'invalid cached response triggered a new open')
 print('NATIVE_REPEAT_INITIALIZE=PASS')
end
print('NATIVE_FULL_PROGRAM=PASS')
""",encoding="utf-8")
        reference = self.design["rf_reference_voltage_v"]
        self.assertEqual(reference, 10000.)
        result=subprocess.run([str(LUA),str(script),str(path),"good",str(reference)],cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("NATIVE_FULL_PROGRAM=PASS",result.stdout)
        self.assertEqual(result.stdout.count("TRACE: timeout_splat "), 1)
        self.assertIn("instrument_time_us=202.5", result.stdout)
        self.assertIn("particle_id=77 particle_age_us=200", result.stdout)
        self.assertNotIn("TRACE: detector_crossing ", result.stdout)
        repeated=subprocess.run([str(LUA),str(script),str(path),"repeat",str(reference)],cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(repeated.returncode,0,repeated.stdout+repeated.stderr)
        self.assertIn("NATIVE_REPEAT_INITIALIZE=PASS",repeated.stdout)
        self.assertEqual(repeated.stdout.count("TRACE: timeout_splat "),2)
        refused=subprocess.run([str(LUA),str(script),str(path),"wrong",str(reference)],cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(refused.returncode,0,refused.stdout+refused.stderr)
        self.assertIn("WRONG_PLACEMENT_REJECTED=PASS",refused.stdout)
        if entrance_refinement:
            wrong_fine=subprocess.run([str(LUA),str(script),str(path),"wrong_fine",str(reference)],
                                      cwd=self.root,capture_output=True,text=True,timeout=30)
            self.assertEqual(wrong_fine.returncode,0,wrong_fine.stdout+wrong_fine.stderr)
            self.assertIn("WRONG_FINE_PLACEMENT_REJECTED=PASS",wrong_fine.stdout)

        detected = subprocess.run([str(LUA),str(script),str(path),"detector",str(reference)],
                                  cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(detected.returncode,0,detected.stdout+detected.stderr)
        self.assertIn("TRACE: detector_crossing ", detected.stdout)
        self.assertIn("TRACE: diagnostic_return_plane ", detected.stdout)
        self.assertNotIn("TRACE: timeout_splat ", detected.stdout)
        velocity_path=self.root/'source_velocity.lua'
        velocity_program=self.build(initial_velocities_mm_per_us=[
            [1.959568200662977,-.12345678901234567,1.2345678901234567],[-4.25,5.125,-6.0625]])+inspect
        velocity_path.write_text(re.sub(r"\badjustable\s+", "", velocity_program),encoding='utf-8',newline='\n')
        velocity=subprocess.run([str(LUA),str(script),str(velocity_path),"velocity",str(reference)],
                                cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(velocity.returncode,0,velocity.stdout+velocity.stderr)
        self.assertIn("NATIVE_SOURCE_VELOCITY=PASS",velocity.stdout)
        cohort_path = self.root / "birth_cohort.lua"
        cohort_program = self.build(birth_times_us=[9.,10.,11.,14.],particle_ids=[11,22,33,44],initial_velocities_mm_per_us=[[2.,0.,1.]]*4)+inspect
        cohort_path.write_text(re.sub(r"\badjustable\s+", "", cohort_program), encoding="utf-8", newline="\n")
        cohort = subprocess.run([str(LUA),str(script),str(cohort_path),"births",str(reference)],
                                cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(cohort.returncode,0,cohort.stdout+cohort.stderr)
        self.assertIn("CAUSAL_PULSE_BIRTH_OBSERVATIONS=PASS",cohort.stdout)
        self.assertEqual(cohort.stdout.count("TRACE: handoff_pulse_on "),2)
        for row, time in re.findall(r"TRACE: \S+ ion=(\d+).*?instrument_time_us=([-+0-9.eE]+)", cohort.stdout):
            self.assertGreaterEqual(float(time), [9.,10.,11.,14.][int(row)-1])
        held_path = self.root / "held.lua"
        held_program = self.build(flight={**self.flight,"pulse":{"mode":"held_off"}})+inspect
        held_path.write_text(re.sub(r"\badjustable\s+", "", held_program),encoding="utf-8",newline="\n")
        held = subprocess.run([str(LUA),str(script),str(held_path),"held",str(reference)],
                              cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(held.returncode,0,held.stdout+held.stderr)
        self.assertIn("GENUINE_HELD_OFF=PASS",held.stdout)
        self.assertNotIn("handoff_pulse_on",held.stdout)
        self.assertNotIn("pre_pulse_state",held.stdout)
        self.assertNotIn("tof_since_pulse_us",held.stdout)
        self.assertEqual(held.stdout.count("TRACE: timeout_splat "),1)
        snapshot_path = self.root / "snapshots.lua"
        snapshot_program = self.build(birth_times_us=[-2.,2.5],initial_velocities_mm_per_us=[[2.,3.,4.],[5.,6.,7.]],flight={**self.flight,
            "pulse":{"mode":"held_off"},"observation_times_us":[-3.,-2.,2.5,2.501,3.,4.]}) + inspect
        snapshot_path.write_text(re.sub(r"\badjustable\s+", "", snapshot_program),encoding="utf-8",newline="\n")
        snapshots = subprocess.run([str(LUA),str(script),str(snapshot_path),"snapshots",str(reference)],
                                   cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(snapshots.returncode,0,snapshots.stdout+snapshots.stderr)
        self.assertIn("NATIVE_ACTUAL_SNAPSHOTS=PASS",snapshots.stdout)
        lines=[line for line in snapshots.stdout.splitlines() if line.startswith('TRACE: native_shared_time ')]
        self.assertEqual(len(lines),4)
        values=[dict(re.findall(r"(\w+)=([-+0-9.eE]+)",line)) for line in lines]
        self.assertEqual([int(v['particle_id']) for v in values],[11,77,77,77])
        self.assertEqual([float(v['x_mm']) for v in values],[101,111,112,113])
        self.assertNotEqual(values[2]['instrument_time_us'],values[2]['candidate_time_us'])
        self.assertEqual([int(v['instance']) for v in values],[3,3,2,1])
        self.assertAlmostEqual(float(values[2]['kinetic_energy_eV']),.0051821348263402529*100*(8**2+9**2+10**2))
        self.assertNotIn('handoff_pulse_on',snapshots.stdout)
        self.assertIn('DIAG: native_shared_time_missing particle_id=77 candidate_time_us=4 actual_instrument_time_us=4.5',snapshots.stdout)
        self.assertEqual(snapshots.stdout.count('TRACE: timeout_splat '),1)
        planes = subprocess.run([str(LUA),str(script),str(held_path),"planes",str(reference)],
                                cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(planes.returncode,0,planes.stdout+planes.stderr)
        self.assertIn("NATIVE_X_PLANES=PASS",planes.stdout)
        self.assertNotIn("TRACE: timeout_splat ",planes.stdout)
        precise_timed_path = self.root / 'precise_timed.lua'
        precise_timed = self.build(flight={**self.flight, 'pulse':dict(mode='timed',time_us=42.48966792789,width_us=3.)})+inspect
        precise_timed_path.write_text(re.sub(r"\badjustable\s+", "", precise_timed),encoding='utf-8',newline='\n')
        for mode, program_path in [('precision',held_path),('precision_timed',precise_timed_path)]:
            precise = subprocess.run([str(LUA),str(script),str(program_path),mode,str(reference)],
                                     cwd=self.root,capture_output=True,text=True,timeout=30)
            self.assertEqual(precise.returncode,0,precise.stdout+precise.stderr)
            self.assertIn('NATIVE_TERMINAL_TIME_ROUNDTRIP=PASS',precise.stdout)
        g = self.geometry["accelerator_projection"]
        expected_planes = dict(single_flight_handoff=self.geometry["composition_plan"]["connection_checks"][0]["upstream_center_mm"][0],
            accelerator_sidewall_inner_forward=g["accelerator_port_aperture_discretization"]["flange_max_mm"],
            accelerator_axis_forward=g["axis_x_mm"])
        start, end = expected_planes["single_flight_handoff"]-1,expected_planes["accelerator_axis_forward"]+1
        times = []
        for line in planes.stdout.splitlines():
            event = line.split()[1] if line.startswith("TRACE: ") else None
            if event not in expected_planes: continue
            values = dict(re.findall(r"(\w+)=([-+0-9.eE]+)",line))
            f = (expected_planes[event]-start)/(end-start)
            self.assertEqual(float(values["x_mm"]),expected_planes[event])
            for key, value in dict(instrument_time_us=2.5+200*f,y_mm=2+10*f,z_mm=-340+20*f,
                    vx_mm_per_us=4+10*f,vy_mm_per_us=6+10*f,vz_mm_per_us=8+10*f,
                    step_start_instrument_time_us=2.5,step_end_instrument_time_us=202.5,
                    step_start_x_mm=start,step_end_x_mm=end).items():
                self.assertAlmostEqual(float(values[key]),value,places=11)
            expected_energy = .0051821348263402529*100*sum((v+10*f)**2 for v in (4,6,8))
            self.assertAlmostEqual(float(values["kinetic_energy_eV"]),expected_energy,places=9)
            times.append(float(values["instrument_time_us"]))
        self.assertEqual(len(times),3)
        self.assertEqual(times,sorted(times))
        # The same actual callback must give the same RF, DC base and pulse
        # result for a 1-V response and a 10000-V reference response.
        self.design["rf_reference_voltage_v"] = 1.
        point = next(p for p in self.design["working_points"] if p["kind"] == "rf_reference")
        point["electrode_voltages_v"] = {k:v/reference for k,v in point["electrode_voltages_v"].items()}
        for row in self.dynamic["dynamic_roles"]:
            row["rf_reference_voltage_v"] = 1.
        unit_path = self.root / "unit.lua"
        unit_path.write_text(re.sub(r"\badjustable\s+", "", self.build()+inspect), encoding="utf-8", newline="\n")
        unit = subprocess.run([str(LUA),str(script),str(unit_path),"good","1"],
                              cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(unit.returncode,0,unit.stdout+unit.stderr)
        self.assertIn("NATIVE_FULL_PROGRAM=PASS",unit.stdout)
        self.assertEqual(unit.stdout.count("TRACE: timeout_splat "), 1)

    def test_held_off_optional_pulse_bank_and_armed_missing_pulse_fails_closed(self):
        original=copy.deepcopy(self.design)
        self.design['working_points']=[p for p in self.design['working_points'] if p['kind']!='pulse_delta']
        for domain in self.design['domains']:domain['refine_convergence_v'].pop('pulse_delta')
        bank=copy.deepcopy(self.dynamic)
        for row in bank['dynamic_roles']:row.pop('pulse_delta_pa_basename')
        held=self.build(flight={**self.flight,'pulse':{'mode':'held_off'}},standalone_dynamic_field_bank=bank)
        self.assertNotIn((self.root/'delta.pa').as_posix(),held)
        self.assertIn('local handoff_pulse_mode=2',held)
        with self.assertRaisesRegex(ValueError,'armed native flight requires'):
            self.build(standalone_dynamic_field_bank=bank)
        # Discovery's temporary held-OFF phase still has a later timed pulse.
        self.design=original
        retained=self.build(flight={**self.flight,'pulse':{'mode':'held_off'}})
        self.assertIn((self.root/'delta.pa').as_posix(),retained)

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_actual_dynamic_glue_held_off_opens_only_rf_or_no_responses(self):
        # Synthetic PA vectors exercise emitted callbacks, not a numerical field.
        from integrations.runtime.build_single_flight_program import (
            _resolve_standalone_dynamic_field_bank,_bind_standalone_dynamic_field_paths,_standalone_dynamic_field_lua)
        for count in (0,2,3):
            row=dict(role='accelerator_main',instance_index=3,carrier_pa_basename='carrier.pa')
            if count:row.update(rf_differential_pa_basenames=[f'rf_{i}.pa' for i in range(1,count+1)],rf_reference_voltage_v=100.)
            bank={**self.dynamic,'dynamic_roles':[row]}
            specs=_resolve_standalone_dynamic_field_bank(bank,{'accelerator_main':3},requires_rf=bool(count))
            _bind_standalone_dynamic_field_paths(specs,response_paths(bank,self.root))
            fixture=r'''local opened=0
local carrier={pa={path='carrier.pa',nx=3,ny=4,nz=5,dx_mm=1,dy_mm=1,dz_mm=1,symmetry='planar',potential_type='electric'},filename='carrier.pa'}
function carrier:wb_to_pa_coords() return 0,0,0 end
simion={wb={instances={[3]=carrier}},pas={}}
function simion.pas:open(path)
 assert(not path:find('pulse') and not path:find('delta'),'held-off opened unused pulse')
 opened=opened+1;local index=assert(tonumber(path:match('rf_(%d+)%.pa$')))
 local pa={};for k,v in pairs(carrier.pa) do pa[k]=v end
 function pa:field_vc() return index,0,0 end
 return pa
end
local single_flight_rf_drives={}
for i=1,3 do local k=i;single_flight_rf_drives[i]={differential_at=function() return k end} end
local single_flight_pulse={is_active_at=function() error('held-off queried pulse response') end}
ion_instance=3;ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0
''' + _standalone_dynamic_field_lua(specs) + f'''
single_flight_initialize_standalone_dynamic_fields()
assert(opened=={count})
ion_dvoltsx_gu=10;ion_dvoltsy_gu=0;ion_dvoltsz_gu=0
single_flight_apply_standalone_dynamic_field(carrier,60)
assert(math.abs(ion_dvoltsx_gu-(10-{sum(i*i for i in range(1,count+1))}/100))<1e-12)
single_flight_standalone_dynamic_by_instance={{}};single_flight_initialize_standalone_dynamic_fields()
assert(opened=={count},'repeat Fly reopened cached RF fields')
print('HELD_OFF_RESPONSE_FIXTURE=PASS')
'''
            path=self.root/f'held_off_{count}.lua';path.write_text(fixture)
            result=subprocess.run([str(LUA),str(path)],cwd=self.root,capture_output=True,text=True,timeout=20,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('HELD_OFF_RESPONSE_FIXTURE=PASS',result.stdout)

    def test_actual_local_held_off_carrier_only_program_and_armed_guard(self):
        import csv
        from integrations.workflows.single_reflection_flight.field_plan import field_bank
        with tempfile.TemporaryDirectory() as directory:
            path,run,request,_=release_fixture(Path(directory),local=True)
            flight=dict(pulse={'mode':'held_off'},maximum_flight_us=200.,maximum_step_us=.001,trajectory_quality=10)
            request['flight']=flight;path.write_text(json.dumps(request));prepare(path,run)
            design=json.loads((run/'inputs/frontend_field_design.json').read_text())
            geometry=json.loads((run/'inputs/frontend_geometry.json').read_text())
            _,oatof=read_designs(run)
            with (run/'inputs/projected_source.csv').open(newline='') as stream:rows=list(csv.DictReader(stream))
            bank=field_bank(design,['parent'])
            bank['dynamic_roles'][0].update(role='accelerator_main',instance_index=3)
            options=dict(frontend_geometry=geometry,flight=flight,
                birth_times_us=[float(r['instrument_time_us']) for r in rows],particle_ids=[int(r['particle_id']) for r in rows],
                initial_velocities_mm_per_us=[[float(r[f'velocity_{a}_m_s'])/1000 for a in 'xyz'] for r in rows],
                standalone_dynamic_field_bank=bank,standalone_dynamic_field_paths=response_paths(bank,self.root),
                downstream_static_fields=self.static,**self.sources)
            program=build_successor_program({},design,oatof,**options)
            self.assertEqual([point['kind'] for point in design['working_points']],['carrier_off'])
            self.assertNotIn('frontend.pulse_delta.pa',program)
            self.assertIn('local handoff_pulse_mode=2',program)
            options['flight']={**flight,'pulse':{'mode':'timed','time_us':43.,'width_us':3.}}
            with self.assertRaisesRegex(ValueError,'armed native flight requires'):
                build_successor_program({},design,oatof,**options)



if __name__ == "__main__":
    unittest.main()
