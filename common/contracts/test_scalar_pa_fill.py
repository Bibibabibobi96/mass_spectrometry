import copy
from pathlib import Path
import struct
import tempfile
import unittest
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.backends.comsol.assembly_scalar_fill import fill_invalid_scalar_pa
from common.contracts.test_assembly_scalar_fill import fixture

class PaFillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.projection,self.request,self.grid=fixture()
        self.header=PaHeader(-2,1,200.,5,3,3,1<<28,1.,1.,1.)
        self.mask_header=PaHeader(-2,1,1.,5,3,3,1<<28,1.,1.,1.)
        self.p=self.root/'in.pa';self.m=self.root/'mask.pa';self.o=self.root/'out.pa';self.om=self.root/'outmask.pa'
        v=[0.]*45;v[0]=-0.;v[1]=0.;mask=[0.]*45;mask[0:2]=[1.,1.]
        self.write(self.p,self.header,v);self.write(self.m,self.mask_header,mask)
    def write(self,path,header,values):
        path.write_bytes(header.pack()+b''.join(struct.pack('<d',v) for v in values))
    def run_fill(self):
        return fill_invalid_scalar_pa(self.p,self.m,self.o,self.om,projection=self.projection,request=self.request,grid=self.grid,chunk_nodes=7)
    def test_interior_vacuum_and_valid_bit_preservation(self):
        before=self.p.read_bytes();r=self.run_fill();out=self.o.read_bytes();mask=self.om.read_bytes()
        self.assertEqual(out[:56],before[:56]);self.assertEqual(out[56:72],before[56:72])
        self.assertEqual(out[56:64],struct.pack('<d',-0.));self.assertEqual(out[64:72],struct.pack('<d',0.))
        def node(raw,i):return struct.unpack_from('<d',raw,56+8*(i-1))[0]
        self.assertEqual(node(out,22),-100.);self.assertEqual(node(mask,22),1.)
        self.assertEqual(node(mask,23),0.);self.assertEqual(r['status'],'success');self.assertGreater(r['filled_conductor_count'],0)
    def test_late_bad_mask_preserves_private_staging(self):
        raw=bytearray(self.m.read_bytes());struct.pack_into('<d',raw,56+8*44,.5);self.m.write_bytes(raw)
        inputs=(self.p.read_bytes(),self.m.read_bytes())
        with self.assertRaisesRegex(ValueError,'binary'):self.run_fill()
        self.assertTrue(self.o.exists());self.assertTrue(self.om.exists())
        self.assertEqual((self.p.read_bytes(),self.m.read_bytes()),inputs)
    def test_conflict_never_publishes(self):
        other=copy.deepcopy(self.projection['members'][0]);other.update(member_id='second',electrode_group_id='other')
        self.projection['members'].append(other);self.projection['electrode_groups'].append({'instance_id':'oa','electrode_group_id':'other','member_ids':['second']})
        self.request['group_voltages'].append({'instance_id':'oa','electrode_group_id':'other','voltage_v':1.})
        inputs=(self.p.read_bytes(),self.m.read_bytes())
        with self.assertRaisesRegex(ValueError,'different electrode groups'):self.run_fill()
        self.assertTrue(self.o.exists());self.assertTrue(self.om.exists())
        self.assertEqual((self.p.read_bytes(),self.m.read_bytes()),inputs)
    def test_bad_header_nonfinite_flags_and_existing_destination(self):
        for mode in ('grid','nonfinite','electrode','exists'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='grid':self.grid['pitch_mm'][0]=2
                elif mode=='nonfinite':
                    raw=bytearray(self.p.read_bytes());struct.pack_into('<d',raw,56+8*44,float('nan'));self.p.write_bytes(raw)
                elif mode=='electrode':
                    raw=bytearray(self.p.read_bytes());struct.pack_into('<d',raw,56+8*44,201.);self.p.write_bytes(raw)
                else:self.o.write_bytes(b'preserve')
                with self.assertRaises(ValueError):self.run_fill()
                if mode=='exists':self.assertEqual(self.o.read_bytes(),b'preserve')
                elif mode in ('nonfinite','electrode'):
                    self.assertTrue(self.o.exists());self.assertTrue(self.om.exists())
                else:self.assertFalse(self.o.exists())
                if mode not in ('nonfinite','electrode'):self.assertFalse(self.om.exists())
    def test_ulp_boundaries_remain_invalid(self):
        import math
        for x in (math.nextafter(1.25,-math.inf),1.25,math.nextafter(1.25,math.inf)):
            with self.subTest(x=x):
                self.setUp();self.grid.update(origin_mm=[x,0,0],dimensions=[2,2,2],point_count=8)
                h=PaHeader(-2,1,200.,2,2,2,1<<28,1.,1.,1.);m=PaHeader(-2,1,1.,2,2,2,1<<28,1.,1.,1.)
                self.write(self.p,h,[0.]*8);self.write(self.m,m,[0.]*8);self.run_fill()
                self.assertEqual(struct.unpack_from('<d',self.om.read_bytes(),56)[0],0.)
    def test_rotated_boolean_and_unsupported(self):
        rotation=[[0,-1,0],[1,0,0],[0,0,1]]
        for member in self.projection['members']:member['transform']['rotation']=rotation
        self.run_fill();mask=self.om.read_bytes()
        self.assertEqual(struct.unpack_from('<d',mask,56+8*(18-1))[0],1.)
        self.setUp();self.projection['members'][0]['shape']={'kind':'unsupported_cone'}
        self.run_fill();mask=self.om.read_bytes()
        self.assertEqual(struct.unpack_from('<d',mask,56+8*(22-1))[0],0.)
    def test_second_existing_destination_and_input_read_failure(self):
        from unittest.mock import patch
        inputs=(self.p.read_bytes(),self.m.read_bytes());self.om.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError,'output exists'):self.run_fill()
        self.assertFalse(self.o.exists());self.assertEqual(self.om.read_bytes(),b'foreign')
        self.assertEqual((self.p.read_bytes(),self.m.read_bytes()),inputs)
        self.om.unlink()
        with patch('msplatform.backends.simion.standalone_pa_composition._read_block',side_effect=OSError('input read failure')):
            with self.assertRaisesRegex(OSError,'input read failure'):self.run_fill()
        self.assertTrue(self.o.exists());self.assertTrue(self.om.exists())
        self.assertEqual((self.p.read_bytes(),self.m.read_bytes()),inputs)
    def test_write_failure_preserves_originals_and_private_staging(self):
        from unittest.mock import patch
        inputs=(self.p.read_bytes(),self.m.read_bytes())
        with patch('os.fsync',side_effect=OSError('staging sync failure')):
            with self.assertRaisesRegex(OSError,'staging sync failure'):self.run_fill()
        self.assertTrue(self.o.exists());self.assertTrue(self.om.exists())
        self.assertEqual((self.p.read_bytes(),self.m.read_bytes()),inputs)
    def test_unused_high_voltage_leaves_header_and_payload_unchanged(self):
        self.request['group_voltages'][1]['voltage_v']=500.
        for vacuum_hole in (False,True):
            with self.subTest(vacuum_hole=vacuum_hole):
                self.setUp();self.request['group_voltages'][1]['voltage_v']=500.
                mask=[1.]*45
                if vacuum_hole:mask[22]=0.
                self.write(self.m,self.mask_header,mask)
                before=self.p.read_bytes();before_mask=self.m.read_bytes();result=self.run_fill()
                self.assertEqual(self.o.read_bytes(),before);self.assertEqual(self.om.read_bytes(),before_mask)
                self.assertEqual(result['filled_conductor_count'],0)
    def test_actual_high_voltage_expands_only_range_and_preserves_valid_bits(self):
        self.request['group_voltages'][1]['voltage_v']=-500.
        mask=[1.]*45;mask[21]=0.;self.write(self.m,self.mask_header,mask)
        before=self.p.read_bytes();result=self.run_fill();out=self.o.read_bytes()
        self.assertEqual(out[:8],before[:8]);self.assertEqual(out[16:56],before[16:56])
        self.assertEqual(struct.unpack_from('<d',out,8)[0],500.)
        self.assertEqual(out[56:72],before[56:72])
        self.assertEqual(struct.unpack_from('<d',out,56+8*21)[0],-500.)
        self.assertEqual(result['filled_conductor_count'],1)
    def test_duplicate_outputs_and_filled_voltage_overflow(self):
        with self.assertRaisesRegex(ValueError,'distinct'):fill_invalid_scalar_pa(self.p,self.m,self.o,self.o,projection=self.projection,request=self.request,grid=self.grid)
        self.request['group_voltages'][1]['voltage_v']=1e308
        before=(self.p.read_bytes(),self.m.read_bytes())
        with self.assertRaisesRegex(ValueError,'overflows'):self.run_fill()
        self.assertEqual((self.p.read_bytes(),self.m.read_bytes()),before)
        self.assertTrue(self.o.exists());self.assertTrue(self.om.exists())
