"""Native zero-ground conversion evidence (run under the shared host lease)."""
import os
import subprocess
import shutil
from types import SimpleNamespace
from contextlib import ExitStack
import tempfile
import unittest
from pathlib import Path

from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.execution.run_paths import create_execution_alias, remove_execution_alias
from msplatform.io.file_identity import guarded_file_identity
from msplatform.backends.simion.source import lua_value, render_restart_fly2

SIMION = Path(r'C:/Program Files/SIMION-2020/simion.exe')
BUILD = r'''
local source=arg[1]
local cylinder=arg[2]=='cylinder'
local pa=assert(simion.pas:open())
if cylinder then pa:size(5,5,1);pa.symmetry='2dcylindrical' else pa:size(5,5,5);pa.symmetry='3dplanar' end
pa.dx_mm=1;pa.dy_mm=1;pa.dz_mm=1
for x,y,z in pa:points() do pa:point(x,y,z,x==0 and 1 or 0,x==0) end
pa:surface_info(0,2,cylinder and 0 or 2,0.25,nil,nil)
pa:save(source);pa:close();print('TINY_GROUND_SOURCE=PASS')
'''


IOB_BUILD = r'''
local seed,source,output=unpack(arg)
local parent=assert(seed:gsub('\\','/'):match('^(.*)/'))
local n=tonumber(arg[4] or '1')
for i=1,n do
 local placeholder=parent..string.format('/iob_seed_placeholder_%02d.pa0',i)
 local pa=assert(simion.pas:open());pa:size(3,3,3);pa.symmetry='3dplanar';pa:save(placeholder);pa:close()
end
simion.command('"'..seed..'"')
for i=1,n do local item=simion.wb.instances[i];item.pa.filename=source;item.pa:load();item:_debug_update_size() end
simion.wb:save(output);print('TINY_IOB_BUILD=PASS')
'''
IOB_OPEN = r'''
simion.command('"'..arg[1]..'"')
assert(#simion.wb.instances==tonumber(arg[2] or '1'));local p=simion.wb.instances[1].pa
assert(p.nx==5 and p.ny==5 and p.nz==5)
local value,metal=p:point(0,2,2);assert(value==0 and metal==true)
local sx,sy,sz=p:surface_info(0,2,2);assert(sx==0.25 and sy==nil and sz==nil)
print('TINY_IOB_REOPEN=PASS')
'''


