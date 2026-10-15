"""Independent voltage/time checks with ordinary Lua, without a SIMION process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]


class NativeDriveTests(unittest.TestCase):
    """Check RF quarter-cycle, DC switches, lift and extraction electrode roles."""

    def test_frozen_voltage_schedule_with_independent_expected_values(self) -> None:
        lua = shutil.which("lua") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe")
        if not Path(lua).is_file():
            self.skipTest("ordinary lua.exe unavailable; no commercial SIMION process is used")
        baseline = json.loads((PROJECT / "config/baseline.json").read_text(encoding="utf-8"))
        point = json.loads((PROJECT / "config/native_operating_point.json").read_text(encoding="utf-8"))
        numerics = json.loads((PROJECT / "config/numerics.json").read_text(encoding="utf-8"))
        # This reference deliberately uses independently specified numerical
        # values for the current physical seed, rather than reimplementing the
        # Lua scheduling branches in Python. If the seed changes, review it.
        cases = [
            (0, [500, -500, 495, -505, 500, 500, -500, -500, -2, 5, -5, 0, 50, 0, -5]),
            (1 / (4 * 3.7), [0, 0, -5, -5, 0, 0, 0, 0, -2, 5, -5, 0, 50, 0, -5]),
            (1500, [500, -500, 502, -498, 500, 500, -500, -500, 22, 5, -5, 0, 50, 0, 2]),
            (4750, [500, -500, 502, -498, 2500, 2500, 1500, 1500, 22, 2005, 1995, 0, 2050, 2000, 2]),
            (5500, [500, -500, 502, -498, 4000, 4000, 3500, 3500, 22, 4005, 3995, 0, 4050, 4000, 2]),
            (5500 + 0.5 / 3.7, [-500, 500, -498, 502, 3100, 4900, 3100, 4900, 22, 4005, 3995, 0, 4050, 4000, 2]),
        ]
        c = {"baseline": baseline, "native_operating_point": point}
        program = "local c=" + lua_literal(c) + "\n"
        program += "local drive=assert(loadfile(" + json.dumps(str(PROJECT / "simion/native_drive.lua").replace("\\", "/")) + "))()\n"
        program += "local rfmodule=assert(loadfile(" + json.dumps(str(REPO / "common/multipole/simion_rf_drive.lua").replace("\\", "/")) + "))()\n"
        program += "local rf=rfmodule.new" + lua_literal({"waveform": "cosine", "frequency_hz": baseline["electric"]["rf_frequency_hz"], "phase_rad": 0, "rf_amplitude_v": baseline["electric"]["rf_peak_to_peak_v"] / 2, "rf_scale": 1, "common_mode_scale": 1, "group_dc_v": [0, 0], "rf_steps_per_period": numerics["rf_steps_per_period"], "electrodes": [{"electrode_id": 1, "electrode_group": 1, "polarity": 1, "common_mode_v": 0}]}) + "\n"
        for time, expected in cases:
            program += "do local t=" + repr(time) + ";local expected=" + lua_literal(expected) + ";local v=drive.voltages(c,t,rf.differential_at(t));assert(#v==15);for i=1,15 do assert(math.abs(v[i]-expected[i])<1e-6,'voltage mismatch electrode '..i..' at '..t) end end\n"
        program += "print('NATIVE_DRIVE_INDEPENDENT_REFERENCE=PASS')\n"
        with tempfile.TemporaryDirectory(prefix="ion_processor_drive_test_") as directory:
            script = Path(directory) / "check.lua"
            script.write_text(program, encoding="utf-8")
            result = subprocess.run([lua, str(script)], capture_output=True, text=True, timeout=20, check=False, cwd=directory)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NATIVE_DRIVE_INDEPENDENT_REFERENCE=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
