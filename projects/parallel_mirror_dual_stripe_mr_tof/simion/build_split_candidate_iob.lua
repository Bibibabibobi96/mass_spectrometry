-- Assemble the independently refined analyser and grounded accelerator PAs.
-- Usage: ... SEED ANALYSER_PA0 ACCELERATOR_PA0 OUTPUT PROGRAM FLY2 AX AY AZ BX BY BZ
local seed=assert(arg[1], 'two-instance seed required')
local analyser=assert(arg[2], 'analyser pa0 required')
local accelerator=assert(arg[3], 'accelerator pa0 required')
local output=assert(arg[4], 'output iob required')
local program=assert(arg[5], 'program required')
local fly2=assert(arg[6], 'fly2 required')
local function number(index,label) return assert(tonumber(arg[index]),label..' must be numeric') end
local origins={{number(7,'analyser x'),number(8,'analyser y'),number(9,'analyser z')},
               {number(10,'accelerator x'),number(11,'accelerator y'),number(12,'accelerator z')}}
assert(seed:match('2_instance_seed%.iob$'), 'must use the repository two-instance IOB seed')
assert(analyser:match('%.pa0$') and accelerator:match('%.pa0$'), 'each component must be a solved pa0')
local seed_directory=seed:match('^(.*[\\/])') or ''
for index=1,10 do
  local placeholder=seed_directory..string.format('iob_seed_placeholder_%02d.pa0',index)
  local handle=io.open(placeholder,'rb')
  assert(handle, 'two-instance seed companion is missing: '..placeholder)
  handle:close()
end
local wb=assert(simion.wb, 'SIMION 2020 did not create an empty Workbench object')
assert(wb.load, 'SIMION 2020 Workbench API lacks the supported IOB load method')
wb:load(seed)
assert(wb.filename, 'SIMION failed to load the IOB seed')
assert(#wb.instances==2, 'two-instance seed must contain exactly two PA instances')
for index,path in ipairs({analyser,accelerator}) do
  local instance=wb.instances[index]
  instance.pa:load(path)
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
copy(fly2,output:gsub('%.iob$','.fly2'))
copy(assert(program:gsub('%.lua$','.operating_point.lua')),output:gsub('%.iob$','.operating_point.lua'))
print(string.format('SPLIT_IOB_BUILD PASS analyser_origin=(%.12g,%.12g,%.12g) accelerator_origin=(%.12g,%.12g,%.12g)',
  origins[1][1],origins[1][2],origins[1][3],origins[2][1],origins[2][2],origins[2][3]))
