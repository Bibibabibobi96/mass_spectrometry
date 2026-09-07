-- Verify the three-component geometry-review IOB without flying particles.
-- Usage: ... IOB REPORT AX AY AZ BX BY BZ CX CY CZ ADX ADY ADZ BDX BDY BDZ CDX CDY CDZ
-- Origins and all component mesh lengths are transported from the frozen contract.
-- Preserve the command-line `--` separator used before negative origins.
local offset=(arg[1]=='--') and 1 or 0
local iob=assert(arg[1+offset], 'IOB required')
local report_path=assert(arg[2+offset], 'report path required')
local expected={}
for index=3+offset,11+offset do expected[#expected+1]=assert(tonumber(arg[index]), 'origin value required') end
local expected_mmgu={}
for instance=1,3 do
  expected_mmgu[instance]={}
  for axis=1,3 do
    local index=11+offset+(instance-1)*3+axis
    local spacing=assert(tonumber(arg[index]), 'component mesh value required')
    assert(spacing>0 and spacing<math.huge, 'component mesh must be finite and positive')
    expected_mmgu[instance][axis]=spacing
  end
end
assert(iob:match('%.iob$'), 'IOB suffix must be .iob')
local directory=iob:match('^(.*[\\/])') or ''
local operating_point_path=iob:gsub('%.iob$','.operating_point.lua')
local voltage_map_path=iob:gsub('%.iob$','.voltage_map.lua')
local operating_point=assert(loadfile(operating_point_path),'IOB operating point required')()
local voltage_map=assert(loadfile(voltage_map_path),'IOB voltage mapper required')()
local voltages=voltage_map(operating_point.mirror_voltages_v,operating_point.stripe_biases_v,
  operating_point.prism_voltages_v,operating_point.accelerator_voltages_v,operating_point.accelerator_ring_voltages_v,
  operating_point.nonaccelerator_scale)
-- This inspector writes only its report; never allow a report to replace an input.
assert(not report_path:lower():match('%.pa[#0-9]*$') and
  not report_path:lower():match('%.iob$') and not report_path:lower():match('%.lua$'),
  'report path must not overwrite a PA, IOB, or Lua input')
local report=assert(io.open(report_path,'wb'))
local function record(text) report:write(text,'\n'); report:flush(); print(text) end
local function close(actual,target) return math.abs(actual-target)<=1e-9 end
local function inspect_voltages(index,pa,expected_voltages)
  local raw_path=directory..pa.filename:match('[^/\\]+$'):gsub('%.pa0$','.pa#')
  assert(raw_path:match('%.pa#$'), 'PA0 must have a same-directory raw PA#')
  local raw=assert(simion.pas:open(raw_path),'cannot open raw electrode ID PA: '..raw_path)
  local counts,samples={},{}
  local ok,err=pcall(function()
    assert(raw.nx==pa.nx and raw.ny==pa.ny and raw.nz==pa.nz, 'raw/PA0 dimensions mismatch')
    assert(close(raw.dx_mm,pa.dx_mm) and close(raw.dy_mm,pa.dy_mm) and close(raw.dz_mm,pa.dz_mm),
      'raw/PA0 mesh mismatch')
    -- Official pa:point(x,y,z) is a read-only getter for potential and material
    -- flag. Do not call fast_adjust, potential_vc with voltages, or any setter:
    -- those would test reconstructed settings rather than the persisted PA0.
    for z=0,raw.nz-1 do for y=0,raw.ny-1 do for x=0,raw.nx-1 do
      local id,electrode=raw:point(x,y,z)
      if electrode then
        assert(expected_voltages[id]~=nil, 'unmapped raw physical electrode ID: '..tostring(id))
        counts[id]=(counts[id] or 0)+1
        if not samples[id] then
          local actual,material=pa:point(x,y,z)
          assert(material, 'PA0 lost material flag for electrode '..id)
          samples[id]={x,y,z,actual}
        end
      end
    end end end
    local scale=100000
    for _,value in pairs(expected_voltages) do scale=math.max(scale,math.abs(value)) end
    -- Installed docs/simion.chm lua_simion.pas.html documents the initial
    -- 100000-V PA encoding scale (pa:clear). Budget floating-point encoding
    -- roundoff, not a field-solution tolerance or a new device voltage.
    local tolerance=16*2^-52*scale
    for id,expected_voltage in pairs(expected_voltages) do
      local sample=assert(samples[id], 'raw PA is missing physical electrode '..id)
      local actual=sample[4]
      assert(math.abs(actual-expected_voltage)<=tolerance,
        string.format('saved PA0 voltage mismatch instance=%d id=%d expected=%.15g actual=%.15g',
          index,id,expected_voltage,actual))
      record(string.format('VOLTAGE_NODE instance=%d id=%d raw_nodes=%d node=%d,%d,%d expected_v=%.15g saved_v=%.15g',
        index,id,counts[id],sample[1],sample[2],sample[3],expected_voltage,actual))
    end
  end)
  raw:close()
  assert(ok,err)
end
local function inspect()
local wb=assert(simion.wb, 'SIMION 2020 did not create an empty Workbench object')
assert(wb.load, 'SIMION 2020 Workbench API lacks the supported IOB load method')
wb:load(iob)
assert(wb.filename and #wb.instances==3, 'MR-TOF review IOB must contain analyser, accelerator, and detector PAs')
local expected_paths={'mrtof_analyzer.pa0','mrtof_accelerator.pa0','mrtof_detector.pa#'}
for index=1,#wb.instances do
  local instance=wb.instances[index]
  local pa=assert(instance.pa, 'instance '..index..' has no loaded PA')
  assert(instance.filename==expected_paths[index], 'instance '..index..' PA basename mismatch')
  assert(pa.filename:match('[^/\\]+$')==expected_paths[index], 'instance '..index..' loaded PA identity mismatch')
  local offset=(index-1)*3
  assert(close(instance.x,expected[offset+1]) and close(instance.y,expected[offset+2]) and close(instance.z,expected[offset+3]), 'instance '..index..' origin mismatch')
  assert(close(instance.az,0) and close(instance.el,0) and close(instance.rt,0) and close(instance.scale,1),
    'instance '..index..' orientation/scale mismatch')
  assert(close(pa.dx_mm,expected_mmgu[index][1]) and close(pa.dy_mm,expected_mmgu[index][2]) and close(pa.dz_mm,expected_mmgu[index][3]), 'instance '..index..' mesh mismatch')
  record(string.format('INSTANCE_%d file=%s origin_mm=%.12g,%.12g,%.12g mesh_mmgu=%.12g,%.12g,%.12g dims=%d,%d,%d',index,instance.filename,instance.x,instance.y,instance.z,pa.dx_mm,pa.dy_mm,pa.dz_mm,pa.nx,pa.ny,pa.nz))
  if index<3 then
    inspect_voltages(index,pa,index==1 and voltages.analyser or voltages.accelerator)
  else
    local electrodes=0
    for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
      local potential,electrode=pa:point(x,y,z)
      assert(potential==0, 'detector contains a nonzero potential node')
      if electrode then electrodes=electrodes+1 end
    end end end
    assert(electrodes>0, 'detector has no terminal electrode nodes')
    record(string.format('DETECTOR_ZERO=PASS electrode_nodes=%d',electrodes))
  end
end
record('POSE_RELOAD=PASS')
record('VOLTAGE_RELOAD=PASS')
record('PHYSICAL_MODEL=false')
record('PARTICLE_FLY_EXECUTED=false')
record('STATUS=PASS')
end
local ok,err=pcall(inspect)
report:close()
assert(ok,err)
