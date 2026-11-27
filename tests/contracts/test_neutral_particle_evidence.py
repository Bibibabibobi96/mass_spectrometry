"""Software-only neutral native evidence; no SIMION Fly is claimed."""
import copy
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs


class NeutralEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(Path('C:/Program Files/SIMION-2020/lua.exe').is_file(), 'standalone Lua unavailable')
    def test_actual_lua_committed_callbacks_emit_auditable_selected_sample(self):
        # Real shared callback source with API doubles; no FieldBundle or vendor Fly.
        runtime = Path('src/msplatform/backends/simion/resources/rf_tracking.lua').read_text(encoding='utf-8')
        prefix = r"""
segment={};local rf_committed_observations=true;local rf_static_operating=true
local rf_trajectory_quality=8;local rf_grouped=0;local rf_step_cap_us=.1
local rf_initial_velocities={{1,0,0}};local single_flight_time_origin_us={0}
local single_flight_absolute_deadline_us={5};local rf_observation_times={0,1}
function single_flight_source_row_index() return 1 end
function single_flight_canonical_particle_id() return 7 end
function single_flight_instrument_time_us() return ion_time_of_flight end
function single_flight_restore_source_velocity(_) end
ion_number=1;ion_instance=1;ion_time_of_flight=0;ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0
ion_vx_mm=1;ion_vy_mm=0;ion_vz_mm=0;ion_mass=100;ion_charge=1;ion_splat=0
"""
        suffix = r"""
segment.initialize_run();segment.initialize()
ion_time_of_flight=.5;ion_px_mm=.5;segment.other_actions()
ion_time_of_flight=1.5;ion_px_mm=1.5;segment.other_actions()
ion_time_of_flight=2;ion_px_mm=2;segment.terminate()
print('status,Fly completed. 1 splats')
"""
        with TemporaryDirectory() as directory:
            script = Path(directory) / 'callbacks.lua'
            script.write_text(prefix + runtime + suffix, encoding='utf-8')
            run = subprocess.run(['C:/Program Files/SIMION-2020/lua.exe', str(script)],
                                 cwd=directory, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            log = Path(directory) / 'callbacks.log'; log.write_text(run.stdout, encoding='utf-8')
            source = dict(particle_id=7, instrument_time_us=0., mass_amu=100., charge_state=1,
                position_x_mm=0., position_y_mm=0., position_z_mm=0.,
                velocity_x_m_s=1000., velocity_y_m_s=0., velocity_z_m_s=0.)
            provenance = dict(state_kind='source_birth', execution_particle_ids=[7], mother_particle_ids=[7],
                mother_records=[dict(particle_id=7, particle_birth_time_us=0.)], mother_fates=[],
                clock_authority_sha256='a'*64, clock_records={})
            batch = dict(source_row_range=[1, 1], expected_particle_ids=[7], build_metadata=dict(
                source_clock=dict(original_birth_times_us=[0.], absolute_deadlines_us=[5.]),
                plane_observations=[], propagation_stop=None, consumed_plane_events=[]))
            result = collect_rf_tracking_logs([log], source_rows={7: source}, source_provenance=provenance,
                flight=dict(tracking_kind='neutral_sampled', grouped=0, observation_times_us=[0., 1.]), batches=[batch])
            self.assertTrue(result['observation_complete'])
            self.assertEqual([(row['instrument_time_us'], row['x_mm'], row['reason']) for row in result['native_shared_states']],
                             [(0., 0., 'actual_birth'), (1., 1., 'accepted_step_linear_interpolation')])
            ip_mr = collect_rf_tracking_logs([log], source_rows={7: source}, source_provenance=provenance,
                flight=dict(tracking_kind='ip_mr', grouped=0, observation_times_us=[0., 1.]), batches=[batch])
            self.assertTrue(ip_mr['observation_complete'])
            tampered = []
            for line in run.stdout.splitlines():
                if line.startswith('RF_NATIVE_STATE_V1: '):
                    payload = json.loads(line.split(': ', 1)[1])
                    if payload['event'] == 'shared' and payload['reason'] == 'actual_birth':
                        payload['x_mm'] = .25
                        line = 'RF_NATIVE_STATE_V1: ' + json.dumps(payload)
                tampered.append(line)
            log.write_text('\n'.join(tampered)+'\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'actual birth observation differs'):
                collect_rf_tracking_logs([log], source_rows={7: source}, source_provenance=provenance,
                    flight=dict(tracking_kind='neutral_sampled', grouped=0, observation_times_us=[0., 1.]), batches=[batch])

    def test_complete_original_birth_and_incomplete_observation_are_distinct(self):
        source = dict(particle_id=7, instrument_time_us=0., mass_amu=100., charge_state=1,
                      position_x_mm=0., position_y_mm=0., position_z_mm=0.,
                      velocity_x_m_s=1000., velocity_y_m_s=0., velocity_z_m_s=0.)
        mother = dict(particle_id=7, particle_birth_time_us=0.)
        provenance = dict(state_kind='source_birth', execution_particle_ids=[7], mother_particle_ids=[7],
                          mother_records=[mother], mother_fates=[], clock_authority_sha256='a'*64,
                          clock_records={})
        batch = dict(source_row_range=[1, 1], expected_particle_ids=[7], build_metadata=dict(
            source_clock=dict(original_birth_times_us=[0.], absolute_deadlines_us=[5.]),
            plane_observations=[], propagation_stop=None, consumed_plane_events=[]))
        flight = dict(tracking_kind='neutral_sampled', grouped=0, observation_times_us=[1.])
        state = dict(event='source_release', reason='none', particle_id=7, ion=1, instrument_time_us=0.,
                     x_mm=0., y_mm=0., z_mm=0., vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0.,
                     mass_amu=100., charge_state=1, instance=1)
        shared = dict(state, event='shared', reason='accepted_step_linear_interpolation',
                      instrument_time_us=1., x_mm=1.)
        terminal = dict(state, event='terminal', reason='unknown', instrument_time_us=2., x_mm=2.)
        controls = 'RF_DYNAMICS_V1: ' + json.dumps(dict(grouped=0, repulsion='none', relativity=0, segment_global=1))
        wire = lambda row: 'RF_NATIVE_STATE_V1: ' + json.dumps(row)
        lines = [controls, wire(state), wire(shared), wire(terminal), 'status,Fly completed. 1 splats']
        with TemporaryDirectory() as directory:
            log = Path(directory) / 'native-fixture.log'
            log.write_text('\n'.join(lines)+'\n', encoding='utf-8')
            args = dict(source_rows={7: source}, source_provenance=provenance, flight=flight, batches=[batch])
            result = collect_rf_tracking_logs([log], **args)
            self.assertTrue(result['observation_complete'])
            self.assertEqual(len(result['native_shared_states']), 1)
            marker = 'RF_OBSERVATION_INCOMPLETE_V1: ion=1 particle_id=7 reason=terminal_before_retained_history'
            log.write_text('\n'.join([*lines[:3], marker, *lines[3:]])+'\n', encoding='utf-8')
            incomplete = collect_rf_tracking_logs([log], **args)
            self.assertFalse(incomplete['observation_complete'])
            self.assertEqual(incomplete['native_shared_states'], [])
            bad = copy.deepcopy(provenance); bad['state_kind'] = 'handoff'
            with self.assertRaisesRegex(ValueError, 'original birth cohort'):
                collect_rf_tracking_logs([log], **dict(args, source_provenance=bad))
