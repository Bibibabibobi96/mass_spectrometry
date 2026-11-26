"""Split OA–TOF native collector keeps full mixed-mass mother identities."""
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
        _, config = _native_field_analyzer_config({}, design, geometry, doc['components_resolved']['tof'], model_document=doc)
        self.assertEqual(config['instance_roles']['detector'], 4)
        self.assertEqual(config['geometry']['detector_z_mm'], geometry['detector_active_face']['native']['center_mm'][2])

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
