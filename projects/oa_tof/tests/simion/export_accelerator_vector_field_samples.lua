local input_path = assert(os.getenv('OATOF_ACCELERATOR_SAMPLE_CSV'))
local output_path = assert(os.getenv('OATOF_SIMION_VECTOR_FIELD_CSV'))
local report_path = assert(os.getenv('OATOF_SIMION_VECTOR_FIELD_REPORT'))
local iob_path = assert(os.getenv('OATOF_FORMAL_IOB_PATH'))

simion.command('"' .. iob_path .. '"')
local instance = assert(simion.wb.instances[3], 'accelerator instance is absent')
local input = assert(io.open(input_path, 'r'))
local output = assert(io.open(output_path, 'w'))
local report = assert(io.open(report_path, 'w'))
local header = assert(input:read('*l'))
local columns = {}
local index = 0
for name in string.gmatch(header, '[^,]+') do
  index = index + 1
  columns[name] = index
end
for _,name in ipairs({'particle_id','time_us','x_mm','y_mm','z_mm'}) do
  assert(columns[name], 'missing coordinate column ' .. name)
end
output:write('particle_id,time_us,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n')
local count = 0
for line in input:lines() do
  local values = {}
  for value in string.gmatch(line, '[^,]+') do values[#values+1] = value end
  local time_us = tonumber(values[columns.time_us])
  local z_mm = tonumber(values[columns.z_mm])
  if time_us <= 2 and z_mm <= 19.6 then
    local x_mm = tonumber(values[columns.x_mm])
    local y_mm = tonumber(values[columns.y_mm])
    local xg,yg,zg = instance:wb_to_pa_coords(x_mm,y_mm,z_mm)
    local ex,ey,ez = instance.pa:field_vc(xg,yg,zg)
    ex = 1000*(ex or 0)/(instance.pa.dx_mm*instance.scale)
    ey = 1000*(ey or 0)/(instance.pa.dy_mm*instance.scale)
    ez = 1000*(ez or 0)/(instance.pa.dz_mm*instance.scale)
    output:write(string.format('%s,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g\n',
      values[columns.particle_id],time_us,x_mm,y_mm,z_mm,ex,ey,ez))
    count = count + 1
  end
end
input:close()
output:close()
report:write(string.format('EXPORTED_ROWS=%d\nSTATUS=PASS\n',count))
report:close()
