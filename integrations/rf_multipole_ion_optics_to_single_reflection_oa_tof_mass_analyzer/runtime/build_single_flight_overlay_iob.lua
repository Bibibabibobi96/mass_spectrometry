-- Build a GUI-visible five-instance workbench from a SIMION-distributed
-- five-instance container.  SIMION 8.2 exposes PA replacement and positioning
-- but does not expose an API for adding a new instance to a four-instance IOB.
-- Usage:
--   simion.exe --nogui --noprompt lua build_single_flight_overlay_iob.lua
--     formal.iob container5.iob output.iob
--     flight.pa0 reflectron.pa0 accelerator.pa0 detector.pa0 overlay.pa0
--     overlay_ox overlay_oy overlay_oz [program.lua particles.fly2]
--
-- The optional same-basename Program/Fly2 arguments preserve the normal
-- runnable IOB contract.  A field-only IOB deliberately omits them: SIMION
-- otherwise auto-loads the Workbench Program while a top-level Lua diagnostic
-- is sampling the static total field.

local formal=assert(arg[1], 'formal IOB is required')
local container=assert(arg[2], 'five-instance container IOB is required')
local output=assert(arg[3], 'output IOB is required')
local pa_paths={
  assert(arg[4], 'flight-tube PA0 is required'),
  assert(arg[5], 'reflectron PA0 is required'),
  assert(arg[6], 'accelerator PA0 is required'),
  assert(arg[7], 'detector PA0 is required'),
  assert(arg[8], 'overlay PA0 is required'),
}
local overlay_origin={
  assert(tonumber(arg[9]), 'overlay origin x is invalid'),
  assert(tonumber(arg[10]), 'overlay origin y is invalid'),
  assert(tonumber(arg[11]), 'overlay origin z is invalid'),
}
local program_path=arg[12]
local fly2_path=arg[13]
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

-- Read only the documented positioning properties from the governed formal IOB.
-- The first build starts from the four-instance Formal IOB.  The field-only
-- diagnostic is rebuilt from that already constructed five-instance IOB so it
-- inherits the exact physical transforms but deliberately drops the fifth
-- instance's Program/Fly2 basename association.  In both cases only the first
-- four physical instances supply transforms; the overlay transform remains the
-- governed explicit argument below.
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

-- The distributed example is used only as a binary five-instance container;
-- every PA and every physical transform is replaced before saving.
simion.command('"'..container..'"')
assert(#simion.wb.instances==5,'SIMION container must contain exactly five instances')
for index=1,5 do
  local item=simion.wb.instances[index]
  item.pa:load(pa_paths[index])
  item.pa.filename=pa_paths[index]
  item:_debug_update_size()
  local transform=index<=4 and transforms[index] or {
    x=overlay_origin[1],y=overlay_origin[2],z=overlay_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  }
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
  'SINGLE_FLIGHT_OVERLAY_IOB=PASS INSTANCES=%d OVERLAY_ORIGIN=(%.12g,%.12g,%.12g)',
  #simion.wb.instances,overlay_origin[1],overlay_origin[2],overlay_origin[3]))
