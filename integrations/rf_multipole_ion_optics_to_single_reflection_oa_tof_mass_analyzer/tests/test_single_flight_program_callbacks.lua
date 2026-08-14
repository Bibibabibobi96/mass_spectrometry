-- Execute the frozen legacy combined Program under SIMION's official Lua CLI.
-- This uses mock Workbench state only; it does not load a PA, refine, Fly, or solve.

local program_path = assert(arg[1], 'combined Program path is required')
local run_mode=arg[2] or 'legacy'
local callbacks, counts = {}, {}
segment = setmetatable({}, {
  __index=function(_, key) return callbacks[key] end,
  __newindex=function(_, key, value)
    counts[key]=(counts[key] or 0)+1
    callbacks[key]=value
  end,
})

local function copy_table(value)
  local result={}
  for key,item in pairs(value) do result[key]=item end
  return result
end

local operation_order={}
local function pa(label,nx,ny,nz,dx,dy,dz)
  local value={nx=nx,ny=ny,nz=nz,dx_mm=dx,dy_mm=dy,dz_mm=dz,calls={},load_calls={}}
  function value:fast_adjust(voltages)
    operation_order[#operation_order+1]=label..':fast_adjust'
    self.calls[#self.calls+1]=copy_table(voltages)
  end
  function value:load(path)
    operation_order[#operation_order+1]=label..':load'
    self.load_calls[#self.load_calls+1]=path
  end
  return value
end

local instances={
  {filename='flight_tube_ground.pa0',scale=1,pa=pa('flight',2001,501,2,1,1,1)},
  {filename='reflectron.pa0',scale=1,pa=pa('reflectron',2001,501,2,1,1,1)},
  {filename='accelerator.pa0',scale=1,pa=pa('accelerator',101,101,101,1,1,1)},
  {filename='detector_ground.pa0',scale=1,pa=pa('detector',3,3,8,1,1,0.05)},
}
if run_mode=='successor_overlay' then
  instances[5]={filename='accelerator_overlay.pa0',scale=1,
    pa=pa('overlay',101,101,101,1,1,1)}
end
for index,instance in ipairs(instances) do
  function instance:_debug_update_size()
    operation_order[#operation_order+1]=(index==3 and 'accelerator' or tostring(index))..':debug_update_size'
  end
  function instance:inside_wc(_,_,_) return false end
end
simion={
  workbench_program=function() end,
  early_access=function(_) end,
  wb={instances=instances},
}

assert(dofile(program_path)==nil, 'combined Program unexpectedly returned a value')

local successor=run_mode:match('^successor')~=nil
local expected_counts=successor and
  {load=1,initialize_run=1,fast_adjust=1,efield_adjust=1,
    initialize=1,tstep_adjust=1,other_actions=1,terminate=1,instance_adjust=1} or
  {load=1,initialize_run=3,fast_adjust=2,efield_adjust=2,
    initialize=2,tstep_adjust=3,other_actions=3,terminate=2,instance_adjust=1}
for name,expected in pairs(expected_counts) do
  assert(counts[name]==expected,
    name .. ' definition count expected ' .. expected .. ', got ' .. tostring(counts[name]))
end
assert(type(callbacks.fast_adjust)=='function' and type(callbacks.tstep_adjust)=='function',
  'final callbacks are missing')

if successor then
  callbacks.__legacy_test_set_adjustable('handoff_pulse_mode',1)
  callbacks.__legacy_test_set_adjustable('handoff_pulse_time_us',1)
  callbacks.__legacy_test_set_adjustable('handoff_pulse_width_us',0.5)
end
callbacks.initialize_run()
if successor then
  assert(#instances[3].pa.load_calls==1 and
    instances[3].pa.load_calls[1]=='mock_combined_frontend.pa0',
    'successor did not load the combined frontend override')
  assert(operation_order[1]=='accelerator:load' and
    operation_order[2]=='accelerator:debug_update_size' and
    operation_order[3]=='accelerator:fast_adjust',
    'combined frontend override was not loaded before dimensions and adjustment')
end
assert(#instances[1].pa.calls==0, 'legacy grounded flight-tube fast_adjust survived')
assert(#instances[2].pa.calls==1, 'reflectron fast_adjust count changed')
assert(#instances[3].pa.calls==2, 'accelerator/frontend fast_adjust sequence changed')
assert(#instances[4].pa.calls==0, 'legacy grounded detector fast_adjust survived')

local function near(actual,expected,label,tolerance)
  tolerance=tolerance or 1e-9
  assert(math.abs(actual-expected)<=tolerance,
    label .. ' expected ' .. expected .. ', got ' .. tostring(actual))
end
if run_mode=='successor_overlay' then
  assert(#instances[5].pa.calls==1,'overlay static frontend adjustment count changed')
  near(instances[5].x,10,'overlay x placement')
  near(instances[5].y,20,'overlay y placement')
  near(instances[5].z,30,'overlay z placement')
end

local function set_callback_value(name,value)
  assert(type(callbacks.__legacy_test_set_adjustable)=='function',
    'test-only adjustable control is missing')
  callbacks.__legacy_test_set_adjustable(name,value)
end
local function get_program_value(name)
  assert(type(callbacks.__legacy_test_get_value)=='function',
    'test-only value reader is missing')
  return callbacks.__legacy_test_get_value(name)
end

local function run_fast(instance_id, elapsed_us, mode)
  local order={}
  adj_elect=setmetatable({}, {__newindex=function(table,key,value)
    order[#order+1]=key; rawset(table,key,value)
  end})
  ion_number=1; ion_instance=instance_id; ion_time_of_flight=elapsed_us
  set_callback_value('handoff_pulse_mode',mode)
  set_callback_value('handoff_pulse_time_us',1)
  set_callback_value('handoff_pulse_width_us',0.5)
  callbacks.fast_adjust()
  return adj_elect,order
end

local pre,pre_order=run_fast(3,0,1)
assert(#pre_order==19 and pre_order[1]==1 and pre_order[19]==19,
  'frontend electrode write order changed before pulse')
for electrode=1,19 do near(pre[electrode],0,'pre-pulse electrode '..electrode,1e-8) end

local active,active_order=run_fast(3,0.75,1)
assert(#active_order==19 and active_order[1]==1 and active_order[19]==19,
  'frontend electrode write order changed during pulse')
for electrode=1,8 do
  near(active[electrode],electrode%2==0 and 100 or -100,
    'active RF electrode '..electrode,1e-8)
end
near(active[9],0,'active ground')
local expected_repeller=get_program_value('V_repeller')
local expected_grid1=get_program_value('V_grid1')
near(active[10],expected_repeller,'active repeller')
near(active[11],expected_grid1,'active grid1')
for index=1,5 do
  near(active[11+index],expected_grid1*(6-index)/6,'active ring '..index)
end
near(active[17],0,'active grid2')
near(active[18],0,'active reference')
near(active[19],0,'active entrance plate')

local post=run_fast(3,1.3,1)
for electrode=10,19 do near(post[electrode],0,'post-pulse electrode '..electrode,1e-8) end
local held=run_fast(3,0.75,2)
for electrode=10,19 do near(held[electrode],0,'held-off electrode '..electrode,1e-8) end
local outside,outside_order=run_fast(2,0.75,1)
assert(#outside_order==0 and next(outside)==nil,'non-frontend instance wrote electrodes')

local function set_particle(number,instance_id,elapsed,z,vz,dt)
  ion_number=number; ion_instance=instance_id; ion_time_of_flight=elapsed
  ion_px_mm=0; ion_py_mm=0; ion_pz_mm=z
  ion_vx_mm=0; ion_vy_mm=0; ion_vz_mm=vz
  ion_time_step=dt; ion_mass=100; ion_ke=0; ion_splat=0
end

set_callback_value('handoff_pulse_mode',1)
set_callback_value('handoff_pulse_time_us',1)
set_callback_value('handoff_pulse_width_us',0.5)
set_particle(1,1,0.65,100,1,1)
callbacks.tstep_adjust()
near(ion_time_step,0.1,'pulse rising-edge timestep',1e-12)

set_callback_value('handoff_pulse_mode',2)
set_particle(1,3,0.75,100,1,1)
callbacks.tstep_adjust()
near(ion_time_step,0.00625,'RF 160-step cap',1e-12)

set_particle(1,1,0.75,100,1,1)
callbacks.tstep_adjust()
near(ion_time_step,1,'non-frontend timestep must not receive RF cap',1e-12)

set_callback_value('handoff_pulse_mode',1)
local expected_grid1_z=get_program_value('accelerator_grid1_z_mm')
set_particle(2,3,0.1,expected_grid1_z-0.001,1,1)
callbacks.tstep_adjust()
near(ion_time_step,0.001,'grid1 native landing timestep',1e-10)

if successor then
  local expected_grid2_z=get_program_value('accelerator_grid2_z_mm')
  set_particle(2,3,0.2,expected_grid2_z-0.001,1,1)
  callbacks.initialize()
  callbacks.tstep_adjust()
  near(ion_time_step,0.001,'grid2 native landing timestep',1e-10)
  set_particle(2,3,0.201,expected_grid2_z-1e-15,1,1)
  callbacks.tstep_adjust()
  near(ion_time_step,0,'grid2 zero-step confirmation',1e-15)
  ion_time_step=1
  callbacks.tstep_adjust()
  assert(ion_time_step>0,'grid2 zero-step confirmation repeated')
  callbacks.other_actions()
end

set_callback_value('handoff_pulse_mode',1)
local expected_repeller_z=get_program_value('accelerator_repeller_front_z_mm')
set_particle(1,3,0.75,expected_repeller_z+0.5,1,1)
ion_dvoltsx_gu=1; ion_dvoltsy_gu=2; ion_dvoltsz_gu=3
callbacks.efield_adjust()
if run_mode=='successor_full_ideal' then
  local expected_e=(get_program_value('V_repeller')-get_program_value('V_grid1'))/
    (get_program_value('accelerator_grid1_z_mm')-expected_repeller_z)
  near(ion_dvoltsx_gu,0,'full-ideal x derivative')
  near(ion_dvoltsy_gu,0,'full-ideal y derivative')
  near(ion_dvoltsz_gu,-expected_e,'full-ideal stage1 derivative')
else
  near(ion_dvoltsx_gu,1,'real-PA x derivative')
  near(ion_dvoltsy_gu,2,'real-PA y derivative')
  near(ion_dvoltsz_gu,3,'real-PA z derivative')
end

ion_instance=5
callbacks.instance_adjust()
if run_mode=='successor_overlay' then
  assert(ion_instance==0,'overlay outside active bounds did not release instance')
  ion_instance=5; ion_px_mm=50; ion_py_mm=50; ion_pz_mm=50
  callbacks.instance_adjust()
  assert(ion_instance==5,'overlay interior point was released')
else
  assert(ion_instance==5,'overlay-disabled instance_adjust changed the instance')
end

if successor then
  set_callback_value('trajectory_log_enable',0)
  set_particle(1,1,89.9,100,1,1)
  callbacks.initialize()
  callbacks.other_actions()
  assert(ion_splat==0,'nonzero birth incorrectly advanced analyzer timeout')
  set_particle(1,1,90,100,1,1)
  callbacks.other_actions()
  assert(ion_splat==1,'solver-local analyzer timeout was not enforced')

  local captured={}
  local native_print=print
  print=function(line) captured[#captured+1]=line end
  set_callback_value('trajectory_log_enable',1)
  set_particle(2,4,2,0.01,-1,1)
  ion_px_mm=48.8
  callbacks.terminate()
  set_callback_value('trajectory_log_enable',0)
  print=native_print
  local detector_elapsed=nil
  for _,line in ipairs(captured) do
    local value=line:match('TRACE: detector_crossing ion=2 t=([-+0-9.eE]+)')
    if value then detector_elapsed=tonumber(value) end
  end
  near(detector_elapsed,2.01,'detector solver-local elapsed clock',1e-12)
end

set_particle(1,1,0.75,100,1,1)
callbacks.terminate()

print(successor and 'SUCCESSOR_SINGLE_FLIGHT_CALLBACKS=PASS' or
  'LEGACY_SINGLE_FLIGHT_CALLBACKS=PASS')
