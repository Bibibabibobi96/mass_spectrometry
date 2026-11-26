"""SIMION event conversion preserves frozen mixed-species identities."""
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion.tracking_collection import read_native_events
from msplatform.backends.simion.particle_data import adapt_native_results
from msplatform.results.particle_data import read_particle_data, write_particle_data, summarize_particle_data
from msplatform.physics import CONSTANTS


def source_line(ion, pid, velocity):
    return (f'TRACE: source_release ion={ion} particle_id={pid} instrument_time_us=0 '
            f'x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us={velocity} vy_mm_per_us=0 vz_mm_per_us=0\n')


class SimionParticleDataTests(unittest.TestCase):
    def test_split_publisher_uses_fixture_evidence_and_cold_reads(self):
        # Synthetic native logs: this exercises publication, not a SIMION Fly.
        from msplatform.backends.simion.tracking_execution import _publish_split_particle_data
        from msplatform.io.manifest_records import file_record
        source, collection, _ = self.collected_fixture()
        with TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / 'fixture.exe'
            executable.write_bytes(b'fixture')
            record = file_record(executable, 'solver_native_binary')
            identity = {key: record[key] for key in ('bytes', 'sha256')}
            session = SimpleNamespace(result_dir=root, context=SimpleNamespace(tools={'simion': str(executable)}),
                declare_file=lambda path, role: path, canonical_path=lambda path: path)
            plan = dict(expected_operation_ids=['track_fly'], rows=list(source.values()),
                flight=dict(detector_instance=4), observations=dict(
                observation_times_us=[1.5], plane_observations=[dict(observation_id='d',
                source_instance_id='tof', surface_id='detector')]))
            records = {}
            with patch('msplatform.backends.simion.tracking_execution.windows_binary_version', return_value='fixture-version'):
                result, version = _publish_split_particle_data(session, plan, collection, dict(native_frame_id='world'),
                    dict(drive=dict(clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64,
                                               phase_reference_instrument_time_us=12.))), identity, records)
                with self.assertRaisesRegex(ValueError, 'does not match the tracked native binary'):
                    _publish_split_particle_data(session, plan, collection, dict(native_frame_id='world'),
                        dict(drive=dict(clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64,
                                                   phase_reference_instrument_time_us=12.))),
                        dict(identity, bytes=identity['bytes']+1), {})
            self.assertEqual(version, 'fixture-version')
            self.assertEqual(result.data_integrity['status'], 'complete')
            self.assertEqual(len(records), 5)
            data = read_particle_data(root / 'particle_data')
            self.assertEqual(data['events'][0]['surface_id'], 'detector')
            self.assertEqual([row['particle_id'] for row in data['initial_states']], [91, 7, 103])
            self.assertEqual(len(data['terminal_states']), 3)
            self.assertEqual(data['trajectories']['particle_id'].tolist(), [91, 7, 103])
            self.assertEqual(data['metadata']['clock'], dict(basis='experiment_relative', unit='s',
                clock_epoch_id='epoch', authority_sha256='a'*64))

    @staticmethod
    def collected_fixture():
        source, terminals, taxonomy, raw, samples = {}, [], [], [], []
        for pid, mass, charge, weight in ((91, 100., 1, 2.), (7, 100., 2, 3.), (103, 200., 1, 1.)):
            source[pid] = dict(particle_id=pid, species_id='s' + str(pid), parent_particle_id=None,
                generation=0, mass_amu=mass, charge_state=charge, particle_weight=weight,
                instrument_time_us=1., position_x_mm=0., position_y_mm=0., position_z_mm=0.,
                velocity_x_m_s=1000., velocity_y_m_s=0., velocity_z_m_s=0.)
            start = dict(event='initialize', instrument_time_us=1., x_mm=0., y_mm=0., z_mm=0.,
                         vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0., instance=3, splat=0)
            end = dict(event='terminate', instrument_time_us=2., x_mm=1., y_mm=0., z_mm=0.,
                       vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0., instance=4, splat=1)
            terminals.append(dict(particle_id=pid, **{k: v for k, v in end.items() if k not in {'event','splat'}}))
            taxonomy.append(dict(particle_id=pid, category='detector_crossing' if pid == 91 else 'programmatic_age_stop'))
            raw.append(dict(particle_id=pid, raw=dict(status='recorded_v1', records=[start, end])))
            samples.append(dict(particle_id=pid, instrument_time_us=1.5, x_mm=.5, y_mm=0., z_mm=0.,
                                vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0.))
        plane = dict(particle_id=91, observation_id='d', direction='outward', method='accepted_step_linear_interpolation',
                     instrument_time_us=1.75, x_mm=.75, y_mm=0., z_mm=0., vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0.)
        collection = dict(native_complete=True, native_terminals=terminals,
            census=dict(terminal_taxonomy=dict(particle_outcomes=taxonomy)),
            terminal_evidence=dict(status='recorded_v1', particle_evidence=raw),
            canonical_events=[dict(particle_id=91, event='detector_crossing', instrument_time_us=1.75,
                                   x_mm=.75, y_mm=0., z_mm=0.)],
            native_shared_states=samples, plane_observations=dict(status='complete', rows=[plane]))
        bindings = dict(d=dict(component_id='tof', surface_id='detector', electrode_id=None, kind='detector'))
        return source, collection, bindings

    def test_actual_primary_birth_terminal_and_plane_cold_read(self):
        source, collection, bindings = self.collected_fixture()
        result = adapt_native_results(source, collection, backend_version='SIMION 8.2',
                                      observation_bindings=bindings, observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        self.assertEqual([row['particle_id'] for row in result.initial_states], [91, 7, 103])
        self.assertEqual([row['charge_state'] for row in result.initial_states], [1, 2, 1])
        self.assertEqual(result.events[0]['velocity_m_s'], [1000., 0., 0.])
        self.assertEqual(result.terminal_states[0]['physical_outcome'], 'detected')
        self.assertEqual(result.terminal_states[1]['stop_reason'], 'time_limit')
        self.assertEqual(result.terminal_states[1]['physical_outcome'], 'unknown')
        with TemporaryDirectory() as folder:
            root = Path(folder)
            write_particle_data(root, result, metadata=dict(schema_version=2, initial_state_basis='native_birth_verified',
                frame_id='world', clock=dict(basis='experiment_relative', unit='s')))
            data = read_particle_data(root)
            self.assertEqual(summarize_particle_data(data)['census']['counts']['detected'], 1)
            self.assertEqual(data['initial_states'][1]['weight'], 3.)
            self.assertEqual(data['trajectories']['particle_id'].tolist(), [91, 7, 103])

    def test_zero_hit_and_incomplete_or_contradictory_evidence(self):
        source, collection, bindings = self.collected_fixture()
        collection['census']['terminal_taxonomy']['particle_outcomes'][0]['category'] = 'programmatic_age_stop'
        collection['plane_observations']['rows'] = []
        collection['canonical_events'] = []
        result = adapt_native_results(source, collection, backend_version='SIMION 8.2',
                                      observation_bindings=bindings, observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        self.assertTrue(all(row['physical_outcome'] == 'unknown' for row in result.terminal_states))
        self.assertEqual(result.events, [])
        unobserved = copy.deepcopy(collection)
        unobserved['census']['terminal_taxonomy']['particle_outcomes'][0]['category'] = 'detector_crossing'
        unobserved['canonical_events'] = [dict(particle_id=91, event='detector_crossing', instrument_time_us=1.8,
                                              x_mm=.8, y_mm=0., z_mm=0.)]
        incomplete = adapt_native_results(source, unobserved, backend_version='SIMION 8.2',
            observation_bindings=bindings, observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        self.assertEqual(incomplete.data_integrity['missing_detector_observation_particle_ids'], [91])
        self.assertEqual(incomplete.data_integrity['status'], 'incomplete')
        self.assertEqual(incomplete.terminal_states[0]['physical_outcome'], 'unknown')
        for mutate in (lambda c: c['native_terminals'].pop(),
                       lambda c: c['terminal_evidence']['particle_evidence'][0]['raw']['records'][0].update(x_mm=3.),
                       lambda c: c['native_shared_states'].pop(),
                       lambda c: c['census']['terminal_taxonomy']['particle_outcomes'][0].update(category='detector_crossing')):
            invalid = copy.deepcopy(collection)
            mutate(invalid)
            with self.assertRaises(ValueError):
                adapt_native_results(source, invalid, backend_version='SIMION 8.2',
                                     observation_bindings=bindings, observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)

    def test_event_energy_uses_mass_of_each_original_particle_across_batches(self):
        with TemporaryDirectory() as folder:
            first, second = Path(folder) / 'a.log', Path(folder) / 'b.log'
            first.write_text(source_line(1, 91, 1) + source_line(2, 7, 1), encoding='utf8')
            second.write_text(source_line(1, 103, 1), encoding='utf8')
            events = read_native_events([first, second], {91: 100., 7: 200., 103: 100.},
                                        [91, 7, 103], [2, 1])['rows']
            self.assertEqual([row['particle_id'] for row in events], [91, 7, 103])
            self.assertAlmostEqual(events[1]['kinetic_energy_eV'], 2 * events[0]['kinetic_energy_eV'])
            self.assertAlmostEqual(events[2]['kinetic_energy_eV'], events[0]['kinetic_energy_eV'])
            for invalid in ({91: 100., 7: 200.}, {91: 100., 7: 0., 103: 100.}):
                with self.assertRaises(ValueError):
                    read_native_events([first, second], invalid, [91, 7, 103], [2, 1])

    def test_detector_instance_comes_from_actual_split_binding(self):
        with TemporaryDirectory() as folder:
            log = Path(folder) / 'native.log'
            log.write_text(source_line(1, 91, 1) +
                'TRACE: detector_crossing ion=1 t=2 x=1 y=0 z=0\n', encoding='utf8')
            evidence = read_native_events([log], {91: 100.}, [91], [1], detector_instance=9)
            self.assertEqual(evidence['terminal_outcomes'][91]['instance_id'], 9)
            with self.assertRaises(ValueError):
                read_native_events([log], {91: 100.}, [91], [1], detector_instance=0)


if __name__ == '__main__':
    unittest.main()
