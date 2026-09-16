-- Plain Lua regression: no SIMION process, PA, or filesystem mutation.
local repo=assert(arg[1],'repository root required')
local directory=repo..'/projects/parallel_mirror_dual_stripe_mr_tof/simion/'
local original_loadfile=loadfile
local map=assert(loadfile(directory..'candidate_voltage_map.lua'))()
local point={mirror_voltages_v={0,-10,20,30,50},stripe_biases_v={-4,6},
  prism_voltages_v={141.3329402510257,0},
  accelerator_voltages_v={40,30,0},accelerator_ring_voltages_v={25,20,15,10,5},
  nonaccelerator_scale=0.5,detector_box_mm={0,0,0,1,1,1},detector_normal_project='+z',
  first_prism_l0={target_plane_z_mm=-101},
  mirror_regions_project={negative={z_min_mm=-20,z_max_mm=-10},positive={z_min_mm=10,z_max_mm=20}},
  prism_regions_project={p1={y_min_mm=-10,y_max_mm=10,z_min_mm=-110,z_max_mm=-90},
    p2={y_min_mm=-10,y_max_mm=10,z_min_mm=90,z_max_mm=110}},
  runtime_accelerator_field_gate_enable=true,
  phase_origin_mirror_side=1,return_mirror_side=-1,
  target_drift_period_ratio=25.5,target_half_oscillation_count=51,trajectory_quality=8,maximum_step_us=0.002,
  full_path_timeout_us=5}
local function build(value)
  return map(value.mirror_voltages_v,value.stripe_biases_v,
    value.prism_voltages_v,
    value.accelerator_voltages_v,value.accelerator_ring_voltages_v,
    value.nonaccelerator_scale)
end
local expected=build(point)
for index=1,5 do
  assert(expected.analyser[index]==point.mirror_voltages_v[index]*point.nonaccelerator_scale)
  assert(expected.analyser[index+5]==expected.analyser[index])
  assert(expected.accelerator[index+4]==point.accelerator_ring_voltages_v[index])
end
assert(expected.analyser[11]==-2 and expected.analyser[12]==-2)
assert(expected.analyser[13]==3 and expected.analyser[14]==3)
assert(expected.analyser[16]==point.prism_voltages_v[1] and expected.analyser[17]==point.prism_voltages_v[2])
for _,id in ipairs({15,18,20}) do assert(expected.analyser[id]==0) end
assert(expected.analyser[19]==nil and expected.accelerator[1]==0)
assert(expected.accelerator[2]==40 and expected.accelerator[3]==30 and expected.accelerator[4]==0)
for _,field in ipairs({'mirror_voltages_v','stripe_biases_v','prism_voltages_v','accelerator_voltages_v',
  'accelerator_ring_voltages_v','nonaccelerator_scale'}) do
  local saved=point[field]; point[field]=nil
  assert(not pcall(build,point),'missing '..field..' accepted')
  point[field]=saved
