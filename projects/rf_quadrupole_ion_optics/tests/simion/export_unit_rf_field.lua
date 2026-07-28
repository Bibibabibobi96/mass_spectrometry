-- Export the refined official PA's unit RF field in PA/COMSOL coordinates.
-- The field is static: electrode 1 = +100 V and electrode 2 = -100 V.

local iob_path = os.getenv('RFQUAD_SIMION_IOB')
local pa_path = os.getenv('RFQUAD_SIMION_PA_PATH')
assert((iob_path and iob_path ~= '') or (pa_path and pa_path ~= ''),
  'RFQUAD_SIMION_IOB or RFQUAD_SIMION_PA_PATH must be set')
local output_path = assert(os.getenv('RFQUAD_SIMION_UNIT_RF_FIELD_CSV'), 'RFQUAD_SIMION_UNIT_RF_FIELD_CSV is not set')
local report_path = assert(os.getenv('RFQUAD_SIMION_UNIT_RF_FIELD_REPORT'), 'RFQUAD_SIMION_UNIT_RF_FIELD_REPORT is not set')

local function required_number(name)
  return assert(tonumber(os.getenv(name)), name .. ' must be set to a number')
end

local x_min = required_number('RFQUAD_FIELD_X_MIN_MM')
local x_max = required_number('RFQUAD_FIELD_X_MAX_MM')
local y_min = required_number('RFQUAD_FIELD_Y_MIN_MM')
local y_max = required_number('RFQUAD_FIELD_Y_MAX_MM')
local z_min = required_number('RFQUAD_FIELD_Z_MIN_MM')
local z_max = required_number('RFQUAD_FIELD_Z_MAX_MM')
local step = required_number('RFQUAD_FIELD_STEP_MM')
assert(step > 0, 'RFQUAD_FIELD_STEP_MM must be positive')

local pa, instance
if pa_path and pa_path ~= '' then
  pa = assert(simion.pas:open(pa_path), 'quadrupole PA cannot be opened')
else
  simion.command('"' .. iob_path:gsub('"', '\\"') .. '"')
  instance = assert(simion.wb.instances[1], 'quadrupole PA instance is absent')
  pa = instance.pa
end
pa:fast_adjust{[1]=100,[2]=-100,[3]=0,[4]=0,[5]=0}

local output = assert(io.open(output_path, 'w'))
local report = assert(io.open(report_path, 'w'))
output:write('x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n')
local count = 0
for z = z_min, z_max + step*1e-6, step do
  for y = y_min, y_max + step*1e-6, step do
    for x = x_min, x_max + step*1e-6, step do
      -- PA/COMSOL x,y,z -> IOB workbench z,-y,x, then PA grid coordinates.
      local xg, yg, zg
      if instance then
        xg, yg, zg = instance:wb_to_pa_coords(z, -y, x)
      else
        xg, yg, zg = x/pa.dx_mm, y/pa.dy_mm, z/pa.dz_mm
      end
      local ex, ey, ez = pa:field_vc(xg, yg, zg)
      local scale = instance and instance.scale or 1
      ex = 1000*(ex or 0)/(pa.dx_mm*scale)
      ey = 1000*(ey or 0)/(pa.dy_mm*scale)
      ez = 1000*(ez or 0)/(pa.dz_mm*scale)
      output:write(string.format('%.12g,%.12g,%.12g,%.12g,%.12g,%.12g\n', x, y, z, ex, ey, ez))
      count = count + 1
    end
  end
end
output:close()
report:write(string.format('ROWS=%d\nRANGE_X_MM=%.12g,%.12g\nRANGE_Y_MM=%.12g,%.12g\nRANGE_Z_MM=%.12g,%.12g\nSTEP_MM=%.12g\nSTATUS=PASS\n', count, x_min, x_max, y_min, y_max, z_min, z_max, step))
report:close()
