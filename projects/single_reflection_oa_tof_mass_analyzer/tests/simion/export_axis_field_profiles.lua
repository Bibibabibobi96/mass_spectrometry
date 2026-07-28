local output_path = assert(os.getenv('OATOF_SIMION_FIELD_CSV'),
  'OATOF_SIMION_FIELD_CSV is not set')
local report_path = assert(os.getenv('OATOF_SIMION_FIELD_REPORT'),
  'OATOF_SIMION_FIELD_REPORT is not set')
local output = assert(io.open(output_path, 'w'))
local report = assert(io.open(report_path, 'w'))
local function required_number(name)
  return assert(tonumber(os.getenv(name)), name .. ' is not set')
end
local accelerator_axis_x = required_number('OATOF_ACCELERATOR_AXIS_X_MM')
local reflectron_axis_x = required_number('OATOF_REFLECTRON_AXIS_X_MM')
local source_z_min = required_number('OATOF_SOURCE_Z_MIN_MM')
local source_z_max = required_number('OATOF_SOURCE_Z_MAX_MM')
local accelerator_z_min = required_number('OATOF_ACCELERATOR_SAMPLE_Z_MIN_MM')
local accelerator_z_max = required_number('OATOF_ACCELERATOR_SAMPLE_Z_MAX_MM')
local reflectron_z_min = required_number('OATOF_REFLECTRON_SAMPLE_Z_MIN_MM')
local reflectron_z_max = required_number('OATOF_REFLECTRON_SAMPLE_Z_MAX_MM')

local iob_path = os.getenv('OATOF_FORMAL_IOB_PATH') or 'oatof_ideal_grounded.iob'
simion.command('"' .. iob_path .. '"')
local wb = simion.wb
assert(#wb.instances == 4, 'formal IOB must contain exactly four PA instances')
output:write('region,sample_index,x_mm,y_mm,z_mm,Ez_V_per_m\n')

local function global_ez_vpm(instance_index, x_mm, y_mm, z_mm, local_component)
  local instance = wb.instances[instance_index]
  local xg,yg,zg = instance:wb_to_pa_coords(x_mm,y_mm,z_mm)
  local ex,ey,ez = instance.pa:field_vc(xg,yg,zg)
  local values = {
    (ex or 0)/(instance.pa.dx_mm*instance.scale),
    (ey or 0)/(instance.pa.dy_mm*instance.scale),
    (ez or 0)/(instance.pa.dz_mm*instance.scale),
  }
  return 1000*values[local_component]
end

local function sample(region, instance_index, x_mm, z_start, z_end, z_step, component)
  local count=math.floor((z_end-z_start)/z_step+0.5)+1
  local minimum,maximum
  for index=1,count do
    local z_mm = z_start+(index-1)*z_step
    local field = global_ez_vpm(instance_index,x_mm,0,z_mm,component)
    output:write(string.format('%s,%d,%.12g,0,%.12g,%.15g\n',
      region,index,x_mm,z_mm,field))
    minimum = not minimum and field or math.min(minimum,field)
    maximum = not maximum and field or math.max(maximum,field)
  end
  report:write(string.format('%s_POINTS=%d\n',string.upper(region),count))
  report:write(string.format('%s_EZ_MIN_MAX_V_PER_M=%.15g,%.15g\n',
    string.upper(region),minimum,maximum))
end

sample('accelerator_source',2,accelerator_axis_x,source_z_min,source_z_max,0.01,3)
sample('accelerator_full',2,accelerator_axis_x,accelerator_z_min,accelerator_z_max,0.05,3)
sample('reflectron',1,reflectron_axis_x,reflectron_z_min,reflectron_z_max,0.25,1)
report:write('STATUS=PASS\n')
output:close()
report:close()
