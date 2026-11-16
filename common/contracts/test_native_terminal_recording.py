"""Portable callback double; no SIMION/native qualification is claimed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LUA = r'''
local recorder=assert(loadfile(arg[1]))()
local order={}
segment={
 initialize_run=function() order[#order+1]='run' end,
 initialize=function() order[#order+1]='init';ion_px_mm=1 end,
 other_actions=function() order[#order+1]='action';ion_splat=5;ion_px_mm=ion_px_mm+1;return 'ok',nil,'tail' end,
 terminate=function() order[#order+1]='terminate' end,
}
local block_splat=false
setmetatable(_G,{__index=function(_,key) if block_splat and key=='ion_splat' then error('terminate read ion_splat') end end})
ion_number=1;ion_run=1;sim_grouped=0;ion_time_of_birth=12.5;ion_time_of_flight=0
ion_time_step=.1;ion_instance=2;ion_px_mm=0;ion_py_mm=3;ion_pz_mm=4
ion_vx_mm=5;ion_vy_mm=6;ion_vz_mm=nil;ion_splat=0
recorder.install(segment,{native_run='run-"A',particle_id=function() return 91 end,
 source_origin_us=function() return 100 end,pipeline_clock_us=function() return 200 end,
 instrument_time_us=function() return 300 end})
segment.initialize_run();segment.initialize()
ion_time_of_flight=8;local a,b,c=segment.other_actions();assert(a=='ok' and b==nil and c=='tail')
ion_splat=0;ion_time_of_flight=10;segment.other_actions()
ion_time_of_flight=9;ion_px_mm=99;ion_py_mm=88;ion_pz_mm=77;ion_vx_mm=66;ion_vy_mm=55;ion_vz_mm=44
ion_splat=nil;block_splat=true;segment.terminate();block_splat=false
assert(table.concat(order,',')=='run,init,action,action,terminate')
ion_run=2;ion_splat=0;ion_time_of_birth=20;ion_time_of_flight=0
segment.initialize_run();segment.initialize();ion_splat=nil;block_splat=true;segment.terminate();block_splat=false
assert(order[#order]=='terminate')
segment.initialize_run();ion_run=3;ion_splat=0;segment.initialize();ion_run=4;segment.initialize()
ion_splat=nil;block_splat=true;segment.terminate();ion_run=3;segment.terminate();block_splat=false
ion_run=0;ion_splat=0;local valid=pcall(segment.initialize);assert(not valid)
local failing={initialize=function() end,other_actions=function() error('original failure') end}
recorder.install(failing,{native_run='fail',particle_id=function() return 91 end,
 source_origin_us=function() return nil end,pipeline_clock_us=function() return nil end,
 instrument_time_us=function() return nil end})
ion_run=3;ion_splat=0;failing.initialize();local ok,err=pcall(failing.other_actions)
assert(not ok and string.find(err,'original failure',1,true))
for _,bad in ipairs({0/0,1/0,-1/0}) do
  local invalid={}
  recorder.install(invalid,{native_run='invalid',particle_id=function() return 91 end,
    source_origin_us=function() return nil end,pipeline_clock_us=function() return nil end,
    instrument_time_us=function() return nil end})
  ion_run=5;ion_px_mm=bad;invalid.initialize()
  local accepted,reason=pcall(invalid.terminate)
  assert(not accepted and string.find(reason,'nonfinite field: x_mm',1,true))
end
io.write('RECORDER_TEST_PASS\n')
'''


class NativeTerminalRecordingTests(unittest.TestCase):
    def test_bounded_snapshots_order_nulls_and_callback_errors(self):
        lua = os.environ.get('SIMION_LUA_EXE') or shutil.which('lua5.1') or shutil.which('lua')
        if not lua:
            self.skipTest('Lua 5.1 provider unavailable')
        resource = Path(__file__).resolve().parents[2] / 'src/msplatform/backends/simion/resources/native_terminal_recording.lua'
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'test.lua'
            script.write_text(LUA, encoding='utf-8')
            result = subprocess.run([str(lua), str(script), str(resource)], cwd=directory,
                                    capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line.split(':', 1)[1]) for line in result.stdout.splitlines()
                if line.startswith('SIMION_TERMINAL_V1:')]
        self.assertIn('RECORDER_TEST_PASS', result.stdout)
        self.assertEqual(len(rows), 10)
        required = {'schema_version','particle_id','ion','native_run','ion_run','capture_sequence','event',
                    'raw_birth_us','raw_tof_us','raw_step_us','source_origin_us','pipeline_clock_us',
                    'instrument_time_us','instance','x_mm','y_mm','z_mm','vx_mm_per_us','vy_mm_per_us',
                    'vz_mm_per_us','splat','grouped'}
        self.assertTrue(all(set(row) == required for row in rows))
        self.assertEqual([row['event'] for row in rows], ['initialize','other_actions_before','other_actions_after',
                         'terminate','initialize','terminate','initialize','terminate','initialize','terminate'])
        self.assertEqual([row['capture_sequence'] for row in rows], [1,4,5,6,1,2,1,2,1,2])
        self.assertEqual((rows[0]['raw_birth_us'],rows[0]['raw_tof_us'],rows[0]['x_mm']), (12.5,0,1))
        self.assertEqual((rows[1]['splat'],rows[2]['splat']), (0,5))
        self.assertEqual((rows[1]['raw_tof_us'],rows[3]['raw_tof_us']), (10,9))
        self.assertEqual([rows[3][name] for name in ('x_mm','y_mm','z_mm','vx_mm_per_us','vy_mm_per_us','vz_mm_per_us')],
                         [99,88,77,66,55,44])
        self.assertIsNone(rows[3]['splat'])
        self.assertIsNone(rows[3]['raw_step_us'])
        self.assertIsNone(rows[0]['vz_mm_per_us'])
        self.assertEqual([row['ion_run'] for row in rows], [1,1,1,1,2,2,4,4,3,3])
        self.assertTrue(all(row['particle_id'] == 91 and row['native_run'] == 'run-"A' for row in rows))


if __name__ == '__main__':
    unittest.main()
