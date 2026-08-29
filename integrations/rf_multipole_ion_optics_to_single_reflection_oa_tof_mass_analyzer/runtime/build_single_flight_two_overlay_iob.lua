-- Build a runnable six-instance Candidate IOB with two local accelerator PAs.
--
-- The six-instance container is deliberately a GUI-created, run-local
-- Candidate input.  SIMION's Lua API can replace existing PA instances but
-- cannot add an instance to a four/five-slot IOB.  Every PA and every
-- physical transform is replaced below; the container supplies only the slot count.
--
-- Usage:
--   simion.exe --nogui --noprompt lua build_single_flight_two_overlay_iob.lua
--     formal.iob container6.iob output.iob flight.pa0 reflectron.pa0
--     accelerator.pa0 detector.pa0 entrance.pa0 intermediate.pa0
--     entrance_ox entrance_oy entrance_oz intermediate_ox intermediate_oy
--     intermediate_oz [program.lua particles.fly2]

local formal=assert(arg[1], 'formal IOB is required')
local container=assert(arg[2], 'six-instance container IOB is required')
local output=assert(arg[3], 'output IOB is required')
local pa_paths={
  assert(arg[4], 'flight-tube PA0 is required'),
  assert(arg[5], 'reflectron PA0 is required'),
  assert(arg[6], 'accelerator PA0 is required'),
  assert(arg[7], 'detector PA0 is required'),
  assert(arg[8], 'entrance overlay PA0 is required'),
  assert(arg[9], 'intermediate overlay PA0 is required'),
}
local entrance_origin={
  assert(tonumber(arg[10]), 'entrance overlay origin x is invalid'),
  assert(tonumber(arg[11]), 'entrance overlay origin y is invalid'),
  assert(tonumber(arg[12]), 'entrance overlay origin z is invalid'),
}
local intermediate_origin={
  assert(tonumber(arg[13]), 'intermediate overlay origin x is invalid'),
  assert(tonumber(arg[14]), 'intermediate overlay origin y is invalid'),
  assert(tonumber(arg[15]), 'intermediate overlay origin z is invalid'),
}
local program_path=arg[16]
local fly2_path=arg[17]
assert((program_path==nil)==(fly2_path==nil),
  'same-basename Program and Fly2 must either both be supplied or both be omitted')

local function read_file(path,label)
  local handle=io.open(path,'rb')
  if not handle then return nil end
  local content=handle:read('*a')
  handle:close()
  return content
end

local function write_file(path,content,label)
  if content==nil then return end
  local handle=assert(io.open(path,'wb'),'cannot restore '..label..': '..path)
  handle:write(content)
  handle:close()
end

local program=program_path and read_file(program_path,'Program') or nil
local fly2=fly2_path and read_file(fly2_path,'Fly2') or nil

-- Formal IOB remains the sole source of the four physical placements.
simion.command('"'..formal..'"')
assert(#simion.wb.instances==4 or #simion.wb.instances==5,
  'formal single-flight IOB must contain four or five instances')
local transforms={}
for index=1,4 do
  local item=simion.wb.instances[index]
  transforms[index]={
    x=item.x,y=item.y,z=item.z,az=item.az,el=item.el,rt=item.rt,
    scale=item.scale,nz_use=item.nz_use,
  }
end

simion.command('"'..container..'"')
assert(#simion.wb.instances==6,'SIMION container must contain exactly six instances')
for index=1,6 do
  local item=simion.wb.instances[index]
  item.pa:load(pa_paths[index])
  item:_debug_update_size()
  local transform=transforms[index] or ((index==5) and {
    x=entrance_origin[1],y=entrance_origin[2],z=entrance_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  } or {
    x=intermediate_origin[1],y=intermediate_origin[2],z=intermediate_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  })
  item.x,item.y,item.z=transform.x,transform.y,transform.z
  item.az,item.el,item.rt,item.scale=transform.az,transform.el,transform.rt,transform.scale
  if item.pa.nz==1 and transform.nz_use~=nil then item.nz_use=transform.nz_use end
end
simion.wb:save(output)
if program_path then
  write_file(program_path,program,'Program')
  write_file(fly2_path,fly2,'Fly2')
end
print(string.format(
  'SINGLE_FLIGHT_TWO_OVERLAY_IOB=PASS INSTANCES=%d ENTRANCE_ORIGIN=(%.12g,%.12g,%.12g) INTERMEDIATE_ORIGIN=(%.12g,%.12g,%.12g)',
  #simion.wb.instances,entrance_origin[1],entrance_origin[2],entrance_origin[3],
  intermediate_origin[1],intermediate_origin[2],intermediate_origin[3]))
