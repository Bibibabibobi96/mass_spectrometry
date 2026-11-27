"""Split OA鈥揟OF native collector keeps full mixed-mass mother identities."""
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import patch

from msplatform.backends.simion.tracking_collection import _collect_tracking_logs, read_plane_observations
from msplatform.backends.simion.tracking_program import _instrument_plane_observations
from msplatform.backends.simion.tracking_execution import _split_tracking_contract
from msplatform.backends.simion.tracking_program import _bound_tracking_model, _native_field_analyzer_config


def source(pid, mass, charge):
    return dict(particle_id=pid, mass_amu=mass, charge_state=charge, instrument_time_us=0.,
                position_x_mm=0., position_y_mm=0., position_z_mm=0.,
                velocity_x_m_s=1000., velocity_y_m_s=0., velocity_z_m_s=0.)


def native_particle(index, pid):
    return (f'TRACE: source_release ion={index} particle_id={pid} instrument_time_us=0 '
            'x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0\n'
            f'TRACE: handoff_terminal_raw ion={index} instance=3 instrument_time_us=2 '
            'x_mm=2 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0\n'
            f'TRACE: timeout_splat ion={index} instance=3 instrument_time_us=2 '
            'x_mm=2 y_mm=0 z_mm=0 zmax_mm=0\n')


