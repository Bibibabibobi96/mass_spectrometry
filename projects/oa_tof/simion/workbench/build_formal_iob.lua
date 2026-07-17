local resolved_path=assert(arg[1], 'usage: build_formal_iob.lua RESOLVED_LUA OUTPUT_IOB TEMPLATE_IOB PROGRAM FLY2')
local output=assert(arg[2], 'output IOB is required')
local template=assert(arg[3], 'template IOB is required')
local program_source=assert(arg[4], 'formal Program is required')
local fly2_source=assert(arg[5], 'formal Fly2 is required')
local contract=assert(dofile(resolved_path), 'resolved contract did not return a table')
local instances=assert(contract.derived.simion_instances, 'resolved SIMION instances are missing')
assert(#instances==4, 'resolved contract must define four SIMION instances')
local f=output:match('^(.*[\\/])') or ''
local reflectron_pa=f..'reflectron.pa0'
local accelerator_pa=f..'accelerator.pa0'
local flight_tube_pa=f..'flight_tube_ground.pa0'
local detector_pa=f..'detector_ground.pa0'
local function read_file(path,label)
  local input=assert(io.open(path,'rb'),'cannot open '..label..': '..path)
  local content=input:read('*a')
  input:close()
  return content
end
local function write_file(path,content,label)
  local output_file=assert(io.open(path,'wb'),'cannot write '..label..': '..path)
  output_file:write(content)
  output_file:close()
end
-- wb:save may create minimal same-basename sidecars. Read the complete Program
-- and GUI release definition before saving, then restore both beside the IOB.
-- The Program segment.load contract makes the Particles-tab T.Qual visible as
-- 8 immediately on every IOB load and reapplies it before every Fly'm.
local program_content=read_file(program_source,'formal Program')
local fly2_content=read_file(fly2_source,'GUI particle definition')
assert(program_content:match('adjustable%s+trajectory_quality%s*=%s*'..contract.simion_runtime.trajectory_quality),
  'formal Program trajectory_quality differs from resolved contract')
assert(program_content:match('function%s+segment%.load%s*%(') and
       program_content:match('sim_trajectory_quality%s*=%s*trajectory_quality'),
  'formal Program must set GUI T.Qual during segment.load')
assert(fly2_content:match('standard_beam%s*{'),
  'GUI particle definition must contain standard_beam')
simion.command('"' .. template .. '"')
local wb=simion.wb
assert(#wb.instances == 4, 'formal template must contain exactly four PA instances')
local r,a,t,d=wb.instances[1],wb.instances[2],wb.instances[3],wb.instances[4]
r.pa:load(reflectron_pa); r:_debug_update_size()
a.pa:load(accelerator_pa); a:_debug_update_size()
t.pa:load(flight_tube_pa); t:_debug_update_size()
d.pa:load(detector_pa); d:_debug_update_size()
local wb_instances={r,a,t,d}
for index,instance in ipairs(wb_instances) do
  local expected=instances[index]
  instance.x,instance.y,instance.z=expected.x_mm,expected.y_mm,expected.z_mm
  instance.az,instance.el,instance.rt,instance.scale=expected.az_deg,0,0,1
end
wb:save(output)
local program_output=output:gsub('%.[iI][oO][bB]$','.lua')
local fly2_output=output:gsub('%.[iI][oO][bB]$','.fly2')
assert(fly2_output~=output,'formal IOB output must end in .iob')
write_file(program_output,program_content,'same-basename formal Program')
write_file(fly2_output,fly2_content,'same-basename GUI particle definition')