@unittest.skipUnless(os.environ.get('SIMION_SOLVER_TEST_AUTHORIZED') == '1', 'requires shared host lease')
class AnalyticGroundNativeTests(unittest.TestCase):
    def test_small_ground_fss_and_independent_cold_open(self):
        with tempfile.TemporaryDirectory(prefix='ground_native_') as directory:
            root = Path(directory)
            build = root/'make.lua'; build.write_text(BUILD, encoding='utf-8')
            projection = root/'projection.lua'; projection.write_text('return function(p) return p end', encoding='utf-8')
            authority = root/'authority.lua'
            authority.write_text("return {schema_version=1,role='analytic_zero_ground',electrode_id=1,voltage_v=0,boundary_condition='ground_dirichlet_zero_outer_homogeneous_neumann'}", encoding='utf-8')
            source, output = root/'source.pa#', root/'output.pa'
            cmd = [str(SIMION), '--nogui', '--noprompt', 'lua']
            def run(args, marker):
                result = subprocess.run(cmd+list(map(str,args)), cwd=root, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace', timeout=120, check=False)
                self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
                self.assertIn(marker, result.stdout)
            run([build, source], 'TINY_GROUND_SOURCE=PASS')
            converter = native_resource_path('raw_collision_pa.lua')
            for mode in ('build','verify'):
                run([converter, mode, source, output, projection, '-', authority],
                    'ANALYTIC_ZERO_GROUND_'+mode.upper()+'=PASS')
            run_dir = root/'canonical'/'nested'/'run'; run_dir.mkdir(parents=True)
            alias_root = root/'aliases'; alias_root.mkdir()
            context = SimpleNamespace(powershell_executable=Path('C:/Program Files/PowerShell/7/pwsh.exe'),
                                      execution_root=alias_root)
            alias = Path(create_execution_alias(context, run_dir)['execution_alias'])
            try:
                seed_dir = run_dir/'seed'; seed_dir.mkdir()
                seed = seed_dir/'1_instance_seed.iob'; shutil.copyfile(structural_seed_path(1), seed)
                build_iob = root/'iob_build.lua'; build_iob.write_text(IOB_BUILD,encoding='utf-8')
                open_iob = root/'iob_open.lua'; open_iob.write_text(IOB_OPEN,encoding='utf-8')
                iob = run_dir/'instrument.iob'
                with ExitStack() as guards:
                    guards.enter_context(guarded_file_identity(output))
                    guards.enter_context(guarded_file_identity(output.with_suffix('.pa-surf')))
                    run([build_iob, seed, output, iob], 'TINY_IOB_BUILD=PASS')
                    run([open_iob, iob], 'TINY_IOB_REOPEN=PASS')
                    alias_open = subprocess.run(cmd+list(map(str, [open_iob, alias/'instrument.iob'])),
                        cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, check=False)
                    self.assertNotEqual(alias_open.returncode, 0)
                    self.assertIn('Missing array file', alias_open.stdout)
                    five_seed_dir = run_dir/'seed5'; five_seed_dir.mkdir()
                    five_seed = five_seed_dir/'5_instance_seed.iob'
                    shutil.copyfile(structural_seed_path(5), five_seed)
                    five_iob = run_dir/'world5.iob'
                    run([build_iob, five_seed, output, five_iob, '5'], 'TINY_IOB_BUILD=PASS')
                    run([open_iob, five_iob, '5'], 'TINY_IOB_REOPEN=PASS')
                    five_alias = subprocess.run(cmd+list(map(str, [open_iob, alias/'world5.iob', '5'])),
                        cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, check=False)
                    self.assertNotEqual(five_alias.returncode, 0)
                    self.assertIn('Missing array file', five_alias.stdout)
                    wrapper_seed_dir = run_dir/'wrapper_seed'; wrapper_seed_dir.mkdir()
                    wrapper_seed = wrapper_seed_dir/'5_instance_seed.iob'
                    shutil.copyfile(structural_seed_path(5), wrapper_seed)
                    roles = ('background','flight_tube','reflectron','accelerator','detector')
                    rows = [dict(role=role,instance_index=i,priority_number=i,path=str(output),
                                 grid=dict(nx=5,ny=5,nz=5,dx_mm=1,dy_mm=1,dz_mm=1),
                                 placement=dict(x_mm=0 if i==1 else i*100,y_mm=0,z_mm=0,
                                                az_deg=0,el_deg=0,rt_deg=0,scale=1))
                            for i,role in enumerate(roles,1)]
                    control = run_dir/'empty.fly2'; control.write_text(render_restart_fly2([]),encoding='utf8')
                    wrapper_iob = run_dir/'wrapper_world.iob'
                    wrapper_spec = root/'wrapper_spec.lua'
                    spec = dict(schema_version=1,role='split_scalar_world_iob_build',instances=rows,
                        background_probes=[[2,2,2]],seed_iob=str(wrapper_seed),output_iob=str(wrapper_iob),
                        empty_particle_control=str(control),preserve_canonical_output=True,preserve_canonical_instances=True,
                        bootstrap_paths=[str(wrapper_seed_dir/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,6)])
                    wrapper_spec.write_text('return '+lua_value(spec)+'\n',encoding='utf8')
                    wrapper=native_resource_path('build_geometry_iob.lua')
                    run([wrapper,wrapper_spec,'build_geometry',projection], 'SINGLE_REFLECTION_GEOMETRY_IOB=PASS')
                    run([wrapper,wrapper_spec,'verify_geometry',projection], 'SPLIT_SCALAR_WORLD_PRIORITY=PASS')
            finally:
                remove_execution_alias(context, alias, run_dir)
            cylinder_source, cylinder_output = root/'cylinder.pa#', root/'cylinder_out.pa'
            run([build, cylinder_source, 'cylinder'], 'TINY_GROUND_SOURCE=PASS')
            for mode in ('build', 'verify'):
                run([converter, mode, cylinder_source, cylinder_output, projection, '-', authority],
                    'ANALYTIC_ZERO_GROUND_'+mode.upper()+'=PASS')
            authority.write_text("return {schema_version=1,role='analytic_zero_ground',electrode_id=1,voltage_v=1,boundary_condition='ground_dirichlet_zero_outer_homogeneous_neumann'}", encoding='utf-8')
            rejected = subprocess.run(cmd+list(map(str, [converter, 'verify', cylinder_source, cylinder_output,
                                                         projection, '-', authority])), cwd=root, capture_output=True,
                                      text=True, encoding='utf-8', errors='replace', timeout=120, check=False)
            self.assertNotEqual(rejected.returncode, 0)