class SplitTofTrackingTests(unittest.TestCase):
    def test_planner_rejects_id_above_lua_log_abi_before_field_work(self):
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from types import SimpleNamespace
        with patch('msplatform.backends.simion.tracking_execution.require_prepared_model', return_value={}), \
             patch('msplatform.backends.simion.tracking_execution.model_geometry', return_value=SimpleNamespace(frontend_geometry={})):
            with self.assertRaisesRegex(ValueError, '2147483647'):
                plan_tracking_execution(None, particles={'rows':[{'particle_id':2**31}]}, clock_records={},
                    propagation={}, observations={}, numerics={})

    @unittest.skipUnless(Path('C:/Program Files/SIMION-2020/lua.exe').is_file(), 'standalone Lua unavailable')
    def test_actual_lua_integer_log_boundary(self):
        result = subprocess.run(['C:/Program Files/SIMION-2020/lua.exe', '-e',
            "print(string.format('%d',2147483647));print(string.format('%d',2147483648))"],
            cwd=Path(__file__).parent, timeout=15, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['2147483647', '-2147483648'])

    def test_complete_tof_guard_is_limited_to_actual_instrument(self):
        from msplatform.assembly.handoff import HandoffResult
        from msplatform.backends.simion.tracking_execution import _guard_complete_tof_flight
        handoff = object.__new__(HandoffResult)
        composite = dict(role='frontend_geometry', composition_plan=dict(scope=dict(instance_ids=['analyzer']),
            components=dict(analyzer=dict(project_id='single_reflection_oa_tof_mass_analyzer'))))
        split = dict(role='simion_split_oa_tof_geometry')
        for geometry in (composite, split):
            _guard_complete_tof_flight(geometry, {}, dict(scope='continuous_assembly'))
            for particles, scope in ((handoff, 'continuous_assembly'), ({}, 'state_relaunch'), ({}, 'segmented_upstream')):
                with self.assertRaises(ValueError):
                    _guard_complete_tof_flight(geometry, particles, dict(scope=scope))
        unrelated = dict(role='independent_rf', composition_plan=dict(scope=dict(instance_ids=['rf']),
            components=dict(rf=dict(project_id='rf_multipole_ion_optics'))))
        _guard_complete_tof_flight(unrelated, handoff, dict(scope='state_relaunch'))

    def test_split_birth_source_and_real_pose(self):
        from msplatform.backends.simion.tracking_execution import _birth_states, _validate_split_birth_instance
        components = {'rf': dict(project_id='rf_multipole_ion_optics', local_frame_id='rf_frame'),
                      'oa': dict(project_id='orthogonal_accelerator', local_frame_id='oa_frame'),
                      'tof': dict(project_id='single_reflection_tof', local_frame_id='tof_frame')}
        transform = dict(schema_version=1, role='rigid_transform', from_frame_id='rf_frame', to_frame_id='world',
                         rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[5., 0., 0.])
        plan = dict(schema_version=6, scope=dict(instance_ids=['rf','oa','tof']), components=components,
                    assembly_frame_id='world', recipe=dict(instances=[dict(instance_id='rf',transform=transform)],
                    connections=[dict(upstream=dict(instance_id='rf'), downstream=dict(instance_id='oa'))]))
        geometry = dict(composition_plan=plan, native_frame_id='world')
        row = dict(source_component_id='rf', frame_id='rf_frame', mass_amu=100., instrument_time_us=1.,
                   position_x_mm=2., position_y_mm=0., position_z_mm=0.,
                   velocity_x_m_s=100., velocity_y_m_s=0., velocity_z_m_s=0.)
        _validate_split_birth_instance(geometry, [row])
        with self.assertRaises(ValueError):
            _validate_split_birth_instance(geometry, [dict(row, source_component_id='oa')])
        with patch('msplatform.backends.simion.tracking_execution.validate_birth_source', return_value=([row], None, None)), \
             patch('msplatform.backends.simion.tracking_execution.validate_component_particle_state_rows'):
            projected, _, _ = _birth_states({}, geometry)
        self.assertEqual(projected[0]['position_x_mm'], 7.)
        self.assertEqual(projected[0]['frame_id'], 'world')

    def test_real_split_prepared_model_binds_tracking_field_and_analyzer(self):
        from msplatform.backends.simion import model as model_module
        from msplatform.backends.simion.native_plans import plan_solve_fields
        from tests.contracts.test_split_tof_simion import SplitTofSimionTests
        produced = []
        original = model_module.compile_prepared_model
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            produced.append(result)
            return result
        with patch.object(model_module, 'compile_prepared_model', side_effect=capture):
            SplitTofSimionTests('test_split_two_component_geometry_uses_real_provider_snapshots').test_split_two_component_geometry_uses_real_provider_snapshots()
        model = next(item for item in produced if model_module.model_geometry(item).frontend_geometry.get('role') == 'simion_split_oa_tof_geometry')
        doc = model_module.require_prepared_model(model)
        geometry = model_module.model_geometry(model, downstream_drive=True).frontend_geometry
        flight = dict(pulse=doc['drive']['pulse'], maximum_flight_us=10., maximum_step_us=.1, trajectory_quality=8)
        numerics = dict(parent=dict(refine_convergence_v=dict(carrier_off=.01, pulse_delta=.01)))
        design = plan_solve_fields(model, numerics=dict(frontend_domains=numerics))['field_design']
        self.assertEqual(_bound_tracking_model(model, {}, doc['components_resolved']['tof'], geometry, design, flight), doc)
        reference = doc['drive']['pulse']
        discovery = {'phase': 'discovery', 'author': {'mode': 'discover',
            'width_us': reference['width_us'],
            'candidate_times_us': [reference['time_us'], reference['time_us'] + 1.]}}
        pilot = dict(flight, pulse={'mode': 'held_off'})
        self.assertEqual(_bound_tracking_model(model, {}, doc['components_resolved']['tof'],
            geometry, design, pilot, discovery), doc)
        with self.assertRaises(ValueError):
            _bound_tracking_model(model, {}, doc['components_resolved']['tof'], geometry, design, pilot)
        with self.assertRaises(ValueError):
            _bound_tracking_model(model, {}, doc['components_resolved']['tof'], geometry, design,
                pilot, dict(discovery, phase='selected'))
        wrong = dict(discovery, author=dict(discovery['author'], width_us=reference['width_us'] + 1.))
        with self.assertRaises(ValueError):
            _bound_tracking_model(model, {}, doc['components_resolved']['tof'], geometry, design, pilot, wrong)
        _, config = _native_field_analyzer_config({}, design, geometry, doc['components_resolved']['tof'], model_document=doc)
        self.assertEqual(config['instance_roles']['detector'], 4)
        self.assertEqual(config['geometry']['detector_z_mm'], geometry['detector_active_face']['native']['center_mm'][2])

        # Render the real compiled model with synthetic owned records; no Fly.
        from msplatform.backends.simion.field_bank import field_bank
        from msplatform.backends.simion.field_identity import working_point_member_id
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.execution.resources import resource_path
        from msplatform.backends.simion.tracking_execution import _render_tracking_controls
        from tests.contracts.test_split_scalar_tracking import basis
        with TemporaryDirectory() as directory:
            root = Path(directory)
            record = lambda name: dict(path=str(root/name), exists=True, bytes=123, sha256='a'*64)
            domains = [row['domain_id'] for row in design['domains']]
            frontend = {domain:{working_point_member_id(point):record('frontend.'+working_point_member_id(point)+'.pa')
                        for point in design['working_points']} for domain in domains}
            downstream = {}
            for role in ('flight_tube','reflectron','detector'):
                family = [record(role+s) for s in ('.pa#','.pa0','.pa1','.pa-surf')] if role != 'reflectron' else []
                downstream[role] = dict(carrier_record=family[1] if family else record(role+'.pa'), family_records=family)
            sources = {key:native_resource_path(name).read_text(encoding='utf8') for key,name in dict(
                analyzer_component_source='oatof_analyzer_component.lua',pulse_hook_source='single_flight_pulse_hook.lua',
                frontend_hook_source='single_flight_frontend_hook.lua',rf_drive_kernel_source='rf_drive.lua',
                voltage_waveforms_source='voltage_waveforms.lua',scalar_adapter_source='scalar_field_adapter.lua',
                scalar_composer_source='split_scalar_field.lua').items()}
            sources['native_path_source'] = resource_path('native_run_path.lua').read_text(encoding='utf8')
            scalar = basis()
            scalar['world_projection'] = dict(role_slots=dict(background=1,flight_tube=2,reflectron=3,accelerator=4,detector=5),
                                              slots=[dict(path=str(root/'background.pa'))])
            row = dict(particle_id=1, instrument_time_us=0., particle_birth_time_us=0.,
                       velocity_x_m_s=0., velocity_y_m_s=0., velocity_z_m_s=1000.)
            plan = dict(rows=[row], flight=dict(flight, tracking_kind='split_oa_tof', detector_instance=5),
                        absolute_deadlines_us_by_particle_id={1:10.}, scalar_field_basis=scalar,
                        observations=dict(plane_observations=[]),
                        propagation=dict(consumed_plane_events=[], stop=None))
            rendered = _render_tracking_controls(model, plan, field_design=design, stored_bank=field_bank(design,domains),
                frontend_records=frontend, downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            self.assertEqual(rendered['build_metadata']['instance_roles'],
                dict(background=1,flight_tube=2,reflectron=3,accelerator=4,detector=5))
            self.assertIn('local single_flight_accelerator_instance_index=4', rendered['program'])
            self.assertIn('local single_flight_detector_instance_index=5', rendered['program'])
            plan['observations']['field_intervention'] = {'id': 'ideal', 'selector': 'ideal:reflectron.ez'}
            diagnostic = _render_tracking_controls(model, plan, field_design=design, stored_bank=field_bank(design,domains),
                frontend_records=frontend, downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            self.assertIn('ideal_reflectron_stage1_axial=true', diagnostic['program'])
            self.assertIn('ideal_reflectron_stage2_axial=true', diagnostic['program'])
            self.assertEqual(diagnostic['build_metadata']['field_intervention']['selector'], 'ideal:reflectron.ez')
            # Run the generated callback with the actual analyzer/region code and
            # controlled scalar samples. This is a Lua software test, not a Fly.
            import re
            lua = Path('C:/Program Files/SIMION-2020/lua.exe')
            if not lua.is_file():
                self.skipTest('standalone SIMION Lua unavailable')
            harness = root / 'scalar_intervention_harness.lua'
            harness.write_text(r"""
segment={}
simion={workbench_program=function() end,early_access=function() end,wb={instances={}}}
ion_number=1;ion_time_of_flight=0;ion_px_mm=0;ion_py_mm=0
local slot=tonumber(arg[2]);ion_instance=slot
simion.wb.instances[slot]={pa={dx_mm=2,dy_mm=3,dz_mm=4},scale=1}
dofile(arg[1]);segment.test_setup()
ion_pz_mm=segment.test_position();ion_dvoltsx_gu=2;ion_dvoltsy_gu=3;ion_dvoltsz_gu=4
segment.efield_adjust()
local expected,full=segment.test_expected(tonumber(arg[3]))
assert(math.abs(ion_dvoltsx_gu-expected)<1e-12, tostring(ion_dvoltsx_gu)..' vs '..tostring(expected))
assert(ion_dvoltsy_gu==(full and 0 or 3) and ion_dvoltsz_gu==(full and 0 or 4))
print('SCALAR_INTERVENTION_CALLBACK=PASS')
""", encoding='utf-8')
            tail = r"""
segment.test_setup=function()
 single_flight_scalar=function() return 2,3,4 end
 single_flight_analyzer=single_flight_analyzer_component.new(analyzer_config)
 single_flight_pulse={is_active_at=function() return false end}
end
segment.test_position=function()
 if tonumber(arg[3])==2 then return (analyzer_config.geometry.reflectron_midgrid_z_mm+analyzer_config.geometry.reflectron_backplate_z_mm)/2 end
 return (analyzer_config.geometry.reflectron_entgrid_z_mm+analyzer_config.geometry.reflectron_midgrid_z_mm)/2
end
segment.test_expected=function(stage)
 local m=analyzer_config.field_modes
 local full=stage==1 and m.ideal_reflectron_stage1 or stage==2 and m.ideal_reflectron_stage2
 if stage==1 and (m.ideal_reflectron_stage1_axial or full) then
  return 2*analyzer_config.voltages.mid_v/(analyzer_config.geometry.reflectron_midgrid_z_mm-analyzer_config.geometry.reflectron_entgrid_z_mm),full
 elseif stage==2 and (m.ideal_reflectron_stage2_axial or full) then
  return 2*(analyzer_config.voltages.backplate_v-analyzer_config.voltages.mid_v)/(analyzer_config.geometry.reflectron_backplate_z_mm-analyzer_config.geometry.reflectron_midgrid_z_mm),full
 end
 return 2,false
end
"""
            import copy
            four_plan = copy.deepcopy(plan)
            four_plan.pop('scalar_field_basis')
            four_plan['flight']['detector_instance'] = 4
            four_plan['observations'].pop('field_intervention')
            four_base = _render_tracking_controls(model, four_plan, field_design=design, stored_bank=field_bank(design,domains),
                frontend_records=frontend, downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            four_plan['observations']['field_intervention'] = {'id': 'ideal', 'selector': 'ideal:reflectron.ez'}
            four_ideal = _render_tracking_controls(model, four_plan, field_design=design, stored_bank=field_bank(design,domains),
                frontend_records=frontend, downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            plan['observations']['field_intervention'] = {'id': 'full', 'selector': 'ideal:reflectron.full'}
            full = _render_tracking_controls(model, plan, field_design=design, stored_bank=field_bank(design,domains),
                frontend_records=frontend, downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            four_plan['observations']['field_intervention'] = {'id': 'full', 'selector': 'ideal:reflectron.full'}
            four_full = _render_tracking_controls(model, four_plan, field_design=design, stored_bank=field_bank(design,domains),
                frontend_records=frontend, downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            for label, output, slot in (('real', rendered, 3), ('axial', diagnostic, 3), ('full', full, 3),
                                         ('real', four_base, 2), ('axial', four_ideal, 2), ('full', four_full, 2)):
                program_file = root / ('actual-scalar-' + str(slot) + '-' + label + '.lua')
                config_line = next(line for line in output['program'].splitlines() if line.startswith('  local analyzer_config='))
                program_file.write_text(re.sub(r'\badjustable\s+', '', output['program']) + '\n' + config_line + '\n' + tail, encoding='utf-8')
                for stage in (1, 2):
                    executed = subprocess.run([str(lua), str(harness), str(program_file), str(slot), str(stage)],
                        cwd=root, capture_output=True, text=True, timeout=30, check=False)
                    self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
                    self.assertIn('SCALAR_INTERVENTION_CALLBACK=PASS', executed.stdout)

    def test_split_plan_requires_actual_detector_and_rejects_relaunch(self):
        from msplatform.assembly.handoff import HandoffResult
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from types import SimpleNamespace
        geometry = dict(detector_active_face=dict(instance_id='tof', surface_id='detector_active_face'),
                        downstream_pa_instances=[dict(role='detector', workbench_index=9)])
        propagation = dict(scope='continuous_assembly', stop=None, consumed_plane_events=[])
        detector = dict(schema_version=2, observation_id='detector', source_instance_id='tof',
                        surface_id='detector_active_face', max_records=5)
        observations = dict(plane_observations=[detector])
        self.assertEqual(_split_tracking_contract(geometry, propagation, observations), 9)
        for invalid in (dict(propagation, scope='state_relaunch'),
                        dict(propagation, scope='segmented_upstream'),
                        dict(propagation, consumed_plane_events=[{}])):
            with self.assertRaises(ValueError):
                _split_tracking_contract(geometry, invalid, observations)
        with self.assertRaises(ValueError):
            _split_tracking_contract(geometry, propagation, dict(plane_observations=[]))
        geometry['role'] = 'simion_split_oa_tof_geometry'
        with patch('msplatform.backends.simion.tracking_execution.require_prepared_model', return_value={}), \
             patch('msplatform.backends.simion.tracking_execution.model_geometry', return_value=SimpleNamespace(frontend_geometry=geometry)):
            with self.assertRaisesRegex(ValueError, 'original births'):
                plan_tracking_execution(None, particles=object.__new__(HandoffResult), clock_records={},
                    propagation=propagation, observations=observations, numerics={})

    @unittest.skipUnless(Path('C:/Program Files/SIMION-2020/lua.exe').is_file(), 'standalone Lua unavailable')
    def test_detector_surface_records_only_finite_disk_crossings(self):
        transform = dict(schema_version=1, role='rigid_transform', from_frame_id='world', to_frame_id='world',
                         rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0,0,0])
        face = dict(center_mm=[0.,0.,0.], normal=[0.,0.,1.], radius_mm=1.)
        geometry = dict(role='simion_split_oa_tof_geometry', native_frame_id='world',
            detector_active_face=dict(instance_id='tof', surface_id='detector_active_face', native_frame_id='world', native=face),
            composition_plan=dict(scope=dict(instance_ids=['tof']), components=dict(tof=dict(local_frame_id='world', ports={})),
                                  recipe=dict(instances=[dict(instance_id='tof', transform=transform)])))
        definition = dict(schema_version=2, observation_id='detector', source_instance_id='tof',
                          surface_id='detector_active_face', max_records=8)
        skeleton = '''segment={}
local single_flight_reported={}
local function single_flight_canonical_particle_id() return 91 end
local function single_flight_write_trace(line) print(line) end
function segment.other_actions()
 local p=previous
 local time=now
  local reported=single_flight_reported[ion_number] or {}
end
'''
        metadata = {}
        program = _instrument_plane_observations(skeleton, [definition], geometry, build_metadata=metadata)
        tail = '''ion_number=1
local function cross(x,t)
 previous={t=t,x=x,y=0,z=1,vx=0,vy=0,vz=-1}
 now=t+2;ion_px_mm=x;ion_py_mm=0;ion_pz_mm=-1;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=-1
 segment.other_actions()
end
cross(.5,1);cross(2,4)
'''
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'program.lua'
            path.write_text(program + tail, encoding='utf8')
            completed = subprocess.run(['C:/Program Files/SIMION-2020/lua.exe', str(path)], cwd=folder,
                                       capture_output=True, text=True, timeout=30, check=True)
            log = Path(folder) / 'native.log'
            log.write_text(completed.stdout, encoding='utf8')
            result = read_plane_observations([log], [91], [1], [definition],
                plane_authority=metadata['plane_observation_authority'], native_frame_id='world')
            self.assertEqual(len(result['rows']), 1)
            self.assertEqual(result['rows'][0]['direction'], 'inward')
            self.assertEqual(result['rows'][0]['x_mm'], .5)
            self.assertEqual(result['rows'][0]['vz_mm_per_us'], -1.)
            with self.assertRaises(ValueError):
                read_plane_observations([log], [91], [1], [definition], native_frame_id='world')

    def test_actual_log_parser_closes_mixed_mother_without_detector_hits(self):
        rows = {91: source(91, 100., 1), 7: source(7, 100., 2), 103: source(103, 200., 1)}
        batches = [dict(source_row_range=[1, 2], expected_particle_ids=[91, 7], build_metadata={}),
                   dict(source_row_range=[3, 3], expected_particle_ids=[103], build_metadata={})]
        with TemporaryDirectory() as folder:
            first, second = Path(folder) / 'first.log', Path(folder) / 'second.log'
            first.write_text(native_particle(1, 91) + native_particle(2, 7) +
                             'status,Fly completed. 2 splats, 0.1 seconds\n', encoding='utf8')
            second.write_text(native_particle(1, 103) +
                              'status,Fly completed. 1 splats, 0.1 seconds\n', encoding='utf8')
            result = _collect_tracking_logs([first, second], source_rows=rows, source_provenance={},
                flight=dict(tracking_kind='split_oa_tof', detector_instance=9, pulse=dict(mode='held_off')),
                batches=batches)
            self.assertTrue(result['native_complete'])
            self.assertEqual([row['particle_id'] for row in result['native_terminals']], [91, 7, 103])
            self.assertEqual(result['census']['terminal_taxonomy']['category_counts'], {'timeout_splat': 3})
            second.write_text('status,Fly completed. 1 splats, 0.1 seconds\n', encoding='utf8')
            with self.assertRaises(ValueError):
                _collect_tracking_logs([first, second], source_rows=rows, source_provenance={},
                    flight=dict(tracking_kind='split_oa_tof', detector_instance=9, pulse=dict(mode='held_off')),
                    batches=batches)


if __name__ == '__main__':
    unittest.main()
