-- Plain Lua composition test: no PA, solver or GUI is started.
local repo,source_directory=assert(arg[1]),assert(arg[2])
local directory=repo..'/projects/parallel_mirror_dual_stripe_mr_tof/'
local function read(path) local f=assert(io.open(path,'rb')); local s=f:read('*a');f:close();return s end
local fixture=read(directory..'tests/simion/test_candidate_plane_events.lua')
local prefix=assert(fixture:match('^(.-)loadfile=function%(path%)'))
-- Reuse the existing geometry and operating point fixture without duplicating it.
prefix=prefix..'return point'
local point=assert(loadstring(prefix,'@existing-plane-fixture'))(repo)
point.accelerator_provider='dual_pressure_rectilinear_ion_processor'
point.field_assembly_verified=true
point.measured_source_matches_workpoint=true
point.measured_source_directory=source_directory
point.accelerator_voltages_v=nil;point.accelerator_ring_voltages_v=nil
point.runtime_fast_adjust_enable=false
point.trajectory_recording_enabled=true
point.trajectory_recording_mode='every_step'
local analyzer={0,-10,20,30,50,0,-10,20,30,50,-4,-4,6,6,0,141.3329402510257,0,0,0,0}
point.static_field={accelerator_provider=point.accelerator_provider,
  assembly_scope='full_c0_ion_processor_replacement',analyzer_voltages_v=analyzer}
local priority={role='mrtof_native_corridor_iob_priority_contract',schema_version=1,
  accelerator_provider=point.accelerator_provider,instances={
    {role='global_fallback',priority_number=1},{role='native_corridor',priority_number=2},
    {role='ion_processor_collision',priority_number=3},{role='detector',priority_number=4}}}
local original_loadfile,original_print=loadfile,print
local scalar_calls=0
loadfile=function(path)
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.priority.lua' then return function() return priority end end
  if path=='virtual/source.scalar_field_adapter.lua' then return function() return function() return function() scalar_calls=scalar_calls+1 end end end end
  if path=='virtual/source.source_runtime.lua' then
    local module_chunk=assert(original_loadfile(source_directory..'/source_runtime.lua'))
    -- Deliberately isolate loadfile modules from workbench reserved variables.
    setfenv(module_chunk,setmetatable({}, {
      __index=function(_,key)
        assert(not key:match('^ion_'),'pure helper read reserved variable '..key)
        return _G[key]
      end,
      __newindex=function(_,key) error('pure helper wrote global '..key) end}))
    return module_chunk
  end
  if path=='virtual/source.mirror_cycle_counter.lua' then return original_loadfile(directory..'simion/mirror_cycle_counter.lua') end
  assert(path~='virtual/source.voltage_map.lua','IP must not load OA voltage map')
  return original_loadfile(path)
