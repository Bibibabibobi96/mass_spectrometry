"""Exercise actual Lua node traversal for every physical aperture normal."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = Path(__file__).with_name("verify_aperture_topology.lua")
LUA = shutil.which("lua") or str(Path("C:/Program Files/SIMION-2020/lua.exe"))

STUB = r"""
local axis, mode = arg[2], arg[3]
local n = ({x=1,y=2,z=3})[axis]
local transverse = {}
for i=1,3 do if i~=n then transverse[#transverse+1]=i end end
local u,v=transverse[1],transverse[2]
simion={pas={open=function()
  return {nx=15,ny=15,nz=15,point=function(_,x,y,z)
    local p={x,y,z}
    local inside=p[u]>=3 and p[u]<=7 and p[v]>=4 and p[v]<=8
    if os.getenv('SIMION_APERTURE_BOOLEAN_BOUNDARY_POLICY')=='exclude_shape_inside_only_v1' then
      inside=p[u]>3 and p[u]<7 and p[v]>4 and p[v]<8
    end
    local metal=p[n]>2 and p[n]<6 and not inside
    if mode=='blocked' and p[n]==4 and inside then metal=true end
    if mode=='guard_gap' and p[n]==4 and p[u]==2 then metal=false end
    return 0,metal
  end}
end}}
dofile(arg[1])
"""


@unittest.skipUnless(Path(LUA).is_file(), "Plain Lua runtime unavailable; no solver is required")
class ApertureTopologyTests(unittest.TestCase):
    def run_case(self, axis: str, mode: str = "open", policy: str = "exclude_shape_inside_or_on_v1") -> tuple[subprocess.CompletedProcess, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stub, report = root / "stub.lua", root / "audit.json"
            stub.write_text(STUB, encoding="utf-8")
            axes = list("xyz")
            cells, origins = dict(zip(axes, (.1, .2, .3))), dict(zip(axes, (-1, -2, -3)))
            transverse = [a for a in axes if a != axis]
            center_indices = {axis: 4, transverse[0]: 5, transverse[1]: 6}
            environment = dict(os.environ)
            values = {
                "PA_PATH": "fixture.pa", "REPORT_PATH": str(report), "NORMAL_AXIS": axis,
                "FLANGE_MIN_MM": origins[axis] + 2*cells[axis],
                "FLANGE_MAX_MM": origins[axis] + 6*cells[axis],
                "WIDTH_MM": 4*cells[transverse[0]], "HEIGHT_MM": 4*cells[transverse[1]],
                "BOOLEAN_BOUNDARY_POLICY": policy,
            }
            for a in axes:
                values[f"ORIGIN_{a.upper()}_MM"] = origins[a]
                values[f"CELL_MM_{a.upper()}"] = cells[a]
                values[f"CENTER_{a.upper()}_MM"] = origins[a] + center_indices[a]*cells[a]
            environment.update({"SIMION_APERTURE_"+k: str(v) for k, v in values.items()})
            completed = subprocess.run([LUA, str(stub), str(VERIFIER), axis, mode], env=environment,
                                       capture_output=True, text=True, check=False, cwd=root, timeout=30)
            return completed, json.loads(report.read_text()) if report.exists() else {}

    def test_open_columns_follow_actual_axis_with_anisotropic_mesh(self):
        for axis in "xyz":
            with self.subTest(axis=axis):
                process, report = self.run_case(axis)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(report["normal_axis"], axis)
                self.assertEqual(report["open_column_count"], 25)
                self.assertTrue(report["guard_electrode_check_passed"])
                transverse = [a for a in "xyz" if a != axis]
                self.assertEqual(report["index_bounds"], {axis: [2, 6], transverse[0]: [3, 7], transverse[1]: [4, 8]})

    def test_blocked_aperture_and_broken_guard_fail_on_each_axis(self):
        for axis in "xyz":
            for mode in ("blocked", "guard_gap"):
                with self.subTest(axis=axis, mode=mode):
                    process, report = self.run_case(axis, mode)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertEqual(report["status"], "FAIL")
                    if mode == "blocked":
                        self.assertEqual(report["open_column_count"], 0)
                    else:
                        self.assertFalse(report["guard_electrode_check_passed"])

    def test_inside_only_cut_keeps_edge_nodes_and_audits_actual_interior(self):
        for axis in "xyz":
            with self.subTest(axis=axis):
                process, report = self.run_case(axis, policy="exclude_shape_inside_only_v1")
                self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
                self.assertEqual(report["open_column_count"], 9)
                self.assertEqual(report["boolean_boundary_policy"], "exclude_shape_inside_only_v1")


if __name__ == "__main__":
    unittest.main()
