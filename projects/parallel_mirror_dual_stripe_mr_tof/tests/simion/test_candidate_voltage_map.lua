-- Plain Lua regression: native-corridor runtime only; no SIMION process or PA mutation.
local repo=assert(arg[1],'repository root required')
local directory=repo..'/projects/parallel_mirror_dual_stripe_mr_tof/simion/'
local original_loadfile=loadfile
local map=assert(loadfile(directory..'candidate_voltage_map.lua'))()
local function test_priority() return {schema_version=1,role='mrtof_native_corridor_iob_priority_contract',
  instances={{role='global_fallback',priority_number=1},{role='native_corridor',priority_number=2},
    {role='accelerator',priority_number=3},{role='detector',priority_number=4}},
  corridor_voltage_groups={{2,7},{3,8},{4,9},{5,10},{11,12},{13,14},{16},{17}}} end
local priority=test_priority()
local point={mirror_voltages_v={0,-10,20,30,50},stripe_biases_v={-4,6},
  prism_voltages_v={141.3329402510257,0}, accelerator_voltages_v={40,30,0},
  accelerator_ring_voltages_v={45,42,39,36,33,30,27,24,21,18,15,12,9,6,3}, nonaccelerator_scale=0.5,
  detector_box_mm={0,0,0,1,1,1},detector_normal_project='+z',
  first_prism_l0={target_plane_z_mm=-101},
  mirror_regions_project={negative={z_min_mm=-20,z_max_mm=-10},positive={z_min_mm=10,z_max_mm=20}},
  prism_regions_project={p1={y_min_mm=-10,y_max_mm=10,z_min_mm=-110,z_max_mm=-90},p2={y_min_mm=-10,y_max_mm=10,z_min_mm=90,z_max_mm=110}},
  runtime_accelerator_field_gate_enable=true,phase_origin_mirror_side=1,return_mirror_side=-1,
  target_drift_period_ratio=25.5,target_half_oscillation_count=51,trajectory_quality=8,maximum_step_us=0.002,
  full_path_timeout_us=5}
local function build(value)
  local values=map.physical_voltages(value.mirror_voltages_v,value.stripe_biases_v,value.prism_voltages_v,
    value.accelerator_voltages_v,value.accelerator_ring_voltages_v,value.nonaccelerator_scale)
  values.corridor=map.corridor_voltages(values.analyser,priority.corridor_voltage_groups)
  return values
end
assert(type(map)=='table' and getmetatable(map)==nil,'legacy callable mapper must not remain')
local expected=build(point)
for index=1,#point.accelerator_ring_voltages_v do
  assert(expected.accelerator[index+4]==point.accelerator_ring_voltages_v[index])
end
for index=1,5 do
  assert(expected.analyser[index]==point.mirror_voltages_v[index]*point.nonaccelerator_scale)
  assert(expected.analyser[index+5]==expected.analyser[index])
