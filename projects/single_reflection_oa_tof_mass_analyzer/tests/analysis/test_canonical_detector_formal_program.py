"""Pure Lua boundary checks for the current canonical physical detector."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_contract, resolve_physical_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import generated_adjustables, render_program, render_resolved_lua

LUA = (os.environ["SIMION_LUA_EXE"] if "SIMION_LUA_EXE" in os.environ else
       shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")


class CanonicalDetectorFormalProgramTests(unittest.TestCase):
    def test_generated_source_and_lua_linked_geometry(self):
        contract = resolve_contract()
        body = resolve_physical_geometry(contract)['simion']['detector_body']
        marker = contract['simion_detector_marker']
        self.assertEqual((body['height_mm'], body['radius_mm']), (1., 40.))
        self.assertEqual((body['back_cells'], body['front_cells']), (105, 20))
        self.assertEqual((marker['active_plane_z_mm'], marker['capture_depth_mm']), (0., .02))
        self.assertEqual(contract['simion_geometry_build']['detector']['max_mib'], 128.)
        self.assertIn('adjustable detector_physical_thickness_mm=1.0', generated_adjustables(contract))
        self.assertIn('detector_body', render_resolved_lua(contract))
        program = re.sub(r'\badjustable\s+', '', render_program(contract))
        stub = r'''
segment={}
local function pa(nx,ny,nz,dx,dy,dz)
 return {nx=nx,ny=ny,nz=nz,dx_mm=dx,dy_mm=dy,dz_mm=dz,fast_adjust=function() end}
end
simion={workbench_program=function() end,wb={instances={
 {filename='flight_tube_ground.pa0',scale=1,pa=pa(1001,361,1,1,1,1)},
 {filename='reflectron.pa0',scale=1,pa=pa(2001,361,1,0.25,1,1)},
 {filename='accelerator.pa0',scale=1,pa=pa(161,161,500,0.25,0.25,0.05)},
 {filename='detector_ground.pa0',scale=1,pa=pa(165,165,126,0.5,0.5,0.01)}
}}}
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'program.lua'
            script.write_text(stub + program + '\nsegment.initialize_run()\nassert(math.abs(simion.wb.instances[4].z + 1.05)<1e-12)\nassert(detector_capture_depth_mm==0.02)\nprint("PHYSICAL_DETECTOR_PLACEMENT=PASS")\n', encoding='utf-8')
            result = subprocess.run([LUA, str(script)], cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PHYSICAL_DETECTOR_PLACEMENT=PASS', result.stdout)
            script.write_text(script.read_text(encoding='utf-8').replace('pa(165,165,126,', 'pa(165,165,36,'), encoding='utf-8')
            failed = subprocess.run([LUA, str(script)], cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('detector physical PA does not cover', failed.stderr)

    def test_formal_detector_requires_return_after_reflectron(self):
        program = re.sub(r"\badjustable\s+", "", render_program(resolve_contract()))
        stub = r"""
segment={}
local function pa(nx,ny,nz,dx,dy,dz)
 return {nx=nx,ny=ny,nz=nz,dx_mm=dx,dy_mm=dy,dz_mm=dz,fast_adjust=function() end}
end
simion={workbench_program=function() end,wb={instances={
 {filename='flight_tube_ground.pa0',scale=1,pa=pa(1001,361,1,1,1,1)},
 {filename='reflectron.pa0',scale=1,pa=pa(2001,361,1,0.25,1,1)},
 {filename='accelerator.pa0',scale=1,pa=pa(161,161,500,0.25,0.25,0.05)},
 {filename='detector_ground.pa0',scale=1,pa=pa(165,165,126,0.5,0.5,0.01)}
}}}
"""
        tail = r"""
segment.initialize_run()
trajectory_log_enable=1; trajectory_log_stride=100000
local output={}; local original_print=print
print=function(line) output[#output+1]=line end
local function exercise(id,arm,vz,expected)
 ion_number=id;ion_instance=4;ion_time_of_flight=0;ion_px_mm=-accelerator_axis_x_mm+detector_mirror_offset_x_mm;ion_py_mm=-accelerator_axis_y_mm+detector_mirror_offset_y_mm
 ion_pz_mm=1;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=vz;ion_splat=0
 segment.initialize()
 if arm then ion_pz_mm=reflectron_entgrid_z_mm+1;ion_time_of_flight=1;segment.other_actions() end
 ion_pz_mm=detector_active_plane_z_mm-.02;ion_time_of_flight=5;ion_vz_mm=vz
 local first=#output+1;segment.terminate()
 local lines=table.concat(output,"\n",first,#output)
 assert(lines:find(expected,1,true),lines)
 if expected=='TRACE: detector_crossing' then
  assert(lines:find('TRACE: detector_hit_entity',1,true),lines)
  assert(lines:find('t=4.98',1,true),lines)
 else
  assert(not lines:find('TRACE: detector_crossing',1,true),lines)
  assert(not lines:find('TRACE: detector_hit_entity',1,true),lines)
 end
end
exercise(11,false,-1,'TRACE: non_detector_splat')
exercise(22,true,1,'TRACE: non_detector_splat')
exercise(33,true,0,'TRACE: non_detector_splat')
exercise(44,true,-1,'TRACE: detector_crossing')
original_print('FORMAL_RETURN_OBSERVATION=PASS')
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "formal_return.lua"
            script.write_text(stub + program + tail, encoding="utf-8")
            result = subprocess.run([LUA, str(script)], cwd=directory,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FORMAL_RETURN_OBSERVATION=PASS", result.stdout)

    def test_native_verifier_probes_canonical_body_midpoint(self):
        import json
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import PROJECT_ROOT
        resolved = PROJECT_ROOT / 'simion/workbench/formal/oatof_resolved.lua'
        verifier = PROJECT_ROOT / 'simion/workbench/verify_formal_runtime.lua'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for physical_depth, success in ((1.0, True), (.1, False)):
                report = root / ('report' + str(physical_depth) + '.txt')
                script = root / ('verify' + str(physical_depth) + '.lua')
                script.write_text('arg={' + ','.join(json.dumps(str(x)) for x in (report, root/'inert.iob', resolved)) + '}\n' +
                    'local c=dofile(arg[3]); local depth=' + str(physical_depth) + r'''
local instances={}
for i,row in ipairs(c.derived.simion_instances) do
 local pa={nx=row.nx,ny=row.ny,nz=row.nz,dx_mm=row.cell_mm,dy_mm=1,dz_mm=1}
 function pa:field_vc() return 0,0,0 end
 local inst={filename=row.name,x=row.x_mm,y=row.y_mm,z=row.z_mm,az=row.az_deg,scale=1,pa=pa}
 function inst:wb_to_pa_coords(x,y,z) return x,y,z end
 instances[i]=inst
end
local wb={instances=instances}
function wb:efield() return 0,0,0 end
function wb:find_at(x,y,z)
 if x==c.coordinate_convention.detector_x and z==-c.physical_geometry.simion.detector_body.height_mm/2 then
  return z>=-depth, z>=-depth and 4 or 1
 end
 return false,1
end
simion={wb=wb,command=function() end}
''' + 'dofile(' + json.dumps(str(verifier)) + ')\n', encoding='utf-8')
                result = subprocess.run([LUA, str(script)], cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
                if success:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('DETECTOR_STATIC_PROBE_XYZ_MM=48.8,0,-0.5', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('static detector priority mismatch', result.stderr)
