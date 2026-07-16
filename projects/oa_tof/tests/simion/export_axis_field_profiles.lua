local output_path = assert(os.getenv('OATOF_SIMION_FIELD_CSV'),
  'OATOF_SIMION_FIELD_CSV is not set')
local report_path = assert(os.getenv('OATOF_SIMION_FIELD_REPORT'),
  'OATOF_SIMION_FIELD_REPORT is not set')
local output = assert(io.open(output_path, 'w'))
local report = assert(io.open(report_path, 'w'))

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

local function sample(region, instance_index, x_mm, z_start, z_step, count, component)
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

sample('accelerator_source',2,-48.8,0.2,0.01,261,3)
sample('accelerator_full',2,-48.8,3.2,0.05,329,3)
sample('reflectron',1,0,620.08,0.25,827,1)
report:write('STATUS=PASS\n')
output:close()
report:close()
