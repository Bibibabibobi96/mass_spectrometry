"""IP-MR typed gas binding; pure source and inert Lua only, not native Fly."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.contracts import test_ip_mr_model as model_fixture
from tests.contracts.test_simion_native_plans import LUA
from tests.components.ion_processor.test_functional import HS1_SOURCE_FIXTURE
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
from msplatform.backends.simion.rf_tracking_execution import prepare_ip_mr_hs1, prepare_rf_ip_hs1
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from msplatform.contracts.gas import BoxDomain
from msplatform.io.manifest_records import file_record


def box(lo, hi):
    return BoxDomain(lo, hi, (True, True, True), (True, True, True))


class IpMrHs1BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from msplatform.assembly.factory import assemble
        from msplatform.backends.simion.mr_compiler import compile_complete_mr_geometry
        from msplatform.components.catalog import resolve_component
        root = Path(__file__).resolve().parents[2]
        fixture = json.loads((root / 'tests/contracts/test_support/ip_mr_current_requests.json').read_text(encoding='utf8'))
        parts = {name: resolve_component(value) for name, value in fixture['component_requests'].items()}
        assembly = assemble(fixture['recipe'], parts)
        compiled = compile_complete_mr_geometry(assembly, numerics={'domains': {
            'ip': model_fixture.domain(-10., 220., .1), 'analyzer': model_fixture.domain(-1000., 1000., .1),
            'detector': model_fixture.domain(-1000., 1000., .1)}})
        from msplatform.io.file_identity import file_sha256
        identity = dict(clock_epoch_id='instrument_clock_epoch_v1', authority_sha256=file_sha256(root/'src/msplatform/examples/instrument_epoch_v1.json'))
        point = json.loads((root/'src/msplatform/components/ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
        drive = dict(clock=dict(identity, phase_reference_instrument_time_us=0.),
            ip_schedule=dict(baseline=assembly.components_source['ion_processor']['baseline'], native_operating_point=point, clock=identity),
            mr_authority=dict(source=dict(analyzer_electrode_voltages_v=list(range(1, 21))),
                candidate=dict(s1=31., s2=32., p1=41., p2=42.), mirror_voltages_v=[11., 12., 13., 14., 15.],
                detector_voltage_v=50., mirror_shield_voltages_v=dict(positive_mirror_ground_shield=51., negative_mirror_ground_shield=52.)))
        cls.model = compile_prepared_model(compiled, compiled.components_resolved, drive=drive, physics=RF_IP_PHYSICS)

    def test_selected_lp60_pose_coverage_and_identity(self):
        baseline = self.model.document['drive']['ip_schedule']['baseline']
        self.assertEqual((baseline['geometry']['lp_length_mm'], baseline['geometry']['lp_center_mm']), (60, 170))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); vendor=root/'vendor.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf8')
            source_environment = Path(__file__).resolve().parents[2] / 'src/msplatform/components/ion_processor/config/gas_environment.json'
            author = json.loads(source_environment.read_text(encoding='utf8'))
            author['outer_state'] = dict(pressure_pa=4, temperature_k=300, bulk_velocity_m_s=[1,2,3])
            environment = root/'environment.json'; environment.write_text(json.dumps(author), encoding='utf8')
            request=dict(bath_domain=box((0,-10,-10),(211,10,10)),outer_domain=box((-500,-500,-500),(500,500,500)),
                         environment_record=file_record(environment), environment_instance_id='ion_processor',
                         vendor_record=file_record(vendor),numerics=dict(seed=40,hs1_steps_per_mfp=20))
            world=box((-20,-230,-10),(20,0,10))
            world_frame=self.model.document['native_frame_id']
            result=prepare_ip_mr_hs1(self.model,request,common_world_domain=world,common_world_frame_id=world_frame)
            self.assertEqual(result['environment_bytes'], environment.read_bytes())
            self.assertEqual(result['identity']['environment_author_sha256'].lower(), request['environment_record']['sha256'].lower())
            self.assertEqual(result['identity']['gas_environment']['species_data'][0]['mass_amu'], 28.0134)
            self.assertEqual(len(result['identity']['gas_environment']['fields']), 2)
            self.assertEqual(result['identity']['native_gas_view']['mass_amu'], 28.0134)
            self.assertEqual(result['identity']['native_gas_view']['cross_section_m2'], 2.27e-18)
            changed = copy.deepcopy(author); changed['outer_state']['pressure_pa'] = 5
            changed_path = root/'changed_outer.json'; changed_path.write_text(json.dumps(changed),encoding='utf8')
            changed_result = prepare_ip_mr_hs1(self.model,dict(request,environment_record=file_record(changed_path)),
                                               common_world_domain=world,common_world_frame_id=world_frame)
            self.assertNotEqual(changed_result['identity']['environment_author_sha256'], result['identity']['environment_author_sha256'])
            self.assertNotEqual(changed_result['identity']['outer_runtime_sha256'], result['identity']['outer_runtime_sha256'])
            self.assertEqual(changed_result['identity']['bath_runtime_sha256'], result['identity']['bath_runtime_sha256'])
            with self.assertRaisesRegex(ValueError, 'different instance'):
                prepare_ip_mr_hs1(self.model,dict(request, environment_instance_id='other'),common_world_domain=world,common_world_frame_id=world_frame)
            bad_environment = copy.deepcopy(request)
            bad_environment['environment_record']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'author identity differs'):
                prepare_ip_mr_hs1(self.model,bad_environment,common_world_domain=world,common_world_frame_id=world_frame)
            missing = copy.deepcopy(author); del missing['outer_state']
            other_environment = root/'missing_outer.json'; other_environment.write_text(json.dumps(missing), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'outer_state'):
                prepare_ip_mr_hs1(self.model,dict(request, environment_record=file_record(other_environment)),
                                   common_world_domain=world,common_world_frame_id=world_frame)
            with self.assertRaisesRegex(ValueError, 'domains'):
                prepare_ip_mr_hs1(self.model,dict(request, outer='second authority'),
                                   common_world_domain=world,common_world_frame_id=world_frame)
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