end
point.mirror_voltages_v[1]=1
assert(not pcall(build,point),'non-grounded A accepted')
point.mirror_voltages_v[1]=0
point.accelerator_ring_voltages_v[3]=math.huge
assert(not pcall(build,point),'nonfinite ring voltage accepted')
point.accelerator_ring_voltages_v[3]=15
local program_file=assert(io.open(directory..'mrtof_candidate.lua','rb'))
local program_text=program_file:read('*a'); program_file:close()
local mapper_file=assert(io.open(directory..'candidate_voltage_map.lua','rb'))
local mapper_text=mapper_file:read('*a'); mapper_file:close()
local calls={}
local function pa(index)
  return {load=function(self,path) self.path=path end,
    fast_adjust=function(self,values) self.values=values; calls[#calls+1]='adjust'..index end,
    save=function(self,path) assert(path==self.path); self.saved=true; calls[#calls+1]='save'..index end}
end
simion={wb={instances={{pa=pa(1)},{pa=pa(2)},{pa=pa(3)}}}}
for _,instance in ipairs(simion.wb.instances) do instance._debug_update_size=function() end end
function simion.wb:load(path) self.filename=path end
function simion.wb:save(path)
  if arg and arg[17]=='read_only_voltageized' then
    assert(not self.instances[1].pa.saved and not self.instances[2].pa.saved
      and not self.instances[3].pa.saved,'read-only PA binding mutated a source PA')
  else
    assert(self.instances[1].pa.saved and self.instances[2].pa.saved,'IOB saved before PA0 voltages')
    assert(not self.instances[3].pa.saved,'raw detector PA was mutated')
  end
  self.filename=path
end
local active_local_config=nil
loadfile=function(path)
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.voltage_map.lua' then return function() return map end end
  if path=='virtual/source.mirror_cycle_counter.lua' then
    return assert(original_loadfile(directory..'mirror_cycle_counter.lua'))
  end
  if path=='virtual/source.local_refinement.lua' and active_local_config then
    return function() return active_local_config end
  end
  return original_loadfile(path)
end
local written={}
io.open=function(path,mode)
  if mode=='rb' then
    local text=path:match('voltage_map%.lua$') and mapper_text or 'fixture'
    return {read=function() return text end,close=function() end}
  end
  assert(mode=='wb','unexpected file operation')
  return {write=function(_,text) written[path]=text end,close=function() end}
end
arg={'virtual/3_instance_seed.iob','virtual/mrtof_analyzer.pa0',
  'virtual/mrtof_accelerator.pa0','virtual/mrtof_detector.pa#','virtual/review.iob',
  'virtual/source.lua','virtual/source.fly2',0,0,0,0,0,0,0,0,0}
assert(original_loadfile(directory..'build_three_component_iob.lua'))()
assert(table.concat(calls,',')=='adjust1,save1,adjust2,save2','PA persistence order changed')
assert(simion.wb.instances[1].pa.values[16]==point.prism_voltages_v[1]
  and simion.wb.instances[1].pa.values[17]==point.prism_voltages_v[2],
  'IOB persistence did not apply run-local prism voltages')
assert(written['virtual/review.voltage_map.lua']==mapper_text,'mapper sidecar not copied')
assert(written['virtual/review.mirror_cycle_counter.lua']=='fixture','cycle-counter companion not copied')
assert(written['virtual/review.operating_point.lua']=='fixture','operating point not copied')
assert(written['virtual/review.fly2']=='fixture','Fly2 companion not copied')
for id,value in pairs(expected.analyser) do assert(simion.wb.instances[1].pa.values[id]==value) end
for id,value in pairs(expected.accelerator) do assert(simion.wb.instances[2].pa.values[id]==value) end
calls={};simion.wb.instances={{pa=pa(1)},{pa=pa(2)},{pa=pa(3)}}
for _,instance in ipairs(simion.wb.instances) do instance._debug_update_size=function() end end
arg={'virtual/3_instance_seed.iob','virtual/iob_input_analyzer.pa',
  'virtual/iob_input_accelerator.pa','virtual/iob_input_detector.pa','virtual/read_only.iob',
  'virtual/source.lua','virtual/source.fly2',0,0,0,0,0,0,0,0,0,'read_only_voltageized'}
assert(original_loadfile(directory..'build_three_component_iob.lua'))()
assert(#calls==0,'read-only voltageized PA binding performed Fast Adjust or save')
-- SIMION alone understands `adjustable`; strip only that declaration keyword
-- to exercise the unchanged callback contract with a stock Lua interpreter.
function simion.workbench_program() segment={} end
function simion.early_access(version) assert(version==8.2) end
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
V_stripe_1,V_stripe_2,V_prism_1,V_prism_2,V_repeller,V_grid1,V_grid2,V_nonaccelerator_scale=-8,12,99,0,44,33,1,0.25
calls={}
segment.fast_adjust()
assert(#calls==0,'standalone accelerator field gate must not use PA-family Fast Adjust')
runtime_fast_adjust_enable=1
segment.fast_adjust()
assert(#calls==1 and calls[1]=='adjust1','only the analyser may use runtime Fast Adjust')
assert(simion.wb.instances[1].pa.values[11]==-2 and simion.wb.instances[1].pa.values[13]==3)
assert(simion.wb.instances[1].pa.values[16]==99 and simion.wb.instances[1].pa.values[17]==0,
  'runtime prism adjustables were not applied to physical prism IDs')
assert(simion.wb.instances[2].pa.values==nil,
  'standalone accelerator operating PA must remain unmodified')
point.prism_switch={enabled=true,electrode_id=17,time_us=3,
  injection_voltage_v=point.prism_voltages_v[2],extraction_voltage_v=-12,
  prism_1_extraction_voltage_v=0}
assert(not pcall(function()
  assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
end),'active static MR-TOF Candidate accepted superseded P1/P2 switching')
point.prism_switch=nil
point.patch_interface_planes_project={{name='test',region='central_transport',face='z_test',axis='z',
  coordinate_mm=0,u_axis='x',u_min_mm=-1,u_max_mm=1,v_axis='y',v_min_mm=-1,v_max_mm=1}}
active_local_config={enabled=true,global_analyzer_instance=1,accelerator_instance=7,detector_instance=8,
  instances={{instance=2,z_max_mm=-131},{instance=3,z_min_mm=-131,z_max_mm=-72},
    {instance=4,z_min_mm=-72,z_max_mm=72},{instance=5,z_min_mm=72,z_max_mm=131},
    {instance=6,z_min_mm=131}}}
point.accelerator_pulse_mode='initial_exit_triggered_single_center'
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
simion.wb.instances={}
for index,name in ipairs({'iob_input_analyzer.pa','iob_input_local_1.pa','iob_input_local_2.pa',
  'iob_input_local_3.pa','iob_input_local_4.pa','iob_input_local_5.pa',
  'iob_input_accelerator.pa','iob_input_detector.pa'}) do
  simion.wb.instances[index]={filename='virtual/'..name,pa=pa(index)}
end
segment.initialize_run()
for _,sample in ipairs({
  {2,-132,2},{2,-131,0},{3,-131,3},{3,-72,0},{4,-72,4},{4,72,0},
  {5,72,5},{5,131,0},{6,131,6},{6,130.999,0},{1,500,1},{7,0,7},{8,0,8}
}) do
  ion_instance,ion_pz_mm=sample[1],sample[2]
  segment.instance_adjust()
  assert(ion_instance==sample[3],string.format('local responsibility mismatch for instance %d at z=%g',sample[1],sample[2]))
end
calls={}
local pulse_events={}
local pulse_test_print=print
print=function(message) pulse_events[#pulse_events+1]=message end
ion_number,ion_instance,ion_time_of_flight,ion_splat=1,7,0,0
ion_px_mm,ion_py_mm,ion_pz_mm=0,-55,-5
ion_vx_mm,ion_vy_mm,ion_vz_mm=0,1,-1
segment.initialize();segment.other_actions()
ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3
segment.efield_adjust()
assert(ion_dvoltsx_gu==1 and ion_dvoltsy_gu==2 and ion_dvoltsz_gu==3,
  'accelerator field must remain energized before its initial exit')
ion_instance,ion_time_of_flight,ion_pz_mm=1,0.1,-6
segment.other_actions()
print=pulse_test_print
local safe_exit_count,pulse_off_count=0,0
for _,message in ipairs(pulse_events) do
  if message:match('MRTOF_EVENT accelerator_safe_exit ') then safe_exit_count=safe_exit_count+1 end
  if message:match('MRTOF_EVENT accelerator_pulse_off ') then pulse_off_count=pulse_off_count+1 end
end
assert(safe_exit_count==1 and pulse_off_count==1,
  'initial accelerator exit must emit one detector-blind safe-exit event and one N=1 pulse event')
ion_instance=7
ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3
segment.efield_adjust()
assert(ion_dvoltsx_gu==0 and ion_dvoltsy_gu==0 and ion_dvoltsz_gu==0,
  'accelerator field must be suppressed after its initial exit')
point.accelerator_pulse_mode='fixed_global_time'
point.accelerator_pulse_off_time_us=0.2
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
simion.wb.instances={}
for index,name in ipairs({'iob_input_analyzer.pa','iob_input_local_1.pa','iob_input_local_2.pa',
  'iob_input_local_3.pa','iob_input_local_4.pa','iob_input_local_5.pa',
  'iob_input_accelerator.pa','iob_input_detector.pa'}) do
  simion.wb.instances[index]={filename='virtual/'..name,pa=pa(index)}
end
segment.initialize_run()
ion_number,ion_instance,ion_time_of_flight,ion_splat=1,7,0.199,0
ion_px_mm,ion_py_mm,ion_pz_mm=0,-55,-5
ion_vx_mm,ion_vy_mm,ion_vz_mm=0,1,-1
ion_time_step=0.01
segment.tstep_adjust()
assert(math.abs(ion_time_step-0.001)<1e-12,
  'fixed global pulse must force an integration boundary at the frozen time')
ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3
segment.efield_adjust()
assert(ion_dvoltsx_gu==1 and ion_dvoltsy_gu==2 and ion_dvoltsz_gu==3,
  'accelerator field must remain energized before the frozen global time')
ion_time_of_flight=0.2
segment.other_actions()
ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=1,2,3
segment.efield_adjust()
assert(ion_dvoltsx_gu==0 and ion_dvoltsy_gu==0 and ion_dvoltsz_gu==0,
  'accelerator field must be suppressed at the frozen global time')
point.accelerator_pulse_off_time_us=nil
assert(not pcall(function()
  assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
end),'fixed global pulse without a time was accepted')
point.accelerator_pulse_mode=nil
print('CANDIDATE_VOLTAGE_MAP=PASS mapping validation persistence sidecars independent_runtime_adjust pulsed_accelerator fixed_global_pulse')

-- Exercise the real reload inspector with read-only PA getters. A mutating
-- API is intentionally absent, so an accidental adjust/save fails this test.
local original_print=print
local inspector=assert(original_loadfile(directory..'inspect_three_component_iob.lua'))
local function inspection(defect)
  local raw_arrays,report_lines={},{}
  local report_closed=false
  local function array(name,values,raw)
    local result={filename=name,nx=22,ny=2,nz=2,dx_mm=1,dy_mm=1,dz_mm=1}
    function result:point(x,y,z)
      if not values then
        return defect=='detector_voltage' and x==0 and y==0 and z==0 and 1 or 0,
          defect~='detector_empty' and x==1 and y==1 and z==1
      end
      local id=(y==0 and z==0) and x or nil
      if raw and defect=='unknown_id' and x==21 and y==0 and z==0 then return 99,true end
      if raw and defect=='missing_id' and id==2 then return 0,false end
      if id and values[id]~=nil then
        if raw then return id,true end
        if defect=='lost_material' and id==2 then return values[id],false end
        return values[id]+((defect=='wrong_voltage' and id==2) and 1 or 0),true
      end
      return 0,false
    end
    function result:close() self.closed=true end
    return result
  end
  local instances={}
  for index,name in ipairs({'mrtof_analyzer','mrtof_accelerator','mrtof_detector'}) do
    local values=index==1 and expected.analyser or index==2 and expected.accelerator or nil
    local suffix=index<3 and '.pa0' or '.pa#'
    instances[index]={filename=name..suffix,pa=array(name..suffix,values,false),
      x=0,y=0,z=0,az=0,el=0,rt=0,scale=1}
    if index<3 then
      raw_arrays['virtual/'..name..'.pa#']=array(name..'.pa#',values,true)
    end
  end
  if defect=='dimensions' then raw_arrays['virtual/mrtof_analyzer.pa#'].nx=23 end
  if defect=='mesh' then raw_arrays['virtual/mrtof_analyzer.pa#'].dx_mm=2 end
  for _,field in ipairs({'az','el','rt','scale'}) do
    if defect==field then instances[2][field]=instances[2][field]+1 end
  end
  simion={wb={instances=instances},pas={}}
  function simion.wb:load(path) assert(path=='virtual/review.iob'); self.filename=path end
  function simion.pas:open(path) return assert(raw_arrays[path],'unexpected PA opened: '..path) end
  loadfile=function(path)
    if path=='virtual/review.operating_point.lua' then
      if defect=='missing_sidecar' then return nil end
      return function() return point end
    end
    if path=='virtual/review.voltage_map.lua' then return function() return map end end
    error('unexpected input: '..path)
  end
  io.open=function(path,mode)
    assert(path=='virtual/report.txt' and mode=='wb','unexpected filesystem operation')
    return {write=function(_,text) report_lines[#report_lines+1]=text end,
      flush=function() end,close=function() report_closed=true end}
  end
  arg={'virtual/review.iob','virtual/report.txt',0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1}
  print=function() end
  local ok,err=pcall(inspector)
  print=original_print
  local text=table.concat(report_lines,'\n')
  if defect then
    assert(not ok,'inspection incorrectly passed '..defect)
    assert(not text:find('VOLTAGE_RELOAD=PASS',1,true),'failed inspection emitted voltage PASS')
    assert(not text:find('STATUS=PASS',1,true),'failed inspection emitted overall PASS')
    if defect~='missing_sidecar' then assert(report_closed,'failure leaked report handle') end
  else
    assert(ok,err)
    assert(report_closed and text:find('POSE_RELOAD=PASS',1,true))
    assert(text:find('VOLTAGE_RELOAD=PASS',1,true) and text:find('DETECTOR_ZERO=PASS',1,true))
    for _,raw in pairs(raw_arrays) do assert(raw.closed,'raw PA was not closed') end
    local count=0
    for _ in text:gmatch('VOLTAGE_NODE instance=') do count=count+1 end
    assert(count==28,'not all 19 analyser and 9 accelerator physical IDs were checked')
  end
end
inspection()
for _,defect in ipairs({'missing_sidecar','unknown_id','missing_id','wrong_voltage','lost_material',
  'dimensions','mesh','az','el','rt','scale','detector_voltage','detector_empty'}) do inspection(defect) end
print('CANDIDATE_VOLTAGE_RELOAD=PASS 28_physical_ids detector_all_nodes pose 13_failure_cases')
