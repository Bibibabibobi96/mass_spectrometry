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
  prism_regions_project={p1={y_min_mm=3,y_max_mm=6,z_min_mm=-4,z_max_mm=1},
    p2={y_min_mm=1,y_max_mm=3,z_min_mm=-4,z_max_mm=1}},
  phase_origin_mirror_side=1,
  target_oscillation_count=25,trajectory_quality=8,maximum_step_us=0.002,
  full_path_timeout_us=1000}
loadfile=function(path)
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.voltage_map.lua' then return function() return map end end
  if path=='virtual/source.mirror_cycle_counter.lua' then
    return assert(original_loadfile(directory..'mirror_cycle_counter.lua'))
  end
  return original_loadfile(path)
end
simion={workbench_program=function() segment={} end,wb={instances={
  {filename='mrtof_analyzer.pa0'}, {filename='mrtof_accelerator.pa0'}, {filename='mrtof_detector.pa#'}}}}
local records={}
print=function(value) records[#records+1]=value end
assert(loadstring(program:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
local function state(z,vz,t,x,y,vy)
  ion_number,ion_splat=1,0
  ion_px_mm,ion_py_mm,ion_pz_mm=x or 0,y or 0,z
  ion_vx_mm,ion_vy_mm,ion_vz_mm=0,vy or 0,vz
  ion_time_of_flight=t
end
local function begin(z,vz,x,y,vy)
  records={}; segment.initialize_run(); state(z,vz,0,x,y,vy); segment.initialize()
end
local function step(z,vz,t,x,y,vy)
  state(z,vz,t,x,y,vy); segment.other_actions()
end
local function events(kind)
  local found={}
  for _,line in ipairs(records) do
    if line:match('^MRTOF_EVENT '..kind..' ') then found[#found+1]=line end
  end
  return found
end
local function value(line,key) return tonumber(assert(line:match(key..'=([^ ]+)'))) end

-- Detector owns only the +z active face and interpolates a crossing.
begin(12,-1); step(10,-1,2); step(9,-1,3)
local hits=events('detector')
assert(#hits==1 and value(hits[1],'z_mm')==10 and value(hits[1],'t_us')==2)
begin(12,-1); step(8,-1,4)
hits=events('detector')
assert(#hits==1 and value(hits[1],'z_mm')==10 and value(hits[1],'t_us')==2)
begin(7,1); step(11,1,4); assert(#events('detector')==0)
begin(12,-1,3,0); step(8,-1,4,3,0); assert(#events('detector')==0)

-- The physical injection path is P1 refraction, a true negative-mirror
-- pre-reflection, P2 refraction, then the selected outbound positive-mirror
-- phase origin.  Prisms never own v_z reversals.
begin(0,-1,3,-5,1)
step(-6,-1,1,3,-4,1)       -- post-P1 interface
step(-11,-1,2,3,-3,1)
step(-12,0,3,3,-2,1)
step(-11,1,4,3,-1,1)       -- negative-mirror pre-reflection
step(-3,1,5,3,2.5,1)       -- enter P2 shield at z=-4
step(2,1,6,3,2,1)          -- leave P2 shield at z=+1; arm drift
assert(#events('p1_plane')==1 and #events('prism_pass')==2)
assert(#events('pre_injection_mirror_turn')==1 and #events('drift_phase_origin')==0)
step(11,1,7,3,0,1); step(12,0,8,3,0,1); step(11,-1,9,3,0,1)
local origins=events('drift_phase_origin')
assert(#origins==1 and value(origins[1],'y_mm')==0 and value(origins[1],'vz_mm_us')==0,
  table.concat(records,'\n'))

-- Each negative -> positive -> negative turn is one complete fast cycle.
-- The final negative turn has positive slow velocity and owns the return.
local t=9
for cycle=1,25 do
  local returning=cycle==25
  t=t+1; step(-11,-1,t,3,-50,1)
  t=t+1; step(-12,0,t,3,-100,1)
  t=t+1; step(-11,1,t,3,-99,1)
  local vy=returning and -1 or 1
  t=t+1; step(11,1,t,3,-2,vy)
  t=t+1; step(12,0,t,3,returning and 0 or -1,vy)
  t=t+1; step(11,-1,t,3,returning and 1 or -2,vy)
end
assert(#events('drift_phase_return')==1, table.concat(records,'\n'))
assert(#events('drift_phase_candidate')==25)
assert(#events('target_k_phase_sample')==1 and value(events('target_k_phase_sample')[1],'k')==25)
assert(#events('target_k')==1 and value(events('target_k')[1],'k')==25,
  table.concat(records,'\n'))
assert(#events('central_plane')>0)

print=original_print
print('CANDIDATE_PLANE_EVENTS=PASS active_face interpolation pre_reflection prism_pass turn_phase same_origin_turn_K25')
