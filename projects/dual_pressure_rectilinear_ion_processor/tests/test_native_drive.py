"""Independent voltage/time checks with ordinary Lua, without a SIMION process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_native_timing, lua_literal


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
            (0, [500, -500, 495, -505, 500, 500, -500, -500, -2, 5, -1, 0, 50, 0, -5]),
            (1 / (4 * 3.7), [0, 0, -5, -5, 0, 0, 0, 0, -2, 5, -1, 0, 50, 0, -5]),
            (1500, [500, -500, 505, -495, 500, 500, -500, -500, 25, 5, -1, 0, 50, 0, 5]),
            (6750, [500, -500, 505, -495, 2500, 2500, 1500, 1500, 25, 2005, 1999, 0, 2050, 2000, 5]),
            (7500, [500, -500, 505, -495, 4000, 4000, 3500, 3500, 25, 4005, 3999, 0, 4050, 4000, 5]),
            (7500 + 0.5 / 3.7, [-500, 500, -495, 505, 3100, 4900, 3100, 4900, 25, 4005, 3999, 0, 4050, 3100, 5]),
        ]
        c = {"baseline": baseline, "native_operating_point": point, "native_timing":derive_native_timing(baseline)}
        program = "local c=" + lua_literal(c) + "\n"
        program += "local waveforms=assert(loadfile(" + json.dumps(str(REPO / "common/simion/voltage_waveforms.lua").replace("\\", "/")) + "))()\n"
        program += "local drive=assert(loadfile(" + json.dumps(str(PROJECT / "simion/native_drive.lua").replace("\\", "/")) + "))(waveforms)\n"
        program += "local rfmodule=assert(loadfile(" + json.dumps(str(REPO / "common/simion/rf_drive.lua").replace("\\", "/")) + "))()\n"
        program += "local rf=rfmodule.new" + lua_literal({"waveform": "cosine", "frequency_hz": baseline["electric"]["rf_frequency_hz"], "phase_rad": 0, "rf_amplitude_v": baseline["electric"]["rf_peak_to_peak_v"] / 2, "rf_scale": 1, "common_mode_scale": 1, "group_dc_v": [0, 0], "rf_steps_per_period": numerics["rf_steps_per_period"], "electrodes": [{"electrode_id": 1, "electrode_group": 1, "polarity": 1, "common_mode_v": 0}]}) + "\n"
        for time, expected in cases:
            program += "do local t=" + repr(time) + ";local expected=" + lua_literal(expected) + ";local v=drive.voltages(c,t,rf.differential_at(t));assert(#v==15);for i=1,15 do assert(math.abs(v[i]-expected[i])<1e-6,'voltage mismatch electrode '..i..' at '..t) end end\n"
        program += r'''
local q,p=c.native_timing.primary_quench_us,c.native_timing.pulse_start_us
assert(c.native_timing.policy=='requested_instrument_time_v1' and q==7500)
assert(math.abs(rf.differential_at(q)-500)<1e-6 and math.abs(rf.differential_at(p)+500)<1e-6)
local before=drive.voltages(c,q-0.001,100)
local at=drive.voltages(c,q,100)
assert(math.abs(before[5]-4100)<1e-6 and math.abs(before[6]-4100)<1e-6 and at[5]==4000 and at[6]==4000)
assert(at[7]==3900 and at[8]==3900,'side RF must continue until frozen side switch')
local waiting=drive.voltages(c,p-0.001,100)
local pulse=drive.voltages(c,p,100)
assert(waiting[7]==3900 and waiting[14]==4000 and pulse[5]==3100 and pulse[6]==4900 and pulse[7]==3100 and pulse[8]==4900 and pulse[14]==3100)
-- Consume the supplied frozen timestamp, with no local zero/pulse formula.
c.native_timing.pulse_start_us=p+1;c.native_timing.side_quench_us=p+1
assert(drive.pulse_start_us(c)==p+1 and drive.voltages(c,p,100)[7]==3900)
'''
        zero_baseline = json.loads(json.dumps(baseline))
        zero_baseline["electric"]["rf_quench_alignment"] = "next_cosine_zero"
        program += "c.native_timing=" + lua_literal(derive_native_timing(zero_baseline)) + "\n"
        program += r'''
assert(c.native_timing.policy=='cosine_zero_at_or_after_requested_v1')
local q,p=c.native_timing.primary_quench_us,c.native_timing.pulse_start_us
assert(q>7500 and p>q and math.abs(rf.differential_at(q))<1e-6 and math.abs(rf.differential_at(p))<1e-6)
local at=drive.voltages(c,q,100);local pulse=drive.voltages(c,p,100)
assert(at[5]==4000 and at[7]==3900 and at[14]==4000)
assert(pulse[5]==3100 and pulse[6]==4900 and pulse[14]==3100)
'''
        program += "print('NATIVE_DRIVE_INDEPENDENT_REFERENCE=PASS')\n"
        with tempfile.TemporaryDirectory(prefix="ion_processor_drive_test_") as directory:
            script = Path(directory) / "check.lua"
            script.write_text(program, encoding="utf-8")
            result = subprocess.run([lua, str(script)], capture_output=True, text=True, timeout=20, check=False, cwd=directory)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NATIVE_DRIVE_INDEPENDENT_REFERENCE=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