end
assert(expected.analyser[11]==-2 and expected.analyser[12]==-2 and expected.analyser[16]==point.prism_voltages_v[1])
local channels={-5,10,15,25,-2,3,point.prism_voltages_v[1],0}
assert(#expected.corridor==8)
for id=1,8 do assert(expected.corridor[id]==channels[id]) end
local function reject_groups(groups)
  assert(not pcall(map.corridor_voltages,expected.analyser,groups),
    'invalid corridor groups accepted')
end
reject_groups(nil)
reject_groups({})
for _,bad in ipairs({{}, {2,3}, {0}, {1.5}, {'2'}, {19}, {25}, {math.huge}}) do
  local groups=test_priority().corridor_voltage_groups
  groups[1]=bad
  reject_groups(groups)
end
for _,bad in ipairs({0/0,math.huge,-math.huge}) do
  assert(not pcall(map.physical_voltages,{0,bad,20,30,50},point.stripe_biases_v,point.prism_voltages_v,
    point.accelerator_voltages_v,point.accelerator_ring_voltages_v,point.nonaccelerator_scale),'nonfinite physical voltage accepted')
end
assert(expected.analyser[15]==0 and expected.analyser[18]==0 and expected.analyser[20]==0
  and expected.analyser[19]==nil and expected.analyser[25]==nil)
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
loadfile=function(path)
  if path=='virtual/source.voltage_waveforms.lua' then return original_loadfile(repo..'/common/simion/voltage_waveforms.lua') end
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.voltage_map.lua' then return function() return map end end
  if path=='virtual/source.mirror_cycle_counter.lua' then return original_loadfile(directory..'mirror_cycle_counter.lua') end
  if path=='virtual/source.priority.lua' then return function() return priority end end
  if path=='virtual/source.scalar_field_adapter.lua' then return function()
    return function() return function() end end
  end end
  return original_loadfile(path)
end
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
segment.initialize_run()
V_mirror_B,V_mirror_C,V_mirror_D,V_mirror_E=-12,22,32,52
V_stripe_1,V_stripe_2,V_prism_1,V_prism_2=-8,12,99,-77
runtime_fast_adjust_enable=0
segment.fast_adjust()
assert(#calls==3 and calls[1]=='adjust2' and calls[2]=='adjust3' and calls[3]=='adjust2',
  'run initialization must adjust both roles and the GUI edit only its changed role')
local values=simion.wb.instances[2].pa.values
for id=1,8 do assert(values[id]~=nil,'missing native channel '..id) end
assert(values[1]==-6 and values[2]==11 and values[3]==16 and values[4]==26)
assert(values[5]==-4 and values[6]==6 and values[7]==99 and values[8]==-77)
local accelerator_values=simion.wb.instances[3].pa.values
for id=1,4+#point.accelerator_ring_voltages_v do
  assert(accelerator_values[id]~=nil,'missing accelerator channel '..id)
end
assert(accelerator_values[2]==40 and accelerator_values[3]==30 and accelerator_values[4]==0)
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
for _,time in ipairs({-1,0.2,0.201}) do
  ion_time_of_flight=time;ion_time_step=0.01;segment.tstep_adjust()
  assert(ion_time_step==point.maximum_step_us,'exact/past edge must preserve ordinary maximum step')
end
ion_time_of_flight=-1;ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3
segment.efield_adjust()
assert(ion_dvoltsx_gu==1,'fixed pulse remains held on before off, including negative clock')
ion_time_of_flight=0.2-1e-12;ion_time_step=0.01;segment.tstep_adjust()
assert(ion_time_step==0.2-ion_time_of_flight,'future edges must not gain a new epsilon cutoff')
ion_time_of_flight=0.2; ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3; segment.efield_adjust()
assert(ion_dvoltsx_gu==0 and ion_dvoltsy_gu==0 and ion_dvoltsz_gu==0,'accelerator field was not suppressed at fixed pulse time')
point.accelerator_pulse_off_time_us=nil
assert(not pcall(function() assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))() end),'fixed global pulse without time accepted')
point.accelerator_pulse_mode=nil
point.prism_switch={enabled=true}
assert(not pcall(function() assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))() end),'superseded P1/P2 switching accepted')
point.prism_switch=nil
priority.corridor_voltage_groups=nil
local count=#calls
assert(not pcall(function()
  assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
  segment.initialize_run()
end),'missing groups accepted by flight')
assert(#calls==count,'missing groups must fail before Fast Adjust')
local physical={}
for id=1,20 do physical[id]=expected.analyser[id] or 0 end
point.static_field={analyzer_voltages_v=physical,accelerator_voltages_v=expected.accelerator}
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
segment.initialize_run(); segment.fast_adjust()
assert(#calls==count,'static collision arrays must never be Fast Adjusted')
V_prism_1=V_prism_1+1
assert(not pcall(segment.fast_adjust),'static field accepted a GUI voltage change')
assert(#calls==count,'rejected static edit must not change a PA')
print('CANDIDATE_VOLTAGE_MAP=PASS native_corridor_4_roles voltage_mapping fast_adjust accelerator_pulse')
