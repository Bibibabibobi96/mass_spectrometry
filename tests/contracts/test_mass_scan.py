"""Software-only mass scan contracts; no native Fly is claimed."""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from tests.particle_release.test_mt19937_disk_cone_rf_phase import _spec
from tests.contracts import test_simion_particle_data as particle_fixture
from msplatform.backends.simion.particle_data import adapt_native_results
from msplatform.physics import CONSTANTS
from tests.contracts.test_support.species import fixture_ion_species
from msplatform.results.particle_data import read_particle_data, write_particle_data
from msplatform.workflows.mass_scan import prepare_mass_scan, merge_mass_scan, analyze_mass_scan


def request(name, n, charge=1):
    spec = _spec(n)
    spec['species']['mass_amu'] = 100.
    spec['species']['charge_state'] = charge
    return dict(schema_version=1, role='canonical_birth_source_request', release_spec=spec,
        clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64), instrument_origin_us=0.,
        species_id=name, source_component_id='rf', relative_weights=None)


def scan(*rows):
    return dict(schema_version=1, role='canonical_mass_scan_request', species_requests=list(rows))


class MassScanTests(unittest.TestCase):
    def test_one_hit_and_zero_hit_remain_publishable(self):
        source, collection, bindings = particle_fixture.SimionParticleDataTests.collected_fixture()
        batch = adapt_native_results(source, collection, backend_version='fixture', observation_bindings=bindings,
            observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        merged = merge_mass_scan([batch])
        with TemporaryDirectory() as folder:
            root = Path(folder)
            write_particle_data(root, merged, metadata=dict(schema_version=2, initial_state_basis='native_birth_verified',
                frame_id='world', clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64), species=fixture_ion_species(merged.initial_states)))
            data = read_particle_data(root)
            analysis = analyze_mass_scan(data)
        self.assertEqual([row['detected_count'] for row in analysis['species']], [1, 0, 0])
        self.assertTrue(all(row['peak_analysis']['status'] == 'not_applicable' for row in analysis['species']))
        self.assertEqual(analysis['calibration_analysis']['status'], 'not_applicable')

    def test_mixed_detector_capabilities_are_per_species_and_survive_roundtrip(self):
        from msplatform.results.detector_observation import detector_observation
        source, collection, bindings = particle_fixture.SimionParticleDataTests.collected_fixture()
        batch = adapt_native_results(source, collection, backend_version='fixture', observation_bindings=bindings,
            observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        results = []
        for index, row in enumerate(batch.initial_states):
            ids = {row['particle_id']}
            part = copy.deepcopy(batch)
            part.initial_states = [row]
            part.terminal_states = [item for item in batch.terminal_states if item['particle_id'] in ids]
            part.events = [item for item in batch.events if item['particle_id'] in ids]
            mask = np.isin(batch.trajectories['particle_id'], list(ids))
            part.trajectories = {key: value[mask] for key, value in batch.trajectories.items()}
            part.data_integrity['detector_observation'] = detector_observation(
                'complete' if index == 0 else 'unavailable', list(ids),
                reason=None if index == 0 else 'detector_observation_unsupported')
            results.append(part)
        merged = merge_mass_scan(results)
        with TemporaryDirectory() as folder:
            root = Path(folder)
            write_particle_data(root, merged, metadata=dict(schema_version=2, initial_state_basis='native_birth_verified',
                frame_id='world', clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64), species=fixture_ion_species(merged.initial_states)))
            data = read_particle_data(root)
            analysis = analyze_mass_scan(data)
        self.assertEqual(analysis['summary']['detector_observation']['status'], 'unavailable')
        self.assertIsNone(analysis['summary']['detection_efficiency'])
        self.assertEqual(analysis['species'][0]['detected_count'], 1)
        self.assertIsNone(analysis['species'][1]['detection_fraction'])
        self.assertEqual(analysis['species'][1]['peak_analysis']['status'], 'unavailable')
        self.assertEqual(analysis['calibration_analysis']['status'], 'unavailable')

    def test_unknown_terminals_without_detector_capability_are_not_zero_hits(self):
        from msplatform.results.detector_observation import detector_observation
        source, collection, bindings = particle_fixture.SimionParticleDataTests.collected_fixture()
        batch = adapt_native_results(source, collection, backend_version='fixture', observation_bindings=bindings,
            observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        for row in batch.terminal_states:
            row['physical_outcome'] = 'unknown'
            row['stop_reason'] = 'time_limit'
        batch.events = []
        batch.data_integrity['detector_observation'] = detector_observation('unavailable',
            [row['particle_id'] for row in batch.initial_states], reason='detector_observation_unsupported')
        result = merge_mass_scan([batch])
        data = dict(initial_states=result.initial_states, terminal_states=result.terminal_states, events=result.events,
                    trajectories=result.trajectories, execution_status=result.execution_status, data_integrity=result.data_integrity)
        analysis = analyze_mass_scan(data)
        self.assertIsNone(analysis['summary']['detection_efficiency'])
        self.assertEqual(analysis['summary']['arrival_analysis']['status'], 'unavailable')
        self.assertTrue(all(item['detection_fraction'] is None for item in analysis['species']))
        self.assertTrue(all(item['peak_analysis']['status'] == 'unavailable' for item in analysis['species']))
        self.assertEqual(analysis['calibration_analysis']['status'], 'unavailable')

    def test_comsol_unknown_detector_is_unavailable_after_publication(self):
        import csv
        from msplatform.backends.comsol.particle_data import read_observations
        from tests.contracts.test_comsol_particle_tracing import COLUMNS
        source = [{'particle_id': 9, 'species_id': 'ion', 'time_s': 0.0,
                   'position_m': [.001, .002, .003], 'velocity_m_s': [1., 2., 3.],
                   'mass_kg': 1e-25, 'charge_state': 1, 'charge_c': 1.602176634e-19,
                   'weight': 1., 'parent_particle_id': None, 'lineage_status': 'primary_birth'}]
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'native.csv'
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(COLUMNS)
                writer.writerow([9, 1, 10, 1, 2, 3, 1, 2, 3, 1, 1, 'nan'])
                writer.writerow([9, 1, 12, 1.2, 2, 3, 1, 2, 3, 1, 1, 11])
            result = read_observations(path, initial_states=source, epoch_us=10, backend_version='COMSOL 6.4',
                observation_times_us=[10, 12], position_atol_m=1e-12, velocity_atol_m_s=1e-9,
                boundary_policy='metal_and_outer_freeze_ideal_pass')
            merged = merge_mass_scan([result])
            write_particle_data(root, merged, metadata=dict(schema_version=2, initial_state_basis='native_birth_verified',
                frame_id='world', clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64), species=fixture_ion_species(merged.initial_states)))
            analysis = analyze_mass_scan(read_particle_data(root))
        self.assertEqual(analysis['summary']['census']['counts']['unknown'], 1)
        self.assertIsNone(analysis['summary']['detection_efficiency'])
        self.assertIsNone(analysis['species'][0]['detection_fraction'])
        self.assertEqual(analysis['calibration_analysis']['status'], 'unavailable')

    def test_native_success_cache_requires_complete_detector_observation(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.workflows.native_tracing import _complete_trajectory
        artifact = SimpleNamespace(kind='trajectory_result', data_path=lambda name: Path('execution.json'))
        with patch('msplatform.workflows.native_tracing.read_particle_data') as read:
            for status in ('unavailable', 'not_requested', 'incomplete', None):
                read.return_value = {'execution_status': 'succeeded', 'metadata': {'species': [{'species_id': 'fixture'}]}, 'data_integrity': {
                    'status': 'complete', 'detector_observation': {'status': status}}}
                self.assertFalse(_complete_trajectory(artifact))
            read.return_value['data_integrity']['detector_observation']['status'] = 'complete'
            self.assertTrue(_complete_trajectory(artifact))

    def test_missing_requested_detector_records_are_incomplete(self):
        source, collection, bindings = particle_fixture.SimionParticleDataTests.collected_fixture()
        del collection['plane_observations']
        batch = adapt_native_results(source, collection, backend_version='fixture', observation_bindings=bindings,
            observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        self.assertEqual(batch.data_integrity['status'], 'incomplete')
        self.assertEqual(batch.data_integrity['detector_observation']['status'], 'incomplete')
        with self.assertRaises(ValueError):
            merge_mass_scan([batch])

    def test_canonical_sampler_preserves_species_counts_charge_weights_and_ids(self):
        one = prepare_mass_scan(scan(request('one', 1)))
        self.assertEqual(len(one[0].rows), 1)
        first, second = request('a', 2), request('b', 3, 2)
        first['relative_weights'] = {'1': .5, '2': 2.}
        second['particle_ids'] = [1, 9, 12]
        batches = prepare_mass_scan(scan(first, second))
        rows = [row for batch in batches for row in batch.rows]
        self.assertEqual([r['particle_id'] for r in rows], [2,3,1,9,12])
        self.assertEqual([r['particle_weight'] for r in rows[:2]], [.5,2.])
        self.assertEqual({r['mass_amu'] for r in rows}, {100.})
        self.assertEqual([r['charge_state'] for r in rows], [1,1,2,2,2])
        self.assertEqual([r['species_id'] for r in rows], ['a','a','b','b','b'])
        self.assertEqual(batches[0].to_dict()['rows'], prepare_mass_scan(scan(first, second))[0].rows)

    def test_rejects_duplicate_ids_species_and_clock(self):
        a, b = request('a', 2), request('b', 1)
        a['particle_ids'] = [8,9]
        b['particle_ids'] = [9]
        with self.assertRaises(ValueError): prepare_mass_scan(scan(a,b))
        b = request('a', 1)
        with self.assertRaises(ValueError): prepare_mass_scan(scan(a,b))
        b = request('b', 1)
        b['clock']['clock_epoch_id'] = 'other'
        with self.assertRaises(ValueError): prepare_mass_scan(scan(a,b))

    def test_null_ids_allocate_globally_and_validate_local_weights(self):
        a, b = request('a', 2), request('b', 2, 2)
        a['particle_ids'] = None
        self.assertEqual([r['particle_id'] for r in prepare_mass_scan(scan(a))[0].rows], [1, 2])
        b['particle_ids'] = None
        b['relative_weights'] = {'1': 2., '2': 4.}
        batches = prepare_mass_scan(scan(a, b))
        self.assertEqual([[r['particle_id'] for r in batch.rows] for batch in batches], [[1, 2], [3, 4]])
        self.assertEqual([r['particle_weight'] for r in batches[1].rows], [2., 4.])
        b['relative_weights'] = {'1': 2., '3': 4.}
        with self.assertRaisesRegex(ValueError, 'weights'):
            prepare_mass_scan(scan(a, b))

    def test_zero_hit_and_incomplete_census_are_distinct(self):
        source, collection, bindings = particle_fixture.SimionParticleDataTests.collected_fixture()
        collection['census']['terminal_taxonomy']['particle_outcomes'][0]['category'] = 'programmatic_age_stop'
        collection['plane_observations']['rows'] = []
        collection['canonical_events'] = []
        batch = adapt_native_results(source, collection, backend_version='fixture', observation_bindings=bindings,
            observation_times_us=[1.5], constants=CONSTANTS, detector_instance=4)
        result = merge_mass_scan([batch])
        data = dict(initial_states=result.initial_states, terminal_states=result.terminal_states, events=result.events,
                    trajectories=result.trajectories, execution_status=result.execution_status, data_integrity=result.data_integrity)
        analysis = analyze_mass_scan(data)
        self.assertTrue(all(row['detection_fraction'] == 0 for row in analysis['species']))
        self.assertEqual(analysis['calibration_analysis']['status'], 'not_applicable')
        partitions = []
        for ids in ({91}, {7, 103}):
            part = copy.deepcopy(batch)
            part.initial_states = [r for r in part.initial_states if r['particle_id'] in ids]
            part.terminal_states = [r for r in part.terminal_states if r['particle_id'] in ids]
            part.data_integrity['detector_observation']['cohort_particle_ids'] = [r['particle_id'] for r in part.initial_states]
            mask = np.isin(part.trajectories['particle_id'], list(ids))
            part.trajectories = {k: v[mask] for k, v in part.trajectories.items()}
            partitions.append(part)
        joined = merge_mass_scan(partitions)
        self.assertEqual(joined.initial_states, result.initial_states)
        self.assertEqual(joined.terminal_states, result.terminal_states)
        np.testing.assert_array_equal(joined.trajectories['particle_id'], result.trajectories['particle_id'])
        with self.assertRaises(ValueError): merge_mass_scan([batch, batch])
        missing = copy.deepcopy(batch)
        missing.terminal_states.pop()
        with self.assertRaises(ValueError): merge_mass_scan([missing])
        incomplete = copy.deepcopy(batch)
        incomplete.data_integrity['status'] = 'incomplete'
        with self.assertRaises(ValueError): merge_mass_scan([incomplete])


if __name__ == '__main__':
    unittest.main()
