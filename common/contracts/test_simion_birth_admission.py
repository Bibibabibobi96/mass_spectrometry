"""Canonical birth admission before geometry or native work."""
import copy
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.ion_release.test_mt19937_disk_cone_rf_phase import _spec
from msplatform import examples, ion_release
from msplatform.assembly.handoff import HandoffMother
from msplatform.backends.simion.tracking_execution import validate_birth_source
from msplatform.contracts.clock import ClockIdentity
from msplatform.io.manifest_records import file_record
from msplatform.ion_release.authoring import load_recorded_release
from msplatform.ion_release.cylinder import CANONICAL_COLUMNS
from msplatform.ion_release.release import generate_release_states


class BirthAdmissionTests(unittest.TestCase):
    def test_generated_complete_cohort_is_preserved_without_resampling(self):
        packet=ion_release.sample_release(examples.load_example('rf_oatof_functional_v1').release).to_dict()
        before=copy.deepcopy(packet)
        with patch('msplatform.ion_release.authoring.generate_release_states',side_effect=AssertionError('resampled')):
            rows,mother,clock=validate_birth_source(packet)
        self.assertEqual(packet,before)
        self.assertEqual(rows,packet['rows'])
        self.assertEqual([r['particle_id'] for r in rows],list(mother.records))
        self.assertIsInstance(mother,HandoffMother)
        self.assertEqual(clock,ClockIdentity(**packet['clock']))
        self.assertEqual(mother.fates,packet['mother']['fates'])
        rows[0]['particle_id']=-1
        self.assertEqual(packet,before)

    def test_recorded_sparse_births_validate_source_identity_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'birth.csv';generated=generate_release_states(_spec(3));ids=[11,1009,2**60+1]
            for row,pid in zip(generated,ids,strict=True):row['particle_id']=pid
            with path.open('w',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=CANONICAL_COLUMNS,extrasaction='ignore',lineterminator='\n');writer.writeheader();writer.writerows(generated)
            packet=load_recorded_release(file_record(path),clock=ClockIdentity('explicit-clock','a'*64),frame_id=_spec(3)['frame_id'],source_component_id='rf',species_id='declared',relative_weights={11:.5,1009:2.,ids[2]:3.},instrument_origin_us=12.5,expected_particle_ids=ids)
            before=copy.deepcopy(packet)
            with patch('msplatform.ion_release.authoring.generate_release_states',side_effect=AssertionError('resampled')):
                rows,mother,clock=validate_birth_source(packet)
            self.assertEqual(packet,before);self.assertEqual([row['particle_id'] for row in rows],ids)
            self.assertEqual(list(mother.records),ids);self.assertEqual(clock,ClockIdentity(**packet['clock']))
            bad=copy.deepcopy(packet);bad['rows'][0]['position_x_mm']+=1
            with self.assertRaisesRegex(ValueError,'differs from its bound source'):validate_birth_source(bad)
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaises(AssertionError):validate_birth_source(packet)

    def test_generated_malformed_rows_mother_role_and_clock_fail_closed(self):
        packet=ion_release.sample_release(examples.load_example('rf_oatof_functional_v1').release).to_dict()
        cases=[]
        bad=copy.deepcopy(packet);bad['rows'][0]['particle_id']=bad['rows'][1]['particle_id'];cases.append(bad)
        bad=copy.deepcopy(packet);bad['mother']['records'].pop(next(iter(bad['mother']['records'])));cases.append(bad)
        bad=copy.deepcopy(packet);bad['role']='untrusted';cases.append(bad)
        bad=copy.deepcopy(packet);bad['clock']['authority_sha256']='not-a-sha';cases.append(bad)
        for bad in cases:
            with self.subTest(case=len(str(bad))),self.assertRaises((ValueError,TypeError)):validate_birth_source(bad)
