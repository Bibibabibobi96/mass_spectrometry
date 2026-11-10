"""Actual dual-cone projections with explicit source and device rigid frames."""

import copy
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_dual_cone_transport_execution import CONFIG, LUA, request
from common.contracts.test_dual_cone_stages import CLOCK, geometry
from msplatform.backends.simion import dual_cone_stages as stages
from msplatform.backends.simion.dual_cone_transport import _materialize_gas_source, _render_run_config, source_placement
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.resources import native_resource_path
from msplatform.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform


def pose(values):
    # Ry(90) @ Rx(90); a noncommuting orientation, off the device axial direction.
    return RigidTransform(values['resolved']['coordinate_frame']['frame_id'], 'laboratory_mm',
                          ((0, 1, 0), (0, 0, -1), (-1, 0, 0)), (12, -7, 31))


def registration(values, translation=(0, 0, 0)):
    return RigidTransform(values['source_spec']['frame_id'],
                          values['resolved']['coordinate_frame']['frame_id'],
                          ((1, 0, 0), (0, 1, 0), (0, 0, 1)), translation)


class DualConePlacementTests(unittest.TestCase):

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable; no native fallback')
    def test_actual_program_repeat_run_resets_only_its_particle_bookkeeping(self):
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import write_uniform_gas_fixture

        values = request()
        harness = r"""local old=loadfile
local config
loadfile=function(path)
 if path==arg[1] then return function()config=assert(old(path))();return config end end
 return old(path)
end
local installs,seeds=0,{}
local SDS={install=function()installs=installs+1 end}
simion={workbench_program=function()segment={}end,import=function()return SDS end}
os.getenv=function()return arg[1]end
seed=function(value)seeds[#seeds+1]=value;print('SEED|'..value)end
adj_elect={};ion_number=1;ion_time_of_flight=0;ion_time_step=1;ion_splat=0
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0
local f=assert(io.open(arg[2],'rb'));local body=f:read('*a');f:close()
assert(loadstring(body:gsub('adjustable%s+',''),'@'..arg[2]))()
for cycle=1,tonumber(arg[4])do
 config.trajectory_csv=arg[3]..'/trajectory-'..cycle..'.csv'
 config.final_state_csv=arg[3]..'/final-'..cycle..'.csv'
 segment.initialize_run()
 for _,id in ipairs{1,7,101}do
  ion_number=id;ion_time_of_flight=0;ion_splat=0
  ion_px_mm=config.device_x_offset_mm;ion_py_mm=config.device_y_offset_mm
  ion_pz_mm=config.device_z_offset_mm+10
  if cycle==1 and arg[5]=='loss' and id==7 then ion_px_mm=ion_px_mm+100 end
  local p=SDS.pressure(ion_px_mm,ion_py_mm,ion_pz_mm)
  local t=SDS.temperature(ion_px_mm,ion_py_mm,ion_pz_mm)
  local x,y,z=SDS.velocity(ion_px_mm,ion_py_mm,ion_pz_mm)
  print(string.format('TRACE|%d|%d|%.17g|%.17g|%.17g|%.17g|%.17g',cycle,id,p,t,x,y,z))
  segment.initialize()
  if cycle==1 and arg[5]=='loss' and id==101 then ion_time_of_flight=config.maximum_time_us end
  segment.other_actions();segment.terminate();segment.terminate()
 end
 segment.terminate_run()
end
assert(installs==1,'SDS.install must remain once per Program load')
assert(#seeds==tonumber(arg[4]),'seed must remain once per initialize_run')
for _,value in ipairs(seeds)do assert(value==config.random_seed)end
print('INSTALLS='..installs..' SEEDS='..#seeds)
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def run(name, cycles, first_loss):
                output=root/name
                solver=output/'solver/simion'
                solver.mkdir(parents=True)
                (output/'results').mkdir()
                (solver/'simion_rf_drive.lua').write_bytes(native_resource_path('rf_drive.lua').read_bytes())
                (solver/'collision_sds_binding.lua').write_bytes(native_resource_path('collision_sds_binding.lua').read_bytes())
                manifest=write_uniform_gas_fixture(solver/'gas_field_runtime.lua', output/'manifest.json',
                    spec_path=CONFIG/'uniform_rear_gas_field.json', interface_path=CONFIG/'gas_field_interface.json')
                config=output/'config.lua'
                config.write_text(_render_run_config(mode='gas_assisted_transport', science=values['science'],
                    numerics=values['numerics'], resolved=values['resolved'], solver=solver, gas_runtime_metadata=manifest), encoding='utf-8')
                script=output/'actual-program.lua'
                script.write_text(harness, encoding='utf-8')
                child=subprocess.run([str(LUA),str(script),str(config),
                    str(native_resource_path('dual_cone_gas_assisted_transport.lua')),str(output),str(cycles),
                    'loss' if first_loss else 'supported'],cwd=output,capture_output=True,text=True,timeout=30)
                self.assertEqual(child.returncode,0,child.stdout+child.stderr)
                rows=[]
                for cycle in range(1,cycles+1):
                    with (output/f'final-{cycle}.csv').open(newline='') as stream:
                        rows.append(list(csv.DictReader(stream)))
                return output, rows, child.stdout

            for losses in (False,True):
                with self.subTest(first_cycle_coverage_loss=losses):
                    first,control1,stdout1=run(f'control-first-{losses}',1,losses)
                    second,control2,stdout2=run(f'control-second-{losses}',1,False)
                    repeated,actual,stdout=run(f'repeated-{losses}',2,losses)
                    self.assertEqual([[int(row['ion_number']) for row in rows] for rows in actual],[[1,7,101],[1,7,101]])
                    self.assertEqual(actual,[control1[0],control2[0]])
                    self.assertEqual([int(row['splat']) for row in actual[0]],[0,3,2] if losses else [0,0,0])
                    self.assertEqual([int(row['splat']) for row in actual[1]],[0,0,0])
                    for cycle,control in ((1,first),(2,second)):
                        for prefix in ('final','trajectory'):
                            self.assertEqual((repeated/f'{prefix}-{cycle}.csv').read_bytes(),(control/f'{prefix}-1.csv').read_bytes())
                    self.assertEqual(stdout.count('SEED|'),2)
                    self.assertEqual(stdout1.count('SEED|'),1)
                    self.assertEqual(stdout2.count('SEED|'),1)
                    self.assertIn('INSTALLS=1 SEEDS=2',stdout)
                    traces=[line.split('|')[2:] for line in stdout.splitlines() if line.startswith('TRACE|')]
                    controls=[line.split('|')[2:] for line in (stdout1+stdout2).splitlines() if line.startswith('TRACE|')]
                    self.assertEqual(traces,controls)

    def test_single_array_pose_preserves_local_geometry_and_places_points_once(self):
        values = request()
        selected = pose(values)
        legacy = stages.plan_geometry_stage(resolved=values['resolved'], numerics=values['numerics'])
        placed = stages.plan_geometry_stage(resolved=values['resolved'], numerics=values['numerics'], placement=selected)
        self.assertEqual(legacy['projection'], placed['projection'])
        array, native = stages.native_instance_pose(values['resolved'], values['numerics'], selected)
        self.assertEqual(native['scale'], 1)
        transform = RigidTransform.from_contract(array)
        # Local (1,2,3) is embedded in the old PA by (25.5,25.5,2).
        actual = transform.transform_position(FramedPosition(transform.from_frame_id, (26.5,27.5,5)))
        self.assertEqual(actual.coordinates_mm, (14,-10,30))
        self.assertEqual(selected.transform_vector(FramedVector(selected.from_frame_id,(1,2,3))).components,(2,-3,-1))
        _, original = stages.native_instance_pose(values['resolved'], values['numerics'])
        self.assertEqual([original[key] for key in ('x_mm','y_mm','z_mm','az_deg','el_deg','rt_deg')], [0]*6)
        arguments = dict(electric_field=values['science']['electric_field'], clock=CLOCK, physics=RF_PHYSICS)
        unplaced = stages.plan_model_stage(geometry(), **arguments)['projection']
        model = stages.plan_model_stage(geometry(), placement=selected, **arguments)['projection']
        self.assertNotEqual(unplaced['identity_sha256'], model['identity_sha256'])
        self.assertEqual(unplaced['geometry'], model['geometry'])
        self.assertEqual(stages.require_model_projection(model), model)

    def test_explicit_source_registration_reuses_original_frame_and_rejects_invalid_pose(self):
        values = request()
        original = copy.deepcopy(values)
        selected = pose(values)
        with self.assertRaisesRegex(ValueError, 'source frame'):
            source_placement(values['resolved'],values['numerics'],values['source_spec'],placement=selected)
        transform, registered = source_placement(values['resolved'],values['numerics'],values['source_spec'],
            placement=selected,source_to_device=registration(values))
        self.assertEqual(registered.from_frame_id, values['source_spec']['frame_id'])
        self.assertEqual(transform.to_frame_id, selected.to_frame_id)
        self.assertEqual(values, original)
        bad = selected.to_contract()
        bad['rotation'][0][0] = 1
        with self.assertRaises(ValueError):
            stages.device_placement(values['resolved'],values['numerics'],bad)
        with self.assertRaisesRegex(ValueError, 'frame binding'):
            source_placement(values['resolved'],values['numerics'],values['source_spec'],
                placement=selected,source_to_device=selected)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable; no native fallback')
    def test_same_sample_source_rigid_projection_birth_and_pa_local_containment(self):
        values = request()
        values['source_spec']['common_time_of_birth_s'] = 2e-6
        values['source_spec']['species']['charge_state'] = -1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root/'release.json'
            release.write_text(json.dumps(values['source_spec']))
            runs = []
            for name,extra in (('legacy',{}),('posed',dict(placement=pose(values),source_to_device=registration(values,(.2,-.1,0))))):
                frozen,solver = root/name/'input',root/name/'solver'
                frozen.mkdir(parents=True);solver.mkdir()
                _,states,_ = _materialize_gas_source(frozen=frozen,solver=solver,resolved=values['resolved'],
                    numerics=values['numerics'],gas_science=json.loads((CONFIG/'gas_flow_science.json').read_text()),
                    source_spec_path=release,**extra)
                runs.append((frozen,states))
            self.assertEqual((runs[0][0]/'cylindrical_ion_source.csv').read_bytes(),
                             (runs[1][0]/'cylindrical_ion_source.csv').read_bytes())
            with (runs[1][0]/'cylindrical_ion_source.csv').open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows),100)
            self.assertEqual({row['charge_state'] for row in rows}, {'-1'})
            self.assertEqual((runs[1][1].parent/'gas_source.fly2').read_text().count('charge = -1,'),100)
            assertions = ['local states=dofile('+json.dumps(str(runs[1][1]))+')','local count=0;for _ in pairs(states)do count=count+1 end;assert(count==100)']
            for row in rows:
                pid=int(row['particle_id'])
                x,y,z=(float(row[a+'_mm']) for a in 'xyz')
                vx,vy,vz=(float(row['v'+a+'_m_s']) for a in 'xyz')
                # Independent explicit Ry90Rx90 oracle; registration acts first.
                expected=(y-.1+12,-z-7,-x-.2+31,vy/1000,-vz/1000,-vx/1000,2)
                for key,value in zip(('x','y','z','vx','vy','vz','t'),expected,strict=True):
                    assertions.append(f"assert(math.abs(states[{pid}].{key}-({value:.17g}))<1e-11,'pose/unit/birth')")
            script=root/'states.lua';script.write_text('\n'.join(assertions))
            result=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            frozen,solver=root/'bad/input',root/'bad/solver';frozen.mkdir(parents=True);solver.mkdir()
            with self.assertRaisesRegex(ValueError,'device-local upstream plenum'):
                _materialize_gas_source(frozen=frozen,solver=solver,resolved=values['resolved'],
                    numerics=values['numerics'],gas_science=json.loads((CONFIG/'gas_flow_science.json').read_text()),
                    source_spec_path=release,placement=pose(values),source_to_device=registration(values,(100,0,0)))

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable; no native fallback')
    def test_actual_program_inverse_points_rotated_gas_velocity_and_local_terminal(self):
        values=request()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);solver=root/'run/solver/simion';solver.mkdir(parents=True)
            (root/'run/results').mkdir()
            config=root/'config.lua'
            config.write_text(_render_run_config(mode='gas_assisted_transport',science=values['science'],
                numerics=values['numerics'],resolved=values['resolved'],solver=solver,placement=pose(values).to_contract(),
                gas_runtime_metadata={'coordinate_frame':{'frame_id':'dual_cone_interface_local'},'sampling':{'outside_domain_policy':'error'}}))
            (solver/'simion_rf_drive.lua').write_bytes(native_resource_path('rf_drive.lua').read_bytes())
            (solver/'collision_sds_binding.lua').write_bytes(native_resource_path('collision_sds_binding.lua').read_bytes())
            script=root/'oracle.lua'
            script.write_text(r'''local old=loadfile
local calls=0
local function query(x,y,z)assert(math.abs(x-1)<1e-12 and math.abs(y-2)<1e-12 and math.abs(z-3)<1e-12);calls=calls+1 end
local gas={sample=function(x,y,z,frame)assert(frame=='dual_cone_interface_local');query(x,y,z);return {status='gas',pressure_pa=123456,temperature_k=321,bulk_velocity_m_s={1.25,-2.5,30}} end}
function gas._sample_sds(channel,...) local s=gas.sample(...);if channel=='pressure' then return s.status,s.pressure_pa elseif channel=='temperature' then return s.status,s.temperature_k end;local u=s.bulk_velocity_m_s or {};return s.status,u[1],u[2],u[3] end
loadfile=function(path)if path:match('gas_field_runtime.lua$')then return function()return gas end end;return old(path)end
local SDS={install=function()end}
local instance={}
function instance:wb_to_pa_coords(x,y,z)return (31-z+25.5)/.5,(x-12+25.5)/.5,(-7-y+2)/.5 end
function instance:pa_to_wb_orient(x,y,z)return y,-z,-x end
simion={workbench_program=function()segment={}end,import=function()return SDS end,wb={instances={instance}}}
os.getenv=function()return arg[1]end;seed=function()end;adj_elect={}
ion_number=1;ion_time_of_flight=0;ion_time_step=1;ion_splat=0
ion_px_mm=14;ion_py_mm=-10;ion_pz_mm=30;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0
local f=assert(io.open(arg[2],'rb'));local program=f:read('*a');f:close()
assert(loadstring(program:gsub('adjustable%s+',''),'@'..arg[2]))()
assert(SDS.pressure(14,-10,30)==123456*(760/101325));assert(SDS.temperature(14,-10,30)==321)
local x,y,z=SDS.velocity(14,-10,30);assert(x==-2.5 and y==-30 and z==-1.25);assert(calls==3)
segment.initialize_run();segment.initialize()
-- Advance beyond the device-local downstream plane while WORLD z stays30.
ion_py_mm=-207;segment.other_actions();assert(ion_splat==1,'terminal used world z instead of local z');segment.terminate()
segment.terminate_run();print('POSED_GAS_AND_TERMINAL=PASS')
''')
            result=subprocess.run([str(LUA),str(script),str(config),str(native_resource_path('dual_cone_gas_assisted_transport.lua'))],cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('POSED_GAS_AND_TERMINAL=PASS',result.stdout)

    def test_c0_rejects_unconsumed_source_registration_without_creating_output(self):
        from msplatform.backends.simion.dual_cone_transport import prepare_transport

        values = request()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'rejected'
            with self.assertRaisesRegex(ValueError, 'fixed device-local C0 smoke source'):
                prepare_transport(output, mode='c0_gem_smoke',
                    resolved_path=CONFIG/'resolved_geometry.json', numerics_path=CONFIG/'simion_solver_numerics.json',
                    science_path=CONFIG/'ion_transport_science.json', interface_path=CONFIG/'gas_field_interface.json',
                    gas_science_path=CONFIG/'gas_flow_science.json', source_spec_path=CONFIG/'cylindrical_ion_source.json',
                    placement=pose(values), source_to_device=registration(values))
            self.assertFalse(output.exists())

    def test_local_terminal_metrics_and_active_plot_read_frozen_pose_without_rewriting_raw_rows(self):
        from msplatform.analysis.terminal_plane import analyze_terminal_plane, REQUIRED_COLUMNS
        from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.plot_simion_trajectory_projection import trajectory_tracks

        selected = pose(request())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'final.csv'
            raw = []
            for index, local in enumerate(((1, 2, 119), (-1, -2, 119)), 1):
                world = selected.transform_position(FramedPosition(selected.from_frame_id, local)).coordinates_mm
                raw.append(dict(ion_number=str(index), time_us='10',
                    x_mm=str(world[0]), y_mm=str(world[1]), z_mm=str(world[2]),
                    vx_mm_per_us='0', vy_mm_per_us='0', vz_mm_per_us='1', splat='1'))
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(raw)
            frozen = path.read_bytes()
            metrics, transmitted = analyze_terminal_plane(path, source_count=2, pass_code=1,
                axis_center_x_mm=0, axis_center_y_mm=0, position_transform=selected.inverse())
            self.assertEqual(transmitted, raw)
            self.assertEqual(path.read_bytes(), frozen)
            self.assertEqual(metrics['spatial_distribution_frame_id'], selected.from_frame_id)
            spatial = metrics['transmitted_spatial_distribution']
            self.assertEqual(spatial['centroid_x_mm'], 0)
            self.assertEqual(spatial['centroid_y_mm'], 0)
            self.assertAlmostEqual(spatial['rms_radius_mm'], 5**.5)
            tracks = trajectory_tracks(path, selected)
            self.assertEqual(tracks[1][0], [119])
            self.assertEqual(tracks[2][0], [119])
            self.assertAlmostEqual(tracks[1][1][0], 5**.5)
