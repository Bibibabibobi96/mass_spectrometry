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
  phase_origin_mirror_side=1,
  runtime_fast_adjust_accelerator_enable=true,
  target_oscillation_count=25,trajectory_quality=8,maximum_step_us=0.002,
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
loadfile=function(path)
  if path=='virtual/source.operating_point.lua' then return function() return point end end
  if path=='virtual/source.voltage_map.lua' then return function() return map end end
  if path=='virtual/source.mirror_cycle_counter.lua' then
    return assert(original_loadfile(directory..'mirror_cycle_counter.lua'))
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
arg={'virtual/3_instance_seed.iob','virtual/mrtof_analyzer.pa0',
  'virtual/mrtof_accelerator.pa0','virtual/mrtof_detector.pa#','virtual/read_only.iob',
  'virtual/source.lua','virtual/source.fly2',0,0,0,0,0,0,0,0,0,'read_only_voltageized'}
assert(original_loadfile(directory..'build_three_component_iob.lua'))()
assert(#calls==0,'read-only voltageized PA binding performed Fast Adjust or save')
-- SIMION alone understands `adjustable`; strip only that declaration keyword
-- to exercise the unchanged callback contract with a stock Lua interpreter.
function simion.workbench_program() segment={} end
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
V_stripe_1,V_stripe_2,V_prism_1,V_prism_2,V_repeller,V_grid1,V_grid2,V_nonaccelerator_scale=-8,12,99,0,44,33,1,0.25
calls={}
segment.fast_adjust()
assert(#calls==0,'saved PA0 flight must not repeat Fast Adjust by default')
runtime_fast_adjust_enable=1
segment.fast_adjust()
assert(simion.wb.instances[1].pa.values[11]==-2 and simion.wb.instances[1].pa.values[13]==3)
assert(simion.wb.instances[1].pa.values[16]==99 and simion.wb.instances[1].pa.values[17]==0,
  'runtime prism adjustables were not applied to physical prism IDs')
assert(simion.wb.instances[2].pa.values[2]==44 and simion.wb.instances[2].pa.values[3]==33)
assert(simion.wb.instances[2].pa.values[4]==1 and simion.wb.instances[2].pa.values[5]==25,
  'runtime endpoint adjustables must not silently rederive frozen ring voltages')
point.prism_switch={enabled=true,electrode_id=17,time_us=3,
  injection_voltage_v=point.prism_voltages_v[2],extraction_voltage_v=-12,
  prism_1_extraction_voltage_v=0}
assert(loadstring(program_text:gsub('\nadjustable ','\n'),'@virtual/source.lua'))()
runtime_fast_adjust_enable=0
ion_instance,ion_time_of_flight=1,2
segment.fast_adjust()
assert(adj_elect17==point.prism_switch.injection_voltage_v,
  'P2 switch did not preserve its injection voltage before the switch')
assert(adj_elect16==point.prism_voltages_v[1],
  'P1 switch did not preserve its injection voltage before the switch')
ion_time_of_flight=3
segment.fast_adjust()
assert(adj_elect17==point.prism_switch.extraction_voltage_v,
  'P2 switch did not apply its extraction voltage at the switch time')
assert(adj_elect16==point.prism_switch.prism_1_extraction_voltage_v,
  'P1 switch did not apply its extraction voltage at the switch time')
ion_instance,ion_time_of_flight=2,4
adj_elect17=123
segment.fast_adjust()
assert(adj_elect17==123,'P2 switch leaked into a non-analyser PA instance')
runtime_fast_adjust_enable=1
assert(not pcall(segment.fast_adjust),
  'prism extraction switching and full analyser Fast Adjust were allowed together')
point.prism_switch=nil
print('CANDIDATE_VOLTAGE_MAP=PASS mapping validation persistence sidecars runtime_adjustables')

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
