-- Plain Lua callback regression; no PA mutation, refinement, or solver flight.
local repo=assert(arg[1], 'repository root required')
local path=repo..'/projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_accelerator_exit.lua'
local file=assert(io.open(path,'rb')); local source=file:read('*a'); file:close()
assert(not source:match('MRTOF_EVENT prism_') and not source:match('prism_instance'),
  'accelerator exit program must not instrument or enter a prism')
local original_print=print
local point={trajectory_quality=8,maximum_step_us=0.00002,full_path_timeout_us=5}
local original_loadfile=loadfile
loadfile=function(name)
  if name=='virtual/exit.operating_point.lua' then return function() return point end end
  return original_loadfile(name)
end
function simion_workbench_program() segment={} end
local function instance(filename)
  local pa={nx=11,ny=11,nz=11}
  function pa:inside_vc(x,y,z) return x>=0 and x<=10 and y>=0 and y<=10 and z>=0 and z<=10 end
  return {
    filename=filename,pa=pa,
    -- Exercise metadata-derived orientation: local PA x, not local PA z,
    -- is the project/workbench z axis in this synthetic placement.
    pa_to_wb_coords=function(_,x,y,z) return z,y,x end,
    wb_to_pa_coords=function(_,x,y,z) return z,y,x end,
  }
end
simion={workbench_program=simion_workbench_program,
  wb={instances={instance('virtual/background.pa'),instance('virtual/detector.pa'),
    instance('virtual/iob_input_accelerator.pa')}}}
local speed_to_ke_calls=0
function speed_to_ke(speed,mass)
  speed_to_ke_calls=speed_to_ke_calls+1
  assert(type(speed)=='number' and mass==524,
    'source energy must use the measured three-dimensional speed and actual mass')
  return 5*(speed/1.356953622185)^2*(mass/524)
end
local original_ipairs=ipairs
ipairs=function(value)
  assert(value~=simion.wb.instances,
    'SIMION Workbench instances must be traversed by numeric index, not ipairs')
  return original_ipairs(value)
end
local messages={}
print=function(message) messages[#messages+1]=message end
assert(loadstring(source:gsub('\nadjustable ','\n'),'@virtual/exit.lua'))()

segment.initialize_run()
assert(messages[1]=='MRTOF_EVENT accelerator_layout accelerator_instance=3',
  'accelerator layout did not report the filename-discovered Workbench slot')
ion_number,ion_instance,ion_splat,ion_time_of_flight=1,3,0,0
ion_mass,ion_charge=524,1
ion_px_mm,ion_py_mm,ion_pz_mm=5,5,5
ion_vx_mm,ion_vy_mm,ion_vz_mm=0,1.356953622185,0
segment.initialize()
assert(messages[2]:match('MRTOF_EVENT accelerator_source ion=1 t_us=0 x_mm=5 y_mm=5 z_mm=5 vx_mm_us=0 vy_mm_us=1%.35695362219 vz_mm_us=0 mass_th=524 charge_state=1 kinetic_energy_ev_native=5'),
  'source event lacks the complete measured source state and species: '..tostring(messages[2]))
assert(speed_to_ke_calls==1,'source event did not call the native speed-to-energy API exactly once')
ion_time_step=0.1;segment.tstep_adjust();assert(ion_time_step==point.maximum_step_us)
segment.other_actions()
ion_instance,ion_time_of_flight,ion_pz_mm=0,0.1,-1
ion_vz_mm=-3
segment.other_actions()
assert(ion_splat==1,'safe negative-z exit did not terminate the ion as one successful splat')
local safe=0
for _,message in ipairs(messages) do
  if message:match('MRTOF_EVENT accelerator_safe_exit ion=1 ') then
    safe=safe+1
    assert(message:match('from_instance=3 to_instance=0'))
    assert(message:match('z_mm=0'))
    assert(message:match('vx_mm_us=0') and message:match('vy_mm_us=1%.35695362219'))
  end
end
assert(safe==1,'safe exit must be emitted exactly once')
segment.terminate();segment.terminate_run()
assert(messages[#messages-1]:match('MRTOF_EVENT terminal ion=1 splat=1 .*turns=0 central_crossings=0'),
  'successful exit did not emit the standard terminal event after safe exit')
assert(messages[#messages]=='MRTOF_ACCELERATOR_EXIT=PASS success_count=1 failure_count=0')

local function reset_ion(number)
  segment.initialize_run()
  ion_number,ion_instance,ion_splat,ion_time_of_flight=number,3,0,0
  ion_mass,ion_charge=524,1
  ion_px_mm,ion_py_mm,ion_pz_mm=5,5,5
  ion_vx_mm,ion_vy_mm,ion_vz_mm=0,1.356953622185,0
  segment.initialize();segment.other_actions()
end

reset_ion(2)
ion_splat=7;segment.other_actions();segment.terminate();segment.terminate_run()
assert(messages[#messages]=='MRTOF_ACCELERATOR_EXIT=FAIL success_count=0 failure_count=1')
assert(table.concat(messages,'\n'):match('reason=electrode_collision splat=7'))

reset_ion(3)
ion_instance,ion_time_of_flight,ion_px_mm=0,0.1,-1
segment.other_actions();segment.terminate();segment.terminate_run()
assert(table.concat(messages,'\n'):match('reason=non_negative_z_face_exit'))

reset_ion(4)
ion_instance,ion_time_of_flight,ion_pz_mm,ion_vz_mm=0,0.1,-1,2
segment.other_actions();segment.terminate();segment.terminate_run()
assert(table.concat(messages,'\n'):match('reason=nonnegative_project_z_exit_velocity'))

segment.initialize_run()
ion_number,ion_instance,ion_splat,ion_time_of_flight=5,1,0,0
ion_mass,ion_charge=524,1
ion_px_mm,ion_py_mm,ion_pz_mm=5,5,5
ion_vx_mm,ion_vy_mm,ion_vz_mm=0,1.356953622185,0
segment.initialize();segment.terminate();segment.terminate_run()
assert(table.concat(messages,'\n'):match('reason=source_accelerator_instance_mismatch'))

reset_ion(6)
ion_time_of_flight=point.full_path_timeout_us
segment.other_actions();segment.terminate();segment.terminate_run()
assert(table.concat(messages,'\n'):match('reason=timeout splat=2'))

-- SIMION may report one callback exactly on the PA face while the accelerator
-- remains selected, then change ion_instance on the following outside step.
reset_ion(7)
ion_time_of_flight,ion_pz_mm=0.08,0
ion_vz_mm=-3
segment.other_actions()
ion_instance,ion_time_of_flight,ion_pz_mm=0,0.1,-1
segment.other_actions()
assert(ion_splat==1,'a negative-z exit following an exact-face callback was rejected')
local exact_face_exit=0
for _,message in ipairs(messages) do
  if message:match('MRTOF_EVENT accelerator_safe_exit ion=7 ') then
    exact_face_exit=exact_face_exit+1
    assert(message:match('t_us=0%.08 ') and message:match('z_mm=0 '),
      'exact-face exit must retain the measured face state at interpolation fraction zero')
  end
end
assert(exact_face_exit==1,'exact-face exit must emit one safe-exit event')
segment.terminate();segment.terminate_run()
assert(messages[#messages]=='MRTOF_ACCELERATOR_EXIT=PASS success_count=1 failure_count=0')

simion.wb.instances[4]=instance('virtual/iob_input_accelerator.pa')
assert(not pcall(segment.initialize_run),'duplicate standalone accelerator instance accepted')
print=original_print
ipairs=original_ipairs
print('ACCELERATOR_EXIT_EVENTS=PASS')
