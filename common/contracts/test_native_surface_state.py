"""Pure native-surface proof validation; no PA or vendor process."""
import copy, unittest
from msplatform.backends.simion import native_surface_state as mod

class NativeSurfaceStateTests(unittest.TestCase):
 def test_modes_and_fail_closed_inputs(self):
  grid=dict(nx=3,ny=4,nz=5,dx_mm=.5,dy_mm=1,dz_mm=2)
  empty=dict(schema_version=1,mode='empty',grid=[3,4,5],pitch=[.5,1,2],scanned_nodes=60,offset_nodes=0)
  present=dict(empty,mode='present',scanned_nodes=None,offset_nodes=None)
  self.assertEqual(mod.validate_native_surface_state(empty,grid=grid,surface_present=False),'empty')
  self.assertEqual(mod.validate_native_surface_state(present,grid=grid,surface_present=True),'present')
  for change,presence in [({'scanned_nodes':59},False),({'offset_nodes':1},False),({'grid':[4,4,5]},False),({'pitch':[.5,1,3]},False),({'schema_version':True},False),({'mode':'other'},False),({},True),({'offset_nodes':False},False)]:
   value=copy.deepcopy(empty);value.update(change)
   with self.subTest(value=value,presence=presence),self.assertRaises(ValueError):mod.validate_native_surface_state(value,grid=grid,surface_present=presence)
  with self.assertRaises(ValueError):mod.validate_native_surface_state(present,grid=grid,surface_present=False)
  with self.assertRaises(ValueError):mod.validate_native_surface_state(empty,grid=dict(grid,nx=True),surface_present=False)

if __name__=='__main__':unittest.main()
