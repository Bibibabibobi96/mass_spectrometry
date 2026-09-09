-- Assemble a global analyser fallback, five overlapping local replacements,
-- shielded accelerator, and independent detector.
-- Usage: ... SEED PA1 ... PA8 OUTPUT PROGRAM FLY2 LOCAL_CONFIG (X Y Z)*8
local offset=(arg[1]=='--') and 1 or 0
local function input(index,label)
  local value=assert(arg[index+offset],label..' required')
  return value
end
local seed=input(1,'eight-instance seed')
local paths={}
for index=1,8 do paths[index]=input(1+index,'PA '..index) end
local output=input(10,'output IOB')
local program=input(11,'program')
local fly2=input(12,'Fly2')
local local_config=input(13,'local-refinement config')
local origins={}
for index=1,8 do
  origins[index]={}
  for axis=1,3 do
    origins[index][axis]=assert(tonumber(input(13+(index-1)*3+axis,
      string.format('instance %d origin axis %d',index,axis))),'origin must be numeric')
  end
end
assert(seed:match('8_instance_seed%.iob$'),'must use the repository eight-instance IOB seed')
assert(paths[1]:match('mrtof_analyzer%.pa0$') and paths[7]:match('mrtof_accelerator%.pa0$')
  and paths[8]:match('mrtof_detector%.pa#$'),'global analyser/accelerator/detector bindings are invalid')
for index=2,6 do assert(paths[index]:match('local_.*%.pa0$'),'local replacement PA filename is invalid') end
assert(output:match('%.iob$') and program:match('%.lua$') and fly2:match('%.fly2$')
  and local_config:match('%.lua$'),'IOB companion suffix is invalid')
local seed_directory=seed:match('^(.*[\\/])') or ''
for index=1,8 do
  local placeholder=seed_directory..string.format('iob_seed_placeholder_%02d.pa0',index)
  local handle=assert(io.open(placeholder,'rb'),'eight-instance seed companion is missing: '..placeholder)
  handle:close()
end
local wb=assert(simion.wb,'SIMION 2020 did not create an empty Workbench object')
assert(wb.load,'SIMION 2020 Workbench API lacks the supported IOB load method')
wb:load(seed)
assert(wb.filename and #wb.instances==8,'eight-instance seed must contain exactly eight PA instances')
for index,path in ipairs(paths) do
  local instance=wb.instances[index]
  instance.pa:load(path)
  assert(instance._debug_update_size,'SIMION 2020 instance-size refresh unavailable')
  instance:_debug_update_size()
  instance.x,instance.y,instance.z=origins[index][1],origins[index][2],origins[index][3]
  instance.az,instance.el,instance.rt,instance.scale=0,0,0,1
end
wb:save(output)
local function copy(source,target)
  if source==target then return end
  local i=assert(io.open(source,'rb')); local payload=i:read('*a'); i:close()
  local o=assert(io.open(target,'wb')); o:write(payload); o:close()
end
copy(program,output:gsub('%.iob$','.lua'))
copy(fly2,output:gsub('%.iob$','.fly2'))
copy(program:gsub('%.lua$','.operating_point.lua'),output:gsub('%.iob$','.operating_point.lua'))
copy(program:gsub('%.lua$','.voltage_map.lua'),output:gsub('%.iob$','.voltage_map.lua'))
copy(program:gsub('%.lua$','.mirror_cycle_counter.lua'),output:gsub('%.iob$','.mirror_cycle_counter.lua'))
copy(local_config,output:gsub('%.iob$','.local_refinement.lua'))
print('MRTOF_LOCAL_REFINEMENT_IOB_BUILD=PASS instances=8')
