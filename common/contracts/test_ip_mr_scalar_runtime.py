"""Callback-neutral scalar composition with actual IP voltage-law resources."""
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from common.contracts.test_simion_prepared_model import LUA
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from msplatform.components.dual_pressure_rectilinear_ion_processor.timing import derive_native_timing

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(LUA.is_file(),'plain Lua unavailable; no native fallback')
class IpMrScalarRuntimeTests(unittest.TestCase):
    def test_resource_missing_refuses_without_fallback(self):
        self.assertTrue(native_resource_path('ip_mr_scalar_field.lua').is_file())
        with tempfile.TemporaryDirectory() as directory, patch('msplatform.backends.simion.resources.files',return_value=Path(directory)):
            with self.assertRaisesRegex(FileNotFoundError,'ip_mr_scalar_field.lua'):
                native_resource_path('ip_mr_scalar_field.lua')

    def test_actual_model_drive_edges_and_all_supports(self):
        fixture=json.loads((ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        baseline=fixture['component_requests']['ion_processor']['design']['baseline']
        point=json.loads((ROOT/'projects/dual_pressure_rectilinear_ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
        schedule=dict(baseline=baseline,native_operating_point=point,native_timing=derive_native_timing(baseline),
                      clock={'clock_epoch_id':'test','authority_sha256':'A'*64})
        groups=[dict(instance_id='ion_processor',electrode_group_id='ip'+str(i),kind='ip_schedule',schedule_index=i,native_targets=[]) for i in range(1,16)]
        groups.append(dict(instance_id='multipole',electrode_group_id='rf',kind='rf',waveform='cosine',frequency_hz=1100000.,
                           phase_rad=0.,rf_amplitude_v=100.,polarity=1,common_mode_v=0.,dc_v=0.,native_targets=[]))
        config=dict(schema_version=1,role='simion_model_drive',clock={'phase_reference_instrument_time_us':0.},groups=groups,ip_schedule=schedule)
        bindings=dict(carrier=100,ip_unit_volt=[dict(instance_id='ion_processor',electrode_group_id='ip'+str(i),binding=i) for i in range(1,16)],
                      rf_reference=dict(binding=200,signature=dict(waveform='cosine',frequency_hz=1100000.,phase_rad=0.,phase_reference_instrument_time_us=0.)))
        resources=native_resource_path('model_drive.lua').parent
        script=r'''
local resources=arg[1]
local model=assert(loadfile(resources..'/model_drive.lua'))()
local rf=assert(loadfile(resources..'/rf_drive.lua'))()
local pulse=assert(loadfile(resources..'/single_flight_pulse_hook.lua'))()
local waveforms=assert(loadfile(resources..'/voltage_waveforms.lua'))()
local native=assert(loadfile(resources..'/native_drive.lua'))
local composer=assert(loadfile(arg[2]))()
local config=CONFIG
local bindings=BINDINGS
local calls=0;local bad=nil
local function adapter(id)
 return function(instance,x,y,z)
  calls=calls+1;assert(id~=bad,'MASK_UNKNOWN')
  return id,2*id,-id
 end
end
local consumer=model.new(config,rf,pulse,waveforms,native)
local sample=composer.new(adapter,consumer,rf,bindings)
local unit_rf=rf.compile_physical{waveform='cosine',frequency_hz=1100000,phase_rad=0,rf_amplitude_v=1,rf_scale=1}
local saved=bindings.ip_unit_volt[15];bindings.ip_unit_volt[15]=nil
local valid,message=pcall(composer.new,adapter,consumer,rf,bindings)
assert(not valid and string.find(message,'fifteen IP unit',1,true));bindings.ip_unit_volt[15]=saved
local reference=bindings.rf_reference;bindings.rf_reference=nil
valid,message=pcall(composer.new,adapter,consumer,rf,bindings)
assert(not valid and string.find(message,'RF reference must match',1,true));bindings.rf_reference=reference
bindings.rf_reference.signature.frequency_hz=1
valid,message=pcall(composer.new,adapter,consumer,rf,bindings)
assert(not valid and string.find(message,'signature differs',1,true));bindings.rf_reference.signature.frequency_hz=1100000
local s=config.ip_schedule.baseline.schedule;local timing=config.ip_schedule.native_timing
local times={0,.25/1.1,s.capture_end_us-1e-6,s.capture_end_us,
 s.transfer_end_us,s.lift_end_us-1e-6,s.lift_end_us,
 timing.primary_quench_us-1e-6,timing.primary_quench_us,
 timing.pulse_start_us-1e-6,timing.pulse_start_us}
for _,t in ipairs(times) do
 calls=0;local expected=100;local magnitude=100
 for _,row in ipairs(consumer.evaluate_at(t)) do
  if row.instance_id=='ion_processor' then
   local term=row.voltage_v*tonumber(row.electrode_group_id:sub(3));expected=expected+term;magnitude=magnitude+math.abs(term)
  end
 end
 local rf_term=200*unit_rf.differential_at(t);expected=expected+rf_term;magnitude=magnitude+math.abs(rf_term)
 local x,y,z=sample({},0,0,0,t)
 -- 256 binary64 eps covers the 17-term sum and scaling, not a physical tolerance.
 local roundoff=256*2^-52*(1+magnitude)
 assert(calls==17 and math.abs(x-expected)<=roundoff and math.abs(y-2*x)<=2*roundoff and math.abs(z+x)<=roundoff)
end
local actual=consumer.evaluate_at(timing.pulse_start_us)
assert(actual[5].voltage_v==config.ip_schedule.native_operating_point.lift_v+config.ip_schedule.native_operating_point.extraction_pull_relative_v)
local original=consumer.evaluate_at
consumer.evaluate_at=function(t)local rows=original(t);rows[1].voltage_v=0;return rows end
bad=1;local ok,err=pcall(sample,{},0,0,0,0);assert(not ok and string.find(err,'MASK_UNKNOWN',1,true))
consumer.evaluate_at=function(t)local rows=original(t);rows[2]=rows[1];return rows end
ok,err=pcall(sample,{},0,0,0,0);assert(not ok and string.find(err,'duplicate evaluated IP group',1,true))
ok,err=pcall(sample,{},0,0,0,0/0);assert(not ok and string.find(err,'instrument time',1,true))
print('IP_MR_SCALAR_RUNTIME=PASS')
'''.replace('CONFIG',lua_value(config)).replace('BINDINGS',lua_value(bindings))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.lua';path.write_text(script,encoding='utf8')
            result=subprocess.run([str(LUA),str(path),str(resources),str(native_resource_path('ip_mr_scalar_field.lua'))],
                                  cwd=directory,capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('IP_MR_SCALAR_RUNTIME=PASS',result.stdout)
