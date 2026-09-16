-- Plain-Lua callback regression, not a native trajectory or timing result.
local repo=assert(arg[1],'repository root required')
local directory=repo..'/projects/parallel_mirror_dual_stripe_mr_tof/simion/'
local original_loadfile,original_print=loadfile,print
local program_file=assert(io.open(directory..'mrtof_candidate.lua','rb'))
local program=program_file:read('*a'); program_file:close()
local map=assert(loadfile(directory..'candidate_voltage_map.lua'))()
local point={mirror_voltages_v={0,-10,20,30,50},stripe_biases_v={-4,6},
  prism_voltages_v={141.3329402510257,0},
  accelerator_voltages_v={40,30,0},accelerator_ring_voltages_v={25,20,15,10,5},
  nonaccelerator_scale=1,detector_box_mm={-2,-3,8,2,3,10},detector_normal_project='+z',
  first_prism_l0={target_plane_z_mm=-5},
  mirror_regions_project={negative={z_min_mm=-20,z_max_mm=-10},positive={z_min_mm=10,z_max_mm=20}},
  prism_regions_project={p1={y_min_mm=-6,y_max_mm=6,z_min_mm=-4,z_max_mm=1},
    p2={y_min_mm=-6,y_max_mm=6,z_min_mm=-8,z_max_mm=-4}},
  p2_low_field_reference={z_mm=0,x_min_mm=-4,x_max_mm=4,y_min_mm=-6,y_max_mm=6},
  phase_origin_mirror_side=1,return_mirror_side=-1,
  target_drift_period_ratio=25.5,target_half_oscillation_count=51,trajectory_quality=8,maximum_step_us=0.002,
  full_path_timeout_us=1000}
loadfile=function(path)
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.voltage_map.lua' then return function() return map end end
  if path=='virtual/source.mirror_cycle_counter.lua' then
    return assert(original_loadfile(directory..'mirror_cycle_counter.lua'))
  end
  return original_loadfile(path)
end
simion={workbench_program=function() segment={} end,
  early_access=function(version) assert(version==8.2) end,wb={instances={
  {filename='mrtof_analyzer.pa0'}, {filename='mrtof_accelerator.pa0'}, {filename='mrtof_detector.pa#'}}}}
local records={}
print=function(value) records[#records+1]=value end
assert(loadstring(program:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
local function state(z,vz,t,x,y,vy)
  ion_number,ion_splat,ion_instance=1,0,1
  ion_px_mm,ion_py_mm,ion_pz_mm=x or 0,y or 0,z
  ion_vx_mm,ion_vy_mm,ion_vz_mm=0,vy or 0,vz
  ion_time_of_flight=t
end
local function begin(z,vz,x,y,vy)
  records={}; segment.initialize_run(); state(z,vz,0,x,y,vy); segment.initialize()
end
local function step(z,vz,t,x,y,vy) state(z,vz,t,x,y,vy); segment.other_actions() end
local function events(kind)
  local found={}
  for _,line in ipairs(records) do
    if line:match('^MRTOF_EVENT '..kind..' ') then found[#found+1]=line end
  end
  return found
end
local function value(line,key) return tonumber(assert(line:match(key..'=([^ ]+)'))) end

-- A geometric detector crossing before the complete return chain is diagnostic only.
begin(12,-1); step(8,-1,4); assert(#events('detector')==0)
begin(7,1); step(11,1,4); assert(#events('detector')==0)

-- Before the first safe accelerator exit, the accelerating field may bring a
-- small source-angle +z component through zero while forming the -z beam.
-- It is launch diagnostics, not an analyser reflection or topology failure.
records={}; segment.initialize_run(); state(1,1,0,0,0,1); ion_instance=2; segment.initialize()
state(0,-1,1,0,0,1); ion_instance=2; segment.other_actions()
assert(#events('accelerator_launch_vz_zero')==1,table.concat(records,'\n'))
assert(#events('nonmirror_reversal')==0 and ion_splat==0,table.concat(records,'\n'))

-- Injection: P1, negative pre-reflection, P2, then positive mirror phase origin.
begin(0,-1,3,-5,1)
step(-6,-1,1,3,-4,1)
step(-11,-1,2,3,-3,1); step(-12,0,3,3,-2,1); step(-11,1,4,3,-1,1)
step(-3,1,5,3,2.5,1); step(2,1,6,3,2,1)
assert(#events('p1_plane')==1 and #events('prism_pass')==2)
assert(#events('p2_low_field_reference')==1
  and value(events('p2_low_field_reference')[1],'z_mm')==0)
assert(#events('pre_injection_mirror_turn')==1 and #events('drift_phase_origin')==0)
step(11,1,7,3,0,1); step(12,0,8,3,0,1); step(11,-1,9,3,0,1)
assert(#events('pre_origin_positive_mirror_turn')==1 and #events('drift_phase_origin')==1)
local origins=events('drift_phase_origin')
assert(#origins==1 and value(origins[1],'y_mm')==0 and value(origins[1],'z_mm')>0
  and value(origins[1],'vz_mm_us')==0,table.concat(records,'\n'))

-- K=25.5 is 51 half oscillations from the positive to the negative turn.
local t=9
for half=1,51 do
  local returning=half==51
  local vy=returning and -1 or 1
  local side=half%2==1 and -1 or 1
  t=t+1; step(11*side,side,t,3,returning and 1 or 10,vy)
  t=t+1; step(12*side,0,t,3,returning and 0.5 or 10,vy)
  t=t+1; step(11*side,-side,t,3,returning and 0 or 10,vy)
end
assert(#events('drift_phase_return')==1,table.concat(records,'\n'))
assert(#events('drift_phase_candidate')==51)
assert(#events('target_k_phase_sample')==1 and #events('target_k')==1)
assert(#events('central_plane')>0)

-- Dynamic prism switching is outside the active static Candidate.
local switched_ok=pcall(function()
  point.prism_switch={enabled=true}
  assert(loadstring(program:gsub('\nadjustable ','\n'),'@virtual/switched.lua'))()
end)
point.prism_switch=nil
assert(not switched_ok)

print=original_print
print('CANDIDATE_PLANE_EVENTS=PASS parameterized_turn_phase_K25p5 switch_rejected')