end
local records={}
local engine=setmetatable({}, {__index=_G})
print=function(line) records[#records+1]=line end
simion={workbench_program=function() engine.segment={} end,wb={instances={
  {filename='full-c0.pa'},{filename='downstream.pa'},{filename='ip-collision.pa'},{filename='detector.pa'}}}}
local program=read(directory..'simion/mrtof_candidate.lua'):gsub('\nadjustable ','\n')
local function compile()
  local chunk=assert(loadstring(program,'@virtual/source.lua'))
  setfenv(chunk,engine);chunk()
end
compile()
local flush_count=0
local original_flush=io.flush
io.flush=function() flush_count=flush_count+1 end
local function state(z,vz,t,x,y,vy)
  engine.ion_number,engine.ion_splat,engine.ion_instance,engine.ion_volts=2,0,1,0
  engine.ion_px_mm,engine.ion_py_mm,engine.ion_pz_mm=x or 0,y or 0,z
  engine.ion_vx_mm,engine.ion_vy_mm,engine.ion_vz_mm=0,vy or 0,vz
  engine.ion_time_of_flight=t+.06
end
local function begin()
  records={};engine.segment.initialize_run()
  -- Mock the engine at the FLY2-defined birth offset before initialize.
  state(99,99,0,99,99,99);engine.ion_time_of_flight=0;engine.segment.initialize()
  assert(engine.ion_mass==524 and engine.ion_charge==1 and engine.ion_time_of_birth==.06)
  assert(engine.ion_px_mm==3 and engine.ion_py_mm==-5 and engine.ion_pz_mm==0)
  assert(engine.ion_vx_mm==0 and engine.ion_vy_mm==1 and engine.ion_vz_mm==-1)
  assert(engine.ion_time_of_flight==0,'initialize must not write the engine clock')
  local birth
  for _,line in ipairs(records) do birth=birth or line:match('^MRTOF_TRAJECTORY.-phase=birth t_us=([^ ]+)') end
  assert(birth)
  assert(tonumber(birth)==7500.51+.06,'birth must use the canonical source epoch before engine TOB application')
end
local function step(z,vz,t,x,y,vy) state(z,vz,t,x,y,vy);engine.segment.other_actions() end
local function events(kind)
  local found={};for _,line in ipairs(records) do
    if line:match('^MRTOF_EVENT '..kind..' ') then found[#found+1]=line end
  end;return found
end
local function value(line,key) return tonumber(assert(line:match(key..'=([^ ]+)'))) end
-- Exercise the complete existing injection, phase-origin and 51-half-cycle path.
local sequence=assert(fixture:match('%-%- Injection:.-\n(.-)%-%- Real 4 ns detector'))
local environment=setmetatable({begin=begin,step=step,events=events,value=value,
  records=records,flush_count=1},{__index=_G})
-- These helpers are local in the original test; retain the same physical vectors.
local chunk=assert(loadstring(sequence,'@existing-injection-sequence'))
setfenv(chunk,environment);chunk()
for _,line in ipairs(records) do
  if line:match('^MRTOF_EVENT ') then
    assert(value(line,'ion')==64,'event ID must retain original non-contiguous ID')
    if line:match('t_us=') then assert(value(line,'t_us')>=7500.57,'absolute event epoch lost') end
  end
end
assert(#events('accelerator_safe_exit')==0 and #events('accelerator_launch_vz_zero')==0)
-- Exercise the existing detector and terminal callback with the completed
-- return stage fixture, as in the ordinary OA callback regression.
begin();step(12,-1,1,0,0,0)
local stage_set=false
for index=1,100 do
  local name,upvalue=debug.getupvalue(engine.segment.other_actions,index)
  if name=='prism_stage' then upvalue[2]='awaiting_static_detector';stage_set=true;break end
  if not name then break end
end
assert(stage_set)
state(8,-1,5,0,0,0);engine.ion_instance=4;engine.segment.other_actions();engine.segment.terminate()
assert(#events('detector')==1 and #events('terminal')==1 and engine.ion_splat==1)
assert(value(events('detector')[1],'ion')==64 and value(events('detector')[1],'t_us')==7503.57)
assert(value(events('terminal')[1],'ion')==64 and value(events('terminal')[1],'t_us')==7505.57)
-- External handoff has already left the accelerator; nonmirror reversal is invalid.
begin();step(1,1,1,3,-5,1)
assert(#events('nonmirror_reversal')==1 and engine.ion_splat==4)
assert(#events('accelerator_launch_vz_zero')==0)
-- The 7500 us instrument epoch and per-particle birth offset are not flight age.
begin();step(0,-1,999.99,3,-5,1);assert(engine.ion_splat==0)
step(0,-1,1000,3,-5,1);assert(engine.ion_splat==2)
engine.segment.terminate();assert(value(events('terminal')[1],'ion')==64)
assert(value(events('terminal')[1],'t_us')==8500.57)
local function rejects(change,undo)
  change();local ok=pcall(compile);undo();assert(not ok,'invalid IP assembly accepted')
end
rejects(function() point.field_assembly_verified=false end,
  function() point.field_assembly_verified=true end)
rejects(function() point.measured_source_matches_workpoint=false end,
  function() point.measured_source_matches_workpoint=true end)
rejects(function() point.static_field.assembly_scope='legacy_oa' end,
  function() point.static_field.assembly_scope='full_c0_ion_processor_replacement' end)
rejects(function() point.runtime_fast_adjust_enable=true end,
  function() point.runtime_fast_adjust_enable=false
point.trajectory_recording_enabled=true
point.trajectory_recording_mode='every_step' end)
rejects(function() priority.accelerator_provider='orthogonal_accelerator' end,
  function() priority.accelerator_provider=point.accelerator_provider end)
rejects(function() priority.instances[5]={role='accelerator',priority_number=5} end,
  function() priority.instances[5]=nil end)
rejects(function() point.accelerator_safe_exit_only=true end,
  function() point.accelerator_safe_exit_only=nil end)
-- A loader-verified fifth collision carrier never replaces scalar E, and keeps
-- the provider/detector slots at 3/4. This is a callback fixture, not a PA query.
local overlay={schema_version=1,role='mrtof_analyzer_collision_overlay',patch_plan_path='sealed_plan.json',pa_path='patch.pa'}
point.static_field.collision_overlay=overlay;priority.collision_overlay=overlay
priority.instances[5]={role='analyzer_collision_patch',priority_number=5}
simion.wb.instances[5]={filename='patch.pa',pa={path='patch.pa'}}
compile();begin()
local before_scalar=scalar_calls
engine.ion_instance=4;engine.segment.efield_adjust()
engine.ion_instance=5;engine.segment.efield_adjust()
assert(scalar_calls==before_scalar+2,'vacuum in the patch must retain the same scalar field callback')
simion.wb.instances[5].pa.path='different.pa'
assert(not pcall(engine.segment.initialize_run),'changed fifth collision PA accepted')
simion.wb.instances[5].pa.path='patch.pa'
rejects(function() priority.instances[5].role='detector' end,
  function() priority.instances[5].role='analyzer_collision_patch' end)
priority.collision_overlay=nil
assert(not pcall(compile),'unverified fifth collision projection accepted')
priority.instances[5]=nil;point.static_field.collision_overlay=nil;simion.wb.instances[5]=nil
compile();engine.V_prism_1=engine.V_prism_1+1
assert(not pcall(engine.segment.initialize_run),'changed voltage on frozen full C0 field accepted')
io.flush=original_flush;print=original_print
print('MEASURED_RUNTIME=PASS original_ids absolute_clock six_dimensional_initialize phase_K25p5 topology elapsed_timeout provider_guards')
