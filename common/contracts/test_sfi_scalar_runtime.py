"""Callback-neutral SFI scalar basis tests; no native field claim."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts.test_simion_prepared_model import LUA

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / 'src/msplatform/backends/simion/resources'


@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class SfiScalarRuntimeTests(unittest.TestCase):
    def test_real_waveforms_selected_slots_and_full_support(self):
        script = r'''
local compose=assert(loadfile(arg[1]))()
local rf=assert(loadfile(arg[2]))()
local pulse_module=assert(loadfile(arg[3]))()
local voltage=assert(loadfile(arg[4]))()
local pulse=pulse_module.compile_physical{voltage_waveforms=voltage,pulse_time_us=10,pulse_width_us=2,pulse_mode=function() return 1 end}
local calls={}
local function adapter(binding)
 return function(inst,x,y,z)
  calls[#calls+1]={binding,inst.slot,x,y,z}
  if binding=='bad' then error('COVERAGE_REFUSAL') end
  if binding=='carrier' then return 1,2,3 end
  if binding=='rf' then return 4,5,6 end
  return 7,8,9
 end
end
local args={carrier='carrier',rf_reference='rf',pulse_delta='pulse'}
local drive={waveform='cosine',frequency_hz=250000,phase_rad=0,phase_reference_instrument_time_us=0}
local field=compose.new(adapter,rf,pulse,args,drive)
-- Binary64: largest phase is 6*pi, and the largest weighted component is 9.
-- 128 eps * (1 + 6*pi) * (1 + 9) bounds argument rounding and the
-- few multiply/add operations, with conservative margin for libm rounding.
local tolerance=128 * 2^-52 * (1 + 6*math.pi) * 10
local function check(actual,expected) assert(math.abs(actual-expected)<=tolerance) end
local a,b,c=field({slot=3},1,2,3,0)
check(a,5);check(b,7);check(c,9)
assert(#calls==3 and calls[1][2]==3 and calls[2][2]==3 and calls[3][2]==3)
a,b,c=field({slot=4},4,5,6,1)
check(a,1);check(b,2);check(c,3)
assert(#calls==6 and calls[4][2]==4 and calls[5][2]==4 and calls[6][2]==4)
-- start is inclusive, end exclusive; RF at 10 and 12 us follows the real kernel.
a,b,c=field({slot=3},1,2,3,10)
check(a,4);check(b,5);check(c,6)
a,b,c=field({slot=4},1,2,3,12)
check(a,5);check(b,7);check(c,9)
assert(#calls==12)
local bad=compose.new(adapter,rf,pulse,{carrier='carrier',rf_reference='bad',pulse_delta='pulse'},drive)
local ok,err=pcall(bad,{slot=3},0,0,0,1)
assert(not ok and string.find(err,'COVERAGE_REFUSAL',1,true))
local bad_pulse=compose.new(adapter,rf,pulse,{carrier='carrier',rf_reference='rf',pulse_delta='bad'},drive)
local pulse_ok,pulse_err=pcall(bad_pulse,{slot=4},0,0,0,1)
assert(not pulse_ok and string.find(pulse_err,'COVERAGE_REFUSAL',1,true))
local missing,message=pcall(field,nil,0,0,0,1)
assert(not missing and string.find(message,'selected instance required',1,true))
local invalid,msg=pcall(compose.new,adapter,rf,pulse,args,{waveform='cosine',frequency_hz=250000,phase_rad=0,phase_reference_instrument_time_us=1})
assert(not invalid and string.find(msg,'phase reference',1,true))
print('SFI_SCALAR_BASIS=PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scalar_test.lua'
            path.write_text(script, encoding='utf-8')
            args = [LUA, path, *(RESOURCES / name for name in ('sfi_scalar_field.lua', 'rf_drive.lua',
                    'single_flight_pulse_hook.lua', 'voltage_waveforms.lua'))]
            result = subprocess.run([str(value) for value in args], capture_output=True, text=True, encoding='utf-8', cwd=directory, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SFI_SCALAR_BASIS=PASS', result.stdout)
