"""Actual canonical IOB Lua over inert indexed PA objects; never launch SIMION."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.backends.simion.source import lua_value

LUA = Path("C:/Program Files/SIMION-2020/lua.exe")


HARNESS = r"""local spec=dofile(arg[1])
local mode=arg[2]
local failure=arg[3]
local function norm(path)return path:gsub('\\','/')end
local function pa(path)
 local result={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,electrode_numbers=spec.instances[1].response_ids}
 function result:size(x,y,z)assert(x==3 and y==3 and z==3)end
 function result:close()end
 function result:load()self.path=self.filename end
 function result:save(path)local f=assert(io.open(path,'wb'));f:write('INERT_BOOTSTRAP_NOT_PA');f:close()end
 function result:point(x,y,z)return 1,x==0 end
 function result:surface_info()if failure=='surface' then return .5,nil,nil end;return .25,nil,nil end
 setmetatable(result,{__index=function(t,k)if k=='path'then return rawget(t,'_path')end end,
  __newindex=function(t,k,v)if k=='path'then rawset(t,'_path',norm(v))else rawset(t,k,v)end end})
 if path then result.path=path end
 if failure=='mapping'then result.electrode_numbers={1,2,3,11,12,21,99}end
 return result
end
local slots={}
local instances=newproxy(true)
getmetatable(instances).__index=slots
getmetatable(instances).__newindex=slots
getmetatable(instances).__len=function()return 1 end
simion={pas={open=function(_,path)return pa(path)end,close=function()end},wb={instances=instances}}
function simion.wb:load_particles(path)
 local f=assert(io.open(path,'rb'));local content=f:read('*a');f:close()
 assert(content~='','particle source/control missing')
end
function simion.wb:save(path)
 local f=assert(io.open(path,'wb'));f:write('INERT_IOB_NOT_NATIVE');f:close()
 -- Actual canonical writer must restore source companions after save.
 f=assert(io.open(path:gsub('%.iob$','.fly2'),'wb'));f:write('particles{coordinates=0,}');f:close()
end
function simion.command(command)
 assert(not command:find('refine')and not command:find('fastadj')and not command:find(' fly'))
 local row=spec.instances[1]
 local path=mode:match('^verify')and row.path or spec.bootstrap_paths[1]
 local item={pa=pa(path),x=0,y=0,z=0,az=0,el=0,rt=0,scale=1,ox=0,oy=0,oz=0}
 function item:_debug_update_size()end
 function item:pa_to_wb_coords(x,y,z)return x,y,z end
 function item:pa_to_wb_orient(x,y,z)return x,y,z end
 if failure=='placed'then
  local p=row.placement
  item.x,item.y,item.z,item.az,item.el,item.rt=p.x_mm,p.y_mm,p.z_mm,p.az_deg,p.el_deg,p.rt_deg
  function item:pa_to_wb_orient(x,y,z)
   local a,e,r=self.az*math.pi/180,self.el*math.pi/180,self.rt*math.pi/180
   local ca,sa,ce,se,cr,sr=math.cos(a),math.sin(a),math.cos(e),math.sin(e),math.cos(r),math.sin(r)
   -- Independent official Ry(az)Rz(el)Rx(rt) oracle, not production rotation rows.
   return ca*ce*x+(-ca*se*cr+sa*sr)*y+(ca*se*sr+sa*cr)*z,
          se*x+ce*cr*y-ce*sr*z,
          -sa*ce*x+(sa*se*cr+ca*sr)*y+(-sa*se*sr+ca*cr)*z
  end
  function item:pa_to_wb_coords(x,y,z)
   local dx,dy,dz=self:pa_to_wb_orient(x*row.grid.dx_mm,y*row.grid.dy_mm,z*row.grid.dz_mm)
   return dx+self.x,dy+self.y,dz+self.z
  end
 end
 slots[1]=item
