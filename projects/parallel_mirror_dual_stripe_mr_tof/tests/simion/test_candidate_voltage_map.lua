-- Plain Lua regression: native-corridor runtime only; no SIMION process or PA mutation.
local repo=assert(arg[1],'repository root required')
local directory=repo..'/projects/parallel_mirror_dual_stripe_mr_tof/simion/'
local original_loadfile=loadfile
local map=assert(loadfile(directory..'candidate_voltage_map.lua'))()
local point={mirror_voltages_v={0,-10,20,30,50},stripe_biases_v={-4,6},
  prism_voltages_v={141.3329402510257,0}, accelerator_voltages_v={40,30,0},
  accelerator_ring_voltages_v={25,20,15,10,5}, nonaccelerator_scale=0.5,
  detector_box_mm={0,0,0,1,1,1},detector_normal_project='+z',
  first_prism_l0={target_plane_z_mm=-101},
  mirror_regions_project={negative={z_min_mm=-20,z_max_mm=-10},positive={z_min_mm=10,z_max_mm=20}},
  prism_regions_project={p1={y_min_mm=-10,y_max_mm=10,z_min_mm=-110,z_max_mm=-90},p2={y_min_mm=-10,y_max_mm=10,z_min_mm=90,z_max_mm=110}},
  runtime_accelerator_field_gate_enable=true,phase_origin_mirror_side=1,return_mirror_side=-1,
  target_drift_period_ratio=25.5,target_half_oscillation_count=51,trajectory_quality=8,maximum_step_us=0.002,
  full_path_timeout_us=5}
local function build(value)
  return map(value.mirror_voltages_v,value.stripe_biases_v,value.prism_voltages_v,
    value.accelerator_voltages_v,value.accelerator_ring_voltages_v,value.nonaccelerator_scale)
end
local expected=build(point)
for index=1,5 do
  assert(expected.analyser[index]==point.mirror_voltages_v[index]*point.nonaccelerator_scale)
  assert(expected.analyser[index+5]==expected.analyser[index])
  assert(expected.accelerator[index+4]==point.accelerator_ring_voltages_v[index])
end
assert(expected.analyser[11]==-2 and expected.analyser[12]==-2 and expected.analyser[16]==point.prism_voltages_v[1])
local program_file=assert(io.open(directory..'mrtof_candidate.lua','rb'))
local program_text=program_file:read('*a'); program_file:close()
local calls={}
local function pa(index)
  return {fast_adjust=function(self,values) self.values=values; calls[#calls+1]='adjust'..index end}
end
simion={wb={instances={
  {filename='virtual/analyzer_operating.pa0',pa=pa(1)},
  {filename='virtual/mrtof_analyzer_corridor.pa0',pa=pa(2)},
  {filename='virtual/orthogonal_accelerator_focus.pa0',pa=pa(3)},
  {filename='virtual/mrtof_detector.pa#',pa=pa(4)}}}}
function simion.workbench_program() segment={} end
local priority=assert(original_loadfile(directory..'native_corridor_priority_contract.lua'))()
loadfile=function(path)
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.voltage_map.lua' then return function() return map end end
  if path=='virtual/source.mirror_cycle_counter.lua' then return original_loadfile(directory..'mirror_cycle_counter.lua') end
  if path=='virtual/source.priority.lua' then return function() return priority end end
  return original_loadfile(path)
end
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
segment.initialize_run()
V_mirror_B,V_mirror_C,V_mirror_D,V_mirror_E=-12,22,32,52
V_stripe_1,V_stripe_2,V_prism_1,V_prism_2=-8,12,99,-77
runtime_fast_adjust_enable=0
segment.fast_adjust()
assert(#calls==1 and calls[1]=='adjust2','native GUI Fast Adjust must update only the corridor role')
local values=simion.wb.instances[2].pa.values
for id=1,8 do assert(values[id]~=nil,'missing native channel '..id) end
assert(values[1]==-6 and values[2]==11 and values[3]==16 and values[4]==26)
assert(values[5]==-4 and values[6]==6 and values[7]==99 and values[8]==-77)
ion_number,ion_time_of_flight,ion_instance=1,0.2,2
ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3
segment.efield_adjust()
assert(ion_dvoltsx_gu==1 and ion_dvoltsy_gu==2 and ion_dvoltsz_gu==3,'corridor role was mistaken for accelerator')
ion_instance=3
segment.efield_adjust()
assert(ion_dvoltsx_gu==1 and ion_dvoltsy_gu==2 and ion_dvoltsz_gu==3,'static accelerator field was suppressed')
point.accelerator_pulse_mode='fixed_global_time'; point.accelerator_pulse_off_time_us=0.2
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
segment.initialize_run()
ion_number,ion_instance,ion_time_of_flight,ion_splat=1,3,0.199,0
ion_time_step=0.01; segment.tstep_adjust(); assert(math.abs(ion_time_step-0.001)<1e-12)
ion_time_of_flight=0.2; ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3; segment.efield_adjust()
assert(ion_dvoltsx_gu==0 and ion_dvoltsy_gu==0 and ion_dvoltsz_gu==0,'accelerator field was not suppressed at fixed pulse time')
point.accelerator_pulse_off_time_us=nil
assert(not pcall(function() assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))() end),'fixed global pulse without time accepted')
point.accelerator_pulse_mode=nil
point.prism_switch={enabled=true}
assert(not pcall(function() assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))() end),'superseded P1/P2 switching accepted')
print('CANDIDATE_VOLTAGE_MAP=PASS native_corridor_4_roles voltage_mapping fast_adjust accelerator_pulse')
