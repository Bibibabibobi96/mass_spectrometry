"""Exercise real focus observer callbacks with an inert TestPlane stub, not SIMION Fly."""
import subprocess
import tempfile
import unittest
import os
from pathlib import Path

from tests.contracts.test_simion_prepared_model import LUA

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / 'src/msplatform/backends/simion/resources/oa_focus_observer.lua'
TESTPLANE = Path(os.environ.get('SIMION_EXE', 'C:/Program Files/SIMION-2020/simion.exe')).parent / 'examples/test_plane/testplanelib.lua'


class FocusCallbackTests(unittest.TestCase):
    @unittest.skipUnless(TESTPLANE.is_file() and LUA.is_file(), 'SIMION TestPlane or Lua unavailable')
    def test_real_renderer_preserves_four_oa_field_modes_and_boundaries(self):
        from msplatform.backends.simion.rf_tracking_program import render_rf_controls
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from msplatform.io.manifest_records import file_record
        from msplatform.particle_release.authoring import sample_release
        from msplatform.recipes import load_recipe
        from tests.contracts.test_support.oa_focus_study import make_focus_recipe
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); author,_,projection=make_focus_recipe(root)
            packet=sample_release(load_recipe(author).to_dict()['study']['document']['release']).to_dict()
            model=projection['model']; clock=model.document['drive']['clock']
            clocks={key:dict(path=str(root/(key+'.json')),exists=True,bytes=1,
                sha256=clock['authority_sha256'] if key=='instrument_epoch' else 'A'*64) for key in ('clock_authority','instrument_epoch')}
            propagation=dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=50.),
                consumed_plane_events=[],stop=None,dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'),
                publication_contract='oa_focus_original_birth_si_v1')
            record=file_record(TESTPLANE,'required_evidence')
            original_rows=None
            for mode in ('native','zone1_ideal','zone2_ideal','full_ideal'):
                with self.subTest(mode=mode):
                    plan=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,
                        observations=dict(plane_observations=[],oa_focus_authority=projection['observations'],oa_focus_field_mode=mode),
                        numerics=dict(maximum_step_us=.0005,trajectory_quality=8),focus_testplane_record=record)
                    if original_rows is None: original_rows=plan['rows']
                    self.assertEqual(plan['rows'],original_rows)
                    plan['flight']['oa_focus_runtime']['testplane_path']='C:/inert/testplanelib.lua'
                    program=render_rf_controls(model,plan,assets={},native_sources={})['program']
                    stub="simion={workbench_program=function() segment={} end,import=function() return function(...) return {tstep_adjust=function() end,other_actions=function() end} end end,wb={instances={{pa={dz_mm=.1},scale=1}}}};ion_instance=1;\n"
                    tail="\nfor _,z in ipairs({34,30,15,0,-1,35}) do ion_pz_mm=z;ion_dvoltsx_gu=7;ion_dvoltsy_gu=8;ion_dvoltsz_gu=9;if segment.efield_adjust then segment.efield_adjust() end;print('F '..z..' '..ion_dvoltsx_gu..' '..ion_dvoltsy_gu..' '..ion_dvoltsz_gu) end\n"
                    script=root/(mode+'.lua');script.write_text(stub+program+tail,encoding='utf8')
                    result=subprocess.run([str(LUA),str(script)],capture_output=True,text=True,timeout=20,cwd=script.parent)
                    self.assertEqual(result.returncode,0,result.stderr)
                    rows=[list(map(float,line.split()[1:])) for line in result.stdout.splitlines() if line.startswith('F ')]
                    groups=model.document['drive']['groups']['oa'];v=[groups[name]['voltage_v'] for name in ('repeller','intermediate_grid_1','exit_grid')]
                    for z,x,y,field in rows:
                        zone1=30<=z<=34 and mode in ('zone1_ideal','full_ideal')
                        zone2=0<=z<30 and mode in ('zone2_ideal','full_ideal')
                        expected=(v[1]-v[0])/(30-34)*.1 if zone1 else (v[2]-v[1])/(0-30)*.1 if zone2 else 9.
                        self.assertAlmostEqual(field,expected,places=9)
                        self.assertEqual((x,y),(0.,0.) if zone1 or zone2 else (7.,8.))

    @unittest.skipUnless(TESTPLANE.is_file(), 'SIMION TestPlane library unavailable')
    def test_explicit_negative_ion_uses_same_focus_planner(self):
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from msplatform.io.manifest_records import file_record
        from msplatform.particle_release.authoring import sample_release
        from msplatform.recipes import load_recipe
        from msplatform.workflows.oa_focus_model_projection import project_focus_model
        from tests.contracts.test_support.oa_focus_study import make_signed_focus_recipe
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            author,_,base=make_signed_focus_recipe(root,species_kind='negative_ion')
            old=base['observations']
            projection=project_focus_model(root/'focus_campaign.json',geometry_profile=old['geometry_profile'],
                mesh_mm_per_gu=old['mesh_mm_per_gu'],clock=old['clock'])
            release=load_recipe(author).to_dict()['study']['document']['release']
            packet=sample_release(release).to_dict()
            clock=projection['model'].document['drive']['clock']
            clocks={key:dict(path=str(root/(key+'.json')),exists=True,bytes=1,
                sha256=clock['authority_sha256'] if key=='instrument_epoch' else 'A'*64) for key in ('clock_authority','instrument_epoch')}
            propagation=dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=50.),
                consumed_plane_events=[],stop=None,dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'),
                publication_contract='oa_focus_original_birth_si_v1')
            library=file_record(TESTPLANE,'required_evidence')
            plan=plan_tracking_execution(projection['model'],particles=packet,clock_records=clocks,propagation=propagation,
                observations=dict(plane_observations=[],oa_focus_authority=projection['observations']),
                numerics=dict(maximum_step_us=.0005,trajectory_quality=8),focus_testplane_record=library)
            self.assertEqual(len(plan['rows']),100)
            self.assertTrue(all(row['charge_state']==-1 for row in plan['rows']))
            self.assertEqual(plan['species'][0]['species_kind'],'ion')

    @unittest.skipUnless(TESTPLANE.is_file(), 'SIMION TestPlane library unavailable')
    def test_authorized_planner_derives_planes_and_binds_testplane_bytes(self):
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        from msplatform.particle_release.authoring import sample_release
        from msplatform.recipes import load_recipe
        from tests.contracts.test_support.oa_focus_study import make_focus_recipe
        with tempfile.TemporaryDirectory() as directory:
            author, _, projection = make_focus_recipe(Path(directory))
            release = load_recipe(author).to_dict()['study']['document']['release']
            packet = sample_release(release).to_dict()
            clock = projection['model'].document['drive']['clock']
            clocks = {key:dict(path=str(resource_path('native_run_path.lua')),exists=True,bytes=1,
                sha256=clock['authority_sha256'] if key=='instrument_epoch' else 'A'*64) for key in ('clock_authority','instrument_epoch')}
            propagation = dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=50.),
                consumed_plane_events=[],stop=None,dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'),
                publication_contract='oa_focus_original_birth_si_v1')
            record = file_record(TESTPLANE,'required_evidence')
            plan = plan_tracking_execution(projection['model'],particles=packet,clock_records=clocks,propagation=propagation,
                observations=dict(plane_observations=[],oa_focus_authority=projection['observations']),
                numerics=dict(maximum_step_us=.0005,trajectory_quality=8),focus_testplane_record=record)
            self.assertEqual(len(plan['rows']),100)
            self.assertEqual(plan['focus_testplane_identity'],{key:record[key] for key in ('bytes','sha256')})
            self.assertEqual(plan['flight']['oa_focus_runtime']['planes'][0]['center_mm'],plan['flight']['oa_focus_runtime']['planes'][1]['center_mm'])
            import copy
            from msplatform.backends.simion.tracking_units import tracking_applicability
            replay = plan_tracking_execution(projection['model'],particles=packet,clock_records=clocks,propagation=propagation,
                observations=plan['observations'],numerics=dict(maximum_step_us=.0005,trajectory_quality=8),focus_testplane_record=record)
            self.assertEqual(tracking_applicability(plan),tracking_applicability(replay))
            forged = copy.deepcopy(plan['observations'])
            forged['plane_observations'][0]['port_id'] = 'untrusted'
            with self.assertRaisesRegex(ValueError,'plane definitions differ'):
                plan_tracking_execution(projection['model'],particles=packet,clock_records=clocks,propagation=propagation,
                    observations=forged,numerics=dict(maximum_step_us=.0005,trajectory_quality=8),focus_testplane_record=record)
            changed = copy.deepcopy(plan)
            changed['focus_testplane_identity']['sha256'] = 'F'*64
            self.assertNotEqual(tracking_applicability(plan),tracking_applicability(changed))
            bad = copy.deepcopy(projection['observations'])
            bad['focus_z_mm'] -= 1.
            with self.assertRaisesRegex(ValueError,'focus authority or actual compiled model differs'):
                plan_tracking_execution(projection['model'],particles=packet,clock_records=clocks,propagation=propagation,
                    observations=dict(plane_observations=[],oa_focus_authority=bad),
                    numerics=dict(maximum_step_us=.0005,trajectory_quality=8),focus_testplane_record=record)

    def run_case(self, tail, *, initial_z=1, initial_vz=-1):
        module = OBSERVER.read_text(encoding='utf8')
        program = '''local M=(function()\n''' + module + '''\nend)()
local function plane(...) return {tstep_adjust=function() end,other_actions=function() end} end
local t=0;ion_number=1;ion_instance=1;ion_splat=0
ion_px_mm=0;ion_py_mm=0;ion_pz_mm=1;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=-1
local spec={exit_id='oa_focus_exit',focus_id='oa_focus_plane',planes={
{observation_id='oa_focus_exit',center_mm={0,0,0},normal={0,0,-1}},
{observation_id='oa_focus_plane',center_mm={0,0,0},normal={0,0,-1}}}}
local obs=M.new(spec,plane,function()return t end,function()return 7 end,print)
obs.initialize();obs.tstep_adjust();obs.other_actions()
'''.replace('ion_pz_mm=1;', 'ion_pz_mm='+repr(initial_z)+';').replace('ion_vz_mm=-1\n','ion_vz_mm='+repr(initial_vz)+'\n') + tail
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'focus.lua'
            script.write_text(program, encoding='utf8')
            result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True, timeout=20, cwd=script.parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_coincident_forward_planes_stop_immediately_and_close_at_terminal(self):
        out = self.run_case("t=2;ion_pz_mm=-1;obs.other_actions();assert(ion_splat==1);obs.terminate()")
        rows = [line for line in out.splitlines() if line.startswith('PLANE_OBSERVATION_V1:')]
        self.assertEqual(len(rows), 2)
        self.assertIn('observation_id=oa_focus_exit', rows[0])
        self.assertIn('observation_id=oa_focus_plane', rows[1])
        self.assertTrue(all('instrument_time_us=1 ' in row for row in rows))

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_terminal_mismatch_and_rollback_do_not_emit_events(self):
        for tail in ("t=2;ion_pz_mm=-1;obs.other_actions();ion_pz_mm=-2;obs.terminate()",
                     "t=1;ion_pz_mm=.5;obs.other_actions();t=.5;obs.other_actions();obs.terminate()"):
            with self.subTest(tail=tail):
                out = self.run_case(tail)
                self.assertIn('OA_FOCUS_INCOMPLETE_V1:', out)
                self.assertNotIn('PLANE_OBSERVATION_V1:', out)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_terminal_at_interpolated_plane_is_reconciled_without_replacing_state(self):
        out = self.run_case('t=2;ion_pz_mm=-1;obs.other_actions();t=1;ion_pz_mm=0;obs.terminate()')
        self.assertIn('terminal_mode=plane_reconciled',out)
        self.assertEqual(out.count('PLANE_OBSERVATION_V1:'),2)
        wrong = self.run_case('t=2;ion_pz_mm=-1;obs.other_actions();t=1;ion_pz_mm=.01;obs.terminate()')
        self.assertIn('OA_FOCUS_INCOMPLETE_V1:',wrong)
        self.assertNotIn('PLANE_OBSERVATION_V1:',wrong)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_replay_real_testplane_terminal_values_and_reject_tampering(self):
        # Exact native action/terminate values from failed run e24551c4ac834e319c732de29fc0c54d.
        # The start of this synthetic bracket is independently constructed; the
        # historical log did not retain the previous action and is not relabeled native evidence.
        action='t=.023755725259154967;ion_pz_mm=-.99999999999999989;obs.other_actions();'
        terminal='t=.023035854796756332;ion_pz_mm=4.2351647362715017e-22;'
        kwargs=dict(initial_z=32,initial_vz=-1389.1388134859185)
        out=self.run_case(action+terminal+'obs.terminate()',**kwargs)
        self.assertIn('terminal_mode=plane_reconciled',out)
        for alteration in ('ion_instance=2;', 'ion_vz_mm=-1389;', 't=.02304;', 'ion_pz_mm=.01;', 't=.01;ion_pz_mm=18.108611865140815;'):
            with self.subTest(alteration=alteration):
                bad=self.run_case(action+terminal+alteration+'obs.terminate()',**kwargs)
                self.assertIn('OA_FOCUS_INCOMPLETE_V1:',bad)
                self.assertNotIn('PLANE_OBSERVATION_V1:',bad)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_wrong_direction_does_not_cross(self):
        out = self.run_case('t=2;ion_pz_mm=-1;ion_vz_mm=1;obs.other_actions();assert(ion_splat==0);obs.terminate()')
        self.assertNotIn('PLANE_OBSERVATION_V1:', out)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_first_step_starting_on_plane_keeps_original_boundary_rule(self):
        out = self.run_case('t=1;ion_pz_mm=-1;obs.other_actions();assert(ion_splat==1);obs.terminate()',initial_z=0)
        rows=[line for line in out.splitlines() if line.startswith('PLANE_OBSERVATION_V1:')]
        self.assertEqual(len(rows),2)

    @unittest.skipUnless(TESTPLANE.is_file() and LUA.is_file(), 'SIMION TestPlane or Lua unavailable')
    def test_installed_testplane_library_caps_real_observer_step(self):
        library = TESTPLANE
        module = OBSERVER.read_text(encoding='utf8')
        program = '''local M=(function()\n''' + module + '''\nend)()
local testplane=assert(loadfile(''' + repr(library.as_posix()) + '''))()
ion_number=1;ion_instance=1;ion_splat=0;ion_time_step=10
ion_px_mm=0;ion_py_mm=0;ion_pz_mm=1;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=-1
local spec={exit_id='e',focus_id='f',planes={{observation_id='e',center_mm={0,0,0},normal={0,0,-1}},
 {observation_id='f',center_mm={0,0,0},normal={0,0,-1}}}}
local obs=M.new(spec,testplane,function()return 0 end,function()return 7 end,print)
obs.initialize();obs.tstep_adjust();assert(ion_time_step>0 and ion_time_step<10);print('TESTPLANE_CAP='..ion_time_step)
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'actual-testplane.lua'
            script.write_text(program,encoding='utf8')
            result = subprocess.run([str(LUA),str(script)],capture_output=True,text=True,timeout=20,cwd=script.parent)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('TESTPLANE_CAP=',result.stdout)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_actual_oa_renderer_wraps_native_callbacks(self):
        import copy
        from msplatform.backends.simion.rf_tracking_program import render_rf_controls
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from tests.contracts.test_oa_tracking import oa_tracking_case

        _, model, packet, clocks, propagation, numerics = oa_tracking_case()
        packet = copy.deepcopy(packet)
        row = packet['rows'][0]
        packet['rows'] = [row]
        packet['mother']['records'] = {row['particle_id']: packet['mother']['records'][row['particle_id']]}
        packet['mother']['fates'] = [packet['mother']['fates'][0]]
        packet['realization']['spec'] = dict(particle_count=1, species=dict(species_kind='ion', mass_amu=row['mass_amu'], charge_state=row['charge_state']))
        plan = plan_tracking_execution(model, particles=packet, clock_records=clocks,
            propagation=propagation, observations=dict(plane_observations=[]), numerics=numerics)
        state = plan['rows'][0]
        position = [state['position_'+axis+'_mm'] for axis in 'xyz']
        velocity = [state['velocity_'+axis+'_m_s']/1000 for axis in 'xyz']
        magnitude = sum(value*value for value in velocity)**.5
        self.assertGreater(magnitude, 0)
        normal = [value/magnitude for value in velocity]
        center = [position[i]+normal[i]*.5 for i in range(3)]
        planes = [dict(observation_id=name, center_mm=center, normal=normal) for name in ('oa_focus_exit','oa_focus_plane')]
        plan['flight']['oa_focus_runtime'] = dict(planes=planes, exit_id='oa_focus_exit', focus_id='oa_focus_plane', testplane_path='C:/inert/testplanelib.lua')
        plan['flight']['original_birth_si'] = True
        plan['observations']['plane_observations'] = [dict(schema_version=1,observation_id=p['observation_id'],source_instance_id='two',port_id=p['observation_id'],max_records=1) for p in planes]
        controls = render_rf_controls(model, plan, assets={}, native_sources={})
        rendered = controls['program']
        from msplatform.backends.simion.terminal_evidence import append_terminal_recorder
        recorder = (ROOT/'src/msplatform/backends/simion/resources/native_terminal_recording.lua').read_text(encoding='utf8')
        rendered = append_terminal_recorder(rendered, recorder_source=recorder, native_run='inert_focus')
        controls['build_metadata']['terminal_evidence'] = dict(schema_version=1,native_run='inert_focus')
        stub = "simion={workbench_program=function() segment={} end,import=function() return function(...) return {tstep_adjust=function() end,other_actions=function() end} end end};sim_grouped=1;adj_elect={};ion_instance=1;ion_number=1;ion_run=1;ion_time_of_birth=0;ion_time_step=.1;ion_splat=0;ion_time_of_flight=0;ion_mass="+repr(state['mass_amu'])+";ion_charge="+str(state['charge_state'])+";\n"
        stub += ''.join('ion_p'+axis+'_mm='+repr(position[i])+';ion_v'+axis+'_mm='+repr(velocity[i])+';\n' for i, axis in enumerate('xyz'))
        tail = '\nsegment.initialize_run();segment.initialize();segment.other_actions();ion_time_of_flight=1;\n'
        tail += ''.join('ion_p'+axis+'_mm='+repr(position[i]+normal[i])+';\n' for i, axis in enumerate('xyz'))
        tail += 'segment.other_actions();assert(ion_splat==1);segment.terminate()\n'
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'rendered.lua'
            script.write_text(stub+rendered+tail, encoding='utf8')
            result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True, timeout=20, cwd=script.parent)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('PLANE_OBSERVATION_V1:'), 2)
            log = Path(directory) / 'inert-stdout.log'
            log.write_text(result.stdout+'status,Fly completed. 1 splats\n', encoding='utf8')
            from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
            collected = collect_rf_tracking_logs([log], source_rows={state['particle_id']:state},
                source_provenance=plan['source_provenance'], flight=plan['flight'], batches=[dict(
                    source_row_range=[1,1], expected_particle_ids=[state['particle_id']], build_metadata=controls['build_metadata'])])
            self.assertEqual(collected['census']['terminal_taxonomy']['particle_outcomes'][0]['category'],'programmatic_focus_stop')
            self.assertEqual(len(collected['plane_observations']['rows']),2)
            import re
            tampered = re.sub(r'signed_distance_before_mm=[^ ]+', 'signed_distance_before_mm=-123',
                              result.stdout, count=1)
            bad_log = Path(directory)/'bad-stdout.log'
            bad_log.write_text(tampered+'status,Fly completed. 1 splats\n',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'focus bracket differs'):
                collect_rf_tracking_logs([bad_log],source_rows={state['particle_id']:state},
                    source_provenance=plan['source_provenance'],flight=plan['flight'],batches=[dict(
                        source_row_range=[1,1],expected_particle_ids=[state['particle_id']],build_metadata=controls['build_metadata'])])
            from msplatform.backends.simion.terminal_evidence import attach_terminal_evidence
            attach_terminal_evidence(collected, [log], [dict(expected_particle_ids=[state['particle_id']],build_metadata=controls['build_metadata'])])
            from msplatform.backends.simion.particle_data import adapt_native_results
            from msplatform.physics import CONSTANTS
            bindings={name:dict(component_id='two',surface_id=name,electrode_id=None,kind='observation') for name in ('oa_focus_exit','oa_focus_plane')}
            result_si=adapt_native_results({state['particle_id']:state},collected,backend_version='inert_fixture',
                observation_bindings=bindings,observation_times_us=[],constants=CONSTANTS,detector_instance=None)
            self.assertEqual([event['surface_id'] for event in result_si.events],['oa_focus_exit','oa_focus_plane'])
            self.assertEqual(result_si.events[0]['position_m'],result_si.events[1]['position_m'])
            self.assertNotEqual(result_si.terminal_states[0]['position_m'],result_si.events[1]['position_m'])
            from msplatform.results.particle_data import read_particle_data, write_particle_data
            output = Path(directory)/'particle_data'
            output.mkdir()
            clock = model.document['drive']['clock']
            write_particle_data(output,result_si,metadata=dict(schema_version=2,initial_state_basis='native_birth_verified',
                frame_id=model.document['native_frame_id'],clock=dict(basis='experiment_relative',unit='s',
                    clock_epoch_id=clock['clock_epoch_id'],authority_sha256=clock['authority_sha256']),species=plan['species']))
            reread = read_particle_data(output)
            self.assertEqual(len(reread['events']),2)


if __name__ == '__main__':
    unittest.main()