end
arg={arg[1],mode,arg[5]}
if mode=='build'or mode=='verify'then
 assert(loadfile(arg[3]..'/build_tracking_iob.lua'))()
elseif mode=='build_model'or mode=='verify_model'then
 assert(loadfile(arg[3]..'/build_model_iob.lua'))()
else
 assert(loadfile(arg[3]..'/iob_core.lua'))()(spec,mode,function(path)return path end)
end
"""


@unittest.skipUnless(LUA.is_file(), "plain Lua unavailable; no native fallback")
class DualConeIobTests(unittest.TestCase):
    def test_actual_shared_writer_build_reopen_source_free_and_tracking_and_rf_control(self):
        for role in (
            "dual_cone_tracking_iob",
            "dual_cone_geometry_iob",
            "dual_cone_model",
            "independent_rf_tracking_iob",
        ):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = root / (
                    "original.pa#" if role in {"dual_cone_geometry_iob", "dual_cone_model"} else "original.pa0"
                )
                raw.write_bytes(b"INERT_ORIGINAL_PA")
                surface = root / "original.pa-surf"
                surface.write_bytes(b"INERT_SURFACE")
                witness = root / "surface.csv"
                witness.write_text("0,0,0,.25,nil,nil\n")
                iob = root / "instrument.iob"
                seed = root / "seed/one.iob"
                seed.parent.mkdir()
                seed.write_bytes(structural_seed_path(1).read_bytes())
                bootstrap = seed.parent / "iob_seed_placeholder_01.pa0"
                control = root / "empty.fly2"
                control.write_text("particles{coordinates=0,}")
                if role not in {"dual_cone_geometry_iob", "dual_cone_model"}:
                    iob.with_suffix(".lua").write_text("-- EXPLICIT_INERT_PROGRAM")
                    iob.with_suffix(".fly2").write_text("particles{standard_beam{n=2}}")
                row = dict(
                    role="rf" if role == "independent_rf_tracking_iob" else "dual_cone",
                    instance_index=1,
                    priority_number=1,
                    path=str(raw),
                    fractional_surface=str(surface),
                    surface_witnesses=str(witness),
                    response_ids=[1] if role == "independent_rf_tracking_iob" else [1, 2, 3, 11, 12, 21, 22],
                    grid=dict(nx=3, ny=3, nz=3, dx_mm=1, dy_mm=1, dz_mm=1),
                    rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    placement=dict(x_mm=0, y_mm=0, z_mm=0, az_deg=0, el_deg=0, rt_deg=0, scale=1),
                    physical_samples=[dict(gu=[0, 0, 0], metal=True, electrode_id=1), dict(gu=[1, 0, 0], metal=False)],
                )
                spec = dict(
                    schema_version=1,
                    role="dual_cone_geometry_iob" if role == "dual_cone_model" else role,
                    instances=[row],
                    seed_iob=str(seed),
                    output_iob=str(iob),
                    response_fields=[],
                    bootstrap_paths=[str(bootstrap)],
                    empty_particle_control=str(control),
                )
                if role == "dual_cone_model":
                    from common.contracts.test_dual_cone_stages import model
                    from msplatform.backends.simion.dual_cone_stages import render_model_stage_configuration

                    configuration = root / "model_drive_configuration.lua"
                    configuration.write_text(render_model_stage_configuration(model()))
                    spec["model"] = dict(
                        configuration=str(configuration),
                        consumer=str(native_resource_path("model_drive.lua")),
                        rf_drive=str(native_resource_path("rf_drive.lua")),
                        pulse_hook=str(native_resource_path("single_flight_pulse_hook.lua")),
                        waveforms=str(native_resource_path("voltage_waveforms.lua")),
                        report=str(root / "model_readback.txt"),
                    )
                request = root / "spec.lua"
                request.write_text("return " + lua_value(spec))
                script = root / "harness.lua"
                script.write_text(HARNESS)
                # The real thin wrapper resolves this explicit path resource.
                native_path = root / "native_path.lua"
                native_path.write_text("return function(path)return path end")
                resources = native_resource_path("iob_core.lua").parent
                source = {path: path.read_bytes() for path in (raw, surface, witness)}

                def call(mode, failure="valid"):
                    selected = copy.deepcopy(spec)
                    if failure == "pose":
                        selected["instances"][0]["placement"]["x_mm"] = 1
                    if failure == "rotation":
                        selected["instances"][0]["rotation"][0][0] = 0
                    if failure == "missing_id":
                        selected["instances"][0]["response_ids"].pop()
                    request.write_text("return " + lua_value(selected))
                    # Harness argv5 is the real resource directory; wrapper's
                    # native path is transported as arg3 by the dispatcher below.
                    code = (
                        HARNESS.replace("arg={arg[1],mode,arg[5]}", "local resources=arg[5];arg={arg[1],mode,arg[4]}")
                        .replace("arg[3]..'/build_tracking_iob.lua'", "resources..'/build_tracking_iob.lua'")
                        .replace("arg[3]..'/iob_core.lua'", "resources..'/iob_core.lua'")
                        .replace("arg[3]..'/build_model_iob.lua'", "resources..'/build_model_iob.lua'")
                    )
                    script.write_text(code)
                    return subprocess.run(
                        [str(LUA), str(script), str(request), mode, failure, str(native_path), str(resources)],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                modes = (
                    ("build_model", "verify_model")
                    if role == "dual_cone_model"
                    else ("build_geometry", "verify_geometry")
                    if role == "dual_cone_geometry_iob"
                    else ("build", "verify")
                )
                first = call(modes[0])
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertFalse(bootstrap.exists(), "canonical writer did not remove its declared bootstrap")
                second = call(modes[1])
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                if role == "dual_cone_model":
                    self.assertIn("DUAL_CONE_MODEL_READBACK=PASS GROUPS=7", second.stdout)
                    self.assertIn(
                        "field_status=not_solved source_status=not_requested", (root / "model_readback.txt").read_text()
                    )
                if role == "dual_cone_tracking_iob":
                    self.assertIn("DUAL_CONE_TRACKING_IOB_REOPEN=PASS", second.stdout)
                    self.assertEqual(iob.with_suffix(".fly2").read_text(), "particles{standard_beam{n=2}}")
                    for failure, reason in (
                        ("mapping", "mapping differs"),
                        ("missing_id", "all seven"),
                        ("pose", "saved provider placement differs"),
                        ("rotation", "basis differs from original matrix"),
                        ("surface", "surface readback differs"),
                    ):
                        result = call("verify", failure)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(reason, result.stderr)
                if role.startswith("dual_cone"):
                    from common.contracts.test_dual_cone_placement import pose
                    from common.contracts.test_dual_cone_transport_execution import request as actual_request
                    from msplatform.backends.simion.dual_cone_stages import native_instance_pose

                    values = actual_request()
                    transform, native = native_instance_pose(values["resolved"], values["numerics"], pose(values))
                    spec["instances"][0]["rotation"] = transform["rotation"]
                    spec["instances"][0]["placement"] = native
                    if role in {"dual_cone_geometry_iob", "dual_cone_model"}:
                        spec["output_iob"] = str(root / "placed.iob")
                    for mode in modes:
                        placed = call(mode, "placed")
                        self.assertEqual(placed.returncode, 0, placed.stdout + placed.stderr)
                for path, before in source.items():
                    self.assertEqual(path.read_bytes(), before)

    def test_actual_sds_adapter_inverse_translation_and_velocity_axes_in_declared_pose(self):
        from common.contracts.test_dual_cone_transport_execution import request
        from msplatform.backends.simion.dual_cone_transport import _render_run_config

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = request()
            config = root / "run.lua"
            config.write_text(
                _render_run_config(
                    mode="gas_assisted_transport",
                    science=values["science"],
                    numerics=values["numerics"],
                    resolved=values["resolved"],
                    solver=root,
                )
            )
            script = root / "frame.lua"
            script.write_text(
                """local original_loadfile=loadfile
