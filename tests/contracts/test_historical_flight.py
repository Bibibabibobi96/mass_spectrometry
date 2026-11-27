"""Historical requests decode without restoring their former producer."""
import json
import hashlib
from pathlib import Path
import unittest

from msplatform.results.historical_flight import decode_flight_request


class HistoricalFlightTests(unittest.TestCase):
    def test_archived_schema_bytes_remain_exact(self):
        import msplatform.results.historical_flight as reader
        root = Path(reader.__file__).with_name('historical_schemas')
        expected = {9: 'F734696E6D5C6A774BEC076EFD424C3CA1D388956AF0B1B3BAF8944D365B4158',
                    10: 'D8DAF61C9A66D6A3A44E13AB22580159773C54750FF14B8306C73E302AA86B69',
                    11: '3B4A980B4CF76EF13CA0CEB2418D5896BE23B895DE52370B96AD1B50080676C1',
                    12: '9DCA4BB9788ADEDF7E12358D0FD0879B582845D8F11458184CD426471242CFAE'}
        for version, digest in expected.items():
            with self.subTest(version=version):
                self.assertEqual(hashlib.sha256((root / f'flight_request_v{version}.schema.json').read_bytes()).hexdigest().upper(), digest)

    def test_versions9_to_11_decode_without_opening_referenced_files(self):
        root = Path(__file__).with_name('fixtures')
        for version in (9, 10, 11):
            data = (root / f'historical_flight_request_v{version}.json').read_bytes()
            with self.subTest(version=version):
                decoded = decode_flight_request(data)
                self.assertEqual(decoded['schema_version'], version)
                self.assertEqual(decoded, json.loads(data))
        invalid = json.loads((root / 'historical_flight_request_v10.json').read_bytes())
        invalid['providers']['instances']['multipole']['electrode_bindings']['rod_group_1'] = 1.0
        with self.assertRaises(ValueError):
            decode_flight_request(json.dumps(invalid).encode())

    def test_version12_preserves_original_request_and_never_infers_species(self):
        record = {"path": "historical", "bytes": 0, "sha256": "0" * 64}
        source = {"kind": "recorded_birth", "instance_id": "oa", "frame_id": "world",
                  "species_id": "legacy", "particle_ids": [1], "particle_source": record,
                  "metadata": record, "clock_authority": record, "instrument_epoch": record,
                  "instrument_origin_us": 0.0}
        original = {"schema_version": 12, "role": "split_oa_tof_recorded_birth_preparation_request",
                    "fields_reference": {"manifest": record, "product_id": "fields"},
                    "source": source, "propagation": {}, "numerics": {}}
        self.assertEqual(decode_flight_request(json.dumps(original).encode()), original)
        self.assertNotIn("species_kind", decode_flight_request(json.dumps(original).encode())["source"])
        original["schema_version"] = 13
        with self.assertRaisesRegex(ValueError, "unsupported historical"):
            decode_flight_request(json.dumps(original).encode())
        original["schema_version"] = 12
        original["source"]["particle_ids"] = [1, 1]
        with self.assertRaises(ValueError):
            decode_flight_request(json.dumps(original).encode())
