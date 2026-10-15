"""Run the production IOB builder with path-checking standalone Lua stubs.

Fixtures contain inert text, not genuine PA/IOB data. No SIMION application,
electrode solve, workbench load, or particle flight is executed by these tests.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal


PROJECT = Path(__file__).resolve().parents[1]

LUA_HARNESS = r'''
local builder_path=assert(arg[1])
local directory=assert(builder_path:match('^(.*[/\\])'))
local normalize=function(path) return path:gsub('\\','/') end
local absolute=function(path)
  return path:match('^%a:[/\\]') or path:match('^/') or path:match('^\\\\')
end
assert(absolute(builder_path),'test must invoke the builder by absolute script path')
local original_loadfile=loadfile
local c=assert(original_loadfile(directory..'frozen_config.lua'))()
local expected={
  seed=c.workbench_seed_path,
  pa=c.native_field.directory..'/processor.pa0',
  fly2=directory..'processor.fly2',
  iob=directory..'processor.iob',
  config=directory..'frozen_config.lua',
}
local calls={}
local virtual_cwd='unrelated_initial_gui_cwd'
local function check(kind,path)
  assert(type(path)=='string' and absolute(path),kind..' must be absolute; cwd='..virtual_cwd)
  assert(normalize(path)==normalize(expected[kind]),
    kind..' targets the wrong directory: '..tostring(path))
  calls[#calls+1]=kind
end
-- Catch config lookup against the process CWD as well as post-load paths.
loadfile=function(path)
  check('config',path)
  return original_loadfile(path)
end
local instance={pa={}}
local resized=false
function instance.pa:load(path)
  assert(virtual_cwd=='public_seed_directory','PA must load after seed')
  check('pa',path)
  local f=assert(io.open(path,'r'));f:close()
end
function instance:_debug_update_size() resized=true end
function instance:pa_to_wb_orient(x,y,z)
  -- Independent ordered Euler oracle: rt around x, el around z, az around y.
  local rt,el,az=math.rad(self.rt),math.rad(self.el),math.rad(self.az)
  y,z=math.cos(rt)*y-math.sin(rt)*z,math.sin(rt)*y+math.cos(rt)*z
  x,y=math.cos(el)*x-math.sin(el)*y,math.sin(el)*x+math.cos(el)*y
  return math.cos(az)*x+math.sin(az)*z,y,-math.sin(az)*x+math.cos(az)*z
end
function instance:pa_to_wb_coords(x,y,z)
  local a,b,d=self:pa_to_wb_orient(x,y,z)
  local grid=c.native_projection.grid_mm
  return self.x+a*grid,self.y+b*grid,self.z+d*grid
end
local wb={instances={instance}}
function wb:load(path)
  check('seed',path)
  local f=assert(io.open(path,'r'));f:close()
  -- Model SIMION's documented/observed CWD side effect without changing the
  -- OS process directory. Every later path is required to resolve absolutely.
  virtual_cwd='public_seed_directory'
end
function wb:load_particles(path)
  assert(virtual_cwd=='public_seed_directory','seed load must precede particles')
  check('fly2',path)
  local f=assert(io.open(path,'r'));f:close()
end
function wb:save(path)
  assert(virtual_cwd=='public_seed_directory','IOB save must survive changed cwd')
  check('iob',path)
  local f=assert(io.open(path,'w'))
  f:write('INERT TEST FIXTURE - NOT A SIMION WORKBENCH\n');f:close()
end
simion={wb=wb}
assert(original_loadfile(builder_path))()
assert(table.concat(calls,',')=='config,seed,pa,fly2,iob','builder operation order/path inventory changed')
assert(resized,'builder must update native PA instance dimensions')
if c.coordinate_transform then
  assert(instance.x==4 and instance.y==-1 and instance.z==13.8,'project instance origin')
  assert(instance.az==0 and instance.el==90 and instance.rt==-90,'project instance rotation')
else
  assert(instance.x==-1 and instance.y==-4 and instance.z==-4,'legacy local origin')
  assert(instance.az==0 and instance.el==0 and instance.rt==0,'legacy rotation')
end
assert(instance.scale==1 and instance.ox==0 and instance.oy==0 and instance.oz==0)
print('WORKBENCH_PATHS_PASS')
'''


class WorkbenchPathTests(unittest.TestCase):
    """Public seed loading must not redirect particle lookup or IOB output."""

    def run_path_fixture(self, *, external_native_field: bool, transformed: bool = False) -> None:
        """Execute the actual builder with isolated inert assets and stub APIs."""
        executable = os.environ.get("SIMION_LUA_EXE") or shutil.which("lua")
        if executable is None:
            installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
            if installed.is_file():
                executable = str(installed)
        if executable is None:
            self.skipTest("Standalone Lua unavailable; set SIMION_LUA_EXE for builder path checks")
        with tempfile.TemporaryDirectory(prefix="ion_processor_workbench_paths_") as temporary:
            root = Path(temporary)
            solver = root / "run output" / "simion"
            seed_dir = root / "public seed assets"
            unrelated = root / "unrelated GUI directory"
            field = root / "earlier native field" if external_native_field else solver
            for path in (solver, seed_dir, unrelated, field):
                path.mkdir(parents=True, exist_ok=True)
            seed = seed_dir / "1_instance_seed.iob"
            seed.write_text("INERT SEED COPY FIXTURE\n", encoding="utf-8")
            (field / "processor.pa0").write_text("INERT PA PATH FIXTURE\n", encoding="utf-8")
            (solver / "processor.fly2").write_text("INERT PARTICLE PATH FIXTURE\n", encoding="utf-8")
            config = {"workbench_seed_path": str(seed), "native_field": {"directory": str(field)},
                      "native_projection": {"origin_mm": [-1, -4, -4], "grid_mm": 0.1}}
            if transformed:
                config["coordinate_transform"] = __import__("json").loads((PROJECT / "config/coordinate_transform.json").read_text())
            (solver / "frozen_config.lua").write_text("return " + lua_literal(config), encoding="utf-8")
            builder = solver / "build_workbench.lua"
            shutil.copyfile(PROJECT / "simion/build_workbench.lua", builder)
            harness = root / "check_paths.lua"
            harness.write_text(LUA_HARNESS, encoding="utf-8")
            result = subprocess.run([executable, str(harness), str(builder)], cwd=unrelated,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                                    check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WORKBENCH_PATHS_PASS", result.stdout)
            self.assertTrue((solver / "processor.iob").is_file())
            self.assertFalse((seed_dir / "processor.iob").exists())
            self.assertFalse((unrelated / "processor.iob").exists())
            self.assertEqual(seed.read_text(encoding="utf-8"), "INERT SEED COPY FIXTURE\n")

    def test_builder_keeps_local_field_and_output_paths_absolute(self) -> None:
        self.run_path_fixture(external_native_field=False)

    def test_builder_asserts_transformed_native_pose(self) -> None:
        self.run_path_fixture(external_native_field=False, transformed=True)

    def test_builder_preserves_external_field_and_local_output_ownership(self) -> None:
        self.run_path_fixture(external_native_field=True)


if __name__ == "__main__":
    unittest.main()
