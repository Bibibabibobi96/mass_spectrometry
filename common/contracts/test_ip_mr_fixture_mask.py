"""Synthetic IP–MR scalar validity and report must describe the same bytes."""
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from common.contracts.test_support import ip_mr_sampled_field_fixture as fixture

class SampledFixtureMaskTests(unittest.TestCase):
    def test_mask_matches_report_and_potential_is_unchanged(self):
        class Case:
            projection={'assembly_frame_id':'world'}
            def publish(self,name,kind,data,metadata,**kwargs):
                if kind=='scalar_field_samples': self.samples=data
                return {'fixture':name,'manifest':{'inert':True}}
        case=Case()
        with patch.object(fixture,'open_artifact',return_value=SimpleNamespace(data_path=lambda _:Path('inert.mph'),data_records={'model':{'inert':True}})):
            fixture.sample(case,'carrier',{})
        data=case.samples; potential=data['field_v']; validity=data['field_valid']; report=data['report']
        self.assertEqual(potential[:56],validity[:56])
        self.assertEqual(potential[56:],bytes(27*8))
        values=struct.unpack('<27d',validity[56:])
        self.assertEqual(values,(1.,)*27)
        self.assertEqual(sum(v==1. for v in values),report['fem_valid'])
        self.assertEqual(sum(v==0. for v in values),report['invalid_count'])

if __name__=='__main__': unittest.main()
