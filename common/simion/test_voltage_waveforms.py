"""Run pure edge arithmetic with standalone Lua; no solver or workbench."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class VoltageWaveformsTests(unittest.TestCase):
    def test_frozen_module_caps_only_a_future_edge(self) -> None:
        lua = shutil.which("lua") or r"C:\Program Files\SIMION-2020\lua.exe"
        if not Path(lua).is_file():
            self.skipTest("standalone Lua unavailable")
        source = Path(__file__).parent
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "voltage_waveforms.lua"
            shutil.copyfile(source / frozen.name, frozen)
            result = subprocess.run(
                [lua, str(source / "test_voltage_waveforms.lua"), str(frozen)],
                cwd=directory, capture_output=True, text=True, check=False, timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VOLTAGE_WAVEFORMS_EDGE_CAP=PASS", result.stdout)
