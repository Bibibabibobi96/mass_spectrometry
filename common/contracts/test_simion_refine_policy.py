"""Reject unbound Refine overrides while preserving documented numerical inputs."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
class SimionRefinePolicyTests(unittest.TestCase):
    """Native adapter option forwarding and invalid numerical input behavior."""

    def test_official_skipped_point_option_reaches_fake_pa_without_changing_defaults(self) -> None:
        lua = Path("C:/Program Files/SIMION-2020/lua.exe")
        if not lua.is_file():
            self.skipTest("installed Lua interpreter required; no SIMION process")
        adapter = REPOSITORY_ROOT / "common/simion/build_dirichlet_patch_basis.lua"
        code = r'''
local adapter,mode=arg[1],arg[2]
local source={dx_mm=1,dy_mm=1,dz_mm=1}
function source:inside_vc() return true end
function source:potential_vc() return 3 end
function source:close() end
local target={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
function target:point(x,y,z,p,e) if p==nil then return 0,false end end
function target:save() end
function target:close() end
function target:refine(options)
 if mode=='default' then assert(options==nil)
 elseif mode=='convergence' then assert(options.convergence==1e-5 and options.skipped_point==nil)
 else assert(options.convergence==1e-5 and options.skipped_point==(mode=='1')) end
 print('MOCK_REFINE_POLICY=PASS')
end
simion={pas={}}
function simion.pas:open(path) return path=='target.pa' and target or source end
arg={'target.pa','source.pa','0,0,0','0,0,0','x_mirror_five_faces'}
if mode~='default' then arg[6]='1e-5' end
if mode~='default' and mode~='convergence' then arg[7]=mode end
dofile(adapter)
'''
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.lua"
            fixture.write_text(code, encoding="utf-8")
            for mode in ("default", "convergence", "0", "1", "false", "2"):
                with self.subTest(mode=mode):
                    run = subprocess.run([str(lua), str(fixture), str(adapter), mode], cwd=directory,
                                         capture_output=True, text=True, timeout=30)
                    if mode in ("false", "2"):
                        self.assertNotEqual(run.returncode, 0)
                        self.assertIn("must be 0 or 1", run.stderr)
                    else:
                        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
                        self.assertIn("MOCK_REFINE_POLICY=PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
