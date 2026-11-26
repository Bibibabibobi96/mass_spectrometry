"""Software-only mass scan contracts; no native Fly is claimed."""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from tests.ion_release.test_mt19937_disk_cone_rf_phase import _spec
from tests.contracts import test_simion_particle_data as particle_fixture
from msplatform.backends.simion.particle_data import adapt_native_results
from msplatform.physics import CONSTANTS
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
                frame_id='world', clock=dict(clock_epoch_id='epoch', authority_sha256='a'*64)))
            data = read_particle_data(root)
            analysis = analyze_mass_scan(data)
        self.assertEqual([row['detected_count'] for row in analysis['species']], [1, 0, 0])
        self.assertTrue(all(row['peak_analysis']['status'] == 'not_applicable' for row in analysis['species']))
        self.assertEqual(analysis['calibration_analysis']['status'], 'not_applicable')

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