local config_path=%s
local queries={}
local function sample(kind,x,y,z)
 queries[#queries+1]={kind,x,y,z};return 123456,321
end
local field={pressure_pa=function(x,y,z)sample('pressure',x,y,z);return 123456 end,
 temperature_k=function(x,y,z)sample('temperature',x,y,z);return 321 end,
 velocity_m_s=function(x,y,z)sample('velocity',x,y,z);return 1.25,-2.5,30 end}
loadfile=function(path)
 if path:match('gas_field_runtime.lua$')then return function()return field end end
 return original_loadfile(path)
end
local SDS={}
SDS.install=function()SDS.init()end
simion={workbench_program=function()segment={}end,import=function()return SDS end}
os.getenv=function(name)assert(name=='DUAL_CONE_SIMION_RUN_CONFIG_LUA');return config_path end
ion_number=1
-- Match the existing official-SDS inert initializer fixture: only remove
-- SIMION adjustable declarations, retaining the actual Program callback body.
local program_path=%s
local stream=assert(io.open(program_path,'rb'));local program=stream:read('*a');stream:close()
program=program:gsub('adjustable%%s+','')
assert(loadstring(program,'@'..program_path))()
local pressure=SDS.pressure(26.5,27.5,5)
local temperature=SDS.temperature(26.5,27.5,5)
local vx,vy,vz=SDS.velocity(26.5,27.5,5)
for _,row in ipairs(queries)do assert(row[2]==1 and row[3]==2 and row[4]==3,'gas inverse translation changed')end
assert(#queries==3)
assert(pressure==123456*(760/101325) and temperature==321,'Pa/Torr/K projection changed')
assert(vx==1.25 and vy==-2.5 and vz==30,'declared unrotated m/s velocity axes changed')
assert(SDS_collision_gas_mass_amu==28.0134 and SDS_collision_gas_diameter_nm==.364)
print('DUAL_CONE_DECLARED_GAS_FRAME=PASS INVERSE=translation VELOCITY_ROTATION=identity')
"""
                % (
                    json.dumps(str(config)),
                    json.dumps(str(native_resource_path("dual_cone_gas_assisted_transport.lua"))),
                )
            )
            # Actual shared RF module remains an explicit file, not a new kernel.
            (root / "simion_rf_drive.lua").write_bytes(native_resource_path("rf_drive.lua").read_bytes())
            result = subprocess.run([str(LUA), str(script)], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("VELOCITY_ROTATION=identity", result.stdout)

    def test_actual_program_global_callbacks_preserve_outside_instance_terminal_census(self):
        from common.contracts.test_dual_cone_transport_execution import request
        from msplatform.backends.simion.dual_cone_transport import _render_run_config

        for mode in ("c0_gem_smoke", "gas_assisted_transport"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                solver = root / "run" / "solver" / "simion"
                solver.mkdir(parents=True)
                (root / "run" / "results").mkdir()
                values = request()
                config = root / "run.lua"
                config.write_text(_render_run_config(mode=mode, science=values["science"],
                    numerics=values["numerics"], resolved=values["resolved"], solver=solver))
                (solver / "simion_rf_drive.lua").write_bytes(native_resource_path("rf_drive.lua").read_bytes())
                script = root / "outside.lua"
                script.write_text(r"""local config_path=arg[1]
local original_loadfile=loadfile
local fail_query=false
local field={pressure_pa=function()if fail_query then error('gas-field query has no fluid support')end;return 1 end,
 temperature_k=function()return 300 end,velocity_m_s=function()return 0,0,0 end}
loadfile=function(path)if path:match('gas_field_runtime.lua$')then return function()return field end end;return original_loadfile(path)end
local SDS={install=function()end}
simion={workbench_program=function()segment={}end,import=function()return SDS end}
os.getenv=function()return config_path end
seed=function()end;adj_elect={};sim_segment_global=0
ion_number=1;ion_instance=1;ion_time_of_flight=0;ion_time_step=1
ion_px_mm=25.5;ion_py_mm=25.5;ion_pz_mm=1
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=1
local f=assert(io.open(arg[2],'rb'));local program=f:read('*a');f:close()
program=program:gsub('adjustable%s+','')
assert(loadstring(program,'@'..arg[2]))()
segment.initialize_run()
assert(sim_segment_global==1,'outside-instance callbacks remain disabled')
segment.initialize()
-- Dispatcher follows official SIMION callback coverage, not an unconditional call.
ion_instance=0;ion_time_of_flight=1
if sim_segment_global==1 or ion_instance>0 then segment.terminate()end
segment.terminate() -- same-particle repeated callback is idempotent.
if arg[3]=='gas_assisted_transport'then
 ion_number=2;ion_instance=1;ion_time_of_flight=0;segment.initialize()
 fail_query=true;SDS.pressure(25.5,25.5,1) -- pre-exit support-loss writes code3.
 ion_instance=0;segment.terminate() -- global terminal must not duplicate it.
end
segment.terminate_run()
print('DUAL_CONE_OUTSIDE_INSTANCE_CENSUS=PASS')
""")
                result = subprocess.run([str(LUA), str(script), str(config),
                    str(native_resource_path("dual_cone_gas_assisted_transport.lua")), mode],
                    cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("DUAL_CONE_OUTSIDE_INSTANCE_CENSUS=PASS", result.stdout)
                import csv
                with (root / "run/results/particle_final_state.csv").open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual([int(row["ion_number"]) for row in rows], [1, 2] if mode == "gas_assisted_transport" else [1])
                self.assertEqual([int(row["splat"]) for row in rows], [0, 3] if mode == "gas_assisted_transport" else [0])

    def test_actual_source_birth_and_workbench_projection_keep_complete_mother(self):
        import csv
        from common.contracts.test_dual_cone_transport_execution import request, CONFIG
        from msplatform.backends.simion.dual_cone_transport import _materialize_gas_source

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = request()
            source = values["source_spec"]
            source["common_time_of_birth_s"] = 1e-6
            path = root / "release.json"
            path.write_text(json.dumps(source))
            frozen = root / "input"
            frozen.mkdir()
            solver = root / "solver"
            solver.mkdir()
            fly2, states, _ = _materialize_gas_source(
                frozen=frozen,
                solver=solver,
                resolved=values["resolved"],
                gas_science=json.loads((CONFIG / "gas_flow_science.json").read_text()),
                numerics=values["numerics"],
                source_spec_path=path,
            )
            with (frozen / "cylindrical_ion_source.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 100)
            self.assertEqual([int(row["particle_id"]) for row in rows], list(range(1, 101)))
            expected = []
            for row in rows:
                values = [
                    float(row[axis + "_mm"]) + offset for axis, offset in zip("xyz", (25.5, 25.5, 2), strict=True)
                ]
                velocities = [float(row["v" + axis + "_m_s"]) / 1000 for axis in "xyz"]
                pid = int(row["particle_id"])
                expected.append("assert(states[%d].t==1)" % pid)
                for key, value in zip(("x", "y", "z", "vx", "vy", "vz"), values + velocities, strict=True):
                    expected.append(
                        "assert(states[%d].%s==%s,'source frame/unit changed')" % (pid, key, format(value, ".15g"))
                    )
            script = root / "source.lua"
            script.write_text("local states=dofile(" + json.dumps(str(states)) + ")\n" + "\n".join(expected))
            result = subprocess.run([str(LUA), str(script)], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(fly2.is_file())
