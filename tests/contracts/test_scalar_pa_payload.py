"""Scalar PA finalization uses the installed shared format authority."""
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.simion.scalar_pa_payload import finalize_scalar_pair
from msplatform.backends.simion.collision_overlay import collision_pa_header, COLLISION_NOTREFINABLE_FLAG
from msplatform.backends.simion.standalone_pa_composition import HEADER, PaHeader


class ScalarPaPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.v=self.root/'v.pa';self.mask=self.root/'mask.pa'
        self.grid={'dimensions':[3,4,5],'pitch_mm':[.25,.5,1.5],'point_count':60}

    def raw(self,values,mask):
        self.v.write_bytes(bytes(HEADER.size)+b''.join(struct.pack('<d',v) for v in values))
        self.mask.write_bytes(bytes(HEADER.size)+b''.join(struct.pack('<d',v) for v in mask))

    def test_exact_shared_header_x_fastest_and_signed_zero(self):
        values=[float(i-30) for i in range(60)];values[0]=-0.0;valid=[float(i%2) for i in range(60)]
        self.raw(values,valid);before_v=self.v.read_bytes()[HEADER.size:];before_mask=self.mask.read_bytes()[HEADER.size:]
        finalize_scalar_pair(self.v,self.mask,self.grid)
        expected=PaHeader(-2,1,29.0,3,4,5,COLLISION_NOTREFINABLE_FLAG,.25,.5,1.5)
        self.assertEqual(self.v.read_bytes()[:HEADER.size],expected.pack());self.assertEqual(collision_pa_header(self.v),expected)
        self.assertEqual(self.v.read_bytes()[HEADER.size:],before_v);self.assertEqual(self.mask.read_bytes()[HEADER.size:],before_mask)
        self.assertEqual(struct.unpack_from('<Q',self.v.read_bytes(),HEADER.size)[0],1<<63)
        self.assertEqual(collision_pa_header(self.mask).max_voltage,1.0)

    def test_two_z_planes_preserve_existing_grid_contract(self):
        self.grid={'dimensions':[3,3,2],'pitch_mm':[1,1,1],'point_count':18}
        values=[float(i) for i in range(18)]
        self.raw(values,[1.0]*18)
        expected=self.v.read_bytes()[HEADER.size:]
        finalize_scalar_pair(self.v,self.mask,self.grid)
        self.assertEqual(collision_pa_header(self.v).nz,2)
        self.assertEqual(self.v.read_bytes()[HEADER.size:],expected)
        self.assertEqual(collision_pa_header(self.mask).nz,2)

    def test_zero_values_choose_positive_header_maximum(self):
        self.raw([0.0]*60,[0.0]*60);finalize_scalar_pair(self.v,self.mask,self.grid)
        self.assertEqual(collision_pa_header(self.v).max_voltage,1.0)

    def test_invalid_payloads_refuse_without_any_header_change(self):
        for failure in ('nonfinite','bad_mask','truncated','trailing','already_finalized','bad_grid'):
            with self.subTest(failure=failure):
                values=[0.0]*60;mask=[1.0]*60
                if failure=='nonfinite':values[-1]=math.nan
                if failure=='bad_mask':mask[-1]=.5
                self.raw(values,mask)
                if failure=='truncated':self.mask.write_bytes(self.mask.read_bytes()[:-1])
                if failure=='trailing':self.mask.write_bytes(self.mask.read_bytes()+b'x')
                if failure=='already_finalized':self.v.write_bytes(b'X'+self.v.read_bytes()[1:])
                grid=dict(self.grid)
                if failure=='bad_grid':grid['point_count']=59
                before=(self.v.read_bytes(),self.mask.read_bytes())
                with self.assertRaises(ValueError):finalize_scalar_pair(self.v,self.mask,grid)
                self.assertEqual((self.v.read_bytes(),self.mask.read_bytes()),before)

    def test_write_error_preserves_original_exception_and_unmodified_second_header(self):
        self.raw([0.0]*60,[1.0]*60);failure=OSError('synthetic encoder write failure')
        with patch.object(PaHeader,'pack',side_effect=failure):
            with self.assertRaises(OSError) as caught:finalize_scalar_pair(self.v,self.mask,self.grid)
        self.assertIs(caught.exception,failure);self.assertEqual(self.mask.read_bytes()[:HEADER.size],bytes(HEADER.size))

    def test_multigrid_later_failure_does_not_hide_completed_first_or_change_bad_pair(self):
        self.raw([2.0]*60,[1.0]*60);finalize_scalar_pair(self.v,self.mask,self.grid);first=self.v.read_bytes()
        other=self.root/'other';other.mkdir();p=other/'v.pa';m=other/'mask.pa';p.write_bytes(bytes(HEADER.size)+struct.pack('<60d',*([3.0]*60)));m.write_bytes(bytes(HEADER.size)+struct.pack('<60d',*([2.0]*60)))
        with self.assertRaisesRegex(ValueError,'zero or one'):finalize_scalar_pair(p,m,self.grid)
        self.assertEqual(self.v.read_bytes(),first);self.assertEqual(p.read_bytes()[:HEADER.size],bytes(HEADER.size))
