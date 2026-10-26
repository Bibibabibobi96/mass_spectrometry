from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
FAST_ADJUST_EXPORTER = ROOT / "export_fast_adjusted_standalone_pa.lua"
COMPOSER = ROOT / "compose_standalone_pa.lua"
DIRICHLET_OPERATING_PATCH = ROOT / "build_dirichlet_patch_operating_pa.lua"
SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
SOLVER_AUTHORIZED = os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"
LUA = Path(shutil.which("lua") or r"C:\Program Files\SIMION-2020\lua.exe")


@unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
class OperatingPatchStoppingTest(unittest.TestCase):
    """Exercise the real Lua helper with a PA double; never invoke SIMION."""

    def run_helper(self, *options: str) -> subprocess.CompletedProcess[str]:
        harness = r'''
local helper=arg[1]
local options={}
for i=2,#arg do options[#options+1]=arg[i] end
local calls=0
local source={dx_mm=1,dy_mm=1,dz_mm=1}
function source:inside_vc() return true end
function source:potential_vc() return 7 end
function source:close() end
local target={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
function target:point(x,y,z,value,metal)
  if value==nil then return 1,x==1 and y==1 and z==1 end
  if x==1 and y==1 and z==1 then assert(value==11 and metal) end
end
function target:save() end
function target:close() end
function target:refine(options)
  calls=calls+1
  if options==nil then print('REFINE_CALL=default')
  else assert(options.convergence==1e-5);print('REFINE_CALL=explicit') end
end
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path)
  print('OPEN_CALLED')
  return path=='parent.pa' and source or target
end
arg={'raw.pa#','patch.pa0','parent.pa','0,0,0','0,0,0','11'}
for _,value in ipairs(options) do arg[#arg+1]=value end
dofile(helper)
assert(calls==1,'one and only one Refine call required')
'''
        with tempfile.TemporaryDirectory(prefix="operating-patch-lua-") as directory:
            path = Path(directory) / "harness.lua"
            path.write_text(harness, encoding="utf-8")
            return subprocess.run(
                [str(LUA), str(path), str(DIRICHLET_OPERATING_PATCH), *options],
                cwd=directory, capture_output=True, text=True, encoding="utf-8",
                check=False, timeout=30,
            )

    def test_default_stopping_preserves_no_argument_refine(self) -> None:
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REFINE_CALL=default", result.stdout)
        self.assertIn("refine_convergence=installed_default", result.stdout)

    def test_explicit_stopping_is_forwarded_once(self) -> None:
        result = self.run_helper("1e-5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REFINE_CALL=explicit", result.stdout)
        self.assertIn("refine_convergence=1e-05", result.stdout.lower())

    def test_parent_patch_restores_only_synthetic_faces_and_keeps_sampled_potentials(self) -> None:
        harness = r'''
local helper=arg[1]
local function key(x,y,z) return x..','..y..','..z end
local function physical(x,y,z)
 return (x==1 and y==1 and z==1) or (x==0 and y==1 and z==1)
   or (x==3 and y==2 and z==2)
end
local function raw_value(x,y,z)
 if x==0 then return 2 elseif x==3 then return 0 else return 1 end
end
local raw={}
function raw:point(x,y,z) return raw_value(x,y,z),physical(x,y,z) end
function raw:close() end
local values,flags,solved_values={},{},{}
local target={nx=4,ny=4,nz=4,dx_mm=.5,dy_mm=.25,dz_mm=.75}
function target:point(x,y,z,value,metal)
 local k=key(x,y,z)
 if value==nil then
  if values[k]~=nil then return values[k],flags[k] end
  return raw:point(x,y,z)
 end
 values[k],flags[k]=value,metal
end
function target:save() end
function target:close() end
local samples,refines=0,0
local parent={dx_mm=2,dy_mm=4,dz_mm=.5}
function parent:inside_vc(x,y,z)
 -- (patch_origin + local_gu * patch_pitch - source_origin)/source_pitch.
 assert(x>=4 and x<=4.75 and y>=4 and y<=4.1875 and z>=48 and z<=52.5)
 return true
end
function parent:potential_vc(x,y,z)
 samples=samples+1
 return x+2*y+3*z
end
function parent:close() end
function parent:save() error('parent must remain unchanged') end
function target:refine(options)
 refines=refines+1;assert(options.convergence==1e-5)
 for z=0,3 do for y=0,3 do for x=0,3 do
  local k=key(x,y,z)
  local boundary=x==0 or y==0 or z==0 or x==3 or y==3 or z==3
  if physical(x,y,z) then
   assert(flags[k] and values[k]==(x==0 and -17 or x==3 and 0 or 11))
  elseif boundary then
   assert(flags[k] and values[k]==(4+x*.25)+2*(4+y*.0625)+3*(48+z*1.5),
     'parent boundary voltage or coordinate mapping changed')
  else
   assert(not flags[k]);values[k]=9+x/10+y/100+z/1000
  end
  solved_values[k]=values[k]
 end end end
end
local raw_opens,parent_opens=0,0
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path)
 if path=='parent.pa' then parent_opens=parent_opens+1;return parent end
 if path=='raw.pa#' then raw_opens=raw_opens+1;return raw_opens==1 and target or raw end
 assert(path=='patch.pa0');return target
end
arg={'raw.pa#','patch.pa0','parent.pa','2,4,6','10,20,30','11,-17','1e-5'}
dofile(helper)
assert(refines==1 and parent_opens==1 and raw_opens==2 and samples==54)
for z=0,3 do for y=0,3 do for x=0,3 do
 local k=key(x,y,z)
 assert(flags[k]==physical(x,y,z),'synthetic faces must not remain collision electrodes')
 assert(values[k]==solved_values[k],'mask restoration changed a solved potential')
end end end
print('PARENT_BOUNDARY_MASK=PASS')
'''
        with tempfile.TemporaryDirectory(prefix="parent-boundary-lua-") as directory:
            path = Path(directory) / "harness.lua"
            path.write_text(harness, encoding="utf-8", newline="\n")
            result = subprocess.run([str(LUA), str(path), str(DIRICHLET_OPERATING_PATCH)],
                                    cwd=directory, capture_output=True, text=True, encoding="utf-8",
                                    check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PARENT_BOUNDARY_MASK=PASS", result.stdout)

    def test_invalid_stopping_and_extra_argument_fail_before_pa_open(self) -> None:
        for options in (("0",), ("-1",), ("nan",), ("inf",), ("junk",), ("1e-5", "extra")):
            with self.subTest(options=options):
                result = self.run_helper(*options)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("OPEN_CALLED", result.stdout)
                self.assertIn("argument 8" if len(options) == 2 else "convergence", result.stderr)

    def test_zero_far_boundary_needs_no_parent_and_restores_only_synthetic_flags(self) -> None:
        harness = r'''
local helper=arg[1]
local function key(x,y,z) return x..','..y..','..z end
local function physical(x,y,z) return (x==1 and y==1 and z==1) or (x==0 and y==1 and z==1) end
local raw={}
function raw:point(x,y,z) return x==1 and y==1 and z==1 and 1 or 0,physical(x,y,z) end
function raw:close() end
local values,flags,solved_values={},{},{}
local target={nx=4,ny=4,nz=4,dx_mm=.2,dy_mm=.2,dz_mm=.2}
function target:point(x,y,z,value,metal)
 local k=key(x,y,z)
 if value==nil then
  if values[k]~=nil then return values[k],flags[k] end
  return raw:point(x,y,z)
 end
 values[k],flags[k]=value,metal
end
function target:save() end
function target:close() end
function target:refine(options)
 assert(options.convergence==1e-5)
 assert(values[key(1,1,1)]==11 and values[key(0,1,1)]==0)
 for z=0,3 do for y=0,3 do for x=0,3 do
  local k=key(x,y,z)
  local boundary=x==0 or y==0 or z==0 or x==3 or y==3 or z==3
  if boundary then assert(flags[k] and values[k]==0,'six zero Dirichlet faces required') end
  if not physical(x,y,z) then values[k]=7+x/10+y/100+z/1000 end
  solved_values[k]=values[k]
 end end end
end
local raw_opens=0
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path)
 if path=='raw.pa#' then raw_opens=raw_opens+1;return raw_opens==1 and target or raw end
 assert(path=='patch.pa0','zero boundary must not open a parent PA')
 return target
end
arg={'raw.pa#','patch.pa0','zero_dirichlet','0,0,0','0,0,0','11','1e-5'}
dofile(helper)
assert(raw_opens==2)
for z=0,3 do for y=0,3 do for x=0,3 do
 local k=key(x,y,z)
 assert(flags[k]==physical(x,y,z),'original physical mask must be restored exactly')
 assert(values[k]==solved_values[k],'mask restoration must preserve every solved potential')
end end end
print('ZERO_BOUNDARY_MASK=PASS')
'''
        with tempfile.TemporaryDirectory(prefix="zero-boundary-lua-") as directory:
            path = Path(directory) / "harness.lua"
            path.write_text(harness, encoding="utf-8")
            result = subprocess.run([str(LUA), str(path), str(DIRICHLET_OPERATING_PATCH)],
                                    cwd=directory, capture_output=True, text=True, encoding="utf-8",
                                    check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ZERO_BOUNDARY_MASK=PASS", result.stdout)


    def test_native_neumann_keeps_open_edges_and_physical_mask_with_one_refine(self) -> None:
        harness = r'''
local helper=arg[1]
local function key(x,y,z) return x..','..y..','..z end
local function metal(x,y,z) return y==1 and z==1 and (x==0 or x==1) end
local values,flags={},{},{}
local target={nx=3,ny=3,nz=3,dx_mm=.2,dy_mm=.3,dz_mm=.4}
function target:point(x,y,z,value,physical)
 local k=key(x,y,z)
 if value==nil then return values[k] or (x==0 and 2 or 1),metal(x,y,z) end
 values[k],flags[k]=value,physical
end
function target:save() end
function target:close() end
local calls=0
function target:refine(options)
 calls=calls+1;assert(options.convergence==1e-5)
 for z=0,2 do for y=0,2 do for x=0,2 do
  local k=key(x,y,z)
  assert(flags[k]==metal(x,y,z),'native open edges may not become electrodes')
  if metal(x,y,z) then assert(values[k]==(x==0 and -17 or 11))
  else assert(values[k]==0) end
 end end end
end
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path)
 assert(path=='raw.pa#' or path=='patch.pa0','no parent PA may be opened')
 return target
end
arg={'raw.pa#','patch.pa0','zero_neumann','0,0,0','0,0,0','11,-17','1e-5'}
dofile(helper)
assert(calls==1)
print('NATIVE_NEUMANN_MASK=PASS')
'''
        with tempfile.TemporaryDirectory(prefix="neumann-lua-") as directory:
            path = Path(directory) / "harness.lua"
            path.write_text(harness, encoding="utf-8", newline="\n")
            result = subprocess.run([str(LUA), str(path), str(DIRICHLET_OPERATING_PATCH)],
                                    cwd=directory, capture_output=True, text=True, encoding="utf-8",
                                    check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NATIVE_NEUMANN_MASK=PASS", result.stdout)


class StandalonePaToolStaticContractTest(unittest.TestCase):
    def test_dirichlet_operating_patch_accepts_solved_standalone_parent(self) -> None:
        source = DIRICHLET_OPERATING_PATCH.read_text(encoding="utf-8")
        self.assertIn("SOURCE_OPERATING_PA_OR_PA0", source)
        self.assertIn("source_path:match('%.pa0$') or source_path:match('%.pa$')", source)
        self.assertIn("source:potential_vc", source)
        self.assertIn("solved:refine()", source)

    def test_fast_adjust_export_contract_is_fail_closed_and_does_not_refine(self) -> None:
        source = FAST_ADJUST_EXPORTER.read_text(encoding="utf-8")
        self.assertIn("source_pa:fast_adjust(voltages)", source)
        self.assertIn("source_pa.electrode_numbers", source)
        self.assertIn("operating-point table is incomplete", source)
        self.assertIn("simion.pas:open()", source)
        self.assertIn("output_pa:copy(source_pa)", source)
        self.assertIn("if output_pa.copy then", source)
        self.assertIn("same-prefix physical geometry PA# is missing", source)
        self.assertIn('"policy_id":"physical_geometry_boundary_flags_v1"', source)
        self.assertIn("output_pa:electrode(ix, iy, iz, false)", source)
        self.assertIn("standalone export lost a physical boundary electrode", source)
        self.assertIn("disjoint standalone boundary traversal is incomplete", source)
        self.assertNotIn("for x, y, z in output_pa:points() do\n  local physical", source)
        self.assertNotIn("pcall", source)
        self.assertIn("output_pa.refined = true", source)
        self.assertIn("output_pa.refinable = false", source)
        self.assertIn("surface-enhanced PA families are unsupported", source)
        self.assertIn("standalone output already exists", source)
        self.assertNotIn(":refine", source)
        self.assertNotIn("source_pa:save(output)", source)

    def test_composer_uses_standalone_inputs_and_preserves_base_flags(self) -> None:
        source = COMPOSER.read_text(encoding="utf-8")
        self.assertIn("must use a standalone .pa or neutral .bin suffix", source)
        self.assertIn("neutral temporary name", source)
        self.assertIn("output_pa:copy(base_pa)", source)
        self.assertIn("output_pa:potential_add(x, y, z, delta)", source)
        self.assertIn("potential + delta, is_electrode", source)
        self.assertIn("for x, y, z in output_pa:points() do", source)
        self.assertIn("delta = delta + response.coefficient * response.pa:potential(x, y, z)", source)
        self.assertLess(
            source.index("for x, y, z in output_pa:points() do"),
            source.index("output_pa:potential_add(x, y, z, delta)"),
        )
        self.assertIn("response PA grid, symmetry, or potential type differs", source)
        self.assertIn("output_pa.refined = true", source)
        self.assertIn("output_pa.refinable = false", source)
        self.assertIn("surface=none is required", source)
        self.assertIn("standalone output already exists", source)
        self.assertNotIn(":refine", source)
        self.assertNotIn("assert(base_pa.refined", source)
        self.assertNotIn("assert(response.pa.refined", source)

    def test_real_solver_tests_are_explicitly_gated(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn('os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"', source)
        self.assertIn("@unittest.skipUnless", source)


BUILD_FAMILY_LUA = r"""
local directory = assert(arg[1], 'temporary directory required')
local separator = package.config:sub(1, 1)
simion.pas:close()
local pa = assert(simion.pas:open(), 'cannot create toy PA family')
pa:size(7, 7, 7)
pa.symmetry = '3dplanar'
pa.dx_mm, pa.dy_mm, pa.dz_mm = 0.5, 0.75, 1.25
pa.refinable = true
for x, y, z in pa:points() do
  if x == 0 then
    pa:point(x, y, z, 1, true)
  elseif x == 6 then
    pa:point(x, y, z, 2, true)
  else
    pa:point(x, y, z, 0, false)
  end
end
pa.filename = directory .. separator .. 'toy.pa#'
pa:save()
pa:refine {}
pa:close()
print('TOY_PA_FAMILY=PASS')
"""


CHECK_OPERATING_POINT_LUA = r"""
local path = assert(arg[1], 'standalone PA required')
local expected_left = assert(tonumber(arg[2]), 'left value required')
local expected_right = assert(tonumber(arg[3]), 'right value required')
simion.pas:close()
local pa = assert(simion.pas:open(path), 'cannot open standalone PA')
assert(#simion.pas == 1, 'output is not detached from a PA family')
local left, left_electrode = pa:point(0, 3, 3)
local right, right_electrode = pa:point(6, 3, 3)
local middle, middle_electrode = pa:point(3, 3, 3)
assert(math.abs(left - expected_left) < 1e-9 and left_electrode,
       'left electrode potential or flag differs')
assert(math.abs(right - expected_right) < 1e-9 and right_electrode,
       'right electrode potential or flag differs')
assert(not middle_electrode, 'base non-electrode flag was not preserved')
pa:close()
print(string.format('OPERATING_POINT=PASS middle=%.17g', middle))
"""


@unittest.skipUnless(
    SIMION.is_file() and SOLVER_AUTHORIZED,
    "real SIMION regression requires the public host lease and explicit authorization",
)
class StandalonePaToolAuthorizedSolverTest(unittest.TestCase):
    def _run(
        self, *arguments: Path | str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [str(SIMION), "--nogui", "--noprompt", "lua", *(str(x) for x in arguments)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=ROOT,
        )
        if check and completed.returncode != 0:
            self.fail(
                "SIMION command failed "
                f"({completed.returncode}): {completed.args!r}\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        return completed

    def test_complete_fast_adjust_export_and_standalone_composition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_standalone_tools_") as temporary:
            root = Path(temporary)
            builder = root / "build.lua"
            checker = root / "check.lua"
            builder.write_text(BUILD_FAMILY_LUA, encoding="utf-8")
            checker.write_text(CHECK_OPERATING_POINT_LUA, encoding="utf-8")
            self.assertIn("TOY_PA_FAMILY=PASS", self._run(builder, root).stdout)

            controller = root / "toy.pa0"
            base = root / "base.pa"
            response = root / "response.pa"
            composed = root / "composed.pa"
            base_receipt = root / "base.boundary_mask.json"
            response_receipt = root / "response.boundary_mask.json"
            exported = self._run(
                FAST_ADJUST_EXPORTER, controller, base, base_receipt, "1=3", "2=7"
            )
            self.assertIn("FAST_ADJUSTED_STANDALONE_PA=PASS", exported.stdout)
            self.assertIn(
                "FAST_ADJUSTED_STANDALONE_PA=PASS",
                self._run(
                    FAST_ADJUST_EXPORTER,
                    controller,
                    response,
                    response_receipt,
                    "1=1",
                    "2=0",
                ).stdout,
            )
            self.assertIn(
                '"policy_id":"physical_geometry_boundary_flags_v1"',
                base_receipt.read_text(encoding="utf-8"),
            )
            self.assertIn("OPERATING_POINT=PASS", self._run(checker, base, "3", "7").stdout)

            combined = self._run(COMPOSER, base, composed, f"{response},2")
            self.assertIn("STANDALONE_PA_COMPOSITION=PASS", combined.stdout)
            self.assertIn("OPERATING_POINT=PASS", self._run(checker, composed, "5", "7").stdout)

    def test_incomplete_fast_adjust_table_is_rejected_without_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_standalone_incomplete_") as temporary:
            root = Path(temporary)
            builder = root / "build.lua"
            builder.write_text(BUILD_FAMILY_LUA, encoding="utf-8")
            self._run(builder, root)
            output = root / "must_not_exist.pa"
            completed = self._run(
                FAST_ADJUST_EXPORTER,
                root / "toy.pa0",
                output,
                root / "must_not_exist.boundary_mask.json",
                "1=3",
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "operating-point table is incomplete",
                completed.stdout + completed.stderr,
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
