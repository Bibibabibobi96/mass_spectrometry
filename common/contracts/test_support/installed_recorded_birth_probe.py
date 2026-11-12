"""Installed recorded-birth consumer of the actual prepared SFI source."""
import csv
import json
from pathlib import Path
from unittest.mock import patch


def run(preparation, run_directory, expected_ids, arm, timer):
    """Check one installed recorded-birth arm without generating or flying ions."""
    from msplatform.contracts.clock import ClockIdentity
    from msplatform.ion_release import load_recorded_release

    with timer('recorded_birth', str(arm)):
        inputs = Path(run_directory) / 'inputs'
        request = json.loads((inputs / 'request.json').read_text(encoding='utf-8-sig'))
        provenance = json.loads((inputs / 'source_provenance.json').read_text(encoding='utf-8-sig'))
        assert request['source']['kind'] == provenance['source_kind'] == 'recorded_birth'
        assert provenance['population_policy'] == 'complete_original_source_no_selection_no_resampling'
        assert provenance['state_time_semantics'] == 'original_birth_time_s_times_1e6_no_epoch_shift'
        record = preparation['input_records']['particle_source']
        assert record == provenance['input_records']['particle_source']
        source = Path(record['path'])
        assert source == inputs / 'particle_source.csv'
        before = source.read_bytes()
        with source.open(encoding='utf-8-sig', newline='') as stream:
            original = list(csv.DictReader(stream))
        ids = [int(value) for value in expected_ids]
        assert [int(row['particle_id']) for row in original] == ids
        epoch = preparation['input_records']['instrument_epoch']
        assert epoch == provenance['input_records']['instrument_epoch']
        clock = ClockIdentity(provenance['clock_epoch_id'], epoch['sha256'])
        assert provenance['instrument_epoch_us'] == 0.0
        with patch('msplatform.ion_release.authoring.generate_release_states',
                   side_effect=AssertionError('recorded source must not resample')):
            packet = load_recorded_release(record, clock=clock, frame_id=request['source']['frame_id'],
                source_component_id=request['source']['instance_id'], species_id='installed_fixture_species',
                relative_weights=None, instrument_origin_us=0.0, expected_particle_ids=ids)
        assert packet['role'] == 'canonical_recorded_birth_realization'
        assert packet['recorded_source']['record'] == record
        assert packet['clock'] == {'clock_epoch_id': clock.clock_epoch_id, 'authority_sha256': clock.authority_sha256}
        assert list(packet['mother']['records']) == ids
        assert packet['mother']['fates'] == [{'particle_id': pid, 'status': 'not_propagated'} for pid in ids]
        for raw, row in zip(original, packet['rows'], strict=True):
            assert row['particle_id'] == int(raw['particle_id'])
            assert row['particle_birth_time_us'] == float(raw['birth_time_s']) * 1e6
            assert row['instrument_time_us'] == row['particle_birth_time_us']
            assert row['mass_amu'] == float(raw['mass_amu'])
            assert row['charge_state'] == int(raw['charge_state'])
            assert row['particle_weight'] == 1.0
            assert row['frame_id'] == request['source']['frame_id']
            assert row['source_component_id'] == request['source']['instance_id']
            for axis in 'xyz':
                assert row['position_' + axis + '_mm'] == float(raw[axis + '_mm'])
                assert row['velocity_' + axis + '_m_s'] == float(raw['v' + axis + '_m_s'])
            assert packet['mother']['records'][row['particle_id']]['particle_birth_time_us'] == row['particle_birth_time_us']
        assert source.read_bytes() == before
        assert not (Path(run_directory) / 'simion').exists()
