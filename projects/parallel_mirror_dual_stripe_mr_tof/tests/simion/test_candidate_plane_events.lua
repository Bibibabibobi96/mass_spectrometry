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
  first_prism_l0={target_plane_z_mm=-101},
  mirror_regions_project={negative={z_min_mm=-20,z_max_mm=-10},positive={z_min_mm=10,z_max_mm=20}},
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
local function begin(z,vz,x,y)
  records={}; segment.initialize_run()
  state(z,vz,0,x,y); segment.initialize()
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

-- +z active face: an initial-step arrival records the actual surface, once.
begin(12,-1); step(10,-1,2); step(9,-1,3)
local hits=events('detector')
assert(#hits==1 and value(hits[1],'z_mm')==10 and value(hits[1],'t_us')==2)
-- A crossing step interpolates to z=10, never the slab middle z=9.
begin(12,-1); step(8,-1,4)
hits=events('detector')
assert(#hits==1 and value(hits[1],'z_mm')==10 and value(hits[1],'t_us')==2)
-- Backside and finite-aperture misses are not active-face detections.
begin(7,1); step(11,1,4); assert(#events('detector')==0)
begin(12,-1,3,0); step(8,-1,4,3,0); assert(#events('detector')==0)
begin(12,-1,0,4); step(8,-1,4,0,4); assert(#events('detector')==0)
-- Central-plane cycle observables begin only after the explicit inbound y=0
-- handoff.  Exact zero nodes then remain single-owner events.
begin(-1,1,0,1); step(0,1,1,0,-1,-1); step(1,1,2,0,-2,-1)
assert(#events('central_plane')==1)
-- A z=0 birth before the main drift is not a Poincare crossing.
begin(0,1,0,1); step(1,1,1,0,2,1)
assert(#events('central_plane')==0)
-- Central-plane observables belong to the crossing, not the step endpoint.
begin(-2,1,1,1); step(-1,1,1,2,-1,-1); step(2,1,4,5,-2,-1)
local crossings=events('central_plane')
assert(#crossings==1 and value(crossings[1],'t_us')==2)
assert(value(crossings[1],'x_mm')==3 and math.abs(value(crossings[1],'y_mm')+4/3)<1e-10)
-- A contract-derived time boundary is an explicit diagnostic loss, never a
-- silent wall-clock interruption or a target-K success.
begin(-1,1); step(-0.5,1,1000)
local splats=events('splat')
assert(#splats==1 and value(splats[1],'code')==2 and ion_splat==2)

-- Main Candidate binding: P2 inbound y=0 opens the drift interval; 50 mirror
-- turns alone do not stop the ion.  The outbound y=0 handoff owns K=25, and
-- only the later detector surface terminates successfully.
begin(0,1,0,1)
local t=1
step(0,1,t,0,-5,-1)
for _=1,25 do
  t=t+1; step(11,1,t,0,-5,-1)
  t=t+1; step(12,-1,t,0,-5,-1)
  t=t+1; step(0,-1,t,0,-5,-1)
  t=t+1; step(-11,-1,t,0,-5,-1)
  t=t+1; step(-12,1,t,0,-5,-1)
  t=t+1; step(0,1,t,0,-5,-1)
end
assert(ion_splat==0 and #events('target_k')==0,'50 turns incorrectly terminated before drift exit')
t=t+1; step(0,1,t,0,-5,1)
t=t+1; step(0,1,t,0,1,1)
assert(ion_splat==0 and #events('target_k')==1,
  'outbound y=0 did not publish K=25 handoff:\n'..table.concat(records,'\n'))
t=t+1; step(12,1,t,0,1,1)
t=t+1; step(8,-1,t,0,1,1)
assert(ion_splat==1 and #events('detector')==1,'detector did not own successful termination')
print=original_print
print('CANDIDATE_PLANE_EVENTS=PASS active_face interpolation timeout_loss explicit_main_drift same_direction_K25 detector_termination')
