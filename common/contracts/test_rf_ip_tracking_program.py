"""Continuous RF-IP Program controls and resources."""
import copy
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from common.contracts import test_joint_ip_model as joint_ip_fixture
from common.contracts import test_simion_tracking_execution as tracking_fixture
from common.contracts.test_simion_native_plans import LUA
from msplatform.backends.simion.model import compile_prepared_model, RF_IP_PHYSICS
from msplatform.backends.simion.rf_tracking_program import render_rf_controls

ROOT=Path(__file__).resolve().parents[2]
RES=ROOT/'src/msplatform/backends/simion/resources'


@unittest.skipUnless(LUA.is_file(),'plain Lua unavailable')
class RfIpProgramTests(unittest.TestCase):
    def test_actual_joint_model_render_is_lua_syntax_valid_and_requires_explicit_inputs(self):
        fixture=joint_ip_fixture.JointIpModelTests(methodName='runTest');fixture.setUp()
        model=compile_prepared_model(fixture.compiled,fixture.compiled.components_resolved,drive=fixture.drive,physics=RF_IP_PHYSICS)
        source=tracking_fixture.TrackingExecutionPlanTests(methodName='runTest');source.setUp();plan=source.plan()
        plan['flight']['tracking_kind']='rf_ip';plan['flight']['grouped']=0
        names=('rf_drive.lua','single_flight_pulse_hook.lua','voltage_waveforms.lua','model_drive.lua','native_drive.lua',
               'rf_tracking.lua','rf_ip_gas_selection.lua','collision_hs1_gas.lua','rf_ip_tracking_hs1.lua')
        resources={name:(RES/name).read_text(encoding='utf-8') for name in names}
        record={'path':str((ROOT/'inert.pa0').resolve()),'bytes':1,'sha256':'A'*64}
        assets={'parent':{'family_records':[record],'witness_record':record}}
        plan['hs1']={'vendor_path':str((ROOT/'inert_hs1.lua').resolve()),'bath_path':str((ROOT/'inert_bath.lua').resolve()),
            'outer_path':str((ROOT/'inert_outer.lua').resolve()),'query_frame_id':model.document['native_frame_id'],
            'numerics':{'seed':40,'hs1_steps_per_mfp':20}}
        value=render_rf_controls(model,plan,assets=assets,native_sources=resources)
        self.assertIn('joint_hs1.install',value['program']);self.assertIn('simion.import',value['program'])
        self.assertIn('single_flight_canonical_particle_id',value['program']);self.assertIn('rf_instance_domains={"parent"}',value['program'])
        self.assertNotIn('upstream_exit_x_mm',value['program'])
        malformed=copy.deepcopy(plan);del malformed['hs1']['outer_path']
        with self.assertRaisesRegex(ValueError,'exact frozen runtime'):
            render_rf_controls(model,malformed,assets=assets,native_sources=resources)
        source_text=re.sub(r'(?m)^(\s*)adjustable ',r'\1',value['program'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'program.lua';path.write_text(source_text,encoding='utf-8')
            from msplatform.backends.simion.source import lua_value
            result=subprocess.run([str(LUA),'-e','assert(loadfile('+lua_value(str(path))+'))'],cwd=directory,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
