"""IP-MR typed gas binding; pure source and inert Lua only, not native Fly."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts import test_ip_mr_model as model_fixture
from common.contracts.test_simion_native_plans import LUA
from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import HS1_SOURCE_FIXTURE
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
from msplatform.backends.simion.rf_tracking_execution import prepare_ip_mr_hs1, prepare_rf_ip_hs1
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
from msplatform.io.manifest_records import file_record


def box(lo, hi):
    return BoxDomain(lo, hi, (True, True, True), (True, True, True))


class IpMrHs1BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_fixture.IpMrModelTests.setUpClass()
        cls.model = compile_prepared_model(model_fixture.IpMrModelTests.compiled,
            model_fixture.IpMrModelTests.compiled.components_resolved,
            drive=model_fixture.IpMrModelTests.drive, physics=RF_IP_PHYSICS)

    def test_selected_lp60_pose_coverage_and_identity(self):
        baseline = self.model.document['drive']['ip_schedule']['baseline']
        self.assertEqual((baseline['geometry']['lp_length_mm'], baseline['geometry']['lp_center_mm']), (60, 170))
        frame = baseline['clock']['frame_id']
        outer = GasFieldSpec(field_id='outer', frame_id=frame, representation='uniform',
            composition_id='ion_processor_explicit_single_gas',
            composition=(GasSpecies('ion_processor_model_gas', baseline['gas']['mass_amu'], 1),),
            domain=box((-500,-500,-500),(500,500,500)), source=GasSource('prescribed','test',()),
            uniform_state=GasState('gas',4,baseline['gas']['temperature_k'],(1,2,3)))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); vendor=root/'vendor.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf8')
            request=dict(bath_domain=box((0,-10,-10),(211,10,10)),outer=outer,
                         vendor_record=file_record(vendor),numerics=dict(seed=40,hs1_steps_per_mfp=20))
            world=box((-20,-230,-10),(20,0,10))
            world_frame=self.model.document['native_frame_id']
            result=prepare_ip_mr_hs1(self.model,request,common_world_domain=world,common_world_frame_id=world_frame)
            self.assertEqual(result['identity']['common_world_domain']['minimum_mm'],world.minimum_mm)
            self.assertEqual(result['identity']['placement']['translation_mm'],[0,-225,3])
            self.assertEqual(result['identity']['numerics'],request['numerics'])
            with self.assertRaisesRegex(ValueError,'actual selected joint model'):
                prepare_rf_ip_hs1(self.model,request)
            with self.assertRaisesRegex(ValueError,'common world BoxDomain'):
                prepare_ip_mr_hs1(self.model,request,common_world_domain=None,common_world_frame_id=world_frame)
            with self.assertRaisesRegex(ValueError,'complete parent box'):
                prepare_ip_mr_hs1(self.model,request,common_world_domain=box((-1000,-230,-10),(20,0,10)),common_world_frame_id=world_frame)
            with self.assertRaisesRegex(ValueError,'box frame'):
                prepare_ip_mr_hs1(self.model,request,common_world_domain=world,common_world_frame_id='wrong_frame')
            bad=copy.deepcopy(request);bad['vendor_record']['sha256']='0'*64
            with self.assertRaises(AssertionError):prepare_ip_mr_hs1(self.model,bad,common_world_domain=world,common_world_frame_id=world_frame)
            if not LUA.is_file(): return
            b=root/'bath.lua';o=root/'outer.lua';b.write_text(result['bath_runtime'],encoding='utf8');o.write_text(result['outer_runtime'],encoding='utf8')
            selector=native_resource_path('rf_ip_gas_selection.lua')
            # IP local (x,y,z) -> world (-z, x-225, -y+3), exactly once.
            lua='local b=assert(loadfile('+lua_value(str(b))+'))()\nlocal o=assert(loadfile('+lua_value(str(o))+'))()\nlocal s=assert(loadfile('+lua_value(str(selector))+'))().new(b,o)\n'
            lua+='local frame='+lua_value(result['query_frame_id'])+'\n'
            for point,pressure in [((0,-195,3),1),((0,-95,3),.2),((0,-14,3),.2),((0,-13.9,3),4),((0,-200,1),0)]:
                lua+='assert(s.sample('+','.join(map(str,point))+',frame).pressure_pa=='+str(pressure)+')\n'
            lua+='local v=s.sample(0,-13.9,3,frame).bulk_velocity_m_s; assert(v[1]==-3 and v[2]==1 and v[3]==-2)\n'
            lua+='assert(s.sample(0,1000,3,frame).status=="outside_domain")\n'
            lua+='assert(not pcall(function() s.sample(0,0,0,"wrong_frame") end))\n'
            path=root/'query.lua';path.write_text(lua,encoding='utf8')
            run=subprocess.run([str(LUA),str(path)],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
