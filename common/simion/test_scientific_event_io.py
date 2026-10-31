"""Structured scientific output and explicit legacy adapters; no solver required."""
from pathlib import Path
import tempfile
import unittest
from common.simion import scientific_event_io as io
ROOT=Path(__file__).resolve().parents[2]

class ScientificEventIoTests(unittest.TestCase):

    def test_stream_header_and_malformed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.csv'
            path.write_text('id,t\n11,7\n45,9\n')
            rows = io.iter_csv_rows(path, ('id', 't'))
            self.assertEqual(next(rows), dict(id='11', t='7'))
            self.assertEqual(next(rows), dict(id='45', t='9'))
            rows.close()
            for bad in ('id,id\n1,2\n', 'id,t\n1\n', 'id,t\n1,2,3\n'):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    list(io.iter_csv_rows(path, ('id', 't')))

    def test_lua_writer_preserves_declared_numeric_precision_and_csv_strings(self):
        import subprocess
        lua = Path('C:/Program Files/SIMION-2020/lua.exe')
        if not lua.is_file():
            self.skipTest('Lua runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.csv'
            script = Path(directory) / 'write.lua'
            script.write_text('local C=assert(loadfile(' + repr((ROOT / 'common/simion/scientific_event_csv.lua').as_posix()) + '))();local w=C.open(' + repr(path.as_posix()) + ",{'event','particle_id','t_us'},15);w:write({'source','45',1.2345678901234567});w:flush();w:close()")
            result = subprocess.run([str(lua), str(script)], cwd=script.parent, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(path.read_text(), 'event,particle_id,t_us\nsource,45,1.23456789012346\n')

    def test_csv_identity_is_checked_during_one_complete_read(self):
        import hashlib
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.csv'
            path.write_bytes(b'\xef\xbb\xbfid,t\r\n11,7\r\n45,9\r\n')
            data = path.read_bytes()
            expected = dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            identity = {}
            original = Path.open
            with patch.object(Path, 'open', autospec=True, side_effect=original) as opened:
                self.assertEqual(len(list(io.iter_csv_rows(path, ('id', 't'), expected_record=expected, identity_result=identity))), 2)
                self.assertEqual(opened.call_count, 1)
            self.assertEqual(identity['sha256'], expected['sha256'])
            path.write_bytes(data + b'99,10\r\n')
            with self.assertRaisesRegex(ValueError, 'differs from bound'):
                list(io.iter_csv_rows(path, ('id', 't'), expected_record=expected))

    def test_csv_quotes_multiline_and_strict_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.csv'
            path.write_bytes(b'id,note\n45,"a,b\nline""two"\n')
            self.assertEqual(list(io.iter_csv_rows(path, ('id', 'note'))), [dict(id='45', note='a,b\nline"two')])
            path.write_text('id,note\n45,"unterminated\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'malformed scientific CSV'):
                list(io.iter_csv_rows(path, ('id', 'note')))

    def test_lua_write_flush_close_and_incomplete_rows_fail(self):
        import subprocess
        lua = Path('C:/Program Files/SIMION-2020/lua.exe')
        if not lua.is_file():
            self.skipTest('Lua runtime unavailable')
        module = (ROOT / 'common/simion/scientific_event_csv.lua').as_posix()
        code = """local C=assert(loadfile(arg[1]))()
local original=io.open
for _,phase in ipairs({'write','flush','close','row'}) do
 local stream={write=function(self) if phase=='write' then return nil,'disk full' end return self end,
  flush=function() if phase=='flush' then return nil,'flush error' end return true end,
  close=function() if phase=='close' then return nil,'close error' end return true end}
 io.open=function() return stream end
 local ok,err=pcall(function()
  local w=C.open('fixture',{'a','b','c'},17)
  if phase=='row' then w:write({'value',nil,'tail'}) elseif phase=='flush' then w:flush() elseif phase=='close' then w:close() end
 end)
 assert(not ok and tostring(err):find('scientific CSV'),'failure was swallowed: '..phase)
end
io.open=original
print('IO_FAILURE_PROPAGATION=PASS')
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'check.lua'
            script.write_text(code, encoding='utf-8')
            result = subprocess.run([str(lua), str(script), module], cwd=script.parent, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('IO_FAILURE_PROPAGATION=PASS', result.stdout)
