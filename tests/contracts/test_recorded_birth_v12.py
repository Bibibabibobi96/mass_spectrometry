"""Versioned recorded birth history remains read-only."""
import json
import unittest
from msplatform.results.historical_flight import decode_flight_request


class RecordedBirthV12Tests(unittest.TestCase):
    def test_historical_without_species_is_not_a_new_release_request(self):
        from msplatform.recipes.native import _validate_birth_request
        record = {'path': 'source', 'bytes': 0, 'sha256': '0'*64}
        request = {'schema_version': 12, 'role': 'split_oa_tof_recorded_birth_preparation_request',
            'fields_reference': {'manifest': record, 'product_id': 'fields'},
            'source': {'kind': 'recorded_birth', 'instance_id': 'oa', 'frame_id': 'world',
                'species_id': 'legacy', 'particle_ids': [1], 'particle_source': record, 'metadata': record,
                'clock_authority': record, 'instrument_epoch': record, 'instrument_origin_us': 0},
            'propagation': {}, 'numerics': {}}
        self.assertEqual(decode_flight_request(json.dumps(request).encode()), request)
        with self.assertRaises(ValueError):
            _validate_birth_request(request)
