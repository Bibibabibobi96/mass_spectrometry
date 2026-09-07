-- Assemble analyser, shielded accelerator, and detector as three independent PAs.
-- Usage: ... SEED ANALYSER_PA0 ACCELERATOR_PA0 DETECTOR_PA0 OUTPUT PROGRAM FLY2 AX AY AZ BX BY BZ CX CY CZ
-- SIMION command-line option parsing requires a `--` separator before a
-- negative project coordinate.  Keep the separator in place and apply a
-- stable offset: SIMION's `arg` proxy does not support table.remove().
local offset=(arg[1]=='--') and 1 or 0
local function input(index,label)
  local value=assert(arg[index+offset],label)
  return value
end
local seed=input(1, 'three-instance seed required')
local paths={input(2, 'analyser pa0 required'),input(3, 'accelerator pa0 required'),input(4, 'detector raw PA required')}
local output=input(5, 'output iob required')
local program=input(6, 'program required')
local fly2=input(7, 'fly2 required')
local function number(index,label)
  local value=input(index,label..' required')
  return assert(tonumber(value),label..' must be numeric')
end
local origins={{number(8,'analyser x'),number(9,'analyser y'),number(10,'analyser z')},
               {number(11,'accelerator x'),number(12,'accelerator y'),number(13,'accelerator z')},
               {number(14,'detector x'),number(15,'detector y'),number(16,'detector z')}}
assert(seed:match('3_instance_seed%.iob$'), 'must use the repository three-instance IOB seed')
assert(paths[1]:match('%.pa0$') and paths[2]:match('%.pa0$'), 'analyser and accelerator must be solved pa0 arrays')
assert(paths[3]:match('%.pa#$'), 'detector must be a raw zero-voltage geometry PA#')
assert(program:match('%.lua$') and output:match('%.iob$'), 'program/output suffixes must be .lua/.iob')
local operating_point_path=program:gsub('%.lua$','.operating_point.lua')
local voltage_map_path=program:gsub('%.lua$','.voltage_map.lua')
local operating_point=assert(loadfile(operating_point_path),'run-local operating point required')()
local voltage_map=assert(loadfile(voltage_map_path),'run-local voltage mapper required')()
local voltages=voltage_map(operating_point.mirror_voltages_v,operating_point.stripe_biases_v,
  operating_point.prism_voltages_v,operating_point.accelerator_voltages_v,operating_point.accelerator_ring_voltages_v,
  operating_point.nonaccelerator_scale)
local instance_voltages={voltages.analyser,voltages.accelerator}
local seed_directory=seed:match('^(.*[\\/])') or ''
for index=1,10 do
  local placeholder=seed_directory..string.format('iob_seed_placeholder_%02d.pa0',index)
  local handle=io.open(placeholder,'rb')
  assert(handle, 'three-instance seed companion is missing: '..placeholder)
  handle:close()
end
local wb=assert(simion.wb, 'SIMION 2020 did not create an empty Workbench object')
assert(wb.load, 'SIMION 2020 Workbench API lacks the supported IOB load method')
wb:load(seed)
assert(wb.filename and #wb.instances==3, 'three-instance seed must contain exactly three PA instances')
for index,path in ipairs(paths) do
  local instance=wb.instances[index]
  instance.pa:load(path)
  if instance_voltages[index] then
    -- Official SIMION pa:fast_adjust + pa:save persist the contract settings
    -- in each run-local PA0, so GUI review does not require a particle flight.
    instance.pa:fast_adjust(instance_voltages[index])
    instance.pa:save(path)
    print(string.format('THREE_COMPONENT_VOLTAGES persisted=true instance=%d pa=%s',index,path))
  end
  assert(instance._debug_update_size, 'SIMION 2020 instance-size refresh unavailable')
  instance:_debug_update_size()
  instance.x,instance.y,instance.z=origins[index][1],origins[index][2],origins[index][3]
  instance.az,instance.el,instance.rt,instance.scale=0,0,0,1
end
wb:save(output)
local function copy(source,target)
  local i=assert(io.open(source,'rb')); local text=i:read('*a'); i:close()
  local o=assert(io.open(target,'wb')); o:write(text); o:close()
end
copy(program,output:gsub('%.iob$','.lua'))
-- The Fly2 is a Workbench companion, not an IOB instance table.  Copy it only
-- after wb:save(), so a freshly assembled IOB can be launched by the one
-- official flight entry without changing its GUI-visible PA instances.
copy(fly2,output:gsub('%.iob$','.fly2'))
copy(operating_point_path,output:gsub('%.iob$','.operating_point.lua'))
copy(voltage_map_path,output:gsub('%.iob$','.voltage_map.lua'))
print(string.format('THREE_COMPONENT_IOB_BUILD PASS analyser=(%.12g,%.12g,%.12g) accelerator=(%.12g,%.12g,%.12g) detector=(%.12g,%.12g,%.12g)',
  origins[1][1],origins[1][2],origins[1][3],origins[2][1],origins[2][2],origins[2][3],origins[3][1],origins[3][2],origins[3][3]))
