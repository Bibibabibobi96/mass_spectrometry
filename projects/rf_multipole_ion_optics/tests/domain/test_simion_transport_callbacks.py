from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / 'projects/rf_multipole_ion_optics'
SUPPLIER_LUA = Path(r'C:\Program Files\SIMION-2020\lua.exe')


class SimionTransportCallbackTests(unittest.TestCase):
    @unittest.skipUnless(SUPPLIER_LUA.is_file(), 'supplier Lua runtime unavailable; no PA/Fly validation')
    def test_actual_brackets_terminal_and_repeated_run(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            result = subprocess.run(
                [str(SUPPLIER_LUA), str(Path(__file__).with_suffix('.lua')),
                 str(PROJECT / 'simion/simion_transport.lua'),
                 str(ROOT / 'common/simion/rf_drive.lua'), output],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                errors='replace', check=False, timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SIMION_TRANSPORT_CALLBACK_TEST=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
