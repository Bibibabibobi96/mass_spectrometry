-- Assemble the existing global fallback, five mirror-only local replacements,
-- and out-of-path accelerator/detector instances for the component diagnostic.
-- Usage matches build_local_refinement_iob.lua through LOCAL_CONFIG, followed
-- by (X Y Z)*8 and a probe-contract Lua sidecar.
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
    origins[index][axis]=assert(tonumber(input(13+(index-1)*3+axis,'origin')))
  end
end
local probe=input(38,'probe sidecar')
assert(seed:match('8_instance_seed%.iob$'),'repository eight-instance seed required')
local wb=assert(simion.wb,'SIMION Workbench object missing')
wb:load(seed)
assert(#wb.instances==8,'seed must contain eight instances')
for index,path in ipairs(paths) do
  local instance=wb.instances[index]
  instance.pa:load(path)
  instance:_debug_update_size()
  instance.x,instance.y,instance.z=origins[index][1],origins[index][2],origins[index][3]
  instance.az,instance.el,instance.rt,instance.scale=0,0,0,1
end
wb:save(output)
local function copy(source,target)
  local i=assert(io.open(source,'rb')); local payload=i:read('*a'); i:close()
  local o=assert(io.open(target,'wb')); o:write(payload); o:close()
end
copy(program,output:gsub('%.iob$','.lua'))
copy(fly2,output:gsub('%.iob$','.fly2'))
copy(local_config,output:gsub('%.iob$','.local_refinement.lua'))
copy(probe,output:gsub('%.iob$','.probe.lua'))
print('MRTOF_MIRROR_PERIOD_IOB_BUILD=PASS instances=8')
